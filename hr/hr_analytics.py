from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify, make_response
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import os
from .hr_utils import check_hr_access

current_dir = os.path.dirname(os.path.abspath(__file__))

hr_analytics_bp = Blueprint('hr_analytics', __name__, url_prefix='/hr',
                            template_folder=os.path.join(current_dir, 'templates'),
                            static_folder=os.path.join(current_dir, 'static'),
                            static_url_path='/static')


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_location_category(location):
    """
    Map specific location to US/Non-US category
    Returns 'US' or 'Non-US' based on location value
    """
    if not location:
        return None
    
    location_str = str(location).strip()
    
    # US locations
    if location_str == "US":
        return "US"
    
    # Non-US locations (including specific countries and cities)
    non_us_locations = [
        "Non-US", "India", "UK", "Canada", "Australia", "Singapore", 
        "Philippines", "Malaysia", "Hyderabad", "Bangalore", "Mumbai", 
        "Delhi", "Pune", "Chennai", "Kolkata", "London", "Toronto", 
        "Sydney", "Melbourne"
    ]
    
    if location_str in non_us_locations:
        return "Non-US"
    
    # Default: treat unknown locations as Non-US
    return "Non-US"


def matches_location_filter(user_location, location_filter):
    """
    Check if user location matches the filter
    Handles both exact matches and category matches (US/Non-US)
    """
    if not location_filter:
        return True
    
    if not user_location:
        return False
    
    # Get the category of the user's location
    user_category = get_location_category(user_location)
    
    # Check if filter matches the category
    if location_filter in ["US", "Non-US"]:
        return user_category == location_filter
    
    # Check for exact match
    return str(user_location).strip() == str(location_filter).strip()


def get_location_values_for_filter(location_filter):
    """
    Get all possible location values that match the filter
    Used for building MongoDB queries
    """
    if not location_filter:
        return None
    
    if location_filter == "US":
        return ["US"]
    
    if location_filter == "Non-US":
        # Return all known non-US locations
        return [
            "Non-US", "India", "UK", "Canada", "Australia", "Singapore", 
            "Philippines", "Malaysia", "Hyderabad", "Bangalore", "Mumbai", 
            "Delhi", "Pune", "Chennai", "Kolkata", "London", "Toronto", 
            "Sydney", "Melbourne"
        ]
    
    # For specific location, return as-is
    return [location_filter]


def get_financial_quarter_and_label(date_obj):
    """
    Calculate financial quarter and labels based on April-March fiscal year
    Returns: (quarter_number, quarter_label, quarter_start_month, fiscal_year_start, fiscal_year_label)
    """
    month = date_obj.month
    year = date_obj.year
    
    if month >= 4:  # April to December
        fiscal_year_start = year
        fiscal_year_label = f"{year}-{str(year + 1)[2:]}"
    else:  # January to March
        fiscal_year_start = year - 1
        fiscal_year_label = f"{year - 1}-{str(year)[2:]}"
    
    if 4 <= month <= 6:
        quarter = 1
        quarter_label = "Q1"
        quarter_start_month = 4
    elif 7 <= month <= 9:
        quarter = 2
        quarter_label = "Q2"
        quarter_start_month = 7
    elif 10 <= month <= 12:
        quarter = 3
        quarter_label = "Q3"
        quarter_start_month = 10
    else:  # 1-3
        quarter = 4
        quarter_label = "Q4"
        quarter_start_month = 1
    
    return quarter, quarter_label, quarter_start_month, fiscal_year_start, fiscal_year_label


# ==========================================
# CATEGORY MANAGEMENT
# ==========================================

def get_all_categories():
    """Get merged list of categories from both collections - deduplicated by name"""
    all_categories = {}
    
    old_categories = list(mongo.db.categories.find())
    for cat in old_categories:
        category_name = cat.get('name', '')
        if category_name:
            all_categories[category_name] = {
                '_id': cat['_id'],
                'name': cat['name'],
                'code': cat.get('code', cat.get('category_code', '')),
                'source': 'categories'
            }
    
    new_categories = list(mongo.db.hr_categories.find())
    for cat in new_categories:
        category_name = cat.get('name', '')
        if category_name:
            if category_name in all_categories:
                old_id = all_categories[category_name]['_id']
                all_categories[category_name] = {
                    '_id': cat['_id'],
                    'old_id': old_id,
                    'name': cat['name'],
                    'code': cat.get('category_code', cat.get('code', '')),
                    'source': 'both'
                }
            else:
                all_categories[category_name] = {
                    '_id': cat['_id'],
                    'name': cat['name'],
                    'code': cat.get('category_code', cat.get('code', '')),
                    'source': 'hr_categories'
                }
    
    return list(all_categories.values())


def get_category_ids_for_name(category_name):
    """Get all possible category IDs for a given category name (from both collections)"""
    category_ids = []
    
    old_cat = mongo.db.categories.find_one({"name": category_name})
    if old_cat:
        category_ids.append(old_cat['_id'])
    
    new_cat = mongo.db.hr_categories.find_one({"name": category_name})
    if new_cat:
        category_ids.append(new_cat['_id'])
    
    return category_ids


