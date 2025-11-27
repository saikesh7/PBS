from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import os
from .hr_utils import check_hr_access

current_dir = os.path.dirname(os.path.abspath(__file__))

pending_tracker_bp = Blueprint('pending_tracker', __name__, url_prefix='/hr',
                               template_folder=os.path.join(current_dir, 'templates'),
                               static_folder=os.path.join(current_dir, 'static'),
                               static_url_path='/hr/static')


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_effective_event_date(entry):
    """
    Get effective event date with fallback logic
    Priority: event_date > request_date > processed_date
    """
    if not entry:
        return None
    
    # Try event_date first
    event_date = entry.get('event_date')
    if event_date and isinstance(event_date, datetime):
        return event_date
    
    # Try request_date
    request_date = entry.get('request_date')
    if request_date and isinstance(request_date, datetime):
        return request_date
    
    # Try processed_date (for approved/rejected)
    processed_date = entry.get('processed_date')
    if processed_date and isinstance(processed_date, datetime):
        return processed_date
    
    return None


def get_pending_location(request_entry):
    """
    Determine WHO the request is pending with based on assigned_validator
    """
    status = request_entry.get('status', 'Unknown')
    
    # If not pending, return the status
    if status == 'Approved':
        # Show who approved it
        processed_by_id = request_entry.get('processed_by')
        if processed_by_id:
            processor = mongo.db.users.find_one({"_id": processed_by_id})
            if processor:
                return f"Approved by {processor.get('name', 'Unknown')}"
        return 'Approved - Completed'
    
    elif status == 'Rejected':
        # Show who rejected it
        processed_by_id = request_entry.get('processed_by')
        if processed_by_id:
            processor = mongo.db.users.find_one({"_id": processed_by_id})
            if processor:
                return f"Rejected by {processor.get('name', 'Unknown')}"
        return 'Rejected - Closed'
    
    # For pending requests, show who needs to approve
    if status == 'Pending':
        # Get assigned validator information - check multiple possible field names
        assigned_validator_id = request_entry.get('assigned_validator_id') or \
                                request_entry.get('pending_validator_id') or \
                                request_entry.get('validator_id')
        
        validator_type = request_entry.get('validator', '')
        
        if assigned_validator_id:
            # Get the validator user info
            validator_user = mongo.db.users.find_one({"_id": assigned_validator_id})
            if validator_user:
                validator_name = validator_user.get('name', '').strip()
                # Only show name if it exists, is not empty, and is not "Unknown"
                if validator_name and validator_name.lower() not in ['unknown', 'n/a', 'na', '']:
                    # Valid name found - show name with type
                    if validator_type:
                        return f"Pending with {validator_name} ({validator_type})"
                    else:
                        return f"Pending with {validator_name}"
                else:
                    # User exists but has no valid name - just show the type
                    if validator_type:
                        return f"Pending with {validator_type}"
                    else:
                        return 'Pending - Awaiting Assignment'
            else:
                # Validator ID exists but user not found - just show the type
                if validator_type:
                    return f"Pending with {validator_type}"
                else:
                    return 'Pending - Awaiting Assignment'
        else:
            # No specific validator assigned yet
            if validator_type:
                return f"Pending - {validator_type} Review"
            else:
                return 'Pending - Awaiting Assignment'
    
    return 'Status Unknown'


def get_requested_by_info(request_entry):
    """
    Get information about who raised/created the request
    Checks multiple possible fields: created_by, created_by_hr_id, created_by_ta_id, created_by_pmo_id, created_by_ld_id
    """
    # Get the person who created the request - check all possible fields
    created_by_id = request_entry.get('created_by') or \
                    request_entry.get('created_by_hr_id') or \
                    request_entry.get('created_by_ta_id') or \
                    request_entry.get('created_by_pmo_id') or \
                    request_entry.get('created_by_ld_id')
    
    if not created_by_id:
        return {
            'name': 'System/Unknown',
            'role': 'Unknown',
            'employee_id': 'N/A'
        }
    
    # Get user info
    user = mongo.db.users.find_one({"_id": created_by_id})
    if user:
        return {
            'name': user.get('name', 'Unknown'),
            'role': user.get('role', 'Unknown'),
            'employee_id': user.get('employee_id', 'N/A')
        }
    
    return {
        'name': 'Unknown User',
        'role': 'Unknown',
        'employee_id': 'N/A'
    }


