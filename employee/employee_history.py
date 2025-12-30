from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from extensions import mongo
from datetime import datetime, timedelta
import sys
import traceback
from bson.objectid import ObjectId
import os

employee_history_bp = Blueprint('employee_history', __name__, url_prefix='/employee')

# ✅ HELPER FUNCTIONS TO HANDLE OLD & NEW DATA STRUCTURES
def get_submission_notes(request_data):
    """Get submission notes from either old or new field name"""
    return request_data.get('submission_notes') or request_data.get('request_notes', '')

def get_response_notes(request_data):
    """Get response notes from either old or new field name"""
    return request_data.get('response_notes') or request_data.get('manager_notes', '')

def get_response_date(request_data):
    """Get response date from either old or new field name"""
    return request_data.get('response_date') or request_data.get('processed_date')

def get_event_date_helper(request_data):
    """Get event date, fallback to request_date"""
    return request_data.get('event_date') or request_data.get('request_date')

def get_category_for_employee(category_id):
    """
    Fetch category for employee data
    Priority: hr_categories (new data) → categories (old data)
    Note: Missing categories are auto-fixed on app startup by utils.category_validator
    """
    if not category_id:
        return None
    
    try:
        # Convert to ObjectId if string
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
        
        # ✅ Try hr_categories FIRST (where new employee categories are stored)
        category = mongo.db.hr_categories.find_one({'_id': category_id})
        if category:
            return category
        
        # ✅ Fallback to categories (where old employee categories were stored)
        category = mongo.db.categories.find_one({'_id': category_id})
        if category:
            return category
        
        # Return placeholder to prevent crashes
        return {'name': 'Uncategorized', 'code': 'N/A'}
        
    except Exception as e:
        return {'name': 'Uncategorized', 'code': 'N/A'}

# ✅ Get effective date (prioritize event_date)
def get_effective_date(entry):
    """
    Get the effective date for calculations.
    Priority: event_date > request_date > award_date
    """
    event_date = entry.get('event_date')
    if event_date and isinstance(event_date, datetime):
        return event_date
    
    request_date = entry.get('request_date')
    if request_date and isinstance(request_date, datetime):
        return request_date
    
    award_date = entry.get('award_date')
    if award_date and isinstance(award_date, datetime):
        return award_date
    
    return None



def get_manager_info(user):
    try:
        if not user or 'manager_id' not in user or not user['manager_id']:
            return None
        
        manager = mongo.db.users.find_one({"_id": ObjectId(user['manager_id'])})
        if not manager:
            return None
        
        return {
            "id": str(manager["_id"]),
            "name": manager.get("name", "Unknown"),
            "manager_level": manager.get("manager_level", "")
        }
    except Exception as e:
        return None

