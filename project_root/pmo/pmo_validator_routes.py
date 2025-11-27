from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from datetime import datetime
from bson import ObjectId

from .pmo_main import pmo_bp
from .pmo_helpers import (
    check_pmo_validator_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, get_pmo_categories
)
from .pmo_email_service import (
    send_approval_email_to_updater, send_rejection_email_to_updater,
    send_approval_email_to_employee, send_bulk_approval_email_to_updater,
    send_bulk_rejection_email_to_updater
)
from utils.error_handling import error_print

@pmo_bp.route('/validator/dashboard', methods=['GET', 'POST'])
def validator_dashboard():
    """PMO Validator Dashboard"""
    has_access, user = check_pmo_validator_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
            return redirect(get_user_redirect(user))
        return redirect(url_for('auth.login'))
    
    current_quarter, current_month = get_financial_quarter_and_month()
    
    try:
        mongo = get_mongo()
        
        if request.method == 'POST':
            action_type = request.form.get('action_type')
            if action_type == 'bulk_approve':
                return handle_bulk_approve(user)
            elif action_type == 'bulk_reject':
                return handle_bulk_reject(user)
            elif action_type == 'single_action':
                return handle_single_action(user)
        
        pmo_categories = get_pmo_categories()
        pmo_category_ids = [cat['_id'] for cat in pmo_categories]
        validator_requests = []
        
        # Fetch ONLY PMO pending requests assigned to this validator
        # Filter by PMO category_ids to exclude HR categories
        pending_cursor = mongo.db.points_request.find({
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending",
            "category_id": {"$in": pmo_category_ids}
        }).sort("request_date", 1)
        
        for req in pending_cursor:
            emp = mongo.db.users.find_one({"_id": req["user_id"]})
            updater = mongo.db.users.find_one({"_id": req.get("created_by_pmo_id")})
            cat = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
            
            if emp and cat:
                # Determine who submitted the request
                # If created_by_pmo_id exists, it was submitted by PMO Updater
                # Otherwise, it was submitted by the employee themselves (employee_raised)
                if updater:
                    submitted_by = updater.get("name", "PMO Updater")
                else:
                    submitted_by = emp.get("name", "Employee")
                
                # Get points - recalculate if needed
                stored_points = req.get("points", 0)
                utilization_value = req.get("utilization_value")
                
                # Check if this is a utilization category
                is_utilization = utilization_value is not None
                
                # Always recalculate points from category configuration to ensure accuracy
                if not is_utilization:
                    points_per_unit = cat.get('points_per_unit', {})
                    employee_grade = emp.get('grade', 'base')
                    
                    if isinstance(points_per_unit, dict):
                        # Try to get points for employee's grade, fallback to base
                        calculated_points = points_per_unit.get(employee_grade, points_per_unit.get('base', 0))
                    elif isinstance(points_per_unit, (int, float)):
                        # If points_per_unit is a number, use it directly
                        stored_points = points_per_unit
                    else:
                        # If points_per_unit is not set or invalid, keep as 0
                        stored_points = 0
                
                validator_requests.append({
                    'request_id': str(req['_id']),
                    'request_date': req["request_date"].strftime('%d-%m-%Y'),
                    'event_date': req.get("event_date", req["request_date"]).strftime('%d-%m-%Y'),
                    'employee_name': emp.get("name", "Unknown"),
                    'employee_id': emp.get("employee_id", "N/A"),
                    'category_name': cat.get("name", "Unknown"),
                    'points': stored_points,
                    'utilization_value': req.get("utilization_value"),
                    'notes': req.get("submission_notes", ""),
                    'updater_name': submitted_by
                })
        
        history_data = []
        
        # Track seen request IDs to avoid duplicates
        seen_request_ids = set()
        
        # Get from points_request collection (approved/rejected records)
        # Fetch ONLY PMO records assigned to this validator
        # Filter by PMO category_ids to exclude HR categories
        # NEW records - check assigned_validator_id or processed_by
        history_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "category_id": {"$in": pmo_category_ids},
            "$or": [
                {"assigned_validator_id": ObjectId(user['_id'])},
                {"processed_by": ObjectId(user['_id'])}
            ]
        }).sort("response_date", -1)
        
        # OLD records without new field names (old categories may have been deleted)
        # Filter by PMO category_ids to exclude HR categories
        old_history_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "category_id": {"$in": pmo_category_ids},
            "$or": [
                {"pmo_id": ObjectId(user['_id'])},  # Old validator field (very old)
                {"pending_validator_id": ObjectId(user['_id'])},  # Old validator field
                {"created_by_pmo_id": ObjectId(user['_id'])}  # Old updater field (for old PMO users)
            ]
        }).sort("response_date", -1)
        
        # Combine both cursors
        combined_cursor = list(history_cursor) + list(old_history_cursor)
        
        for req in combined_cursor:
            request_id = str(req.get("_id", ""))
            
            # Skip if we've already seen this request
            if request_id in seen_request_ids:
                continue
            
            seen_request_ids.add(request_id)
            
            emp = mongo.db.users.find_one({"_id": req["user_id"]})
            # Check both hr_categories and old categories collection
            cat = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
            if not cat:
                cat = mongo.db.categories.find_one({"_id": req["category_id"]})
            
            # Show record even if category doesn't exist (for old records with deleted categories)
            if emp:
                # Always use event_date for history display
                event_date = req.get("event_date", req["request_date"])
                
                # Handle different field names for utilization (old vs new records)
                utilization_val = req.get("utilization_value") or req.get("utilization") or req.get("utilization_percentage")
                
                # Separate submission notes (updater) and response notes (validator)
                submission_notes = req.get("submission_notes") or req.get("notes") or ""
                response_notes = req.get("response_notes") or ""
                
                history_data.append({
                    'request_id': request_id,
                    'point_id': None,
                    'request_date': event_date,
                    'date': event_date.strftime('%d-%m-%Y'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'employee': emp.get("name", "Unknown"),
                    'employee_id': emp.get("employee_id", "N/A"),
                    'employee_department': emp.get("department", ""),
                    'category': cat.get("name", "Unknown"),
                    'points': req.get("points", 0),
                        'utilization_value': utilization_val,
                        'submission_notes': submission_notes,
                        'response_notes': response_notes,
                        'status': req.get("status", "Unknown")
                    })
            
        # Also get from points collection (old approved records - ONLY for rewards, NOT utilization)
        # Note: utilization_value is NOT stored in points collection, only in points_request
        # Fetch ONLY PMO records awarded by this validator
        # Filter by PMO category_ids to exclude HR categories
        points_cursor = mongo.db.points.find({
            "awarded_by": ObjectId(user['_id']),
            "category_id": {"$in": pmo_category_ids}
        }).sort("created_at", -1)
        
        for point in points_cursor:
            # Check if we already have this from points_request
            point_request_id = str(point.get("request_id", ""))
            if point_request_id and point_request_id in seen_request_ids:
                continue
            
            emp = mongo.db.users.find_one({"_id": point["user_id"]})
            # Check both hr_categories and old categories collection
            cat = mongo.db.hr_categories.find_one({"_id": point["category_id"]})
            if not cat:
                cat = mongo.db.categories.find_one({"_id": point["category_id"]})
            
            # Show record even if category doesn't exist (for old records with deleted categories)
            if emp:
                # Use award_date (which is the event_date) for history display
                event_date = point.get("award_date") or point.get("event_date") or point.get("created_at")
                
                # Separate submission notes and response notes for old records
                submission_notes = point.get("submission_notes") or point.get("notes") or ""
                response_notes = point.get("response_notes") or ""
                
                # Check if this is an old utilization record (shouldn't be, but handle it)
                utilization_val = point.get("utilization_value") or point.get("utilization") or point.get("utilization_percentage")
                
                history_data.append({
                    'request_id': point_request_id if point_request_id else None,
                    'point_id': str(point.get("_id", "")),
                    'request_date': event_date,
                    'date': event_date.strftime('%d-%m-%Y'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'employee': emp.get("name", "Unknown"),
                    'employee_id': emp.get("employee_id", "N/A"),
                    'employee_department': emp.get("department", ""),
                    'category': cat.get("name", "Unknown"),
                    'points': point.get("points", 0),
                    'utilization_value': utilization_val,  # Check for utilization in old records
                    'submission_notes': submission_notes,
                    'response_notes': response_notes,
                    'status': 'Approved'  # Points collection only has approved records
                })
        
        # Sort history by date
        history_data.sort(key=lambda x: x['request_date'], reverse=True)
        
        # Extract unique quarters and years for filters
        reward_quarters = set()
        reward_years = set()
        util_quarters = set()
        util_years = set()
        
        for h in history_data:
            if h.get('request_date'):
                month = h['request_date'].month
                year = h['request_date'].year
                # Financial year quarters: Q1(Apr-Jun), Q2(Jul-Sep), Q3(Oct-Dec), Q4(Jan-Mar)
                if month in [4, 5, 6]:
                    quarter = 'Q1'
                elif month in [7, 8, 9]:
                    quarter = 'Q2'
                elif month in [10, 11, 12]:
                    quarter = 'Q3'
                elif month in [1, 2, 3]:
                    quarter = 'Q4'
                else:
                    quarter = None
                
                if quarter:
                    if h.get('utilization_value'):
                        util_quarters.add(quarter)
                        util_years.add(year)
                    else:
                        reward_quarters.add(quarter)
                        reward_years.add(year)
        
        return render_template(
            'pmo_validator_dashboard.html',
            user=user,
            validator_requests=validator_requests,
            history_data=history_data,
            pmo_categories=pmo_categories,
            current_quarter=current_quarter,
            current_month=current_month,
            pending_count=len(validator_requests),
            reward_quarters=sorted(reward_quarters, key=lambda x: int(x[1])),
            reward_years=sorted(reward_years, reverse=True),
            util_quarters=sorted(util_quarters, key=lambda x: int(x[1])),
            util_years=sorted(util_years, reverse=True)
        )
    
    except Exception as e:
        error_print("Error in PMO validator dashboard", e)
        flash('An error occurred while loading the validator dashboard.', 'danger')
        return redirect(url_for('auth.login'))

def handle_single_action(user):
    """Handle single request approve/reject"""
    mongo = get_mongo()
    
    request_id = request.form.get('request_id')
    action = request.form.get('action')
    response_notes = request.form.get('response_notes', '').strip()
    
    if not request_id or not action or not response_notes:
        flash('Please provide notes for your decision.', 'danger')
        return redirect(url_for('pmo.validator_dashboard', tab='review'))
    
    try:
        request_doc = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not request_doc or request_doc.get("status") != "Pending":
            flash('Request not found or already processed', 'warning')
            return redirect(url_for('pmo.validator_dashboard', tab='review'))
        
        if action == 'approve':
            mongo.db.points_request.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {
                    "status": "Approved",
                    "response_date": datetime.utcnow(),
                    "response_notes": response_notes,
                    "processed_by": ObjectId(user['_id'])
                }}
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
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_pmo_id')})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            # Notify validator dashboard to refresh
            from services.realtime_events import publish_validator_dashboard_refresh
            publish_validator_dashboard_refresh(str(user['_id']), 'pmo_validator', 'approved')
            
            # Send email to updater
            if updater_data and updater_data.get('email') and category_data:
                send_approval_email_to_updater(
                    updater_email=updater_data.get('email'),
                    updater_name=updater_data.get('name', 'PMO Updater'),
                    employee_name=employee_data.get('name', 'Unknown') if employee_data else 'Unknown',
                    category_name=category_data.get('name', 'Unknown'),
                    points=request_doc.get('points', 0),
                    validator_name=user.get('name', 'Validator'),
                    utilization_value=request_doc.get('utilization_value')
                )
            
            # Send email to employee
            if employee_data and employee_data.get('email') and category_data:
                send_approval_email_to_employee(
                    employee_email=employee_data.get('email'),
                    employee_name=employee_data.get('name', 'Employee'),
                    category_name=category_data.get('name', 'Unknown'),
                    points=request_doc.get('points', 0),
                    event_date=request_doc.get('event_date', datetime.utcnow()).strftime('%d-%m-%Y'),
                    utilization_value=request_doc.get('utilization_value')
                )
            
            flash('Request approved successfully', 'success')
        
        elif action == 'reject':
            mongo.db.points_request.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {
                    "status": "Rejected",
                    "response_date": datetime.utcnow(),
                    "response_notes": response_notes,
                    "processed_by": ObjectId(user['_id'])
                }}
            )
            
            # Realtime notification - notify employee, updater, and validator
            from services.realtime_events import publish_request_rejected
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_pmo_id')})
            
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Notify validator dashboard to refresh
            from services.realtime_events import publish_validator_dashboard_refresh
            publish_validator_dashboard_refresh(str(user['_id']), 'pmo_validator', 'rejected')
            
            # Send email to updater
            if updater_data and updater_data.get('email') and category_data:
                send_rejection_email_to_updater(
                    updater_email=updater_data.get('email'),
                    updater_name=updater_data.get('name', 'PMO Updater'),
                    employee_name=employee_data.get('name', 'Unknown') if employee_data else 'Unknown',
                    category_name=category_data.get('name', 'Unknown'),
                    validator_name=user.get('name', 'Validator'),
                    rejection_notes=response_notes
                )
            
            flash('Request rejected successfully', 'success')
        
        return redirect(url_for('pmo.validator_dashboard', tab='review'))
    
    except Exception as e:
        error_print("Error processing request action", e)
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('pmo.validator_dashboard', tab='review'))