def get_employee_info(user_id):
    """Get employee information"""
    if not user_id:
        return {
            'name': 'Unknown',
            'employee_id': 'N/A',
            'grade': 'N/A',
            'department': 'N/A'
        }
    
    user = mongo.db.users.find_one({"_id": user_id})
    if user:
        return {
            'name': user.get('name', 'Unknown'),
            'employee_id': user.get('employee_id', 'N/A'),
            'grade': user.get('grade', 'N/A'),
            'department': user.get('department', 'N/A')
        }
    
    return {
        'name': 'Unknown',
        'employee_id': 'N/A',
        'grade': 'N/A',
        'department': 'N/A'
    }


def get_category_info(category_id):
    """
    Get category information from both hr_categories and categories collections
    Try hr_categories first, then fallback to old categories
    """
    if not category_id:
        return {'name': 'Unknown', 'code': 'N/A'}
    
    # Try hr_categories first (new system)
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return {
            'name': category.get('name', 'Unknown'),
            'code': category.get('category_code', 'N/A')
        }
    
    # Fallback to old categories collection
    category = mongo.db.categories.find_one({"_id": category_id})
    if category:
        return {
            'name': category.get('name', 'Unknown'),
            'code': category.get('code', 'N/A')
        }
    
    return {'name': 'Unknown Category', 'code': 'N/A'}


def get_source_display_name(request_entry):
    """
    Determine source based on available fields
    If no explicit source, it's a user-created request
    """
    # Check if there's a source field
    source = request_entry.get('source')
    if source:
        source_map = {
            'manager_request': 'Manager Request',
            'hr_bonus': 'HR Bonus',
            'netsuite_sales': 'NetSuite Sales',
            'netsuite_so': 'NetSuite SO',
            'manual': 'Manual Entry',
            'system': 'System Generated'
        }
        return source_map.get(source, source)
    
    # If no source field, it's a user-created request
    validator = request_entry.get('validator', '')
    created_by_id = request_entry.get('created_by')
    
    if created_by_id:
        creator = mongo.db.users.find_one({"_id": created_by_id})
        if creator:
            creator_role = creator.get('role', '')
            if creator_role == 'Manager':
                return 'Manager Request'
            elif creator_role == 'Employee':
                return 'Employee Request'
    
    # Default based on validator
    if validator:
        return f'User Request ({validator})'
    
    return 'User Request'


# ==========================================
# ROUTES
# ==========================================