def get_category_for_analytics(category_id):
    """Get category info from either collection - handles both ObjectId and string types"""
    if not category_id:
        return None
    
    # Convert string to ObjectId if needed
    try:
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
    except Exception:
        return None
    
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return category
    
    category = mongo.db.categories.find_one({"_id": category_id})
    return category


# ==========================================
# DATE HANDLING FUNCTIONS
# ==========================================

def extract_event_date(entry):
    """Extract event_date from a points entry based on its source"""
    if not entry:
        return None
    
    if 'event_date' in entry and entry['event_date']:
        return entry['event_date']
    
    source = entry.get('source')
    
    if source == 'netsuite_sales':
        return entry.get('close_date')
    elif source == 'netsuite_so':
        return entry.get('creation_date')
    elif source == 'manager_request':
        return entry.get('request_date')
    elif source == 'hr_bonus':
        return entry.get('award_date')
    
    return entry.get('request_date') or entry.get('award_date')


def get_effective_date(entry):
    """Determine the effective date for a points entry"""
    if not entry:
        return None
    
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


# ==========================================
# ANALYTICS DATA FUNCTIONS - USING POINTS COLLECTION ONLY
# ==========================================

def get_quarterly_performance_data_fixed(filter_start_date=None, filter_end_date=None, location_filter=None):
    """
    Get quarterly performance data from points_request collection
    If filter dates are provided, show quarters within that range
    Otherwise, show last 4 quarters from today
    """
    current_date = datetime.utcnow()
    
    # ✅ FIXED: Determine which quarters to show based on filter
    if filter_start_date and filter_end_date:
        # Use filter dates to determine quarters
        base_date = filter_start_date
    else:
        # Use current date for last 4 quarters
        base_date = current_date
    
    fiscal_year = base_date.year
    if base_date.month < 4:
        fiscal_year -= 1
    
    month = base_date.month
    if month >= 4 and month <= 6:
        fiscal_quarter = 1
    elif month >= 7 and month <= 9:
        fiscal_quarter = 2
    elif month >= 10 and month <= 12:
        fiscal_quarter = 3
    else:
        fiscal_quarter = 4
    
    quarters_data = []
    
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    
    # ✅ Get eligible users if location filter is applied
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
        
        # If no eligible users found, return empty quarters
        if not eligible_user_ids:
            for i in range(4):
                q = fiscal_quarter - i
                yr = fiscal_year
                
                if q <= 0:
                    q += 4
                    yr -= 1
                
                if q == 1:
                    period_name = f"Q1 {yr}-{yr+1}"
                elif q == 2:
                    period_name = f"Q2 {yr}-{yr+1}"
                elif q == 3:
                    period_name = f"Q3 {yr}-{yr+1}"
                else:
                    period_name = f"Q4 {yr}-{yr+1}"
                
                quarters_data.append({
                    "period": period_name,
                    "categories": [],
                    "total_points": 0,
                    "total_count": 0
                })
            return quarters_data
    
    # ✅ FIXED: Determine how many quarters to show
    # If filter range spans multiple quarters, show all of them (up to 4)
    # Otherwise, show last 4 quarters
    if filter_start_date and filter_end_date:
        # Calculate quarters within filter range
        quarters_to_show = []
        
        # Start from the quarter containing filter_start_date
        temp_date = filter_start_date
        while temp_date <= filter_end_date:
            temp_fiscal_year = temp_date.year if temp_date.month >= 4 else temp_date.year - 1
            temp_month = temp_date.month
            
            if 4 <= temp_month <= 6:
                temp_q = 1
                q_start = datetime(temp_fiscal_year, 4, 1)
                q_end = datetime(temp_fiscal_year, 6, 30, 23, 59, 59, 999999)
            elif 7 <= temp_month <= 9:
                temp_q = 2
                q_start = datetime(temp_fiscal_year, 7, 1)
                q_end = datetime(temp_fiscal_year, 9, 30, 23, 59, 59, 999999)
            elif 10 <= temp_month <= 12:
                temp_q = 3
                q_start = datetime(temp_fiscal_year, 10, 1)
                q_end = datetime(temp_fiscal_year, 12, 31, 23, 59, 59, 999999)
            else:  # 1-3
                temp_q = 4
                q_start = datetime(temp_fiscal_year + 1, 1, 1)
                q_end = datetime(temp_fiscal_year + 1, 3, 31, 23, 59, 59, 999999)
            
            quarters_to_show.append((temp_q, temp_fiscal_year, q_start, q_end))
            
            # Move to next quarter
            from datetime import timedelta
            temp_date = q_end + timedelta(days=1)
            
            # Limit to 4 quarters max
            if len(quarters_to_show) >= 4:
                break
        
        num_quarters = len(quarters_to_show)
    else:
        # Show last 4 quarters from current date
        quarters_to_show = []
        for i in range(4):
            q = fiscal_quarter - i
            yr = fiscal_year
            
            if q <= 0:
                q += 4
                yr -= 1
            
            if q == 1:
                q_start = datetime(yr, 4, 1)
                q_end = datetime(yr, 6, 30, 23, 59, 59, 999999)
            elif q == 2:
                q_start = datetime(yr, 7, 1)
                q_end = datetime(yr, 9, 30, 23, 59, 59, 999999)
            elif q == 3:
                q_start = datetime(yr, 10, 1)
                q_end = datetime(yr, 12, 31, 23, 59, 59, 999999)
            else:  # q == 4
                q_start = datetime(yr + 1, 1, 1)
                q_end = datetime(yr + 1, 3, 31, 23, 59, 59, 999999)
            
            quarters_to_show.append((q, yr, q_start, q_end))
        
        num_quarters = 4
    
    # Process each quarter
    for q, yr, start_date, end_date in quarters_to_show:
        if q == 1:
            period_name = f"Q1 {yr}-{yr+1}"
        elif q == 2:
            period_name = f"Q2 {yr}-{yr+1}"
        elif q == 3:
            period_name = f"Q3 {yr}-{yr+1}"
        else:
            period_name = f"Q4 {yr}-{yr+1}"
        
        category_data = {}
        total_points = 0
        total_count = 0
        processed_request_ids = set()
        
        # ✅ STEP 1: Query approved points_request
        pr_query = {
            "status": "Approved",
            "$or": [
                {"event_date": {"$gte": start_date, "$lte": end_date}},
                {"request_date": {"$gte": start_date, "$lte": end_date}},
                {"award_date": {"$gte": start_date, "$lte": end_date}}
            ]
        }
        
        if utilization_category_ids:
            pr_query["category_id"] = {"$nin": utilization_category_ids}
        
        # ✅ Add user_id filter if location filter is applied
        if eligible_user_ids is not None:
            pr_query["user_id"] = {"$in": eligible_user_ids}
        
        approved_requests = list(mongo.db.points_request.find(pr_query))
        
        for req in approved_requests:
            event_date = extract_event_date(req)
            entry_with_dates = {
                'event_date': event_date,
                'request_date': req.get('request_date'),
                'award_date': req.get('award_date')
            }
            effective_date = get_effective_date(entry_with_dates)
            
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
            
            # ✅ If filter dates provided, also check if effective_date is within filter range
            if filter_start_date and filter_end_date:
                if not (filter_start_date <= effective_date <= filter_end_date):
                    continue
            
            # Mark as processed
            processed_request_ids.add(req['_id'])
            
            category_id = req.get("category_id")
            if not category_id:
                continue
            
            points = req.get("points", 0)
            category = get_category_for_analytics(category_id)
            category_name = category["name"] if category else "No Category"
            
            if str(category_id) not in category_data:
                category_data[str(category_id)] = {
                    "name": category_name,
                    "total_points": 0,
                    "count": 0
                }
            
            category_data[str(category_id)]["total_points"] += points
            category_data[str(category_id)]["count"] += 1
            total_points += points
            total_count += 1
        
        quarters_data.append({
            "period": period_name,
            "categories": list(category_data.values()),
            "total_points": total_points,
            "total_count": total_count
        })
    
    return quarters_data


