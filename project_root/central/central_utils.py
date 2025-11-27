from flask import session
from extensions import mongo
from bson.objectid import ObjectId
from datetime import datetime
import calendar
import logging

logger = logging.getLogger(__name__)

def check_central_dashboard_access(user):
    """
    Check if user has Central dashboard access.
    Handles both list and string formats for dashboard_access.
    """
    if not user:
        return False

    dashboard_access = user.get('dashboard_access', [])

    # Convert to list if it's a comma-separated string
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]

    # Ensure lowercase comparison for list
    return 'central' in [x.lower() for x in dashboard_access]

def check_central_access():
    """
    Check if current session user has Central dashboard access.
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
    
    # Check dashboard_access field for Central access
    dashboard_access = user.get('dashboard_access', [])
    
    # Handle both string and list formats
    if isinstance(dashboard_access, str):
        dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
    else:
        dashboard_access = [x.lower() for x in dashboard_access]
    
    has_access = 'central' in dashboard_access
    
    return has_access, user

def debug_print(message, data=None):
    """Debug function disabled for production"""
    pass  # No-op function to disable debug output

def error_print(message, error=None):
    """Log errors via logging. If an exception object is provided, log its stack trace."""
    try:
        if error:
            logger.exception("CENTRAL: %s | Exception: %s", message, str(error))
        else:
            logger.error("CENTRAL: %s", message)
    except Exception:
        # Swallow any logging errors
        pass

def get_eligible_users():
    """Get all users eligible for rewards (employees and managers with manager_id)"""
    # Get all employees
    employees = list(mongo.db.users.find({"role": "Employee"}))
    
    # Get managers who have a manager_id (not null)
    managers_with_manager = list(mongo.db.users.find({
        "role": "Manager",
        "manager_id": {"$ne": None, "$exists": True}
    }))
    
    # Combine both lists
    all_eligible = employees + managers_with_manager
    
    return all_eligible

def get_current_quarter():
    """Get current quarter (April-March fiscal year)"""
    now = datetime.now()
    # Adjust month for April-March fiscal year (April = 1, May = 2, ..., March = 12)
    adjusted_month = (now.month - 4) % 12 + 1
    quarter = (adjusted_month - 1) // 3 + 1
    
    # For fiscal year, use the year when the fiscal year starts (April)
    fiscal_year = now.year
    if now.month < 4:  # Jan, Feb, March belong to previous fiscal year
        fiscal_year -= 1
        
    return f"Q{quarter}-{fiscal_year}", quarter, fiscal_year

def get_quarter_date_range(quarter, fiscal_year):
    """Get date range for quarter (April-March fiscal year)"""
    # Calculate the first month of the quarter in the April-March system
    first_month = ((quarter - 1) * 3 + 4) % 12
    if first_month == 0:
        first_month = 12
    
    # Calculate the year for the first month
    year_adjustment = 0
    if quarter == 4:  # Q4 (Jan-Mar) is in the next calendar year
        year_adjustment = 1
    
    # Calculate the start date (beginning of first month)
    start_year = fiscal_year if quarter < 4 else fiscal_year + 1
    start_date = datetime(start_year, first_month, 1)
    
    # Calculate the end date (end of last month in quarter)
    last_month = (first_month + 2) % 12
    if last_month == 0:
        last_month = 12
    
    end_year = start_year if last_month > first_month or (quarter != 4) else start_year + 1
    last_day = calendar.monthrange(end_year, last_month)[1]
    end_date = datetime(end_year, last_month, last_day, 23, 59, 59)
    
    return start_date, end_date

def get_quarters_in_year(fiscal_year=None):
    """Get all quarters in a fiscal year up to current quarter"""
    now = datetime.now()
    
    if fiscal_year is None:
        fiscal_year = now.year
        if now.month < 4:  # Jan, Feb, March belong to previous fiscal year
            fiscal_year -= 1
    
    # Determine current quarter in the fiscal year
    adjusted_month = (now.month - 4) % 12 + 1
    current_quarter = (adjusted_month - 1) // 3 + 1
    
    quarters = []
    for q in range(1, 5):  # Always include all 4 quarters for fiscal year
        # Only include future quarters if we're checking previous fiscal years
        if fiscal_year < now.year or q <= current_quarter:
            start_date, end_date = get_quarter_date_range(q, fiscal_year)
            quarters.append({
                'quarter': q,
                'name': f"Q{q}-{fiscal_year}",
                'start_date': start_date,
                'end_date': end_date
            })
    
    return quarters

def get_reward_config():
    """Get the current reward configuration"""
    config = mongo.db.reward_config.find_one({})
    
    # If no configuration exists, create default
    if not config:
        default_config = {
            "grade_targets": {
                "A1": 2750, "B1": 3950, "B2": 4850,
                "C1": 7700, "C2": 8700, "D1": 6700, "D2": 6200
            },
            "milestones": [
                {"name": "Milestone 1", "description": "100% of Qtr target", "percentage": 25, "bonus_points": {"Q1": 1000, "Q2": 1000, "Q3": 1000, "Q4": 1000}},
                {"name": "Milestone 2", "description": "50% of Yearly target", "percentage": 50, "bonus_points": {"Q1": 2000, "Q2": 0, "Q3": 0, "Q4": 0}},
                {"name": "Milestone 3", "description": "75% of Yearly target", "percentage": 75, "bonus_points": {"Q1": 3000, "Q2": 2000, "Q3": 0, "Q4": 0}},
                {"name": "Milestone 4", "description": "100% of Yearly target", "percentage": 100, "bonus_points": {"Q1": 4000, "Q2": 3000, "Q3": 2000, "Q4": 0}}
            ],
            "utilization_threshold": 80,
            "yearly_bonus_limit": 10000,
            "last_updated": datetime.utcnow()
        }
        result = mongo.db.reward_config.insert_one(default_config)
        return default_config
    
    return config

def calculate_quarter_utilization(employee_id, quarter_start, quarter_end):
    """
    ✅ FIXED: Calculate average utilization checking BOTH collections
    """
    # ✅ Check hr_categories first (new location)
    utilization_category = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    
    # ✅ Fallback to categories collection (old location)
    if not utilization_category:
        utilization_category = mongo.db.categories.find_one({"code": "utilization_billable"})
    
    # If still not found, return 0
    if not utilization_category:
        return 0
    
    utilization_category_id = utilization_category["_id"]
    
    # Determine all months in this quarter
    quarter_months = []
    current_date = quarter_start
    while current_date <= quarter_end:
        month_key = f"{current_date.year}-{current_date.month}"
        quarter_months.append({
            "key": month_key,
            "name": current_date.strftime("%B"),
            "year": current_date.year,
            "month": current_date.month
        })
        # Move to next month
        if current_date.month == 12:
            next_month = 1
            next_year = current_date.year + 1
        else:
            next_month = current_date.month + 1
            next_year = current_date.year
        current_date = datetime(next_year, next_month, 1)
    
    # Initialize all months with 0% utilization
    monthly_utilization = {}
    for month in quarter_months:
        monthly_utilization[month["key"]] = 0
    
    # Find utilization records for this employee in this quarter
    utilization_records = mongo.db.points_request.find({
        "user_id": ObjectId(employee_id),
        "request_date": {"$gte": quarter_start, "$lte": quarter_end},
        "status": "Approved",
        "category_id": utilization_category_id
    })
    
    # Process each utilization record
    record_count = 0
    for record in utilization_records:
        record_count += 1
        record_date = record.get("request_date")
        if record_date:
            month_key = f"{record_date.year}-{record_date.month}"
            
            # ✅ Try multiple field locations
            utilization_value = None
            
            # Try 1: Direct field
            if 'utilization_value' in record:
                utilization_value = record.get('utilization_value')
            
            # Try 2: submission_data
            elif 'submission_data' in record:
                submission_data = record.get('submission_data', {})
                if isinstance(submission_data, dict):
                    utilization_value = submission_data.get('utilization_value') or submission_data.get('utilization')
            
            # Try 3: points field (fallback)
            if utilization_value is None or utilization_value == 0:
                points = record.get('points', 0)
                if points > 0 and points <= 100:
                    utilization_value = points / 100.0
            
            # Convert to percentage and store
            if utilization_value is not None and utilization_value > 0:
                if utilization_value <= 1:
                    # It's a decimal (0.85 = 85%)
                    percentage = utilization_value * 100
                else:
                    # It's already a percentage (85 = 85%)
                    percentage = utilization_value
                
                if month_key in monthly_utilization:
                    monthly_utilization[month_key] = percentage
    
    # Calculate average across ALL months in the quarter
    if not quarter_months:
        return 0
    
    total_utilization = sum(monthly_utilization.values())
    average_utilization = total_utilization / len(quarter_months)
    
    return round(average_utilization, 2)

def calculate_yearly_bonus_points(employee_id, year):
    """Calculate total bonus points earned by an employee in a given year"""
    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31, 23, 59, 59)
    
    total_bonus_points = 0
    
    # Only get points from approved requests (single source of truth)
    bonus_requests_cursor = mongo.db.points_request.find({
        "user_id": ObjectId(employee_id),
        "status": "Approved",
        "request_date": {"$gte": start_date, "$lte": end_date},
        "is_bonus": True
    })
    
    # Sum up all the bonus points
    for req in bonus_requests_cursor:
        total_bonus_points += req.get("points", 0)
    
    return total_bonus_points

def calculate_yearly_points(employee_id, year):
    """Calculate total non-bonus points earned by an employee in a given year"""
    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31, 23, 59, 59)
    
    total_points = 0
    
    # Get points only from approved requests (excluding bonuses)
    requests_cursor = mongo.db.points_request.find({
        "user_id": ObjectId(employee_id),
        "status": "Approved",
        "request_date": {"$gte": start_date, "$lte": end_date},
        "is_bonus": {"$ne": True}
    })
    
    # Sum regular points, skipping utilization records
    for req in requests_cursor:
        category_id = req.get("category_id")
        
        # ✅ Check both collections for utilization category
        is_utilization = False
        
        # Check hr_categories
        category = mongo.db.hr_categories.find_one({"_id": category_id, "category_code": "utilization_billable"})
        if category:
            is_utilization = True
        
        # Check categories if not found
        if not is_utilization:
            category = mongo.db.categories.find_one({"_id": category_id, "code": "utilization_billable"})
            if category:
                is_utilization = True
        
        # Skip utilization records
        if is_utilization:
            continue
        
        # Add to total
        total_points += req.get("points", 0)
    
    return total_points

def check_bonus_eligibility(employee_points, employee_grade, utilization_avg=None, bonus_already_awarded=False, yearly_bonus_points=None):
    """Check if an employee is eligible for bonus"""
    # If bonus already awarded this quarter, not eligible
    if bonus_already_awarded:
        return False, "Bonus already awarded this quarter"
        
    # Get current configuration
    config = get_reward_config()
    grade_targets = config.get("grade_targets", {})
    utilization_threshold = config.get("utilization_threshold", 80)
    yearly_bonus_limit = config.get("yearly_bonus_limit", 10000)
    
    # If the grade is not found, return not eligible
    if employee_grade not in grade_targets:
        return False, "Unknown employee grade"
    
    # Get minimum required points for this grade
    min_required = grade_targets.get(employee_grade, 0)
    
    # Check if employee has achieved the minimum required points
    if employee_points < min_required:
        return False, f"Insufficient points: {employee_points}/{min_required}"
    
    # Check billability criteria if provided (mandatory per quarter)
    if employee_grade.strip().upper() != 'A1' and utilization_avg is not None and utilization_avg < utilization_threshold:
        return False, f"Insufficient billability: {utilization_avg}% (required: {utilization_threshold}%)"
    
    # Check yearly bonus points limit - only if supplied
    if yearly_bonus_points is not None and yearly_bonus_points >= yearly_bonus_limit:
        return False, f"Yearly bonus points limit reached: {yearly_bonus_points}/{yearly_bonus_limit}"
    
    return True, None

def calculate_bonus_points(employee_points, yearly_target, quarter):
    """Calculate bonus points with cumulative milestones"""
    # Get current configuration
    config = get_reward_config()
    milestones = config.get("milestones", [])

    # Sort milestones by percentage (lowest first to enable summation)
    milestones = sorted(milestones, key=lambda m: m.get("percentage", 0))

    # Calculate percentage of yearly target achieved
    if yearly_target <= 0:
        yearly_percentage = 0
    else:
        yearly_percentage = (employee_points / yearly_target) * 100

    # Initialize bonus and list of achieved milestones
    bonus = 0
    achieved_milestones = []

    # Calculate sum of all achieved milestone bonuses
    for milestone in milestones:
        milestone_percentage = milestone.get("percentage", 0)
        if yearly_percentage >= milestone_percentage:
            # Get bonus points for this quarter
            quarter_key = f"Q{quarter}"
            milestone_bonus = milestone.get("bonus_points", {}).get(quarter_key, 0)

            # Add milestone bonus if it's > 0 for this quarter
            if milestone_bonus > 0:
                bonus += milestone_bonus
                achieved_milestones.append(milestone)

    # Return total bonus and list of all achieved milestones
    return bonus, achieved_milestones

def check_bonus_awarded_for_quarter(employee_id, quarter_name):
    """Check if bonus already awarded in current quarter"""
    # Check only points_request collection for bonus entries in current quarter with "Approved" status
    bonus_exists = mongo.db.points_request.find_one({
        "user_id": ObjectId(employee_id),
        "status": "Approved",
        "is_bonus": True,
        # Find a request from this quarter
        "response_notes": {"$regex": f"Milestone bonus.*{quarter_name}"}
    })
    
    return bonus_exists is not None

def get_monthly_billable_utilization(user_id, start_dt, end_dt):
    """
    Fetches the total billable utilization for a given user for each month
    within a specified date range.
    """
    try:
        if not isinstance(user_id, ObjectId):
            user_id = ObjectId(user_id)
        
        pipeline = [
            {
                '$match': {
                    'user_id': user_id,
                    'status': 'Approved',
                    'request_date': {'$gte': start_dt, '$lte': end_dt},
                    'utilization_value': {'$exists': True, '$ne': None, '$gt': 0}
                }
            },
            {
                '$group': {
                    '_id': {
                        'year': {'$year': '$request_date'},
                        'month': {'$month': '$request_date'}
                    },
                    'total_utilization': {'$sum': '$utilization_value'}
                }
            },
            {
                '$sort': {'_id.year': 1, '_id.month': 1}
            }
        ]
        
        results = list(mongo.db.points_request.aggregate(pipeline))
        monthly_data = {
            f"{item['_id']['year']}-{item['_id']['month']:02d}": round(item['total_utilization'], 2)
            for item in results
        }
        return monthly_data
    except Exception as e:
        error_print(f"Error fetching monthly utilization for user {user_id}", e)
        return {}