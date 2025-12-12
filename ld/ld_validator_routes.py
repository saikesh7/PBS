from flask import render_template, request, session, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
from bson import ObjectId

from .ld_main import ld_bp
from .ld_helpers import (
    check_ld_validator_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, emit_updater_history_update,
    get_financial_quarter_dates, get_ld_categories, get_category_by_id,
    get_quarter_label_from_date
)
from utils.error_handling import error_print


@ld_bp.route('/validator/dashboard', methods=['GET', 'POST'])
def validator_dashboard():
    """L&D Validator Dashboard"""
    has_access, user = check_ld_validator_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
            redirect_url = get_user_redirect(user)
            return redirect(redirect_url)
        return redirect(url_for('auth.login'))
    
    current_quarter, current_month = get_financial_quarter_and_month()
    
    try:
        mongo = get_mongo()
        
        # Handle POST requests
        if request.method == 'POST':
            action_type = request.form.get('action_type')
            
            if action_type == 'bulk_approve':
                return handle_bulk_approve(user)
            elif action_type == 'bulk_reject':
                return handle_bulk_reject(user)
            elif action_type == 'single_action':
                return handle_single_action(user)
        
        # GET request - render validator dashboard
        # Fetches categories from both hr_categories and old categories to find all pending requests
        ld_categories = get_ld_categories()
        
        if not ld_categories:
            flash('No L&D categories found in database.', 'warning')
            validator_requests = []
            category_ids = []
        else:
            category_ids = [cat["_id"] for cat in ld_categories]
            
            # Query includes both new (assigned_validator_id) and old (pending_validator_id) field names for backward compatibility
            pending_query = {
                "status": "Pending",
                "category_id": {"$in": category_ids},
                "$or": [
                    {"assigned_validator_id": ObjectId(user['_id'])},  # NEW: Explicitly assigned to this validator
                    {"pending_validator_id": ObjectId(user['_id'])}    # OLD: Pending for this validator (backward compatibility)
                ]
            }
            
            pending_cursor = mongo.db.points_request.find(pending_query).sort("request_date", 1)
            validator_requests = []
            
            for req_data in pending_cursor:
                employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
                updater = mongo.db.users.find_one({"_id": req_data.get("created_by_ld_id")})
                category = get_category_by_id(req_data["category_id"])
                
                if employee and category:
                    # Calculate quarter from event_date (Financial Year: Apr-Mar)
                    event_date = req_data.get("event_date", req_data.get("request_date"))
                    quarter = get_quarter_label_from_date(event_date)
                    
                    # Determine who raised the request
                    if updater:
                        updater_name = updater.get("name", "Unknown")
                    elif req_data.get("created_by") == req_data.get("user_id"):
                        updater_name = "Self (Employee)"
                    else:
                        updater_name = "Unknown"
                    
                    # Support both old (request_notes) and new (submission_notes) field names
                    submission_notes = req_data.get("submission_notes") or req_data.get("request_notes", "")
                    
                    validator_requests.append({
                        'request_id': str(req_data['_id']),
                        'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                        'event_date': event_date.strftime('%d-%m-%Y'),
                        'employee_name': employee.get("name", "Unknown"),
                        'employee_id': employee.get("employee_id", "N/A"),
                        'department': employee.get("department", "N/A"),
                        'grade': employee.get("grade", "Unknown"),
                        'quarter': quarter,
                        'category_name': category.get("name", "Unknown"),
                        'quantity': req_data.get("quantity", 1),
                        'points': req_data.get("points", 0),
                        'notes': submission_notes,
                        'updater_name': updater_name
                    })
        
        # Get history data
        history_data = []
        seen_request_ids = set()
        
        if category_ids:
            # NEW records with category filter
            history_cursor = mongo.db.points_request.find({
                "category_id": {"$in": category_ids},
                "status": {"$in": ["Approved", "Rejected"]},
                "$or": [
                    {"assigned_validator_id": ObjectId(user['_id'])},
                    {"processed_by": ObjectId(user['_id'])}
                ]
            }).sort("response_date", -1)
            
            # OLD records - check ALL possible old field names
            old_history_cursor = mongo.db.points_request.find({
                "status": {"$in": ["Approved", "Rejected"]},
                "$or": [
                    {"pending_validator_id": ObjectId(user['_id'])},  # Old validator field
                    {"actioned_by_ld_id": ObjectId(user['_id'])},  # Old validator field (very old)
                    {"created_by_ld_id": ObjectId(user['_id'])},  # Old updater field (for old LD users)
                    {"pmo_id": ObjectId(user['_id'])},  # Very old field name
                    {"validator_id": ObjectId(user['_id'])},  # Another old field name
                    {"ld_validator_id": ObjectId(user['_id'])}  # Another possible old field
                ]
            }).sort("response_date", -1)
            
            # Also check points collection for old approved records
            old_points_cursor = mongo.db.points.find({
                "$or": [
                    {"awarded_by": ObjectId(user['_id'])},
                    {"validator_id": ObjectId(user['_id'])},
                    {"ld_validator_id": ObjectId(user['_id'])}
                ]
            }).sort("created_at", -1)
            
            # Combine all cursors
            combined_cursor = list(history_cursor) + list(old_history_cursor) + list(old_points_cursor)
            
            for req_data in combined_cursor:
                request_id = str(req_data.get("_id", ""))
                
                # Skip if we've already seen this request
                if request_id in seen_request_ids:
                    continue
                
                seen_request_ids.add(request_id)
                employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
                category = get_category_by_id(req_data["category_id"])
                
                # ✅ Show record even if category doesn't exist (for old records with deleted categories)
                if employee:
                    # Calculate quarter from event_date (Financial Year: Apr-Mar)
                    event_date = req_data.get("event_date")
                    if not event_date and "request_date" in req_data:
                        event_date = req_data["request_date"]
                    if not event_date:
                        continue  # Skip if no date available
                    
                    quarter = get_quarter_label_from_date(event_date)
                    
                    # Support both old (request_notes) and new (submission_notes) field names
                    submission_notes = req_data.get("submission_notes") or req_data.get("request_notes", "")
                    
                    # Determine status - points collection records are always Approved
                    status = req_data.get("status", "Approved")
                    
                    # Get date - handle both points_request and points collection
                    if "response_date" in req_data:
                        display_date = req_data["response_date"]
                    elif "created_at" in req_data:
                        display_date = req_data["created_at"]
                    elif "award_date" in req_data:
                        display_date = req_data["award_date"]
                    else:
                        display_date = req_data.get("request_date", event_date)
                    
                    # Get response notes - check multiple possible field names
                    response_notes = (
                        req_data.get("response_notes") or 
                        req_data.get("validator_notes") or 
                        req_data.get("action_notes") or 
                        req_data.get("notes") or 
                        ""
                    )
                    
                    history_data.append({
                        'date': display_date.strftime('%d-%m-%Y'),
                        'event_date': event_date.strftime('%d-%m-%Y'),
                        'employee': employee.get("name", "Unknown"),
                        'employee_name': employee.get("name", "Unknown"),
                        'employee_id': employee.get("employee_id", "N/A"),
                        'department': employee.get("department", "N/A"),
                        'grade': employee.get("grade", "Unknown"),
                        'quarter': quarter,
                        'category': category.get("name", "Unknown") if category else "Unknown Category",
                        'quantity': req_data.get("quantity", 1),
                        'points': req_data.get("points", 0),
                        'notes': submission_notes,
                        'response_notes': response_notes,
                        'status': status
                    })
        
        # Get filter options with crash protection
        year_options = []
        if history_data:
            try:
                years = set()
                for h in history_data:
                    if h.get('date') and isinstance(h['date'], str) and len(h['date'].split('-')) == 3:
                        years.add(h['date'].split('-')[2])
                year_options = sorted(list(years), reverse=True)
            except Exception:
                year_options = []
        
        quarter_options = ['Q1', 'Q2', 'Q3', 'Q4']
        
        grades = []
        if history_data:
            try:
                grades = sorted(list(set([h['grade'] for h in history_data if h.get('grade')])))
            except Exception:
                grades = []
        
        # ✅ Prepare combined recent activity data (for Recent Activity widget on Dashboard tab)
        # Combines pending requests and history, sorted by most recent activity
        recent_activity_data = []
        
        # Add history (approved/rejected) with response_date as activity_date
        for item in history_data:
            try:
                # Parse the date string to datetime for sorting
                date_parts = item['date'].split('-')
                activity_date = datetime(int(date_parts[2]), int(date_parts[1]), int(date_parts[0]))
            except:
                activity_date = datetime.utcnow()
            
            recent_activity_data.append({
                'employee_name': item['employee'],
                'category_name': item['category'],
                'quantity': item['quantity'],
                'points': item['points'],
                'event_date': item['event_date'],
                'status': item['status'],
                '_activity_date': activity_date
            })
        
        # Add pending requests with request_date as activity_date
        for req in validator_requests:
            try:
                # Parse the date string to datetime for sorting
                date_parts = req['request_date'].split('-')
                activity_date = datetime(int(date_parts[2]), int(date_parts[1]), int(date_parts[0]))
            except:
                activity_date = datetime.utcnow()
            
            recent_activity_data.append({
                'employee_name': req['employee_name'],
                'category_name': req['category_name'],
                'quantity': req['quantity'],
                'points': req['points'],
                'event_date': req['event_date'],
                'status': 'Pending',
                '_activity_date': activity_date
            })
        
        # Sort by most recent activity first
        recent_activity_data.sort(key=lambda x: x['_activity_date'], reverse=True)
        
        return render_template(
            'ld_validator_dashboard.html',
            user=user,
            validator_requests=validator_requests,
            history_data=history_data,
            recent_activity_data=recent_activity_data,  # ✅ NEW: For Recent Activity widget
            ld_categories=ld_categories,
            current_quarter=current_quarter,
            current_month=current_month,
            year_options=year_options,
            quarter_options=quarter_options,
            grades=grades,
            pending_count=len(validator_requests)
        )
    
    except Exception:
        flash('An error occurred while loading the validator dashboard.', 'danger')
        return redirect(url_for('auth.login'))


