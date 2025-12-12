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

def get_fiscal_quarter_from_date(date):
    """Get fiscal quarter number (1-4) from a date based on April-March fiscal year"""
    if not date or not isinstance(date, datetime):
        return None
    
    month = date.month
    # Fiscal year: April=Q1, July=Q2, October=Q3, January=Q4
    if 4 <= month <= 6:
        return 1
    elif 7 <= month <= 9:
        return 2
    elif 10 <= month <= 12:
        return 3
    else:  # 1-3 (Jan-Mar)
        return 4

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
    """Fast effective date extraction with fallback - MATCHES HR/Employee logic"""
    # Priority: event_date → request_date → award_date (same as HR Update Points)
    for field in ['event_date', 'request_date', 'award_date']:
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
        selected_year_param = request.args.get('year', '')
        selected_category = request.args.get('category', '')
        include_bonus = request.args.get('include_bonus', 'false') == 'true'
        grade_filter = request.args.get('grade', '')
        role_filter = request.args.get('role', '')
        
        # Get quarter info
        current_qtr_name, current_qtr, current_year = get_current_quarter()
        
        # Get available years from database (years with actual data)
        available_years = set()
        
        # Query points_request collection for years with data
        points_pipeline = [
            {
                "$match": {
                    "status": "Approved",
                    "$or": [
                        {"event_date": {"$exists": True, "$ne": None}},
                        {"request_date": {"$exists": True, "$ne": None}},
                        {"award_date": {"$exists": True, "$ne": None}}
                    ]
                }
            },
            {
                "$project": {
                    "year": {
                        "$year": {
                            "$ifNull": [
                                "$event_date",
                                {"$ifNull": ["$request_date", "$award_date"]}
                            ]
                        }
                    }
                }
            },
            {
                "$group": {
                    "_id": "$year"
                }
            },
            {
                "$sort": {"_id": -1}
            }
        ]
        
        years_with_data = list(mongo.db.points_request.aggregate(points_pipeline))
        for year_doc in years_with_data:
            if year_doc.get('_id'):
                available_years.add(year_doc['_id'])
        
        # Always include current year even if no data yet
        available_years.add(current_year)
        
        # Convert to sorted list (descending order - newest first)
        available_years = sorted(list(available_years), reverse=True)
        
        # ✅ NEW: Add "All Years" option at the beginning
        available_years.insert(0, 'all')
        
        # Determine selected year
        if selected_year_param and selected_year_param != 'all':
            selected_year = int(selected_year_param)
        elif selected_year_param == 'all':
            selected_year = 'all'
        else:
            selected_year = current_year
        
        # ✅ Get quarters based on selected year
        if selected_year == 'all':
            # For "All Years", show Q1, Q2, Q3, Q4 options (across all years)
            quarters = [
                {"name": "Q1-all", "quarter": 1, "start_date": None, "end_date": None},
                {"name": "Q2-all", "quarter": 2, "start_date": None, "end_date": None},
                {"name": "Q3-all", "quarter": 3, "start_date": None, "end_date": None},
                {"name": "Q4-all", "quarter": 4, "start_date": None, "end_date": None}
            ]
        else:
            # For specific year, get quarters for that year
            quarters = get_quarters_in_year(selected_year)
        
        # Add "All Quarters" option at the beginning
        if selected_year == 'all':
            # ✅ For "All Years", use all available data
            quarters.insert(0, {
                "name": "All-all",
                "start_date": datetime(1900, 1, 1),  # Very old date to include all data
                "end_date": datetime(2100, 12, 31, 23, 59, 59, 999999)  # Far future date
            })
        else:
            # ✅ FIXED: All Quarters should include Q4 data (Jan-Mar of next year)
            quarters.insert(0, {
                "name": f"All-{selected_year}",
                "start_date": datetime(selected_year, 4, 1),  # Fiscal year starts in April
                "end_date": datetime(selected_year + 1, 3, 31, 23, 59, 59, 999999)  # Ends in March next year
            })
        
        # If no quarter selected or quarter doesn't match year, use All Quarters
        if not selected_quarter:
            if selected_year == 'all':
                selected_quarter = "All-all"
            else:
                selected_quarter = f"All-{selected_year}"
        elif selected_year != 'all' and not selected_quarter.endswith(str(selected_year)):
            selected_quarter = f"All-{selected_year}"
        
        # Parse selected quarter and get date range
        selected_q_num = None  # Track quarter number for cross-year filtering
        
        if selected_quarter == "All-all" or (selected_year == 'all' and selected_quarter.startswith("All-")):
            # ✅ All years, all quarters - use all available data
            qtr_start = datetime(1900, 1, 1)
            qtr_end = datetime(2100, 12, 31, 23, 59, 59, 999999)
            is_all_quarters = True
        elif selected_quarter.endswith("-all") and selected_year == 'all':
            # ✅ Specific quarter across all years (e.g., Q1-all, Q2-all)
            selected_q_num = int(selected_quarter[1])
            # Use wide date range, will filter by quarter number in post-processing
            qtr_start = datetime(1900, 1, 1)
            qtr_end = datetime(2100, 12, 31, 23, 59, 59, 999999)
            is_all_quarters = False
        elif selected_quarter.startswith("All-") and selected_year != 'all':
            # ✅ FIXED: All quarters selected for specific year - use full FISCAL year (Apr to Mar next year)
            qtr_start = datetime(selected_year, 4, 1)  # April 1st
            qtr_end = datetime(selected_year + 1, 3, 31, 23, 59, 59, 999999)  # March 31st next year
            is_all_quarters = True
        elif selected_year != 'all':
            # Specific quarter selected for specific year
            selected_q_num = int(selected_quarter[1])
            qtr_start, qtr_end = get_quarter_date_range(selected_q_num, selected_year)
            is_all_quarters = False
        else:
            # Fallback: All years, all data
            qtr_start = datetime(1900, 1, 1)
            qtr_end = datetime(2100, 12, 31, 23, 59, 59, 999999)
            is_all_quarters = True
        
        # Get merged categories ONCE
        merged_categories, id_to_name = get_merged_categories()
        
        # Find utilization category IDs
        utilization_ids = []
        for cat_name, cat_info in merged_categories.items():
            if cat_info.get('code') == 'utilization_billable':
                utilization_ids.extend(cat_info['ids'])
        
        # Get all eligible users with minimal fields
        # ✅ FIXED: Get ALL employees and ALL managers (including top-level managers)
        all_users = list(mongo.db.users.find({
            "role": {"$in": ["Employee", "Manager"]}
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
        
        # Build base query - MATCHES HR Analytics logic
        base_query = {
            "user_id": {"$in": user_ids},
            "status": "Approved"
        }
        
        # ✅ ONLY add date filter if NOT viewing "All Years, All Quarters"
        # This matches HR Analytics behavior which doesn't filter by date when no dates provided
        if not (selected_quarter == "All-all" or (selected_year == 'all' and selected_quarter.startswith("All-"))):
            base_query["$or"] = [
                {"event_date": {"$gte": qtr_start, "$lte": qtr_end}},
                {"request_date": {"$gte": qtr_start, "$lte": qtr_end}},
                {"award_date": {"$gte": qtr_start, "$lte": qtr_end}}
            ]
        
        # ✅ Add category filter if selected - handle both single ID and merged category IDs
        selected_category_ids = []
        selected_category_name = ""
        if selected_category:
            try:
                # Try to find the category in merged categories
                for cat_name, cat_info in merged_categories.items():
                    if str(cat_info['ids'][0]) == selected_category:
                        selected_category_ids = cat_info['ids']
                        selected_category_name = cat_name
                        break
                
                # If not found in merged, use the ID directly
                if not selected_category_ids:
                    selected_category_ids = [ObjectId(selected_category)]
                
                base_query["category_id"] = {"$in": selected_category_ids}
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
        
        # ✅ REMOVED: No longer fetching from points collection (historical data)
        # Only use points_request collection for consistency with analytics and export
        
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
            # ✅ Get effective date for all records (needed for quarter filtering)
            effective_date = get_effective_date_fast(req)
            
            # ✅ ONLY do date double-check if NOT viewing "All Years, All Quarters" - matches HR Analytics
            if not (selected_quarter == "All-all" or (selected_year == 'all' and selected_quarter.startswith("All-"))):
                if not effective_date or not (qtr_start <= effective_date <= qtr_end):
                    continue
            
            # ✅ Additional filtering for specific quarter across all years (Q1-all, Q2-all, etc.)
            if selected_q_num is not None and selected_year == 'all':
                if effective_date:
                    req_quarter = get_fiscal_quarter_from_date(effective_date)
                    if req_quarter != selected_q_num:
                        continue
            
            uid_str = str(req['user_id'])
            if uid_str not in leaderboard_data:
                continue
            
            category_id = req.get('category_id')
            
            # Skip utilization
            if category_id in utilization_ids:
                continue
            
            # ✅ If category filter is active, skip points from other categories
            if selected_category_ids and category_id not in selected_category_ids:
                continue
            
            # Get category name
            category_name = id_to_name.get(category_id, 'Unknown')
            
            points_value = req.get('points', 0)
            is_bonus = req.get('is_bonus', False)
            
            # ✅ NEW: If "Show bonus breakdown" filter is active, only count bonus points
            if include_bonus and not is_bonus:
                continue  # Skip regular points when bonus filter is active
            
            # Count points based on type
            if is_bonus:
                leaderboard_data[uid_str]['bonus_points'] += points_value
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
        
        # ✅ REMOVED: No longer processing points collection (historical data)
        # Only use points_request collection for consistency with analytics and export
        # This ensures all dashboards show the same point totals
        
        # ==========================================
        # CALCULATE UTILIZATION & PROGRESS (BATCH OPTIMIZED)
        # ==========================================
        
        # BATCH CALCULATE UTILIZATION FOR ALL USERS AT ONCE
        utilization_map = batch_calculate_utilization(user_ids, qtr_start, qtr_end, utilization_ids)
        
        # BATCH CALCULATE YEARLY BONUS FOR ALL USERS AT ONCE
        # ✅ FIXED: When year='all', use current_year for bonus calculation
        bonus_calc_year = current_year if selected_year == 'all' else selected_year
        yearly_bonus_map = batch_calculate_yearly_bonus(user_ids, bonus_calc_year)
        
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
        
        # ✅ Filter employees with points
        # When include_bonus is checked, only bonus points are counted
        final_leaderboard = [
            data for data in leaderboard_data.values()
            if data['total_points'] > 0
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
        
        # ✅ Get categories that have actual data in the selected period
        # Query to find which categories have points in the selected period
        categories_with_data_query = {
            "user_id": {"$in": user_ids},
            "status": "Approved"
        }
        
        # ✅ ONLY add date filter if NOT viewing "All Years, All Quarters"
        if not (selected_quarter == "All-all" or (selected_year == 'all' and selected_quarter.startswith("All-"))):
            categories_with_data_query["$or"] = [
                {"event_date": {"$gte": qtr_start, "$lte": qtr_end}},
                {"request_date": {"$gte": qtr_start, "$lte": qtr_end}},
                {"award_date": {"$gte": qtr_start, "$lte": qtr_end}}
            ]
        
        # Get unique category IDs from points_request
        categories_with_data = mongo.db.points_request.distinct("category_id", categories_with_data_query)
        
        # Filter out utilization categories
        categories_with_data = [cat_id for cat_id in categories_with_data if cat_id not in utilization_ids]
        
        # Convert merged categories for template - only include categories with data
        categories_list = []
        for cat_name, cat_info in merged_categories.items():
            # Check if any of this category's IDs have data
            has_data = any(cat_id in categories_with_data for cat_id in cat_info['ids'])
            
            if has_data:
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
            selected_year=selected_year,
            available_years=available_years,
            selected_category=selected_category,
            selected_category_name=selected_category_name,
            include_bonus=include_bonus,
            grade_filter=grade_filter,
            role_filter=role_filter,
            all_grades=all_grades,
            all_roles=all_roles,
            config=config
        )
        
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print("=" * 80)
        print("LEADERBOARD ERROR:")
        print(error_msg)
        print("-" * 80)
        print(error_trace)
        print("=" * 80)
        
        # Return error page instead of redirecting so we can see the error
        return f"""
        <html>
        <head><title>Leaderboard Error</title></head>
        <body style="font-family: monospace; padding: 20px;">
            <h1>Leaderboard Error</h1>
            <h2>Error Message:</h2>
            <pre style="background: #f5f5f5; padding: 10px; border: 1px solid #ccc;">{error_msg}</pre>
            <h2>Stack Trace:</h2>
            <pre style="background: #f5f5f5; padding: 10px; border: 1px solid #ccc;">{error_trace}</pre>
            <p><a href="/central/dashboard">Back to Dashboard</a></p>
        </body>
        </html>
        """, 500