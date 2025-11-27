from flask import render_template, request, session, redirect, url_for, flash
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
from . import central_bp
from .central_utils import (
    get_eligible_users, 
    get_current_quarter, 
    get_quarter_date_range,
    get_quarters_in_year, 
    get_reward_config,
    check_central_access
)
from .central_batch_utils import (
    batch_calculate_utilization,
    batch_calculate_yearly_bonus
)

def get_merged_categories():
    """Get categories from both collections and merge by name - OPTIMIZED"""
    merged_categories = {}
    
    # Bulk fetch with minimal projection
    old_categories = list(mongo.db.categories.find({}, {'name': 1, 'code': 1}))
    hr_categories = list(mongo.db.hr_categories.find({}, {'name': 1, 'category_code': 1}))
    
    # Build lookup dictionaries
    id_to_name = {}
    
    for cat in old_categories:
        cat_name = cat.get('name', '')
        if cat_name:
            merged_categories[cat_name] = {
                'name': cat_name,
                'code': cat.get('code', ''),
                'ids': [cat['_id']]
            }
            id_to_name[cat['_id']] = cat_name
    
    for cat in hr_categories:
        cat_name = cat.get('name', '')
        if cat_name:
            if cat_name in merged_categories:
                merged_categories[cat_name]['ids'].append(cat['_id'])
                merged_categories[cat_name]['code'] = cat.get('category_code', merged_categories[cat_name]['code'])
            else:
                merged_categories[cat_name] = {
                    'name': cat_name,
                    'code': cat.get('category_code', ''),
                    'ids': [cat['_id']]
                }
            id_to_name[cat['_id']] = cat_name
    
    return merged_categories, id_to_name

def get_effective_date_fast(entry):
    """Fast effective date extraction with fallback"""
    for field in ['event_date', 'request_date', 'award_date', 'response_date']:
        date_val = entry.get(field)
        if date_val and isinstance(date_val, datetime):
            return date_val
    return None