def handle_single_action(user):
    """Handle single request approve/reject"""
    mongo = get_mongo()
    
    request_id = request.form.get('request_id')
    action = request.form.get('action')
    response_notes = request.form.get('response_notes', '').strip()
    
    if not request_id or not action:
        flash('Invalid request', 'danger')
        return redirect(url_for('ld.validator_dashboard', tab='pending'))
    
    if not response_notes:
        flash('Please provide notes for your decision.', 'danger')
        return redirect(url_for('ld.validator_dashboard', tab='pending'))
    
    try:
        request_doc = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not request_doc or request_doc.get("status") != "Pending":
            flash('Request not found or already processed', 'warning')
            return redirect(url_for('ld.validator_dashboard', tab='pending'))
        
        if action == 'approve':
            mongo.db.points_request.update_one(
                {"_id": ObjectId(request_id)},
                {
                    "$set": {
                        "status": "Approved",
                        "response_date": datetime.utcnow(),
                        "response_notes": response_notes,
                        "processed_by": ObjectId(user['_id'])
                    }
                }
            )
            
            points_record = {
                "user_id": request_doc["user_id"],
                "category_id": request_doc["category_id"],
                "points": request_doc["points"],
                "award_date": request_doc.get("event_date", datetime.utcnow()),
                "awarded_by": ObjectId(user['_id']),
                "notes": response_notes,
                "request_id": ObjectId(request_id),
                "created_at": datetime.utcnow()
            }
            mongo.db.points.insert_one(points_record)

            # Realtime notification - notify employee, updater, and validator
            from services.realtime_events import publish_request_approved
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            # Notify validator dashboard to refresh
            from services.realtime_events import publish_validator_dashboard_refresh
            publish_validator_dashboard_refresh(str(user['_id']), 'ld_validator', 'approved')
            
            # Send approval emails to employee and updater
            from flask import current_app
            from ld.ld_email_service import send_single_approval_emails
            category_data = get_category_by_id(request_doc['category_id'])
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_ld_id')})
            if employee_data and category_data:
                request_doc['response_notes'] = response_notes
                # Send email even if updater_data is None (employee-raised requests)
                send_single_approval_emails(current_app._get_current_object(), mongo, request_doc, employee_data, user, category_data, updater_data)
            
            flash('Request approved successfully', 'success')
        
        elif action == 'reject':
            mongo.db.points_request.update_one(
                {"_id": ObjectId(request_id)},
                {
                    "$set": {
                        "status": "Rejected",
                        "response_date": datetime.utcnow(),
                        "response_notes": response_notes,
                        "processed_by": ObjectId(user['_id'])
                    }
                }
            )
            # Realtime notification - notify employee, updater, and validator
            from services.realtime_events import publish_request_rejected
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Notify validator dashboard to refresh
            from services.realtime_events import publish_validator_dashboard_refresh
            publish_validator_dashboard_refresh(str(user['_id']), 'ld_validator', 'rejected')
            
            # Send rejection email ONLY to updater (not employee)
            from flask import current_app
            from ld.ld_email_service import send_single_rejection_email
            category_data = get_category_by_id(request_doc['category_id'])
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_ld_id')})
            if category_data and updater_data:
                request_doc['response_notes'] = response_notes
                # Only send rejection email if updater exists (not for employee-raised requests)
                send_single_rejection_email(current_app._get_current_object(), mongo, request_doc, employee_data, user, category_data, updater_data)
            
            flash('Request rejected successfully', 'success')
        
        try:
            emit_updater_history_update()
        except:
            pass
        
        return redirect(url_for('ld.validator_dashboard', tab='pending'))
    
    except Exception:
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('ld.validator_dashboard', tab='pending'))



