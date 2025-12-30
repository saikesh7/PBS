from flask import session, url_for
from extensions import mongo as flask_mongo
from bson import ObjectId
from datetime import datetime, timedelta
from dashboard_config import get_redirect_for_unauthorized_user

def get_mongo():
    """Get MongoDB instance"""
    return flask_mongo

def check_hr_updater_access():
    """Check if user has HR Updater access"""
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    mongo = get_mongo()
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    
    if not user:
        return False, None
    
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    
    dashboard_access = [x.lower() for x in dashboard_access]
    
    # Check for hr_up
    if 'hr_up' in dashboard_access:
        return True, user
    
    return False, user

def check_hr_validator_access():
    """Check if user has HR Validator access"""
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    mongo = get_mongo()
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    
    if not user:
        return False, None
    
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    
    dashboard_access = [x.lower() for x in dashboard_access]
    
    # Check for hr_va
    if 'hr_va' in dashboard_access:
        return True, user
    
    return False, user

def get_user_redirect(user):
    """Get redirect URL for user"""
    return get_redirect_for_unauthorized_user(user)

def get_financial_quarter_and_month():
    """Get current financial quarter and month"""
    now = datetime.utcnow()
    month = now.month
    year = now.year
    
    if month >= 4:
        quarter = f"Q{((month - 4) // 3) + 1}-{year}"
    else:
        quarter = f"Q{((month + 8) // 3) + 1}-{year - 1}"
    
    month_name = now.strftime('%B %Y')
    return quarter, month_name

def get_hr_categories():
    """Get active HR categories from HR configuration (excludes employee_raised)"""
    mongo = get_mongo()
    # Use regex for case-insensitive matching
    # Exclude employee_raised categories (they should only show in employee dashboard)
    categories = list(mongo.db.hr_categories.find({
        'category_department': {'$regex': '^hr', '$options': 'i'},
        'category_status': 'active',
        'category_type': {'$not': {'$regex': 'employee.*raised', '$options': 'i'}}  # Exclude employee raised
    }).sort('name', 1))
    return categories

def get_hr_categories_for_validator():
    """Get active HR categories for validator (includes employee_raised)"""
    mongo = get_mongo()
    # Include ALL HR categories including employee_raised for validators
    categories = list(mongo.db.hr_categories.find({
        'category_department': {'$regex': '^hr', '$options': 'i'},
        'category_status': 'active'
    }).sort('name', 1))
    return categories

def get_hr_validators():
    """Get users with HR Validator access"""
    mongo = get_mongo()
    validators = list(mongo.db.users.find({
        'dashboard_access': {'$in': ['HR - Validator', 'hr_va']}
    }))
    return validators

def parse_date_flexibly(date_str):
    """Parse date from various formats"""
    formats = ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d']
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except:
            continue
    return None

def validate_event_date(date_str, allow_future=False):
    """Validate event date"""
    event_date = parse_date_flexibly(date_str)
    if not event_date:
        return None, "Invalid date format"
    
    if not allow_future and event_date.date() > datetime.utcnow().date():
        return None, "Event date cannot be in the future"
    
    return event_date, None

SELECTABLE_EMPLOYEE_FILTER = {
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
        # Users with BOTH HR updater AND validator access (can appear in dropdown)
        {
            'dashboard_access': {'$all': ['hr_up', 'hr_va']},
            'employee_id': {'$exists': True, '$ne': None, '$ne': ''}
        }
    ]
}


def get_all_hr_categories():
    """
    Get ALL HR categories (both active and inactive) from hr_categories collection
    Used for displaying existing pending/processed requests - shows all regardless of status
    This ensures pending requests are shown even if category is inactive
    
    KEY: category_department must START with 'hr' (case-insensitive)
    This handles categories like 'hr', 'HR', 'hr_up', 'Hr Up', etc.
    But excludes 'pmo', 'ta', 'ld', etc.
    """
    mongo = get_mongo()
    # STRICT: category_department must START with 'hr' (^hr)
    # No status filter - includes both active and inactive
    categories = list(mongo.db.hr_categories.find({
        'category_department': {'$regex': '^hr', '$options': 'i'}
    }).sort('name', 1))
    return categories


def get_all_hr_category_ids():
    """Get list of ALL HR category ObjectIds (active + inactive) - for displaying existing requests"""
    categories = get_all_hr_categories()
    return [cat["_id"] for cat in categories]


def get_hr_category_ids():
    """Get list of ACTIVE HR category ObjectIds - for new requests"""
    categories = get_hr_categories()
    return [cat["_id"] for cat in categories]
