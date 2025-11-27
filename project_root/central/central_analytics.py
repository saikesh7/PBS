from flask import render_template, session, redirect, url_for, flash, request
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
from . import central_bp
from .central_utils import (
    get_eligible_users,
    get_current_quarter,
    get_quarter_date_range,
    get_quarters_in_year
)

def get_merged_categories():
    """Get categories from both collections and merge by name - OPTIMIZED"""
    merged_categories = {}
    
    # Bulk fetch with projection (only needed fields)
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

def get_fiscal_quarter_from_date(date):
    """Get fiscal quarter and year from date"""
    if not date:
        return None, None
    
    month = date.month
    year = date.year
    
    if 1 <= month <= 3:
        return 4, year - 1
    elif 4 <= month <= 6:
        return 1, year
    elif 7 <= month <= 9:
        return 2, year
    else:
        return 3, year

def get_effective_date_fast(entry):
    """Fast effective date extraction"""
    for field in ['event_date', 'request_date', 'award_date', 'response_date']:
        date_val = entry.get(field)
        if date_val and isinstance(date_val, datetime):
            return date_val
    return None

@central_bp.route('/analytics', methods=['GET'])
def analytics():
    """OPTIMIZED Analytics dashboard with bulk operations"""
    user_id = session.get('user_id')
    user_role = session.get('user_role')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    if user_role != 'Central':
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)}, {'name': 1})
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))
        
        # Get filter parameters
        selected_quarter = request.args.get('quarter', '')
        selected_year = request.args.get('year', '')
        
        # Get current quarter info
        current_qtr_name, current_qtr, current_year = get_current_quarter()
        
        # Determine the date range for analysis
        if selected_quarter and selected_year:
            q_num = int(selected_quarter)
            year = int(selected_year)
            analysis_start, analysis_end = get_quarter_date_range(q_num, year)
            analysis_label = f"Q{q_num}-{year}"
        else:
            analysis_start = datetime(current_year, 4, 1)
            analysis_end = datetime.now()
            analysis_label = f"FY {current_year}-{current_year + 1}"
        
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
            'department': 1,
            'grade': 1,
            'role': 1
        }))
        
        user_ids = [u['_id'] for u in all_users]
        user_lookup = {str(u['_id']): u for u in all_users}
        
        # ==========================================
        # BULK FETCH ALL DATA AT ONCE
        # ==========================================
        
        # Build date query
        date_query = {
            "$or": [
                {"event_date": {"$gte": analysis_start, "$lte": analysis_end}},
                {"request_date": {"$gte": analysis_start, "$lte": analysis_end}},
                {"award_date": {"$gte": analysis_start, "$lte": analysis_end}},
                {"response_date": {"$gte": analysis_start, "$lte": analysis_end}}
            ]
        }
        
        # Fetch points_request data
        points_request_data = list(mongo.db.points_request.find({
            "user_id": {"$in": user_ids},
            "status": "Approved",
            **date_query
        }, {
            'user_id': 1,
            'category_id': 1,
            'points': 1,
            'is_bonus': 1,
            'event_date': 1,
            'request_date': 1,
            'response_date': 1,
            'award_date': 1,
            'utilization_value': 1,
            'submission_notes': 1,
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
        
        employee_data = {}
        
        # Initialize all users
        for user_id_obj in user_ids:
            uid_str = str(user_id_obj)
            employee_data[uid_str] = {
                "total_points": 0,
                "bonus_points": 0,
                "regular_points": 0,
                "points_by_category": {},
                "points_by_quarter": {},
                "utilization_data": []
            }
        
        # Process points_request
        for req in points_request_data:
            effective_date = get_effective_date_fast(req)
            if not effective_date or not (analysis_start <= effective_date <= analysis_end):
                continue
            
            uid_str = str(req['user_id'])
            if uid_str not in employee_data:
                continue
            
            category_id = req.get('category_id')
            
            # Handle utilization
            if category_id in utilization_ids:
                utilization_value = req.get('utilization_value', 0)
                employee_data[uid_str]['utilization_data'].append({
                    'date': effective_date,
                    'value': utilization_value,
                    'notes': req.get('submission_notes', '')
                })
                continue
            
            # Get category name
            category_name = id_to_name.get(category_id, 'Unknown')
            category_code = merged_categories.get(category_name, {}).get('code', 'unknown')
            
            points_value = req.get('points', 0)
            is_bonus = req.get('is_bonus', False)
            
            # Update totals
            employee_data[uid_str]['total_points'] += points_value
            if is_bonus:
                employee_data[uid_str]['bonus_points'] += points_value
            else:
                employee_data[uid_str]['regular_points'] += points_value
            
            # Update category breakdown
            if category_name not in employee_data[uid_str]['points_by_category']:
                employee_data[uid_str]['points_by_category'][category_name] = {
                    'name': category_name,
                    'code': category_code,
                    'points': 0
                }
            employee_data[uid_str]['points_by_category'][category_name]['points'] += points_value
            
            # Update quarter breakdown
            quarter, fiscal_year = get_fiscal_quarter_from_date(effective_date)
            if quarter and fiscal_year:
                quarter_key = f"Q{quarter}-{fiscal_year}"
                if quarter_key not in employee_data[uid_str]['points_by_quarter']:
                    employee_data[uid_str]['points_by_quarter'][quarter_key] = 0
                employee_data[uid_str]['points_by_quarter'][quarter_key] += points_value
        
        # Process historical points (skip if already in points_request)
        for pt in points_data:
            request_id = pt.get('request_id')
            if request_id and request_id in processed_request_ids:
                continue
            
            effective_date = get_effective_date_fast(pt)
            if not effective_date or not (analysis_start <= effective_date <= analysis_end):
                continue
            
            uid_str = str(pt['user_id'])
            if uid_str not in employee_data:
                continue
            
            category_id = pt.get('category_id')
            
            # Skip utilization from historical
            if category_id in utilization_ids:
                continue
            
            category_name = id_to_name.get(category_id, 'Unknown')
            category_code = merged_categories.get(category_name, {}).get('code', 'unknown')
            
            points_value = pt.get('points', 0)
            is_bonus = pt.get('is_bonus', False)
            
            # Update totals
            employee_data[uid_str]['total_points'] += points_value
            if is_bonus:
                employee_data[uid_str]['bonus_points'] += points_value
            else:
                employee_data[uid_str]['regular_points'] += points_value
            
            # Update category breakdown
            if category_name not in employee_data[uid_str]['points_by_category']:
                employee_data[uid_str]['points_by_category'][category_name] = {
                    'name': category_name,
                    'code': category_code,
                    'points': 0
                }
            employee_data[uid_str]['points_by_category'][category_name]['points'] += points_value
            
            # Update quarter breakdown
            quarter, fiscal_year = get_fiscal_quarter_from_date(effective_date)
            if quarter and fiscal_year:
                quarter_key = f"Q{quarter}-{fiscal_year}"
                if quarter_key not in employee_data[uid_str]['points_by_quarter']:
                    employee_data[uid_str]['points_by_quarter'][quarter_key] = 0
                employee_data[uid_str]['points_by_quarter'][quarter_key] += points_value
        
        # ==========================================
        # BUILD FINAL OUTPUT
        # ==========================================
        
        employee_analytics_data = []
        
        for uid_str, data in employee_data.items():
            # Skip users with no data
            if data['total_points'] == 0 and not data['utilization_data']:
                continue
            
            user_info = user_lookup.get(uid_str)
            if not user_info:
                continue
            
            # Calculate average utilization
            if data['utilization_data']:
                avg_util = sum(u['value'] for u in data['utilization_data']) / len(data['utilization_data'])
                data['avg_utilization'] = round(avg_util * 100, 2)
            else:
                data['avg_utilization'] = 0
            
            employee_analytics_data.append({
                'id': uid_str,
                'name': user_info.get('name', 'Unknown'),
                'email': user_info.get('email', ''),
                'department': user_info.get('department', 'Unassigned'),
                'grade': user_info.get('grade', 'Unknown'),
                'role': user_info.get('role', 'Employee'),
                'points_data': data
            })
        
        # Sort by total points
        employee_analytics_data.sort(key=lambda x: x['points_data']['total_points'], reverse=True)
        
        # Get available quarters and years
        quarters = get_quarters_in_year(current_year)
        available_years = [current_year, current_year - 1, current_year - 2]
        
        # Convert categories for template
        categories_list = [
            {
                'name': cat_name,
                'code': cat_info.get('code', ''),
                '_id': cat_info['ids'][0] if cat_info['ids'] else None
            }
            for cat_name, cat_info in merged_categories.items()
        ]
        categories_list.sort(key=lambda x: x['name'])
        
        return render_template(
            'central_analytics.html',
            user=user,
            employees=employee_analytics_data,
            categories=categories_list,
            quarters=quarters,
            available_years=available_years,
            selected_quarter=selected_quarter,
            selected_year=selected_year,
            analysis_label=analysis_label,
            current_quarter=current_qtr_name
        )
        
    except Exception as e:
        import traceback

        flash('An error occurred while loading analytics', 'danger')
        return redirect(url_for('central.dashboard'))