def handle_bulk_approve(user):
    """Handle bulk approval of requests"""
    mongo = get_mongo()
    selected_request_ids = request.form.getlist('selected_requests')
    response_notes = request.form.get('response_notes', 'Bulk approved').strip()
    
    if not selected_request_ids:
        flash('No requests selected for approval.', 'warning')
        return redirect(url_for('ld.validator_dashboard', tab='pending'))
    
    approved_count = 0
    approved_requests_data = []  # Collect for bulk email
    approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})  # Fetch once
    
    # Batch process all requests
    for request_id_str in selected_request_ids:
        try:
            request_id = ObjectId(request_id_str)
            request_doc = mongo.db.points_request.find_one({"_id": request_id})
            
            if not request_doc or request_doc.get("status") != "Pending":
                continue
            
            # Update request status
            mongo.db.points_request.update_one(
                {"_id": request_id},
                {
                    "$set": {
                        "status": "Approved",
                        "response_date": datetime.utcnow(),
                        "response_notes": response_notes,
                        "processed_by": ObjectId(user['_id'])
                    }
                }
            )
            
            # Insert points record
            points_record = {
                "user_id": request_doc["user_id"],
                "category_id": request_doc["category_id"],
                "points": request_doc["points"],
                "award_date": request_doc.get("event_date", datetime.utcnow()),
                "awarded_by": ObjectId(user['_id']),
                "notes": "Bulk approved by L&D Validator",
                "request_id": request_id,
                "created_at": datetime.utcnow()
            }
            mongo.db.points.insert_one(points_record)

            # Collect data for realtime events and emails
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            if employee_data and approver_data:
                # Publish realtime event
                from services.realtime_events import publish_request_approved
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
                
                # Collect for bulk email
                category_data = get_category_by_id(request_doc['category_id'])
                if category_data:
                    request_doc['response_notes'] = response_notes
                    approved_requests_data.append({
                        'request_data': request_doc,
                        'employee': employee_data,
                        'category': category_data
                    })
            
            approved_count += 1
        
        except Exception:
            continue
    
    # Send bulk approval emails in background (non-blocking)
    if approved_requests_data:
        from flask import current_app
        from threading import Thread
        from ld.ld_email_service import send_bulk_approval_emails, send_approval_email_to_employee
        
        # Get updater from first request (all should have same updater in bulk)
        first_request = approved_requests_data[0]['request_data']
        updater_data = mongo.db.users.find_one({'_id': first_request.get('created_by_ld_id')})
        
        # Send bulk email to updater
        if updater_data and updater_data.get('email'):
            # Send emails in background thread to avoid blocking
            app = current_app._get_current_object()
            thread = Thread(target=send_bulk_approval_emails, args=(app, mongo, approved_requests_data, user, updater_data))
            thread.daemon = True
            thread.start()
        
        # Send individual approval emails to each employee
        for req_data in approved_requests_data:
            employee = req_data['employee']
            category = req_data['category']
            request_doc = req_data['request_data']
            
            if employee.get('email'):
                send_approval_email_to_employee(
                    employee_email=employee.get('email'),
                    employee_name=employee.get('name', 'Employee'),
                    category_name=category.get('name', 'Unknown'),
                    points=request_doc.get('points', 0),
                    event_date=request_doc.get('event_date', datetime.utcnow()).strftime('%d-%m-%Y')
                )
    
    # Notify validator dashboard to refresh after bulk approval
    from services.realtime_events import publish_validator_dashboard_refresh
    publish_validator_dashboard_refresh(str(user['_id']), 'ld_validator', 'bulk_approved')
    
    flash(f'Successfully approved {approved_count} requests.', 'success')
    
    try:
        emit_updater_history_update()
    except:
        pass
    
    return redirect(url_for('ld.validator_dashboard', tab='pending'))


