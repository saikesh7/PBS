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
                            static_url_path='/hr/static')


# ==========================================
# HELPER FUNCTIONS
# ==========================================

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
    """Get category info from either collection"""
    if not category_id:
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

def get_quarterly_performance_data_fixed():
    """
    Get quarterly performance data from POINTS collection only
    ALWAYS shows last 4 quarters regardless of filters
    """
    current_date = datetime.utcnow()
    
    fiscal_year = current_date.year
    if current_date.month < 4:
        fiscal_year -= 1
    
    month = current_date.month
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
    
    for i in range(4):
        q = fiscal_quarter - i
        yr = fiscal_year
        
        if q <= 0:
            q += 4
            yr -= 1
        
        if q == 1:
            start_date = datetime(yr, 4, 1)
            end_date = datetime(yr, 6, 30, 23, 59, 59, 999999)
            period_name = f"Q1 {yr}-{yr+1}"
        elif q == 2:
            start_date = datetime(yr, 7, 1)
            end_date = datetime(yr, 9, 30, 23, 59, 59, 999999)
            period_name = f"Q2 {yr}-{yr+1}"
        elif q == 3:
            start_date = datetime(yr, 10, 1)
            end_date = datetime(yr, 12, 31, 23, 59, 59, 999999)
            period_name = f"Q3 {yr}-{yr+1}"
        else:
            start_date = datetime(yr + 1, 1, 1)
            end_date = datetime(yr + 1, 3, 31, 23, 59, 59, 999999)
            period_name = f"Q4 {yr}-{yr+1}"
        
        category_data = {}
        total_points = 0
        total_count = 0
        
        query = {
            "$or": [
                {"event_date": {"$gte": start_date, "$lte": end_date}},
                {"award_date": {"$gte": start_date, "$lte": end_date}},
                {"request_date": {"$gte": start_date, "$lte": end_date}}
            ]
        }
        
        if utilization_category_ids:
            query["category_id"] = {"$nin": utilization_category_ids}
        
        points_data = list(mongo.db.points.find(query))
        
        for entry in points_data:
            event_date = extract_event_date(entry)
            entry_with_dates = {
                'event_date': event_date,
                'request_date': entry.get('request_date'),
                'award_date': entry.get('award_date')
            }
            effective_date = get_effective_date(entry_with_dates)
            
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
            
            category_id = entry.get("category_id")
            if not category_id:
                continue
            
            points = entry.get("points", 0)
            category = get_category_for_analytics(category_id)
            category_name = category["name"] if category else "Unknown"
            
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


