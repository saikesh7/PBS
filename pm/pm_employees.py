from flask import render_template, request, session, redirect, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import sys
from .pm_main import pm_bp

def error_print(message, error=None):
    pass

def check_pm_access():
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    return 'pm' in dashboard_access, user

def get_current_quarter_date_range():
    now = datetime.utcnow()
    current_month = now.month
    current_year = now.year

    if current_month < 4:
        fiscal_year_start = current_year - 1
    else:
        fiscal_year_start = current_year

    if 4 <= current_month <= 6:
        quarter = 1
        quarter_start = datetime(fiscal_year_start, 4, 1)
        quarter_end = datetime(fiscal_year_start, 6, 30, 23, 59, 59, 999999)
    elif 7 <= current_month <= 9:
        quarter = 2
        quarter_start = datetime(fiscal_year_start, 7, 1)
        quarter_end = datetime(fiscal_year_start, 9, 30, 23, 59, 59, 999999)
    elif 10 <= current_month <= 12:
        quarter = 3
        quarter_start = datetime(fiscal_year_start, 10, 1)
        quarter_end = datetime(fiscal_year_start, 12, 31, 23, 59, 59, 999999)
    else:
        quarter = 4
        quarter_start = datetime(fiscal_year_start + 1, 1, 1)
        quarter_end = datetime(fiscal_year_start + 1, 3, 31, 23, 59, 59, 999999)

    return quarter_start, quarter_end, quarter, fiscal_year_start

def get_grade_minimum_expectations():
    return {
        'A1': 500, 'B1': 500, 'B2': 500, 'C1': 1000, 
        'C2': 1000, 'D1': 1000, 'D2': 500
    }

def is_employee_eligible_for_category(employee_grade, category_code):
    if employee_grade == 'A1' and category_code.lower() == 'mentoring':
        return False
    return True

@pm_bp.route('/employees')
def employees():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # ✅ Get PM categories from hr_categories
        pm_categories = list(mongo.db.hr_categories.find({
            "category_department": "pm",
            "category_status": "active"
        }))
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        # Get quarter info
        quarter_start, quarter_end, current_quarter, year = get_current_quarter_date_range()
        
        # Get all employees
        employees_cursor = mongo.db.users.find({"role": "Employee"}).sort("name", 1)
        
        employees = []
        for emp in employees_cursor:
            if str(emp["_id"]) == str(user["_id"]):
                continue
            
            # Calculate total points
            total_points = 0
            points_cursor = mongo.db.points.find({"user_id": emp["_id"]})
            for point in points_cursor:
                total_points += point["points"]
            
            # Calculate quarterly PM category points
            quarter_points = 0
            if pm_categories:
                quarter_points_cursor = mongo.db.points.find({
                    "user_id": emp["_id"],
                    "category_id": {"$in": pm_category_ids},
                    "award_date": {"$gte": quarter_start, "$lt": quarter_end}
                })
                for point in quarter_points_cursor:
                    quarter_points += point["points"]
            
            # Get expected points
            grade = emp.get("grade", "Unknown")
            minimum_expectations = get_grade_minimum_expectations()
            expected_points = minimum_expectations.get(grade, 0)
            
            employees.append({
                'id': str(emp["_id"]),
                'name': emp.get("name", "Unknown"),
                'email': emp.get("email", ""),
                'employee_id': emp.get("employee_id", ""),
                'grade': grade,
                'department': emp.get("department", "Unknown"),
                'total_points': total_points,
                'quarter_points': quarter_points,
                'expected_points': expected_points,
                'can_award': True
            })
        
        return render_template('pm_employees.html',
                             user=user,
                             employees=employees,
                             current_quarter=f"Q{current_quarter}",
                             current_year=year)
                             
    except Exception as e:
        error_print("Error loading employees", e)
        flash("An error occurred while loading employees", "danger")
        return redirect(url_for('pm.dashboard'))