def handle_bulk_reject(user):
    """Handle bulk rejection of requests"""
    mongo = get_mongo()
    selected_request_ids = request.form.getlist('selected_requests')
    response_notes = request.form.get('response_notes', 'Bulk rejected').strip()
    
    if not selected_request_ids:
        flash('No requests selected for rejection.', 'warning')
        return redirect(url_for('ld.validator_dashboard', tab='pending'))
    
    rejected_count = 0
    rejected_requests_data = []  # Collect for bulk email
    rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})  # Fetch once
    
    # Batch process all requests
    for request_id_str in selected_request_ids:
        try:
            request_id = ObjectId(request_id_str)
            request_doc = mongo.db.points_request.find_one({"_id": request_id})
            
            if not request_doc or request_doc.get("status") != "Pending":
                continue
            
            # Update request status
            mongo.db.points_request.update_one(
                {"_id": request_id},
                {
                    "$set": {
                        "status": "Rejected",
                        "response_date": datetime.utcnow(),
                        "response_notes": response_notes,
                        "processed_by": ObjectId(user['_id'])
                    }
                }
            )
            
            # Collect data for realtime events and emails
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            if employee_data and rejector_data:
                # Publish realtime event
                from services.realtime_events import publish_request_rejected
                publish_request_rejected(request_doc, employee_data, rejector_data)
                
                # Collect for bulk email
                category_data = get_category_by_id(request_doc['category_id'])
                if category_data:
                    request_doc['response_notes'] = response_notes
                    rejected_requests_data.append({
                        'request_data': request_doc,
                        'employee': employee_data,
                        'category': category_data
                    })

            rejected_count += 1
        
        except Exception:
            continue
    
    # Send bulk rejection email in background (only to updater)
    if rejected_requests_data:
        from flask import current_app
        from threading import Thread
        from ld.ld_email_service import send_bulk_rejection_email
        
        # Get updater from first request (all should have same updater in bulk)
        first_request = rejected_requests_data[0]['request_data']
        updater_data = mongo.db.users.find_one({'_id': first_request.get('created_by_ld_id')})
        
        if updater_data and updater_data.get('email'):
            # Send email in background thread to avoid blocking
            app = current_app._get_current_object()
            thread = Thread(target=send_bulk_rejection_email, args=(app, mongo, rejected_requests_data, user, updater_data, response_notes))
            thread.daemon = True
            thread.start()
        else:
            error_print("Bulk rejection email not sent", f"Updater data missing or no email: {updater_data}")
    
    # Notify validator dashboard to refresh after bulk rejection
    from services.realtime_events import publish_validator_dashboard_refresh
    publish_validator_dashboard_refresh(str(user['_id']), 'ld_validator', 'bulk_rejected')
    
    flash(f'Successfully rejected {rejected_count} requests.', 'success')
    
    try:
        emit_updater_history_update()
    except:
        pass
    
    return redirect(url_for('ld.validator_dashboard', tab='pending'))


