from flask import render_template, request, session, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
from bson import ObjectId

from .ta_main import ta_bp
from .helpers import (
    check_ta_validator_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, emit_updater_history_update,
    get_financial_quarter_dates, get_ta_categories, get_ta_categories_for_validator,
    get_all_ta_category_ids, get_ta_category_ids
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
        ta_categories = get_ta_categories()  # Active categories for display/dropdown
        
        if not ta_categories:
            flash('No TA categories found in database.', 'warning')
        
        category_ids = get_ta_category_ids() if ta_categories else []  # Active only for history
        
        # Get ALL TA categories (including employee_raised AND inactive) for display in Categories section
        all_ta_categories = get_ta_categories_for_validator()
        # Use get_all_ta_category_ids() to include inactive categories for pending requests
        all_ta_category_ids = get_all_ta_category_ids()
        
        # Fetch pending requests assigned to this validator
        # Include both:
        # 1. TA updater-created requests (filtered by ALL TA category_ids including inactive)
        # 2. Employee-raised requests with TA department (regardless of category_type)
        # This ensures pending requests are shown even if category becomes inactive
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
                        {"category_id": {"$in": all_ta_category_ids}},  # TA requests (includes ALL TA categories including inactive)
                        {"category_department": {"$regex": "^ta", "$options": "i"}}  # Employee-raised TA requests
                    ]
                }
            ]
        }).sort("request_date", 1)
        
        validator_requests = []
        for req_data in pending_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            
            # Try multiple field names for updater (old data might use different field names)
            updater_id = req_data.get("created_by_ta_id") or req_data.get("created_by_pmo_id") or req_data.get("created_by_ld_id") or req_data.get("created_by_hr_id") or req_data.get("created_by") or req_data.get("submitted_by") or req_data.get("raised_by")
            updater = None
            updater_name = "Self-Submitted"  # Default if no updater found
            
            if updater_id:
                updater = mongo.db.users.find_one({"_id": updater_id})
                if updater:
                    updater_name = updater.get("name", "Unknown")
                # Check if employee raised it themselves (matches LD logic)
                elif req_data.get("created_by") == req_data.get("user_id"):
                    updater_name = "Self (Employee)"
            else:
                # If no updater_id, check if employee raised it themselves
                if req_data.get("created_by") == req_data.get("user_id"):
                    updater_name = "Self (Employee)"
                elif req_data.get("updated_by") == "Employee":
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
        
        # Get history data from points_request
        # Track seen request IDs to avoid duplicates
        seen_request_ids = set()
        history_data = []
        
        # IMPORTANT: History should ONLY show records processed by THIS department (TA)
        # Records approved/rejected by other departments should NOT appear here
        # even if the same user has access to multiple validator dashboards
        
        # NEW records - MUST have processed_department = "ta"
        history_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_department": "ta"  # ✅ Only show records processed by TA department
        }).sort("response_date", -1)
        
        # OLD records - records without processed_department field, filter by TA validator fields
        # These are records from before processed_department field was used
        old_history_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_department": {"$exists": False},  # Only old records without processed_department
            "$or": [
                {"ta_validator_id": ObjectId(user['_id'])},  # Old TA validator field
                {"created_by_ta_id": {"$exists": True}}  # Records created by TA updater
            ]
        }).sort("response_date", -1)
        
        # Combine cursors (excluding old_points_cursor as we handle points collection separately below)
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
            
            # Only show records where BOTH employee AND category exist in database (not deleted)
            if employee and category:
                # Determine who raised the request (matches LD logic)
                updater_id = req_data.get("created_by_ta_id") or req_data.get("created_by_pmo_id") or req_data.get("created_by_ld_id") or req_data.get("created_by_hr_id") or req_data.get("created_by")
                updater_name = "Unknown"
                
                if updater_id:
                    updater = mongo.db.users.find_one({"_id": updater_id})
                    if updater:
                        updater_name = updater.get("name", "Unknown")
                    # Check if employee raised it themselves (matches LD logic)
                    elif req_data.get("created_by") == req_data.get("user_id"):
                        updater_name = "Self (Employee)"
                elif req_data.get("created_by") == req_data.get("user_id"):
                    updater_name = "Self (Employee)"
                
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
                
                # Use processed_date for history display - handle both points_request and points collection
                if "response_date" in req_data:
                    processed_date = req_data["response_date"]
                elif "created_at" in req_data:
                    processed_date = req_data["created_at"]
                elif "award_date" in req_data:
                    processed_date = req_data["award_date"]
                else:
                    processed_date = req_data.get("request_date") or req_data.get("event_date")
                
                event_date = req_data.get("event_date") or req_data.get("award_date") or req_data.get("request_date")
                
                history_data.append({
                    'request_id': request_id,
                    'date': processed_date.strftime('%d-%m-%Y') if processed_date else "N/A",
                    'event_date': event_date.strftime('%d-%m-%Y') if event_date else "N/A",
                    'employee': employee.get("name", "Unknown"),
                    'employee_id': employee.get("employee_id", "N/A"),
                    'department': employee.get("department", "N/A"),
                    'grade': employee.get("grade", "Unknown"),
                    'category': category.get("name", "Unknown") if category else "Unknown Category",
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': notes,
                    'status': req_data.get("status", "Approved"),  # Points collection records are always Approved
                    'updater_name': updater_name,  # Add updater name to history
                    'hr_modified': req_data.get('hr_modified', False)
                })
        
        # Also fetch from points collection
        # Get awards given by TA department - filter by processed_department or TA-specific fields
        
        # Fetch awards from points collection - ONLY TA department records
        points_cursor = mongo.db.points.find({
            "$or": [
                {"processed_department": "ta"},  # New records with processed_department
                {"created_by_ta_id": {"$exists": True}}  # Old records created by TA updater
            ]
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
                # Determine who raised the request (for old points records)
                updater_id = point.get("created_by_ta_id") or point.get("created_by_pmo_id") or point.get("created_by_ld_id") or point.get("created_by_hr_id") or point.get("created_by")
                updater_name = "Unknown"
                
                if updater_id:
                    updater = mongo.db.users.find_one({"_id": updater_id})
                    if updater:
                        updater_name = updater.get("name", "Unknown")
                    elif point.get("created_by") == point.get("user_id"):
                        updater_name = "Self (Employee)"
                elif point.get("created_by") == point.get("user_id"):
                    updater_name = "Self (Employee)"
                
                # Use award_date (which is the event_date) for history display
                event_date = point.get("award_date") or point.get("event_date") or point.get("created_at")
                
                history_data.append({
                    'date': event_date.strftime('%d-%m-%Y'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'employee': employee.get("name", "Unknown"),
                    'employee_id': employee.get("employee_id", "N/A"),
                    'department': employee.get("department", "N/A"),
                    'grade': employee.get("grade", "Unknown"),
                    'category': category.get("name", "Unknown"),
                    'quantity': point.get("quantity", 1),
                    'points': point.get("points", 0),
                    'notes': point.get("notes", ""),
                    'status': 'Approved',
                    'updater_name': updater_name,
                    'hr_modified': point.get('hr_modified', False)
                })
        
        # Get filter options - use event_date instead of processed date
        year_options = sorted(list(set([h['event_date'].split('-')[2] for h in history_data if h.get('event_date') and h['event_date'] != 'N/A'])), reverse=True) if history_data else []
        
        # Dynamically generate quarter options based on actual data - use event_date
        quarters_set = set()
        for h in history_data:
            if h.get('event_date') and h['event_date'] != 'N/A':
                date_parts = h['event_date'].split('-')
                if len(date_parts) == 3:
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
            ta_categories=all_ta_categories,
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
                        "processed_by": ObjectId(user['_id']),
                        "processed_department": "ta"  # ✅ Store which department processed this
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
            from services.realtime_events import publish_request_approved, publish_ta_working_notification
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_ta_id')})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            # Notify PM/PMArch/Presales that TA is approving their request
            if employee_data and category_data:
                publish_ta_working_notification(request_doc, employee_data, user, category_data, action='approving')
            
            # Send email to updater
            if updater_data and updater_data.get('email') and category_data:
                # Get submission notes from request
                submission_notes = (
                    request_doc.get("submission_notes") or 
                    request_doc.get("request_notes") or 
                    request_doc.get("notes") or 
                    request_doc.get("employee_notes") or 
                    request_doc.get("description") or 
                    ""
                )
                
                send_approval_email_to_updater(
                    updater_email=updater_data.get('email'),
                    updater_name=updater_data.get('name', 'TA Updater'),
                    employee_name=employee_data.get('name', 'Unknown') if employee_data else 'Unknown',
                    category_name=category_data.get('name', 'Unknown'),
                    points=request_doc.get('points', 0),
                    validator_name=user.get('name', 'Validator'),
                    submission_notes=submission_notes,
                    validator_notes=response_notes
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
                        "processed_by": ObjectId(user['_id']),
                        "processed_department": "ta"  # ✅ Store which department processed this
                    }
                }
            )
            
            # Realtime notification
            from services.realtime_events import publish_request_rejected, publish_ta_working_notification
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_ta_id')})
            
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Notify PM/PMArch/Presales that TA is rejecting their request
            if employee_data and category_data:
                publish_ta_working_notification(request_doc, employee_data, user, category_data, action='rejecting')
            
            # Send email to updater (only updater gets rejection email, not employee)
            if updater_data and updater_data.get('email') and category_data:
                # Get submission notes from request
                submission_notes = (
                    request_doc.get("submission_notes") or 
                    request_doc.get("request_notes") or 
                    request_doc.get("notes") or 
                    request_doc.get("employee_notes") or 
                    request_doc.get("description") or 
                    ""
                )
                
                send_rejection_email_to_updater(
                    updater_email=updater_data.get('email'),
                    updater_name=updater_data.get('name', 'TA Updater'),
                    employee_name=employee_data.get('name', 'Unknown') if employee_data else 'Unknown',
                    category_name=category_data.get('name', 'Unknown'),
                    validator_name=user.get('name', 'Validator'),
                    rejection_notes=response_notes,
                    points=request_doc.get('points', 0),
                    submission_notes=submission_notes
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
    approval_notes = request.form.get('response_notes', '').strip() or request.form.get('approval_notes', '').strip() or request.form.get('bulk_notes', '').strip()
    
    if not selected_request_ids:
        flash('No requests selected for approval.', 'warning')
        return redirect(url_for('ta.validator_dashboard', tab=current_tab))
    
    if not approval_notes:
        flash('Please provide notes for bulk approval.', 'danger')
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
                        "response_notes": approval_notes,
                        "processed_by": ObjectId(user['_id']),
                        "processed_department": "ta"  # ✅ Store which department processed this
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
                "notes": approval_notes,
                "request_id": request_id,
                "created_at": datetime.utcnow()
            }
            mongo.db.points.insert_one(points_record)

            # Realtime notification
            from services.realtime_events import publish_request_approved, publish_ta_working_notification
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            # Notify PM/PMArch/Presales that TA is approving their request (bulk)
            if employee_data and category_data:
                publish_ta_working_notification(request_doc, employee_data, user, category_data, action='approving')
            
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
                        "processed_by": ObjectId(user['_id']),
                        "processed_department": "ta"  # ✅ Store which department processed this
                    }
                }
            )
            
            # Realtime notification
            from services.realtime_events import publish_request_rejected, publish_ta_working_notification
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc.get('category_id')})
            
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Notify PM/PMArch/Presales that TA is rejecting their request (bulk)
            if employee_data and category_data:
                publish_ta_working_notification(request_doc, employee_data, user, category_data, action='rejecting')
            
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