@pm_bp.route('/employee/<employee_id>')
def employee_detail(employee_id):
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to view this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        
        if not employee:
            flash('Employee not found', 'danger')
            return redirect(url_for('pm.employees'))
        
        # ✅ Get PM categories from hr_categories
        pm_categories = list(mongo.db.hr_categories.find({
            "category_department": "pm",
            "category_status": "active"
        }))
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        # Get request history (including old data from 'categories' collection)
        request_history = []
        history_cursor = mongo.db.points_request.find({
            "user_id": ObjectId(employee_id)
        }).sort("request_date", -1)
        
        for req in history_cursor:
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req.get("category_id")})
            
            if category:
                request_history.append({
                    'request': req,
                    'category': category
                })
        
        # Get awarded points (including old data from 'categories' collection)
        awarded_points = []
        total_points = 0
        points_cursor = mongo.db.points.find({
            "user_id": ObjectId(employee_id)
        }).sort("award_date", -1)
        
        for point in points_cursor:
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": point.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": point.get("category_id")})
            
            if category:
                awarded_points.append({
                    'point': point,
                    'category': category
                })
                total_points += point["points"]
        
        # Get eligible categories
        employee_grade = employee.get('grade', '')
        eligible_categories = [
            cat for cat in pm_categories
            if is_employee_eligible_for_category(employee_grade, cat.get('code', ''))
        ]
        
        return render_template('pm_employee_detail.html',
                             user=user,
                             employee=employee,
                             request_history=request_history,
                             awarded_points=awarded_points,
                             total_points=total_points,
                             categories=eligible_categories)
                             
    except Exception as e:
        error_print("Error loading employee details", e)
        flash('An error occurred while loading employee details', 'danger')
        return redirect(url_for('pm.employees'))

@pm_bp.route('/validate-employee/<employee_id>')
def validate_employee(employee_id):
    has_access, user = check_pm_access()
    
    if not has_access:
        return jsonify({"error": "Not authorized"}), 403
    
    try:
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        
        if not employee:
            return jsonify({
                "valid": False,
                "error": "Employee not found"
            })
        
        # ✅ Get PM categories from hr_categories
        pm_categories = list(mongo.db.hr_categories.find({
            "category_department": "pm",
            "category_status": "active"
        }))
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        # Get quarter info
        quarter_start, quarter_end, quarter, year = get_current_quarter_date_range()
        
        # Calculate quarterly points
        quarter_points = 0
        quarter_count = 0
        
        if pm_categories:
            quarter_count = mongo.db.points.count_documents({
                "user_id": ObjectId(employee_id),
                "category_id": {"$in": pm_category_ids},
                "award_date": {"$gte": quarter_start, "$lt": quarter_end}
            })
            
            quarter_points_cursor = mongo.db.points.find({
                "user_id": ObjectId(employee_id),
                "category_id": {"$in": pm_category_ids},
                "award_date": {"$gte": quarter_start, "$lt": quarter_end}
            })
            
            for point in quarter_points_cursor:
                quarter_points += point["points"]
        
        # Get expected points
        grade = employee.get("grade", "Unknown")
        minimum_expectations = get_grade_minimum_expectations()
        expected_points = minimum_expectations.get(grade, 0)
        
        return jsonify({
            "valid": True,
            "employee_id": str(employee["_id"]),
            "employee_name": employee.get("name", ""),
            "email": employee.get("email", ""),
            "employee_id_field": employee.get("employee_id", ""),
            "grade": grade,
            "department": employee.get("department", ""),
            "current_quarter_count": quarter_count,
            "total_quarter_points": quarter_points,
            "expected_points": expected_points
        })
        
    except Exception as e:
        error_print(f"Error validating employee {employee_id}", e)
        return jsonify({"valid": False, "error": "Server error"}), 500

@pm_bp.route('/find-employee-by-id/<employee_code>')
def find_employee_by_id(employee_code):
    has_access, user = check_pm_access()
    
    if not has_access:
        return jsonify({"error": "Not authorized"}), 403
    
    try:
        employee = mongo.db.users.find_one({"employee_id": employee_code})
        
        if not employee:
            return jsonify({"found": False, "error": "Employee not found"}), 404
        
        return jsonify({
            "found": True,
            "employee": {
                "id": str(employee["_id"]),
                "name": employee.get("name", ""),
                "email": employee.get("email", ""),
                "employee_id": employee.get("employee_id", ""),
                "grade": employee.get("grade", ""),
                "department": employee.get("department", "")
            }
        })
        
    except Exception as e:
        error_print(f"Error finding employee by ID {employee_code}", e)
        return jsonify({"found": False, "error": "Server error"}), 500