def get_grade_participation_fixed(start_date, end_date, location_filter=None):
    """Get grade participation data from points_request collection"""
    categories = get_all_categories()
    grades = ["A1", "B1", "B2", "C1", "C2", "D1", "D2"]
    
    participation_data = {}
    
    for category in categories:
        category_name = category["name"]
        category_ids = get_category_ids_for_name(category_name)
        
        if not category_ids:
            continue
        
        grade_counts = {grade: 0 for grade in grades}
        user_ids = set()
        
        query = {
            "category_id": {"$in": category_ids},
            "status": "Approved"
        }
        
        if start_date and end_date:
            query["$or"] = [
                {"event_date": {"$gte": start_date, "$lte": end_date}},
                {"award_date": {"$gte": start_date, "$lte": end_date}},
                {"request_date": {"$gte": start_date, "$lte": end_date}}
            ]
        
        # ✅ Query points_request collection
        points_data = list(mongo.db.points_request.find(query))
        
        for entry in points_data:
            if start_date and end_date:
                event_date = extract_event_date(entry)
                entry_with_dates = {
                    'event_date': event_date,
                    'request_date': entry.get('request_date'),
                    'award_date': entry.get('award_date')
                }
                effective_date = get_effective_date(entry_with_dates)
                
                if not effective_date or not (start_date <= effective_date <= end_date):
                    continue
            
            if "user_id" in entry and entry["user_id"] is not None:
                user_ids.add(str(entry["user_id"]))
        
        for user_id in user_ids:
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            if user and "grade" in user:
                # Check location filter if provided
                if location_filter:
                    # ✅ FIXED: Prioritize us_non_us field over location field
                    user_location = user.get("us_non_us") or user.get("location")
                    if not matches_location_filter(user_location, location_filter):
                        continue
                
                if user.get("role") == "Employee" or (user.get("role") == "Manager" and user.get("manager_id")):
                    grade = user["grade"]
                    if grade in grade_counts:
                        grade_counts[grade] += 1
        
        participation_data[category_name] = grade_counts
    
    return participation_data


