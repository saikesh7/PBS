"""
Presales Requests Module
Handles request processing (approve/reject) for presales categories
"""
from flask import request, session, redirect, url_for, flash, jsonify, render_template
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import logging
from threading import Thread

from .presales_main import presales_bp
from .presales_helpers import (
    check_presales_access, 
    get_presales_category_ids, 
    get_financial_quarter_and_label
)
from .presales_notifications import send_approval_notification, send_rejection_notification
from .services.request_service import RequestService
from .constants import ERROR_MESSAGES, SUCCESS_MESSAGES, FLASH_CATEGORIES
from services.realtime_events import publish_request_approved, publish_request_rejected

logger = logging.getLogger(__name__)

@presales_bp.route('/process-request/<request_id>', methods=['POST'])
def process_request(request_id):
    """Process (approve/reject) a presales request"""
    has_access, user = check_presales_access()
    
    if not has_access:
        flash(ERROR_MESSAGES['NOT_LOGGED_IN'] if not user else ERROR_MESSAGES['ACCESS_DENIED'], 
              FLASH_CATEGORIES['WARNING'] if not user else FLASH_CATEGORIES['ERROR'])
        return redirect(url_for('auth.login'))
    
    try:
        # Get and validate request
        points_request = RequestService.get_request_by_id(request_id)
        if not points_request:
            flash(ERROR_MESSAGES['REQUEST_NOT_FOUND'], FLASH_CATEGORIES['ERROR'])
            return redirect(url_for('presales.pending_requests'))
        
        # Validate access
        has_access, error_msg = RequestService.validate_request_access(points_request, user["_id"])
        if not has_access:
            flash(error_msg, FLASH_CATEGORIES['ERROR'])
            return redirect(url_for('presales.pending_requests'))
        
        # Get employee and category
        employee = RequestService.get_employee_by_id(points_request.get("user_id"))
        if not employee:
            flash(ERROR_MESSAGES['EMPLOYEE_NOT_FOUND'], FLASH_CATEGORIES['ERROR'])
            return redirect(url_for('presales.pending_requests'))
        
        category = RequestService.get_category_by_id(points_request["category_id"])
        
        # Get action and notes
        action = request.form.get('action')
        notes = request.form.get('notes', '')
        
        if action not in ['approve', 'reject']:
            flash(ERROR_MESSAGES['INVALID_ACTION'], FLASH_CATEGORIES['ERROR'])
            return redirect(url_for('presales.pending_requests'))
        
        # Process the request
        if action == 'approve':
            success, message, points_award = RequestService.approve_request(request_id, user["_id"], notes)
            if not success:
                flash(message, FLASH_CATEGORIES['ERROR'])
                return redirect(url_for('presales.pending_requests'))
            
            # ✅ PUBLISH APPROVAL EVENT (matches PM logic)
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
                return redirect(url_for('presales.pending_requests'))
            
            # ✅ PUBLISH REJECTION EVENT (matches PM logic)
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
            
            # Send email notifications asynchronously (non-blocking)
            Thread(target=send_rejection_notification, args=(
                points_request, employee, user, category
            ), daemon=True).start()
            
            flash(SUCCESS_MESSAGES['REQUEST_REJECTED'], FLASH_CATEGORIES['WARNING'])
        
        return redirect(url_for('presales.pending_requests'))
    
    except Exception as e:
        logger.error(f"Error processing request {request_id}: {str(e)}")
        flash(ERROR_MESSAGES['PROCESSING_ERROR'], FLASH_CATEGORIES['ERROR'])
        return redirect(url_for('presales.pending_requests'))

