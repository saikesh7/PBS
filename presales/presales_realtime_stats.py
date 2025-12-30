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
    Calculate quarterly statistics for presales dashboard
    Returns dict with stats by grade - shows ALL grades but only points under the current manager
    """
    try:
        presales_category_ids = get_presales_category_ids()
        quarter_start, quarter_end, quarter, fiscal_year = get_current_quarter_date_range()
        quarterly_stats = {}
        
        # Convert user_id to ObjectId if it's a string
        manager_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        
        logger.info(f"Calculating quarterly stats for manager {manager_id} - category_ids: {presales_category_ids}, quarter_start: {quarter_start}, quarter_end: {quarter_end}")
        
        for grade_key in ALL_GRADES:
            # Get all users with this grade
            grade_employees = list(mongo.db.users.find({"grade": grade_key}))
            grade_employee_ids = [emp["_id"] for emp in grade_employees]
            
            # Always include all grades, even if no employees
            if not grade_employee_ids:
                quarterly_stats[grade_key] = {
                    "total_employees": 0,
                    "employees_with_presales_rfp": 0,
                    "employees_with_points": 0,
                    "total_presales_rfp_points": 0,
                    "total_points": 0,
                }
                continue
            
            # Date filter for current quarter
            date_filter = {
                "$or": [
                    {"processed_date": {"$gte": quarter_start, "$lte": quarter_end}},
                    {
                        "$and": [
                            {"$or": [
                                {"processed_date": {"$exists": False}},
                                {"processed_date": None}
                            ]},
                            {"request_date": {"$gte": quarter_start, "$lte": quarter_end}}
                        ]
                    }
                ]
            }
            
            # Build category/department filter
            category_conditions = []
            if presales_category_ids:
                category_conditions.append({"category_id": {"$in": presales_category_ids}})
            category_conditions.append({"processed_department": "presales"})
            category_conditions.append({"processed_department": "Pre-Sales"})
            category_conditions.append({"processed_department": {"$regex": "pre.?sales", "$options": "i"}})
            
            # Filter by current manager - check processed_by, assigned_validator, or manager_id
            manager_filter = {
                "$or": [
                    {"processed_by": manager_id},
                    {"assigned_validator": manager_id},
                    {"manager_id": manager_id}
                ]
            }
            
            base_query = {
                "user_id": {"$in": grade_employee_ids},
                "status": "Approved",
                "$and": [
                    {"$or": category_conditions},
                    date_filter,
                    manager_filter
                ]
            }
            
            # Calculate employees with presales points under this manager
            employees_with_presales = mongo.db.points_request.distinct("user_id", base_query)
            
            # Sum of approved presales points for the quarter under this manager
            total_presales_points_cursor = mongo.db.points_request.aggregate([
                {"$match": base_query},
                {"$group": {"_id": None, "total_points": {"$sum": "$points"}}}
            ])
            total_presales_points_list = list(total_presales_points_cursor)
            total_presales_points = total_presales_points_list[0]['total_points'] if total_presales_points_list else 0
            
            # Show all grades with total employees count, but only points under this manager
            quarterly_stats[grade_key] = {
                "total_employees": len(grade_employees),  # Total employees in this grade
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


@presales_bp.route('/api/debug_quarterly_stats', methods=['GET'])
def debug_quarterly_stats():
    """
    Debug endpoint to check what data exists for quarterly stats
    """
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'Not authenticated'}), 401
    
    try:
        from .presales_helpers import get_presales_categories, get_presales_category_ids, get_current_quarter_date_range
        
        # Get presales categories
        presales_categories = get_presales_categories()
        presales_category_ids = get_presales_category_ids()
        quarter_start, quarter_end, quarter, fiscal_year = get_current_quarter_date_range()
        
        # Get all approved requests (not just presales) to debug
        all_approved = list(mongo.db.points_request.find({
            "status": "Approved"
        }).limit(20))
        
        # Format for display
        approved_list = []
        for req in all_approved:
            user = mongo.db.users.find_one({"_id": req.get("user_id")})
            cat_id = req.get("category_id")
            is_presales_cat = cat_id in presales_category_ids if cat_id else False
            
            # Check date range
            proc_date = req.get("processed_date")
            req_date = req.get("request_date")
            in_quarter = False
            if proc_date and isinstance(proc_date, datetime):
                in_quarter = quarter_start <= proc_date <= quarter_end
            elif req_date and isinstance(req_date, datetime):
                in_quarter = quarter_start <= req_date <= quarter_end
            
            approved_list.append({
                "id": str(req["_id"]),
                "user_name": user.get("name") if user else "Unknown",
                "user_id": str(req.get("user_id")),
                "user_grade": user.get("grade") if user else "Unknown",
                "category_id": str(cat_id) if cat_id else None,
                "is_presales_category": is_presales_cat,
                "processed_department": req.get("processed_department"),
                "points": req.get("points"),
                "status": req.get("status"),
                "processed_date": str(proc_date) if proc_date else None,
                "processed_date_type": type(proc_date).__name__,
                "request_date": str(req_date) if req_date else None,
                "request_date_type": type(req_date).__name__,
                "in_current_quarter": in_quarter
            })
        
        # Also get D2 users to check (all roles, not just Employee)
        d2_employees = list(mongo.db.users.find({"grade": "D2"}).limit(5))
        d2_list = [{"id": str(e["_id"]), "name": e.get("name"), "role": e.get("role")} for e in d2_employees]
        
        return jsonify({
            'success': True,
            'debug_info': {
                'presales_categories': [{"id": str(c["_id"]), "name": c.get("name"), "department": c.get("category_department")} for c in presales_categories],
                'presales_category_ids': [str(cid) for cid in presales_category_ids],
                'quarter_start': str(quarter_start),
                'quarter_end': str(quarter_end),
                'quarter': quarter,
                'fiscal_year': fiscal_year,
                'approved_requests': approved_list,
                'd2_employees_sample': d2_list
            }
        })
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}")
        import traceback
        return jsonify({'success': False, 'message': str(e), 'traceback': traceback.format_exc()}), 500
