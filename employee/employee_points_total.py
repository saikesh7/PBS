from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, send_file, flash
from extensions import mongo
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from gridfs import GridFS
import io
import traceback

employee_points_total_bp = Blueprint(
    'employee_points_total', 
    __name__, 
    url_prefix='/employee',
    template_folder='templates',
    static_folder='static'
)

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

def get_category_for_employee(category_id):
    """
    Fetch category for employee data with robust error handling
    Priority: hr_categories (new data) → categories (old data)
    Note: Missing categories are auto-fixed on app startup by utils.category_validator
    """
    if not category_id:
        return None
    
    try:
        # Convert to ObjectId if string
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
        
        # Try hr_categories FIRST (where new employee categories are stored)
        category = mongo.db.hr_categories.find_one({'_id': category_id})
        if category:
            return category
        
        # Fallback to categories (where old employee categories were stored)
        category = mongo.db.categories.find_one({'_id': category_id})
        if category:
            return category
        
        # If still not found, return placeholder to prevent crashes
        # This should rarely happen as categories are auto-fixed on startup
        return {'name': 'Uncategorized', 'code': 'N/A'}
        
    except Exception as e:
        return {'name': 'Uncategorized', 'code': 'N/A'}

def is_utilization_category(category):
    """Check if category is utilization/billable"""
    if not category:
        return False
    
    category_name = category.get('name', '').lower()
    category_code = category.get('code', '').lower()
    
    return 'utilization' in category_name or 'billable' in category_name or category_code == 'utilization_billable'

# ✅ HELPER FUNCTION: Get effective date with error handling
def get_effective_date(entry):
    """Priority: event_date > request_date > award_date"""
    try:
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
    except Exception as e:
        return None

# ✅ HELPER FUNCTION: Get fiscal quarter from date
def get_fiscal_quarter_year(date_obj):
    """
    Returns fiscal quarter and year (April-March)
    Q1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar
    """
    if not date_obj or not isinstance(date_obj, datetime):
        return None, None
    
    try:
        month = date_obj.month
        year = date_obj.year
        
        if 1 <= month <= 3:
            quarter = 4
            fiscal_year = year - 1
        elif 4 <= month <= 6:
            quarter = 1
            fiscal_year = year
        elif 7 <= month <= 9:
            quarter = 2
            fiscal_year = year
        else:  # 10-12
            quarter = 3
            fiscal_year = year
        
        return quarter, fiscal_year
    except Exception as e:
        return None, None

