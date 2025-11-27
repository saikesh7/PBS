from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from datetime import datetime
from bson import ObjectId

from .hr_main import hr_bp
from .hr_helpers import (
    check_hr_validator_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, get_hr_categories
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
        
        hr_categories = get_hr_categories()
        validator_requests = []
        
        # Get HR category IDs to filter requests
        hr_category_ids = [cat["_id"] for cat in hr_categories] if hr_categories else []
        
        # Only fetch pending requests for HR categories
        query = {
            "assigned_validator_id": ObjectId(user['_id']),
            "status": "Pending"
        }
        if hr_category_ids:
            query["category_id"] = {"$in": hr_category_ids}
        
        pending_cursor = mongo.db.points_request.find(query).sort("request_date", 1)
        
        for req in pending_cursor:
            emp = mongo.db.users.find_one({"_id": req["user_id"]})
            updater = mongo.db.users.find_one({"_id": req.get("created_by_pmo_id")})
            cat = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
            
            if emp and cat:
                if updater:
                    submitted_by = updater.get("name", "HR Updater")
                else:
                    submitted_by = emp.get("name", "Employee")
                
                validator_requests.append({
                    'request_id': str(req['_id']),
                    'request_date': req["request_date"].strftime('%d-%m-%Y'),
                    'event_date': req.get("event_date", req["request_date"]).strftime('%d-%m-%Y'),
                    'employee_name': emp.get("name", "Unknown"),
                    'employee_id': emp.get("employee_id", "N/A"),
                    'category_name': cat.get("name", "Unknown"),
                    'points': req.get("points", 0),
                    'utilization_value': req.get("utilization_value"),
                    'notes': req.get("submission_notes", ""),
                    'updater_name': submitted_by
                })
        
        history_data = []
        seen_request_ids = set()
        
        # Filter history by HR categories only
        history_query = {
            "status": {"$in": ["Approved", "Rejected"]},
            "$or": [
                {"assigned_validator_id": ObjectId(user['_id'])},
                {"processed_by": ObjectId(user['_id'])}
            ]
        }
        if hr_category_ids:
            history_query["category_id"] = {"$in": hr_category_ids}
        
        history_cursor = mongo.db.points_request.find(history_query).sort("response_date", -1)
        
        # Old history with HR category filter
        old_history_query = {
            "status": {"$in": ["Approved", "Rejected"]},
            "$or": [
                {"pmo_id": ObjectId(user['_id'])},
                {"pending_validator_id": ObjectId(user['_id'])},
                {"created_by_pmo_id": ObjectId(user['_id'])}
            ]
        }
        if hr_category_ids:
            old_history_query["category_id"] = {"$in": hr_category_ids}
        
        old_history_cursor = mongo.db.points_request.find(old_history_query).sort("response_date", -1)
        
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
                    'status': req.get("status", "Unknown")
                })
        
        # Filter points by HR categories only
        points_query = {"awarded_by": ObjectId(user['_id'])}
        if hr_category_ids:
            points_query["category_id"] = {"$in": hr_category_ids}
        
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
                    'status': 'Approved'
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
            hr_categories=hr_categories,
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
            
            from services.realtime_events import publish_request_approved
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
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
            
            from services.realtime_events import publish_request_rejected
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            rejector_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            
            if employee_data and rejector_data:
                publish_request_rejected(request_doc, employee_data, rejector_data)
            
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
    
    if not selected_request_ids:
        flash('No requests selected for approval.', 'warning')
        return redirect(url_for('hr_roles.validator_dashboard', tab='review'))
    
    approved_count = 0
    
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
                    "response_notes": "Bulk approved",
                    "processed_by": ObjectId(user['_id'])
                }}
            )
            
            points_record = {
                "user_id": request_doc["user_id"],
                "category_id": request_doc["category_id"],
                "points": request_doc["points"],
                "award_date": request_doc.get("event_date", datetime.utcnow()),
                "awarded_by": ObjectId(user['_id']),
                "notes": "Bulk approved by HR Validator",
                "request_id": request_id,
                "created_at": datetime.utcnow()
            }
            mongo.db.points.insert_one(points_record)
            
            from services.realtime_events import publish_request_approved
            employee_data = mongo.db.users.find_one({'_id': request_doc['user_id']})
            approver_data = mongo.db.users.find_one({'_id': ObjectId(user['_id'])})
            
            if employee_data and approver_data:
                publish_request_approved(request_doc, employee_data, approver_data, points_record)
            
            approved_count += 1
        except Exception as e:
            error_print(f"Error approving request {request_id_str}", e)
            continue
    
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
            
            rejected_count += 1
        except Exception as e:
            error_print(f"Error rejecting request {request_id_str}", e)
            continue
    
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
        
        # Get HR category IDs to filter by department
        hr_categories = get_hr_categories()
        hr_category_ids = [cat['_id'] for cat in hr_categories]
        
        # Count ONLY HR pending requests assigned to this validator
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
        
        # Get HR category IDs to filter by department
        hr_categories = get_hr_categories()
        hr_category_ids = [cat['_id'] for cat in hr_categories]
        
        # Fetch ONLY HR pending requests assigned to this validator
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

