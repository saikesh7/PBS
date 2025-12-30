"""
Presales Dashboard Module
Handles main dashboard for presales team members (peer-to-peer validation)
"""
from flask import render_template, request, session, redirect, url_for, flash
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
from gridfs import GridFS
import logging

from .presales_main import presales_bp
from .presales_helpers import (
    check_presales_access, get_financial_quarter_and_label,
    get_current_quarter_date_range, get_presales_categories,
    get_presales_category_ids, get_all_presales_category_ids
)
from .constants import ALL_GRADES

logger = logging.getLogger(__name__)

@presales_bp.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    """Main dashboard for Presales team members - supports peer-to-peer validation"""
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_presales_access()
    
    if not has_access:
        flash('You do not have permission to access the Presales dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    # ✅ Check if user still has presales dashboard access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    has_presales_access = any('presales' in str(access).lower() for access in dashboard_access)
    if not has_presales_access:
        flash('You no longer have access to the Presales dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        fs = GridFS(mongo.db)
        
        # Get manager name if exists
        manager_name = 'N/A'
        if user.get('manager_id'):
            manager_doc = mongo.db.users.find_one({"_id": ObjectId(user.get('manager_id'))})
            if manager_doc:
                manager_name = manager_doc.get('name', 'N/A')
        user['manager_name'] = manager_name
        
        # Get current quarter info
        now = datetime.utcnow()
        quarter, quarter_label_display, quarter_start_month, fiscal_year_start_val, fiscal_year_label = get_financial_quarter_and_label(now)
        
        current_quarter = f"{quarter_label_display} {fiscal_year_label}"
        display_quarter = f"{quarter_label_display.split()[0]} {fiscal_year_label}"
        display_month = now.strftime("%b %Y").upper()
        
        # Get quarter start date
        actual_calendar_year_of_quarter_start = fiscal_year_start_val
        if quarter == 4:
            actual_calendar_year_of_quarter_start = fiscal_year_start_val + 1
        quarter_start = datetime(actual_calendar_year_of_quarter_start, quarter_start_month, 1)
        
        # Get all employees for departments breakdown
        all_employees = list(mongo.db.users.find({"role": "Employee"}))
        
        departments = {}
        for emp in all_employees:
            grade = emp.get('grade', 'Unassigned')
            departments.setdefault(emp.get('department', 'Unassigned'), {}).setdefault(grade, []).append(emp)
        
        # Get presales categories (active only for reference)
        presales_categories = get_presales_categories()
        presales_category_ids = get_presales_category_ids()
        
        # Get ALL presales category IDs (active + inactive) for displaying existing requests
        all_presales_category_ids = get_all_presales_category_ids()
        
        if not presales_categories and not all_presales_category_ids:
            flash('Presales categories not found. Please contact HR to create categories.', 'warning')
        
        # ✅ Fetch pending requests assigned to this presales member
        # Use ALL category IDs to show requests even if category is now inactive
        pending_requests = []
        
        # ✅ Build query with Presales category filter (includes inactive categories)
        pending_query = {
            "status": "Pending",
            "assigned_validator_id": ObjectId(user_id)
        }
        
        # ✅ Filter by ALL Presales category IDs (active + inactive)
        if all_presales_category_ids:
            pending_query["category_id"] = {"$in": all_presales_category_ids}
        
        pending_cursor = mongo.db.points_request.find(pending_query).sort("request_date", -1).limit(5)
        
        # ✅ Get total pending count for badge (not limited)
        pending_count = mongo.db.points_request.count_documents(pending_query)
        
        for req_data in pending_cursor:
            employee = mongo.db.users.find_one({"_id": req_data.get("user_id")})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            if not employee or not category:
                continue
            
            pending_requests.append({
                'id': str(req_data["_id"]),
                    'employee_name': employee.get("name", "Unknown"),
                    'employee_id': employee.get("employee_id", "N/A"),
                    'employee_grade': employee.get("grade", ""),
                    'employee_department': employee.get("department", ""),
                    'category_name': category.get("name", "Unknown"),
                    'title': req_data.get("title", "N/A"),
                    'request_date': req_data["request_date"].isoformat() if req_data.get("request_date") else None,
                    'points': req_data["points"],
                    'notes': req_data.get("request_notes") or req_data.get("notes", ""),
                    'status': req_data["status"],
                    'has_attachment': req_data.get("has_attachment", False)
                })
        
        # ✅ Fetch rejected requests separately - ONLY presales categories
        # Include records where:
        # 1. Originally processed by this user (processed_by matches)
        # 2. OR assigned to this user but modified by HR (assigned_validator_id matches + hr_modified flag)
        rejected_requests = []
        
        # Build query to show:
        # 1. New records with processed_department = "presales"
        # 2. Old records without processed_department but with presales category_id
        rejected_or_conditions = [
            {"processed_department": "presales"}
        ]
        
        # For old records without processed_department, filter by category
        if presales_category_ids:
            rejected_or_conditions.append({
                "processed_department": {"$exists": False},
                "category_id": {"$in": presales_category_ids}
            })
        
        rejected_query = {
            "status": "Rejected",
            "$and": [
                {
                    "$or": [
                        {"processed_by": ObjectId(user_id)},
                        {
                            "assigned_validator_id": ObjectId(user_id),
                            "hr_modified": True
                        }
                    ]
                },
                {
                    "$or": rejected_or_conditions
                }
            ]
        }
        
        rejected_cursor = mongo.db.points_request.find(rejected_query).sort("processed_date", -1).limit(100)
        
        for req_data in rejected_cursor:
            employee = mongo.db.users.find_one({"_id": req_data.get("user_id")})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            if not employee or not category:
                continue
            
            rejected_requests.append({
                'id': str(req_data['_id']),
                'employee_name': employee.get("name", "Unknown"),
                'employee_id': employee.get("employee_id", "N/A"),
                'employee_grade': employee.get("grade", ""),
                'employee_department': employee.get("department", ""),
                'category_name': category.get("name", "Unknown"),
                'title': req_data.get("title", "N/A"),
                'request_date': req_data["request_date"],
                'processed_date': req_data.get("processed_date"),
                'points': req_data["points"],
                'notes': req_data.get("manager_notes", req_data.get("notes", "")),
                'status': req_data.get("status", "Rejected"),
                'has_attachment': req_data.get("has_attachment", False)
            })
        
        # ✅ Fetch processed history - ONLY presales categories
        # Include records where:
        # 1. Originally processed by this user (processed_by matches)
        # 2. OR assigned to this user but modified by HR (assigned_validator_id matches + hr_modified flag)
        all_records = []
        
        # Build query to show:
        # 1. New records with processed_department = "presales"
        # 2. Old records without processed_department but with presales category_id
        or_conditions = [
            {"processed_department": "presales"}
        ]
        
        # For old records without processed_department, filter by category
        if presales_category_ids:
            or_conditions.append({
                "processed_department": {"$exists": False},
                "category_id": {"$in": presales_category_ids}
            })
        
        history_query = {
            "status": {"$in": ["Approved", "Rejected"]},
            "$and": [
                {
                    "$or": [
                        {"processed_by": ObjectId(user_id)},
                        {
                            "assigned_validator_id": ObjectId(user_id),
                            "hr_modified": True
                        }
                    ]
                },
                {
                    "$or": or_conditions
                }
            ]
        }
        
        # ✅ Get total counts for dashboard stats (ALL records, not limited)
        processed_count = mongo.db.points_request.count_documents(history_query)
        
        approved_query = history_query.copy()
        approved_query["status"] = "Approved"
        approved_count = mongo.db.points_request.count_documents(approved_query)
        
        # ✅ Calculate total points awarded (sum of all approved request points)
        total_points_pipeline = [
            {"$match": approved_query},
            {"$group": {"_id": None, "total_points": {"$sum": "$points"}}}
        ]
        total_points_result = list(mongo.db.points_request.aggregate(total_points_pipeline))
        total_points_awarded = total_points_result[0]["total_points"] if total_points_result else 0
        
        # ✅ Get recent records for display (limited to 5)
        history_cursor = mongo.db.points_request.find(history_query).sort("processed_date", -1).limit(5)
        
        for req_data in history_cursor:
            employee = mongo.db.users.find_one({"_id": req_data.get("user_id")})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            if not employee or not category:
                continue
            
            request_date = req_data["request_date"]
            _, record_quarter_display, _, _, record_fiscal_year_label = get_financial_quarter_and_label(request_date)
            record_quarter_label = f"{record_quarter_display} {record_fiscal_year_label}"
            
            all_records.append({
                'id': str(req_data['_id']),
                'employee_name': employee.get("name", "Unknown"),
                'employee_id': employee.get("employee_id", "N/A"),
                'employee_grade': employee.get("grade", ""),
                'employee_department': employee.get("department", ""),
                'category_name': category.get("name", "Unknown"),
                'title': req_data.get("title", "N/A"),
                'request_date': req_data["request_date"],
                'processed_date': req_data.get("processed_date"),
                'points': req_data["points"],
                'notes': req_data.get("manager_notes", req_data.get("notes", "")),
                'status': req_data.get("status", "Approved"),
                'quarter': record_quarter_label,
                'has_attachment': req_data.get("has_attachment", False)
            })
        
        # Calculate quarterly statistics - Shows ONLY employees with approved points under current manager
        quarterly_stats = {}
        
        # Get current manager's ID
        manager_id = user["_id"]
        
        # Calculate quarter end date for proper range query
        if quarter == 1:
            quarter_end = datetime(actual_calendar_year_of_quarter_start, 6, 30, 23, 59, 59, 999999)
        elif quarter == 2:
            quarter_end = datetime(actual_calendar_year_of_quarter_start, 9, 30, 23, 59, 59, 999999)
        elif quarter == 3:
            quarter_end = datetime(actual_calendar_year_of_quarter_start, 12, 31, 23, 59, 59, 999999)
        else:  # Q4
            quarter_end = datetime(actual_calendar_year_of_quarter_start, 3, 31, 23, 59, 59, 999999)
        
        for grade_key in ALL_GRADES:
            # Get all users with this grade
            grade_employees = list(mongo.db.users.find({"grade": grade_key}))
            grade_employee_ids = [emp["_id"] for emp in grade_employees]
            
            # Always include all grades, even if no employees
            if not grade_employee_ids:
                quarterly_stats[grade_key] = {
                    "total_employees": 0,
                    "employees_with_presales": 0,
                    "employees_with_points": 0,
                    "total_presales_points": 0,
                    "total_points": 0,
                }
                continue
            
            # Date filter for current quarter
            date_filter = {
                "$or": [
                    {"processed_date": {"$gte": quarter_start, "$lte": quarter_end}},
                    {
                        "$and": [
                            {"$or": [
                                {"processed_date": {"$exists": False}},
                                {"processed_date": None}
                            ]},
                            {"request_date": {"$gte": quarter_start, "$lte": quarter_end}}
                        ]
                    }
                ]
            }
            
            # Build category/department filter
            category_conditions = []
            if presales_category_ids:
                category_conditions.append({"category_id": {"$in": presales_category_ids}})
            category_conditions.append({"processed_department": "presales"})
            category_conditions.append({"processed_department": "Pre-Sales"})
            category_conditions.append({"processed_department": {"$regex": "pre.?sales", "$options": "i"}})
            
            # Filter by current manager - check processed_by, assigned_validator, or manager_id
            manager_filter = {
                "$or": [
                    {"processed_by": manager_id},
                    {"assigned_validator": manager_id},
                    {"manager_id": manager_id}
                ]
            }
            
            base_query = {
                "user_id": {"$in": grade_employee_ids},
                "status": "Approved",
                "$and": [
                    {"$or": category_conditions},
                    date_filter,
                    manager_filter
                ]
            }
            
            # Calculate employees with presales points under this manager
            employees_with_presales = mongo.db.points_request.distinct("user_id", base_query)
            
            # Sum of approved presales points for the quarter under this manager
            total_presales_points_cursor = mongo.db.points_request.aggregate([
                {"$match": base_query},
                {"$group": {"_id": None, "total_points": {"$sum": "$points"}}}
            ])
            total_presales_points_list = list(total_presales_points_cursor)
            total_presales_points = total_presales_points_list[0]['total_points'] if total_presales_points_list else 0
            
            # Show all grades with total employees count, but only points under this manager
            quarterly_stats[grade_key] = {
                "total_employees": len(grade_employees),  # Total employees in this grade
                "employees_with_presales": len(employees_with_presales),
                "employees_with_points": len(employees_with_presales),
                "total_presales_points": total_presales_points,
                "total_points": total_presales_points,
            }
        
        return render_template('presales_dashboard.html',
                             user=user,
                             departments=departments,
                             display_quarter=display_quarter,
                             display_month=display_month,
                             current_quarter=current_quarter,
                             quarterly_stats=quarterly_stats,
                             all_records=all_records,
                             pending_requests=pending_requests,
                             rejected_requests=rejected_requests,
                             pending_count=pending_count,
                             processed_count=processed_count,
                             approved_count=approved_count,
                             rejected_count=len(rejected_requests),
                             total_points_awarded=total_points_awarded,
                             employee_view_url=url_for('employee_dashboard.dashboard'))
        
    except Exception as e:
        logger.error(f"Presales Dashboard Error: {str(e)}")
        flash(f'An error occurred while loading the dashboard: {str(e)}', 'danger')
        return redirect(url_for('auth.login'))

@presales_bp.route('/switch_to_employee_view')
def switch_to_employee_view():
    """Switch from presales view to employee view"""
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_presales_access()
    
    if not has_access:
        flash('Invalid action.', 'danger')
        return redirect(url_for('auth.login'))
    
    session['is_acting_as_employee'] = True
    session['original_dashboard'] = 'presales'
    session['original_view_url'] = url_for('presales.dashboard')
    flash('Switched to Employee View. You can now raise requests for yourself.', 'info')
    return redirect(url_for('employee_dashboard.dashboard'))

@presales_bp.route('/switch_to_manager_view')
def switch_to_manager_view():
    """Switch back from employee view to presales view"""
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))
    
    original_url = session.get('original_view_url', url_for('presales.dashboard'))
    
    # Clear the session flags
    session.pop('is_acting_as_employee', None)
    session.pop('original_role', None)
    session.pop('original_view_url', None)
    
    flash('Switched back to Presales View.', 'info')
    return redirect(original_url)