def get_activity_participation_fixed(start_date, end_date, location_filter=None):
    """Get activity participation data from POINTS collection only"""
    categories = get_all_categories()
    
    # Build user query with location filter if provided
    # ✅ FIXED: Include ALL employees and ALL managers (including top-level managers)
    user_query = {
        "role": {"$in": ["Employee", "Manager"]}
    }
    
    if location_filter:
        # Check both location and us_non_us fields for backward compatibility
        user_query = {
            "$and": [
                {"role": {"$in": ["Employee", "Manager"]}},
                {"$or": [
                    {"location": location_filter},
                    {"us_non_us": location_filter}
                ]}
            ]
        }
    
    total_eligible_users = mongo.db.users.count_documents(user_query)
    
    participation_data = []
    
    for category in categories:
        category_name = category["name"]
        category_ids = get_category_ids_for_name(category_name)
        
        if not category_ids:
            continue
        
        unique_user_ids = set()
        
        query = {
            "category_id": {"$in": category_ids},
            "status": "Approved"
        }
        
        if start_date and end_date:
            query["$or"] = [
                {"event_date": {"$gte": start_date, "$lte": end_date}},
                {"award_date": {"$gte": start_date, "$lte": end_date}},
                {"request_date": {"$gte": start_date, "$lte": end_date}}
            ]
        
        # ✅ Query points_request collection
        points_data = list(mongo.db.points_request.find(query))
        
        for entry in points_data:
            if start_date and end_date:
                event_date = extract_event_date(entry)
                entry_with_dates = {
                    'event_date': event_date,
                    'request_date': entry.get('request_date'),
                    'award_date': entry.get('award_date')
                }
                effective_date = get_effective_date(entry_with_dates)
                
                if not effective_date or not (start_date <= effective_date <= end_date):
                    continue
            
            if "user_id" in entry and entry["user_id"] is not None:
                unique_user_ids.add(str(entry["user_id"]))
        
        eligible_participants = 0
        for user_id in unique_user_ids:
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            if user:
                # Check role eligibility
                if user.get("role") == "Employee" or (user.get("role") == "Manager" and user.get("manager_id")):
                    # Check location filter if provided
                    if location_filter:
                        # ✅ FIXED: Prioritize us_non_us field over location field
                        user_location = user.get("us_non_us") or user.get("location")
                        if matches_location_filter(user_location, location_filter):
                            eligible_participants += 1
                    else:
                        eligible_participants += 1
        
        if total_eligible_users > 0:
            participation_rate = (eligible_participants / total_eligible_users) * 100
        else:
            participation_rate = 0
        
        participation_data.append({
            "category": category_name,
            "participants": eligible_participants,
            "total": total_eligible_users,
            "rate": round(participation_rate, 2)
        })
    
    return participation_data


def get_top_performers_fixed(start_date, end_date, location_filter=None):
    """Get top performers from BOTH collections (points_request + points)"""
    # ✅ FIXED: Include ALL employees and ALL managers (including top-level managers)
    user_query = {"role": {"$in": ["Employee", "Manager"]}}
    
    # Apply location filter if provided
    if location_filter:
        location_values = get_location_values_for_filter(location_filter)
        if location_values:
            user_query["$or"] = [
                {"location": {"$in": location_values}},
                {"us_non_us": {"$in": location_values}}
            ]
    
    eligible_users = list(mongo.db.users.find(user_query, {
        "_id": 1, 
        "name": 1, 
        "grade": 1, 
        "location": 1,
        "us_non_us": 1, 
        "employee_id": 1,
        "role": 1
    }))
    
    # ✅ Create a set of eligible user IDs for faster lookup
    eligible_user_ids = {user["_id"] for user in eligible_users}
    
    user_points = {}
    processed_request_ids = set()
    
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    
    # ✅ STEP 1: Query approved points_request - ONLY for eligible users
    pr_query = {
        "status": "Approved",
        "user_id": {"$in": list(eligible_user_ids)}  # ✅ FIXED: Only get points for filtered users
    }
    
    if start_date and end_date:
        pr_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    if utilization_category_ids:
        pr_query["category_id"] = {"$nin": utilization_category_ids}
    
    approved_requests = list(mongo.db.points_request.find(pr_query))
    
    for req in approved_requests:
        if start_date and end_date:
            event_date = extract_event_date(req)
            entry_with_dates = {
                'event_date': event_date,
                'request_date': req.get('request_date'),
                'award_date': req.get('award_date')
            }
            effective_date = get_effective_date(entry_with_dates)
            
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Mark as processed
        processed_request_ids.add(req['_id'])
        
        user_id = req.get("user_id")
        if user_id and user_id in eligible_user_ids:  # ✅ FIXED: Double-check user is eligible
            user_id_str = str(user_id)
            points = req.get("points", 0)
            user_points[user_id_str] = user_points.get(user_id_str, 0) + points
    
    # ✅ REMOVED: No longer fetching from points collection (historical data)
    # Only use points_request collection for consistency with central leaderboard and export
    # This ensures all dashboards show the same point totals
    
    performers = []
    for user in eligible_users:
        user_id_str = str(user["_id"])
        if user_id_str in user_points and user_points[user_id_str] > 0:
            user["total_points"] = user_points[user_id_str]
            
            # ✅ FIXED: Prioritize us_non_us field over location field for US/Non-US categorization
            # us_non_us is the authoritative field for US/Non-US status
            us_non_us_value = user.get("us_non_us")
            location_value = user.get("location")
            
            # Determine the display location and category
            if us_non_us_value == "US":
                # If us_non_us is explicitly "US", use it regardless of location field
                user["us_non_us"] = "US"
                user["location_category"] = "US"
            elif us_non_us_value in ["Non-US", "India", "UK", "Canada", "Australia", "Singapore", "Philippines", "Malaysia", "Hyderabad", "Bangalore", "Mumbai", "Delhi", "Pune", "Chennai", "Kolkata"]:
                # If us_non_us has a specific Non-US value, use it
                user["us_non_us"] = us_non_us_value
                user["location_category"] = "Non-US"
            elif location_value:
                # Fallback to location field if us_non_us is not set
                if location_value == "US":
                    user["us_non_us"] = "US"
                    user["location_category"] = "US"
                elif location_value in ["Non-US", "India", "UK", "Canada", "Australia", "Singapore", "Philippines", "Malaysia", "Hyderabad", "Bangalore", "Mumbai", "Delhi", "Pune", "Chennai", "Kolkata"]:
                    user["us_non_us"] = location_value
                    user["location_category"] = "Non-US"
                else:
                    user["us_non_us"] = location_value
                    user["location_category"] = "Non-US"
            else:
                # No location data available
                user["us_non_us"] = "N/A"
                user["location_category"] = "N/A"
            
            performers.append(user)
    
    performers.sort(key=lambda x: x["total_points"], reverse=True)
    
    return performers


