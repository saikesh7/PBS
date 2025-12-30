from flask import Blueprint, request, session, jsonify, render_template, redirect, url_for
from extensions import mongo
from datetime import datetime
import sys
import traceback
from bson.objectid import ObjectId
from collections import defaultdict

employee_leaderboard_bp = Blueprint('employee_leaderboard', __name__, url_prefix='/employee')

def debug_print(message, data=None):
    """Debug logging function"""
    pass

def error_print(message, error=None):
    """Error logging function"""
    pass

# ==========================================
# DATE HANDLING FUNCTIONS
# ==========================================

def get_fiscal_quarter_from_date(date):
    """Get fiscal quarter number (1-4) from a date based on April-March fiscal year"""
    if not date or not isinstance(date, datetime):
        return None
    
    month = date.month
    # Fiscal year: April=Q1, July=Q2, October=Q3, January=Q4
    if 4 <= month <= 6:
        return 1
    elif 7 <= month <= 9:
        return 2
    elif 10 <= month <= 12:
        return 3
    else:  # 1-3 (Jan-Mar)
        return 4

def extract_event_date(entry):
    """
    Extract event_date from a points entry based on its source
    Handles both points_request and points collections
    """
    if not entry:
        return None
    
    # If event_date exists directly, use it
    if 'event_date' in entry and entry['event_date']:
        return entry['event_date']
    
    # Check if this is from points_request (has 'source' field)
    source = entry.get('source')
    
    if source == 'netsuite_sales':
        # For NetSuite sales, use close_date
        return entry.get('close_date')
    
    elif source == 'netsuite_so':
        # For NetSuite SO, use creation_date
        return entry.get('creation_date')
    
    elif source == 'manager_request':
        # For manager requests, use request_date
        return entry.get('request_date')
    
    elif source == 'hr_bonus':
        # For HR bonus, use award_date
        return entry.get('award_date')
    
    # Fallback: try request_date, then award_date
    return entry.get('request_date') or entry.get('award_date')

def get_effective_date(entry):
    """
    Determine the effective date for a points entry
    Priority: event_date > request_date > award_date
    """
    if not entry:
        return None
    
    # Try event_date first (from extract_event_date)
    event_date = entry.get('event_date')
    if event_date and isinstance(event_date, datetime):
        return event_date
    
    # Try request_date
    request_date = entry.get('request_date')
    if request_date and isinstance(request_date, datetime):
        return request_date
    
    # Try award_date
    award_date = entry.get('award_date')
    if award_date and isinstance(award_date, datetime):
        return award_date
    
    return None

def get_current_fiscal_quarter_and_year(now_utc=None):
    """Get current fiscal quarter and year"""
    if now_utc is None:
        now_utc = datetime.utcnow()
    
    current_month = now_utc.month
    current_calendar_year = now_utc.year
    
    if 1 <= current_month <= 3:
        fiscal_quarter = 4
        fiscal_year_start_calendar_year = current_calendar_year - 1
    elif 4 <= current_month <= 6:
        fiscal_quarter = 1
        fiscal_year_start_calendar_year = current_calendar_year
    elif 7 <= current_month <= 9:
        fiscal_quarter = 2
        fiscal_year_start_calendar_year = current_calendar_year
    else:
        fiscal_quarter = 3
        fiscal_year_start_calendar_year = current_calendar_year
    
    return fiscal_quarter, fiscal_year_start_calendar_year

def get_fiscal_period_date_range(fiscal_quarter, fiscal_year_start_calendar_year):
    """Get date range for a fiscal quarter"""
    if fiscal_quarter == 1:
        start_date = datetime(fiscal_year_start_calendar_year, 4, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 6, 30, 23, 59, 59, 999999)
    elif fiscal_quarter == 2:
        start_date = datetime(fiscal_year_start_calendar_year, 7, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 9, 30, 23, 59, 59, 999999)
    elif fiscal_quarter == 3:
        start_date = datetime(fiscal_year_start_calendar_year, 10, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 12, 31, 23, 59, 59, 999999)
    elif fiscal_quarter == 4:
        start_date = datetime(fiscal_year_start_calendar_year + 1, 1, 1)
        end_date = datetime(fiscal_year_start_calendar_year + 1, 3, 31, 23, 59, 59, 999999)
    else:
        raise ValueError("Invalid fiscal quarter")
    return start_date, end_date