@ta_bp.route('/validator/delete-record', methods=['POST'])
def validator_delete_record():
    """Delete a record (validator can delete records they processed)"""
    has_access, user = check_ta_validator_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        request_id = request.form.get('request_id', '').strip()
        point_id = request.form.get('point_id', '').strip()
        
        if not request_id and not point_id:
            flash('No record ID provided.', 'danger')
            return redirect(url_for('ta.validator_dashboard'))
        
        deleted = False
        
        if request_id:
            # Find the record - check if validator has access
            record = mongo.db.points_request.find_one({
                '_id': ObjectId(request_id),
                '$or': [
                    {'assigned_validator_id': ObjectId(user['_id'])},
                    {'processed_by': ObjectId(user['_id'])},
                    {'pending_validator_id': ObjectId(user['_id'])},
                    {'ta_validator_id': ObjectId(user['_id'])},
                    {'validator_id': ObjectId(user['_id'])}
                ]
            })
            
            if record:
                # Delete from points_request collection
                mongo.db.points_request.delete_one({'_id': ObjectId(request_id)})
                # Also delete from points collection
                mongo.db.points.delete_one({'request_id': ObjectId(request_id)})
                deleted = True
        
        if point_id and not deleted:
            # Try to delete from points collection directly
            point_record = mongo.db.points.find_one({
                '_id': ObjectId(point_id),
                'awarded_by': ObjectId(user['_id'])
            })
            
            if point_record:
                # Delete from points collection
                mongo.db.points.delete_one({'_id': ObjectId(point_id)})
                # Also delete from points_request if exists
                if point_record.get('request_id'):
                    mongo.db.points_request.delete_one({'_id': point_record['request_id']})
                deleted = True
        
        if deleted:
            flash('Record deleted successfully.', 'success')
        else:
            flash('Record not found or you do not have permission to delete it.', 'danger')
        
        return redirect(url_for('ta.validator_dashboard'))
        
    except Exception as e:
        error_print("Error deleting record", e)
        flash(f'Error deleting record: {str(e)}', 'danger')
        return redirect(url_for('ta.validator_dashboard'))


