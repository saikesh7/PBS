"""
PM/Arch Dashboard Module
Handles main dashboard for PM/Arch team members (peer-to-peer validation)
"""
from flask import render_template, request, session, redirect, url_for, flash
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
from gridfs import GridFS
import logging

from .pmarch_main import pmarch_bp
from .pmarch_helpers import (
    check_pmarch_access, get_financial_quarter_and_label,
    get_current_quarter_date_range, get_pmarch_categories,
    get_pmarch_category_ids
)
from .services.request_service import RequestService
from .constants import ALL_GRADES

logger = logging.getLogger(__name__)

@pmarch_bp.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    """Main dashboard for PM/Arch team members - supports peer-to-peer validation"""
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_pmarch_access()
    
    if not has_access:
        flash('You do not have permission to access the PM/Arch dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    # ✅ Check if user still has pmarch dashboard access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    has_pmarch_access = any('pm' in str(access).lower() and 'arch' in str(access).lower() for access in dashboard_access)
    if not has_pmarch_access:
        flash('You no longer have access to the PM/Arch dashboard', 'danger')
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
        logger.debug(f"Fetched {len(all_employees)} employees from 'users' collection")
        
        departments = {}
        for emp in all_employees:
            grade = emp.get('grade', 'Unassigned')
            departments.setdefault(emp.get('department', 'Unassigned'), {}).setdefault(grade, []).append(emp)
        
        # Get PM/Arch categories
        pmarch_categories = get_pmarch_categories()
        pmarch_category_ids = get_pmarch_category_ids()
        
        if not pmarch_categories:
            flash('PM/Arch categories not found. Please contact HR to create categories.', 'warning')
        
        # ✅ Fetch pending requests assigned to this PM/Arch member (peer validation)
        # Shows requests from OTHER PM/Arch members that this user needs to approve
        pending_requests = []
        
        # ✅ Build query with PMArch category filter
        pending_query = {
            "status": "Pending",
            "assigned_validator_id": ObjectId(user_id),
            "created_by_pmarch_id": {"$ne": ObjectId(user_id)}  # Exclude own requests
        }
        
        # ✅ Filter by PMArch category IDs only
        if pmarch_category_ids:
            pending_query["category_id"] = {"$in": pmarch_category_ids}
        
        pending_cursor = mongo.db.points_request.find(pending_query).sort("request_date", -1)
        
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
        
        # ✅ Fetch rejected requests separately - ONLY pmarch categories
        rejected_requests = []
        rejected_query = {
            "status": "Rejected",
            "processed_by": ObjectId(user_id)
        }
        
        # ✅ Filter by pmarch category IDs only
        if pmarch_category_ids:
            rejected_query["category_id"] = {"$in": pmarch_category_ids}
        
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
        
        # ✅ Fetch processed history - ONLY pmarch categories
        all_records = []
        history_query = {
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_by": ObjectId(user_id)
        }
        
        # ✅ Filter by pmarch category IDs only
        if pmarch_category_ids:
            history_query["category_id"] = {"$in": pmarch_category_ids}
        
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
        
        # ✅ FIXED: Calculate quarterly statistics (PM/ARCH categories only)
        quarterly_stats = {}
        for grade_key in ALL_GRADES:
            grade_employees = list(mongo.db.users.find({"role": "Employee", "grade": grade_key}))
            grade_employee_ids = [emp["_id"] for emp in grade_employees]
            
            if not grade_employee_ids:
                quarterly_stats[grade_key] = {
                    "total_employees": 0,
                    "employees_with_pmarch": 0,
                    "employees_with_points": 0,
                    "total_pmarch_points": 0,
                    "total_points": 0,
                }
                continue
            
            # ✅ FIXED: Calculate employees with pmarch points (PM/ARCH categories only)
            employees_with_pmarch = mongo.db.points_request.distinct("user_id", {
                "user_id": {"$in": grade_employee_ids},
                "category_id": {"$in": pmarch_category_ids},  # ✅ Critical: Only PM/Arch categories
                "processed_date": {"$gte": quarter_start},  # ✅ Use processed_date for consistency
                "status": "Approved",
                "processed_by": ObjectId(user_id)
            })
            
            # ✅ FIXED: Sum of approved pmarch points (PM/ARCH categories only)
            total_pmarch_points_cursor = mongo.db.points_request.aggregate([
                {"$match": {
                    "user_id": {"$in": grade_employee_ids},
                    "category_id": {"$in": pmarch_category_ids},  # ✅ Critical: Only PM/Arch categories
                    "processed_date": {"$gte": quarter_start},  # ✅ Use processed_date for consistency
                    "status": "Approved",
                    "processed_by": ObjectId(user_id)
                }},
                {"$group": {"_id": None, "total_points": {"$sum": "$points"}}}
            ])
            total_pmarch_points_list = list(total_pmarch_points_cursor)
            total_pmarch_points = total_pmarch_points_list[0]['total_points'] if total_pmarch_points_list else 0
            
            quarterly_stats[grade_key] = {
                "total_employees": len(grade_employees),
                "employees_with_pmarch": len(employees_with_pmarch),
                "employees_with_points": len(employees_with_pmarch),
                "total_pmarch_points": total_pmarch_points,
                "total_points": total_pmarch_points,
            }
        
        return render_template('pmarch_dashboard.html',
                             user=user,
                             departments=departments,
                             display_quarter=display_quarter,
                             display_month=display_month,
                             current_quarter=current_quarter,
                             quarterly_stats=quarterly_stats,
                             all_records=all_records,
                             pending_requests=pending_requests,
                             rejected_requests=rejected_requests,
                             pending_count=len(pending_requests),
                             rejected_count=len(rejected_requests),
                             employee_view_url=url_for('employee_dashboard.dashboard'))
        
    except Exception as e:
        logger.error(f"PM/Arch Dashboard Error: {str(e)}")
        flash(f'An error occurred while loading the dashboard: {str(e)}', 'danger')
        return redirect(url_for('auth.login'))


@pmarch_bp.route('/switch_to_employee_view')
def switch_to_employee_view():
    """Switch from PM/Arch view to employee view"""
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_pmarch_access()
    
    if not has_access:
        flash('Invalid action.', 'danger')
        return redirect(url_for('auth.login'))
    
    session['is_acting_as_employee'] = True
    session['original_dashboard'] = 'pmarch'
    session['original_view_url'] = url_for('pm_arch.dashboard')
    flash('Switched to Employee View. You can now raise requests for yourself.', 'info')
    return redirect(url_for('employee_dashboard.dashboard'))


@pmarch_bp.route('/switch_to_manager_view')
def switch_to_manager_view():
    """Switch back from employee view to PM/Arch view"""
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))
    
    original_url = session.get('original_view_url', url_for('pm_arch.dashboard'))
    
    # Clear the session flags
    session.pop('is_acting_as_employee', None)
    session.pop('original_role', None)
    session.pop('original_view_url', None)
    
    flash('Switched back to PM/Arch View.', 'info')
    return redirect(original_url)