def get_category_for_leaderboard(category_id):
    """
    Get category from either hr_categories or old categories collection
    Note: Missing categories are auto-fixed on app startup by utils.category_validator
    """
    if not category_id:
        return None
    
    # Try hr_categories first (new system)
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return category
    
    # Fallback to old categories
    category = mongo.db.categories.find_one({"_id": category_id})
    if category:
        return category
    
    # Return placeholder to prevent crashes
    return {'name': 'Uncategorized', 'code': 'N/A'}

# ==========================================
# LEADERBOARD DATA FUNCTIONS
# ==========================================

def get_all_approved_points_for_leaderboard(filters=None):
    """
    Get all approved points for leaderboard with effective date filtering
    Handles both old points and new points_request collections
    """
    if filters is None:
        filters = {}
    
    # Build user filter query
    user_filter_query = {}
    department_filter = filters.get('department')
    if department_filter and department_filter != 'all':
        user_filter_query["department"] = department_filter
    
    grade_filter = filters.get('grade')
    if grade_filter and grade_filter != 'all':
        user_filter_query["grade"] = grade_filter
    
    # Get filtered user IDs
    filtered_user_ids = [user['_id'] for user in mongo.db.users.find(user_filter_query, {"_id": 1})]
    
    if not filtered_user_ids:
        return []
    
    # Initialize aggregated points dictionary
    aggregated_points = defaultdict(lambda: {
        'points': 0,
        'user_id': None,
        'last_update': None,
        'entries': []
    })
    
    processed_request_ids = set()
    
    # Parse date filter from year and quarter selection
    date_range = None
    selected_year = filters.get('year', 'all')
    selected_quarter = filters.get('quarter', 'all')
    selected_q_num = None  # Track quarter number for cross-year filtering
    
    # Build quarter filter string based on year and quarter
    if selected_year != 'all' and selected_quarter != 'all':
        # Specific year and specific quarter (e.g., Q1-2025)
        selected_quarter_filter = f"{selected_quarter}-{selected_year}"
    elif selected_year == 'all' and selected_quarter != 'all':
        # All years but specific quarter (e.g., Q1-all)
        selected_quarter_filter = f"{selected_quarter}-all"
    elif selected_year != 'all' and selected_quarter == 'all':
        # Specific year but all quarters (e.g., All-2025)
        selected_quarter_filter = f"All-{selected_year}"
    else:
        # All years and all quarters
        selected_quarter_filter = 'all'
    
    # Parse the constructed quarter filter
    if selected_quarter_filter != 'all':
        if selected_quarter_filter.endswith('-all') and not selected_quarter_filter.startswith('All-'):
            # Specific quarter across all years (Q1-all, Q2-all, etc.) - use wide date range
            selected_q_num = int(selected_quarter_filter[1])  # Extract quarter number
            date_range = (datetime(1900, 1, 1), datetime(2100, 12, 31, 23, 59, 59, 999999))
        elif selected_quarter_filter.startswith('All-') and selected_quarter_filter != 'All-all':
            # All quarters for specific year - use full fiscal year
            try:
                year_start_cal = int(selected_quarter_filter.split('-')[1])
                start_date = datetime(year_start_cal, 4, 1)  # Fiscal year starts April 1
                end_date = datetime(year_start_cal + 1, 3, 31, 23, 59, 59, 999999)  # Ends March 31 next year
                date_range = (start_date, end_date)
            except ValueError:
                pass
        elif '-' in selected_quarter_filter:
            # Specific quarter for specific year
            try:
                q_str, year_str = selected_quarter_filter.split('-')
                q_num = int(q_str[1:])
                year_start_cal = int(year_str)
                start_date, end_date = get_fiscal_period_date_range(q_num, year_start_cal)
                date_range = (start_date, end_date)
            except ValueError:
                pass
    
    # Parse category filter
    category_id_filter_str = filters.get('category')
    category_filter_id = None
    
    if category_id_filter_str and category_id_filter_str != 'all':
        try:
            category_filter_id = ObjectId(category_id_filter_str)
        except Exception:
            return []
    
    # Get utilization category ID to exclude
    utilization_category_doc = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    utilization_category_id = utilization_category_doc["_id"] if utilization_category_doc else None
    
    # ==========================================
    # PROCESS POINTS_REQUEST COLLECTION
    # ==========================================
    pr_query = {
        "status": "Approved",
        "user_id": {"$in": filtered_user_ids}
    }
    
    # Add flexible date query - check multiple date fields
    if date_range:
        start_date, end_date = date_range
        pr_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    # Exclude utilization category if not specifically filtering for it
    if not category_filter_id and utilization_category_id:
        pr_query["category_id"] = {"$ne": utilization_category_id}
    elif category_filter_id:
        pr_query["category_id"] = category_filter_id
    
    approved_requests = mongo.db.points_request.find(pr_query)
    
    for req in approved_requests:
        user_id = req.get("user_id")
        if not user_id:
            continue
        
        # Extract and validate effective date
        event_date = extract_event_date(req)
        entry = {
            'event_date': event_date,
            'request_date': req.get('request_date'),
            'award_date': req.get('award_date')
        }
        effective_date = get_effective_date(entry)
        
        # Check if effective date falls within selected date range
        if date_range:
            start_date, end_date = date_range
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Additional filtering for specific quarter across all years (Q1-all, Q2-all, etc.)
        if selected_q_num is not None:
            req_quarter = get_fiscal_quarter_from_date(effective_date)
            if req_quarter != selected_q_num:
                continue
        
        # Skip if this is utilization category (unless specifically filtered)
        category_id = req.get("category_id")
        if not category_filter_id and utilization_category_id and category_id == utilization_category_id:
            continue
        
        # Mark request as processed
        processed_request_ids.add(req['_id'])
        
        # Add points
        points_value = req.get("points", 0)
        if not isinstance(points_value, (int, float)):
            points_value = 0
        
        aggregated_points[user_id]['points'] += points_value
        aggregated_points[user_id]['user_id'] = user_id
        
        # Update last_update with the most recent effective date
        if effective_date:
            current_last_update = aggregated_points[user_id].get('last_update')
            if not current_last_update or effective_date > current_last_update:
                aggregated_points[user_id]['last_update'] = effective_date
    
    # ==========================================
    # PROCESS POINTS COLLECTION (OLD SYSTEM)
    # ==========================================
    p_query = {
        "user_id": {"$in": filtered_user_ids}
    }
    
    # Add flexible date query for points collection
    if date_range:
        start_date, end_date = date_range
        p_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    # Exclude utilization category if not specifically filtering for it
    if not category_filter_id and utilization_category_id:
        p_query["category_id"] = {"$ne": utilization_category_id}
    elif category_filter_id:
        p_query["category_id"] = category_filter_id
    
    # ✅ REMOVED: No longer fetching from points collection
    points_entries = []
    
    for point in points_entries:
        # Skip if already processed from points_request
        request_id = point.get('request_id')
        if request_id and request_id in processed_request_ids:
            continue
        
        user_id = point.get("user_id")
        if not user_id:
            continue
        
        # Extract and validate effective date
        event_date = extract_event_date(point)
        entry = {
            'event_date': event_date,
            'request_date': point.get('request_date'),
            'award_date': point.get('award_date')
        }
        effective_date = get_effective_date(entry)
        
        # Check if effective date falls within selected date range
        if date_range:
            start_date, end_date = date_range
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Skip if this is utilization category (unless specifically filtered)
        category_id = point.get("category_id")
        if not category_filter_id and utilization_category_id and category_id == utilization_category_id:
            continue
        
        # Add points
        points_value = point.get("points", 0)
        if not isinstance(points_value, (int, float)):
            points_value = 0
        
        aggregated_points[user_id]['points'] += points_value
        aggregated_points[user_id]['user_id'] = user_id
        
        # Update last_update with the most recent effective date
        if effective_date:
            current_last_update = aggregated_points[user_id].get('last_update')
            if not current_last_update or effective_date > current_last_update:
                aggregated_points[user_id]['last_update'] = effective_date
    
    # ==========================================
    # BUILD USER POINTS LIST
    # ==========================================
    user_points_list = []
    user_ids_with_points = [uid for uid, data in aggregated_points.items() if data['points'] > 0]
    
    if not user_ids_with_points:
        return []
    
    # Fetch user details
    users = mongo.db.users.find(
        {"_id": {"$in": user_ids_with_points}},
        {"name": 1, "department": 1, "grade": 1}
    )
    users_map = {user["_id"]: user for user in users}
    
    # Build final list
    for user_id_obj, data in aggregated_points.items():
        if data['points'] > 0 and user_id_obj in users_map:
            user_detail = users_map[user_id_obj]
            user_points_list.append({
                "user_id": str(user_id_obj),
                "name": user_detail.get("name", "N/A"),
                "department": user_detail.get("department", "N/A"),
                "grade": user_detail.get("grade", "N/A"),
                "points": data['points'],
                "last_update": data['last_update']
            })
    
    # Sort by points (descending), then by last_update, then by name
    user_points_list.sort(
        key=lambda x: (-x["points"], x["last_update"] or datetime.max, x["name"])
    )
    
    # Assign ranks (handle ties)
    ranked_list = []
    for i, emp_data in enumerate(user_points_list):
        if i > 0 and emp_data['points'] == user_points_list[i-1]['points']:
            emp_data['rank'] = user_points_list[i-1]['rank']
        else:
            emp_data['rank'] = i + 1
        ranked_list.append(emp_data)
    
    return ranked_list