@pending_tracker_bp.route('/pending_points_tracker', methods=['GET'])
def pending_points_tracker():
    """Main pending points tracker dashboard"""
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    # Get filter parameters
    employee_filter = request.args.get('employee', '').strip()
    category_filter = request.args.get('category', '').strip()
    status_filter = request.args.get('status', 'all')
    validator_filter = request.args.get('validator', 'all')
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    
    # Build query for points_request collection
    query = {}
    
    # Status filter
    if status_filter == 'pending':
        query['status'] = 'Pending'
    elif status_filter == 'approved':
        query['status'] = 'Approved'
    elif status_filter == 'rejected':
        query['status'] = 'Rejected'
    
    # Validator filter
    if validator_filter != 'all':
        query['validator'] = validator_filter
    
    # Date range filter (on request_date)
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_date = datetime.combine(end_date.date(), datetime.max.time())
            query['request_date'] = {'$gte': start_date, '$lte': end_date}
        except ValueError:
            flash('Invalid date format', 'warning')
    
    # Employee filter (search by name or employee_id)
    if employee_filter:
        # Find matching users
        user_query = {
            '$or': [
                {'name': {'$regex': employee_filter, '$options': 'i'}},
                {'employee_id': {'$regex': employee_filter, '$options': 'i'}}
            ]
        }
        matching_users = list(mongo.db.users.find(user_query, {'_id': 1}))
        user_ids = [u['_id'] for u in matching_users]
        
        if user_ids:
            query['user_id'] = {'$in': user_ids}
        else:
            # No matching users, return empty result
            query['user_id'] = ObjectId('000000000000000000000000')  # Non-existent ID
    
    # Category filter (search in both category collections)
    if category_filter:
        category_ids = []
        
        # Search in hr_categories
        hr_cats = list(mongo.db.hr_categories.find({
            'name': {'$regex': category_filter, '$options': 'i'}
        }, {'_id': 1}))
        category_ids.extend([c['_id'] for c in hr_cats])
        
        # Search in old categories
        old_cats = list(mongo.db.categories.find({
            'name': {'$regex': category_filter, '$options': 'i'}
        }, {'_id': 1}))
        category_ids.extend([c['_id'] for c in old_cats])
        
        if category_ids:
            query['category_id'] = {'$in': category_ids}
        else:
            # No matching categories, return empty result
            query['category_id'] = ObjectId('000000000000000000000000')  # Non-existent ID
    
    # Fetch requests from points_request collection ONLY
    # Sort: Pending first, then by request_date descending
    pending_requests = list(mongo.db.points_request.find(query).sort([
        ('status', 1),  # Pending comes before Approved/Rejected alphabetically
        ('request_date', -1)  # Most recent first
    ]))
    
    # Re-sort to ensure Pending is truly first
    pending_first = sorted(pending_requests, key=lambda x: (
        0 if x.get('status') == 'Pending' else 1,
        -(x.get('request_date').timestamp() if x.get('request_date') else 0)
    ))
    
    # Enrich data
    enriched_requests = []
    for req in pending_first:
        employee_info = get_employee_info(req.get('user_id'))
        category_info = get_category_info(req.get('category_id'))
        requested_by_info = get_requested_by_info(req)
        pending_location = get_pending_location(req)
        event_date = get_effective_event_date(req)
        source_display = get_source_display_name(req)
        
        enriched_requests.append({
            '_id': str(req['_id']),
            'employee_name': employee_info['name'],
            'employee_id': employee_info['employee_id'],
            'employee_grade': employee_info['grade'],
            'employee_department': employee_info['department'],
            'category_name': category_info['name'],
            'category_code': category_info['code'],
            'points': req.get('points', 0),
            'status': req.get('status', 'Unknown'),
            'source': source_display,
            'validator': req.get('validator', 'N/A'),
            'pending_location': pending_location,
            'requested_by_name': requested_by_info['name'],
            'requested_by_role': requested_by_info['role'],
            'requested_by_employee_id': requested_by_info['employee_id'],
            'request_date': req.get('request_date'),
            'event_date': event_date,
            'processed_date': req.get('processed_date'),
            'description': req.get('request_notes', 'N/A'),
            'comments': req.get('response_notes', 'N/A'),
            'has_attachment': req.get('has_attachment', False),
            'attachment_filename': req.get('attachment_filename', 'N/A')
        })
    
    # Get unique categories for filter dropdown (from both collections)
    all_categories = []
    category_names_set = set()
    
    # Get from hr_categories
    hr_categories = list(mongo.db.hr_categories.find({}, {'name': 1}).sort('name', 1))
    for cat in hr_categories:
        cat_name = cat.get('name')
        if cat_name and cat_name not in category_names_set:
            all_categories.append(cat_name)
            category_names_set.add(cat_name)
    
    # Get from old categories
    old_categories = list(mongo.db.categories.find({}, {'name': 1}).sort('name', 1))
    for cat in old_categories:
        cat_name = cat.get('name')
        if cat_name and cat_name not in category_names_set:
            all_categories.append(cat_name)
            category_names_set.add(cat_name)
    
    all_categories.sort()
    
    # Get unique validators for filter dropdown
    all_validators = list(mongo.db.points_request.distinct('validator'))
    all_validators = [v for v in all_validators if v]  # Remove None/empty
    all_validators.sort()
    
    # Calculate summary statistics
    total_requests = len(enriched_requests)
    pending_count = sum(1 for r in enriched_requests if r['status'] == 'Pending')
    approved_count = sum(1 for r in enriched_requests if r['status'] == 'Approved')
    rejected_count = sum(1 for r in enriched_requests if r['status'] == 'Rejected')
    total_points = sum(r['points'] for r in enriched_requests)
    pending_points = sum(r['points'] for r in enriched_requests if r['status'] == 'Pending')
    
    summary = {
        'total_requests': total_requests,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'total_points': total_points,
        'pending_points': pending_points
    }
    
    # Get current quarter and month for header display
    from .hr_analytics import get_financial_quarter_and_label
    now = datetime.utcnow()
    _, quarter_label, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
    display_quarter = f"{quarter_label} {fiscal_year_label}"
    display_month = now.strftime("%b %Y").upper()
    
    return render_template(
        'pending_points_tracker.html',
        requests=enriched_requests,
        summary=summary,
        all_categories=all_categories,
        all_validators=all_validators,
        filters={
            'employee': employee_filter,
            'category': category_filter,
            'status': status_filter,
            'validator': validator_filter,
            'start_date': start_date_str,
            'end_date': end_date_str
        },
        display_quarter=display_quarter,
        display_month=display_month,
        user=user
    )


