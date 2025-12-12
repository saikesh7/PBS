from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import os
import re
from .hr_utils import check_hr_access
from .hr_analytics import get_location_values_for_filter, matches_location_filter

current_dir = os.path.dirname(os.path.abspath(__file__))

pending_tracker_bp = Blueprint('pending_tracker', __name__, url_prefix='/hr',
                               template_folder=os.path.join(current_dir, 'templates'),
                               static_folder=os.path.join(current_dir, 'static'),
                               static_url_path='/static')


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_effective_event_date(entry):
    """
    Get effective event date with fallback logic
    Priority: event_date > request_date > award_date (SAME AS PBS ANALYTICS)
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
    
    # ✅ FIXED: Try award_date (same as PBS Analytics, not processed_date)
    award_date = entry.get('award_date')
    if award_date and isinstance(award_date, datetime):
        return award_date
    
    return None


def get_pending_location(request_entry):
    """
    Determine WHO the request is pending with based on assigned_validator
    Shows clearly who will approve/reject for pending requests
    """
    status = request_entry.get('status', 'Unknown')
    
    # If not pending, return the status with who processed it
    if status == 'Approved':
        # Show who approved it
        processed_by_id = request_entry.get('processed_by')
        if processed_by_id:
            processor = mongo.db.users.find_one({"_id": processed_by_id})
            if processor:
                processor_name = processor.get('name', 'Unknown')
                processor_role = processor.get('role', '')
                return f" Approved by {processor_name} ({processor_role})"
        return ' Approved - Completed'
    
    elif status == 'Rejected':
        # Show who rejected it
        processed_by_id = request_entry.get('processed_by')
        if processed_by_id:
            processor = mongo.db.users.find_one({"_id": processed_by_id})
            if processor:
                processor_name = processor.get('name', 'Unknown')
                processor_role = processor.get('role', '')
                return f" Rejected by {processor_name} ({processor_role})"
        return ' Rejected - Closed'
    
    # For pending requests, show who needs to approve/reject
    if status == 'Pending':
        # Get assigned validator information - check multiple possible field names
        assigned_validator_id = request_entry.get('assigned_validator_id') or \
                                request_entry.get('pending_validator_id') or \
                                request_entry.get('validator_id') or \
                                request_entry.get('pending_with')
        
        validator_type = request_entry.get('validator', '')
        
        if assigned_validator_id:
            # Get the validator user info
            validator_user = mongo.db.users.find_one({"_id": assigned_validator_id})
            if validator_user:
                validator_name = validator_user.get('name', '').strip()
                validator_role = validator_user.get('role', '').strip()
                
                # Only show name if it exists, is not empty, and is not "Unknown"
                if validator_name and validator_name.lower() not in ['unknown', 'n/a', 'na', '']:
                    # Valid name found - show clearly who will approve/reject
                    if validator_role:
                        return f" Awaiting {validator_name} ({validator_role}) to Approve/Reject"
                    else:
                        return f" Awaiting {validator_name} to Approve/Reject"
                else:
                    # User exists but has no valid name - just show the type
                    if validator_type:
                        return f" Awaiting {validator_type} to Approve/Reject"
                    else:
                        return ' Awaiting Assignment'
            else:
                # Validator ID exists but user not found - just show the type
                if validator_type:
                    return f" Awaiting {validator_type} to Approve/Reject"
                else:
                    return ' Awaiting Assignment'
        else:
            # No specific validator assigned yet
            if validator_type:
                return f" Pending - Awaiting {validator_type} Assignment"
            else:
                return ' Pending - Awaiting Validator Assignment'
    
    return 'Status Unknown'


def get_requested_by_info(request_entry):
    """
    Get information about who raised/created the request
    Checks multiple possible fields: created_by, created_by_hr_id, created_by_ta_id, created_by_pmo_id, created_by_ld_id, requested_by
    """
    # Get the person who created the request - check all possible fields
    created_by_id = request_entry.get('created_by') or \
                    request_entry.get('requested_by') or \
                    request_entry.get('created_by_hr_id') or \
                    request_entry.get('created_by_ta_id') or \
                    request_entry.get('created_by_pmo_id') or \
                    request_entry.get('created_by_ld_id') or \
                    request_entry.get('raised_by')
    
    # Determine which department/role based on the field used
    department_hint = None
    if request_entry.get('created_by_ta_id'):
        department_hint = 'TA'
    elif request_entry.get('created_by_pmo_id'):
        department_hint = 'PMO'
    elif request_entry.get('created_by_hr_id'):
        department_hint = 'HR'
    elif request_entry.get('created_by_ld_id'):
        department_hint = 'L&D'
    
    if not created_by_id:
        # Check if it's a system-generated request
        source = request_entry.get('source', '')
        if source in ['netsuite_sales', 'netsuite_so', 'system']:
            return {
                'name': 'System Generated',
                'role': 'Automated',
                'employee_id': 'SYSTEM'
            }
        
        # Check updated_by field as fallback
        updated_by = request_entry.get('updated_by', '')
        if updated_by:
            return {
                'name': f'{updated_by} Updater',
                'role': f'{updated_by} Updater',
                'employee_id': 'N/A'
            }
        
        return {
            'name': 'Unknown',
            'role': 'Unknown',
            'employee_id': 'N/A'
        }
    
    # Get user info
    user = mongo.db.users.find_one({"_id": created_by_id})
    if user:
        user_name = user.get('name', '').strip()
        user_role = user.get('role', '').strip()
        user_emp_id = user.get('employee_id', 'N/A')
        
        # If user exists but has no name, use department hint
        if not user_name or user_name.lower() in ['unknown', 'n/a', '']:
            if department_hint:
                return {
                    'name': f'{department_hint} Updater',
                    'role': f'{department_hint}_UP',
                    'employee_id': user_emp_id if user_emp_id != 'N/A' else 'N/A'
                }
            else:
                return {
                    'name': 'Unknown User',
                    'role': user_role if user_role else 'Unknown',
                    'employee_id': user_emp_id
                }
        
        return {
            'name': user_name,
            'role': user_role if user_role else 'Unknown',
            'employee_id': user_emp_id
        }
    
    # User ID exists but user not found in database
    # Use department hint as fallback
    if department_hint:
        return {
            'name': f'{department_hint} Updater',
            'role': f'{department_hint}_UP',
            'employee_id': 'N/A'
        }
    
    # Check updated_by field as last resort
    updated_by = request_entry.get('updated_by', '')
    if updated_by:
        return {
            'name': f'{updated_by} Updater',
            'role': f'{updated_by} Updater',
            'employee_id': 'N/A'
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
    If category not found in database, return 'No Category' instead of 'Unknown Category'
    Handles both ObjectId and string types for category_id
    
    Note: Missing categories are auto-fixed on app startup by utils.category_validator
    """
    if not category_id:
        return {'name': 'No Category', 'code': 'N/A'}
    
    # Convert string to ObjectId if needed
    try:
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
    except Exception:
        # Invalid ObjectId format
        return {'name': 'No Category', 'code': 'N/A'}
    
    # Try hr_categories first (new system)
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return {
            'name': category.get('name', 'No Category'),
            'code': category.get('category_code', 'N/A')
        }
    
    # Fallback to old categories collection
    category = mongo.db.categories.find_one({"_id": category_id})
    if category:
        return {
            'name': category.get('name', 'No Category'),
            'code': category.get('code', 'N/A')
        }
    
    # Category ID exists but not found in database - return 'No Category'
    # This should rarely happen as categories are auto-fixed on startup
    return {'name': 'No Category', 'code': 'N/A'}


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
    status_filter = request.args.get('status', '').strip()
    source_filter = request.args.get('source', '').strip()
    validator_filter = request.args.get('validator', '').strip()
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    location_filter = request.args.get('location', '').strip()  # ✅ NEW: Location filter
    
    # ✅ Get utilization category IDs to EXCLUDE from point calculations
    # Utilization is a percentage (85%), not actual points, so we exclude it
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    
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
    if validator_filter and validator_filter != '':
        query['validator'] = validator_filter
    
    # ✅ FIXED: Date range filter - match PBS Analytics logic
    # Filter by event_date, request_date, OR award_date (same as PBS Analytics)
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_date = datetime.combine(end_date.date(), datetime.max.time())
            query['$or'] = [
                {"event_date": {"$gte": start_date, "$lte": end_date}},
                {"request_date": {"$gte": start_date, "$lte": end_date}},
                {"award_date": {"$gte": start_date, "$lte": end_date}}
            ]
        except ValueError:
            flash('Invalid date format', 'warning')
    
    # ✅ NEW: Location filter - get eligible user IDs first
    eligible_user_ids = None
    if location_filter:
        user_query = {"role": {"$in": ["Employee", "Manager"]}}
        location_values = get_location_values_for_filter(location_filter)
        if location_values:
            user_query["$or"] = [
                {"location": {"$in": location_values}},
                {"us_non_us": {"$in": location_values}}
            ]
        eligible_users = list(mongo.db.users.find(user_query, {"_id": 1}))
        eligible_user_ids = [u["_id"] for u in eligible_users]
        
        # If no eligible users found, return empty result
        if not eligible_user_ids:
            query['user_id'] = ObjectId('000000000000000000000000')  # Non-existent ID
    
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
        
        # ✅ FIXED: Combine with location filter if both are applied
        if eligible_user_ids is not None:
            # Intersect with location-filtered users
            user_ids = [uid for uid in user_ids if uid in eligible_user_ids]
        
        if user_ids:
            query['user_id'] = {'$in': user_ids}
        else:
            # No matching users, return empty result
            query['user_id'] = ObjectId('000000000000000000000000')  # Non-existent ID
    elif eligible_user_ids is not None:
        # ✅ FIXED: Apply location filter even if no employee filter
        query['user_id'] = {'$in': eligible_user_ids}
    
    # Category filter (search in both category collections)
    if category_filter:
        category_ids = []
        
        # Escape special regex characters in the filter
        escaped_filter = re.escape(category_filter)
        
        # Search in hr_categories - exact match (case-insensitive)
        hr_cats = list(mongo.db.hr_categories.find({
            'name': {'$regex': f'^{escaped_filter}$', '$options': 'i'}
        }, {'_id': 1}))
        category_ids.extend([c['_id'] for c in hr_cats])
        
        # Search in old categories - exact match (case-insensitive)
        old_cats = list(mongo.db.categories.find({
            'name': {'$regex': f'^{escaped_filter}$', '$options': 'i'}
        }, {'_id': 1}))
        category_ids.extend([c['_id'] for c in old_cats])
        
        if category_ids:
            query['category_id'] = {'$in': category_ids}
        else:
            # No matching categories, return empty result
            query['category_id'] = ObjectId('000000000000000000000000')  # Non-existent ID
    
    # ✅ EXCLUDE utilization category from ALL queries (unless specifically filtered)
    # This ensures point totals don't include utilization percentages
    if not category_filter and utilization_category_ids:
        # Only exclude if user hasn't specifically filtered for a category
        query['category_id'] = {'$nin': utilization_category_ids}
    
    # Fetch requests from points_request collection ONLY
    # Sort: Pending first, then by request_date descending
    pending_requests = list(mongo.db.points_request.find(query).sort([
        ('status', 1),  # Pending comes before Approved/Rejected alphabetically
        ('request_date', -1)  # Most recent first
    ]))
    
    # ✅ FIXED: Apply additional date filtering (same as PBS Analytics)
    # Filter by effective_date to match PBS Analytics logic exactly
    if start_date_str and end_date_str:
        try:
            start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_date_obj = datetime.combine(end_date_obj.date(), datetime.max.time())
            
            filtered_requests = []
            for req in pending_requests:
                # ✅ Skip if no category_id (same as PBS Analytics)
                if not req.get('category_id'):
                    continue
                
                # ✅ CRITICAL: Skip utilization category (same as PBS Analytics)
                category_id = req.get('category_id')
                if category_id in utilization_category_ids:
                    continue
                
                # Get effective date (priority: event_date > request_date > award_date)
                effective_date = get_effective_event_date(req)
                
                # ✅ Skip if no effective_date or not within date range (same as PBS Analytics)
                if not effective_date or not (start_date_obj <= effective_date <= end_date_obj):
                    continue
                
                filtered_requests.append(req)
            
            pending_requests = filtered_requests
        except ValueError:
            pass  # If date parsing fails, use all requests
    else:
        # ✅ Even without date filter, skip records with no category_id and utilization
        pending_requests = [req for req in pending_requests 
                          if req.get('category_id') and req.get('category_id') not in utilization_category_ids]
    
    # Re-sort to ensure Pending is truly first
    # Use datetime object directly for sorting (avoids Windows timestamp issues)
    pending_first = sorted(pending_requests, key=lambda x: (
        0 if x.get('status') == 'Pending' else 1,
        x.get('request_date') if x.get('request_date') else datetime.min
    ), reverse=True)
    
    # Get ALL unique filter options from the ENTIRE database (not just filtered results)
    # This allows users to select any category/source even if not in current filtered view
    all_categories = []
    all_sources = []
    all_validators = []
    
    categories_set = set()
    sources_set = set()
    validators_set = set()
    
    # Get all requests from database to collect filter options
    all_requests = list(mongo.db.points_request.find({}, {'category_id': 1, 'source': 1, 'validator': 1, 'created_by': 1}))
    
    for req in all_requests:
        # Collect categories
        category_id = req.get('category_id')
        if category_id:
            category_info = get_category_info(category_id)
            cat_name = category_info.get('name')
            if cat_name and cat_name not in categories_set:
                all_categories.append(cat_name)
                categories_set.add(cat_name)
        
        # Collect sources - convert to display name
        # Use the full request object to get accurate source display name
        source_display = get_source_display_name(req)
        if source_display and source_display not in sources_set:
            all_sources.append(source_display)
            sources_set.add(source_display)
        
        # Collect validators
        validator = req.get('validator')
        if validator and validator != 'N/A' and validator not in validators_set:
            all_validators.append(validator)
            validators_set.add(validator)
    
    # Sort all filter options
    all_categories.sort()
    all_sources.sort()
    all_validators.sort()
    
    # Enrich data
    enriched_requests = []
    for req in pending_first:
        # ✅ CRITICAL: Double-check - skip utilization category (should already be filtered, but ensure)
        category_id = req.get('category_id')
        if category_id in utilization_category_ids:
            continue  # Skip utilization records completely
        
        employee_info = get_employee_info(req.get('user_id'))
        category_info = get_category_info(category_id)
        requested_by_info = get_requested_by_info(req)
        pending_location = get_pending_location(req)
        event_date = get_effective_event_date(req)
        source_display = get_source_display_name(req)
        
        # Get description from multiple possible field names (for compatibility with different sources)
        description = (
            req.get('request_notes') or 
            req.get('submission_notes') or 
            req.get('notes') or 
            'N/A'
        )
        
        # ✅ FIX: Check if this is a utilization entry and format accordingly
        points_value = req.get('points', 0)
        is_utilization = category_info['code'] == 'utilization_billable' or 'utilization' in category_info['name'].lower()
        utilization_percentage = None
        
        if is_utilization:
            # Try to get utilization value from multiple possible fields
            utilization_value = req.get('utilization_value')
            if not utilization_value and 'submission_data' in req:
                submission_data = req.get('submission_data', {})
                if isinstance(submission_data, dict):
                    utilization_value = submission_data.get('utilization_value') or submission_data.get('utilization')
            
            # Convert to percentage
            if utilization_value is not None and utilization_value > 0:
                if utilization_value <= 1:
                    # It's a decimal (0.85 = 85%)
                    utilization_percentage = round(utilization_value * 100, 2)
                else:
                    # It's already a percentage (85 = 85%)
                    utilization_percentage = round(utilization_value, 2)
        
        enriched_requests.append({
            '_id': str(req['_id']),
            'employee_name': employee_info['name'],
            'employee_id': employee_info['employee_id'],
            'employee_grade': employee_info['grade'],
            'employee_department': employee_info['department'],
            'category_name': category_info['name'],
            'category_code': category_info['code'],
            'points': points_value,
            'is_utilization': is_utilization,
            'utilization_percentage': utilization_percentage,
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
            'description': description,
            'comments': req.get('response_notes', 'N/A'),
            'has_attachment': req.get('has_attachment', False),
            'attachment_filename': req.get('attachment_filename', 'N/A')
        })
    
    # Apply source filter if specified (source_filter contains display name, need to match against enriched source)
    if source_filter:
        enriched_requests = [req for req in enriched_requests if req.get('source') == source_filter]
    
    # ✅ FIXED: Calculate summary statistics with proper date filtering
    # Only count points that fall within the date range (if specified)
    # EXCLUDE utilization category from point totals (it's a percentage, not points)
    total_requests = len(enriched_requests)
    pending_count = sum(1 for r in enriched_requests if r['status'] == 'Pending')
    approved_count = sum(1 for r in enriched_requests if r['status'] == 'Approved')
    rejected_count = sum(1 for r in enriched_requests if r['status'] == 'Rejected')
    
    # ✅ FIXED: Calculate points correctly
    # Utilization already excluded in enriched_requests, just sum up the points
    total_points = sum(r['points'] for r in enriched_requests if r['status'] == 'Approved')
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
        all_sources=all_sources,
        all_validators=all_validators,
        filters={
            'employee': employee_filter,
            'category': category_filter,
            'status': status_filter,
            'source': source_filter,
            'start_date': start_date_str,
            'end_date': end_date_str,
            'location': location_filter  # ✅ NEW: Pass location filter to template
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