def get_specific_user_points(user_id, filters):
    """
    Get points for a specific user with effective date filtering
    """
    user_id_obj = ObjectId(user_id)
    aggregated_points = 0
    processed_request_ids = set()
    
    if filters is None:
        filters = {}
    
    # Parse date filter from year and quarter selection
    date_range = None
    selected_year = filters.get('year', 'all')
    selected_quarter = filters.get('quarter', 'all')
    selected_q_num = None  # Track quarter number for cross-year filtering
    
    # Build quarter filter string based on year and quarter
    if selected_year != 'all' and selected_quarter != 'all':
        selected_quarter_filter = f"{selected_quarter}-{selected_year}"
    elif selected_year == 'all' and selected_quarter != 'all':
        selected_quarter_filter = f"{selected_quarter}-all"
    elif selected_year != 'all' and selected_quarter == 'all':
        selected_quarter_filter = f"All-{selected_year}"
    else:
        selected_quarter_filter = 'all'
    
    # Parse the constructed quarter filter
    if selected_quarter_filter != 'all':
        if selected_quarter_filter.endswith('-all') and not selected_quarter_filter.startswith('All-'):
            # Specific quarter across all years (Q1-all, Q2-all, etc.)
            selected_q_num = int(selected_quarter_filter[1])
            date_range = (datetime(1900, 1, 1), datetime(2100, 12, 31, 23, 59, 59, 999999))
        elif selected_quarter_filter.startswith('All-') and selected_quarter_filter != 'All-all':
            # All quarters for specific year
            try:
                year_start_cal = int(selected_quarter_filter.split('-')[1])
                start_date = datetime(year_start_cal, 4, 1)
                end_date = datetime(year_start_cal + 1, 3, 31, 23, 59, 59, 999999)
                date_range = (start_date, end_date)
            except ValueError:
                pass
        elif '-' in selected_quarter_filter:
            # Specific quarter for specific year
            try:
                q_str, year_str = selected_quarter_filter.split('-')
                q_num = int(q_str[1:])
                year_start_cal = int(year_str)
                start_date, end_date = get_fiscal_period_date_range(q_num, year_start_cal)
                date_range = (start_date, end_date)
            except ValueError:
                pass
    
    # Parse category filter
    category_id_filter_str = filters.get('category')
    category_filter_id = None
    
    if category_id_filter_str and category_id_filter_str != 'all':
        try:
            category_filter_id = ObjectId(category_id_filter_str)
        except Exception:
            return 0
    
    # Get utilization category ID to exclude
    utilization_category_doc = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    utilization_category_id = utilization_category_doc["_id"] if utilization_category_doc else None
    
    # ==========================================
    # PROCESS POINTS_REQUEST
    # ==========================================
    pr_query = {
        "status": "Approved",
        "user_id": user_id_obj
    }
    
    if date_range:
        start_date, end_date = date_range
        pr_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    if not category_filter_id and utilization_category_id:
        pr_query["category_id"] = {"$ne": utilization_category_id}
    elif category_filter_id:
        pr_query["category_id"] = category_filter_id
    
    approved_requests = mongo.db.points_request.find(pr_query)
    
    for req in approved_requests:
        # Extract and validate effective date
        event_date = extract_event_date(req)
        entry = {
            'event_date': event_date,
            'request_date': req.get('request_date'),
            'award_date': req.get('award_date')
        }
        effective_date = get_effective_date(entry)
        
        # Check if effective date falls within selected date range
        if date_range:
            start_date, end_date = date_range
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Additional filtering for specific quarter across all years
        if selected_q_num is not None:
            req_quarter = get_fiscal_quarter_from_date(effective_date)
            if req_quarter != selected_q_num:
                continue
        
        processed_request_ids.add(req['_id'])
        
        points_value = req.get("points", 0)
        if not isinstance(points_value, (int, float)):
            points_value = 0
        aggregated_points += points_value
    
    # ==========================================
    # PROCESS POINTS COLLECTION
    # ==========================================
    p_query = {"user_id": user_id_obj}
    
    if date_range:
        start_date, end_date = date_range
        p_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    if not category_filter_id and utilization_category_id:
        p_query["category_id"] = {"$ne": utilization_category_id}
    elif category_filter_id:
        p_query["category_id"] = category_filter_id
    
    # ✅ REMOVED: No longer fetching from points collection
    points_entries = []
    
    for point in points_entries:
        # Skip if already processed
        request_id = point.get('request_id')
        if request_id and request_id in processed_request_ids:
            continue
        
        # Extract and validate effective date
        event_date = extract_event_date(point)
        entry = {
            'event_date': event_date,
            'request_date': point.get('request_date'),
            'award_date': point.get('award_date')
        }
        effective_date = get_effective_date(entry)
        
        # Check if effective date falls within selected date range
        if date_range:
            start_date, end_date = date_range
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        points_value = point.get("points", 0)
        if not isinstance(points_value, (int, float)):
            points_value = 0
        aggregated_points += points_value
    
    return aggregated_points