@ld_bp.route('/validator/get-pending-requests', methods=['GET'])
def get_pending_requests():
    """Get all pending requests for validator"""
    has_access, user = check_ld_validator_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        ld_categories = get_ld_categories()
        if not ld_categories:
            return jsonify({'success': True, 'requests': []})
        
        category_ids = [cat["_id"] for cat in ld_categories]
        
        # Include both assigned requests (new and old field names for backward compatibility)
        pending_query = {
            "status": "Pending",
            "category_id": {"$in": category_ids},
            "$or": [
                {
                    "assigned_validator_id": ObjectId(user['_id'])
                },  # NEW: Explicitly assigned to this validator
                {
                    "pending_validator_id": ObjectId(user['_id'])
                }  # OLD: Pending for this validator (old field name)
            ]
        }
        
        pending_cursor = mongo.db.points_request.find(pending_query).sort("request_date", 1)
        
        requests = []
        for req_data in pending_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            category = get_category_by_id(req_data["category_id"])
            updater = mongo.db.users.find_one({"_id": req_data.get("created_by_ld_id")})
            
            if employee and category:
                # Calculate quarter from event_date (Financial Year: Apr-Mar)
                event_date = req_data.get("event_date", req_data.get("request_date"))
                quarter = get_quarter_label_from_date(event_date)
                
                # Determine who raised the request
                if updater:
                    updater_name = updater.get("name", "Unknown")
                elif req_data.get("created_by") == req_data.get("user_id"):
                    updater_name = "Self (Employee)"
                else:
                    updater_name = "Unknown"
                
                # Support both old (request_notes) and new (submission_notes) field names
                submission_notes = req_data.get("submission_notes") or req_data.get("request_notes", "")
                
                requests.append({
                    'request_id': str(req_data['_id']),
                    'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'employee_name': employee.get("name", "Unknown"),
                    'employee_id': employee.get("employee_id", "N/A"),
                    'department': employee.get("department", "N/A"),
                    'grade': employee.get("grade", "Unknown"),
                    'quarter': quarter,
                    'category_name': category.get("name", "Unknown"),
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': submission_notes,
                    'updater_name': updater_name
                })
        
        return jsonify({'success': True, 'requests': requests})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ld_bp.route('/validator/check-new-requests')
