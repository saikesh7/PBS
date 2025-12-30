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

def is_employee_eligible_for_category(employee_grade, category_code):
    if employee_grade == 'A1' and category_code.lower() == 'mentoring':
        return False
    return True

@pm_bp.route('/award-form')
def award_form():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get PM categories
        pm_categories = list(mongo.db.categories.find({
            "code": {"$in": ["initiative_ai", "mentoring"]},
            "validator": "PM"
        }))
        
        # Get all employees
        employees = list(mongo.db.users.find({"role": "Employee"}).sort("name", 1))
        
        return render_template('pm_award_form.html',
                             user=user,
                             categories=pm_categories,
                             employees=employees)
                             
    except Exception as e:
        error_print("Error loading award form", e)
        flash("An error occurred while loading the award form", "danger")
        return redirect(url_for('pm.dashboard'))

@pm_bp.route('/award-points', methods=['POST'])
def award_points():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get form data
        employee_id = request.form.get('employee_id')
        category_id = request.form.get('category_id')
        points = request.form.get('points', 0)
        notes = request.form.get('notes', '')
        
        if not employee_id or not category_id:
            flash('Missing required fields', 'danger')
            return redirect(url_for('pm.award_form'))
        
        # Validate points
        try:
            points = int(points)
            if points <= 0:
                raise ValueError("Points must be positive")
        except ValueError:
            flash('Points must be a positive number', 'danger')
            return redirect(url_for('pm.award_form'))
        
        # Get employee and category
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        
        if not employee:
            flash('Employee not found', 'danger')
            return redirect(url_for('pm.award_form'))
        
        if not category:
            flash('Category not found', 'danger')
            return redirect(url_for('pm.award_form'))
        
        # Check eligibility
        if not is_employee_eligible_for_category(employee.get('grade', ''), category.get('code', '')):
            flash(f"Employee with grade {employee.get('grade')} is not eligible for {category.get('name')}", 'danger')
            return redirect(url_for('pm.award_form'))
        
        # Get quarter info
        quarter_start, quarter_end, quarter, year = get_current_quarter_date_range()
        
        # Create points entry
        points_entry = {
            "user_id": ObjectId(employee_id),
            "category_id": ObjectId(category_id),
            "points": points,
            "award_date": datetime.utcnow(),
            "awarded_by": ObjectId(user["_id"]),
            "notes": notes,
            "quarter": quarter,
            "year": year
        }
        
        mongo.db.points.insert_one(points_entry)
        
        flash(f'{points} points awarded to {employee.get("name")} for {category.get("name")}', 'success')
        return redirect(url_for('pm.dashboard'))
        
    except Exception as e:
        error_print("Error awarding points", e)
        flash('An error occurred while awarding points', 'danger')
        return redirect(url_for('pm.award_form'))

@pm_bp.route('/award-history')
def award_history():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get PM categories
        pm_categories = list(mongo.db.categories.find({
            "code": {"$in": ["initiative_ai", "mentoring"]},
            "validator": "PM"
        }))
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        # Get awards given by this user
        awards_cursor = mongo.db.points.find({
            "awarded_by": ObjectId(user["_id"]),
            "category_id": {"$in": pm_category_ids}
        }).sort("award_date", -1).limit(100)
        
        awards = []
        for award in awards_cursor:
            employee = mongo.db.users.find_one({"_id": award["user_id"]})
            category = next((cat for cat in pm_categories if cat["_id"] == award["category_id"]), None)
            
            if employee and category:
                awards.append({
                    'id': str(award["_id"]),
                    'employee_name': employee.get("name", "Unknown"),
                    'employee_grade': employee.get("grade", "Unknown"),
                    'category_name': category.get("name", "Unknown"),
                    'points': award["points"],
                    'award_date': award["award_date"],
                    'notes': award.get("notes", ""),
                    'quarter': award.get("quarter", ""),
                    'year': award.get("year", "")
                })
        
        return render_template('pm_award_history.html',
                             user=user,
                             awards=awards)
                             
    except Exception as e:
        error_print("Error loading award history", e)
        flash("An error occurred while loading award history", "danger")
        return redirect(url_for('pm.dashboard'))