def get_leaderboard_data_with_rank(user_id_to_find_rank_str, filters=None):
    """
    Get complete leaderboard data with user's rank
    """
    all_ranked_employees = get_all_approved_points_for_leaderboard(filters)
    
    user_rank_details = None
    person_above = None
    average_points = 0
    points_to_next_rank = None
    
    # Calculate average points
    if all_ranked_employees:
        total_points_sum = sum(emp['points'] for emp in all_ranked_employees)
        average_points = round(total_points_sum / len(all_ranked_employees), 2) if all_ranked_employees else 0
    
    # Find user in leaderboard
    if user_id_to_find_rank_str:
        found_user_index = -1
        for i, emp in enumerate(all_ranked_employees):
            if emp["user_id"] == user_id_to_find_rank_str:
                user_rank_details = emp
                found_user_index = i
                break
        
        # Calculate points to next rank
        if found_user_index > 0:
            person_above = all_ranked_employees[found_user_index - 1]
            if user_rank_details and person_above:
                user_points = user_rank_details.get('points')
                above_points = person_above.get('points')
                
                if isinstance(user_points, (int, float)) and isinstance(above_points, (int, float)):
                    diff = above_points - user_points
                    points_to_next_rank = diff if diff >= 0 else 0
                elif user_rank_details.get('rank') != "N/A":
                    points_to_next_rank = "N/A"
        elif found_user_index == 0:
            points_to_next_rank = 0
        
        # User not found in leaderboard - create entry
        elif found_user_index == -1:
            user_db_details = mongo.db.users.find_one({"_id": ObjectId(user_id_to_find_rank_str)})
            if user_db_details:
                department_filter = filters.get('department') if filters else 'all'
                grade_filter = filters.get('grade') if filters else 'all'
                
                user_dept = user_db_details.get('department', '')
                user_grade = user_db_details.get('grade', '')
                
                matches_dept = (not department_filter or department_filter == 'all' or user_dept == department_filter)
                matches_grade = (not grade_filter or grade_filter == 'all' or user_grade == grade_filter)
                
                user_points = get_specific_user_points(user_id_to_find_rank_str, filters)
                
                rank = "N/A"
                if user_points > 0:
                    higher_ranked_count = 0
                    for emp in all_ranked_employees:
                        if emp['points'] > user_points:
                            higher_ranked_count += 1
                    rank = higher_ranked_count + 1
                
                user_rank_details = {
                    "rank": rank,
                    "user_id": user_id_to_find_rank_str,
                    "name": user_db_details.get("name", "N/A"),
                    "department": user_db_details.get("department", "N/A"),
                    "grade": user_db_details.get("grade", "N/A"),
                    "points": user_points,
                    "last_update": None
                }
    
    # Get top 3 and table data
    top_3_employees = all_ranked_employees[:3]
    leaderboard_table_data = all_ranked_employees[:5]
    
    # Add user to table if outside top 5
    if user_rank_details:
        rank_value = user_rank_details.get('rank')
        
        user_is_outside_top_5_display = False
        if rank_value == 'N/A':
            user_is_outside_top_5_display = True
        elif isinstance(rank_value, (int, float)) and rank_value > 5:
            user_is_outside_top_5_display = True
        
        if user_is_outside_top_5_display:
            is_user_in_table = any(u['user_id'] == user_rank_details['user_id'] for u in leaderboard_table_data)
            if not is_user_in_table:
                leaderboard_table_data.append(user_rank_details)
    
    return {
        "user_rank_details": user_rank_details,
        "person_above": person_above,
        "points_to_next_rank": points_to_next_rank,
        "average_points": average_points,
        "top_3_employees": top_3_employees,
        "leaderboard_table_data": leaderboard_table_data,
        "all_count": len(all_ranked_employees)
    }