@central_bp.route('/leaderboard', methods=['GET'])
def leaderboard():
    """OPTIMIZED Employee and Manager leaderboard with dual collection support"""
    # Check dashboard access
    has_access, user = check_central_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        
        # Get filter parameters
        selected_quarter = request.args.get('quarter', '')
        selected_category = request.args.get('category', '')
        include_bonus = request.args.get('include_bonus', 'false') == 'true'
        grade_filter = request.args.get('grade', '')
        role_filter = request.args.get('role', '')
        
        # Get quarter info
        current_qtr_name, current_qtr, current_year = get_current_quarter()
        
        if not selected_quarter:
            selected_quarter = current_qtr_name
        
        quarters = get_quarters_in_year(current_year)
        
        # Parse selected quarter
        selected_q_num = int(selected_quarter[1])
        selected_year = int(selected_quarter[3:])
        qtr_start, qtr_end = get_quarter_date_range(selected_q_num, selected_year)
        
        # Get merged categories ONCE
        merged_categories, id_to_name = get_merged_categories()
        
        # Find utilization category IDs
        utilization_ids = []
        for cat_name, cat_info in merged_categories.items():
            if cat_info.get('code') == 'utilization_billable':
                utilization_ids.extend(cat_info['ids'])
        
        # Get all eligible users with minimal fields
        all_users = list(mongo.db.users.find({
            "$or": [
                {"role": "Employee"},
                {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
            ]
        }, {
            'name': 1,
            'email': 1,
            'grade': 1,
            'department': 1,
            'role': 1,
            'manager_id': 1
        }))
        
        # Apply grade/role filters
        if grade_filter:
            all_users = [u for u in all_users if u.get('grade') == grade_filter]
        
        if role_filter:
            all_users = [u for u in all_users if u.get('role') == role_filter]
        
        user_ids = [u['_id'] for u in all_users]
        user_lookup = {str(u['_id']): u for u in all_users}
        
        # Get config
        config = get_reward_config()
        grade_targets = config.get("grade_targets", {})
        
        # ==========================================
        # BULK FETCH ALL DATA AT ONCE
        # ==========================================
        
        # Build date query
        date_query = {
            "$or": [
                {"event_date": {"$gte": qtr_start, "$lte": qtr_end}},
                {"request_date": {"$gte": qtr_start, "$lte": qtr_end}},
                {"award_date": {"$gte": qtr_start, "$lte": qtr_end}},
                {"response_date": {"$gte": qtr_start, "$lte": qtr_end}}
            ]
        }
        
        # Build base query
        base_query = {
            "user_id": {"$in": user_ids},
            "status": "Approved",
            **date_query
        }
        
        # Add category filter if selected
        if selected_category:
            try:
                base_query["category_id"] = ObjectId(selected_category)
            except:
                pass
        
        # Fetch points_request data
        points_request_data = list(mongo.db.points_request.find(base_query, {
            'user_id': 1,
            'category_id': 1,
            'points': 1,
            'is_bonus': 1,
            'event_date': 1,
            'request_date': 1,
            'response_date': 1,
            'award_date': 1,
            '_id': 1
        }))
        
        # Fetch points (historical) data
        points_data = list(mongo.db.points.find({
            "user_id": {"$in": user_ids},
            **date_query
        }, {
            'user_id': 1,
            'category_id': 1,
            'points': 1,
            'is_bonus': 1,
            'event_date': 1,
            'request_date': 1,
            'award_date': 1,
            'request_id': 1
        }))
        
        # Track processed request IDs to avoid double counting
        processed_request_ids = {req['_id'] for req in points_request_data}
        
        # ==========================================
        # PROCESS DATA IN MEMORY (MUCH FASTER)
        # ==========================================
        
        leaderboard_data = {}
        
        # Initialize all users
        for user_id_obj in user_ids:
            uid_str = str(user_id_obj)
            user_info = user_lookup.get(uid_str)
            
            if not user_info:
                continue
            
            leaderboard_data[uid_str] = {
                "id": uid_str,
                "name": user_info.get("name", "Unknown"),
                "email": user_info.get("email", ""),
                "grade": user_info.get("grade", "Unknown"),
                "department": user_info.get("department", ""),
                "role": user_info.get("role", "Employee"),
                "manager_id": user_info.get("manager_id"),
                "total_points": 0,
                "bonus_points": 0,
                "regular_points": 0,
                "categories_breakdown": {},
                "rank": 0,
                "progress": 0,
                "utilization": 0,
                "yearly_bonus_points": 0
            }
        
        # Process points_request
        for req in points_request_data:
            effective_date = get_effective_date_fast(req)
            if not effective_date or not (qtr_start <= effective_date <= qtr_end):
                continue
            
            uid_str = str(req['user_id'])
            if uid_str not in leaderboard_data:
                continue
            
            category_id = req.get('category_id')
            
            # Skip utilization
            if category_id in utilization_ids:
                continue
            
            # Get category name
            category_name = id_to_name.get(category_id, 'Unknown')
            
            points_value = req.get('points', 0)
            is_bonus = req.get('is_bonus', False)
            
            # Update totals
            if is_bonus:
                leaderboard_data[uid_str]['bonus_points'] += points_value
                if include_bonus:
                    leaderboard_data[uid_str]['total_points'] += points_value
            else:
                leaderboard_data[uid_str]['regular_points'] += points_value
                leaderboard_data[uid_str]['total_points'] += points_value
            
            # Update category breakdown
            if category_name not in leaderboard_data[uid_str]['categories_breakdown']:
                leaderboard_data[uid_str]['categories_breakdown'][category_name] = {
                    'name': category_name,
                    'points': 0
                }
            leaderboard_data[uid_str]['categories_breakdown'][category_name]['points'] += points_value
        
        # Process historical points (skip if already in points_request)
        for pt in points_data:
            request_id = pt.get('request_id')
            if request_id and request_id in processed_request_ids:
                continue
            
            effective_date = get_effective_date_fast(pt)
            if not effective_date or not (qtr_start <= effective_date <= qtr_end):
                continue
            
            uid_str = str(pt['user_id'])
            if uid_str not in leaderboard_data:
                continue
            
            category_id = pt.get('category_id')
            
            # Skip utilization from historical
            if category_id in utilization_ids:
                continue
            
            category_name = id_to_name.get(category_id, 'Unknown')
            
            points_value = pt.get('points', 0)
            is_bonus = pt.get('is_bonus', False)
            
            # Update totals
            if is_bonus:
                leaderboard_data[uid_str]['bonus_points'] += points_value
                if include_bonus:
                    leaderboard_data[uid_str]['total_points'] += points_value
            else:
                leaderboard_data[uid_str]['regular_points'] += points_value
                leaderboard_data[uid_str]['total_points'] += points_value
            
            # Update category breakdown
            if category_name not in leaderboard_data[uid_str]['categories_breakdown']:
                leaderboard_data[uid_str]['categories_breakdown'][category_name] = {
                    'name': category_name,
                    'points': 0
                }
            leaderboard_data[uid_str]['categories_breakdown'][category_name]['points'] += points_value
        
        # ==========================================
        # CALCULATE UTILIZATION & PROGRESS (BATCH OPTIMIZED)
        # ==========================================
        
        # BATCH CALCULATE UTILIZATION FOR ALL USERS AT ONCE
        utilization_map = batch_calculate_utilization(user_ids, qtr_start, qtr_end, utilization_ids)
        
        # BATCH CALCULATE YEARLY BONUS FOR ALL USERS AT ONCE
        yearly_bonus_map = batch_calculate_yearly_bonus(user_ids, selected_year)
        
        for uid_str, data in leaderboard_data.items():
            # Get pre-calculated utilization
            data['utilization'] = utilization_map.get(uid_str, 0)
            
            # Get pre-calculated yearly bonus points
            data['yearly_bonus_points'] = yearly_bonus_map.get(uid_str, 0)
            
            # Calculate progress
            user_grade = data['grade']
            quarterly_target = grade_targets.get(user_grade, 0)
            
            if quarterly_target > 0:
                data['progress'] = round((data['total_points'] / quarterly_target * 100), 1)
        
        # ==========================================
        # FILTER & SORT
        # ==========================================
        
        # Filter out users with no points
        final_leaderboard = [
            data for data in leaderboard_data.values()
            if data['total_points'] > 0 or (include_bonus and data['bonus_points'] > 0)
        ]
        
        # Sort by total points
        final_leaderboard.sort(key=lambda x: x['total_points'], reverse=True)
        
        # Assign ranks
        for i, emp in enumerate(final_leaderboard):
            emp['rank'] = i + 1
        
        # ==========================================
        # PREPARE FILTERS & CATEGORIES
        # ==========================================
        
        # Get unique grades and roles for filters
        all_grades = sorted(list(set(u.get('grade', 'Unknown') for u in all_users)))
        all_roles = sorted(list(set(u.get('role', 'Employee') for u in all_users)))
        
        # Convert merged categories for template
        categories_list = []
        for cat_name, cat_info in merged_categories.items():
            categories_list.append({
                'name': cat_name,
                'code': cat_info.get('code', ''),
                '_id': cat_info['ids'][0] if cat_info['ids'] else None
            })
        categories_list.sort(key=lambda x: x['name'])
        
        return render_template(
            'central_leaderboard.html',
            user=user,
            leaderboard=final_leaderboard,
            quarters=quarters,
            categories=categories_list,
            selected_quarter=selected_quarter,
            selected_category=selected_category,
            include_bonus=include_bonus,
            grade_filter=grade_filter,
            role_filter=role_filter,
            all_grades=all_grades,
            all_roles=all_roles,
            config=config
        )
        
    except Exception as e:
        import traceback

        flash('An error occurred while loading the leaderboard', 'danger')
        return redirect(url_for('central.dashboard'))