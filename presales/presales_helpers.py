"""
Presales Helper Functions
Common utility functions used across presales module
"""
from flask import session
from extensions import mongo
from bson.objectid import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Import constants from centralized location
from .constants import ALL_GRADES

def check_presales_access():
    """
    Check if user has Presales dashboard access
    Matches PM dashboard logic - uses dashboard_access field
    """
    user_id = session.get('user_id')
    
    if not user_id:
        return False, None
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    # Check dashboard_access field for Presales access (matches PM logic)
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    # Check for any presales-related dashboard access
    # Accepts: 'Presales - Updater', 'Presales - Validator', 'Presales', 'presales'
    has_access = any(
        'presales' in str(access).lower() 
        for access in dashboard_access
    )
    
    return has_access, user

def get_financial_quarter_and_label(date_obj):
    """
    Returns (quarter_number, quarter_label, quarter_start_month, fiscal_year_label)
    for the given date_obj based on the financial year:
    Q1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar (next year)
    Fiscal year label: e.g., 2024-25 for Q1 2024
    """
    month = date_obj.month
    year = date_obj.year
    
    if 4 <= month <= 6:
        quarter = 1
        quarter_label = "Q1 (Apr-Jun)"
        quarter_start_month = 4
        fiscal_year_start = year
    elif 7 <= month <= 9:
        quarter = 2
        quarter_label = "Q2 (Jul-Sep)"
        quarter_start_month = 7
        fiscal_year_start = year
    elif 10 <= month <= 12:
        quarter = 3
        quarter_label = "Q3 (Oct-Dec)"
        quarter_start_month = 10
        fiscal_year_start = year
    else:  # Jan-Mar
        quarter = 4
        quarter_label = "Q4 (Jan-Mar)"
        quarter_start_month = 1
        fiscal_year_start = year - 1  # Q4 belongs to previous fiscal year
    
    fiscal_year_end_short = str(fiscal_year_start + 1)[-2:]
    fiscal_year_label = f"{fiscal_year_start}-{fiscal_year_end_short}"
    
    return quarter, quarter_label, quarter_start_month, fiscal_year_start, fiscal_year_label

def get_current_quarter_date_range():
    """Get current fiscal quarter date range"""
    now = datetime.utcnow()
    quarter, _, quarter_start_month, fiscal_year_start, _ = get_financial_quarter_and_label(now)
    
    # Determine the actual calendar year of quarter start
    actual_calendar_year = fiscal_year_start
    if quarter == 4:  # Q4 (Jan-Mar) starts in the calendar year after fiscal_year_start
        actual_calendar_year = fiscal_year_start + 1
    
    quarter_start = datetime(actual_calendar_year, quarter_start_month, 1)
    
    # Calculate quarter end
    if quarter == 1:
        quarter_end = datetime(actual_calendar_year, 6, 30, 23, 59, 59, 999999)
    elif quarter == 2:
        quarter_end = datetime(actual_calendar_year, 9, 30, 23, 59, 59, 999999)
    elif quarter == 3:
        quarter_end = datetime(actual_calendar_year, 12, 31, 23, 59, 59, 999999)
    else:  # Q4
        quarter_end = datetime(actual_calendar_year, 3, 31, 23, 59, 59, 999999)
    
    return quarter_start, quarter_end, quarter, fiscal_year_start

def get_presales_categories():
    """
    Get all presales categories from hr_categories collection
    Matches PM dashboard logic - uses hr_categories with department filter
    Handles variations: 'presales', 'pre-sales', 'Pre-Sales', etc.
    Also checks old 'categories' collection for backward compatibility
    """
    # Try multiple variations of the department name in hr_categories
    categories = list(mongo.db.hr_categories.find({
        "$or": [
            {"category_department": "presales"},
            {"category_department": "pre-sales"},
            {"category_department": "Pre-Sales"},
            {"category_department": {"$regex": "^pre.?sales$", "$options": "i"}}
        ],
        "category_status": "active"
    }))
    
    # If no categories found, also try searching by category name containing "presales" or "pre-sales"
    if not categories:
        categories = list(mongo.db.hr_categories.find({
            "name": {"$regex": "pre.?sales", "$options": "i"},
            "category_status": "active"
        }))
    
    # Also check old 'categories' collection for backward compatibility
    old_categories = list(mongo.db.categories.find({
        "$or": [
            {"department": "presales"},
            {"department": "pre-sales"},
            {"department": "Pre-Sales"},
            {"department": {"$regex": "^pre.?sales$", "$options": "i"}},
            {"name": {"$regex": "pre.?sales", "$options": "i"}}
        ]
    }))
    
    # Merge categories, avoiding duplicates by _id
    existing_ids = {cat["_id"] for cat in categories}
    for old_cat in old_categories:
        if old_cat["_id"] not in existing_ids:
            categories.append(old_cat)
            existing_ids.add(old_cat["_id"])
    
    # Debug logging removed to reduce console noise
    # Use logger.debug() if needed for troubleshooting
    
    return categories

