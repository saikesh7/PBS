from flask import Blueprint, render_template, session, redirect, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import os

# Define Blueprint
current_dir = os.path.dirname(os.path.abspath(__file__))

dp_bp = Blueprint('dp', __name__, url_prefix='/dp',
                  template_folder=os.path.join(current_dir, 'templates'),
                  static_folder=os.path.join(current_dir, 'static'),
                  static_url_path='/dp/static')

def get_utilization_category_ids():
    """
    Get utilization category IDs to exclude from point calculations
    Utilization is a percentage (98%), not actual points, so we exclude it
    """
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    return utilization_category_ids


def get_category_info(category_id):
    """
    Get category information from both hr_categories and categories collections
    Try hr_categories first, then fallback to old categories
    If category not found in database, return 'No Category' instead of 'Unknown Category'
    Handles both ObjectId and string types for category_id
    """
    if not category_id:
        return {'name': 'No Category', 'code': 'N/A'}
    
    # Convert string to ObjectId if needed
    try:
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
    except Exception:
        # Invalid ObjectId format
        return {'name': 'No Category', 'code': 'N/A'}
    
    # Try hr_categories first (new system)
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return {
            'name': category.get('name', 'No Category'),
            'code': category.get('category_code', 'N/A')
        }
    
    # Fallback to old categories collection
    category = mongo.db.categories.find_one({"_id": category_id})
    if category:
        return {
            'name': category.get('name', 'No Category'),
            'code': category.get('code', 'N/A')
        }
    
    # Category ID exists but not found in database - return 'No Category'
    return {'name': 'No Category', 'code': 'N/A'}


def get_effective_event_date(entry):
    """
    Get effective event date with fallback logic
    Priority: event_date > request_date > award_date (SAME AS HR ANALYTICS)
    """
    if not entry:
        return None
    
    # Try event_date first
    event_date = entry.get('event_date')
    if event_date and isinstance(event_date, datetime):
        return event_date
    
    # Try request_date
    request_date = entry.get('request_date')
    if request_date and isinstance(request_date, datetime):
        return request_date
    
    # Try award_date
    award_date = entry.get('award_date')
    if award_date and isinstance(award_date, datetime):
        return award_date
    
    return None


