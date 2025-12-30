from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from datetime import datetime
from bson import ObjectId

from .hr_main import hr_bp
from .hr_helpers import (
    check_hr_validator_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, get_hr_categories, get_hr_categories_for_validator,
    get_all_hr_category_ids, get_hr_category_ids
)
from .hr_email_service import (
    send_approval_email_to_updater, send_rejection_email_to_updater,
    send_approval_email_to_employee, send_bulk_approval_email_to_updater,
    send_bulk_rejection_email_to_updater
)
from utils.error_handling import error_print

@hr_bp.route('/validator/dashboard', methods=['GET', 'POST'])
def validator_dashboard():
    """HR Validator Dashboard"""
    has_access, user = check_hr_validator_access()
    
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
        
        hr_categories = get_hr_categories()  # For dropdown (excludes employee_raised)
        hr_categories_for_validator = get_hr_categories_for_validator()  # For fetching requests (includes employee_raised)
        validator_requests = []
        
        # Get ALL HR category IDs (including inactive) to filter pending requests
        # This ensures pending requests are shown even if category becomes inactive
        all_hr_category_ids = get_all_hr_category_ids()
        hr_category_ids = get_hr_category_ids()  # Active only for history
        
        # Get category IDs from the old 'categories' collection that belong to HR
        # This handles cases where categories might be in the old collection
        old_hr_categories = list(mongo.db.categories.find({
            'category_department': {'$regex': '^hr', '$options': 'i'}
        }))
        old_hr_category_ids = [cat['_id'] for cat in old_hr_categories]
        
        # Combine HR category IDs from both collections
        # Use a dict to deduplicate ObjectIds properly
        combined_ids_dict = {}
        for cat_id in all_hr_category_ids + old_hr_category_ids:
            combined_ids_dict[str(cat_id)] = cat_id
        combined_hr_category_ids = list(combined_ids_dict.values())
        
        # Fetch pending requests for HR validator
        # KEY LOGIC: Show requests where the CATEGORY currently belongs to HR
        # This handles scenarios where:
        # 1. Category was moved from another department (e.g., TA -> HR)
        # 2. Request was raised after category department change
        # 3. Old requests for categories that now belong to HR
        
        # Primary filter: category_id must be in HR categories list
        # This is the most reliable way to determine if a request belongs to HR
        pending_cursor = mongo.db.points_request.find({
            "status": "Pending",
            "category_id": {"$in": combined_hr_category_ids}
        }).sort("request_date", 1)
        
        for req in pending_cursor:
            emp = mongo.db.users.find_one({"_id": req["user_id"]})
            
            # Try multiple field names for updater (old data might use different field names)
            updater_id = req.get("created_by_hr_id") or req.get("created_by_pmo_id") or req.get("created_by_ld_id") or req.get("created_by_ta_id") or req.get("created_by") or req.get("submitted_by") or req.get("raised_by")
            updater = None
            updater_name = "Self-Submitted"  # Default if no updater found
            
            if updater_id:
                updater = mongo.db.users.find_one({"_id": updater_id})
                if updater:
                    updater_name = updater.get("name", "Unknown")
                # Check if employee raised it themselves
                elif req.get("created_by") == req.get("user_id"):
                    updater_name = "Self (Employee)"
            else:
                # If no updater_id, check if employee raised it themselves
                if req.get("created_by") == req.get("user_id"):
                    updater_name = "Self (Employee)"
                elif req.get("updated_by") == "Employee":
                    updater_name = "Self-Submitted"
                elif req.get("updated_by") == "HR":
                    updater_name = "HR Updater"
                elif req.get("updated_by") == "PMO":
                    updater_name = "PMO Updater"
            
            # Try hr_categories first, then fall back to old categories collection
            cat = mongo.db.hr_categories.find_one({"_id": req.get("category_id")})
            if not cat:
                cat = mongo.db.categories.find_one({"_id": req.get("category_id")})
            
            # Show record even if category is not found (for inactive/deleted categories)
            if emp:
                # Try multiple field names for notes
                notes = (
                    req.get("submission_notes") or 
                    req.get("request_notes") or 
                    req.get("notes") or 
                    req.get("employee_notes") or 
                    req.get("description") or 
                    req.get("comment") or 
                    "No notes provided"
                )
                
                # Recalculate points based on employee grade and category points_per_unit
                stored_points = req.get("points", 0)
                utilization_value = req.get("utilization_value")
                
                # Check if this is a utilization category
                is_utilization = utilization_value is not None
                
                if stored_points == 0 and not is_utilization and cat:
                    # Recalculate if points are 0 and it's not a utilization category
                    points_per_unit = cat.get('points_per_unit', {})
                    employee_grade = emp.get('grade', 'base')
                    
                    if isinstance(points_per_unit, dict):
                        # Try to get points for employee's grade, fallback to base
                        stored_points = points_per_unit.get(employee_grade, points_per_unit.get('base', 0))
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
                    'category_name': cat.get("name", "Unknown Category") if cat else "Unknown Category",
                    'category_status': cat.get("category_status", "active") if cat else "unknown",
                    'points': stored_points,
                    'utilization_value': req.get("utilization_value"),
                    'notes': notes,
                    'updater_name': updater_name
                })
        
        history_data = []
        seen_request_ids = set()
        
        # IMPORTANT: History should ONLY show records processed by THIS department (HR)
        # Records approved/rejected by other departments should NOT appear here
        # even if the same user has access to multiple validator dashboards
        # History shows ONLY Approved and Rejected records (NOT Pending)
        
        # Get all HR category IDs (active + inactive) for history filtering
        all_hr_category_ids_for_history = get_all_hr_category_ids()
        
        # NEW records - MUST have processed_department = "hr"
        # Only show Approved and Rejected (NOT Pending)
        history_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},  # Only Approved/Rejected in history
            "processed_department": "hr"  # ✅ Only show records processed by HR department
        }).sort("response_date", -1)
        
        # OLD records - records without processed_department field
        # STRICT filtering: Only show records that were DEFINITELY processed by HR
        # - Must have hr_validator_id field (explicitly assigned to HR validator)
        # - OR created by HR updater AND belongs to HR category (not other departments)
        # Exclude records that have other department's updater fields (created_by_pmo_id, created_by_ld_id, created_by_ta_id)
        old_history_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},  # Only Approved/Rejected in history
            "processed_department": {"$exists": False},  # Only old records without processed_department
            # Exclude records created by other departments
            "created_by_pmo_id": {"$exists": False},
            "created_by_ld_id": {"$exists": False},
            "created_by_ta_id": {"$exists": False},
            "$or": [
                {"hr_validator_id": {"$exists": True}},  # Has HR validator field
                {
                    "created_by_hr_id": {"$exists": True},  # Created by HR updater
                    "category_id": {"$in": all_hr_category_ids_for_history}  # AND belongs to HR category
                }
            ]
        }).sort("response_date", -1)
        
        combined_cursor = list(history_cursor) + list(old_history_cursor)
        
        for req in combined_cursor:
            request_id = str(req.get("_id", ""))
            
            if request_id in seen_request_ids:
                continue
            
            seen_request_ids.add(request_id)
            
            emp = mongo.db.users.find_one({"_id": req["user_id"]})
            cat = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
            if not cat:
                cat = mongo.db.categories.find_one({"_id": req["category_id"]})
            
            if emp:
                event_date = req.get("event_date", req["request_date"])
                utilization_val = req.get("utilization_value") or req.get("utilization") or req.get("utilization_percentage")
                submission_notes = req.get("submission_notes") or req.get("notes") or ""
                response_notes = req.get("response_notes") or ""
                
                # Determine who submitted the request
                # Check ALL possible updater fields (request might have been created by any department's updater)
                updater_id = req.get("created_by_pmo_id") or req.get("created_by_hr_id") or req.get("created_by_ld_id") or req.get("created_by_ta_id") or req.get("created_by")
                updater_name = "Unknown"
                
                if updater_id:
                    # Check if employee raised it themselves
                    if req.get("created_by") == req.get("user_id"):
                        updater_name = emp.get('name', 'Unknown')
                    else:
                        # Show actual name
                        updater = mongo.db.users.find_one({"_id": updater_id})
                        if updater:
                            updater_name = updater.get("name", "Unknown")
                elif req.get("created_by") == req.get("user_id"):
                    updater_name = emp.get('name', 'Unknown')
                
                history_data.append({
                    'request_id': request_id,
                    'point_id': None,
                    'request_date': event_date,
                    'date': event_date.strftime('%d-%m-%Y'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'employee': emp.get("name", "Unknown"),
                    'employee_id': emp.get("employee_id", "N/A"),
                    'employee_department': emp.get("department", ""),
                    'category': cat.get("name", "Unknown") if cat else "Unknown",
                    'points': req.get("points", 0),
                    'utilization_value': utilization_val,
                    'submission_notes': submission_notes,
                    'response_notes': response_notes,
                    'status': req.get("status", "Unknown"),
                    'hr_modified': req.get('hr_modified', False),
                    'updater_name': updater_name
                })
        
        # Filter points - ONLY awarded by HR department
        # Use processed_department to filter, with fallback for old records
        # STRICT filtering: Exclude records that have other department's updater fields
        points_query = {
            "$or": [
                {"processed_department": "hr"},  # New records with processed_department
                {
                    "processed_department": {"$exists": False},  # Old records without processed_department
                    "created_by_hr_id": {"$exists": True},  # Created by HR updater
                    "created_by_pmo_id": {"$exists": False},  # NOT created by PMO
                    "created_by_ld_id": {"$exists": False},  # NOT created by LD
                    "created_by_ta_id": {"$exists": False},  # NOT created by TA
                    "category_id": {"$in": all_hr_category_ids_for_history}  # AND belongs to HR category
                }
            ]
        }
        
        points_cursor = mongo.db.points.find(points_query).sort("created_at", -1)
        
        for point in points_cursor:
            point_request_id = str(point.get("request_id", ""))
            if point_request_id and point_request_id in seen_request_ids:
                continue
            
            emp = mongo.db.users.find_one({"_id": point["user_id"]})
            cat = mongo.db.hr_categories.find_one({"_id": point["category_id"]})
            if not cat:
                cat = mongo.db.categories.find_one({"_id": point["category_id"]})
            
            if emp:
                event_date = point.get("award_date") or point.get("event_date") or point.get("created_at")
                submission_notes = point.get("submission_notes") or point.get("notes") or ""
                response_notes = point.get("response_notes") or ""
                utilization_val = point.get("utilization_value") or point.get("utilization") or point.get("utilization_percentage")
                
                # Determine who submitted the request
                # Check ALL possible updater fields (request might have been created by any department's updater)
                updater_id = point.get("created_by_pmo_id") or point.get("created_by_hr_id") or point.get("created_by_ld_id") or point.get("created_by_ta_id") or point.get("created_by")
                updater_name = "Unknown"
                
                if updater_id:
                    # Check if employee raised it themselves
                    if point.get("created_by") == point.get("user_id"):
                        updater_name = emp.get('name', 'Unknown')
                    else:
                        # Show actual name
                        updater = mongo.db.users.find_one({"_id": updater_id})
                        if updater:
                            updater_name = updater.get("name", "Unknown")
                elif point.get("created_by") == point.get("user_id"):
                    updater_name = emp.get('name', 'Unknown')
                
                history_data.append({
                    'request_id': point_request_id if point_request_id else None,
                    'point_id': str(point.get("_id", "")),
                    'request_date': event_date,
                    'date': event_date.strftime('%d-%m-%Y'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'employee': emp.get("name", "Unknown"),
                    'employee_id': emp.get("employee_id", "N/A"),
                    'employee_department': emp.get("department", ""),
                    'category': cat.get("name", "Unknown") if cat else "Unknown",
                    'points': point.get("points", 0),
                    'utilization_value': utilization_val,
                    'submission_notes': submission_notes,
                    'response_notes': response_notes,
                    'status': 'Approved',
                    'hr_modified': point.get('hr_modified', False),
                    'updater_name': updater_name
                })
        
        history_data.sort(key=lambda x: x['request_date'], reverse=True)
        
        reward_quarters = set()
        reward_years = set()
        util_quarters = set()
        util_years = set()
        
        for h in history_data:
            if h.get('request_date'):
                month = h['request_date'].month
                year = h['request_date'].year
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
            'hr_validator_dashboard.html',
            user=user,
            validator_requests=validator_requests,
            history_data=history_data,
            hr_categories=hr_categories_for_validator,
            current_quarter=current_quarter,
            current_month=current_month,
            pending_count=len(validator_requests),
            reward_quarters=sorted(reward_quarters, key=lambda x: int(x[1])),
            reward_years=sorted(reward_years, reverse=True),
            util_quarters=sorted(util_quarters, key=lambda x: int(x[1])),
            util_years=sorted(util_years, reverse=True)
        )
    
    except Exception as e:
        error_print("Error in HR validator dashboard", e)
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
        return redirect(url_for('hr_roles.validator_dashboard', tab='review'))
    
    try:
        request_doc = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not request_doc or request_doc.get("status") != "Pending":
            flash('Request not found or already processed', 'warning')
            return redirect(url_for('hr_roles.validator_dashboard', tab='review'))
        
        if action == 'approve':
            mongo.db.points_request.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {
                    "status": "Approved",
                    "response_date": datetime.utcnow(),
                    "response_notes": response_notes,
                    "processed_by": ObjectId(user['_id']),
                    "processed_department": "hr"  # ✅ Store which department processed this
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
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_hr_id')})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            # Notify validator dashboard to refresh
            from services.realtime_events import publish_validator_dashboard_refresh
            publish_validator_dashboard_refresh(str(user['_id']), 'hr_validator', 'approved')
            
            # Send email to updater
            if updater_data and updater_data.get('email') and category_data:
                send_approval_email_to_updater(
                    updater_email=updater_data.get('email'),
                    updater_name=updater_data.get('name', 'HR Updater'),
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
                {"$set": {
                    "status": "Rejected",
                    "response_date": datetime.utcnow(),
                    "response_notes": response_notes,
                    "processed_by": ObjectId(user['_id']),
                    "processed_department": "hr"  # ✅ Store which department processed this
                }}
            )
            
            # Realtime notification - notify employee, updater, and validator
            from services.realtime_events import publish_request_rejected
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            category_data = mongo.db.hr_categories.find_one({'_id': request_doc['category_id']})
            updater_data = mongo.db.users.find_one({'_id': request_doc.get('created_by_hr_id')})
            
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Notify validator dashboard to refresh
            from services.realtime_events import publish_validator_dashboard_refresh
            publish_validator_dashboard_refresh(str(user['_id']), 'hr_validator', 'rejected')
            
            # Send email to updater (NOT to employee for rejection)
            if updater_data and updater_data.get('email') and category_data:
                send_rejection_email_to_updater(
                    updater_email=updater_data.get('email'),
                    updater_name=updater_data.get('name', 'HR Updater'),
                    employee_name=employee_data.get('name', 'Unknown') if employee_data else 'Unknown',
                    category_name=category_data.get('name', 'Unknown'),
                    validator_name=user.get('name', 'Validator'),
                    rejection_notes=response_notes
                )
            
            flash('Request rejected successfully', 'success')
        
        return redirect(url_for('hr_roles.validator_dashboard', tab='review'))
    
    except Exception as e:
        error_print("Error processing request action", e)
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('hr_roles.validator_dashboard', tab='review'))

def handle_bulk_approve(user):
    """Handle bulk approval"""
    mongo = get_mongo()
    selected_request_ids = request.form.getlist('selected_requests')
    approval_notes = request.form.get('approval_notes', '').strip()
    
    if not selected_request_ids:
        flash('No requests selected for approval.', 'warning')
        return redirect(url_for('hr_roles.validator_dashboard', tab='review'))
    
    if not approval_notes:
        flash('Please provide notes for bulk approval.', 'danger')
        return redirect(url_for('hr_roles.validator_dashboard', tab='review'))
    
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
                    "processed_by": ObjectId(user['_id']),
                    "processed_department": "hr"  # ✅ Store which department processed this
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
            updater_id = request_doc.get('created_by_hr_id')
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
                updater_name=updater.get('name', 'HR Updater'),
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
    publish_validator_dashboard_refresh(str(user['_id']), 'hr_validator', 'bulk_approved')
    
    flash(f'Successfully approved {approved_count} requests.', 'success')
    return redirect(url_for('hr_roles.validator_dashboard', tab='review'))

def handle_bulk_reject(user):
    """Handle bulk rejection"""
    mongo = get_mongo()
    selected_request_ids = request.form.getlist('selected_requests')
    rejection_notes = request.form.get('rejection_notes', 'No reason provided')
    
    if not selected_request_ids:
        flash('No requests selected for rejection.', 'warning')
        return redirect(url_for('hr_roles.validator_dashboard', tab='review'))
    
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
                    "processed_by": ObjectId(user['_id']),
                    "processed_department": "hr"  # ✅ Store which department processed this
                }}
            )
            
            from services.realtime_events import publish_request_rejected
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
            # Track updater for bulk email (NOT employee for rejection)
            updater_id = request_doc.get('created_by_hr_id')
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
    
    # Send single bulk email to each updater (NOT to employees for rejection)
    for updater_id, data in updaters_notified.items():
        updater = data['updater']
        count = data['count']
        if updater.get('email'):
            send_bulk_rejection_email_to_updater(
                updater_email=updater.get('email'),
                updater_name=updater.get('name', 'HR Updater'),
                rejected_count=count,
                validator_name=user.get('name', 'Validator'),
                rejection_notes=rejection_notes
            )
    
    # Notify validator dashboard to refresh after bulk rejection
    from services.realtime_events import publish_validator_dashboard_refresh
    publish_validator_dashboard_refresh(str(user['_id']), 'hr_validator', 'bulk_rejected')
    
    flash(f'Successfully rejected {rejected_count} requests.', 'success')
    return redirect(url_for('hr_roles.validator_dashboard', tab='review'))


