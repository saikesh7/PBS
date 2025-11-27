"""
Batch calculation utilities for optimized leaderboard performance
Reduces N+1 query problems by calculating data for all users at once
"""

from extensions import mongo
from datetime import datetime


def batch_calculate_utilization(user_ids, quarter_start, quarter_end, utilization_category_ids):
    """
    Calculate utilization for ALL users in a single aggregation query
    
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
    
    pipeline = [
        {
            "$match": {
                "user_id": {"$in": user_ids},
                "category_id": {"$in": utilization_category_ids},
                "status": "Approved",
                "request_date": {"$gte": quarter_start, "$lte": quarter_end}
            }
        },
        {
            "$group": {
                "_id": "$user_id",
                "total_util": {"$sum": "$points"},
                "count": {"$sum": 1}
            }
        }
    ]
    
    results = list(mongo.db.points_request.aggregate(pipeline))
    
    utilization_map = {}
    for result in results:
        user_id_str = str(result['_id'])
        count = result.get('count', 0)
        total_util = result.get('total_util', 0)
        
        if count > 0 and total_util > 0:
            avg_util = total_util / count
            utilization_map[user_id_str] = round(avg_util, 2)
    
    return utilization_map


def batch_calculate_yearly_bonus(user_ids, year):
    """
    Calculate yearly bonus points for ALL users in a single aggregation query
    
    Args:
        user_ids: List of user ObjectIds
        year: Year to calculate bonus for
    
    Returns:
        dict: {user_id_str: total_bonus_points}
    """
    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31, 23, 59, 59)
    
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
