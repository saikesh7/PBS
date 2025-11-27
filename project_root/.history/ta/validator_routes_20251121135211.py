from flask import render_template, request, session, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
from bson import ObjectId

from .ta_main import ta_bp
from .helpers import (
    check_ta_validator_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, emit_updater_history_update,
    get_financial_quarter_dates, get_ta_categories
)
from .ta_email_service import (
    send_approval_email_to_updater, send_rejection_email_to_updater,
    send_approval_email_to_employee, send_bulk_approval_email_to_updater,
    send_bulk_rejection_email_to_updater
)
from utils.error_handling import error_print


@ta_bp.route('/validator/dashboard', methods=['GET', 'POST'])
def validator_dashboard():
    """TA Validator Dashboard"""
    has_access, user = check_ta_validator_access()
    
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
        ta_categories = get_ta_categories()
        
        if not ta_categories:
            flash('No TA categories found in database.', 'warning')
        
        category_ids = [cat["_id"] for cat in ta_categories] if ta_categories else []
        
        # Fetch pending requests assigned to this validator
        # Include both:
        # 1. TA updater-created requests (filtered by TA category_ids)
        # 2. Employee-raised requests with TA department (regardless of category_type)
        pending_cursor = mongo.db.points_request.find({
            "status": "Pending",
            "$and": [
                {
                    "$or": [
                        {"assigned_validator_id": ObjectId(user['_id'])},
                        {"pending_validator_id": ObjectId(user['_id'])},
                        {"validator_id": ObjectId(user['_id'])}
                    ]
                },
                {
                    "$or": [
                        {"category_id": {"$in": category_ids}},  # TA updater requests
                        {"category_department": {"$regex": "^ta", "$options": "i"}}  # Employee-raised TA requests
                    ]
                }
            ]
        }).sort("request_date", 1)
        
        validator_requests = []
        for req_data in pending_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            
            # Try multiple field names for updater (old data might use different field names)
            updater_id = req_data.get("created_by_ta_id") or req_data.get("created_by_pmo_id") or req_data.get("created_by") or req_data.get("submitted_by") or req_data.get("raised_by")
            updater = None
            updater_name = "Self-Submitted"  # Default if no updater found
            
            if updater_id:
                updater = mongo.db.users.find_one({"_id": updater_id})
                if updater:
                    updater_name = updater.get("name", "Unknown")
            else:
                # If no updater_id, check if employee raised it themselves
                if req_data.get("updated_by") == "Employee":
                    updater_name = "Self-Submitted"
                elif req_data.get("updated_by") == "TA":
                    updater_name = "TA Updater"
                elif req_data.get("updated_by") == "PMO":
                    updater_name = "PMO Updater"
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            if employee and category:
                # Try multiple field names for notes (old data might use different field names)
                # Check all possible note fields and use the first non-empty one
                notes = (
                    req_data.get("submission_notes") or 
                    req_data.get("request_notes") or 
                    req_data.get("notes") or 
                    req_data.get("employee_notes") or 
                    req_data.get("description") or 
                    req_data.get("comment") or 
                    "No notes provided"
                )
                
                validator_requests.append({
                    'request_id': str(req_data['_id']),
                    'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                    'event_date': req_data.get("event_date", req_data["request_date"]).strftime('%d-%m-%Y'),
                    'employee_name': employee.get("name", "Unknown"),
                    'employee_id': employee.get("employee_id", "N/A"),
                    'grade': employee.get("grade", "Unknown"),
                    'department': employee.get("department", "N/A"),
                    'category_name': category.get("name", "Unknown"),
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': notes,
                    'updater_name': updater_name
                })
        
        # Get history data from points_request (matches PMO logic with old field names)
        # Track seen request IDs to avoid duplicates
        seen_request_ids = set()
        history_data = []
        
        # NEW records - check assigned_validator_id or processed_by
        history_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "$or": [
                {"assigned_validator_id": ObjectId(user['_id'])},
                {"processed_by": ObjectId(user['_id'])}
            ]
        }).sort("response_date", -1)
        
        # OLD records without new field names (old categories may have been deleted)
        old_history_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "$or": [
                {"ta_validator_id": ObjectId(user['_id'])},  # Old validator field
                {"pending_validator_id": ObjectId(user['_id'])},  # Old validator field
                {"validator_id": ObjectId(user['_id'])}  # Old validator field
            ]
        }).sort("response_date", -1)
        
        # Combine both cursors
        combined_cursor = list(history_cursor) + list(old_history_cursor)
        
        for req_data in combined_cursor:
            request_id = str(req_data.get("_id", ""))
            
            # Skip if we've already seen this request
            if request_id in seen_request_ids:
                continue
            
            seen_request_ids.add(request_id)
            
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            # Only show records where BOTH employee AND category exist (matches TA Updater logic)
            if employee and category:
                # Try multiple field names for notes (old data might use different field names)
                # Check all possible note fields and use the first non-empty one
                notes = (
                    req_data.get("response_notes") or 
                    req_data.get("manager_notes") or 
                    req_data.get("submission_notes") or 
                    req_data.get("request_notes") or 
                    req_data.get("notes") or 
                    req_data.get("employee_notes") or 
                    req_data.get("description") or 
                    "No notes"
                )
                
                # Use processed_date for history display (matches PMO logic)
                processed_date = req_data.get("processed_date") or req_data.get("response_date") or req_data.get("request_date")
                event_date = req_data.get("event_date") or req_data.get("request_date")
                
                history_data.append({
                    'request_id': request_id,
                    'date': processed_date.strftime('%d-%m-%Y') if processed_date else "N/A",
                    'event_date': event_date.strftime('%d-%m-%Y') if event_date else "N/A",
                    'employee': employee.get("name", "Unknown"),
                    'grade': employee.get("grade", "Unknown"),
                    'category': category.get("name", "Unknown"),
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': notes,
                    'status': req_data.get("status", "Unknown")
                })
        
        # Also fetch from points collection (matches PMO logic exactly)
        # Get awards given by this validator
        
        # Fetch awards from points collection - ONLY awarded by this validator
        points_cursor = mongo.db.points.find({
            "awarded_by": ObjectId(user['_id'])
        }).sort("award_date", -1).limit(100)
        
        for point in points_cursor:
            # Skip if we already have this from points_request
            point_request_id = str(point.get("request_id", ""))
            if point_request_id and point_request_id in seen_request_ids:
                continue
            
            employee = mongo.db.users.find_one({"_id": point["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": point.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": point.get("category_id")})
            
            if employee and category:
                # Use award_date (which is the event_date) for history display
                event_date = point.get("award_date") or point.get("event_date") or point.get("created_at")
                
                history_data.append({
                    'date': event_date.strftime('%d-%m-%Y'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'employee': employee.get("name", "Unknown"),
                    'grade': employee.get("grade", "Unknown"),
                    'category': category.get("name", "Unknown"),
                    'quantity': point.get("quantity", 1),
                    'points': point.get("points", 0),
                    'notes': point.get("notes", ""),
                    'status': 'Approved'
                })
        
        # Get filter options
        year_options = sorted(list(set([h['date'].split('-')[2] for h in history_data])), reverse=True) if history_data else []
        
        # Dynamically generate quarter options based on actual data
        quarters_set = set()
        for h in history_data:
            date_parts = h['date'].split('-')
            month = int(date_parts[1])
            # Determine fiscal quarter based on month
            if month in [4, 5, 6]:
                quarters_set.add('Q1')
            elif month in [7, 8, 9]:
                quarters_set.add('Q2')
            elif month in [10, 11, 12]:
                quarters_set.add('Q3')
            elif month in [1, 2, 3]:
                quarters_set.add('Q4')
        
        # Sort quarters in order Q1, Q2, Q3, Q4
        quarter_order = ['Q1', 'Q2', 'Q3', 'Q4']
        quarter_options = [q for q in quarter_order if q in quarters_set]
        
        grades = sorted(list(set([h['grade'] for h in history_data]))) if history_data else []
        
        # Calculate processed count (total history records) - matches PM dashboard
        processed_count = len(history_data)
        
        # Get tab parameter from URL
        tab = request.args.get('tab', 'dashboard')
        
        return render_template(
            'validator_dashboard.html',
            user=user,
            validator_requests=validator_requests,
            history_data=history_data,
            ta_categories=ta_categories,
            current_quarter=current_quarter,
            current_month=current_month,
            year_options=year_options,
            quarter_options=quarter_options,
            grades=grades,
            pending_count=len(validator_requests),
            processed_count=processed_count,
            tab=tab
        )
    
    except Exception as e:
        error_print("Error in TA validator dashboard", e)
        flash('An error occurred while loading the validator dashboard.', 'danger')
        return redirect(url_for('auth.login'))


def handle_single_action(user):
    """Handle single request approve/reject"""
    mongo = get_mongo()
    
    # Get current tab from form or default to 'review'
    current_tab = request.form.get('current_tab', 'review')
    
    request_id = request.form.get('request_id')
    action = request.form.get('action')
    response_notes = request.form.get('response_notes', '').strip()
    
    if not request_id or not action:
        flash('Invalid request', 'danger')
        return redirect(url_for('ta.validator_dashboard', tab=current_tab))
    
    # ✅ Validate notes are provided
    if not response_notes:
        flash('Please provide notes for your decision.', 'danger')
        return redirect(url_for('ta.validator_dashboard', tab=current_tab))
    
    try:
        request_doc = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not request_doc or request_doc.get("status") != "Pending":
            flash('Request not found or already processed', 'warning')
            return redirect(url_for('ta.validator_dashboard', tab=current_tab))
        
        if action == 'approve':
            # Update request status
            mongo.db.points_request.update_one(
                {"_id": ObjectId(request_id)},
                {
                    "$set": {
                        "status": "Approved",
                        "response_date": datetime.utcnow(),
                        "response_notes": response_notes,  # ✅ Now always has value
                        "processed_by": ObjectId(user['_id'])
                    }
                }
            )
            
            # Add points record
            points_record = {
                "user_id": request_doc["user_id"],
                "category_id": request_doc["category_id"],
                "points": request_doc["points"],
                "award_date": request_doc.get("event_date", datetime.utcnow()),
                "awarded_by": ObjectId(user['_id']),
                "notes": response_notes,  # ✅ Use actual notes
                "request_id": ObjectId(request_id),
                "created_at": datetime.utcnow()
            }
            mongo.db.points.insert_one(points_record)

            # Realtime notification
            from services.realtime_events import publish_request_approved
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_ta_id')})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            # Send email to updater
            if updater_data and updater_data.get('email') and category_data:
                send_approval_email_to_updater(
                    updater_email=updater_data.get('email'),
                    updater_name=updater_data.get('name', 'TA Updater'),
                    employee_name=employee_data.get('name', 'Unknown') if employee_data else 'Unknown',
                    category_name=category_data.get('name', 'Unknown'),
                    points=request_doc.get('points', 0),
                    validator_name=user.get('name', 'Validator')
                )
            
            # Send email to employee
            if employee_data and employee_data.get('email') and category_data:
                send_approval_email_to_employee(
                    employee_email=employee_data.get('email'),
                    employee_name=employee_data.get('name', 'Employee'),
                    category_name=category_data.get('name', 'Unknown'),
                    points=request_doc.get('points', 0),
                    event_date=request_doc.get('event_date', datetime.utcnow()).strftime('%d-%m-%Y')
                )
            
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
            
            # Realtime notification
            from services.realtime_events import publish_request_rejected
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_ta_id')})
            
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Send email to updater (only updater gets rejection email, not employee)
            if updater_data and updater_data.get('email') and category_data:
                send_rejection_email_to_updater(
                    updater_email=updater_data.get('email'),
                    updater_name=updater_data.get('name', 'TA Updater'),
                    employee_name=employee_data.get('name', 'Unknown') if employee_data else 'Unknown',
                    category_name=category_data.get('name', 'Unknown'),
                    validator_name=user.get('name', 'Validator'),
                    rejection_notes=response_notes
                )
            
            flash('Request rejected successfully', 'success')
        
        try:
            emit_updater_history_update()
        except:
            pass
        
        return redirect(url_for('ta.validator_dashboard', tab=current_tab))
    
    except Exception as e:
        error_print("Error processing request action", e)
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('ta.validator_dashboard', tab=current_tab))



def handle_bulk_approve(user):
    """Handle bulk approval of requests"""
    mongo = get_mongo()
    
    # Get current tab from form or default to 'review'
    current_tab = request.form.get('current_tab', 'review')
    
    selected_request_ids = request.form.getlist('selected_requests')
    
    if not selected_request_ids:
        flash('No requests selected for approval.', 'warning')
        return redirect(url_for('ta.validator_dashboard', tab=current_tab))
    
    approved_count = 0
    updaters_notified = {}  # Track updaters for bulk email
    employees_to_notify = []  # Track employees for individual emails
    
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
                        "response_notes": "Bulk approved",
                        "processed_by": ObjectId(user['_id'])
                    }
                }
            )
            
            # Add points record
            points_record = {
                "user_id": request_doc["user_id"],
                "category_id": request_doc["category_id"],
                "points": request_doc["points"],
                "award_date": request_doc.get("event_date", datetime.utcnow()),
                "awarded_by": ObjectId(user['_id']),
                "notes": "Bulk approved by TA Validator",
                "request_id": request_id,
                "created_at": datetime.utcnow()
            }
            mongo.db.points.insert_one(points_record)

            # Realtime notification
            from services.realtime_events import publish_request_approved
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            # Track updater for bulk email
            updater_id = request_doc.get('created_by_ta_id')
            if updater_id:
                updater_id_str = str(updater_id)
                if updater_id_str not in updaters_notified:
                    updater_data = mongo.db.users.find_one({'_id': updater_id})
                    if updater_data:
                        updaters_notified[updater_id_str] = {
                            'updater': updater_data,
                            'count': 0
                        }
                if updater_id_str in updaters_notified:
                    updaters_notified[updater_id_str]['count'] += 1
            
            # Track employee for individual email
            if employee_data and employee_data.get('email') and category_data:
                employees_to_notify.append({
                    'email': employee_data.get('email'),
                    'name': employee_data.get('name', 'Employee'),
                    'category': category_data.get('name', 'Unknown'),
                    'points': request_doc.get('points', 0),
                    'event_date': request_doc.get('event_date', datetime.utcnow()).strftime('%d-%m-%Y')
                })
            
            approved_count += 1
        
        except Exception as e:
            error_print(f"Error approving request {request_id_str}", e)
            continue
    
    # Send single bulk email to each updater
    for updater_id, data in updaters_notified.items():
        updater = data['updater']
        count = data['count']
        if updater.get('email'):
            send_bulk_approval_email_to_updater(
                updater_email=updater.get('email'),
                updater_name=updater.get('name', 'TA Updater'),
                approved_count=count,
                validator_name=user.get('name', 'Validator')
            )
    
    # Send individual emails to each employee
    for emp_data in employees_to_notify:
        send_approval_email_to_employee(
            employee_email=emp_data['email'],
            employee_name=emp_data['name'],
            category_name=emp_data['category'],
            points=emp_data['points'],
            event_date=emp_data['event_date']
        )
    
    flash(f'Successfully approved {approved_count} requests.', 'success')
    
    try:
        emit_updater_history_update()
    except:
        pass
    
    return redirect(url_for('ta.validator_dashboard', tab=current_tab))


