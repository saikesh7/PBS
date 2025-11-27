from flask import session
from extensions import mongo
from bson.objectid import ObjectId


def check_hr_dashboard_access(user):
    """
    Check if user has HR dashboard access.
    Handles both list and string formats for dashboard_access.
    """
    if not user:
        return False

    dashboard_access = user.get('dashboard_access', [])

    # Convert to list if it's a comma-separated string
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]

    # Ensure lowercase comparison for list
    return 'hr' in [x.lower() for x in dashboard_access]


def check_hr_access():
    """
    Check if current session user has HR dashboard access.
    Returns: (has_access: bool, user: dict or None)
    """
    user_id = session.get('user_id')
    
    if not user_id:
        return False, None
    
    try:
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    except:
        return False, None
    
    if not user:
        return False, None
    
    # Check dashboard_access field for HR access
    dashboard_access = user.get('dashboard_access', [])
    
    # Handle both string and list formats
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    else:
        dashboard_access = [x.lower() for x in dashboard_access]
    
    has_access = 'hr' in dashboard_access
    
    return has_access, user