def get_leaderboard_filter_options():
    """
    Get all available filter options for leaderboard
    Uses hr_categories for new system
    """
    # Get utilization category to exclude
    utilization_category_doc = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    utilization_category_id = utilization_category_doc["_id"] if utilization_category_doc else None
    
    distinct_category_ids = set()
    
    # Get categories from points_request (exclude utilization)
    pr_match_filter = {"status": "Approved"}
    if utilization_category_id:
        pr_match_filter["category_id"] = {"$ne": utilization_category_id}
    
    pr_cat_pipeline = [
        {"$match": pr_match_filter},
        {"$group": {"_id": "$category_id"}}
    ]
    for doc in mongo.db.points_request.aggregate(pr_cat_pipeline):
        if doc.get("_id"):
            distinct_category_ids.add(doc["_id"])
    
    # Get categories from points collection (exclude utilization)
    p_match_filter = {}
    if utilization_category_id:
        p_match_filter["category_id"] = {"$ne": utilization_category_id}
    
    p_cat_pipeline = [
        {"$match": p_match_filter},
        {"$group": {"_id": "$category_id"}}
    ]
    for doc in mongo.db.points.aggregate(p_cat_pipeline):
        if doc.get("_id"):
            distinct_category_ids.add(doc["_id"])
    
    # Fetch category details from hr_categories
    leaderboard_categories = []
    if distinct_category_ids:
        leaderboard_categories = list(mongo.db.hr_categories.find(
            {"_id": {"$in": list(distinct_category_ids)}},
            {"_id": 1, "name": 1}
        ))
    
    # Get distinct quarters from both collections
    date_entries_for_quarters = set()
    
    # From points_request
    pr_date_pipeline = [
        {"$match": {
            "status": "Approved",
            "$or": [
                {"event_date": {"$exists": True, "$ne": None}},
                {"request_date": {"$exists": True, "$ne": None}},
                {"award_date": {"$exists": True, "$ne": None}}
            ]
        }},
        {"$project": {
            "date": {
                "$ifNull": [
                    "$event_date",
                    {"$ifNull": ["$request_date", "$award_date"]}
                ]
            }
        }},
        {"$match": {"date": {"$ne": None}}},
        {"$project": {
            "year": {"$year": "$date"},
            "month": {"$month": "$date"}
        }},
        {"$group": {"_id": {"year": "$year", "month": "$month"}}}
    ]
    for entry in mongo.db.points_request.aggregate(pr_date_pipeline):
        if entry.get('_id') and entry['_id'].get('year') and entry['_id'].get('month'):
            date_entries_for_quarters.add((entry['_id']['year'], entry['_id']['month']))
    
    # From points
    p_date_pipeline = [
        {"$match": {
            "$or": [
                {"event_date": {"$exists": True, "$ne": None}},
                {"award_date": {"$exists": True, "$ne": None}}
            ]
        }},
        {"$project": {
            "date": {
                "$ifNull": ["$event_date", "$award_date"]
            }
        }},
        {"$match": {"date": {"$ne": None}}},
        {"$project": {
            "year": {"$year": "$date"},
            "month": {"$month": "$date"}
        }},
        {"$group": {"_id": {"year": "$year", "month": "$month"}}}
    ]
    for entry in mongo.db.points.aggregate(p_date_pipeline):
        if entry.get('_id') and entry['_id'].get('year') and entry['_id'].get('month'):
            date_entries_for_quarters.add((entry['_id']['year'], entry['_id']['month']))
    
    # Convert to fiscal quarters and extract years
    distinct_quarters_set = set()
    distinct_years_set = set()
    
    for year, month in date_entries_for_quarters:
        if year is not None and month is not None:
            try:
                fq, fyscy = get_current_fiscal_quarter_and_year(datetime(year, month, 1))
                distinct_quarters_set.add(f"Q{fq}-{fyscy}")
                distinct_years_set.add(fyscy)
            except ValueError as e:
                pass
    
    # Sort quarters (most recent first)
    sorted_distinct_quarters = sorted(
        list(distinct_quarters_set),
        key=lambda q_str: (int(q_str.split('-')[1]), int(q_str.split('-')[0][1:])),
        reverse=True
    )
    
    # Sort years (most recent first) and add "all" option
    sorted_distinct_years = sorted(list(distinct_years_set), reverse=True)
    sorted_distinct_years.insert(0, 'all')  # Add "All Years" option at the beginning
    
    # Get user IDs with points
    user_ids_with_points = set()
    
    # From points_request
    pr_user_match = {"status": "Approved", "user_id": {"$exists": True, "$ne": None}}
    if utilization_category_id:
        pr_user_match["category_id"] = {"$ne": utilization_category_id}
    
    pr_user_pipeline = [
        {"$match": pr_user_match},
        {"$group": {"_id": "$user_id"}}
    ]
    for doc in mongo.db.points_request.aggregate(pr_user_pipeline):
        if doc.get("_id"):
            user_ids_with_points.add(doc["_id"])
    
    # From points
    p_user_match = {"user_id": {"$exists": True, "$ne": None}}
    if utilization_category_id:
        p_user_match["category_id"] = {"$ne": utilization_category_id}
    
    p_user_pipeline = [
        {"$match": p_user_match},
        {"$group": {"_id": "$user_id"}}
    ]
    for doc in mongo.db.points.aggregate(p_user_pipeline):
        if doc.get("_id"):
            user_ids_with_points.add(doc["_id"])
    
    # Get distinct departments and grades
    distinct_departments = []
    distinct_grades = []
    
    if user_ids_with_points:
        user_list_for_query = list(user_ids_with_points)
        
        # Departments
        dept_query = {
            "_id": {"$in": user_list_for_query},
            "department": {"$ne": None, "$ne": ""}
        }
        departments_from_users = mongo.db.users.distinct("department", dept_query)
        distinct_departments = sorted([d for d in departments_from_users if d])
        
        # Grades
        grade_query = {
            "_id": {"$in": user_list_for_query},
            "grade": {"$ne": None, "$ne": ""}
        }
        grades_from_users = mongo.db.users.distinct("grade", grade_query)
        distinct_grades = sorted([g for g in grades_from_users if g])
    
    return {
        "distinct_departments": distinct_departments,
        "distinct_grades": distinct_grades,
        "leaderboard_categories": sorted(leaderboard_categories, key=lambda c: c.get('name', '')),
        "distinct_quarters": sorted_distinct_quarters,
        "distinct_years": sorted_distinct_years
    }