def get_current_fiscal_quarter_details():
    """Get current fiscal quarter (April-March fiscal year)"""
    now = datetime.utcnow()
    adjusted_month = (now.month - 4 + 12) % 12
    current_quarter_num = (adjusted_month // 3) + 1
    
    fiscal_year = now.year
    if now.month < 4:
        fiscal_year -= 1
        
    current_quarter_name = f"Q{current_quarter_num}-{fiscal_year}"
    return current_quarter_name, current_quarter_num, fiscal_year

def get_fiscal_quarter_date_range(quarter_num, fiscal_year):
    """Get date range for a fiscal quarter"""
    if quarter_num == 1:
        start_date = datetime(fiscal_year, 4, 1)
        end_date = datetime(fiscal_year, 6, 30, 23, 59, 59)
    elif quarter_num == 2:
        start_date = datetime(fiscal_year, 7, 1)
        end_date = datetime(fiscal_year, 9, 30, 23, 59, 59)
    elif quarter_num == 3:
        start_date = datetime(fiscal_year, 10, 1)
        end_date = datetime(fiscal_year, 12, 31, 23, 59, 59)
    elif quarter_num == 4:
        start_date = datetime(fiscal_year + 1, 1, 1)
        end_date = datetime(fiscal_year + 1, 3, 31, 23, 59, 59)
    else:
        raise ValueError("Invalid quarter number")
    return start_date, end_date

@dp_bp.route('/dashboard')
def dashboard():
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('auth.login'))
    
    # Check if user has dp_dashboard access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    else:
        dashboard_access = [x.lower() for x in dashboard_access]
    
    if 'dp_dashboard' not in dashboard_access and 'dp' not in dashboard_access:
        flash('You do not have permission to access the DP Dashboard', 'danger')
        return redirect(url_for('employee_dashboard.dashboard'))
    
    # Get current quarter details
    current_quarter_name, current_quarter_num, fiscal_year = get_current_fiscal_quarter_details()
    year_start = datetime(fiscal_year, 4, 1)
    year_end = datetime(fiscal_year + 1, 3, 31, 23, 59, 59)
    
    # Get all employees assigned to this DP
    assigned_employees = list(mongo.db.users.find({"dp_id": ObjectId(user_id)}))
    assigned_employee_ids = [emp['_id'] for emp in assigned_employees]
    
    # Get utilization category IDs to exclude from point calculations
    utilization_category_ids = get_utilization_category_ids()
    
    # Calculate points for each assigned employee
    employees_data = []
    for employee in assigned_employees:
        emp_id = employee['_id']
        
        # Calculate quarterly points using MongoDB aggregation (matches Central dashboard)
        emp_quarterly_points = {}
        for quarter in range(1, 5):
            start_date, end_date = get_fiscal_quarter_date_range(quarter, fiscal_year)
            
            # Build aggregation pipeline (same as Central dashboard)
            pipeline = [
                {
                    "$match": {
                        "user_id": emp_id,
                        "status": "Approved"
                    }
                },
                {
                    "$addFields": {
                        # Create effective_date field: event_date > request_date > award_date
                        "effective_date": {
                            "$ifNull": [
                                "$event_date",
                                {"$ifNull": ["$request_date", "$award_date"]}
                            ]
                        }
                    }
                },
                {
                    "$match": {
                        "effective_date": {"$gte": start_date, "$lte": end_date}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_points": {"$sum": "$points"}
                    }
                }
            ]
            
            # Exclude utilization categories
            if utilization_category_ids:
                pipeline[0]["$match"]["category_id"] = {"$nin": utilization_category_ids}
            
            results = list(mongo.db.points_request.aggregate(pipeline))
            points_from_request_total = results[0]['total_points'] if results else 0
            
            # ✅ REMOVED: No longer querying points collection for consistency with central dashboard
            # Only use points_request collection
            
            emp_quarterly_points[f'Q{quarter}'] = points_from_request_total
        
        # Get ALL-TIME total points from BOTH collections (matches Central leaderboard logic)
        # From points_request (excluding utilization)
        total_match_query = {
            "user_id": emp_id,
            "status": "Approved"
        }
        
        # Exclude utilization categories
        if utilization_category_ids:
            total_match_query["category_id"] = {"$nin": utilization_category_ids}
        
        total_from_request_agg = mongo.db.points_request.aggregate([
            {
                "$match": total_match_query
            },
            {
                "$group": {
                    "_id": None,
                    "total_points": {"$sum": "$points"}
                }
            }
        ])
        
        total_request_list = list(total_from_request_agg)
        total_from_request = total_request_list[0]['total_points'] if total_request_list else 0
        
        # Track all processed request IDs
        all_processed_request_ids = set()
        for req in mongo.db.points_request.find(total_match_query, {"_id": 1}):
            all_processed_request_ids.add(req['_id'])
        
        # From points collection (exclude already processed requests)
        # ✅ REMOVED: No longer querying points collection for consistency with central dashboard
        # Only use points_request collection
        
        emp_total_points = total_from_request
        
        employees_data.append({
            'employee': employee,
            'quarterly_points': emp_quarterly_points,
            'total_points': emp_total_points
        })
    
    # Get unique departments from assigned employees
    unique_departments = list(set([emp['employee'].get('department') for emp in employees_data if emp['employee'].get('department')]))
    
    # Get unique grades from assigned employees
    unique_grades = sorted(list(set([emp['employee'].get('grade') for emp in employees_data if emp['employee'].get('grade')])))
    
    # Calculate total points of all assigned employees (all-time)
    total_points_all_employees = sum([emp['total_points'] for emp in employees_data])
    
    # Calculate total pending points from all assigned employees (excluding utilization)
    total_pending_points = 0
    if assigned_employee_ids:
        pending_match_query = {
            "user_id": {"$in": assigned_employee_ids},
            "status": "Pending"
        }
        
        # Exclude utilization categories
        if utilization_category_ids:
            pending_match_query["category_id"] = {"$nin": utilization_category_ids}
        
        pending_points_agg = mongo.db.points_request.aggregate([
            {
                "$match": pending_match_query
            },
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": "$points"}
                }
            }
        ])
        pending_list = list(pending_points_agg)
        total_pending_points = pending_list[0]['total'] if pending_list else 0
    
    return render_template('dp_dashboard.html',
                         user=user,
                         current_quarter=current_quarter_name,
                         employees_data=employees_data,
                         fiscal_year=fiscal_year,
                         unique_departments=unique_departments,
                         unique_grades=unique_grades,
                         total_points_all_employees=total_points_all_employees,
                         total_pending_points=total_pending_points)