def get_grade_participation_percentage_fixed(start_date, end_date, location_filter=None):
    """Get grade participation percentage from POINTS collection only"""
    grades = ["A1", "B1", "B2", "C1", "C2", "D1", "D2"]
    
    grade_counts = {}
    for grade in grades:
        user_query = {
            "$and": [
                {"grade": grade},
                {
                    "role": {"$in": ["Employee", "Manager"]}
                }
            ]
        }
        
        # Apply location filter if provided
        if location_filter:
            location_values = get_location_values_for_filter(location_filter)
            if location_values:
                user_query["$and"].append({
                    "$or": [
                        {"location": {"$in": location_values}},
                        {"us_non_us": {"$in": location_values}}
                    ]
                })
        
        count = mongo.db.users.count_documents(user_query)
        grade_counts[grade] = count
    
    categories = get_all_categories()
    participation_data = {}
    
    for grade in grades:
        if grade_counts[grade] == 0:
            continue
        
        category_participation = {}
        
        for category in categories:
            category_name = category["name"]
            category_ids = get_category_ids_for_name(category_name)
            
            if not category_ids:
                continue
            
            user_query_for_ids = {
                "$and": [
                    {"grade": grade},
                    {
                        "role": {"$in": ["Employee", "Manager"]}
                    }
                ]
            }
            
            # Apply location filter if provided
            if location_filter:
                location_values = get_location_values_for_filter(location_filter)
                if location_values:
                    user_query_for_ids["$and"].append({
                        "$or": [
                            {"location": {"$in": location_values}},
                            {"us_non_us": {"$in": location_values}}
                        ]
                    })
            
            user_ids = [str(u["_id"]) for u in mongo.db.users.find(user_query_for_ids, {"_id": 1})]
            
            object_ids = [ObjectId(id) for id in user_ids]
            
            participants_for_category_grade = set()
            
            query = {
                "category_id": {"$in": category_ids},
                "user_id": {"$in": object_ids},
                "status": "Approved"
            }
            
            if start_date and end_date:
                query["$or"] = [
                    {"event_date": {"$gte": start_date, "$lte": end_date}},
                    {"award_date": {"$gte": start_date, "$lte": end_date}},
                    {"request_date": {"$gte": start_date, "$lte": end_date}}
                ]
            
            # ✅ Query points_request collection
            points_data = list(mongo.db.points_request.find(query))
            
            for entry in points_data:
                if start_date and end_date:
                    event_date = extract_event_date(entry)
                    entry_with_dates = {
                        'event_date': event_date,
                        'request_date': entry.get('request_date'),
                        'award_date': entry.get('award_date')
                    }
                    effective_date = get_effective_date(entry_with_dates)
                    
                    if not effective_date or not (start_date <= effective_date <= end_date):
                        continue
                
                if "user_id" in entry and entry["user_id"] is not None:
                    participants_for_category_grade.add(str(entry["user_id"]))
            
            participant_count = len(participants_for_category_grade)
            percentage = (participant_count / grade_counts[grade]) * 100
            
            category_participation[category_name] = {
                "count": participant_count,
                "total": grade_counts[grade],
                "percentage": round(percentage, 2)
            }
        
        participation_data[grade] = category_participation
    
    return participation_data


def calculate_summary_for_period(start_date, end_date, location_filter=None):
    """
    Calculate summary for selected period from points_request collection
    This should match the sum of quarterly data to ensure consistency
    """
    # ✅ FIXED: Use the same logic as quarterly chart to ensure numbers match
    quarterly_data = get_quarterly_performance_data_fixed(start_date, end_date, location_filter)
    
    total_points = 0
    total_count = 0
    
    # Sum up all quarters
    for quarter in quarterly_data:
        total_points += quarter.get("total_points", 0)
        total_count += quarter.get("total_count", 0)
    
    return {"total_points": total_points, "total_count": total_count}