# ==========================================
# ROUTES
# ==========================================

@employee_leaderboard_bp.route('/get-leaderboard-filters', methods=['GET'])
def get_leaderboard_filters_api():
    """API endpoint to get filter options"""
    try:
        filter_options = get_leaderboard_filter_options()
        return jsonify(filter_options)
    except Exception as e:
        return jsonify({'error': 'Server error: ' + str(e)}), 500

@employee_leaderboard_bp.route('/get-leaderboard-data', methods=['GET'])
def get_leaderboard_data_route():
    """API endpoint to get leaderboard data"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not authenticated'}), 401
    
    filters = {
        'department': request.args.get('department', 'all'),
        'grade': request.args.get('grade', 'all'),
        'category': request.args.get('category', 'all'),
        'quarter': request.args.get('quarter', 'all'),
        'year': request.args.get('year', 'all'),
    }
    
        
    try:
        leaderboard_data = get_leaderboard_data_with_rank(str(user_id), filters)
        
        return jsonify(leaderboard_data)
    except Exception as e:
        return jsonify({'error': 'Server error: ' + str(e)}), 500

@employee_leaderboard_bp.route('/get-leaderboard-summary')
def get_leaderboard_summary():
    """API endpoint to get leaderboard summary for dashboard widget"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not authenticated'}), 401
    
    try:
        quarter = request.args.get('quarter', 'all')
        category = request.args.get('category', 'all')
        department = request.args.get('department', 'all')
        grade = request.args.get('grade', 'all')
        
        filters = {
            'quarter': quarter,
            'category': category,
            'department': department,
            'grade': grade
        }
        
        leaderboard_data = get_leaderboard_data_with_rank(str(user_id), filters)
        
        user_rank = None
        user_points = 0
        
        if leaderboard_data and leaderboard_data.get('user_rank_details'):
            user_rank_details = leaderboard_data['user_rank_details']
            user_rank = user_rank_details.get('rank', 'N/A')
            user_points = user_rank_details.get('points', 0)
        
        return jsonify({
            'user_rank': user_rank,
            'user_points': user_points
        })
    
    except Exception as e:
        return jsonify({'error': 'Server error'}), 500

