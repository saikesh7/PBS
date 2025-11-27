from flask import render_template, request, session, redirect, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import sys
import logging
from threading import Thread
from .pm_main import pm_bp

# ✅ IMPORT REAL-TIME PUBLISHER
from services.realtime_events import publish_request_approved, publish_request_rejected

# ✅ IMPORT REQUEST SERVICE AND EMAIL NOTIFICATIONS (matches pmarch/presales pattern)
from pm.services.request_service import RequestService
from pm.pm_notifications import send_approval_notification, send_rejection_notification

logger = logging.getLogger(__name__)

def error_print(message, error=None):

    pass

def check_pm_access():
    """Check if user has PM dashboard access"""
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

def get_pm_categories():
    """
    Get all PM categories from hr_categories collection
    Matches presales and pmarch logic
    """
    return list(mongo.db.hr_categories.find({
        "category_department": "pm",
        "category_status": "active"
    }))

def get_pm_category_ids():
    """Get list of PM category ObjectIds"""
    categories = get_pm_categories()
    return [cat["_id"] for cat in categories]

def get_financial_quarter_and_label(date_obj):
    """
    Returns (quarter_number, quarter_label, quarter_start_month, fiscal_year_label)
    for the given date_obj based on the financial year:
    Q1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar (next year)
    Fiscal year label: e.g., 2024-25 for Q1 2024
    """
    month = date_obj.month
    year = date_obj.year
    
    if 4 <= month <= 6:
        quarter = 1
        quarter_label = "Q1 (Apr-Jun)"
        quarter_start_month = 4
        fiscal_year_start = year
    elif 7 <= month <= 9:
        quarter = 2
        quarter_label = "Q2 (Jul-Sep)"
        quarter_start_month = 7
        fiscal_year_start = year
    elif 10 <= month <= 12:
        quarter = 3
        quarter_label = "Q3 (Oct-Dec)"
        quarter_start_month = 10
        fiscal_year_start = year
    else:  # Jan-Mar
        quarter = 4
        quarter_label = "Q4 (Jan-Mar)"
        quarter_start_month = 1
        fiscal_year_start = year - 1  # Q4 belongs to previous fiscal year
    
    fiscal_year_end_short = str(fiscal_year_start + 1)[-2:]
    fiscal_year_label = f"{fiscal_year_start}-{fiscal_year_end_short}"
    
    return quarter, quarter_label, quarter_start_month, fiscal_year_start, fiscal_year_label

@pm_bp.route('/pending-requests')
def pending_requests():
    """Show pending requests assigned to this PM"""
    has_access, user = check_pm_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get ALL PM categories from hr_categories
        pm_category_ids = get_pm_category_ids()
        
        # Get ONLY requests assigned to this PM user
        requests_cursor = mongo.db.points_request.find({
            "category_id": {"$in": pm_category_ids},
            "status": "Pending",
            "assigned_validator_id": ObjectId(user["_id"])
        }).sort("request_date", -1)
        
        pending_requests_list = []
        for req_data in requests_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            category = mongo.db.hr_categories.find_one({"_id": req_data["category_id"]})
            
            if not employee or not category:
                continue
            
            # Format request data - matches presales/pmarch pattern
            record = {
                'id': str(req_data['_id']),
                'employee_name': employee.get("name", "Unknown"),
                'employee_id': employee.get("employee_id", "N/A"),
                'employee_grade': employee.get("grade", "Unknown"),
                'employee_department': employee.get("department", ""),
                'category_name': category.get("name", "Unknown"),
                'title': req_data.get("title", "N/A"),
                'points': req_data["points"],
                'request_date': req_data["request_date"],
                'notes': req_data.get("submission_notes", req_data.get("request_notes", "")),
                'has_attachment': req_data.get("has_attachment", False),
                'attachment_filename': req_data.get("attachment_filename", ""),
                'attachment_id': str(req_data.get("attachment_id")) if req_data.get("attachment_id") else None
            }
            pending_requests_list.append(record)
        
        # Get display quarter and month
        now = datetime.utcnow()
        _, quarter_label_display, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
        display_quarter = f"{quarter_label_display.split()[0]} {fiscal_year_label}"
        display_month = now.strftime("%b %Y").upper()
        
        return render_template(
            'pm_pending_requests.html', 
            user=user,
            pending_requests=pending_requests_list,
            pending_count=len(pending_requests_list),
            display_quarter=display_quarter,
            display_month=display_month
        )
                             
    except Exception as e:
        error_print("Error loading pending requests", e)
        flash("An error occurred while loading requests", "danger")
        return redirect(url_for('pm.dashboard'))