def get_utilization_participation_data(start_date, end_date, location_filter=None):
    """Get utilization participation data from POINTS collection only"""
    # Try to find utilization category by code first
    utilization_category = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if not utilization_category:
        utilization_category = mongo.db.categories.find_one({"code": "utilization_billable"})
    
    # If not found by code, try by name
    if not utilization_category:
        utilization_category = mongo.db.hr_categories.find_one({"name": "Utilization/Billable"})
    if not utilization_category:
        utilization_category = mongo.db.categories.find_one({"name": "Utilization/Billable"})
    
    if not utilization_category:
        return {
            "category": "Utilization/Billable",
            "participants": 0,
            "total_eligible": 0,
            "rate": 0
        }

    category_name = utilization_category.get("name", "Utilization/Billable")
    category_ids = get_category_ids_for_name(category_name)
    
    # Also add the current category ID if not already in list
    if utilization_category.get("_id") and utilization_category["_id"] not in category_ids:
        category_ids.append(utilization_category["_id"])
    
    if not category_ids:
        return {
            "category": category_name,
            "participants": 0,
            "total_eligible": 0,
            "rate": 0
        }

    # ✅ FIXED: Include ALL employees and ALL managers (including top-level managers)
    # Apply location filter if provided
    user_query = {"role": {"$in": ["Employee", "Manager"]}}
    if location_filter:
        location_values = get_location_values_for_filter(location_filter)
        if location_values:
            user_query["$or"] = [
                {"location": {"$in": location_values}},
                {"us_non_us": {"$in": location_values}}
            ]
    
    total_eligible_users = mongo.db.users.count_documents(user_query)

    unique_user_ids = set()
    
    # Utilization data is stored in points_request collection (not moved to points on approval)
    # So we need to query points_request with status "Approved"
    query = {
        "category_id": {"$in": category_ids},
        "status": "Approved"
    }
    
    if start_date and end_date:
        query["$and"] = [
            {
                "$or": [
                    {"event_date": {"$gte": start_date, "$lte": end_date}},
                    {"request_date": {"$gte": start_date, "$lte": end_date}},
                    {"response_date": {"$gte": start_date, "$lte": end_date}}
                ]
            }
        ]
    
    # Query points_request collection for approved utilization records
    all_data = list(mongo.db.points_request.find(query))

    for entry in all_data:
        # If date range is specified, filter by effective date
        if start_date and end_date:
            event_date = extract_event_date(entry)
            entry_with_dates = {
                'event_date': event_date,
                'request_date': entry.get('request_date'),
                'award_date': entry.get('award_date')
            }
            effective_date = get_effective_date(entry_with_dates)
            
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Add user to unique set
        if "user_id" in entry and entry["user_id"] is not None:
            unique_user_ids.add(str(entry["user_id"]))

    # Count eligible participants (only those who are Employees or Managers with manager_id)
    eligible_participants = 0
    
    for user_id in unique_user_ids:
        try:
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            if user:
                # Check location filter if provided
                if location_filter:
                    # ✅ FIXED: Prioritize us_non_us field over location field
                    user_location = user.get("us_non_us") or user.get("location")
                    if not matches_location_filter(user_location, location_filter):
                        continue
                
                if user.get("role") == "Employee" or \
                   (user.get("role") == "Manager" and user.get("manager_id")):
                    eligible_participants += 1
        except Exception as e:
            # Skip invalid ObjectIds
            continue

    if total_eligible_users > 0:
        participation_rate = (eligible_participants / total_eligible_users) * 100
    else:
        participation_rate = 0

    utilization_data = {
        "category": category_name,
        "participants": eligible_participants,
        "total_eligible": total_eligible_users,
        "rate": round(participation_rate, 2)
    }
    return utilization_data


# ==========================================
# ROUTES
# ==========================================

