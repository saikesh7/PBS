"""
Presales Real-time Statistics Update Module
Handles automatic updates to quarterly statistics when requests are approved
"""
from flask import jsonify, session
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import logging

from .presales_main import presales_bp
from .presales_helpers import (
    check_presales_access, get_financial_quarter_and_label,
    get_current_quarter_date_range, get_presales_category_ids
)
from .constants import ALL_GRADES

logger = logging.getLogger(__name__)

def calculate_quarterly_stats_for_user(user_id):
    """
    Calculate quarterly statistics for a specific presales manager/validator
    Returns dict with stats by grade
    """
    try:
        presales_category_ids = get_presales_category_ids()
        
        if not presales_category_ids:
            logger.error("No presales categories found")
            return {}
        
        quarter_start, _, _, _ = get_current_quarter_date_range()
        quarterly_stats = {}
        
        for grade_key in ALL_GRADES:
            grade_employees = list(mongo.db.users.find({"role": "Employee", "grade": grade_key}))
            grade_employee_ids = [emp["_id"] for emp in grade_employees]
            
            if not grade_employee_ids:
                quarterly_stats[grade_key] = {
                    "total_employees": 0,
                    "employees_with_presales_rfp": 0,
                    "employees_with_points": 0,
                    "total_presales_rfp_points": 0,
                    "total_points": 0,
                }
                continue
            
            # ✅ FIXED: Calculate employees with presales points (approved by this user in PRESALES categories only)
            # Must filter by presales_category_ids to ensure only presales approvals are counted
            employees_with_presales = mongo.db.points_request.distinct("user_id", {
                "user_id": {"$in": grade_employee_ids},
                "category_id": {"$in": presales_category_ids},  # ✅ Critical: Only presales categories
                "processed_date": {"$gte": quarter_start},
                "status": "Approved",
                "processed_by": ObjectId(user_id)
            })
            
            # ✅ FIXED: Sum of approved presales points (PRESALES categories only)
            total_presales_points_cursor = mongo.db.points_request.aggregate([
                {"$match": {
                    "user_id": {"$in": grade_employee_ids},
                    "category_id": {"$in": presales_category_ids},  # ✅ Critical: Only presales categories
                    "processed_date": {"$gte": quarter_start},
                    "status": "Approved",
                    "processed_by": ObjectId(user_id)
                }},
                {"$group": {"_id": None, "total_points": {"$sum": "$points"}}}
            ])
            total_presales_points_list = list(total_presales_points_cursor)
            total_presales_points = total_presales_points_list[0]['total_points'] if total_presales_points_list else 0
            
            quarterly_stats[grade_key] = {
                "total_employees": len(grade_employees),
                "employees_with_presales_rfp": len(employees_with_presales),
                "employees_with_points": len(employees_with_presales),
                "total_presales_rfp_points": total_presales_points,
                "total_points": total_presales_points,
            }
        
        return quarterly_stats
        
    except Exception as e:
        logger.error(f"Error calculating quarterly stats: {str(e)}")
        return {}

@presales_bp.route('/api/get_quarterly_stats', methods=['GET'])
def get_quarterly_stats():
    """
    API endpoint to fetch updated quarterly statistics
    Called automatically after request approval
    """
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'Not authenticated'}), 401
    
    if manager_level != 'Pre-sales':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    try:
        quarterly_stats = calculate_quarterly_stats_for_user(user_id)
        
        return jsonify({
            'success': True,
            'quarterly_stats': quarterly_stats
        })
        
    except Exception as e:
        logger.error(f"Error fetching quarterly stats: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
