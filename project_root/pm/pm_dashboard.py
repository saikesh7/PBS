from flask import render_template, request, session, redirect, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import sys
from .pm_main import pm_bp

# Helper functions
def debug_print(message, data=None):
    pass  # No-op function to disable debug output

def error_print(message, error=None):

    if error:
        print(f"  Exception: {str(error)}", file=sys.stderr)

def check_pm_access():
    """Check if user has PM dashboard access"""
    user_id = session.get('user_id')
    
    if not user_id:
        return False, None
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    # Check dashboard_access field for PM access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    if 'pm' not in dashboard_access:
        return False, user
    
    return True, user

def get_current_quarter_date_range():
    now = datetime.utcnow()
    current_month = now.month
    current_year = now.year

    if current_month < 4:  # Q4 (Jan-Mar)
        fiscal_year_start = current_year - 1
    else:
        fiscal_year_start = current_year

    if 4 <= current_month <= 6:  # Q1: April-June
        quarter = 1
        quarter_start = datetime(fiscal_year_start, 4, 1)
        quarter_end = datetime(fiscal_year_start, 6, 30, 23, 59, 59, 999999)
    elif 7 <= current_month <= 9:  # Q2: July-September
        quarter = 2
        quarter_start = datetime(fiscal_year_start, 7, 1)
        quarter_end = datetime(fiscal_year_start, 9, 30, 23, 59, 59, 999999)
    elif 10 <= current_month <= 12:  # Q3: October-December
        quarter = 3
        quarter_start = datetime(fiscal_year_start, 10, 1)
        quarter_end = datetime(fiscal_year_start, 12, 31, 23, 59, 59, 999999)
    else:  # Q4: January-March
        quarter = 4
        quarter_start = datetime(fiscal_year_start + 1, 1, 1)
        quarter_end = datetime(fiscal_year_start + 1, 3, 31, 23, 59, 59, 999999)

    return quarter_start, quarter_end, quarter, fiscal_year_start

def get_grade_minimum_expectations():
    return {
        'A1': 500, 'B1': 500, 'B2': 500, 'C1': 1000, 
        'C2': 1000, 'D1': 1000, 'D2': 500
    }

def get_fiscal_quarter_for_date(date):
    """Get fiscal quarter (Q1-Q4) for a given date"""
    if not date:
        return ""
    
    month = date.month
    year = date.year
    
    # Determine fiscal year start
    if month >= 4:
        fiscal_year_start = year
    else:
        fiscal_year_start = year - 1
    
    # Determine quarter
    if 4 <= month <= 6:
        quarter = "Q1"
    elif 7 <= month <= 9:
        quarter = "Q2"
    elif 10 <= month <= 12:
        quarter = "Q3"
    else:  # 1-3
        quarter = "Q4"
    
    return f"{quarter}"