@pm_bp.route('/process-request/<request_id>', methods=['POST'])
def process_request(request_id):
    """Process (approve/reject) a pending request"""
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        points_request = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not points_request:
            flash('Request not found', 'danger')
            return redirect(url_for('pm.pending_requests'))
        
        # Verify request is assigned to this PM
        if str(points_request.get("assigned_validator_id")) != str(user["_id"]):
            flash('You are not authorized to process this request', 'danger')
            return redirect(url_for('pm.pending_requests'))
        
        # Get employee and category data
        employee = mongo.db.users.find_one({"_id": points_request["user_id"]})
        category = mongo.db.hr_categories.find_one({"_id": points_request["category_id"]})
        
        if not employee or not category:
            flash('Employee or category not found', 'danger')
            return redirect(url_for('pm.pending_requests'))
        
        # Get action and notes
        action = request.form.get('action')
        notes = request.form.get('notes', '')
        
        if action not in ['approve', 'reject']:
            flash('Invalid action', 'danger')
            return redirect(url_for('pm.pending_requests'))
        
        # ✅ PROCESS REQUEST (matches pmarch/presales pattern)
        if action == 'approve':
            success, message, points_award = RequestService.approve_request(
                request_id, 
                str(user["_id"]), 
                notes
            )
            
            if not success:
                flash(message, 'danger')
                return redirect(url_for('pm.pending_requests'))
            
            # ✅ PUBLISH APPROVAL EVENT
            publish_request_approved(
                request_data={
                    "_id": ObjectId(request_id),
                    "category_id": points_request["category_id"],
                    "points": points_request["points"],
                    "created_by_ta_id": points_request.get("created_by_ta_id"),
                    "response_notes": notes
                },
                employee_data=employee,
                approver_data=user,
                points_award_data=points_award
            )
            
            # Update points_request with response_notes for email
            points_request["response_notes"] = notes
            
            # ✅ Send email notifications asynchronously (non-blocking) - matches pmarch/presales
            Thread(target=send_approval_notification, args=(
                points_request, employee, user, category
            ), daemon=True).start()
            
            flash(f'Request approved! {points_request["points"]} points awarded to {employee.get("name", "employee")}', 'success')
        else:
            success, message = RequestService.reject_request(
                request_id, 
                str(user["_id"]), 
                notes
            )
            
            if not success:
                flash(message, 'danger')
                return redirect(url_for('pm.pending_requests'))
            
            # ✅ PUBLISH REJECTION EVENT
            publish_request_rejected(
                request_data={
                    "_id": ObjectId(request_id),
                    "category_id": points_request["category_id"],
                    "points": points_request["points"],
                    "created_by_ta_id": points_request.get("created_by_ta_id"),
                    "response_notes": notes
                },
                employee_data=employee,
                rejector_data=user
            )
            
            # Update points_request with response_notes for email
            points_request["response_notes"] = notes
            
            # ✅ Send email notifications asynchronously (non-blocking) - matches pmarch/presales
            Thread(target=send_rejection_notification, args=(
                points_request, employee, user, category
            ), daemon=True).start()
            
            flash('Request rejected', 'warning')
        
        return redirect(url_for('pm.pending_requests'))
        
    except Exception as e:
        error_print(f"Error processing request {request_id}", e)
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('pm.pending_requests'))

@pm_bp.route('/processed-requests')
def processed_requests():
    """Display processed requests page"""
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get PM categories - ONLY show PM category requests
        pm_category_ids = get_pm_category_ids()
        
        if not pm_category_ids:
            # No PM categories found, return empty list
            all_records = []
        else:
            # Fetch processed history - ONLY PM categories processed by this user
            all_records = []
            history_cursor = mongo.db.points_request.find({
                "status": {"$in": ["Approved", "Rejected"]},
                "category_id": {"$in": pm_category_ids},  # ✅ FILTER BY PM CATEGORIES ONLY
                "processed_by": ObjectId(user_id)
            }).sort("processed_date", -1).limit(200)
        
            for req_data in history_cursor:
                employee = mongo.db.users.find_one({"_id": req_data.get("user_id")})
                
                # Get category from hr_categories (PM categories only)
                category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
                
                if not employee or not category:
                    continue
            
                # Get quarter label for this request
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
                    'notes': req_data.get("response_notes") or req_data.get("manager_notes") or req_data.get("notes", ""),
                    'response_notes': req_data.get("response_notes", ""),
                    'manager_notes': req_data.get("manager_notes", ""),
                    'status': req_data.get("status", "Approved"),
                    'quarter': record_quarter_label,
                    'has_attachment': req_data.get("has_attachment", False),
                    'attachment_filename': req_data.get('attachment_filename', ''),
                    'attachment_id': str(req_data.get('attachment_id')) if req_data.get('attachment_id') else None
                })
        
        # Get display quarter and month
        now = datetime.utcnow()
        _, quarter_label_display, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
        display_quarter = f"{quarter_label_display.split()[0]} {fiscal_year_label}"
        display_month = now.strftime("%b %Y").upper()
        
        # Get pending count for sidebar badge
        pending_count = 0
        if pm_category_ids:
            pending_count = mongo.db.points_request.count_documents({
                "status": "Pending",
                "category_id": {"$in": pm_category_ids},
                "assigned_validator_id": ObjectId(user_id)
            })
        
        return render_template(
            'pm_processed_requests.html',
            user=user,
            all_records=all_records,
            processed_requests=all_records,  # ✅ Pass as both names for template compatibility
            pending_count=pending_count,
            display_quarter=display_quarter,
            display_month=display_month
        )
        
    except Exception as e:
        error_print("Error loading processed requests", e)
        flash("An error occurred while loading processed requests", "danger")
        return redirect(url_for('pm.dashboard'))

@pm_bp.route('/api/pending-count', methods=['GET'])
def api_pending_count():
    """API endpoint to get current pending request count"""
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'count': 0}), 200
    
    try:
        # Get PM categories
        pm_category_ids = get_pm_category_ids()
        
        # Count pending requests
        pending_count = 0
        if pm_category_ids:
            pending_count = mongo.db.points_request.count_documents({
                "status": "Pending",
                "category_id": {"$in": pm_category_ids},
                "assigned_validator_id": ObjectId(user_id)
            })
        
        return jsonify({'count': pending_count}), 200
        
    except Exception as e:
        error_print("Error fetching pending count", e)
        return jsonify({'count': 0}), 200