@employee_history_bp.route('/points-history', methods=['GET', 'POST'])
def points_history():
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to login first', 'warning')
        return redirect(url_for('auth.login'))
    
    user = None
    categories = []
    points_data = []
    bonus_data = []
    utilization_data = []
    total_points = 0
    total_bonus_points = 0
    manager = None
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30)
    
    try:
        categories_count = mongo.db.categories.count_documents({"code": {"$in": ["value_add", "initiative_ai", "mentoring", "mindshare", "presales_rfp", "interviews"]}})
        if categories_count < 6:
            return redirect(url_for('employee_categories.force_initialize_categories'))
        
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))
        
        manager = get_manager_info(user)
        categories = list(mongo.db.categories.find())
        
        if request.method == 'POST':
            try:
                start_date_str = request.form.get('start_date')
                end_date_str = request.form.get('end_date')
                category_id = request.form.get('category_id')
                
                if start_date_str:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                
                if end_date_str:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                    end_date = datetime.combine(end_date.date(), datetime.max.time())
                
            
            except Exception as e:
                flash("Invalid date format", "danger")
        
        points_data = []
        bonus_data = []
        utilization_data = []
        total_points = 0
        total_bonus_points = 0
        
        processed_entries = set()
        
        points_query = {
            "user_id": ObjectId(user_id),
            "award_date": {"$gte": start_date, "$lte": end_date}
        }
        
        if request.method == 'POST' and category_id and category_id != 'all':
            points_query["category_id"] = ObjectId(category_id)
        
        points_cursor = mongo.db.points.find(points_query).sort("award_date", -1)
        
        for point in points_cursor:
            # ✅ Fetch category properly
            category = get_category_for_employee(point["category_id"])
            
            category_name = category["name"] if category else "Unknown Category"
            category_code = category.get("code", "") if category else ""
            is_bonus = category.get("is_bonus", False) if category else False
            
            # ✅ Extract event_date
            event_date = None
            if 'metadata' in point and 'event_date' in point['metadata']:
                event_date = point['metadata']['event_date']
            elif 'event_date' in point:
                event_date = point['event_date']
            
            rounded_date = point["award_date"].replace(microsecond=0)
            entry_key = (str(point["category_id"]), point["points"], rounded_date.isoformat())
            
            if entry_key not in processed_entries:
                processed_entries.add(entry_key)
                entry = {
                    "date": point["award_date"],
                    "event_date": event_date,
                    "category": category_name,
                    "points": point["points"],
                    "status": "Approved",
                    "notes": point.get("notes", ""),
                    "is_percentage": False,
                    "numeric_value": point["points"],
                    "is_bonus": is_bonus,
                    "milestone": None,
                    'has_attachment': point.get('has_attachment', False),
                    'attachment_filename': point.get('attachment_filename', ''),
                }
                if category_code != "utilization_billable":
                    if is_bonus:
                        bonus_data.append(entry)
                        total_bonus_points += point["points"]
                    else:
                        points_data.append(entry)
                        total_points += point["points"]
                else:
                    utilization_value = point.get("utilization_value", 0)
                    utilization_data.append({
                        "date": point["award_date"],
                        "event_date": event_date,
                        "category": category_name,
                        "percentage": f"{utilization_value*100:.2f}%",
                        "status": "Approved",
                        "notes": point.get("notes", ""),
                        "numeric_value": utilization_value * 100
                    })
        
        # ✅ TOTAL POINTS HISTORY TAB LOGIC:
        # Show ALL APPROVED records (both direct awards and employee-raised)
        # Show ONLY employee-raised Pending/Rejected (NOT direct award Pending/Rejected)
        
        # First, get ALL approved requests (including direct awards)
        approved_requests_query = {
            "user_id": ObjectId(user_id),
            "status": "Approved",
            "$or": [
                {"request_date": {"$gte": start_date, "$lte": end_date}},
                {"processed_date": {"$gte": start_date, "$lte": end_date}},
                {"response_date": {"$gte": start_date, "$lte": end_date}}
            ]
        }
        
        if request.method == 'POST' and category_id and category_id != 'all':
            approved_requests_query["category_id"] = ObjectId(category_id)
        
        # Get employee-raised Pending/Rejected requests (exclude direct awards)
        # Use $and to properly combine all conditions
        employee_pending_rejected_query = {
            "$and": [
                {"user_id": ObjectId(user_id)},
                {"status": {"$in": ["Pending", "Rejected"]}},
                {
                    "$or": [
                        {"request_date": {"$gte": start_date, "$lte": end_date}},
                        {"processed_date": {"$gte": start_date, "$lte": end_date}},
                        {"response_date": {"$gte": start_date, "$lte": end_date}}
                    ]
                },
                # Exclude direct awards by ensuring these fields don't exist
                {'created_by_ta_id': {'$exists': False}},
                {'created_by_pmo_id': {'$exists': False}},
                {'created_by_hr_id': {'$exists': False}},
                {'created_by_ld_id': {'$exists': False}},
                {'created_by_manager_id': {'$exists': False}},
                # Also ensure if created_by exists, it's the employee themselves
                {
                    "$or": [
                        {'created_by': {'$exists': False}},
                        {'created_by': ObjectId(user_id)}
                    ]
                }
            ]
        }
        
        if request.method == 'POST' and category_id and category_id != 'all':
            # Add category filter to the $and array
            employee_pending_rejected_query["$and"].append({"category_id": ObjectId(category_id)})
        
        # Combine both queries
        approved_cursor = mongo.db.points_request.find(approved_requests_query)
        pending_rejected_cursor = mongo.db.points_request.find(employee_pending_rejected_query)
        
        approved_list = list(approved_cursor)
        pending_rejected_list = list(pending_rejected_cursor)
        
        requests_cursor = approved_list + pending_rejected_list
        requests_cursor.sort(key=lambda x: x.get("request_date", datetime.min), reverse=True)
        
        for req in requests_cursor:
            # ✅ SAFETY CHECK: Skip direct awards if status is Pending or Rejected
            # This is a backup filter in case the query didn't catch everything
            if req.get('status') in ['Pending', 'Rejected']:
                # Check for ALL possible direct award markers
                is_direct_award = (
                    req.get('created_by_ta_id') or 
                    req.get('created_by_pmo_id') or 
                    req.get('created_by_hr_id') or 
                    req.get('created_by_ld_id') or
                    req.get('created_by_manager_id') or
                    # Also check if created_by exists and is different from user_id
                    (req.get('created_by') and req.get('created_by') != ObjectId(user_id))
                )
                if is_direct_award:
                    continue
            
            # ✅ Fetch category properly
            category = get_category_for_employee(req["category_id"])
            
            category_name = category["name"] if category else "Unknown Category"
            category_code = category.get("code", "") if category else ""
            is_bonus = category.get("is_bonus", False) if category else False
            if req.get("is_bonus", False):
                is_bonus = True
            
            # ✅ Determine if this is a direct award or employee-raised request
            # Direct awards have created_by_X_id fields OR created_by field different from user
            is_direct_award = (
                req.get('created_by_ta_id') or 
                req.get('created_by_pmo_id') or 
                req.get('created_by_hr_id') or 
                req.get('created_by_ld_id') or
                req.get('created_by_manager_id') or
                (req.get('created_by') and req.get('created_by') != ObjectId(user_id))
            )
            
            # ✅ Extract event_date and source based on type
            event_date = None
            if is_direct_award:
                # This is a direct award - should only appear if status is Approved
                if req.get('created_by_ta_id'):
                    source = 'ta_direct'
                    event_date = req.get('event_date')
                elif req.get('created_by_pmo_id'):
                    source = 'pmo_direct'
                    event_date = req.get('event_date')
                elif req.get('created_by_hr_id'):
                    source = 'hr_direct'
                    event_date = req.get('event_date')
                elif req.get('created_by_ld_id'):
                    source = 'ld_direct'
                    event_date = req.get('metadata', {}).get('event_date')
                elif req.get('created_by_manager_id') or (req.get('created_by') and req.get('created_by') != ObjectId(user_id)):
                    source = 'manager_direct'
                    event_date = req.get('event_date')
            else:
                # This is an employee-raised request
                source = 'employee'
                if req.get('ta_id'):
                    source = 'ta'
                    event_date = req.get('event_date')
                elif req.get('pmo_id'):
                    source = 'pmo'
                    event_date = req.get('event_date')
                elif req.get('actioned_by_ld_id'):
                    source = 'ld'
                    event_date = req.get('metadata', {}).get('event_date')
            
            rounded_date = req["request_date"].replace(microsecond=0)
            entry_key = (str(req["category_id"]), req["points"], rounded_date.isoformat())
            
            is_duplicate = False
            for existing_key in processed_entries:
                existing_category_id, existing_points, existing_date_str = existing_key
                existing_date = datetime.fromisoformat(existing_date_str)
                time_diff = abs((rounded_date - existing_date).total_seconds())
                
                if (str(req["category_id"]) == existing_category_id and
                    req["points"] == existing_points and
                    time_diff <= 300):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                processed_entries.add(entry_key)
                milestone = None
                notes = get_response_notes(req)  # ✅ Handle both old & new
                if "Milestone bonus:" in notes:
                    parts = notes.split(" in ")
                    if len(parts) > 0:
                        milestone_part = parts[0].replace("Milestone bonus: ", "")
                        milestone = milestone_part.strip()
                
                entry = {
                    "date": req["request_date"],
                    "event_date": event_date,
                    "category": category_name,
                    "points": req["points"],
                    "status": req["status"],
                    "notes": notes,
                    "is_percentage": False,
                    "numeric_value": req["points"],
                    "is_bonus": is_bonus,
                    "milestone": milestone,
                    'has_attachment': req.get('has_attachment', False),
                    'attachment_filename': req.get('attachment_filename', ''),
                }
                
                if category_code == "utilization_billable":
                    utilization_value = req.get("utilization_value")
                    if utilization_value is not None:
                        utilization_data.append({
                            "date": req["request_date"],
                            "event_date": event_date,
                            "category": category_name,
                            "percentage": f"{utilization_value*100:.2f}%",
                            "status": req["status"],
                            "notes": get_response_notes(req),
                            "numeric_value": utilization_value * 100
                        })
                else:
                    if is_bonus:
                        bonus_data.append(entry)
                        total_bonus_points += req["points"]
                    else:
                        points_data.append(entry)
                        total_points += req["points"]
        
        points_data.sort(key=lambda x: x["date"], reverse=True)
        bonus_data.sort(key=lambda x: x["date"], reverse=True)
        utilization_data.sort(key=lambda x: x["date"], reverse=True)
    
    except Exception as e:
        flash("An error occurred while loading points history", "danger")
    
    return render_template(
        'employee_dashboard.html',
        user=user,
        points_data=points_data,
        bonus_data=bonus_data,
        utilization_data=utilization_data,
        categories=categories,
        total_points=total_points,
        total_bonus_points=total_bonus_points,
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d'),
        manager=manager
    )