def handle_bulk_reject(user):
    """Handle bulk rejection of requests"""
    mongo = get_mongo()
    
    # Get current tab from form or default to 'review'
    current_tab = request.form.get('current_tab', 'review')
    
    selected_request_ids = request.form.getlist('selected_requests')
    rejection_notes = request.form.get('rejection_notes', 'No reason provided')
    
    if not selected_request_ids:
        flash('No requests selected for rejection.', 'warning')
        return redirect(url_for('ta.validator_dashboard', tab=current_tab))
    
    rejected_count = 0
    updaters_notified = {}  # Track updaters for bulk email
    
    for request_id_str in selected_request_ids:
        try:
            request_id = ObjectId(request_id_str)
            request_doc = mongo.db.points_request.find_one({"_id": request_id})
            
            if not request_doc or request_doc.get("status") != "Pending":
                continue
            
            mongo.db.points_request.update_one(
                {"_id": request_id},
                {
                    "$set": {
                        "status": "Rejected",
                        "response_date": datetime.utcnow(),
                        "response_notes": rejection_notes,
                        "processed_by": ObjectId(user['_id'])
                    }
                }
            )
            
            # Realtime notification
            from services.realtime_events import publish_request_rejected
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Track updater for bulk email
            updater_id = request_doc.get('created_by_ta_id')
            if updater_id:
                updater_id_str = str(updater_id)
                if updater_id_str not in updaters_notified:
                    updater_data = mongo.db.users.find_one({'_id': updater_id})
                    if updater_data:
                        updaters_notified[updater_id_str] = {
                            'updater': updater_data,
                            'count': 0
                        }
                if updater_id_str in updaters_notified:
                    updaters_notified[updater_id_str]['count'] += 1

            rejected_count += 1
        
        except Exception as e:
            error_print(f"Error rejecting request {request_id_str}", e)
            continue
    
    # Send single bulk email to each updater
    for updater_id, data in updaters_notified.items():
        updater = data['updater']
        count = data['count']
        if updater.get('email'):
            send_bulk_rejection_email_to_updater(
                updater_email=updater.get('email'),
                updater_name=updater.get('name', 'TA Updater'),
                rejected_count=count,
                validator_name=user.get('name', 'Validator'),
                rejection_notes=rejection_notes
            )
    
    flash(f'Successfully rejected {rejected_count} requests.', 'success')
    
    try:
        emit_updater_history_update()
    except:
        pass
    
    return redirect(url_for('ta.validator_dashboard', tab=current_tab))