def get_grade_participation_fixed(start_date, end_date):
    """Get grade participation data from POINTS collection only"""
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
        
        query = {"category_id": {"$in": category_ids}}
        
        if start_date and end_date:
            query["$or"] = [
                {"event_date": {"$gte": start_date, "$lte": end_date}},
                {"award_date": {"$gte": start_date, "$lte": end_date}},
                {"request_date": {"$gte": start_date, "$lte": end_date}}
            ]
        
        points_data = list(mongo.db.points.find(query))
        
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
    user_query = {
        "$or": [
            {"role": "Employee"},
            {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
        ]
    }
    
    if location_filter:
        # Check both location and us_non_us fields for backward compatibility
        user_query = {
            "$and": [
                {"$or": [
                    {"role": "Employee"},
                    {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
                ]},
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
        
        query = {"category_id": {"$in": category_ids}}
        
        if start_date and end_date:
            query["$or"] = [
                {"event_date": {"$gte": start_date, "$lte": end_date}},
                {"award_date": {"$gte": start_date, "$lte": end_date}},
                {"request_date": {"$gte": start_date, "$lte": end_date}}
            ]
        
        points_data = list(mongo.db.points.find(query))
        
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
                        user_location = user.get("location") or user.get("us_non_us")
                        if user_location == location_filter:
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


def get_top_performers_fixed(start_date, end_date):
    """Get top performers from POINTS collection only"""
    eligible_users = list(mongo.db.users.find({
        "$or": [
            {"role": "Employee"},
            {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
        ]
    }, {
        "_id": 1, 
        "name": 1, 
        "grade": 1, 
        "location": 1,
        "us_non_us": 1, 
        "employee_id": 1,
        "role": 1
    }))
    
    user_points = {}
    
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    
    query = {}
    
    if start_date and end_date:
        query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    if utilization_category_ids:
        query["category_id"] = {"$nin": utilization_category_ids}
    
    points_data = list(mongo.db.points.find(query))
    
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
        
        user_id = entry.get("user_id")
        if user_id:
            user_id_str = str(user_id)
            points = entry.get("points", 0)
            user_points[user_id_str] = user_points.get(user_id_str, 0) + points
    
    performers = []
    for user in eligible_users:
        user_id_str = str(user["_id"])
        if user_id_str in user_points and user_points[user_id_str] > 0:
            user["total_points"] = user_points[user_id_str]
            
            # Get location from either field
            location = user.get("location") or user.get("us_non_us")
            
            # Map specific locations to US/Non-US categories for filtering
            if location == "US":
                user["us_non_us"] = "US"
                user["location_category"] = "US"
            elif location in ["Non-US", "India", "UK", "Canada", "Australia", "Singapore", "Philippines", "Malaysia"]:
                user["us_non_us"] = location  # Keep original for display
                user["location_category"] = "Non-US"  # Category for filtering
            else:
                user["us_non_us"] = location or "N/A"
                user["location_category"] = "Non-US" if location else "N/A"
            
            performers.append(user)
    
    performers.sort(key=lambda x: x["total_points"], reverse=True)
    
    return performers


def get_grade_participation_percentage_fixed(start_date, end_date):
    """Get grade participation percentage from POINTS collection only"""
    grades = ["A1", "B1", "B2", "C1", "C2", "D1", "D2"]
    
    grade_counts = {}
    for grade in grades:
        count = mongo.db.users.count_documents({
            "$and": [
                {"grade": grade},
                {
                    "$or": [
                        {"role": "Employee"},
                        {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
                    ]
                }
            ]
        })
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
            
            user_ids = [str(u["_id"]) for u in mongo.db.users.find({
                "$and": [
                    {"grade": grade},
                    {
                        "$or": [
                            {"role": "Employee"},
                            {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
                        ]
                    }
                ]
            }, {"_id": 1})]
            
            object_ids = [ObjectId(id) for id in user_ids]
            
            participants_for_category_grade = set()
            
            query = {
                "category_id": {"$in": category_ids},
                "user_id": {"$in": object_ids}
            }
            
            if start_date and end_date:
                query["$or"] = [
                    {"event_date": {"$gte": start_date, "$lte": end_date}},
                    {"award_date": {"$gte": start_date, "$lte": end_date}},
                    {"request_date": {"$gte": start_date, "$lte": end_date}}
                ]
            
            points_data = list(mongo.db.points.find(query))
            
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


def calculate_summary_for_period(start_date, end_date):
    """Calculate summary for selected period from POINTS collection only"""
    total_points = 0
    total_count = 0
    
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    
    query = {}
    
    if start_date and end_date:
        query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    if utilization_category_ids:
        query["category_id"] = {"$nin": utilization_category_ids}
    
    points_data = list(mongo.db.points.find(query))
    
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
        
        total_points += entry.get("points", 0)
        total_count += 1
    
    return {"total_points": total_points, "total_count": total_count}


def get_utilization_participation_data(start_date, end_date):
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

    total_eligible_users = mongo.db.users.count_documents({
        "$or": [
            {"role": "Employee"},
            {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
        ]
    })

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
        "$or": [
            {"role": "Employee"},
            {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
        ]
    })

    # Get active participants (users with at least one point entry)
    active_participant_ids = mongo.db.points.distinct("user_id")
    active_participants = len([uid for uid in active_participant_ids if uid is not None])

    # Get total points awarded (excluding utilization)
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])

    query = {}
    if utilization_category_ids:
        query["category_id"] = {"$nin": utilization_category_ids}

    total_points_pipeline = [
        {"$match": query},
        {"$group": {"_id": None, "total": {"$sum": "$points"}}}
    ]
    total_points_result = list(mongo.db.points.aggregate(total_points_pipeline))
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

    # Get recent activities (last 20 point entries)
    recent_activities = []
    recent_points = list(mongo.db.points.find(query).sort([("award_date", -1), ("request_date", -1)]).limit(20))
    
    for entry in recent_points:
        user_doc = mongo.db.users.find_one({"_id": entry.get("user_id")})
        category = get_category_for_analytics(entry.get("category_id"))
        
        if user_doc and category:
            event_date = extract_event_date(entry)
            recent_activities.append({
                "date": event_date or entry.get("award_date") or entry.get("request_date"),
                "employee_name": user_doc.get("name", "Unknown"),
                "category_name": category.get("name", "Unknown"),
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

    quarterly_data = get_quarterly_performance_data_fixed()
    grade_participation = get_grade_participation_fixed(start_date_obj, end_date_obj)
    top_performers = get_top_performers_fixed(start_date_obj, end_date_obj)
    activity_participation = get_activity_participation_fixed(start_date_obj, end_date_obj, location_filter)
    grade_participation_percent = get_grade_participation_percentage_fixed(start_date_obj, end_date_obj)
    
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

    utilization_data = get_utilization_participation_data(start_date_obj, end_date_obj)
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
        summary_for_selected_period=calculate_summary_for_period(start_date_obj, end_date_obj),
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

    quarterly_data = get_quarterly_performance_data_fixed()
    grade_participation = get_grade_participation_fixed(start_date_obj, end_date_obj)
    top_performers = get_top_performers_fixed(start_date_obj, end_date_obj)
    activity_participation = get_activity_participation_fixed(start_date_obj, end_date_obj, location_filter)
    grade_participation_percent = get_grade_participation_percentage_fixed(start_date_obj, end_date_obj)
    utilization_data = get_utilization_participation_data(start_date_obj, end_date_obj)
    summary_for_selected_period = calculate_summary_for_period(start_date_obj, end_date_obj)

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