@hr_bp.route('/validator/update-utilization', methods=['POST'])
def update_utilization():
    """Update utilization percentage for a record"""
    has_access, user = check_hr_validator_access()
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
            
            utilization_decimal = utilization_value / 100.0
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid utilization value'}), 400
        
        updated_count = 0
        
        if request_id:
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
                
                points_result = mongo.db.points.update_one(
                    {"request_id": ObjectId(request_id)},
                    {"$set": {
                        "utilization_value": utilization_decimal,
                        "updated_at": datetime.utcnow()
                    }}
                )
                if points_result.modified_count > 0:
                    updated_count += 1
        
        elif point_id:
            point_doc = mongo.db.points.find_one({"_id": ObjectId(point_id)})
            if point_doc:
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
            return jsonify({'success': True, 'message': f'Utilization updated successfully in {updated_count} location(s)'})
        else:
            return jsonify({'success': False, 'error': 'No records were updated. You may not have permission to edit this record.'}), 400
    
    except Exception as e:
        error_print("Error updating utilization", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@hr_bp.route('/validator/pending-count', methods=['GET'])
def hr_validator_get_pending_count():
    """Get pending requests count for real-time updates"""
    has_access, user = check_hr_validator_access()
    
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        # Get HR category IDs to filter by department (includes employee_raised)
        hr_categories_for_validator = get_hr_categories_for_validator()
        hr_category_ids = [cat['_id'] for cat in hr_categories_for_validator]
        
        # Count ONLY HR pending requests assigned to this validator (includes employee_raised)
        pending_count = mongo.db.points_request.count_documents({
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending",
            "category_id": {"$in": hr_category_ids}
        })
        
        return jsonify({'count': pending_count})
    
    except Exception as e:
        error_print("Error getting pending count", e)
        return jsonify({'error': str(e)}), 500


@hr_bp.route('/validator/pending-requests-data', methods=['GET'])
def hr_validator_get_pending_requests_data():
    """Get pending requests data for real-time updates"""
    has_access, user = check_hr_validator_access()
    
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        # Get HR category IDs to filter by department (includes employee_raised)
        hr_categories_for_validator = get_hr_categories_for_validator()
        hr_category_ids = [cat['_id'] for cat in hr_categories_for_validator]
        
        # Fetch ONLY HR pending requests assigned to this validator (includes employee_raised)
        pending_cursor = mongo.db.points_request.find({
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending",
            "category_id": {"$in": hr_category_ids}
        }).sort("request_date", -1)
        
        rewards_requests = []
        
        for req in pending_cursor:
            emp = mongo.db.users.find_one({"_id": req["user_id"]})
            cat = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
            
            if not emp or not cat:
                continue
            
            # Determine who submitted the request
            if req.get('created_by_hr_id'):
                updater = mongo.db.users.find_one({"_id": req['created_by_hr_id']})
                updater_name = updater.get('name', 'HR Updater') if updater else 'HR Updater'
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
                'updater_name': updater_name
            }
            
            rewards_requests.append(request_data)
        
        return jsonify({
            'success': True,
            'requests': {
                'rewards': rewards_requests
            }
        })
    
    except Exception as e:
        error_print("Error getting pending requests data", e)
        return jsonify({'success': False, 'error': str(e)}), 500