@ta_bp.route('/validator/get-pending-requests', methods=['GET'])
def get_pending_requests():
    """Get all pending requests for validator"""
    has_access, user = check_ta_validator_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        ta_categories = get_ta_categories()
        if not ta_categories:
            return jsonify({'success': True, 'requests': []})
        
        category_ids = [cat["_id"] for cat in ta_categories]
        
        # Include both TA updater requests and employee-raised TA requests
        pending_query = {
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending",
            "$or": [
                {"category_id": {"$in": category_ids}},  # TA updater requests
                {"category_department": {"$regex": "^ta", "$options": "i"}}  # Employee-raised TA requests
            ]
        }
        
        pending_cursor = mongo.db.points_request.find(pending_query).sort("request_date", 1)
        
        requests = []
        for req_data in pending_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            if employee and category:
                requests.append({
                    'request_id': str(req_data['_id']),
                    'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                    'event_date': req_data.get("event_date", req_data["request_date"]).strftime('%d-%m-%Y'),
                    'employee_name': employee.get("name", "Unknown"),
                    'grade': employee.get("grade", "Unknown"),
                    'category_name': category.get("name", "Unknown"),
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': req_data.get("submission_notes", "")
                })
        
        return jsonify({'success': True, 'requests': requests})
    
    except Exception as e:
        error_print("Error getting pending requests", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@ta_bp.route('/validator/check-new-requests')
def check_new_requests():
    """Check for new pending requests"""
    has_access, user = check_ta_validator_access()
    
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
        
        ta_categories = get_ta_categories()
        if not ta_categories:
            return jsonify({'pending_count': 0, 'new_requests': []})
        
        category_ids = [cat["_id"] for cat in ta_categories]
        
        # Get total pending count (include both TA updater and employee-raised requests)
        pending_count = mongo.db.points_request.count_documents({
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending",
            "$or": [
                {"category_id": {"$in": category_ids}},  # TA updater requests
                {"category_department": {"$regex": "^ta", "$options": "i"}}  # Employee-raised TA requests
            ]
        })
        
        # Get new requests since last check (include both TA updater and employee-raised requests)
        new_requests_cursor = mongo.db.points_request.find({
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending",
            "request_date": {"$gt": last_check_date},
            "$or": [
                {"category_id": {"$in": category_ids}},  # TA updater requests
                {"category_department": {"$regex": "^ta", "$options": "i"}}  # Employee-raised TA requests
            ]
        }).sort("request_date", -1)
        
        new_requests = []
        for req_data in new_requests_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            if employee and category:
                new_requests.append({
                    'employee_name': employee.get("name", "Unknown"),
                    'category_name': category.get("name", "Unknown"),
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': req_data.get("submission_notes", "")
                })
        
        return jsonify({
            'pending_count': pending_count,
            'new_requests': new_requests,
            'count': len(new_requests),
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        error_print("Error checking new requests", e)
        return jsonify({'error': str(e)}), 500