@ta_bp.route('/validator/modify-record', methods=['POST'])
def validator_modify_record():
    """Modify a record (validator can modify records they processed)"""
    has_access, user = check_ta_validator_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        request_id = request.form.get('request_id', '').strip()
        point_id = request.form.get('point_id', '').strip()
        new_points = request.form.get('points', '').strip()
        new_notes = request.form.get('notes', '').strip()
        
        if not request_id and not point_id:
            flash('No record ID provided.', 'danger')
            return redirect(url_for('ta.validator_dashboard'))
        
        updated = False
        
        if request_id:
            # Find the record - check if validator has access
            record = mongo.db.points_request.find_one({
                '_id': ObjectId(request_id),
                '$or': [
                    {'assigned_validator_id': ObjectId(user['_id'])},
                    {'processed_by': ObjectId(user['_id'])},
                    {'pending_validator_id': ObjectId(user['_id'])},
                    {'ta_validator_id': ObjectId(user['_id'])},
                    {'validator_id': ObjectId(user['_id'])}
                ]
            })
            
            if record:
                update_data = {
                    'last_updated_by': ObjectId(user['_id']),
                    'last_updated_at': datetime.utcnow()
                }
                
                if new_points:
                    try:
                        update_data['points'] = int(new_points)
                    except ValueError:
                        flash('Invalid points value.', 'danger')
                        return redirect(url_for('ta.validator_dashboard'))
                
                if new_notes:
                    update_data['response_notes'] = new_notes
                
                # Update in points_request collection
                mongo.db.points_request.update_one(
                    {'_id': ObjectId(request_id)},
                    {'$set': update_data}
                )
                
                # Also update in points collection if approved
                if record.get('status') == 'Approved':
                    points_update = {'last_updated_at': datetime.utcnow()}
                    if new_points:
                        points_update['points'] = int(new_points)
                    if new_notes:
                        points_update['notes'] = new_notes
                    mongo.db.points.update_one(
                        {'request_id': ObjectId(request_id)},
                        {'$set': points_update}
                    )
                updated = True
        
        if point_id and not updated:
            # Try to update in points collection directly
            point_record = mongo.db.points.find_one({
                '_id': ObjectId(point_id),
                'awarded_by': ObjectId(user['_id'])
            })
            
            if point_record:
                points_update = {'last_updated_at': datetime.utcnow()}
                if new_points:
                    try:
                        points_update['points'] = int(new_points)
                    except ValueError:
                        flash('Invalid points value.', 'danger')
                        return redirect(url_for('ta.validator_dashboard'))
                if new_notes:
                    points_update['notes'] = new_notes
                
                mongo.db.points.update_one(
                    {'_id': ObjectId(point_id)},
                    {'$set': points_update}
                )
                updated = True
        
        if updated:
            flash('Record updated successfully.', 'success')
        else:
            flash('Record not found or you do not have permission to modify it.', 'danger')
        
        return redirect(url_for('ta.validator_dashboard'))
        
    except Exception as e:
        error_print("Error modifying record", e)
        flash(f'Error modifying record: {str(e)}', 'danger')
        return redirect(url_for('ta.validator_dashboard'))