@dp_bp.route('/employee-details/<employee_id>')
def employee_details(employee_id):
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Verify the employee is assigned to this DP
    employee = mongo.db.users.find_one({
        "_id": ObjectId(employee_id),
        "dp_id": ObjectId(user_id)
    })
    
    if not employee:
        return jsonify({'error': 'Employee not found or not assigned to you'}), 404
    
    # Get current fiscal year
    current_quarter_name, current_quarter_num, fiscal_year = get_current_fiscal_quarter_details()
    year_start = datetime(fiscal_year, 4, 1)
    year_end = datetime(fiscal_year + 1, 3, 31, 23, 59, 59)
    
    # ✅ Get all approved points for this employee from points_request ONLY (matches Central leaderboard logic)
    all_points = list(mongo.db.points_request.find({
        "user_id": ObjectId(employee_id),
        "status": "Approved",
        "$or": [
            {"event_date": {"$gte": year_start, "$lte": year_end}},
            {"request_date": {"$gte": year_start, "$lte": year_end}},
            {"award_date": {"$gte": year_start, "$lte": year_end}}
        ]
    }))
    
    # Group by category
    points_by_category = []
    category_map = {}
    
    for pr in all_points:
        category_id = pr.get('category_id')
        if category_id:
            # Convert to ObjectId if it's a string
            if isinstance(category_id, str):
                try:
                    category_id = ObjectId(category_id)
                except:
                    pass
            
            if category_id not in category_map:
                # Use the same logic as Points Tracker
                category_info = get_category_info(category_id)
                category_name = category_info['name']
                category_code = category_info['code']
                
                # Check if this is a utilization category
                is_utilization = category_code == 'utilization_billable' or 'utilization' in category_name.lower()
                
                # Use event_date or award_date depending on source
                event_date = pr.get('event_date') or pr.get('award_date')
                event_date_str = event_date.strftime('%d-%m-%Y') if event_date else 'N/A'
                
                category_map[category_id] = {
                    'category_name': category_name,
                    'points': 0,
                    'count': 0,
                    'event_date': event_date_str,
                    'status': pr.get('status', 'Approved'),
                    'is_utilization': is_utilization,
                    'utilization_percentage': None
                }
            
            # Handle utilization vs regular points
            if category_map[category_id]['is_utilization']:
                # Get utilization value from the request
                utilization_value = pr.get('utilization_value')
                if not utilization_value and 'submission_data' in pr:
                    submission_data = pr.get('submission_data', {})
                    if isinstance(submission_data, dict):
                        utilization_value = submission_data.get('utilization_value') or submission_data.get('utilization')
                
                # Convert to percentage
                if utilization_value is not None and utilization_value > 0:
                    if utilization_value <= 1:
                        # It's a decimal (0.98 = 98%)
                        utilization_percentage = round(utilization_value * 100, 2)
                    else:
                        # It's already a percentage (98 = 98%)
                        utilization_percentage = round(utilization_value, 2)
                    
                    # Store the utilization percentage
                    category_map[category_id]['utilization_percentage'] = utilization_percentage
                    # Don't add to points for utilization
                else:
                    category_map[category_id]['points'] += pr.get('points', 0)
            else:
                # Regular points category
                category_map[category_id]['points'] += pr.get('points', 0)
            
            category_map[category_id]['count'] += 1
    
    points_by_category = list(category_map.values())
    
    # Get utilization category IDs to exclude from quarterly calculations
    utilization_category_ids = get_utilization_category_ids()
    
    # Calculate quarterly points using MongoDB aggregation (matches Central dashboard)
    quarterly_points = {}
    for quarter in range(1, 5):
        start_date, end_date = get_fiscal_quarter_date_range(quarter, fiscal_year)
        
        # Build aggregation pipeline (same as Central dashboard)
        pipeline = [
            {
                "$match": {
                    "user_id": ObjectId(employee_id),
                    "status": "Approved"
                }
            },
            {
                "$addFields": {
                    # Create effective_date field: event_date > request_date > award_date
                    "effective_date": {
                        "$ifNull": [
                            "$event_date",
                            {"$ifNull": ["$request_date", "$award_date"]}
                        ]
                    }
                }
            },
            {
                "$match": {
                    "effective_date": {"$gte": start_date, "$lte": end_date}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_points": {"$sum": "$points"}
                }
            }
        ]
        
        # Exclude utilization categories if needed
        if utilization_category_ids:
            pipeline[0]["$match"]["category_id"] = {"$nin": utilization_category_ids}
        
        results = list(mongo.db.points_request.aggregate(pipeline))
        quarter_total = results[0]['total_points'] if results else 0
        
        quarterly_points[f'Q{quarter}'] = quarter_total
    
    # Calculate total points excluding utilization (should match sum of quarterly points)
    # Use the same logic as quarterly calculation
    total_match_query = {
        "user_id": ObjectId(employee_id),
        "status": "Approved",
        "$or": [
            {"event_date": {"$gte": year_start, "$lte": year_end}},
            {"request_date": {"$gte": year_start, "$lte": year_end}},
            {"award_date": {"$gte": year_start, "$lte": year_end}}
        ]
    }
    
    # Exclude utilization categories
    if utilization_category_ids:
        total_match_query["category_id"] = {"$nin": utilization_category_ids}
    
    total_points_agg = mongo.db.points_request.aggregate([
        {
            "$match": total_match_query
        },
        {
            "$group": {
                "_id": None,
                "total_points": {"$sum": "$points"}
            }
        }
    ])
    
    total_points_list = list(total_points_agg)
    total_points = total_points_list[0]['total_points'] if total_points_list else 0
    
    return jsonify({
        'employee': {
            'name': employee.get('name'),
            'employee_id': employee.get('employee_id'),
            'email': employee.get('email'),
            'department': employee.get('department'),
            'grade': employee.get('grade')
        },
        'total_points': total_points,
        'quarterly_points': quarterly_points,
        'points_by_category': points_by_category,
        'fiscal_year': fiscal_year
    })


