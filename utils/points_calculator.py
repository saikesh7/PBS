"""
Centralized Points Calculation Logic
Used across all modules: Employee Dashboard, HR Analytics, Central Dashboard, etc.
Ensures consistent points calculation from both collections (points_request + points)
"""

from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId


def get_utilization_category_ids():
    """Get utilization category IDs from both collections"""
    utilization_category_ids = []
    
    # Check hr_categories first (new system)
    util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
    if util_cat_hr:
        utilization_category_ids.append(util_cat_hr["_id"])
    
    # Check categories (old system)
    util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
    if util_cat_old:
        utilization_category_ids.append(util_cat_old["_id"])
    
    return utilization_category_ids


def extract_effective_date(entry):
    """
    Extract effective date from entry with flexible field checking
    Priority: event_date → request_date → award_date → metadata.event_date
    """
    if not entry:
        return None
    
    # Priority 1: event_date
    event_date = entry.get('event_date')
    if event_date and isinstance(event_date, datetime):
        return event_date
    
    # Priority 2: request_date (for points_request)
    request_date = entry.get('request_date')
    if request_date and isinstance(request_date, datetime):
        return request_date
    
    # Priority 3: award_date
    award_date = entry.get('award_date')
    if award_date and isinstance(award_date, datetime):
        return award_date
    
    # Priority 4: metadata.event_date (for old points records)
    if 'metadata' in entry and isinstance(entry['metadata'], dict):
        metadata_event_date = entry['metadata'].get('event_date')
        if metadata_event_date and isinstance(metadata_event_date, datetime):
            return metadata_event_date
    
    return None