def check_new_requests():
    """Check for new pending requests"""
    has_access, user = check_ld_validator_access()
    
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 401
    
    try:
        mongo = get_mongo()
        
        last_check = request.args.get('last_check')
        if last_check:
            try:
                last_check_date = datetime.fromisoformat(last_check.replace('Z', ''))
            except:
                last_check_date = datetime.utcnow() - timedelta(minutes=5)
        else:
            last_check_date = datetime.utcnow() - timedelta(minutes=5)
        
        ld_categories = get_ld_categories()
        if not ld_categories:
            return jsonify({'pending_count': 0, 'new_requests': []})
        
        category_ids = [cat["_id"] for cat in ld_categories]
        
        # Get total pending count - include both assigned requests (new and old field names)
        pending_count = mongo.db.points_request.count_documents({
            "status": "Pending",
            "category_id": {"$in": category_ids},
            "$or": [
                {
                    "assigned_validator_id": ObjectId(user['_id'])
                },  # NEW field
                {
                    "pending_validator_id": ObjectId(user['_id'])
                }  # OLD field
            ]
        })
        
        # Get new requests since last check
        # Support both old (pending_validator_id) and new (assigned_validator_id) field names
        new_requests_cursor = mongo.db.points_request.find({
            "status": "Pending",
            "request_date": {"$gt": last_check_date},
            "category_id": {"$in": category_ids},
            "$or": [
                {
                    "assigned_validator_id": ObjectId(user['_id'])
                },  # NEW field
                {
                    "pending_validator_id": ObjectId(user['_id'])
                }  # OLD field
            ]
        }).sort("request_date", -1)
        
        new_requests = []
        for req_data in new_requests_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            category = get_category_by_id(req_data["category_id"])
            
            if employee and category:
                # Support both old (request_notes) and new (submission_notes) field names
                submission_notes = req_data.get("submission_notes") or req_data.get("request_notes", "")
                
                new_requests.append({
                    'employee_name': employee.get("name", "Unknown"),
                    'category_name': category.get("name", "Unknown"),
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': submission_notes
                })
        
        return jsonify({
            'pending_count': pending_count,
            'new_requests': new_requests,
            'count': len(new_requests),
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@ld_bp.route('/validator/get-pending-count', methods=['GET'])
def get_pending_count():
    """Get current pending count for badge update"""
    has_access, user = check_ld_validator_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        ld_categories = get_ld_categories()
        if not ld_categories:
            return jsonify({'success': True, 'pending_count': 0})
        
        category_ids = [cat["_id"] for cat in ld_categories]
        
        # Get total pending count - include both assigned requests (new and old field names)
        pending_count = mongo.db.points_request.count_documents({
            "status": "Pending",
            "category_id": {"$in": category_ids},
            "$or": [
                {
                    "assigned_validator_id": ObjectId(user['_id'])
                },
                {
                    "pending_validator_id": ObjectId(user['_id'])
                }
            ]
        })
        
        return jsonify({
            'success': True,
            'pending_count': pending_count
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