@dp_bp.route('/api/employees-points-summary')
def employees_points_summary():
    """API endpoint to get updated points summary for all assigned employees"""
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Get current quarter details
    current_quarter_name, current_quarter_num, fiscal_year = get_current_fiscal_quarter_details()
    year_start = datetime(fiscal_year, 4, 1)
    year_end = datetime(fiscal_year + 1, 3, 31, 23, 59, 59)
    
    # Get all employees assigned to this DP
    assigned_employees = list(mongo.db.users.find({"dp_id": ObjectId(user_id)}))
    
    # Get utilization category IDs to exclude from point calculations
    utilization_category_ids = get_utilization_category_ids()
    
    employees_summary = []
    
    for employee in assigned_employees:
        emp_id = employee['_id']
        
        # Calculate quarterly points using MongoDB aggregation (matches Central dashboard)
        emp_quarterly_points = {}
        for quarter in range(1, 5):
            start_date, end_date = get_fiscal_quarter_date_range(quarter, fiscal_year)
            
            # Build aggregation pipeline (same as Central dashboard)
            pipeline = [
                {
                    "$match": {
                        "user_id": emp_id,
                        "status": "Approved"
                    }
                },
                {
                    "$addFields": {
                        # Create effective_date field: event_date > request_date > award_date
                        "effective_date": {
                            "$ifNull": [
                                "$event_date",
                                {"$ifNull": ["$request_date", "$award_date"]}
                            ]
                        }
                    }
                },
                {
                    "$match": {
                        "effective_date": {"$gte": start_date, "$lte": end_date}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_points": {"$sum": "$points"}
                    }
                }
            ]
            
            # Exclude utilization categories
            if utilization_category_ids:
                pipeline[0]["$match"]["category_id"] = {"$nin": utilization_category_ids}
            
            results = list(mongo.db.points_request.aggregate(pipeline))
            points_from_request_total = results[0]['total_points'] if results else 0
            
            # ✅ REMOVED: No longer querying points collection for consistency with central dashboard
            # Only use points_request collection
            
            emp_quarterly_points[f'Q{quarter}'] = points_from_request_total
        
        # Get ALL-TIME total points (excluding utilization)
        total_match_query = {
            "user_id": emp_id,
            "status": "Approved"
        }
        
        # Exclude utilization categories
        if utilization_category_ids:
            total_match_query["category_id"] = {"$nin": utilization_category_ids}
        
        total_from_request_agg = mongo.db.points_request.aggregate([
            {
                "$match": total_match_query
            },
            {
                "$group": {
                    "_id": None,
                    "total_points": {"$sum": "$points"}
                }
            }
        ])
        
        total_request_list = list(total_from_request_agg)
        total_from_request = total_request_list[0]['total_points'] if total_request_list else 0
        
        # ✅ REMOVED: No longer querying points collection for consistency with central dashboard
        # Only use points_request collection
        
        emp_total_points = total_from_request
        
        employees_summary.append({
            'employee_id': str(emp_id),
            'employee_name': employee.get('name', 'Unknown'),
            'employee_employee_id': employee.get('employee_id', 'N/A'),
            'employee_email': employee.get('email', 'N/A'),
            'employee_department': employee.get('department', 'N/A'),
            'quarterly_points': emp_quarterly_points,
            'total_points': emp_total_points
        })
    
    return jsonify({
        'employees': employees_summary,
        'fiscal_year': fiscal_year
    })


@dp_bp.route('/api/employees-count')
def employees_count():
    """API endpoint to get count of assigned employees"""
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Get count of employees assigned to this DP
    count = mongo.db.users.count_documents({"dp_id": ObjectId(user_id)})
    
    return jsonify({'count': count})