def handle_bulk_approve(user):
    """Handle bulk approval"""
    mongo = get_mongo()
    selected_request_ids = request.form.getlist('selected_requests')
    approval_notes = request.form.get('approval_notes', '').strip()
    
    if not selected_request_ids:
        flash('No requests selected for approval.', 'warning')
        return redirect(url_for('pmo.validator_dashboard', tab='review'))
    
    if not approval_notes:
        flash('Please provide notes for bulk approval.', 'danger')
        return redirect(url_for('pmo.validator_dashboard', tab='review'))
    
    approved_count = 0
    updaters_notified = {}  # Track updaters for bulk email
    employees_to_notify = []  # Track employees for individual emails
    
    for request_id_str in selected_request_ids:
        try:
            request_id = ObjectId(request_id_str)
            request_doc = mongo.db.points_request.find_one({"_id": request_id})
            
            if not request_doc or request_doc.get("status") != "Pending":
                continue
            
            mongo.db.points_request.update_one(
                {"_id": request_id},
                {"$set": {
                    "status": "Approved",
                    "response_date": datetime.utcnow(),
                    "response_notes": approval_notes,
                    "processed_by": ObjectId(user['_id'])
                }}
            )
            
            points_record = {
                "user_id": request_doc["user_id"],
                "category_id": request_doc["category_id"],
                "points": request_doc["points"],
                "award_date": request_doc.get("event_date", datetime.utcnow()),
                "awarded_by": ObjectId(user['_id']),
                "notes": approval_notes,
                "request_id": request_id,
                "created_at": datetime.utcnow()
            }
            mongo.db.points.insert_one(points_record)
            
            from services.realtime_events import publish_request_approved
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            # Track updater for bulk email
            updater_id = request_doc.get('created_by_pmo_id')
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
                updater_name=updater.get('name', 'PMO Updater'),
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
    
    # Notify validator dashboard to refresh after bulk approval
    from services.realtime_events import publish_validator_dashboard_refresh
    publish_validator_dashboard_refresh(str(user['_id']), 'pmo_validator', 'bulk_approved')
    
    flash(f'Successfully approved {approved_count} requests.', 'success')
    return redirect(url_for('pmo.validator_dashboard', tab='review'))