@employee_points_total_bp.route('/points-total')
def points_total():
    """Total points history page - Using HR Analytics Logic"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return redirect(url_for('auth.login'))
    
    # Initialize totals
    total_points = 0
    total_bonus_points = 0
    request_history = []
    
    try:
        # ============================================
        # ✅ FIXED: Get ALL points from BOTH collections (like leaderboard)
        # ============================================
        
        # Get utilization category IDs to exclude from totals
        utilization_category_ids = []
        util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
        if util_cat_hr:
            utilization_category_ids.append(util_cat_hr["_id"])
        util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
        if util_cat_old:
            utilization_category_ids.append(util_cat_old["_id"])
        
        # Track processed request IDs to avoid double counting
        processed_request_ids = set()
        
        # ✅ FIXED: Separate regular and bonus points tracking
        total_regular_points = 0
        
        # ✅ STEP 1: Query approved points_request first
        approved_requests = list(mongo.db.points_request.find({
            'user_id': ObjectId(user_id),
            'status': 'Approved'
        }).sort('request_date', -1))
        
        # Process approved requests
        for req in approved_requests:
            try:
                req_id = req['_id']
                processed_request_ids.add(req_id)
                
                category_id = req.get('category_id')
                points_value = req.get('points', 0)
                
                # Fetch category
                category = get_category_for_employee(category_id)
                category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
                
                # Check if utilization
                is_utilization = is_utilization_category(category)
                
                # Check if bonus
                is_bonus = req.get('is_bonus', False)
                if category and category.get('is_bonus'):
                    is_bonus = True
                
                # ✅ FIXED: Count regular and bonus separately
                if isinstance(points_value, (int, float)) and not is_utilization:
                    if is_bonus:
                        total_bonus_points += points_value
                    else:
                        total_regular_points += points_value
                
                # Get display value
                display_value = points_value
                utilization_percentage = None
                
                if is_utilization and 'utilization_value' in req:
                    utilization_value = req.get('utilization_value', 0)
                    utilization_percentage = round(utilization_value * 100, 2)
                    display_value = f"{utilization_percentage}%"
                elif is_utilization:
                    display_value = "N/A"
                
                # Get dates
                request_date = req.get('request_date')
                if not isinstance(request_date, datetime):
                    request_date = datetime.utcnow()
                
                event_date = req.get('event_date')
                award_date = req.get('award_date')
                
                effective_date = event_date if event_date and isinstance(event_date, datetime) else \
                                request_date if request_date and isinstance(request_date, datetime) else \
                                award_date if award_date and isinstance(award_date, datetime) else request_date
                
                # Calculate fiscal quarter
                quarter, fiscal_year = get_fiscal_quarter_year(effective_date)
                quarter_label = f"FY{fiscal_year} Q{quarter}" if quarter and fiscal_year else None
                
                # Determine source
                source = 'employee' if req.get('source') == 'employee_request' or \
                        (req.get('created_by') and str(req.get('created_by')) == str(user_id)) else 'manager'
                display_source = 'Employee Request' if source == 'employee' else 'Direct Award'
                
                # ✅ FIXED: Store fiscal year for filtering (not calendar year)
                # This ensures Q4-2025 (Jan-Mar 2026) is included when filtering by year 2025
                year_for_filter = fiscal_year
                
                # Get validator name - check multiple fields
                validator_name = None
                if is_bonus and req.get('bonus_approved_by_id'):
                    try:
                        bonus_approver = mongo.db.users.find_one({'_id': req['bonus_approved_by_id']})
                        if bonus_approver:
                            validator_name = bonus_approver.get('name')
                    except:
                        pass
                
                if not validator_name and req.get('assigned_validator_id'):
                    try:
                        validator = mongo.db.users.find_one({'_id': req['assigned_validator_id']})
                        if validator:
                            validator_name = validator.get('name')
                    except:
                        pass
                
                if not validator_name and req.get('processed_by'):
                    try:
                        processor = mongo.db.users.find_one({'_id': req['processed_by']})
                        if processor:
                            validator_name = processor.get('name')
                    except:
                        pass
                
                # ✅ NEW: Check additional fields for validator
                if not validator_name and req.get('awarded_by'):
                    try:
                        awarder = mongo.db.users.find_one({'_id': req['awarded_by']})
                        if awarder:
                            validator_name = awarder.get('name')
                    except:
                        pass
                
                if not validator_name and req.get('approved_by'):
                    try:
                        approver = mongo.db.users.find_one({'_id': req['approved_by']})
                        if approver:
                            validator_name = approver.get('name')
                    except:
                        pass
                
                # ✅ NEW: If still no validator, show "Auto-Approved" or "System"
                if not validator_name:
                    # Check if it's a system-generated entry (TA, PMO, LD, etc.)
                    if req.get('ta_id') or req.get('created_by_ta_id'):
                        validator_name = 'TA System'
                    elif req.get('pmo_id') or req.get('created_by_pmo_id'):
                        validator_name = 'PMO System'
                    elif req.get('created_by_ld_id') or req.get('actioned_by_ld_id'):
                        validator_name = 'L&D System'
                    elif req.get('created_by_market_id'):
                        validator_name = 'Marketing System'
                    elif req.get('created_by_presales_id'):
                        validator_name = 'Presales System'
                    elif is_utilization:
                        validator_name = 'HR System'
                    else:
                        validator_name = 'Auto-Approved'
                
                # ✅ FIXED: Use fiscal year for year field (not calendar year)
                year_str = str(year_for_filter) if year_for_filter else None
                
                entry = {
                    'id': str(req_id),
                    'category_name': category_name,
                    'points': points_value,
                    'display_value': display_value,
                    'is_utilization': is_utilization,
                    'utilization_percentage': utilization_percentage,
                    'request_date': request_date,
                    'event_date': event_date,
                    'display_date': effective_date,
                    'year': year_str,
                    'quarter_label': quarter_label,
                    'status': 'Approved',
                    'submission_notes': get_submission_notes(req),
                    'response_notes': get_response_notes(req),
                    'has_attachment': req.get('has_attachment', False),
                    'attachment_filename': req.get('attachment_filename', ''),
                    'attachment_id': req.get('attachment_id'),
                    'source': source,
                    'display_source': display_source,
                    'is_bonus': is_bonus,
                    'validator_name': validator_name,
                    'from_collection': 'points_request'
                }
                
                request_history.append(entry)
                
            except Exception as req_error:
                continue
        
        # ✅ REMOVED: No longer fetching from points collection
        # Only use points_request collection for consistency with database export
        
        # Skip points collection processing
        if False:  # Disabled
            points_entries = []
        else:
            points_entries = []
        
        for point in points_entries:
            try:
                # ✅ Skip if already counted from points_request
                request_id = point.get('request_id')
                if request_id and request_id in processed_request_ids:
                    continue
                
                point_id = str(point['_id'])
                category_id = point.get('category_id')
                points_value = point.get('points', 0)
                
                # Fetch category
                category = get_category_for_employee(category_id)
                category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
                
                # Check if utilization
                is_utilization = is_utilization_category(category)
                
                # Check if bonus
                is_bonus = point.get('is_bonus', False)
                if category and category.get('is_bonus'):
                    is_bonus = True
                
                # ✅ FIXED: Count regular and bonus separately
                if isinstance(points_value, (int, float)) and not is_utilization:
                    if is_bonus:
                        total_bonus_points += points_value
                    else:
                        total_regular_points += points_value
                
                # Get display value
                display_value = points_value
                utilization_percentage = None
                
                # ✅ Check for attachment in original request
                has_attachment = point.get('has_attachment', False)
                attachment_filename = point.get('attachment_filename', '')
                attachment_id = point.get('attachment_id')
                
                if is_utilization:
                    # Try to get utilization percentage
                    point_request_id = point.get('request_id')
                    if point_request_id:
                        try:
                            original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                            if original_request:
                                if 'utilization_value' in original_request:
                                    utilization_value = original_request.get('utilization_value', 0)
                                    utilization_percentage = round(utilization_value * 100, 2)
                                    display_value = f"{utilization_percentage}%"
                                # ✅ Get attachment info from original request if not in point
                                if not has_attachment and original_request.get('has_attachment'):
                                    has_attachment = True
                                    attachment_filename = original_request.get('attachment_filename', '')
                                    attachment_id = original_request.get('attachment_id')
                        except:
                            pass
                    
                    if not utilization_percentage and 'utilization_value' in point:
                        utilization_value = point.get('utilization_value', 0)
                        utilization_percentage = round(utilization_value * 100, 2)
                        display_value = f"{utilization_percentage}%"
                    
                    if not utilization_percentage:
                        display_value = "N/A"
                else:
                    # ✅ For non-utilization points, also check original request for attachment
                    point_request_id = point.get('request_id')
                    if point_request_id and not has_attachment:
                        try:
                            original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                            if original_request and original_request.get('has_attachment'):
                                has_attachment = True
                                attachment_filename = original_request.get('attachment_filename', '')
                                attachment_id = original_request.get('attachment_id')
                        except:
                            pass
                
                # Get dates
                award_date = point.get('award_date')
                if not isinstance(award_date, datetime):
                    award_date = datetime.utcnow()
                
                event_date = point.get('event_date')
                if 'metadata' in point and 'event_date' in point['metadata']:
                    event_date = point['metadata']['event_date']
                
                effective_date = event_date if event_date and isinstance(event_date, datetime) else award_date
                
                # Calculate fiscal quarter
                quarter, fiscal_year = get_fiscal_quarter_year(effective_date)
                quarter_label = f"FY{fiscal_year} Q{quarter}" if quarter and fiscal_year else None
                
                # Determine source
                source = 'manager'
                point_request_id = point.get('request_id')
                if point_request_id:
                    try:
                        original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                        if original_request:
                            if original_request.get('source') == 'employee_request':
                                source = 'employee'
                            elif original_request.get('created_by') and str(original_request.get('created_by')) == str(user_id):
                                source = 'employee'
                    except:
                        pass
                
                if source == 'manager' and point.get('awarded_by'):
                    try:
                        awarded_by_user = mongo.db.users.find_one({"_id": point['awarded_by']})
                        if awarded_by_user:
                            dashboard_access = awarded_by_user.get('dashboard_access', [])
                            if 'central' in dashboard_access:
                                source = 'central'
                            elif 'hr' in dashboard_access:
                                source = 'hr'
                    except:
                        pass
                
                display_source = 'Employee Request' if source == 'employee' else 'Direct Award'
                
                # ✅ Get validator name
                validator_name = None
                
                # For bonus points, check bonus_approved_by_id first
                if is_bonus and point.get('bonus_approved_by_id'):
                    try:
                        bonus_approver = mongo.db.users.find_one({'_id': point['bonus_approved_by_id']})
                        if bonus_approver:
                            validator_name = bonus_approver.get('name')
                    except:
                        pass
                
                # If not found, check request_id for validator
                if not validator_name:
                    point_request_id = point.get('request_id')
                    if point_request_id:
                        try:
                            original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                            if original_request and original_request.get('assigned_validator_id'):
                                validator = mongo.db.users.find_one({'_id': original_request['assigned_validator_id']})
                                if validator:
                                    validator_name = validator.get('name')
                        except:
                            pass
                
                # If still not found and it's a direct award, check awarded_by
                if not validator_name and point.get('awarded_by'):
                    try:
                        awarded_by_user = mongo.db.users.find_one({'_id': point['awarded_by']})
                        if awarded_by_user:
                            validator_name = awarded_by_user.get('name')
                    except:
                        pass
                
                # ✅ Use request_id for attachment link if available, otherwise use point_id
                attachment_link_id = str(point.get('request_id')) if point.get('request_id') else point_id
                
                entry = {
                    'id': attachment_link_id,  # Use request_id for attachment downloads
                    'category_name': category_name,
                    'points': points_value,
                    'display_value': display_value,
                    'is_utilization': is_utilization,
                    'utilization_percentage': utilization_percentage,
                    'request_date': award_date,
                    'event_date': event_date,
                    'display_date': effective_date,
                    'quarter_label': quarter_label,
                    'status': 'Approved',
                    'submission_notes': point.get('notes', ''),
                    'response_notes': point.get('notes', ''),
                    'has_attachment': has_attachment,
                    'attachment_filename': attachment_filename,
                    'attachment_id': attachment_id,
                    'source': source,
                    'display_source': display_source,
                    'is_bonus': is_bonus,
                    'validator_name': validator_name,
                    'from_collection': 'points'
                }
                
                request_history.append(entry)
                
            except Exception as point_error:
                continue
        
        # ============================================
        # Add Pending/Rejected employee requests
        # ============================================
        try:
            pending_requests = list(mongo.db.points_request.find({
                'user_id': ObjectId(user_id),
                'status': {'$in': ['Pending', 'Rejected']},
                '$or': [
                    {'source': 'employee_request'},
                    {'created_by': ObjectId(user_id)}
                ]
            }).sort('request_date', -1))
            
            for req in pending_requests:
                try:
                    category = get_category_for_employee(req.get('category_id'))
                    category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
                    
                    is_utilization = is_utilization_category(category)
                    is_bonus = req.get('is_bonus', False)
                    if category and category.get('is_bonus'):
                        is_bonus = True
                    
                    points_value = req.get('points', 0)
                    display_value = points_value
                    utilization_percentage = None
                    
                    if is_utilization and 'utilization_value' in req:
                        utilization_value = req.get('utilization_value', 0)
                        utilization_percentage = round(utilization_value * 100, 2)
                        display_value = f"{utilization_percentage}%"
                    
                    request_date = req.get('request_date')
                    if not isinstance(request_date, datetime):
                        request_date = datetime.utcnow()
                    
                    event_date = req.get('event_date')
                    effective_date = event_date if event_date and isinstance(event_date, datetime) else request_date
                    
                    quarter, fiscal_year = get_fiscal_quarter_year(effective_date)
                    quarter_label = f"FY{fiscal_year} Q{quarter}" if quarter and fiscal_year else None
                    
                    # ✅ FIXED: Use fiscal year (not calendar year)
                    year_str = str(fiscal_year) if fiscal_year else None
                    
                    # ✅ Get validator name
                    validator_name = None
                    
                    # For bonus points, check bonus_approved_by_id first
                    if is_bonus and req.get('bonus_approved_by_id'):
                        try:
                            bonus_approver = mongo.db.users.find_one({'_id': req['bonus_approved_by_id']})
                            if bonus_approver:
                                validator_name = bonus_approver.get('name')
                        except:
                            pass
                    
                    # If not found, check assigned_validator_id
                    if not validator_name and req.get('assigned_validator_id'):
                        try:
                            validator = mongo.db.users.find_one({'_id': req['assigned_validator_id']})
                            if validator:
                                validator_name = validator.get('name')
                        except:
                            pass
                    
                    entry = {
                        'id': str(req['_id']),
                        'category_name': category_name,
                        'points': points_value,
                        'display_value': display_value,
                        'is_utilization': is_utilization,
                        'utilization_percentage': utilization_percentage,
                        'request_date': request_date,
                        'event_date': event_date,
                        'display_date': effective_date,
                        'year': year_str,
                        'quarter_label': quarter_label,
                        'status': req.get('status', 'Pending'),
                        'submission_notes': get_submission_notes(req),
                        'response_notes': get_response_notes(req),
                        'has_attachment': req.get('has_attachment', False),
                        'attachment_filename': req.get('attachment_filename', ''),
                        'source': 'employee',
                        'display_source': 'Employee Request',
                        'is_bonus': is_bonus,
                        'validator_name': validator_name,
                        'from_collection': 'points_request'
                    }
                    
                    request_history.append(entry)
                    
                except Exception as req_error:
                    continue
        
        except Exception as pending_error:
            pass
        
        # Sort by date
        request_history.sort(
            key=lambda x: x['display_date'] if x['display_date'] else datetime.min,
            reverse=True
        )
        
        # ✅ FIXED: Total points = Regular only (bonus shown separately)
        total_points = total_regular_points
        
    except Exception as e:
        flash('Error loading points history. Please contact support if this persists.', 'danger')
        request_history = []
        total_points = 0
        total_bonus_points = 0
    
    return render_template('employee_points_total.html',
                         user=user,
                         request_history=request_history,
                         total_points=int(total_points),
                         total_bonus_points=int(total_bonus_points),
                         other_dashboards=[],
                         user_profile_pic_url=None)

@employee_points_total_bp.route('/api/filter-points', methods=['POST'])
def filter_points():
    """API endpoint to filter points based on criteria"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        filters = request.get_json()
        year = filters.get('year', 'all')
        quarter = filters.get('quarter', 'all')
        category = filters.get('category', 'all')
        source = filters.get('source', 'all')
        point_type = filters.get('pointType', 'all')
        status = filters.get('status', 'all')
        
        # Get utilization category IDs
        utilization_category_ids = []
        util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
        if util_cat_hr:
            utilization_category_ids.append(util_cat_hr["_id"])
        util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
        if util_cat_old:
            utilization_category_ids.append(util_cat_old["_id"])
        
        # ✅ Query BOTH collections
        filtered_history = []
        total_regular = 0
        total_bonus = 0
        processed_request_ids = set()
        
        # ✅ STEP 1: Get approved requests
        approved_requests = list(mongo.db.points_request.find({
            'user_id': ObjectId(user_id),
            'status': 'Approved'
        }).sort('request_date', -1))
        
        # Process approved requests
        for req in approved_requests:
            try:
                processed_request_ids.add(req['_id'])
                
                category_id = req.get('category_id')
                cat = get_category_for_employee(category_id)
                
                # ✅ FIX: Don't skip entries with missing categories, show as "Unknown Category"
                if cat:
                    category_name = cat.get('name', 'Unknown Category')
                    is_utilization = is_utilization_category(cat)
                    is_bonus = req.get('is_bonus', False) or cat.get('is_bonus', False)
                else:
                    category_name = 'Unknown Category'
                    is_utilization = False
                    is_bonus = req.get('is_bonus', False)
                points_value = req.get('points', 0)
                
                # Get dates
                request_date = req.get('request_date')
                if not isinstance(request_date, datetime):
                    request_date = datetime.utcnow()
                
                event_date = req.get('event_date')
                award_date = req.get('award_date')
                
                effective_date = event_date if event_date and isinstance(event_date, datetime) else \
                                request_date if request_date and isinstance(request_date, datetime) else \
                                award_date if award_date and isinstance(award_date, datetime) else request_date
                
                # Calculate fiscal quarter
                q, fy = get_fiscal_quarter_year(effective_date)
                quarter_label = f"FY{fy} Q{q}" if q and fy else None
                
                # Determine source
                src = 'employee' if req.get('source') == 'employee_request' or \
                     (req.get('created_by') and str(req.get('created_by')) == str(user_id)) else 'manager'
                display_source = 'Employee Request' if src == 'employee' else 'Direct Award'
                
                # ✅ FIXED: Get FISCAL year from effective date (not calendar year)
                # This ensures Q4-2025 (Jan-Mar 2026) is included when filtering by year 2025
                year_str = str(fy) if fy else None
                
                # Apply filters
                if year != 'all' and year_str != year:
                    continue
                
                # ✅ FIXED: Quarter filter now accepts both "Q1" and "FY2025 Q1" formats
                if quarter != 'all':
                    # If quarter is just "Q1", "Q2", etc., match against the quarter number only
                    if quarter.startswith('Q') and not quarter.startswith('FY'):
                        quarter_num = f"Q{q}" if q else None
                        if quarter_num != quarter:
                            continue
                    # If quarter is "FY2025 Q1" format, match exactly
                    elif quarter_label != quarter:
                        continue
                if category != 'all' and category_name != category:
                    continue
                if source != 'all' and display_source != source:
                    continue
                if status != 'all' and 'Approved' != status:
                    continue
                
                # Point type filter
                if point_type == 'regular' and (is_bonus or is_utilization):
                    continue
                if point_type == 'bonus' and not is_bonus:
                    continue
                if point_type == 'utilization' and not is_utilization:
                    continue
                
                # ✅ FIXED: Count regular and bonus separately
                if isinstance(points_value, (int, float)) and not is_utilization:
                    if is_bonus:
                        total_bonus += points_value
                    else:
                        total_regular += points_value
                
                # Get display value
                display_value = points_value
                utilization_percentage = None
                
                if is_utilization and 'utilization_value' in req:
                    utilization_value = req.get('utilization_value', 0)
                    utilization_percentage = round(utilization_value * 100, 2)
                    display_value = f"{utilization_percentage}%"
                elif is_utilization:
                    display_value = "N/A"
                
                # Get validator name - check multiple fields
                validator_name = None
                if is_bonus and req.get('bonus_approved_by_id'):
                    try:
                        bonus_approver = mongo.db.users.find_one({'_id': req['bonus_approved_by_id']})
                        if bonus_approver:
                            validator_name = bonus_approver.get('name')
                    except:
                        pass
                
                if not validator_name and req.get('assigned_validator_id'):
                    try:
                        validator = mongo.db.users.find_one({'_id': req['assigned_validator_id']})
                        if validator:
                            validator_name = validator.get('name')
                    except:
                        pass
                
                if not validator_name and req.get('processed_by'):
                    try:
                        processor = mongo.db.users.find_one({'_id': req['processed_by']})
                        if processor:
                            validator_name = processor.get('name')
                    except:
                        pass
                
                # ✅ NEW: Check additional fields for validator
                if not validator_name and req.get('awarded_by'):
                    try:
                        awarder = mongo.db.users.find_one({'_id': req['awarded_by']})
                        if awarder:
                            validator_name = awarder.get('name')
                    except:
                        pass
                
                if not validator_name and req.get('approved_by'):
                    try:
                        approver = mongo.db.users.find_one({'_id': req['approved_by']})
                        if approver:
                            validator_name = approver.get('name')
                    except:
                        pass
                
                # ✅ NEW: If still no validator, show "Auto-Approved" or "System"
                if not validator_name:
                    # Check if it's a system-generated entry (TA, PMO, LD, etc.)
                    if req.get('ta_id') or req.get('created_by_ta_id'):
                        validator_name = 'TA System'
                    elif req.get('pmo_id') or req.get('created_by_pmo_id'):
                        validator_name = 'PMO System'
                    elif req.get('created_by_ld_id') or req.get('actioned_by_ld_id'):
                        validator_name = 'L&D System'
                    elif req.get('created_by_market_id'):
                        validator_name = 'Marketing System'
                    elif req.get('created_by_presales_id'):
                        validator_name = 'Presales System'
                    elif is_utilization:
                        validator_name = 'HR System'
                    else:
                        validator_name = 'Auto-Approved'
                
                entry = {
                    'id': str(req['_id']),
                    'category_name': category_name,
                    'points': points_value,
                    'display_value': str(display_value),
                    'is_utilization': is_utilization,
                    'utilization_percentage': utilization_percentage,
                    'display_date': effective_date.strftime('%d/%m/%Y') if effective_date else 'N/A',
                    'display_date_iso': effective_date.strftime('%Y-%m-%d') if effective_date else '',
                    'year': year_str or '',
                    'quarter_label': quarter_label or 'N/A',
                    'status': 'Approved',
                    'submission_notes': get_submission_notes(req),
                    'response_notes': get_response_notes(req),
                    'has_attachment': req.get('has_attachment', False),
                    'attachment_filename': req.get('attachment_filename', ''),
                    'source': src,
                    'display_source': display_source,
                    'is_bonus': is_bonus,
                    'validator_name': validator_name,
                    'from_collection': 'points_request'
                }
                
                filtered_history.append(entry)
                
            except Exception as req_error:
                continue
        
        # ✅ REMOVED: No longer fetching from points collection
        # Only use points_request collection for consistency with database export
        # This prevents double-counting and ensures all dashboards show the same values
        
        # Add Pending/Rejected requests if status filter allows
        if status == 'all' or status in ['Pending', 'Rejected']:
            try:
                status_filter = {'$in': ['Pending', 'Rejected']}
                if status != 'all':
                    status_filter = status
                
                pending_requests = list(mongo.db.points_request.find({
                    'user_id': ObjectId(user_id),
                    'status': status_filter,
                    '$or': [
                        {'source': 'employee_request'},
                        {'created_by': ObjectId(user_id)}
                    ]
                }).sort('request_date', -1))
                
                for req in pending_requests:
                    try:
                        cat = get_category_for_employee(req.get('category_id'))
                        if not cat:
                            continue
                        
                        category_name = cat.get('name', 'Unknown Category')
                        is_utilization = is_utilization_category(cat)
                        is_bonus = req.get('is_bonus', False) or cat.get('is_bonus', False)
                        points_value = req.get('points', 0)
                        
                        request_date = req.get('request_date')
                        if not isinstance(request_date, datetime):
                            request_date = datetime.utcnow()
                        
                        event_date = req.get('event_date')
                        effective_date = event_date if event_date and isinstance(event_date, datetime) else request_date
                        
                        q, fy = get_fiscal_quarter_year(effective_date)
                        quarter_label = f"FY{fy} Q{q}" if q and fy else None
                        
                        # ✅ FIXED: Use fiscal year (not calendar year)
                        year_str = str(fy) if fy else None
                        
                        # Apply filters
                        if year != 'all' and year_str != year:
                            continue
                        
                        # ✅ FIXED: Quarter filter now accepts both "Q1" and "FY2025 Q1" formats
                        if quarter != 'all':
                            # If quarter is just "Q1", "Q2", etc., match against the quarter number only
                            if quarter.startswith('Q') and not quarter.startswith('FY'):
                                quarter_num = f"Q{q}" if q else None
                                if quarter_num != quarter:
                                    continue
                            # If quarter is "FY2025 Q1" format, match exactly
                            elif quarter_label != quarter:
                                continue
                        if category != 'all' and category_name != category:
                            continue
                        if source != 'all' and 'Employee Request' != source:
                            continue
                        
                        # Point type filter
                        if point_type == 'regular' and (is_bonus or is_utilization):
                            continue
                        if point_type == 'bonus' and not is_bonus:
                            continue
                        if point_type == 'utilization' and not is_utilization:
                            continue
                        
                        display_value = points_value
                        utilization_percentage = None
                        
                        if is_utilization and 'utilization_value' in req:
                            utilization_value = req.get('utilization_value', 0)
                            utilization_percentage = round(utilization_value * 100, 2)
                            display_value = f"{utilization_percentage}%"
                        
                        # Get validator name
                        validator_name = None
                        if is_bonus and req.get('bonus_approved_by_id'):
                            try:
                                bonus_approver = mongo.db.users.find_one({'_id': req['bonus_approved_by_id']})
                                if bonus_approver:
                                    validator_name = bonus_approver.get('name')
                            except:
                                pass
                        
                        if not validator_name and req.get('assigned_validator_id'):
                            try:
                                validator = mongo.db.users.find_one({'_id': req['assigned_validator_id']})
                                if validator:
                                    validator_name = validator.get('name')
                            except:
                                pass
                        
                        entry = {
                            'id': str(req['_id']),
                            'category_name': category_name,
                            'points': points_value,
                            'display_value': str(display_value),
                            'is_utilization': is_utilization,
                            'utilization_percentage': utilization_percentage,
                            'display_date': effective_date.strftime('%d/%m/%Y') if effective_date else 'N/A',
                            'display_date_iso': effective_date.strftime('%Y-%m-%d') if effective_date else '',
                            'year': year_str or '',
                            'quarter_label': quarter_label or '',
                            'status': req.get('status', 'Pending'),
                            'submission_notes': get_submission_notes(req),
                            'response_notes': get_response_notes(req),
                            'has_attachment': req.get('has_attachment', False),
                            'display_source': 'Employee Request',
                            'is_bonus': is_bonus,
                            'validator_name': validator_name or 'N/A'
                        }
                        
                        filtered_history.append(entry)
                        
                    except Exception as req_error:
                        continue
            
            except Exception as pending_error:
                pass
        
        # Sort by date
        filtered_history.sort(
            key=lambda x: x['display_date_iso'],
            reverse=True
        )
        
        return jsonify({
            'success': True,
            'data': filtered_history,
            'totals': {
                'regular': int(total_regular),
                'bonus': int(total_bonus),
                'combined': int(total_regular + total_bonus)
            },
            'count': len(filtered_history)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@employee_points_total_bp.route('/get-attachment/<request_id>')
def get_attachment(request_id):
    """Download attachment for a request"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    try:
        # ✅ Try to find the request in points_request collection
        req = mongo.db.points_request.find_one({
            '_id': ObjectId(request_id),
            'user_id': ObjectId(user_id)
        })
        
        # ✅ If not found in points_request, try points collection (for older data)
        if not req:
            point = mongo.db.points.find_one({
                '_id': ObjectId(request_id),
                'user_id': ObjectId(user_id)
            })
            
            # If found in points collection, check if it has request_id to get attachment from original request
            if point and point.get('request_id'):
                req = mongo.db.points_request.find_one({
                    '_id': point['request_id']
                })
            elif point:
                # Use the point data directly if no request_id
                req = point
        
        if not req:
            flash('Request not found', 'danger')
            return redirect(url_for('employee_points_total.points_total'))
        
        if not req.get('has_attachment'):
            flash('No attachment found for this request', 'warning')
            return redirect(url_for('employee_points_total.points_total'))
        
        attachment_id = req.get('attachment_id')
        if not attachment_id:
            flash('Attachment ID missing', 'warning')
            return redirect(url_for('employee_points_total.points_total'))
        
        fs = GridFS(mongo.db)
        
        # ✅ Try both ObjectId and string formats
        attachment_found = False
        grid_out = None
        
        # Try as ObjectId first
        try:
            if isinstance(attachment_id, str):
                oid = ObjectId(attachment_id)
            else:
                oid = attachment_id
                
            if fs.exists(oid):
                grid_out = fs.get(oid)
                attachment_found = True
        except:
            pass
        
        # If not found, try searching by filename in GridFS
        if not attachment_found and req.get('attachment_filename'):
            try:
                grid_out = fs.find_one({'filename': req.get('attachment_filename')})
                if grid_out:
                    attachment_found = True
            except:
                pass
        
        # If still not found, return error
        if not attachment_found or not grid_out:
            flash('Attachment file not found in storage. The file may have been deleted or corrupted. Please contact support.', 'warning')
            return redirect(url_for('employee_points_total.points_total'))
        
        # Get the file from GridFS
        grid_out = fs.get(attachment_id)
        file_data = grid_out.read()
        
        file_stream = io.BytesIO(file_data)
        file_stream.seek(0)
        
        # Get original filename and content type
        original_filename = grid_out.metadata.get('original_filename', req.get('attachment_filename', 'attachment'))
        content_type = grid_out.content_type or 'application/octet-stream'
        
        return send_file(
            file_stream,
            mimetype=content_type,
            download_name=original_filename,
            as_attachment=True
        )
        
    except Exception as e:
        flash(f'Error downloading attachment: {str(e)}', 'danger')
        return redirect(url_for('employee_points_total.points_total'))