@dp_bp.route('/api/leaderboard-data')
def get_leaderboard_data():
    """API endpoint to get leaderboard data without full page reload"""
    from flask import request
    
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Get filter parameters
    selected_scope = request.args.get('scope', 'organization')
    selected_year_param = request.args.get('year', '')
    selected_department = request.args.get('department', '')
    selected_grade = request.args.get('grade', '')
    selected_quarter = request.args.get('quarter', '')
    
    # Get current quarter details
    current_quarter_name, current_quarter_num, fiscal_year = get_current_fiscal_quarter_details()
    
    # Determine selected year - handle "all" option
    if selected_year_param and selected_year_param != 'all':
        selected_year = int(selected_year_param)
    elif selected_year_param == 'all':
        selected_year = 'all'
    else:
        # Default to current fiscal year
        selected_year = fiscal_year
    
    # Calculate date range based on filters
    if selected_year == 'all':
        # "All Years" selected - show all-time top performers
        year_start = datetime(2000, 1, 1)
        year_end = datetime(2100, 12, 31, 23, 59, 59)
    elif selected_year:
        # Specific year selected
        if selected_quarter:
            quarter_num = int(selected_quarter)
            year_start, year_end = get_fiscal_quarter_date_range(quarter_num, selected_year)
        else:
            year_start = datetime(selected_year, 4, 1)
            year_end = datetime(selected_year + 1, 3, 31, 23, 59, 59)
    else:
        # Fallback - show all-time
        year_start = datetime(2000, 1, 1)
        year_end = datetime(2100, 12, 31, 23, 59, 59)
        selected_year = 'all'
    
    # Get departments and grades dynamically from the actual leaderboard data
    # First, get the user IDs based on scope
    if selected_scope == 'my_team':
        assigned_employees = list(mongo.db.users.find({"dp_id": ObjectId(user_id)}))
        allowed_user_ids = [emp['_id'] for emp in assigned_employees]
    else:
        # Organization wide - get all users
        allowed_user_ids = [u['_id'] for u in mongo.db.users.find({}, {"_id": 1})]
    
    # Get unique departments and grades from users who have points in the selected date range
    # Build match criteria for points_request
    match_for_filters = {
        "status": "Approved",
        "user_id": {"$in": allowed_user_ids}
    }
    
    # Add date range filter if not "all"
    if selected_year != 'all':
        match_for_filters["$or"] = [
            {"event_date": {"$gte": year_start, "$lte": year_end}},
            {"request_date": {"$gte": year_start, "$lte": year_end}},
            {"award_date": {"$gte": year_start, "$lte": year_end}}
        ]
    
    # Get distinct user IDs who have points
    users_with_points_pipeline = [
        {"$match": match_for_filters},
        {"$group": {"_id": "$user_id"}}
    ]
    
    users_with_points = list(mongo.db.points_request.aggregate(users_with_points_pipeline))
    user_ids_with_points = [u['_id'] for u in users_with_points]
    
    # Get departments and grades from these users
    all_departments = []
    all_grades = []
    
    if user_ids_with_points:
        # Get unique departments
        departments_cursor = mongo.db.users.find(
            {"_id": {"$in": user_ids_with_points}, "department": {"$exists": True, "$ne": None, "$ne": ""}},
            {"department": 1}
        ).distinct('department')
        all_departments = sorted([d for d in departments_cursor if d])
        
        # Get unique grades
        grades_cursor = mongo.db.users.find(
            {"_id": {"$in": user_ids_with_points}, "grade": {"$exists": True, "$ne": None, "$ne": ""}},
            {"grade": 1}
        ).distinct('grade')
        all_grades = sorted([g for g in grades_cursor if g])
    
    # Get overall top 10 performers with filters
    top_performers = get_top_performers(year_start, year_end, limit=10, 
                                       department=selected_department,
                                       grade=selected_grade,
                                       scope=selected_scope,
                                       dp_user_id=user_id if selected_scope == 'my_team' else None)
    
    return jsonify({
        'top_performers': top_performers,
        'all_departments': all_departments,
        'all_grades': all_grades
    })


