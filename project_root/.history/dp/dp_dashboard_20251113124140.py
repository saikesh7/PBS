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
    
    # Calculate points for each assigned employee
    employees_data = []
    for employee in assigned_employees:
        emp_id = employee['_id']
        
        print(f"DEBUG: Processing employee {employee.get('name')} (ID: {emp_id})")
        
        # First check if there are any points at all for this employee
        all_points = list(mongo.db.points_request.find({"user_id": emp_id}))
        print(f"DEBUG: Total points records for employee: {len(all_points)}")
        
        if all_points:
            print(f"DEBUG: Sample point record: {all_points[0]}")
            # Check approved points
            approved_points = list(mongo.db.points_request.find({"user_id": emp_id, "status": "Approved"}))
            print(f"DEBUG: Approved points records: {len(approved_points)}")
            if approved_points:
                total_all_time = sum(p.get('points', 0) for p in approved_points)
                print(f"DEBUG: Total approved points (all time): {total_all_time}")
        
        # Calculate quarterly points from BOTH collections
        emp_quarterly_points = {}
        for quarter in range(1, 5):
            start_date, end_date = get_fiscal_quarter_date_range(quarter, fiscal_year)
            
            print(f"DEBUG: Q{quarter} date range: {start_date} to {end_date}")
            
            # Query points_request collection (Approved status)
            points_from_request = mongo.db.points_request.aggregate([
                {
                    "$match": {
                        "user_id": emp_id,
                        "status": "Approved",
                        "event_date": {"$gte": start_date, "$lte": end_date}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_points": {"$sum": "$points"}
                    }
                }
            ])
            
            points_request_list = list(points_from_request)
            points_from_request_total = points_request_list[0]['total_points'] if points_request_list else 0
            
            # Query points collection (already approved and moved)
            points_from_points_col = mongo.db.points.aggregate([
                {
                    "$match": {
                        "user_id": emp_id,
                        "award_date": {"$gte": start_date, "$lte": end_date}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_points": {"$sum": "$points"}
                    }
                }
            ])
            
            points_col_list = list(points_from_points_col)
            points_from_points_total = points_col_list[0]['total_points'] if points_col_list else 0
            
            # Combine both sources
            emp_quarterly_points[f'Q{quarter}'] = points_from_request_total + points_from_points_total
            print(f"DEBUG: Q{quarter} points: {emp_quarterly_points[f'Q{quarter}']} (request: {points_from_request_total}, points: {points_from_points_total})")
        
        # Get total points for the year from BOTH collections
        # From points_request
        total_from_request_agg = mongo.db.points_request.aggregate([
            {
                "$match": {
                    "user_id": emp_id,
                    "status": "Approved",
                    "event_date": {"$gte": year_start, "$lte": year_end}
                }
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
        
        # From points collection
        total_from_points_agg = mongo.db.points.aggregate([
            {
                "$match": {
                    "user_id": emp_id,
                    "award_date": {"$gte": year_start, "$lte": year_end}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_points": {"$sum": "$points"}
                }
            }
        ])
        
        total_points_col_list = list(total_from_points_agg)
        total_from_points = total_points_col_list[0]['total_points'] if total_points_col_list else 0
        
        # Combine both sources
        emp_total_points = total_from_request + total_from_points
        
        print(f"DEBUG: Total points for {employee.get('name')}: {emp_total_points} (request: {total_from_request}, points: {total_from_points})")
        print("=" * 60)
        
        employees_data.append({
            'employee': employee,
            'quarterly_points': emp_quarterly_points,
            'total_points': emp_total_points
        })
    
    return render_template('dp_dashboard.html',
                         user=user,
                         current_quarter=current_quarter_name,
                         employees_data=employees_data,
                         fiscal_year=fiscal_year)

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
    
    # Get all approved points for this employee from BOTH collections
    points_from_request = list(mongo.db.points_request.find({
        "user_id": ObjectId(employee_id),
        "status": "Approved",
        "event_date": {"$gte": year_start, "$lte": year_end}
    }))
    
    points_from_points_col = list(mongo.db.points.find({
        "user_id": ObjectId(employee_id),
        "award_date": {"$gte": year_start, "$lte": year_end}
    }))
    
    # Combine both sources
    all_points = points_from_request + points_from_points_col
    
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
                category = mongo.db.categories.find_one({"_id": category_id})
                
                # If category not found, try to get category name from the request itself
                category_name = 'Unknown'
                if category:
                    category_name = category.get('name', 'Unknown')
                elif pr.get('category_name'):
                    category_name = pr.get('category_name')
                
                # Use event_date or award_date depending on source
                event_date = pr.get('event_date') or pr.get('award_date')
                event_date_str = event_date.strftime('%d-%m-%Y') if event_date else 'N/A'
                
                category_map[category_id] = {
                    'category_name': category_name,
                    'points': 0,
                    'count': 0,
                    'event_date': event_date_str,
                    'status': pr.get('status', 'Approved')
                }
            
            category_map[category_id]['points'] += pr.get('points', 0)
            category_map[category_id]['count'] += 1
    
    points_by_category = list(category_map.values())
    
    # Calculate quarterly points from BOTH collections
    quarterly_points = {}
    for quarter in range(1, 5):
        start_date, end_date = get_fiscal_quarter_date_range(quarter, fiscal_year)
        
        # From points_request
        points_from_request = mongo.db.points_request.aggregate([
            {
                "$match": {
                    "user_id": ObjectId(employee_id),
                    "status": "Approved",
                    "event_date": {"$gte": start_date, "$lte": end_date}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_points": {"$sum": "$points"}
                }
            }
        ])
        
        points_request_list = list(points_from_request)
        points_from_request_total = points_request_list[0]['total_points'] if points_request_list else 0
        
        # From points collection
        points_from_points_col = mongo.db.points.aggregate([
            {
                "$match": {
                    "user_id": ObjectId(employee_id),
                    "award_date": {"$gte": start_date, "$lte": end_date}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_points": {"$sum": "$points"}
                }
            }
        ])
        
        points_col_list = list(points_from_points_col)
        points_from_points_total = points_col_list[0]['total_points'] if points_col_list else 0
        
        quarterly_points[f'Q{quarter}'] = points_from_request_total + points_from_points_total
    
    # Calculate total points from both sources
    total_points = sum(pr.get('points', 0) for pr in all_points)
    
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
    
    employees_summary = []
    
    for employee in assigned_employees:
        emp_id = employee['_id']
        
        # Calculate quarterly points from BOTH collections
        emp_quarterly_points = {}
        for quarter in range(1, 5):
            start_date, end_date = get_fiscal_quarter_date_range(quarter, fiscal_year)
            
            # From points_request
            points_from_request = mongo.db.points_request.aggregate([
                {
                    "$match": {
                        "user_id": emp_id,
                        "status": "Approved",
                        "event_date": {"$gte": start_date, "$lte": end_date}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_points": {"$sum": "$points"}
                    }
                }
            ])
            
            points_request_list = list(points_from_request)
            points_from_request_total = points_request_list[0]['total_points'] if points_request_list else 0
            
            # From points collection
            points_from_points_col = mongo.db.points.aggregate([
                {
                    "$match": {
                        "user_id": emp_id,
                        "award_date": {"$gte": start_date, "$lte": end_date}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_points": {"$sum": "$points"}
                    }
                }
            ])
            
            points_col_list = list(points_from_points_col)
            points_from_points_total = points_col_list[0]['total_points'] if points_col_list else 0
            
            # Combine both
            emp_quarterly_points[f'Q{quarter}'] = points_from_request_total + points_from_points_total
        
        # Get total points for the year from BOTH collections
        total_from_request_agg = mongo.db.points_request.aggregate([
            {
                "$match": {
                    "user_id": emp_id,
                    "status": "Approved",
                    "event_date": {"$gte": year_start, "$lte": year_end}
                }
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
        
        total_from_points_agg = mongo.db.points.aggregate([
            {
                "$match": {
                    "user_id": emp_id,
                    "award_date": {"$gte": year_start, "$lte": year_end}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_points": {"$sum": "$points"}
                }
            }
        ])
        
        total_points_col_list = list(total_from_points_agg)
        total_from_points = total_points_col_list[0]['total_points'] if total_points_col_list else 0
        
        emp_total_points = total_from_request + total_from_points
        
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


@dp_bp.route('/leaderboard')
def leaderboard():
    """Dedicated leaderboard page showing top performers by category and grade"""
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
    
    # Get overall top 10 performers
    top_performers = get_top_performers(year_start, year_end, limit=10)
    
    # Get category-wise top 10 performers
    category_top_performers = get_category_wise_top_performers(year_start, year_end, limit=10)
    
    # Get grade-wise top 10 performers
    grade_top_performers = get_grade_wise_top_performers(year_start, year_end, limit=10)
    
    return render_template('dp_leaderboard.html',
                         user=user,
                         current_quarter=current_quarter_name,
                         fiscal_year=fiscal_year,
                         top_performers=top_performers,
                         category_top_performers=category_top_performers,
                         grade_top_performers=grade_top_performers)


def get_grade_wise_top_performers(start_date, end_date, limit=10):
    """Get top performers by grade for the given date range"""
    grades = ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']
    
    grade_leaders = {}
    
    for grade in grades:
        # Get all users with this grade
        users_in_grade = list(mongo.db.users.find({"grade": grade}))
        user_ids = [u['_id'] for u in users_in_grade]
        
        if not user_ids:
            continue
        
        pipeline = [
            {
                "$match": {
                    "status": "Approved",
                    "user_id": {"$in": user_ids},
                    "event_date": {"$gte": start_date, "$lte": end_date}
                }
            },
            {
                "$group": {
                    "_id": "$user_id",
                    "total_points": {"$sum": "$points"}
                }
            },
            {
                "$sort": {"total_points": -1}
            },
            {
                "$limit": limit
            }
        ]
        
        top_in_grade = list(mongo.db.points_request.aggregate(pipeline))
        
        if top_in_grade:
            performers = []
            for idx, performer in enumerate(top_in_grade, 1):
                user = mongo.db.users.find_one({"_id": performer["_id"]})
                if user:
                    performers.append({
                        'rank': idx,
                        'name': user.get('name', 'Unknown'),
                        'employee_id': user.get('employee_id', 'N/A'),
                        'department': user.get('department', 'N/A'),
                        'grade': user.get('grade', 'N/A'),
                        'total_points': performer['total_points']
                    })
            
            if performers:
                grade_leaders[grade] = performers
    
    return grade_leaders