@employee_history_bp.route('/history')
def history():
    """Request history page - Shows only employee-submitted requests (NOT direct awards)
    Shows: Pending, Approved, Rejected employee-raised requests
    Does NOT show: Any direct awards (pending, approved, or rejected)
    """
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return redirect(url_for('auth.login'))
    
    employee_submitted_history = []
    
    try:
        # ✅ REQUEST HISTORY TAB: Show ONLY employee-raised requests (ALL statuses)
        # Exclude ALL direct awards (those created by managers/HR/PMO/TA/LD without employee initiation)
        
        # Direct awards are identified by having created_by_X_id fields where X is ta/pmo/hr/ld
        # Employee-raised requests either have no created_by field OR created_by equals employee's user_id
        
        requests = mongo.db.points_request.find({
            'user_id': ObjectId(user_id),
            # Exclude direct awards by ensuring these fields don't exist
            'created_by_ta_id': {'$exists': False},
            'created_by_pmo_id': {'$exists': False},
            'created_by_hr_id': {'$exists': False},
            'created_by_ld_id': {'$exists': False},
            # Exclude bonus points from request history
            'is_bonus': {'$ne': True},
            # Also ensure if created_by exists, it's the employee themselves
            '$or': [
                {'created_by': {'$exists': False}},  # Employee-initiated (no created_by)
                {'created_by': ObjectId(user_id)}    # Employee created it themselves
            ]
        }).sort('request_date', -1)
        
        requests_list = list(requests)
        
        for req in requests_list:
            try:
                # ✅ Use helper to get category (hr_categories → categories)
                category = get_category_for_employee(req.get('category_id'))
                category_name = category.get('name', 'Unknown') if category else 'Unknown'
                
                # ✅ Skip bonus points in request history
                is_bonus = req.get('is_bonus', False)
                if category and category.get('is_bonus'):
                    is_bonus = True
                if is_bonus:
                    continue

                validator = mongo.db.users.find_one({'_id': req.get('assigned_validator_id')})
                
                # ✅ Determine source for display purposes
                source = 'employee'
                if req.get('ta_id'):
                    source = 'ta'
                elif req.get('pmo_id'):
                    source = 'pmo'
                elif req.get('actioned_by_ld_id'):
                    source = 'ld'
                
                # ✅ Extract event_date based on source
                event_date = None
                if source == 'ta':
                    event_date = req.get('event_date')
                elif source == 'pmo':
                    event_date = req.get('event_date')
                elif source == 'ld':
                    event_date = req.get('metadata', {}).get('event_date')
                
                employee_submitted_history.append({
                    'id': str(req['_id']),
                    'category_name': category_name,
                    'points': req.get('points', 0),
                    'assigned_validator_name': validator.get('name') if validator else None,
                    'request_date': req.get('request_date'),
                    'event_date': event_date,
                    'status': req.get('status', 'Pending'),
                    'submission_notes': get_submission_notes(req),
                    'response_notes': get_response_notes(req),
                    'has_attachment': req.get('has_attachment', False),
                    'attachment_filename': req.get('attachment_filename', ''),
                    'source': source,
                    'is_bonus': req.get('is_bonus', False),
                    'hr_modified': req.get('hr_modified', False)
                })
                
            except Exception as req_error:
                continue
        
    except Exception as e:

        flash('Error loading request history', 'danger')
    
    from dashboard_config import get_user_dashboard_configs
    from flask import make_response
    
    dashboard_access = user.get('dashboard_access', [])
    user_dashboards = get_user_dashboard_configs(dashboard_access)
    other_dashboards = [d for d in user_dashboards if d['normalized_name'] != 'Employee']
    
    rendered_template = render_template('employee_history.html',
                         user=user,
                         employee_submitted_history=employee_submitted_history,
                         other_dashboards=other_dashboards,
                         user_profile_pic_url=None)
    
    # ✅ Add cache-control headers to prevent browser caching across all browsers
    response = make_response(rendered_template)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response