@employee_leaderboard_bp.route('/leaderboard')
def leaderboard():
    """Main leaderboard page route"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    # Get user details
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return redirect(url_for('auth.login'))
    
    try:
        # Get filter options for the dropdowns
        filter_options = get_leaderboard_filter_options()
        
        # Get current fiscal quarter and year for default filters
        current_fq, current_fy = get_current_fiscal_quarter_and_year()
        current_quarter = f"Q{current_fq}"
        current_year = str(current_fy)
        
        # Get initial leaderboard data with current year and quarter filter
        initial_leaderboard_data = get_leaderboard_data_with_rank(
            str(user_id), 
            filters={'year': current_year, 'quarter': current_quarter}
        )
        
        # Get dashboard access for navigation
        from dashboard_config import get_user_dashboard_configs
        dashboard_access = user.get('dashboard_access', [])
        user_dashboards = get_user_dashboard_configs(dashboard_access)
        other_dashboards = [d for d in user_dashboards if d['normalized_name'] != 'Employee']
        
        return render_template(
            'employee_leaderboard.html',
            user=user,
            leaderboard_distinct_departments=filter_options.get('distinct_departments', []),
            leaderboard_distinct_grades=filter_options.get('distinct_grades', []),
            leaderboard_categories_options=filter_options.get('leaderboard_categories', []),
            leaderboard_distinct_quarters=filter_options.get('distinct_quarters', []),
            leaderboard_distinct_years=filter_options.get('distinct_years', []),
            initial_leaderboard_data=initial_leaderboard_data,
            current_quarter=current_quarter,
            current_year=current_year,
            other_dashboards=other_dashboards,
            user_profile_pic_url=None
        )
    except Exception as e:
        return redirect(url_for('auth.login'))