@dp_bp.route('/pending-requests')
def pending_requests():
    """Show pending point requests from assigned employees with pagination"""
    from flask import request
    
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('auth.login'))
    
    # Check if user has dp_dashboard access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    else:
        dashboard_access = [x.lower() for x in dashboard_access]
    
    if 'dp_dashboard' not in dashboard_access and 'dp' not in dashboard_access:
        flash('You do not have permission to access the DP Dashboard', 'danger')
        return redirect(url_for('employee_dashboard.dashboard'))
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Get all employees assigned to this DP
    assigned_employees = list(mongo.db.users.find({"dp_id": ObjectId(user_id)}))
    assigned_employee_ids = [emp['_id'] for emp in assigned_employees]
    
    # Get total count of pending requests
    total_pending = mongo.db.points_request.count_documents({
        "user_id": {"$in": assigned_employee_ids},
        "status": "Pending"
    })
    
    # Calculate pagination
    total_pages = max(1, (total_pending + per_page - 1) // per_page) if total_pending > 0 else 1
    skip = (page - 1) * per_page
    
    # Get pending requests for current page
    pending_requests_list = list(mongo.db.points_request.find({
        "user_id": {"$in": assigned_employee_ids},
        "status": "Pending"
    }).sort("request_date", -1).skip(skip).limit(per_page))
    
    # Enrich requests with employee and category details
    for req in pending_requests_list:
        # Get employee details
        employee = mongo.db.users.find_one({"_id": req.get('user_id')})
        req['employee_name'] = employee.get('name', 'Unknown') if employee else 'Unknown'
        req['employee_id_display'] = employee.get('employee_id', 'N/A') if employee else 'N/A'
        req['department'] = employee.get('department', 'N/A') if employee else 'N/A'
        req['grade'] = employee.get('grade', 'N/A') if employee else 'N/A'
        
        # Get category name using the same logic as Points Tracker
        category_id = req.get('category_id')
        if category_id:
            category_info = get_category_info(category_id)
            req['category_name'] = category_info['name']
        else:
            req['category_name'] = 'No Category'
        
        # Add source (where the request came from)
        req['source'] = req.get('source', 'employee').capitalize()
        
        # Add requested by (who submitted the request)
        req['requested_by'] = req['employee_name']
        
        # Use submission_notes or request_notes as description
        if not req.get('description'):
            req['description'] = req.get('submission_notes') or req.get('request_notes') or req.get('response_notes')
        
        # Determine where the request is pending and who needs to approve
        # Use assigned_validator_id from your database
        pending_with_id = req.get('assigned_validator_id') or req.get('pending_with') or req.get('approver_id')
        pending_role = req.get('category_department', '').upper() or req.get('pending_role') or req.get('approver_role')
        
        if pending_with_id:
            # Get the approver's details
            try:
                approver_obj_id = ObjectId(pending_with_id) if isinstance(pending_with_id, str) else pending_with_id
                approver = mongo.db.users.find_one({"_id": approver_obj_id})
                if approver:
                    approver_name = approver.get('name', 'Unknown')
                    approver_role = approver.get('role', pending_role or 'Unknown')
                    req['pending_at'] = f"{approver_role} - {approver_name}"
                else:
                    req['pending_at'] = pending_role or 'HR/Admin'
            except:
                req['pending_at'] = pending_role or 'HR/Admin'
        elif pending_role:
            req['pending_at'] = pending_role
        else:
            # If no specific approver, just show HR/Admin
            req['pending_at'] = 'HR/Admin'
    
    return render_template('dp_pending_requests.html',
                         user=user,
                         pending_requests=pending_requests_list,
                         total_pending=total_pending,
                         page=page,
                         total_pages=total_pages,
                         per_page=per_page)


@dp_bp.route('/leaderboard')
def leaderboard():
    """Dedicated leaderboard page showing top performers by category and grade"""
    from flask import request
    
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('auth.login'))
    
    # Check if user has dp_dashboard access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    else:
        dashboard_access = [x.lower() for x in dashboard_access]
    
    if 'dp_dashboard' not in dashboard_access and 'dp' not in dashboard_access:
        flash('You do not have permission to access the DP Dashboard', 'danger')
        return redirect(url_for('employee_dashboard.dashboard'))
    
    try:
        # Get current quarter details first
        current_quarter_name, current_quarter_num, fiscal_year = get_current_fiscal_quarter_details()
        
        # Get filter parameters
        selected_scope = request.args.get('scope', 'organization')  # Default to organization
        selected_year_param = request.args.get('year', '')
        selected_department = request.args.get('department', '')
        selected_grade = request.args.get('grade', '')
        selected_quarter = request.args.get('quarter', '')
        
        # Determine selected year - handle "all" option
        if selected_year_param and selected_year_param != 'all':
            selected_year = int(selected_year_param)
        elif selected_year_param == 'all':
            selected_year = 'all'
        else:
            # Default to current fiscal year
            selected_year = fiscal_year
        
        # Calculate date range based on filters
        if selected_year == 'all':
            # "All Years" selected - show all-time top performers
            year_start = datetime(2000, 1, 1)
            year_end = datetime(2100, 12, 31, 23, 59, 59)
        elif selected_year:
            # Specific year selected
            if selected_quarter:
                quarter_num = int(selected_quarter)
                year_start, year_end = get_fiscal_quarter_date_range(quarter_num, selected_year)
            else:
                year_start = datetime(selected_year, 4, 1)
                year_end = datetime(selected_year + 1, 3, 31, 23, 59, 59)
        else:
            # Fallback - show all-time
            year_start = datetime(2000, 1, 1)
            year_end = datetime(2100, 12, 31, 23, 59, 59)
            selected_year = 'all'
    
        # Get departments and grades dynamically from the actual leaderboard data
        # First, get the user IDs based on scope
        if selected_scope == 'my_team':
            assigned_employees = list(mongo.db.users.find({"dp_id": ObjectId(user_id)}))
            allowed_user_ids = [emp['_id'] for emp in assigned_employees]
        else:
            # Organization wide - get all users
            allowed_user_ids = [u['_id'] for u in mongo.db.users.find({}, {"_id": 1})]
        
        # Get unique departments and grades from users who have points in the selected date range
        # Build match criteria for points_request
        match_for_filters = {
            "status": "Approved",
            "user_id": {"$in": allowed_user_ids}
        }
        
        # Add date range filter if not "all"
        if selected_year != 'all':
            match_for_filters["$or"] = [
                {"event_date": {"$gte": year_start, "$lte": year_end}},
                {"request_date": {"$gte": year_start, "$lte": year_end}},
                {"award_date": {"$gte": year_start, "$lte": year_end}}
            ]
        
        # Get distinct user IDs who have points
        users_with_points_pipeline = [
            {"$match": match_for_filters},
            {"$group": {"_id": "$user_id"}}
        ]
        
        users_with_points = list(mongo.db.points_request.aggregate(users_with_points_pipeline))
        user_ids_with_points = [u['_id'] for u in users_with_points]
        
        # Get departments and grades from these users
        all_departments = []
        all_grades = []
        
        if user_ids_with_points:
            # Get unique departments
            departments_cursor = mongo.db.users.find(
                {"_id": {"$in": user_ids_with_points}, "department": {"$exists": True, "$ne": None, "$ne": ""}},
                {"department": 1}
            ).distinct('department')
            all_departments = sorted([d for d in departments_cursor if d])
            
            # Get unique grades
            grades_cursor = mongo.db.users.find(
                {"_id": {"$in": user_ids_with_points}, "grade": {"$exists": True, "$ne": None, "$ne": ""}},
                {"grade": 1}
            ).distinct('grade')
            all_grades = sorted([g for g in grades_cursor if g])
        
        # If no data found, fallback to all departments and standard grades
        if not all_departments:
            all_departments = sorted(mongo.db.users.distinct('department', {"department": {"$ne": None, "$ne": ""}}))
        
        if not all_grades:
            all_grades = ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']
        
        # Get available years dynamically from database (years with actual data)
        available_years_set = set()
        
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
                # Convert calendar year to fiscal year
                calendar_year = year_doc['_id']
                # If data is from Jan-Mar, it belongs to previous fiscal year
                # We'll add both the year and year-1 to cover all cases
                available_years_set.add(calendar_year)
                available_years_set.add(calendar_year - 1)
        
        # Always include current fiscal year even if no data yet
        available_years_set.add(fiscal_year)
        
        # Convert to sorted list (descending order - newest first)
        available_years = sorted(list(available_years_set), reverse=True)
        
        # Add "All Years" option at the beginning
        available_years.insert(0, 'all')
        
        # Validate selected_year if it's a number
        if selected_year != 'all' and isinstance(selected_year, int):
            if selected_year < 2000 or selected_year > 2100:
                selected_year = fiscal_year
        
        # Get overall top 10 performers with filters
        top_performers = get_top_performers(year_start, year_end, limit=10, 
                                           department=selected_department,
                                           grade=selected_grade,
                                           scope=selected_scope,
                                           dp_user_id=user_id if selected_scope == 'my_team' else None)
    
        return render_template('dp_leaderboard.html',
                             user=user,
                             current_quarter=current_quarter_name,
                             fiscal_year=fiscal_year,
                             selected_scope=selected_scope,
                             selected_year=selected_year,
                             selected_department=selected_department,
                             selected_grade=selected_grade,
                             selected_quarter=selected_quarter,
                             all_departments=all_departments,
                             all_grades=all_grades,
                             available_years=available_years,
                             top_performers=top_performers)
    except Exception as e:
        print(f"Error in leaderboard route: {e}")
        import traceback
        traceback.print_exc()
        flash('An error occurred while loading the leaderboard', 'danger')
        return redirect(url_for('dp.dashboard'))


