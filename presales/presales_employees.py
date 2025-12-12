from flask import render_template, session, redirect, url_for, flash
from extensions import mongo
from bson.objectid import ObjectId
from .presales_main import presales_bp
from .presales_helpers import (
    check_presales_access, 
    get_current_quarter_date_range
)
from .constants import GRADE_MINIMUM_EXPECTATIONS
import logging

logger = logging.getLogger(__name__)

@presales_bp.route('/employees')
def employees():
    has_access, user = check_presales_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get presales categories from hr_categories
        presales_categories = list(mongo.db.hr_categories.find({
            "category_department": "presales",
            "category_status": "active"
        }))
        
        presales_category_ids = [cat["_id"] for cat in presales_categories]
        
        # Get quarter info
        quarter_start, quarter_end, current_quarter, year = get_current_quarter_date_range()
        
        # Get all employees (same as PM dashboard approach)
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
            
            # Calculate quarterly presales category points
            quarter_points = 0
            if presales_categories:
                quarter_points_cursor = mongo.db.points.find({
                    "user_id": emp["_id"],
                    "category_id": {"$in": presales_category_ids},
                    "award_date": {"$gte": quarter_start, "$lt": quarter_end}
                })
                for point in quarter_points_cursor:
                    quarter_points += point["points"]
            
            # Get expected points
            grade = emp.get("grade", "Unknown")
            minimum_expectations = GRADE_MINIMUM_EXPECTATIONS
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
        
        return render_template('presales_employees.html',
                             user=user,
                             employees=employees,
                             current_quarter=f"Q{current_quarter}",
                             current_year=year)
                             
    except Exception as e:
        logger.error(f"Error loading employees: {str(e)}")
        flash("An error occurred while loading employees", "danger")
        return redirect(url_for('presales.dashboard'))

@presales_bp.route('/employee/<employee_id>')
def employee_detail(employee_id):
    has_access, user = check_presales_access()
    
    if not has_access:
        flash('You do not have permission to view this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        
        if not employee:
            flash('Employee not found', 'danger')
            return redirect(url_for('presales.employees'))
        
        # Get presales categories from hr_categories
        presales_categories = list(mongo.db.hr_categories.find({
            "category_department": "presales",
            "category_status": "active"
        }))
        
        presales_category_ids = [cat["_id"] for cat in presales_categories]
        
        # Get request history
        request_history = []
        history_cursor = mongo.db.points_request.find({
            "user_id": ObjectId(employee_id),
            "category_id": {"$in": presales_category_ids}
        }).sort("request_date", -1)
        
        for req in history_cursor:
            category = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
            if category:
                request_history.append({
                    'request': req,
                    'category': category
                })
        
        # Get awarded points
        awarded_points = []
        total_points = 0
        points_cursor = mongo.db.points.find({
            "user_id": ObjectId(employee_id),
            "category_id": {"$in": presales_category_ids}
        }).sort("award_date", -1)
        
        for point in points_cursor:
            category = mongo.db.hr_categories.find_one({"_id": point["category_id"]})
            if category:
                awarded_points.append({
                    'point': point,
                    'category': category
                })
                total_points += point["points"]
        
        return render_template('presales_employee_detail.html',
                             user=user,
                             employee=employee,
                             request_history=request_history,
                             awarded_points=awarded_points,
                             total_points=total_points,
                             categories=presales_categories)
                             
    except Exception as e:
        logger.error(f"Error loading employee details: {str(e)}")
        flash('An error occurred while loading employee details', 'danger')
        return redirect(url_for('presales.employees'))