@presales_bp.route('/fetch_pending_requests', methods=['GET'])
def fetch_pending_requests():
    """Fetch all pending requests for the current user"""
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'You need to log in first'}), 401
    
    if manager_level != 'Pre-sales':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    try:
        # Get presales categories
        presales_category_ids = get_presales_category_ids()
        
        if not presales_category_ids:
            logger.error("Presales categories not found in fetch_pending_requests.")
            return jsonify({'success': False, 'message': 'Presales categories not found'}), 500
        
        # Get pending requests
        pending_cursor = RequestService.get_pending_requests(user_id, presales_category_ids)
        
        # Format requests for JSON response
        pending_requests = []
        for req in pending_cursor:
            emp = RequestService.get_employee_by_id(req.get("user_id"))
            category_doc = RequestService.get_category_by_id(req.get("category_id"))
            
            if not emp or not category_doc:
                continue
            
            # Get attachment info
            attachment_info = RequestService.get_attachment_info(req)
            if attachment_info["has_attachment"]:
                attachment_info["download_url"] = url_for('presales.get_attachment', request_id=str(req["_id"]))
            
            # Format request data
            request_data = RequestService.format_request_for_display(req, emp, category_doc)
            request_data['attachment'] = attachment_info
            
            pending_requests.append(request_data)
        
        return jsonify({'success': True, 'data': pending_requests})
    
    except Exception as e:
        logger.error(f"Error fetching pending requests: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@presales_bp.route('/pending-requests', methods=['GET'])
def pending_requests():
    """Display pending requests page"""
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_presales_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
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
        # Get presales categories
        presales_category_ids = get_presales_category_ids()
        
        if not presales_category_ids:
            flash('Presales categories not found. Please contact HR.', 'warning')
        
        # Fetch pending requests
        pending_requests_list = []
        if presales_category_ids:
            pending_cursor = RequestService.get_pending_requests(user_id, presales_category_ids)
            
            for req_data in pending_cursor:
                employee = RequestService.get_employee_by_id(req_data.get("user_id"))
                category = RequestService.get_category_by_id(req_data.get("category_id"))
                
                if not employee or not category:
                    continue
                
                # Format request data
                record = RequestService.format_request_for_display(req_data, employee, category)
                record['request_date'] = req_data["request_date"]  # Keep as datetime for template
                
                pending_requests_list.append(record)
        
        # Get display quarter and month
        now = datetime.utcnow()
        _, quarter_label_display, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
        display_quarter = f"{quarter_label_display.split()[0]} {fiscal_year_label}"
        display_month = now.strftime("%b %Y").upper()
        
        return render_template('presales_pending_requests.html',
                             user=user,
                             pending_requests=pending_requests_list,
                             pending_count=len(pending_requests_list),
                             display_quarter=display_quarter,
                             display_month=display_month)
        
    except Exception as e:
        logger.error(f"Error loading pending requests page: {str(e)}")
        flash('An error occurred while loading pending requests', 'danger')
        return redirect(url_for('presales.dashboard'))

@presales_bp.route('/processed-requests', methods=['GET'])
def processed_requests():
    """Display processed requests page"""
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    has_access, user = check_presales_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
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
        # Get presales categories
        presales_category_ids = get_presales_category_ids()
        
        if not presales_category_ids:
            flash('Presales categories not found. Please contact HR.', 'warning')
        
        # ✅ Fetch processed history - ONLY presales categories
        all_records = []
        query = {
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_by": ObjectId(user_id)
        }
        
        # ✅ Filter by presales category IDs only
        if presales_category_ids:
            query["category_id"] = {"$in": presales_category_ids}
        
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
                'notes': req_data.get("manager_notes", req_data.get("notes", "")),
                'status': req_data.get("status", "Approved"),
                'quarter': record_quarter_label,
                'has_attachment': req_data.get("has_attachment", False)
            })
        
        # Get display quarter and month
        now = datetime.utcnow()
        _, quarter_label_display, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
        display_quarter = f"{quarter_label_display.split()[0]} {fiscal_year_label}"
        display_month = now.strftime("%b %Y").upper()
        
        # Get pending count for sidebar badge
        pending_count = 0
        if presales_category_ids:
            pending_count = mongo.db.points_request.count_documents({
                "status": "Pending",
                "category_id": {"$in": presales_category_ids},
                "assigned_validator_id": ObjectId(user_id)
            })
        
        return render_template('presales_processed_requests.html',
                             user=user,
                             all_records=all_records,
                             pending_count=pending_count,
                             display_quarter=display_quarter,
                             display_month=display_month)
        
    except Exception as e:
        logger.error(f"Error loading processed requests page: {str(e)}")
        flash('An error occurred while loading processed requests', 'danger')
        return redirect(url_for('presales.dashboard'))

@presales_bp.route('/api/pending-count', methods=['GET'])
def api_pending_count():
    """API endpoint to get current pending request count"""
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'count': 0}), 200
    
    try:
        # Get presales categories
        presales_category_ids = get_presales_category_ids()
        
        # Count pending requests
        pending_count = 0
        if presales_category_ids:
            pending_count = mongo.db.points_request.count_documents({
                "status": "Pending",
                "category_id": {"$in": presales_category_ids},
                "assigned_validator_id": ObjectId(user_id)
            })
        
        return jsonify({'count': pending_count}), 200
        
    except Exception as e:
        logger.error(f"Error fetching pending count: {str(e)}")
        return jsonify({'count': 0}), 200