@hr_analytics_bp.route('/dashboard', methods=['GET'])
def hr_dashboard():
    """Main HR dashboard route with stats cards like PM/Arch"""
    has_access, user = check_hr_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the HR Dashboard', 'danger')
        return redirect(url_for('auth.login'))

    # Get total employees count
    total_employees = mongo.db.users.count_documents({
        "role": {"$in": ["Employee", "Manager"]}
    })

    # Get active participants (users with at least one approved point request)
    active_participant_ids = mongo.db.points_request.distinct("user_id", {"status": "Approved"})
    active_participants = len([uid for uid in active_participant_ids if uid is not None])

    # Get total points awarded (excluding utilization) from approved requests
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])

    query = {"status": "Approved"}
    if utilization_category_ids:
        query["category_id"] = {"$nin": utilization_category_ids}

    total_points_pipeline = [
        {"$match": query},
        {"$group": {"_id": None, "total": {"$sum": "$points"}}}
    ]
    total_points_result = list(mongo.db.points_request.aggregate(total_points_pipeline))
    total_points_awarded = total_points_result[0]["total"] if total_points_result else 0

    # Calculate average participation rate
    activity_participation = get_activity_participation_fixed(None, None, None)
    avg_participation_rate = 0
    if activity_participation:
        total_rate_sum = 0
        valid_activity_count = 0
        for activity in activity_participation:
            rate = activity.get("rate")
            if rate is not None and rate > 0:
                total_rate_sum += float(rate)
                valid_activity_count += 1
        if valid_activity_count > 0:
            avg_participation_rate = round(total_rate_sum / valid_activity_count, 1)

    # Get most active grade
    grade_participation_percent = get_grade_participation_percentage_fixed(None, None)
    most_active_grade = "N/A"
    if grade_participation_percent:
        grade_total_activity_counts = {}
        for grade, categories_data in grade_participation_percent.items():
            current_grade_total_activity = 0
            if isinstance(categories_data, dict):
                for category_details in categories_data.values():
                    if isinstance(category_details, dict):
                        current_grade_total_activity += category_details.get("count", 0)
            grade_total_activity_counts[grade] = current_grade_total_activity

        if grade_total_activity_counts:
            sorted_grades_by_activity = sorted(
                grade_total_activity_counts.items(),
                key=lambda item: (-item[1], item[0])
            )
            if sorted_grades_by_activity and sorted_grades_by_activity[0][1] > 0:
                most_active_grade = sorted_grades_by_activity[0][0]

    # Get recent activities (last 20 approved point requests)
    recent_activities = []
    recent_points = list(mongo.db.points_request.find(query).sort([("award_date", -1), ("request_date", -1)]).limit(20))
    
    for entry in recent_points:
        user_doc = mongo.db.users.find_one({"_id": entry.get("user_id")})
        category = get_category_for_analytics(entry.get("category_id"))
        
        if user_doc and category:
            event_date = extract_event_date(entry)
            recent_activities.append({
                "date": event_date or entry.get("award_date") or entry.get("request_date"),
                "employee_name": user_doc.get("name", "Unknown"),
                "category_name": category.get("name", "No Category"),
                "points": entry.get("points", 0),
                "status": "Approved"
            })

    # Get current quarter and month for header display
    now = datetime.utcnow()
    _, quarter_label, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
    display_quarter = f"{quarter_label} {fiscal_year_label}"
    display_month = now.strftime("%b %Y").upper()

    return render_template(
        'hr_dashboard.html',
        user=user,
        total_employees=total_employees,
        active_participants=active_participants,
        total_points_awarded=total_points_awarded,
        avg_participation_rate=avg_participation_rate,
        most_active_grade=most_active_grade,
        recent_activities=recent_activities,
        display_quarter=display_quarter,
        display_month=display_month
    )


@hr_analytics_bp.route('/pbs_analytics', methods=['GET', 'POST'])
def pbs_analytics():
    """Main analytics dashboard route"""
    has_access, user = check_hr_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the HR Analytics dashboard', 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        location_filter = request.form.get('location_filter')

        query_params = {}
        if start_date_str:
            query_params['start_date'] = start_date_str
        if end_date_str:
            query_params['end_date'] = end_date_str
        if location_filter:
            query_params['location'] = location_filter
        
        return redirect(url_for('hr_analytics.pbs_analytics', **query_params))

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    location_filter = request.args.get('location')

    start_date_obj = None
    end_date_obj = None

    if start_date_str:
        try:
            start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d')
            start_date_obj = datetime.combine(start_date_obj.date(), datetime.min.time())
        except ValueError:
            flash("Invalid start date format. Using empty start date.", "warning")
            start_date_str = ""
    else:
        start_date_str = ""

    if end_date_str:
        try:
            end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_date_obj = datetime.combine(end_date_obj.date(), datetime.max.time())
        except ValueError:
            flash("Invalid end date format. Using empty end date.", "warning")
            end_date_str = ""
    else:
        end_date_str = ""

    if start_date_obj and end_date_obj and start_date_obj > end_date_obj:
        flash("Start date cannot be after end date. Please select valid dates.", "warning")
        start_date_obj = None
        end_date_obj = None
        start_date_str = ""
        end_date_str = ""

    quarterly_data = get_quarterly_performance_data_fixed(start_date_obj, end_date_obj, location_filter)
    grade_participation = get_grade_participation_fixed(start_date_obj, end_date_obj, location_filter)
    top_performers = get_top_performers_fixed(start_date_obj, end_date_obj, location_filter)
    activity_participation = get_activity_participation_fixed(start_date_obj, end_date_obj, location_filter)
    grade_participation_percent = get_grade_participation_percentage_fixed(start_date_obj, end_date_obj, location_filter)
    
    most_active_grade_name = "N/A"
    if grade_participation_percent:
        grade_total_activity_counts = {}
        for grade, categories_data in grade_participation_percent.items():
            current_grade_total_activity = 0
            if isinstance(categories_data, dict):
                for category_details in categories_data.values():
                    if isinstance(category_details, dict):
                        current_grade_total_activity += category_details.get("count", 0)
            grade_total_activity_counts[grade] = current_grade_total_activity

        if grade_total_activity_counts:
            sorted_grades_by_activity = sorted(
                grade_total_activity_counts.items(),
                key=lambda item: (-item[1], item[0])
            )
            if sorted_grades_by_activity and sorted_grades_by_activity[0][1] > 0:
                most_active_grade_name = sorted_grades_by_activity[0][0]

    avg_participation_rate_value = 0
    if activity_participation:
        total_rate_sum = 0
        valid_activity_count = 0
        for activity in activity_participation:
            rate = activity.get("rate")
            if rate is not None and rate > 0:  # Only count activities with participation
                total_rate_sum += float(rate)
                valid_activity_count += 1
        if valid_activity_count > 0:
            avg_participation_rate_value = round(total_rate_sum / valid_activity_count, 1)

    utilization_data = get_utilization_participation_data(start_date_obj, end_date_obj, location_filter)
    categories = get_all_categories()
    
    # Get current quarter and month for header display
    now = datetime.utcnow()
    _, quarter_label, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
    display_quarter = f"{quarter_label} {fiscal_year_label}"
    display_month = now.strftime("%b %Y").upper()
    
    rendered_template = render_template(
        'pbs_analytics.html',
        categories=categories,
        quarterly_data=quarterly_data,
        grade_participation=grade_participation,
        top_performers=top_performers,
        activity_participation=activity_participation,
        grade_participation_percent=grade_participation_percent,
        utilization_data=utilization_data,
        most_active_grade_name=most_active_grade_name,
        avg_participation_rate_value=avg_participation_rate_value,
        start_date=start_date_str,
        end_date=end_date_str,
        location_filter=location_filter,
        display_quarter=display_quarter,
        display_month=display_month,
        summary_for_selected_period=calculate_summary_for_period(start_date_obj, end_date_obj, location_filter),
        user=user
    )
    
    # Add cache-control headers to prevent browser caching
    response = make_response(rendered_template)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response


