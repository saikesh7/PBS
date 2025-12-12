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


def check_ld_updater_access():
    """Check if user has L&D Updater access"""
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    mongo = get_mongo()
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    # Check for 'ld_up' or 'ld_updater' (primary values)
    has_access = (
        check_dashboard_access(user, 'ld_up') or 
        check_dashboard_access(user, 'ld_updater')
    )
    return has_access, user


def check_ld_validator_access():
    """Check if user has L&D Validator access"""
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    mongo = get_mongo()
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    # Check for 'ld_va' or 'ld_validator' (primary values)
    has_access = (
        check_dashboard_access(user, 'ld_va') or 
        check_dashboard_access(user, 'ld_validator')
    )
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
    elif 'ld_va' in dashboard_access or 'ld_validator' in dashboard_access:
        return url_for('ld.validator_dashboard')
    elif 'ld_up' in dashboard_access or 'ld_updater' in dashboard_access:
        return url_for('ld.updater_dashboard')
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


def get_quarter_label_from_date(date_obj):
    """
    Get quarter label from date (Financial Year: Apr-Mar)
    
    Args:
        date_obj: datetime object or None
        
    Returns:
        str: Quarter label like "Q1 2024", "Q4 2024", etc.
        Returns "Unknown" if date_obj is None or invalid
        
    Examples:
        - April 2024 → "Q1 2024"
        - February 2025 → "Q4 2024" (belongs to FY 2024-25)
        - None → "Unknown"
    """
    # ✅ Safety check: Handle None or invalid date objects
    if not date_obj:
        return "Unknown"
    
    try:
        month = date_obj.month
        year = date_obj.year
        
        if month in [4, 5, 6]:
            return f"Q1 {year}"
        elif month in [7, 8, 9]:
            return f"Q2 {year}"
        elif month in [10, 11, 12]:
            return f"Q3 {year}"
        else:  # 1, 2, 3 (Jan, Feb, Mar belong to previous FY)
            return f"Q4 {year - 1}"
    except (AttributeError, TypeError):
        # Handle cases where date_obj is not a datetime object
        return "Unknown"


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
            return None, "Event date in the future."
    
    return event_date, None


def get_ld_categories():
    """Get all L&D categories from both hr_categories and old "categories" collection for backward compatibility.
    Fetches from both collections to support existing requests created with old category IDs."""
    mongo = get_mongo()
    
    # Fetch from NEW hr_categories - Direct Award and Employee Raised types (for validators)
    ld_categories_new = list(mongo.db.hr_categories.find({
        "category_department": {"$regex": "^(ld.?up|ld.?va)$", "$options": "i"},
        "category_status": {"$regex": "^active$", "$options": "i"},
        "category_type": {"$regex": "^(Direct.?award|Employee.?raised)$", "$options": "i"}
    }).sort("name", 1))
    
    # Fetch from OLD "categories" collection - for backward compatibility with existing requests
    ld_categories_old = list(mongo.db.categories.find({
        "$or": [
            {"name": {"$regex": "L&D|LD|learning|certification", "$options": "i"}},
            {"category_type": "Direct Award"}
        ]
    }).sort("name", 1))
    
    # Combine both lists - keep ALL categories (don't deduplicate by name)
    # This ensures we can find requests created with old category IDs
    all_categories = {}
    for cat in ld_categories_new + ld_categories_old:
        cat_id = str(cat.get('_id'))
        if cat_id not in all_categories:
            all_categories[cat_id] = cat
    
    # Normalize structure (ensure all have proper fields)
    normalized_categories = []
    for cat in all_categories.values():
        normalized_categories.append(normalize_category_structure(cat))
    
    return normalized_categories


def get_ld_updater_categories():
    """Get L&D categories for updaters from both collections to support existing requests with old category IDs.
    Backend uses all categories for CSV validation; display uses only hr_categories to avoid duplicates."""
    mongo = get_mongo()
    
    # Fetch from NEW hr_categories - Updaters should only see Direct Award categories, not Employee raised
    ld_categories_new = list(mongo.db.hr_categories.find({
        "category_department": {"$regex": "^(ld.?up|ld.?va)$", "$options": "i"},
        "category_status": {"$regex": "^active$", "$options": "i"},
        "category_type": {"$regex": "^Direct.?award$", "$options": "i"}
    }).sort("name", 1))
    
    # Fetch from OLD categories collection - for backward compatibility with existing requests
    ld_categories_old = list(mongo.db.categories.find({
        "$or": [
            {"name": {"$regex": "L&D|LD|learning|certification", "$options": "i"}},
            {"category_type": "Direct Award"}
        ]
    }).sort("name", 1))
    
    # Combine both collections - keep ALL categories by ID to support requests with old category IDs
    all_categories = {}
    for cat in ld_categories_new + ld_categories_old:
        cat_id = str(cat.get('_id'))
        if cat_id not in all_categories:
            all_categories[cat_id] = cat
    
    # Normalize structure (ensure all have proper fields)
    normalized_categories = []
    for cat in all_categories.values():
        normalized_categories.append(normalize_category_structure(cat))
    
    return normalized_categories