def handle_bulk_reject(user):
    """Handle bulk rejection"""
    mongo = get_mongo()
    selected_request_ids = request.form.getlist('selected_requests')
    rejection_notes = request.form.get('rejection_notes', 'No reason provided')
    
    if not selected_request_ids:
        flash('No requests selected for rejection.', 'warning')
        return redirect(url_for('pmo.validator_dashboard', tab='review'))
    
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
                {"$set": {
                    "status": "Rejected",
                    "response_date": datetime.utcnow(),
                    "response_notes": rejection_notes,
                    "processed_by": ObjectId(user['_id'])
                }}
            )
            
            from services.realtime_events import publish_request_rejected
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Track updater for bulk email
            updater_id = request_doc.get('created_by_pmo_id')
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
                updater_name=updater.get('name', 'PMO Updater'),
                rejected_count=count,
                validator_name=user.get('name', 'Validator'),
                rejection_notes=rejection_notes
            )
    
    # Notify validator dashboard to refresh after bulk rejection
    from services.realtime_events import publish_validator_dashboard_refresh
    publish_validator_dashboard_refresh(str(user['_id']), 'pmo_validator', 'bulk_rejected')
    
    flash(f'Successfully rejected {rejected_count} requests.', 'success')
    return redirect(url_for('pmo.validator_dashboard', tab='review'))