def calculate_user_points(user_id, start_date=None, end_date=None, category_filter=None, exclude_bonus=True, exclude_utilization=True):
    """
    Calculate total points for a user from BOTH collections
    
    Args:
        user_id: User ObjectId or string
        start_date: Optional start date filter
        end_date: Optional end date filter
        category_filter: Optional category ID or list of IDs to filter
        exclude_bonus: Whether to exclude bonus points (default: True)
        exclude_utilization: Whether to exclude utilization points (default: True)
    
    Returns:
        dict: {
            'total_points': int,
            'bonus_points': int,
            'regular_points': int,
            'count': int
        }
    """
    if isinstance(user_id, str):
        user_id = ObjectId(user_id)
    
    # Get utilization category IDs
    utilization_category_ids = get_utilization_category_ids() if exclude_utilization else []
    
    # Track processed request IDs to avoid double counting
    processed_request_ids = set()
    
    total_points = 0
    bonus_points = 0
    regular_points = 0
    count = 0
    
    # ==========================================
    # STEP 1: Query points_request collection
    # ==========================================
    pr_query = {
        "user_id": user_id,
        "status": "Approved"
    }
    
    # Add date filter with flexible field checking
    if start_date and end_date:
        pr_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    # Add category filter
    if category_filter:
        if isinstance(category_filter, list):
            pr_query["category_id"] = {"$in": category_filter}
        else:
            pr_query["category_id"] = category_filter
    
    # Exclude utilization if requested
    if utilization_category_ids:
        if "category_id" in pr_query:
            # Combine with existing category filter
            if isinstance(pr_query["category_id"], dict) and "$in" in pr_query["category_id"]:
                pr_query["category_id"]["$nin"] = utilization_category_ids
            else:
                pr_query["$and"] = [
                    {"category_id": pr_query["category_id"]},
                    {"category_id": {"$nin": utilization_category_ids}}
                ]
        else:
            pr_query["category_id"] = {"$nin": utilization_category_ids}
    
    approved_requests = list(mongo.db.points_request.find(pr_query))
    
    for req in approved_requests:
        # Extract effective date
        effective_date = extract_effective_date(req)
        
        # Validate date falls in range (double-check)
        if start_date and end_date:
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Mark as processed
        processed_request_ids.add(req['_id'])
        
        # Get points value
        points_value = req.get('points', 0)
        if not isinstance(points_value, (int, float)):
            points_value = 0
        
        # Check if bonus
        is_bonus = req.get('is_bonus', False)
        if not is_bonus:
            # Check category for bonus flag
            category_id = req.get('category_id')
            if category_id:
                category = mongo.db.hr_categories.find_one({'_id': category_id})
                if not category:
                    category = mongo.db.categories.find_one({'_id': category_id})
                if category and category.get('is_bonus'):
                    is_bonus = True
        
        # Add to totals
        if is_bonus:
            bonus_points += points_value
            if not exclude_bonus:
                total_points += points_value
        else:
            regular_points += points_value
            total_points += points_value
        
        count += 1
    
    # ==========================================
    # STEP 2: Query points collection (historical)
    # ==========================================
    p_query = {"user_id": user_id}
    
    # Add date filter with flexible field checking
    if start_date and end_date:
        p_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    # Add category filter
    if category_filter:
        if isinstance(category_filter, list):
            p_query["category_id"] = {"$in": category_filter}
        else:
            p_query["category_id"] = category_filter
    
    # Exclude utilization if requested
    if utilization_category_ids:
        if "category_id" in p_query:
            # Combine with existing category filter
            if isinstance(p_query["category_id"], dict) and "$in" in p_query["category_id"]:
                p_query["category_id"]["$nin"] = utilization_category_ids
            else:
                p_query["$and"] = [
                    {"category_id": p_query["category_id"]},
                    {"category_id": {"$nin": utilization_category_ids}}
                ]
        else:
            p_query["category_id"] = {"$nin": utilization_category_ids}
    
    points_entries = list(mongo.db.points.find(p_query))
    
    for point in points_entries:
        # Skip if already counted from points_request
        request_id = point.get('request_id')
        if request_id and request_id in processed_request_ids:
            continue
        
        # Extract effective date
        effective_date = extract_effective_date(point)
        
        # Validate date falls in range (double-check)
        if start_date and end_date:
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Get points value
        points_value = point.get('points', 0)
        if not isinstance(points_value, (int, float)):
            points_value = 0
        
        # Check if bonus
        is_bonus = point.get('is_bonus', False)
        if not is_bonus:
            # Check category for bonus flag
            category_id = point.get('category_id')
            if category_id:
                category = mongo.db.hr_categories.find_one({'_id': category_id})
                if not category:
                    category = mongo.db.categories.find_one({'_id': category_id})
                if category and category.get('is_bonus'):
                    is_bonus = True
        
        # Add to totals
        if is_bonus:
            bonus_points += points_value
            if not exclude_bonus:
                total_points += points_value
        else:
            regular_points += points_value
            total_points += points_value
        
        count += 1
    
    return {
        'total_points': total_points,
        'bonus_points': bonus_points,
        'regular_points': regular_points,
        'count': count
    }