def get_presales_category_ids():
    """Get list of ACTIVE presales category ObjectIds - for new requests"""
    categories = get_presales_categories()
    return [cat["_id"] for cat in categories]


def get_all_presales_categories():
    """
    Get ALL presales categories (both active and inactive) from hr_categories collection
    Used for displaying existing pending/processed requests - shows all regardless of status
    This ensures pending requests are shown even if category is inactive or moved from another department
    """
    # Try multiple variations of the department name in hr_categories (no status filter)
    categories = list(mongo.db.hr_categories.find({
        "$or": [
            {"category_department": "presales"},
            {"category_department": "pre-sales"},
            {"category_department": "Pre-Sales"},
            {"category_department": {"$regex": "^pre.?sales$", "$options": "i"}}
        ]
    }))
    
    # Also check old 'categories' collection for backward compatibility
    old_categories = list(mongo.db.categories.find({
        "$or": [
            {"department": "presales"},
            {"department": "pre-sales"},
            {"department": "Pre-Sales"},
            {"department": {"$regex": "^pre.?sales$", "$options": "i"}}
        ]
    }))
    
    # Merge categories, avoiding duplicates by _id
    existing_ids = {cat["_id"] for cat in categories}
    for old_cat in old_categories:
        if old_cat["_id"] not in existing_ids:
            categories.append(old_cat)
            existing_ids.add(old_cat["_id"])
    
    return categories


def get_all_presales_category_ids():
    """Get list of ALL presales category ObjectIds (active + inactive) - for displaying existing requests"""
    categories = get_all_presales_categories()
    return [cat["_id"] for cat in categories]

def get_grade_max_points_for_category(category_code, grade):
    """
    Get maximum points allowed for a specific grade and category
    Fetches from hr_categories collection dynamically (matches PM logic)
    
    Args:
        category_code: Category code (e.g., 'presales_rfp', 'presales_partial')
        grade: Employee grade (e.g., 'C1', 'D2')
    
    Returns:
        int: Maximum points allowed for this grade, or 0 if not found
    """
    category = mongo.db.hr_categories.find_one({
        "category_code": category_code,
        "category_department": "presales",
        "category_status": "active"
    })
    
    if not category:
        logger.warning(f"Category {category_code} not found in hr_categories")
        return 0
    
    grade_points = category.get('grade_points', {})
    return grade_points.get(grade, 0)

def get_all_grade_limits():
    """
    Get all grade-wise limits for all presales categories
    Returns a dictionary with category codes as keys and grade_points as values
    Matches PM dashboard logic
    
    Returns:
        dict: {category_code: {grade: max_points}}
    """
    categories = get_presales_categories()
    grade_limits = {}
    
    for cat in categories:
        category_code = cat.get('category_code', cat.get('code'))
        grade_points = cat.get('grade_points', {})
        if category_code:
            grade_limits[category_code] = grade_points
    
    return grade_limits

# Removed validator/updater distinction - presales uses peer-to-peer validation
# All presales members can both create and approve requests

def format_request_for_json(request, employee, category):
    """Helper to format a request for JSON serialization"""
    return {
        "id": str(request["_id"]),
        "employee_name": employee.get("name", "Unknown"),
        "employee_id": employee.get("employee_id", "N/A"),
        "category_name": category.get("name", "Unknown"),
        "points": request.get("points"),
        "request_date": request.get("request_date").isoformat() if request.get("request_date") else None,
        "notes": request.get("notes", "")
    }