def get_top_performers(start_date, end_date, limit=10, department=None, grade=None, scope='organization', dp_user_id=None):
    """Get overall top performers for the given date range with optional filters"""
    
    # Get list of user IDs to filter by if scope is 'my_team'
    allowed_user_ids = None
    if scope == 'my_team' and dp_user_id:
        # Get all employees assigned to this DP
        assigned_employees = list(mongo.db.users.find({"dp_id": ObjectId(dp_user_id)}))
        allowed_user_ids = [emp['_id'] for emp in assigned_employees]
    
    # Build match criteria for points_request (matches Central leaderboard logic)
    match_request = {
        "status": "Approved",
        "$or": [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    }
    
    # Add user_id filter for my_team scope
    if allowed_user_ids is not None:
        match_request["user_id"] = {"$in": allowed_user_ids}
    
    # Aggregate from points_request collection
    pipeline_request = [
        {"$match": match_request},
        {
            "$group": {
                "_id": "$user_id",
                "total_points": {"$sum": "$points"}
            }
        }
    ]
    
    points_from_request = list(mongo.db.points_request.aggregate(pipeline_request))
    
    # ✅ REMOVED: No longer querying points collection for consistency with central dashboard
    # Only use points_request collection
    
    # Create user_points_map from points_request only
    user_points_map = {}
    for item in points_from_request:
        user_id = item['_id']
        user_points_map[user_id] = user_points_map.get(user_id, 0) + item['total_points']
    
    # Sort by points and get top performers
    sorted_performers = sorted(user_points_map.items(), key=lambda x: x[1], reverse=True)
    
    performers = []
    for idx, (user_id, total_points) in enumerate(sorted_performers, 1):
        user = mongo.db.users.find_one({"_id": user_id})
        if user:
            # Apply department filter
            if department and user.get('department') != department:
                continue
            
            # Apply grade filter
            if grade and user.get('grade') != grade:
                continue
            
            performers.append({
                'rank': len(performers) + 1,
                'name': user.get('name', 'Unknown'),
                'employee_id': user.get('employee_id', 'N/A'),
                'department': user.get('department', 'N/A'),
                'grade': user.get('grade', 'N/A'),
                'total_points': total_points
            })
            
            if len(performers) >= limit:
                break
    
    return performers


def get_category_wise_top_performers(start_date, end_date, limit=10, department=None, employee=None):
    """Get top performers by category for the given date range with optional filters"""
    # Get all categories
    categories = list(mongo.db.categories.find())
    
    category_leaders = {}
    
    for category in categories:
        category_id = category['_id']
        category_name = category.get('name', 'Unknown')
        
        # Aggregate from points_request collection
        pipeline_request = [
            {
                "$match": {
                    "status": "Approved",
                    "category_id": category_id,
                    "event_date": {"$gte": start_date, "$lte": end_date}
                }
            },
            {
                "$group": {
                    "_id": "$user_id",
                    "total_points": {"$sum": "$points"}
                }
            }
        ]
        
        points_from_request = list(mongo.db.points_request.aggregate(pipeline_request))
        
        # ✅ REMOVED: No longer querying points collection for consistency with central dashboard
        # Only use points_request collection
        
        # Create user_points_map from points_request only
        user_points_map = {}
        for item in points_from_request:
            user_id = item['_id']
            user_points_map[user_id] = user_points_map.get(user_id, 0) + item['total_points']
        
        if not user_points_map:
            continue
        
        # Sort by points and get top performers
        sorted_performers = sorted(user_points_map.items(), key=lambda x: x[1], reverse=True)
        
        performers = []
        for idx, (user_id, total_points) in enumerate(sorted_performers, 1):
            user = mongo.db.users.find_one({"_id": user_id})
            if user:
                # Apply department filter
                if department and user.get('department') != department:
                    continue
                
                # Apply employee filter
                if employee:
                    try:
                        if user['_id'] != ObjectId(employee):
                            continue
                    except:
                        continue
                
                performers.append({
                    'rank': len(performers) + 1,
                    'name': user.get('name', 'Unknown'),
                    'employee_id': user.get('employee_id', 'N/A'),
                    'department': user.get('department', 'N/A'),
                    'grade': user.get('grade', 'N/A'),
                    'total_points': total_points
                })
                
                if len(performers) >= limit:
                    break
        
        if performers:
            category_leaders[category_name] = performers
    
    return category_leaders


def get_grade_wise_top_performers(start_date, end_date, limit=10, department=None, category=None, employee=None):
    """Get top performers by grade for the given date range with optional filters"""
    grades = ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']
    
    grade_leaders = {}
    
    for grade in grades:
        # Build user query with filters
        user_query = {"grade": grade}
        if department:
            user_query["department"] = department
        if employee:
            try:
                user_query["_id"] = ObjectId(employee)
            except:
                pass
        
        # Get all users with this grade and filters
        users_in_grade = list(mongo.db.users.find(user_query))
        user_ids = [u['_id'] for u in users_in_grade]
        
        if not user_ids:
            continue
        
        # Build match criteria for points_request
        match_request = {
            "status": "Approved",
            "user_id": {"$in": user_ids},
            "event_date": {"$gte": start_date, "$lte": end_date}
        }
        
        if category:
            try:
                match_request["category_id"] = ObjectId(category)
            except:
                pass
        
        # Aggregate from points_request collection
        pipeline_request = [
            {"$match": match_request},
            {
                "$group": {
                    "_id": "$user_id",
                    "total_points": {"$sum": "$points"}
                }
            }
        ]
        
        points_from_request = list(mongo.db.points_request.aggregate(pipeline_request))
        
        # ✅ REMOVED: No longer querying points collection for consistency with central dashboard
        # Only use points_request collection
        
        # Create user_points_map from points_request only
        user_points_map = {}
        for item in points_from_request:
            user_id = item['_id']
            user_points_map[user_id] = user_points_map.get(user_id, 0) + item['total_points']
        
        if not user_points_map:
            continue
        
        # Sort by points and get top performers
        sorted_performers = sorted(user_points_map.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        performers = []
        for idx, (user_id, total_points) in enumerate(sorted_performers, 1):
            user = mongo.db.users.find_one({"_id": user_id})
            if user:
                performers.append({
                    'rank': idx,
                    'name': user.get('name', 'Unknown'),
                    'employee_id': user.get('employee_id', 'N/A'),
                    'department': user.get('department', 'N/A'),
                    'grade': user.get('grade', 'N/A'),
                    'total_points': total_points
                })
        
        if performers:
            grade_leaders[grade] = performers
    
    return grade_leaders