def calculate_multiple_users_points(user_ids, start_date=None, end_date=None, category_filter=None, exclude_bonus=True, exclude_utilization=True):
    """
    Calculate points for multiple users efficiently
    
    Args:
        user_ids: List of User ObjectIds
        start_date: Optional start date filter
        end_date: Optional end date filter
        category_filter: Optional category ID or list of IDs to filter
        exclude_bonus: Whether to exclude bonus points (default: True)
        exclude_utilization: Whether to exclude utilization points (default: True)
    
    Returns:
        dict: {user_id_str: {'total_points': int, 'bonus_points': int, 'regular_points': int, 'count': int}}
    """
    # Get utilization category IDs
    utilization_category_ids = get_utilization_category_ids() if exclude_utilization else []
    
    # Track processed request IDs to avoid double counting
    processed_request_ids = set()
    
    # Initialize results dictionary
    results = {str(uid): {'total_points': 0, 'bonus_points': 0, 'regular_points': 0, 'count': 0} for uid in user_ids}
    
    # ==========================================
    # STEP 1: Query points_request collection
    # ==========================================
    pr_query = {
        "user_id": {"$in": user_ids},
        "status": "Approved"
    }
    
    # Add date filter
    if start_date and end_date:
        pr_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"request_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    # Add category filter
    if category_filter:
        if isinstance(category_filter, list):
            pr_query["category_id"] = {"$in": category_filter}
        else:
            pr_query["category_id"] = category_filter
    
    # Exclude utilization
    if utilization_category_ids:
        if "category_id" in pr_query:
            if isinstance(pr_query["category_id"], dict) and "$in" in pr_query["category_id"]:
                pr_query["category_id"]["$nin"] = utilization_category_ids
            else:
                pr_query["$and"] = [
                    {"category_id": pr_query["category_id"]},
                    {"category_id": {"$nin": utilization_category_ids}}
                ]
        else:
            pr_query["category_id"] = {"$nin": utilization_category_ids}
    
    approved_requests = list(mongo.db.points_request.find(pr_query))
    
    for req in approved_requests:
        user_id_str = str(req['user_id'])
        
        # Extract effective date
        effective_date = extract_effective_date(req)
        
        # Validate date falls in range
        if start_date and end_date:
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Mark as processed
        processed_request_ids.add(req['_id'])
        
        # Get points value
        points_value = req.get('points', 0)
        if not isinstance(points_value, (int, float)):
            points_value = 0
        
        # Check if bonus
        is_bonus = req.get('is_bonus', False)
        if not is_bonus:
            category_id = req.get('category_id')
            if category_id:
                category = mongo.db.hr_categories.find_one({'_id': category_id})
                if not category:
                    category = mongo.db.categories.find_one({'_id': category_id})
                if category and category.get('is_bonus'):
                    is_bonus = True
        
        # Add to totals
        if is_bonus:
            results[user_id_str]['bonus_points'] += points_value
            if not exclude_bonus:
                results[user_id_str]['total_points'] += points_value
        else:
            results[user_id_str]['regular_points'] += points_value
            results[user_id_str]['total_points'] += points_value
        
        results[user_id_str]['count'] += 1
    
    # ==========================================
    # STEP 2: Query points collection (historical)
    # ==========================================
    p_query = {"user_id": {"$in": user_ids}}
    
    # Add date filter
    if start_date and end_date:
        p_query["$or"] = [
            {"event_date": {"$gte": start_date, "$lte": end_date}},
            {"award_date": {"$gte": start_date, "$lte": end_date}}
        ]
    
    # Add category filter
    if category_filter:
        if isinstance(category_filter, list):
            p_query["category_id"] = {"$in": category_filter}
        else:
            p_query["category_id"] = category_filter
    
    # Exclude utilization
    if utilization_category_ids:
        if "category_id" in p_query:
            if isinstance(p_query["category_id"], dict) and "$in" in p_query["category_id"]:
                p_query["category_id"]["$nin"] = utilization_category_ids
            else:
                p_query["$and"] = [
                    {"category_id": p_query["category_id"]},
                    {"category_id": {"$nin": utilization_category_ids}}
                ]
        else:
            p_query["category_id"] = {"$nin": utilization_category_ids}
    
    points_entries = list(mongo.db.points.find(p_query))
    
    for point in points_entries:
        # Skip if already counted
        request_id = point.get('request_id')
        if request_id and request_id in processed_request_ids:
            continue
        
        user_id_str = str(point['user_id'])
        
        # Extract effective date
        effective_date = extract_effective_date(point)
        
        # Validate date falls in range
        if start_date and end_date:
            if not effective_date or not (start_date <= effective_date <= end_date):
                continue
        
        # Get points value
        points_value = point.get('points', 0)
        if not isinstance(points_value, (int, float)):
            points_value = 0
        
        # Check if bonus
        is_bonus = point.get('is_bonus', False)
        if not is_bonus:
            category_id = point.get('category_id')
            if category_id:
                category = mongo.db.hr_categories.find_one({'_id': category_id})
                if not category:
                    category = mongo.db.categories.find_one({'_id': category_id})
                if category and category.get('is_bonus'):
                    is_bonus = True
        
        # Add to totals
        if is_bonus:
            results[user_id_str]['bonus_points'] += points_value
            if not exclude_bonus:
                results[user_id_str]['total_points'] += points_value
        else:
            results[user_id_str]['regular_points'] += points_value
            results[user_id_str]['total_points'] += points_value
        
        results[user_id_str]['count'] += 1
    
    return results
