from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify
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
# CATEGORY MANAGEMENT
# ==========================================

def get_all_categories():
    """Get merged list of categories from both collections - deduplicated by name"""
    all_categories = {}
    
    # Get from old categories collection first
    old_categories = list(mongo.db.categories.find())
    for cat in old_categories:
        category_name = cat.get('name', '')
        if category_name:
            # Store with name as key to prevent duplicates
            all_categories[category_name] = {
                '_id': cat['_id'],
                'name': cat['name'],
                'code': cat.get('code', cat.get('category_code', '')),
                'source': 'categories'
            }
    
    # Get from hr_categories collection (will override if same name exists)
    new_categories = list(mongo.db.hr_categories.find())
    for cat in new_categories:
        category_name = cat.get('name', '')
        if category_name:
            # If same name exists, we need to track both IDs
            if category_name in all_categories:
                # Merge IDs - track both old and new
                old_id = all_categories[category_name]['_id']
                all_categories[category_name] = {
                    '_id': cat['_id'],  # Use new ID as primary
                    'old_id': old_id,   # Keep old ID for reference
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
    
    # Check old categories
    old_cat = mongo.db.categories.find_one({"name": category_name})
    if old_cat:
        category_ids.append(old_cat['_id'])
    
    # Check hr_categories
    new_cat = mongo.db.hr_categories.find_one({"name": category_name})
    if new_cat:
        category_ids.append(new_cat['_id'])
    
    return category_ids


def get_category_for_analytics(category_id):
    """Get category info from either collection"""
    if not category_id:
        return None
    
    # Try hr_categories first
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return category
    
    # Fallback to old categories
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
    
    # Get utilization category IDs to exclude
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
        
        # Query POINTS collection only
        query = {
            "$or": [
                {"event_date": {"$gte": start_date, "$lte": end_date}},
                {"award_date": {"$gte": start_date, "$lte": end_date}},
                {"request_date": {"$gte": start_date, "$lte": end_date}}
            ]
        }
        
        # Exclude utilization categories
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
        
        # Get all possible IDs for this category
        category_ids = get_category_ids_for_name(category_name)
        
        if not category_ids:
            continue
        
        grade_counts = {grade: 0 for grade in grades}
        user_ids = set()
        
        # Query POINTS collection only
        query = {
            "category_id": {"$in": category_ids}
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
                user_ids.add(str(entry["user_id"]))
        
        # Count by grade
        for user_id in user_ids:
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            if user and "grade" in user:
                if user.get("role") == "Employee" or (user.get("role") == "Manager" and user.get("manager_id")):
                    grade = user["grade"]
                    if grade in grade_counts:
                        grade_counts[grade] += 1
        
        participation_data[category_name] = grade_counts
    
    return participation_data


def get_activity_participation_fixed(start_date, end_date):
    """Get activity participation data from POINTS collection only"""
    categories = get_all_categories()
    
    total_eligible_users = mongo.db.users.count_documents({
        "$or": [
            {"role": "Employee"},
            {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
        ]
    })
    
    participation_data = []
    
    for category in categories:
        category_name = category["name"]
        
        # Get all possible IDs for this category
        category_ids = get_category_ids_for_name(category_name)
        
        if not category_ids:
            continue
        
        unique_user_ids = set()
        
        # Query POINTS collection only
        query = {
            "category_id": {"$in": category_ids}
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
                unique_user_ids.add(str(entry["user_id"]))
        
        # Count eligible participants
        eligible_participants = 0
        for user_id in unique_user_ids:
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            if user:
                if user.get("role") == "Employee" or (user.get("role") == "Manager" and user.get("manager_id")):
                    eligible_participants += 1
        
        # Calculate participation rate
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
        "us_non_us": 1, 
        "employee_id": 1,
        "role": 1
    }))
    
    user_points = {}
    
    # Get utilization category IDs to exclude
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    
    # Query POINTS collection only
    query = {}
    
    if start_date and end_date:
        query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    # Exclude utilization categories
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
    
    # Build performers list
    performers = []
    for user in eligible_users:
        user_id_str = str(user["_id"])
        if user_id_str in user_points and user_points[user_id_str] > 0:
            user["total_points"] = user_points[user_id_str]
            performers.append(user)
    
    performers.sort(key=lambda x: x["total_points"], reverse=True)
    
    return performers


def get_grade_participation_percentage_fixed(start_date, end_date):
    """Get grade participation percentage from POINTS collection only"""
    grades = ["A1", "B1", "B2", "C1", "C2", "D1", "D2"]
    
    # Count users per grade
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
            
            # Get all possible IDs for this category
            category_ids = get_category_ids_for_name(category_name)
            
            if not category_ids:
                continue
            
            # Get user IDs for this grade
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
            
            # Query POINTS collection only
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
    
    # Get utilization category IDs to exclude
    utilization_category_ids = []
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    
    # Query POINTS collection only
    query = {}
    
    if start_date and end_date:
        query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    # Exclude utilization categories
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
    # Get utilization category from both collections
    utilization_category = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if not utilization_category:
        utilization_category = mongo.db.categories.find_one({"code": "utilization_billable"})
    
    if not utilization_category:
        return None

    category_name = utilization_category["name"]
    
    # Get all possible IDs for utilization category
    category_ids = get_category_ids_for_name(category_name)
    
    if not category_ids:
        return None

    total_eligible_users = mongo.db.users.count_documents({
        "$or": [
            {"role": "Employee"},
            {"role": "Manager", "manager_id": {"$exists": True, "$ne": None}}
        ]
    })

    unique_user_ids = set()
    
    # Query POINTS collection only
    query = {
        "category_id": {"$in": category_ids}
    }
    
    if start_date and end_date:
        query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
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
            if user.get("role") == "Employee" or \
               (user.get("role") == "Manager" and user.get("manager_id")):
                eligible_participants += 1

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

        query_params = {}
        if start_date_str:
            query_params['start_date'] = start_date_str
        if end_date_str:
            query_params['end_date'] = end_date_str
        
        return redirect(url_for('hr_analytics.pbs_analytics', **query_params))

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

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

    # Get analytics data
    quarterly_data = get_quarterly_performance_data_fixed()
    grade_participation = get_grade_participation_fixed(start_date_obj, end_date_obj)
    top_performers = get_top_performers_fixed(start_date_obj, end_date_obj)
    activity_participation = get_activity_participation_fixed(start_date_obj, end_date_obj)
    grade_participation_percent = get_grade_participation_percentage_fixed(start_date_obj, end_date_obj)
    
    # Calculate most active grade
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

    # Calculate average participation rate
    avg_participation_rate_value = 0
    if activity_participation:
        total_rate_sum = 0
        valid_activity_count = 0
        for activity in activity_participation:
            rate = activity.get("rate")
            if rate is not None:
                total_rate_sum += float(rate)
                valid_activity_count += 1
        if valid_activity_count > 0:
            avg_participation_rate_value = round(total_rate_sum / valid_activity_count, 1)

    utilization_data = get_utilization_participation_data(start_date_obj, end_date_obj)
    
    # Get categories
    categories = get_all_categories()
    
    return render_template(
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
        summary_for_selected_period=calculate_summary_for_period(start_date_obj, end_date_obj),
        user=user
    )


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
    activity_participation = get_activity_participation_fixed(start_date_obj, end_date_obj)
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
            if rate is not None:
                total_rate_sum += float(rate)
                valid_activity_count += 1
        if valid_activity_count > 0:
            avg_participation_rate_value = round(total_rate_sum / valid_activity_count, 1)

    return jsonify({
        "quarterly_data": quarterly_data,
        "grade_participation": grade_participation,
        "top_performers": top_performers,
        "activity_participation": activity_participation,
        "grade_participation_percent": grade_participation_percent,
        "utilization_data": utilization_data,
        "most_active_grade_name": most_active_grade_name,
        "avg_participation_rate_value": avg_participation_rate_value,
        "summary_for_selected_period": summary_for_selected_period,
    })