@pending_tracker_bp.route('/api/pending_points_data', methods=['GET'])
def api_pending_points_data():
    """API endpoint for pending points data"""
    has_access, user = check_hr_access()
    
    if not has_access:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get filter parameters
    employee_filter = request.args.get('employee', '').strip()
    category_filter = request.args.get('category', '').strip()
    status_filter = request.args.get('status', 'all')
    
    query = {}
    
    if status_filter == 'pending':
        query['status'] = 'Pending'
    elif status_filter == 'approved':
        query['status'] = 'Approved'
    elif status_filter == 'rejected':
        query['status'] = 'Rejected'
    
    if employee_filter:
        user_query = {
            '$or': [
                {'name': {'$regex': employee_filter, '$options': 'i'}},
                {'employee_id': {'$regex': employee_filter, '$options': 'i'}}
            ]
        }
        matching_users = list(mongo.db.users.find(user_query, {'_id': 1}))
        user_ids = [u['_id'] for u in matching_users]
        
        if user_ids:
            query['user_id'] = {'$in': user_ids}
        else:
            query['user_id'] = ObjectId('000000000000000000000000')
    
    if category_filter:
        category_ids = []
        
        hr_cats = list(mongo.db.hr_categories.find({
            'name': {'$regex': category_filter, '$options': 'i'}
        }, {'_id': 1}))
        category_ids.extend([c['_id'] for c in hr_cats])
        
        old_cats = list(mongo.db.categories.find({
            'name': {'$regex': category_filter, '$options': 'i'}
        }, {'_id': 1}))
        category_ids.extend([c['_id'] for c in old_cats])
        
        if category_ids:
            query['category_id'] = {'$in': category_ids}
        else:
            query['category_id'] = ObjectId('000000000000000000000000')
    
    pending_requests = list(mongo.db.points_request.find(query).sort([
        ('status', 1),
        ('request_date', -1)
    ]))
    
    enriched_requests = []
    for req in pending_requests:
        employee_info = get_employee_info(req.get('user_id'))
        category_info = get_category_info(req.get('category_id'))
        requested_by_info = get_requested_by_info(req)
        pending_location = get_pending_location(req)
        event_date = get_effective_event_date(req)
        
        enriched_requests.append({
            '_id': str(req['_id']),
            'employee_name': employee_info['name'],
            'employee_id': employee_info['employee_id'],
            'category_name': category_info['name'],
            'points': req.get('points', 0),
            'status': req.get('status', 'Unknown'),
            'pending_location': pending_location,
            'requested_by_name': requested_by_info['name'],
            'request_date': req.get('request_date').isoformat() if req.get('request_date') else None,
            'event_date': event_date.isoformat() if event_date else None
        })
    
    return jsonify({
        'requests': enriched_requests,
        'total': len(enriched_requests)
    })