@pmo_bp.route('/validator/update-utilization', methods=['POST'])
def update_utilization():
    """Update utilization percentage for a record"""
    has_access, user = check_pmo_validator_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        mongo = get_mongo()
        request_id = request.form.get('request_id', '').strip()
        point_id = request.form.get('point_id', '').strip()
        utilization_str = request.form.get('utilization', '').strip()
        
        if not utilization_str:
            return jsonify({'success': False, 'error': 'Utilization value is required'}), 400
        
        try:
            utilization_value = float(utilization_str)
            if utilization_value < 0 or utilization_value > 100:
                return jsonify({'success': False, 'error': 'Utilization must be between 0 and 100'}), 400
            
            # Convert to decimal (88 -> 0.88)
            utilization_decimal = utilization_value / 100.0
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid utilization value'}), 400
        
        updated_count = 0
        
        # Update in points_request collection if request_id exists
        if request_id:
            # Verify validator has access
            req_doc = mongo.db.points_request.find_one({
                "_id": ObjectId(request_id),
                "assigned_validator_id": ObjectId(user['_id'])
            })
            
            if req_doc:
                result = mongo.db.points_request.update_one(
                    {"_id": ObjectId(request_id)},
                    {"$set": {
                        "utilization_value": utilization_decimal,
                        "updated_at": datetime.utcnow()
                    }}
                )
                if result.modified_count > 0:
                    updated_count += 1
                
                # Also update in points collection if it exists (for approved records)
                points_result = mongo.db.points.update_one(
                    {"request_id": ObjectId(request_id)},
                    {"$set": {
                        "utilization_value": utilization_decimal,
                        "updated_at": datetime.utcnow()
                    }}
                )
                if points_result.modified_count > 0:
                    updated_count += 1
        
        # Update in points collection if point_id exists (for old records without request_id)
        elif point_id:
            # Verify the validator has access to this record
            point_doc = mongo.db.points.find_one({"_id": ObjectId(point_id)})
            if point_doc:
                # Check if validator has access via request_id or awarded_by
                has_access_to_point = False
                if point_doc.get('request_id'):
                    original_req = mongo.db.points_request.find_one({"_id": point_doc['request_id']})
                    if original_req and original_req.get('assigned_validator_id') == ObjectId(user['_id']):
                        has_access_to_point = True
                elif point_doc.get('awarded_by') == ObjectId(user['_id']):
                    has_access_to_point = True
                
                if has_access_to_point:
                    result = mongo.db.points.update_one(
                        {"_id": ObjectId(point_id)},
                        {"$set": {
                            "utilization_value": utilization_decimal,
                            "updated_at": datetime.utcnow()
                        }}
                    )
                    if result.modified_count > 0:
                        updated_count += 1
        
        if updated_count > 0:
            # Send real-time notification to updater dashboard
            if request_id:
                req_doc = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
                if req_doc and req_doc.get('created_by_pmo_id'):
                    # Get updater info
                    updater = mongo.db.users.find_one({"_id": req_doc['created_by_pmo_id']})
                    if updater:
                        # Publish real-time event to updater
                        try:
                            redis_service = current_app.config.get('redis_service')
                            if redis_service:
                                redis_service.publish_event(
                                    event_type='utilization_updated',
                                    data={
                                        'request_id': str(request_id),
                                        'utilization_value': utilization_decimal,
                                        'utilization_percentage': f"{utilization_value:.0f}%",
                                        'updated_by': user.get('name', 'Validator'),
                                        'timestamp': datetime.utcnow().isoformat()
                                    },
                                    target_user_id=str(updater['_id']),
                                    target_role='pmo_updater'
                                )
                        except Exception as e:
                            error_print("Error sending real-time notification", e)
            
            return jsonify({'success': True, 'message': f'Utilization updated successfully in {updated_count} location(s)'})
        else:
            return jsonify({'success': False, 'error': 'No records were updated. You may not have permission to edit this record.'}), 400
    
    except Exception as e:
        error_print("Error updating utilization", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@pmo_bp.route('/validator/pending-count', methods=['GET'])
def get_pending_count():
    """Get pending requests count for real-time updates"""
    has_access, user = check_pmo_validator_access()
    
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        # Get PMO category IDs to filter by department
        pmo_categories = get_pmo_categories()
        pmo_category_ids = [cat['_id'] for cat in pmo_categories]
        
        # Count ONLY PMO pending requests assigned to this validator
        pending_count = mongo.db.points_request.count_documents({
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending",
            "category_id": {"$in": pmo_category_ids}
        })
        
        return jsonify({'count': pending_count})
    
    except Exception as e:
        error_print("Error getting pending count", e)
        return jsonify({'error': str(e)}), 500


@pmo_bp.route('/validator/pending-requests-data', methods=['GET'])
def get_pending_requests_data():
    """Get pending requests data for real-time updates"""
    has_access, user = check_pmo_validator_access()
    
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        # Get PMO category IDs to filter by department
        pmo_categories = get_pmo_categories()
        pmo_category_ids = [cat['_id'] for cat in pmo_categories]
        
        # Fetch ONLY PMO pending requests assigned to this validator
        pending_cursor = mongo.db.points_request.find({
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending",
            "category_id": {"$in": pmo_category_ids}
        }).sort("request_date", -1)
        
        rewards_requests = []
        utilization_requests = []
        
        for req in pending_cursor:
            emp = mongo.db.users.find_one({"_id": req["user_id"]})
            cat = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
            
            if not emp or not cat:
                continue
            
            # Determine who submitted the request
            # If created_by_pmo_id exists, it was submitted by PMO Updater
            # Otherwise, it was submitted by the employee themselves (employee_raised)
            if req.get('created_by_pmo_id'):
                updater = mongo.db.users.find_one({"_id": req['created_by_pmo_id']})
                updater_name = updater.get('name', 'PMO Updater') if updater else 'PMO Updater'
            else:
                updater_name = emp.get('name', 'Employee')
            
            request_data = {
                'request_id': str(req['_id']),
                'employee_name': emp.get('name', 'Unknown'),
                'employee_id': emp.get('employee_id', 'N/A'),
                'department': emp.get('department', 'N/A'),
                'category_name': cat.get('name', 'Unknown'),
                'points': req.get('points', 0),
                'event_date': req.get('event_date').strftime('%d-%m-%Y') if req.get('event_date') else 'N/A',
                'submission_notes': req.get('submission_notes', ''),
                'utilization_value': req.get('utilization_value'),
                'updater_name': updater_name
            }
            
            # Check if utilization category
            category_name = cat.get('name', '').lower()
            is_utilization = 'utilization' in category_name or 'utlization' in category_name or 'billable' in category_name
            
            if is_utilization and request_data['utilization_value'] is not None:
                request_data['utilization_percentage'] = f"{(request_data['utilization_value'] * 100):.1f}%"
                utilization_requests.append(request_data)
            else:
                rewards_requests.append(request_data)
        
        return jsonify({
            'success': True,
            'requests': {
                'rewards': rewards_requests,
                'utilization': utilization_requests
            }
        })
    
    except Exception as e:
        error_print("Error getting pending requests data", e)
        return jsonify({'success': False, 'error': str(e)}), 500
