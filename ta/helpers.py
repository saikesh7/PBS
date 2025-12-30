from flask import session, redirect, url_for, flash
from datetime import datetime
from bson import ObjectId


def get_mongo():
    """Get MongoDB instance from app context"""
    from app import mongo
    return mongo


def check_dashboard_access(user, required_dashboard):
    """Check if user has access to a specific dashboard"""
    if not user:
        return False
    
    dashboard_access = user.get('dashboard_access', [])
    
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    
    dashboard_access = [x.lower() for x in dashboard_access]
    required_dashboard = required_dashboard.lower()
    
    return required_dashboard in dashboard_access


def check_ta_updater_access():
    """Check if user has TA Updater access"""
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    mongo = get_mongo()
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    has_access = check_dashboard_access(user, 'ta_up')
    return has_access, user


def check_ta_validator_access():
    """Check if user has TA Validator access"""
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    mongo = get_mongo()
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    has_access = check_dashboard_access(user, 'ta_va')
    return has_access, user


def get_user_redirect(user):
    """Get appropriate redirect URL for user based on their dashboard_access"""
    if not user:
        return url_for('auth.login')
    
    dashboard_access = user.get('dashboard_access', [])
    
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    else:
        dashboard_access = [x.lower() for x in dashboard_access]
    
    if 'employee' in dashboard_access:
        return url_for('employee_dashboard.dashboard')
    elif 'ta_va' in dashboard_access:
        return url_for('ta.validator_dashboard')
    elif 'ta_up' in dashboard_access:
        return url_for('ta.updater_dashboard')
    elif 'pm' in dashboard_access:
        return url_for('pm.dashboard')
    else:
        return url_for('auth.login')


def get_financial_quarter_dates(for_date=None):
    """Determines the financial quarter (Apr-Mar) for a given date"""
    if for_date is None:
        for_date = datetime.utcnow()
    
    year = for_date.year
    month = for_date.month

    if 4 <= month <= 6:
        quarter = 1
        financial_year = year
        start_date = datetime(year, 4, 1)
        end_date = datetime(year, 6, 30, 23, 59, 59)
    elif 7 <= month <= 9:
        quarter = 2
        financial_year = year
        start_date = datetime(year, 7, 1)
        end_date = datetime(year, 9, 30, 23, 59, 59)
    elif 10 <= month <= 12:
        quarter = 3
        financial_year = year
        start_date = datetime(year, 10, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
    else:  # Jan, Feb, Mar
        quarter = 4
        financial_year = year - 1
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 3, 31, 23, 59, 59)
    
    return {
        "start_date": start_date,
        "end_date": end_date,
        "quarter": quarter,
        "year": financial_year
    }


def get_financial_quarter_and_month():
    """Get current financial quarter and month display strings"""
    now = datetime.utcnow()
    month = now.month
    year = now.year

    financial_year = year
    if 4 <= month <= 6:
        quarter_label = "Q1"
    elif 7 <= month <= 9:
        quarter_label = "Q2"
    elif 10 <= month <= 12:
        quarter_label = "Q3"
    else:  # Jan, Feb, Mar
        quarter_label = "Q4"
        financial_year = year - 1

    quarter_display = f"{quarter_label} {financial_year}"
    current_month_display = now.strftime("%B")

    return quarter_display, current_month_display


def parse_date_flexibly(date_str):
    """Parses a date string from common formats"""
    if not date_str:
        return None
    
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def validate_event_date(event_date_str, allow_future=False):
    """Validates event date string and returns datetime object or error"""
    if not event_date_str:
        return None, "Event date is required."
    
    event_date = parse_date_flexibly(event_date_str)
    if not event_date:
        return None, "Invalid event date format. Please use a valid date format (e.g., DD-MM-YYYY)."
    
    if not allow_future:
        today = datetime.utcnow().date()
        if event_date.date() > today:
            return None, "Event date cannot be in the future."
    
    return event_date, None