@pm_bp.route('/dashboard')
def dashboard():
    # Check PM access
    has_access, user = check_pm_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the PM dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get current quarter info
        quarter_start, quarter_end, current_quarter, current_year = get_current_quarter_date_range()
        
        # Format quarter and month display like pmarch
        now = datetime.utcnow()
        fiscal_year_end = current_year + 1
        display_quarter = f"Q{current_quarter} FY{current_year}-{str(fiscal_year_end)[-2:]}"
        display_month = now.strftime("%b %Y").upper()
        
        # ✅ Get PM categories from hr_categories
        pm_categories = list(mongo.db.hr_categories.find({
            "category_department": "pm",
            "category_status": "active"
        }))
        
        if not pm_categories:
            flash('PM categories not found in hr_categories', 'warning')
            pm_categories = []
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        # Get dashboard counts - ONLY for PM category requests assigned to this PM
        pending_count = mongo.db.points_request.count_documents({
            "status": "Pending",
            "category_id": {"$in": pm_category_ids},  # ✅ Only PM categories
            "$or": [
                {"assigned_validator_id": ObjectId(user["_id"])},  # New field name
                {"pending_validator_id": ObjectId(user["_id"])},   # Old field name
                {"pm_id": ObjectId(user["_id"])}                   # Very old field name
            ]
        })
        
        processed_this_quarter = mongo.db.points_request.count_documents({
            "category_id": {"$in": pm_category_ids},
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_by": ObjectId(user["_id"]),  # ✅ Only processed by this PM
            "processed_date": {"$gte": quarter_start, "$lte": quarter_end}
        })
        
        approved_this_quarter = mongo.db.points_request.count_documents({
            "category_id": {"$in": pm_category_ids},
            "status": "Approved",
            "processed_by": ObjectId(user["_id"]),  # ✅ Only approved by this PM
            "processed_date": {"$gte": quarter_start, "$lte": quarter_end}
        })
        
        # Get recent pending requests (top 10) - ONLY PM category requests assigned to this PM
        recent_pending = []
        pending_cursor = mongo.db.points_request.find({
            "status": "Pending",
            "category_id": {"$in": pm_category_ids},  # ✅ Only PM categories
            "$or": [
                {"assigned_validator_id": ObjectId(user["_id"])},  # New field name
                {"pending_validator_id": ObjectId(user["_id"])},   # Old field name
                {"pm_id": ObjectId(user["_id"])}                   # Very old field name
            ]
        }).sort("request_date", -1).limit(10)
        
        for req in pending_cursor:
            employee = mongo.db.users.find_one({"_id": req["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req.get("category_id")})
            
            if not employee or not category:
                continue
            
            recent_pending.append({
                'id': str(req["_id"]),
                'employee_name': employee.get("name", "Unknown"),
                'employee_id': employee.get("employee_id", "N/A"),
                'employee_grade': employee.get("grade", ""),
                'employee_department': employee.get("department", ""),
                'category_name': category.get("name", "Unknown"),
                'title': req.get("title", "N/A"),
                'request_date': req["request_date"].strftime('%d-%m-%Y') if req.get("request_date") else None,
                'points': req.get("points", 0),
                'notes': req.get("request_notes") or req.get("notes", ""),
                'status': req["status"],
                'has_attachment': req.get("has_attachment", False)
            })
        
        # Get rejected requests - ONLY PM categories processed by this PM
        rejected_requests = []
        rejected_cursor = mongo.db.points_request.find({
            "status": "Rejected",
            "category_id": {"$in": pm_category_ids},  # ✅ Only PM categories
            "processed_by": ObjectId(user["_id"])
        }).sort("processed_date", -1).limit(100)
        
        for req in rejected_cursor:
            employee = mongo.db.users.find_one({"_id": req["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req.get("category_id")})
            
            if not employee or not category:
                continue
            
            request_date = req.get("request_date")
            quarter_label = get_fiscal_quarter_for_date(request_date) if request_date else ""
            
            rejected_requests.append({
                'id': str(req["_id"]),
                'employee_name': employee.get("name", "Unknown"),
                'employee_id': employee.get("employee_id", "N/A"),
                'employee_grade': employee.get("grade", ""),
                'employee_department': employee.get("department", ""),
                'category_name': category.get("name", "Unknown"),
                'title': req.get("title", "N/A"),
                'request_date': request_date,
                'processed_date': req.get("processed_date"),
                'points': req.get("points", 0),
                'notes': req.get("response_notes") or req.get("manager_notes") or req.get("notes", ""),
                'response_notes': req.get("response_notes", ""),
                'manager_notes': req.get("manager_notes", ""),
                'status': req.get("status", "Rejected"),
                'quarter': quarter_label,
                'has_attachment': req.get("has_attachment", False)
            })
        
        # Get recent processed requests - ONLY PM categories processed by this PM
        recent_processed = []
        processed_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "category_id": {"$in": pm_category_ids},  # ✅ Only PM categories
            "processed_by": ObjectId(user["_id"])  # ✅ Only processed by this PM
        }).sort("processed_date", -1).limit(100)
        
        for req in processed_cursor:
            employee = mongo.db.users.find_one({"_id": req["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req.get("category_id")})
            
            if not employee or not category:
                continue
            
            request_date = req.get("request_date")
            quarter_label = get_fiscal_quarter_for_date(request_date) if request_date else ""
            
            recent_processed.append({
                'id': str(req["_id"]),
                'employee_name': employee.get("name", "Unknown"),
                'employee_id': employee.get("employee_id", "N/A"),
                'employee_grade': employee.get("grade", ""),
                'employee_department': employee.get("department", ""),
                'category_name': category.get("name", "Unknown"),
                'title': req.get("title", "N/A"),
                'request_date': request_date,
                'processed_date': req.get("processed_date"),
                'points': req.get("points", 0),
                'notes': req.get("response_notes") or req.get("manager_notes") or req.get("notes", ""),
                'response_notes': req.get("response_notes", ""),
                'manager_notes': req.get("manager_notes", ""),
                'status': req.get("status", "Approved"),
                'quarter': quarter_label,
                'has_attachment': req.get("has_attachment", False)
            })
        
        # Get recent awards (direct awards given by this PM in points collection)
        # ONLY PM categories - filter out other departments
        recent_awards = []
        awards_cursor = mongo.db.points.find({
            "awarded_by": ObjectId(user["_id"]),  # ✅ Awards given by this PM
            "category_id": {"$in": pm_category_ids}  # ✅ Only PM categories
        }).sort("award_date", -1).limit(100)
        
        for award in awards_cursor:
            employee = mongo.db.users.find_one({"_id": award["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": award.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": award.get("category_id")})
            
            if employee and category:
                recent_awards.append({
                    'award_date': award.get("award_date", datetime.utcnow()),
                    'employee_name': employee.get("name", "Unknown"),
                    'employee_id': employee.get("employee_id", "N/A"),
                    'category_name': category.get("name", "Unknown"),
                    'points': award["points"]
                })
        
        # Get employees summary (all employees for statistics)
        employees_cursor = mongo.db.users.find({"role": "Employee"}).sort("name", 1)
        all_employees = []
        
        for emp in employees_cursor:
            if str(emp["_id"]) == str(user["_id"]):
                continue
                
            grade = emp.get("grade", "Unknown")
            minimum_expectations = get_grade_minimum_expectations()
            expected_points = minimum_expectations.get(grade, 0)
            
            # Calculate total points
            total_points = 0
            points_cursor = mongo.db.points.find({"user_id": emp["_id"]})
            for point in points_cursor:
                total_points += point["points"]
            
            # Calculate quarterly points for PM categories
            quarter_points = 0
            if pm_categories:
                quarter_points_cursor = mongo.db.points.find({
                    "user_id": emp["_id"],
                    "category_id": {"$in": pm_category_ids},
                    "award_date": {"$gte": quarter_start, "$lt": quarter_end}
                })
                for point in quarter_points_cursor:
                    quarter_points += point["points"]
            
            employee_data = {
                'id': str(emp["_id"]),
                'name': emp.get("name", "Unknown"),
                'email': emp.get("email", ""),
                'employee_id': emp.get("employee_id", ""),
                'grade': grade,
                'department': emp.get("department", "Unknown"),
                'total_points': total_points,
                'total_quarter_points': quarter_points,
                'expected_points': expected_points
            }
            
            all_employees.append(employee_data)
        
        # Prepare context for template
        context = {
            'user': user,
            'current_quarter': f"Q{current_quarter}",
            'current_year': current_year,
            'current_month': datetime.utcnow().strftime("%B"),
            'display_quarter': display_quarter,  # ✅ Formatted like pmarch
            'display_month': display_month,      # ✅ Formatted like pmarch
            'categories': pm_categories,
            'is_validator': True,  # ✅ PM users are validators
            # Dashboard counts
            'pending_count': pending_count,
            'processed_this_quarter': processed_this_quarter,
            'approved_this_quarter': approved_this_quarter,
            'rejected_count': len(rejected_requests),
            # Lists for template
            'pending_requests': recent_pending,
            'all_records': recent_processed,  # ✅ Match presales/pmarch naming
            'processed_requests': recent_processed,
            'rejected_requests': rejected_requests,
            'recent_awards': recent_awards,
            'all_employees': all_employees,
            'managed_employees': all_employees
        }
        
        return render_template('pm_dashboard.html', **context)
        
    except Exception as e:
        error_print("Dashboard error", e)
        flash("An error occurred while loading the dashboard", "danger")
        return redirect(url_for('auth.login'))

@pm_bp.route('/switch_to_employee_view')
def switch_to_employee_view():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('Invalid action.', 'danger')
        return redirect(url_for('auth.login'))
    
    session['is_acting_as_employee'] = True
    session['original_dashboard'] = 'pm'
    session['original_view_url'] = url_for('pm.dashboard')
    flash('Switched to Employee View. You can now raise requests for yourself.', 'info')
    return redirect(url_for('employee_dashboard.dashboard'))