@hr_bp.route('/validator/delete-record', methods=['POST'])
def validator_delete_record():
    """Delete a record (validator can delete records they processed)"""
    has_access, user = check_hr_validator_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        request_id = request.form.get('request_id', '').strip()
        point_id = request.form.get('point_id', '').strip()
        
        if not request_id and not point_id:
            flash('No record ID provided.', 'danger')
            return redirect(url_for('hr_roles.validator_dashboard'))
        
        deleted = False
        
        if request_id:
            # Find the record - check if validator has access
            record = mongo.db.points_request.find_one({
                '_id': ObjectId(request_id),
                '$or': [
                    {'assigned_validator_id': ObjectId(user['_id'])},
                    {'processed_by': ObjectId(user['_id'])},
                    {'pending_validator_id': ObjectId(user['_id'])}
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
        
        return redirect(url_for('hr_roles.validator_dashboard'))
        
    except Exception as e:
        error_print("Error deleting record", e)
        flash(f'Error deleting record: {str(e)}', 'danger')
        return redirect(url_for('hr_roles.validator_dashboard'))


@hr_bp.route('/validator/modify-record', methods=['POST'])
def validator_modify_record():
    """Modify a record (validator can modify records they processed)"""
    has_access, user = check_hr_validator_access()
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
            return redirect(url_for('hr_roles.validator_dashboard'))
        
        updated = False
        
        if request_id:
            # Find the record - check if validator has access
            record = mongo.db.points_request.find_one({
                '_id': ObjectId(request_id),
                '$or': [
                    {'assigned_validator_id': ObjectId(user['_id'])},
                    {'processed_by': ObjectId(user['_id'])},
                    {'pending_validator_id': ObjectId(user['_id'])}
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
                        return redirect(url_for('hr_roles.validator_dashboard'))
                
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
                        return redirect(url_for('hr_roles.validator_dashboard'))
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
        
        return redirect(url_for('hr_roles.validator_dashboard'))
        
    except Exception as e:
        error_print("Error modifying record", e)
        flash(f'Error modifying record: {str(e)}', 'danger')
        return redirect(url_for('hr_roles.validator_dashboard'))
