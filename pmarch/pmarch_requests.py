"""
PM/Arch Requests Module
Handles request processing (approve/reject) for PM/Arch categories
"""
from flask import request, session, redirect, url_for, flash, jsonify, render_template
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import logging
from threading import Thread

from .pmarch_main import pmarch_bp
from .pmarch_helpers import (
    check_pmarch_access, 
    get_pmarch_category_ids,
    get_all_pmarch_category_ids,
    get_financial_quarter_and_label
)
from .pmarch_notifications import send_approval_notification, send_rejection_notification
from .services.request_service import RequestService
from .constants import ERROR_MESSAGES, SUCCESS_MESSAGES, FLASH_CATEGORIES

# ✅ NOTE: Real-time event publishers (publish_request_approved, publish_request_rejected) 
# are called inside RequestService methods to avoid duplicate notifications

logger = logging.getLogger(__name__)

@pmarch_bp.route('/process-request/<request_id>', methods=['POST'])
def process_request(request_id):
    """Process (approve/reject) a PM/Arch request"""
    has_access, user = check_pmarch_access()
    
    if not has_access:
        flash(ERROR_MESSAGES['NOT_LOGGED_IN'] if not user else ERROR_MESSAGES['ACCESS_DENIED'], 
              FLASH_CATEGORIES['WARNING'] if not user else FLASH_CATEGORIES['ERROR'])
        return redirect(url_for('auth.login'))
    
    try:
        # Get and validate request
        points_request = RequestService.get_request_by_id(request_id)
        if not points_request:
            flash(ERROR_MESSAGES['REQUEST_NOT_FOUND'], FLASH_CATEGORIES['ERROR'])
            return redirect(url_for('pm_arch.pending_requests'))
        
        # Validate access
        has_access, error_msg = RequestService.validate_request_access(points_request, user["_id"])
        if not has_access:
            flash(error_msg, FLASH_CATEGORIES['ERROR'])
            return redirect(url_for('pm_arch.pending_requests'))
        
        # Get employee and category
        employee = RequestService.get_employee_by_id(points_request.get("user_id"))
        if not employee:
            flash(ERROR_MESSAGES['EMPLOYEE_NOT_FOUND'], FLASH_CATEGORIES['ERROR'])
            return redirect(url_for('pm_arch.pending_requests'))
        
        category = RequestService.get_category_by_id(points_request["category_id"])
        
        # Get action and notes
        action = request.form.get('action')
        notes = request.form.get('notes', '')
        
        if action not in ['approve', 'reject']:
            flash(ERROR_MESSAGES['INVALID_ACTION'], FLASH_CATEGORIES['ERROR'])
            return redirect(url_for('pm_arch.pending_requests'))
        
        # Process the request
        if action == 'approve':
            success, message, points_award = RequestService.approve_request(request_id, user["_id"], notes)
            if not success:
                flash(message, FLASH_CATEGORIES['ERROR'])
                return redirect(url_for('pm_arch.pending_requests'))
            
            # ✅ NOTE: publish_request_approved() is already called inside RequestService.approve_request()
            # No need to call it again here to avoid duplicate notifications
            
            # Update points_request with response_notes for email
            points_request["response_notes"] = notes
            
            # Send email notifications asynchronously (non-blocking)
            Thread(target=send_approval_notification, args=(
                points_request, employee, user, category
            ), daemon=True).start()
            
            flash(SUCCESS_MESSAGES['REQUEST_APPROVED'].format(
                points=points_request["points"], 
                employee_name=employee.get("name", "employee")
            ), FLASH_CATEGORIES['SUCCESS'])
        else:
            success, message = RequestService.reject_request(request_id, user["_id"], notes)
            if not success:
                flash(message, FLASH_CATEGORIES['ERROR'])
                return redirect(url_for('pm_arch.pending_requests'))
            
            # ✅ NOTE: publish_request_rejected() is already called inside RequestService.reject_request()
            # No need to call it again here to avoid duplicate notifications
            
            # Update points_request with response_notes for email
            points_request["response_notes"] = notes
            
            # Send email notifications asynchronously (non-blocking)
            Thread(target=send_rejection_notification, args=(
                points_request, employee, user, category
            ), daemon=True).start()
            
            flash(SUCCESS_MESSAGES['REQUEST_REJECTED'], FLASH_CATEGORIES['WARNING'])
        
        return redirect(url_for('pm_arch.pending_requests'))
    
    except Exception as e:
        logger.error(f"Error processing request {request_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(ERROR_MESSAGES['PROCESSING_ERROR'], FLASH_CATEGORIES['ERROR'])
        return redirect(url_for('pm_arch.pending_requests'))




@pmarch_bp.route('/pending-requests', methods=['GET'])
def pending_requests():
    """Display pending requests page"""
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_pmarch_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
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
        # Get ALL PM/Arch categories (active + inactive) for displaying existing requests
        all_pmarch_category_ids = get_all_pmarch_category_ids()
        
        if not all_pmarch_category_ids:
            flash('PM/Arch categories not found. Please contact HR.', 'warning')
        
        # Fetch pending requests (includes requests with inactive categories)
        pending_requests_list = []
        if all_pmarch_category_ids:
            pending_cursor = RequestService.get_pending_requests(user_id, all_pmarch_category_ids)
            
            for req_data in pending_cursor:
                employee = RequestService.get_employee_by_id(req_data.get("user_id"))
                category = RequestService.get_category_by_id(req_data.get("category_id"))
                
                if not employee or not category:
                    continue
                
                request_display = RequestService.format_request_for_display(req_data, employee, category)
                
                # Ensure attachment info is included
                request_display['has_attachment'] = req_data.get('has_attachment', False)
                request_display['attachment_filename'] = req_data.get('attachment_filename', '')
                request_display['attachment_id'] = str(req_data.get('attachment_id')) if req_data.get('attachment_id') else None
                
                pending_requests_list.append(request_display)
        
        # Get display quarter and month
        now = datetime.utcnow()
        _, quarter_label_display, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
        display_quarter = f"{quarter_label_display.split()[0]} {fiscal_year_label}"
        display_month = now.strftime("%b %Y").upper()
        
        return render_template('pmarch_pending_requests.html',
                             user=user,
                             pending_requests=pending_requests_list,
                             pending_count=len(pending_requests_list),
                             display_quarter=display_quarter,
                             display_month=display_month)
        
    except Exception as e:
        logger.error(f"Error loading pending requests page: {str(e)}")
        flash('An error occurred while loading pending requests', 'danger')
        return redirect(url_for('pm_arch.dashboard'))


@pmarch_bp.route('/processed-requests', methods=['GET'])
def processed_requests():
    """Display processed requests page"""
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_pmarch_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
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
        # Get ALL PM/Arch categories (active + inactive) for displaying existing requests
        all_pmarch_category_ids = get_all_pmarch_category_ids()
        
        if not all_pmarch_category_ids:
            flash('PM/Arch categories not found. Please contact HR.', 'warning')
        
        # ✅ Fetch processed history - ONLY pmarch department requests
        # Filter by processed_department to show only requests that were processed as pmarch
        # This ensures that if a category is moved to another department, old records stay with pmarch
        all_records = []
        
        # Build query to show:
        # 1. New records with processed_department = "pmarch"
        # 2. Old records without processed_department but with pmarch category_id
        or_conditions = [
            {"processed_department": "pmarch"},  # New records with processed_department
            {"processed_department": {"$regex": "^pm.*arch", "$options": "i"}}  # Handle variations like "PM/Arch"
        ]
        
        # For old records without processed_department, filter by category (includes inactive)
        if all_pmarch_category_ids:
            or_conditions.append({
                "processed_department": {"$exists": False},
                "category_id": {"$in": all_pmarch_category_ids}
            })
        
        query = {
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_by": ObjectId(user_id),
            "$or": or_conditions
        }
        
        history_cursor = mongo.db.points_request.find(query).sort("processed_date", -1).limit(200)
        
        for req_data in history_cursor:
            employee = mongo.db.users.find_one({"_id": req_data.get("user_id")})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
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
                'status': req_data.get("status", "Approved"),
                'quarter': record_quarter_label,
                'has_attachment': req_data.get("has_attachment", False),
                'attachment_filename': req_data.get('attachment_filename', ''),
                'attachment_id': str(req_data.get('attachment_id')) if req_data.get('attachment_id') else None,
                'hr_modified': req_data.get('hr_modified', False)
            })
        
        # Get display quarter and month
        now = datetime.utcnow()
        _, quarter_label_display, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
        display_quarter = f"{quarter_label_display.split()[0]} {fiscal_year_label}"
        display_month = now.strftime("%b %Y").upper()
        
        # Get pending count for sidebar badge (includes inactive categories)
        pending_count = 0
        if all_pmarch_category_ids:
            pending_query = {
                "status": "Pending",
                "assigned_validator_id": ObjectId(user_id),
                "category_id": {"$in": all_pmarch_category_ids}
            }
            pending_count = mongo.db.points_request.count_documents(pending_query)
        
        return render_template('pmarch_processed_requests.html',
                             user=user,
                             all_records=all_records,
                             pending_count=pending_count,
                             display_quarter=display_quarter,
                             display_month=display_month)
        
    except Exception as e:
        logger.error(f"Error loading processed requests page: {str(e)}")
        flash('An error occurred while loading processed requests', 'danger')
        return redirect(url_for('pm_arch.dashboard'))


@pmarch_bp.route('/api/pending-count', methods=['GET'])
def api_pending_count():
    """API endpoint to get current pending request count"""
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'count': 0}), 200
    
    try:
        # Get ALL PM/Arch categories (active + inactive) for counting existing requests
        all_pmarch_category_ids = get_all_pmarch_category_ids()
        
        # Count pending requests (includes inactive categories)
        pending_count = 0
        if all_pmarch_category_ids:
            pending_query = {
                "status": "Pending",
                "assigned_validator_id": ObjectId(user_id),
                "category_id": {"$in": all_pmarch_category_ids}
            }
            pending_count = mongo.db.points_request.count_documents(pending_query)
        
        return jsonify({'count': pending_count}), 200
        
    except Exception as e:
        logger.error(f"Error fetching pending count: {str(e)}")
        return jsonify({'count': 0}), 200