def get_ta_categories():
    """Get all TA categories from hr_categories (excludes employee_raised)"""
    mongo = get_mongo()
    
    # Exclude employee_raised categories (they should only show in employee dashboard)
    # This matches PMO logic to ensure employee-raised requests appear in validator dashboard
    # Use regex to match any category_department starting with 'ta' (case-insensitive)
    ta_categories = list(mongo.db.hr_categories.find({
        "category_department": {"$regex": "^ta", "$options": "i"},
        "category_status": "active",
        "category_type": {"$not": {"$regex": "employee.*raised", "$options": "i"}}  # Exclude employee raised (case-insensitive)
    }).sort("name", 1))
    
    return ta_categories


def get_ta_categories_for_validator():
    """Get ALL active TA categories for validator display (includes employee_raised)"""
    mongo = get_mongo()
    
    # Include ALL TA categories including employee_raised for validators
    ta_categories = list(mongo.db.hr_categories.find({
        "category_department": {"$regex": "^ta", "$options": "i"},
        "category_status": "active"
    }).sort("name", 1))
    
    return ta_categories


def get_ta_validators():
    """Get all users with TA Validator access"""
    mongo = get_mongo()
    
    validators = list(mongo.db.users.find({
        "dashboard_access": {"$regex": "ta_va", "$options": "i"}
    }).sort("name", 1))
    
    return validators


# Employee filter for TA dropdowns
# Show ALL users from ALL departments (Employee, Manager, HR, etc.)
SELECTABLE_EMPLOYEE_FILTER_FOR_TA = {
    'employee_id': {'$exists': True, '$ne': None, '$ne': ''},
    '$or': [
        # Regular employees (role: Employee)
        {
            'role': 'Employee',
            'is_active': True
        },
        # Old data structure (no is_active field)
        {
            'role': 'Employee',
            'is_active': {'$exists': False}
        },
        # Users with TA updater access (can appear in dropdown)
        {
            'dashboard_access': 'ta_up'
        },
        # Users with TA validator access (can appear in dropdown)
        {
            'dashboard_access': 'ta_va'
        }
    ]
}


def emit_pending_request_update():
    """Emit event to refresh validator dashboard"""
    try:
        from app import socketio
        socketio.emit('refresh_validator_dashboard', {'source': 'ta_updater'})
    except Exception as e:
        pass


def emit_updater_history_update():
    """Emit event to refresh updater history table"""
    try:
        from app import socketio
        socketio.emit('updater_history_updated', {'source': 'ta_validator'})
    except Exception as e:
        pass


def get_month_year_options():
    """Get last 12 months options for backdating"""
    months = []
    now = datetime.utcnow()
    
    for i in range(12):
        # Calculate month
        month = now.month - i
        year = now.year
        
        # Handle year rollback
        while month <= 0:
            month += 12
            year -= 1
        
        date_obj = datetime(year, month, 1)
        months.append({
            'value': date_obj.strftime('%Y-%m'),
            'label': date_obj.strftime('%B %Y'),
            'month': month,
            'year': year
        })
    
    return months


def get_all_ta_categories():
    """
    Get ALL TA categories (both active and inactive) from hr_categories collection
    Used for displaying existing pending/processed requests - shows all regardless of status
    This ensures pending requests are shown even if category is inactive or moved from another department
    """
    mongo = get_mongo()
    
    # Use regex to match any category_department starting with 'ta' (case-insensitive, no status filter)
    ta_categories = list(mongo.db.hr_categories.find({
        "category_department": {"$regex": "^ta", "$options": "i"}
    }).sort("name", 1))
    
    return ta_categories


def get_all_ta_category_ids():
    """Get list of ALL TA category ObjectIds (active + inactive) - for displaying existing requests"""
    categories = get_all_ta_categories()
    return [cat["_id"] for cat in categories]


def get_ta_category_ids():
    """Get list of ACTIVE TA category ObjectIds - for new requests"""
    categories = get_ta_categories()
    return [cat["_id"] for cat in categories]