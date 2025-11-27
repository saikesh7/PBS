"""
PM/Arch Helper Functions
Common utility functions used across PM/Arch module
"""
from flask import session
from extensions import mongo
from bson.objectid import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Import constants from centralized location
from .constants import GRADE_CONFIG


def check_pmarch_access():
    """
    Check if user has PM/Arch dashboard access
    Matches PM dashboard logic - uses dashboard_access field
    Checks for: pm_arch, pmarch, pm/arch (case insensitive)
    """
    user_id = session.get('user_id')
    
    if not user_id:
        return False, None
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    # Check dashboard_access field for PM/Arch access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    

    
    # Check for PM/Arch dashboard access (using pm_arch format like pm, presales)
    has_access = 'pm_arch' in dashboard_access
    
    logger.debug(f"PM/Arch Access Check: has_access = {has_access}")
    
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


def get_pmarch_categories():
    """
    Get all PM/Arch categories from hr_categories collection
    Uses case-insensitive regex to match various formats:
    - pm_arch, PM_ARCH, Pm_Arch
    - pm arch, PM ARCH, Pm Arch
    - pm-arch, PM-ARCH, Pm-Arch
    - pmarch, PMARCH, Pmarch
    """
    return list(mongo.db.hr_categories.find({
        "category_department": {
            "$regex": "^(pm[_\\s-]?arch|pmarch)$",
            "$options": "i"  # Case-insensitive
        },
        "category_status": "active"
    }))


def get_pmarch_category_ids():
    """Get list of PM/Arch category ObjectIds"""
    categories = get_pmarch_categories()
    return [cat["_id"] for cat in categories]


# Removed validator distinction - PM/Arch uses peer-to-peer validation
# All PM/Arch members can both create and approve requests