def get_ld_updater_categories_for_display():
    """Get L&D categories for bulk upload display from hr_categories only to show unique categories without duplicates."""
    mongo = get_mongo()
    
    # Fetch ONLY from hr_categories - Direct Award categories for display (no old categories to avoid duplicates)
    ld_categories = list(mongo.db.hr_categories.find({
        "category_department": {"$regex": "^(ld.?up|ld.?va)$", "$options": "i"},
        "category_status": {"$regex": "^active$", "$options": "i"},
        "category_type": {"$regex": "^Direct.?award$", "$options": "i"}
    }).sort("name", 1))
    
    # Normalize structure (ensure all have proper fields)
    normalized_categories = []
    for cat in ld_categories:
        normalized_categories.append(normalize_category_structure(cat))
    
    return normalized_categories


def get_ld_validators():
    """Get all users with L&D Validator access"""
    mongo = get_mongo()
    
    validators = list(mongo.db.users.find({
        "dashboard_access": {"$regex": "ld_va", "$options": "i"}
    }).sort("name", 1))
    
    return validators


# Employee filter for L&D dropdowns
# Show ALL users from ALL departments (Employee, Manager, HR, etc.)
SELECTABLE_EMPLOYEE_FILTER_FOR_LD = {
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
        # Users with LD updater access (can appear in dropdown)
        {
            'dashboard_access': 'ld_up'
        },
        # Users with LD validator access (can appear in dropdown)
        {
            'dashboard_access': 'ld_va'
        }
    ]
}


def emit_pending_request_update():
    """Emit event to refresh validator dashboard - broadcasts to all L&D validators"""
    try:
        from app import socketio
        socketio.emit(
            'refresh_validator_dashboard',
            {
                'source': 'ld_updater',
                'timestamp': datetime.utcnow().isoformat()
            },
            broadcast=True,
            namespace='/'
        )
    except Exception:
        pass


def emit_updater_history_update():
    """Emit event to refresh updater history table"""
    try:
        from app import socketio
        socketio.emit('updater_history_updated', {'source': 'ld_validator'})
    except Exception as e:
        pass


def emit_updater_own_request_created(updater_id):
    """Emit event to updater when they create their own request"""
    try:
        from app import socketio
        socketio.emit('updater_request_created', {
            'source': 'ld_updater',
            'updater_id': str(updater_id)
        })
    except Exception:
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


def normalize_category_structure(category):
    """Normalize old and new category structures to have consistent fields"""
    if not category:
        return None
    
    # If it's an old category (has metadata but no points_per_unit at root)
    if 'metadata' in category and 'points_per_unit' not in category:
        # Copy metadata.grade_points to points_per_unit for consistency
        if 'grade_points' in category['metadata']:
            category['points_per_unit'] = category['metadata']['grade_points'].copy()
        elif 'points_per_unit' in category['metadata']:
            # Some old categories might have points_per_unit in metadata
            category['points_per_unit'] = category['metadata']['points_per_unit']
        else:
            # Fallback to empty dict
            category['points_per_unit'] = {}
    
    # Ensure points_per_unit exists (for safety)
    if 'points_per_unit' not in category:
        category['points_per_unit'] = {}
    
    # Ensure 'base' key exists for template compatibility
    # Old categories don't have 'base', so we calculate it from grade points
    if isinstance(category['points_per_unit'], dict) and 'base' not in category['points_per_unit']:
        # Calculate base as the most common non-zero value, or first non-zero value
        grade_values = [v for v in category['points_per_unit'].values() if isinstance(v, (int, float)) and v > 0]
        if grade_values:
            # Use the most common value as base
            from collections import Counter
            category['points_per_unit']['base'] = Counter(grade_values).most_common(1)[0][0]
        else:
            category['points_per_unit']['base'] = 0
    
    return category


def get_category_by_id(category_id):
    """Get category from hr_categories (or old categories for backward compatibility with historical data)"""
    mongo = get_mongo()
    
    # Try new hr_categories collection first
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    
    # If not found, try old categories collection (for backward compatibility with old historical data)
    if not category:
        category = mongo.db.categories.find_one({"_id": category_id})
    
    # Normalize the structure
    return normalize_category_structure(category)
