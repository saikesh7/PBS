"""
Batch calculation utilities for optimized leaderboard performance
Reduces N+1 query problems by calculating data for all users at once
"""

from extensions import mongo
from datetime import datetime


def batch_calculate_utilization(user_ids, quarter_start, quarter_end, utilization_category_ids):
    """
    Calculate utilization for ALL users - ✅ FIXED to fetch ALL records (including old ones)
    
    Args:
        user_ids: List of user ObjectIds
        quarter_start: Start date of quarter
        quarter_end: End date of quarter
        utilization_category_ids: List of utilization category ObjectIds
    
    Returns:
        dict: {user_id_str: utilization_percentage}
    """
    if not utilization_category_ids:
        return {}
    
    # Use simple loop for reliability (still fast - small dataset)
    utilization_map = {}
    
    try:
        for user_id in user_ids:
            user_id_str = str(user_id)
            
            # ✅ FIXED: Get ALL utilization records (don't filter by date in query)
            # This ensures old records are fetched, then we filter by effective date
            utilization_records = list(mongo.db.points_request.find({
                "user_id": user_id,
                "category_id": {"$in": utilization_category_ids},
                "status": "Approved"
            }))
            
            if utilization_records:
                total_util = 0.0
                count_util = 0
                
                for util_rec in utilization_records:
                    # ✅ Get effective date (prioritize event_date, fallback to request_date)
                    event_date = util_rec.get('event_date')
                    request_date = util_rec.get('request_date')
                    
                    effective_date = None
                    if event_date and isinstance(event_date, datetime):
                        effective_date = event_date
                    elif request_date and isinstance(request_date, datetime):
                        effective_date = request_date
                    
                    # ✅ Filter by effective date (not query date)
                    if not effective_date or not (quarter_start <= effective_date <= quarter_end):
                        continue
                    
                    # Extract utilization value (try multiple locations)
                    util_val = None
                    
                    # Try 1: utilization_value field
                    if 'utilization_value' in util_rec and util_rec.get('utilization_value'):
                        util_val = util_rec.get('utilization_value')
                    
                    # Try 2: submission_data
                    elif 'submission_data' in util_rec:
                        submission_data = util_rec.get('submission_data', {})
                        if isinstance(submission_data, dict):
                            util_val = submission_data.get('utilization_value') or submission_data.get('utilization')
                    
                    # Try 3: points field (as percentage) - for old records
                    if util_val is None or util_val == 0:
                        points = util_rec.get('points', 0)
                        if points > 0 and points <= 100:
                            util_val = points / 100.0
                    
                    if util_val is not None and util_val > 0:
                        # Convert to decimal if it's a percentage
                        if util_val > 1:
                            util_val = util_val / 100.0
                        
                        total_util += util_val
                        count_util += 1
                
                if count_util > 0:
                    utilization_percentage = round((total_util / count_util) * 100, 2)
                    utilization_map[user_id_str] = utilization_percentage
    
    except Exception as e:
        print(f"Error calculating batch utilization: {e}")
    
    return utilization_map


def batch_calculate_yearly_bonus(user_ids, year):
    """
    Calculate yearly bonus points for ALL users in a single aggregation query
    
    Args:
        user_ids: List of user ObjectIds
        year: FISCAL year to calculate bonus for (April-March)
    
    Returns:
        dict: {user_id_str: total_bonus_points}
    """
    # ✅ FIXED: Use fiscal year (April to March next year)
    start_date = datetime(year, 4, 1)
    end_date = datetime(year + 1, 3, 31, 23, 59, 59, 999999)
    
    pipeline = [
        {
            "$match": {
                "user_id": {"$in": user_ids},
                "status": "Approved",
                "request_date": {"$gte": start_date, "$lte": end_date},
                "is_bonus": True
            }
        },
        {
            "$group": {
                "_id": "$user_id",
                "total_bonus": {"$sum": "$points"}
            }
        }
    ]
    
    results = list(mongo.db.points_request.aggregate(pipeline))
    
    bonus_map = {}
    for result in results:
        user_id_str = str(result['_id'])
        bonus_map[user_id_str] = result.get('total_bonus', 0)
    
    return bonus_map