@hr_analytics_bp.route('/api/analytics-data', methods=['GET'])
def api_analytics_data():
    """API endpoint for analytics data"""
    has_access, user = check_hr_access()
    
    if not has_access:
        return jsonify({"error": "Unauthorized"}), 401

    start_date_obj = None
    end_date_obj = None

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    location_filter = request.args.get('location')
    
    if start_date_str:
        try:
            start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d')
            start_date_obj = datetime.combine(start_date_obj.date(), datetime.min.time())
        except ValueError:
            pass
    
    if end_date_str:
        try:
            end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_date_obj = datetime.combine(end_date_obj.date(), datetime.max.time())
        except ValueError:
            pass

    quarterly_data = get_quarterly_performance_data_fixed(start_date_obj, end_date_obj, location_filter)
    grade_participation = get_grade_participation_fixed(start_date_obj, end_date_obj, location_filter)
    top_performers = get_top_performers_fixed(start_date_obj, end_date_obj, location_filter)
    activity_participation = get_activity_participation_fixed(start_date_obj, end_date_obj, location_filter)
    grade_participation_percent = get_grade_participation_percentage_fixed(start_date_obj, end_date_obj, location_filter)
    utilization_data = get_utilization_participation_data(start_date_obj, end_date_obj, location_filter)
    summary_for_selected_period = calculate_summary_for_period(start_date_obj, end_date_obj, location_filter)

    most_active_grade_name = "N/A"
    avg_participation_rate_value = 0
    
    if grade_participation_percent:
        grade_total_activity_counts = {}
        for grade, categories_data in grade_participation_percent.items():
            current_grade_total_activity = 0
            if isinstance(categories_data, dict):
                for category_details in categories_data.values():
                    if isinstance(category_details, dict):
                        current_grade_total_activity += category_details.get("count", 0)
            grade_total_activity_counts[grade] = current_grade_total_activity

        if grade_total_activity_counts:
            sorted_grades_by_activity = sorted(
                grade_total_activity_counts.items(),
                key=lambda item: (-item[1], item[0])
            )
            
            if sorted_grades_by_activity and sorted_grades_by_activity[0][1] > 0:
                most_active_grade_name = sorted_grades_by_activity[0][0]

    if activity_participation:
        total_rate_sum = 0
        valid_activity_count = 0
        for activity in activity_participation:
            rate = activity.get("rate")
            if rate is not None and rate > 0:  # Only count activities with participation
                total_rate_sum += float(rate)
                valid_activity_count += 1
        if valid_activity_count > 0:
            avg_participation_rate_value = round(total_rate_sum / valid_activity_count, 1)

    # Get current quarter and month for header display
    now = datetime.utcnow()
    _, quarter_label, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
    display_quarter = f"{quarter_label} {fiscal_year_label}"
    display_month = now.strftime("%b %Y").upper()

    # Serialize top_performers to remove ObjectId
    serialized_top_performers = []
    for performer in top_performers:
        serialized_top_performers.append({
            "name": performer.get("name"),
            "employee_id": performer.get("employee_id"),
            "grade": performer.get("grade"),
            "us_non_us": performer.get("us_non_us"),
            "location_category": performer.get("location_category"),
            "total_points": performer.get("total_points"),
            "role": performer.get("role")
        })
    
    return jsonify({
        "quarterly_data": quarterly_data,
        "grade_participation": grade_participation,
        "top_performers": serialized_top_performers,
        "activity_participation": activity_participation,
        "grade_participation_percent": grade_participation_percent,
        "utilization_data": utilization_data,
        "most_active_grade_name": most_active_grade_name,
        "avg_participation_rate_value": avg_participation_rate_value,
        "summary_for_selected_period": summary_for_selected_period,
        "display_quarter": display_quarter,
        "display_month": display_month
    })