"""
Presales API Module
RESTful API endpoints for AJAX calls and real-time updates
"""
from flask import request, session, jsonify
from extensions import mongo
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import logging

from .presales_main import presales_bp
from .presales_helpers import (
    check_presales_access, 
    get_presales_category_ids,
    format_request_for_json
)

logger = logging.getLogger(__name__)

@presales_bp.route('/api/pending_requests', methods=['GET'])
@presales_bp.route('/validator/api/pending_requests', methods=['GET'])
def api_pending_requests():
    """API: Get all pending requests for the current user"""
    has_access, user = check_presales_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    user_id = user['_id']
    
    try:
        presales_category_ids = get_presales_category_ids()
        
        if not presales_category_ids:
            return jsonify({'success': False, 'pending_requests': []})
        
        pending_cursor = mongo.db.points_request.find({
            "category_id": {"$in": presales_category_ids},
            "status": "Pending",
            "assigned_validator_id": ObjectId(user_id)
        }).sort("request_date", -1)
        
        pending_requests = []
        for req_data in pending_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            category = mongo.db.hr_categories.find_one({"_id": req_data["category_id"]})
            
            if not employee or not category:
                continue
            
            pending_requests.append({
                'id': str(req_data["_id"]),
                'employee_name': employee.get("name", "Unknown"),
                'employee_grade': employee.get("grade", "Unknown"),
                'employee_id': employee.get("employee_id", "N/A"),
                'category_name': category.get("name", "Unknown"),
                'points': req_data["points"],
                'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                'notes': req_data.get("request_notes", ""),
                'has_attachment': req_data.get("has_attachment", False),
                'attachment_filename': req_data.get("attachment_filename", ""),
                'title': req_data.get("title", "N/A")
            })
        
        return jsonify({'success': True, 'pending_requests': pending_requests})
    
    except Exception as e:
        logger.error(f"Error getting pending requests: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@presales_bp.route('/check-new-requests', methods=['GET'])
@presales_bp.route('/validator/check-new-requests', methods=['GET'])
def check_new_requests():
    """API: Check for new pending requests since last check"""
    has_access, user = check_presales_access()
    
    if not has_access:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    user_id = user['_id']
    
    try:
        presales_category_ids = get_presales_category_ids()
        
        if not presales_category_ids:
            return jsonify({"pending_count": 0, "new_requests": []})
        
        # Get last check timestamp
        last_check = request.args.get('last_check')
        if last_check:
            try:
                last_check_date = datetime.fromisoformat(last_check.replace('Z', '').replace('+00:00', ''))
            except Exception:
                last_check_date = datetime.utcnow() - timedelta(minutes=5)
        else:
            last_check_date = datetime.utcnow() - timedelta(minutes=5)
        
        # Build query
        query = {
            "category_id": {"$in": presales_category_ids},
            "status": "Pending",
            "assigned_validator_id": ObjectId(user_id)
        }
        
        # Get total pending count
        pending_count = mongo.db.points_request.count_documents(query)
        
        # Find only new requests since last check
        query["request_date"] = {"$gt": last_check_date}
        new_requests_cursor = mongo.db.points_request.find(query).sort("request_date", -1)
        
        new_requests = []
        for req_data in new_requests_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            category = mongo.db.hr_categories.find_one({"_id": req_data["category_id"]})
            
            if not employee or not category:
                continue
            
            new_requests.append({
                'id': str(req_data["_id"]),
                'employee_name': employee.get("name", "Unknown"),
                'employee_grade': employee.get("grade", "Unknown"),
                'category_name': category.get("name", "Unknown"),
                'points': req_data["points"],
                'request_date': req_data["request_date"].isoformat(),
                'notes': req_data.get("request_notes", ""),
                'has_attachment': req_data.get("has_attachment", False),
                'title': req_data.get("title", "N/A")
            })
        
        return jsonify({
            'success': True,
            "pending_count": pending_count,
            "new_requests": new_requests,
            "count": len(new_requests),
            "timestamp": datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error checking new requests: {str(e)}")
        return jsonify({"error": "Server error"}), 500

@presales_bp.route('/fetch_employees', methods=['POST'])
def fetch_employees():
    """API: Fetch employees filtered by department and grade (matches PM logic)"""
    has_access, user = check_presales_access()
    
    if not has_access:
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    try:
        department = request.form.get('department')
        grade = request.form.get('grade')
        
        query = {"role": "Employee"}
        if department != "all":
            query["department"] = department
        if grade != "all":
            query["grade"] = grade
        
        employees = list(mongo.db.users.find(query, {"name": 1, "employee_id": 1, "_id": 1, "grade": 1}))
        
        employee_list = [{
            'id': str(emp['_id']),
            'name': emp.get('name', 'Unknown'),
            'employee_id': emp.get('employee_id', 'N/A'),
            'grade': emp.get('grade', 'Unknown')
        } for emp in employees]
        
        return jsonify({'success': True, 'employees': employee_list})
    
    except Exception as e:
        logger.error(f"Error fetching employees: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@presales_bp.route('/get_categories', methods=['GET'])
def get_categories():
    """API: Fetch all presales categories with full names (matches PM logic)"""
    try:
        # Get presales categories from hr_categories (matches PM logic)
        presales_categories = list(mongo.db.hr_categories.find(
            {
                "category_department": "presales",
                "category_status": "active"
            },
            {"_id": 1, "category_code": 1, "name": 1}
        ))
        
        # Format categories for frontend (matches PM logic)
        formatted_categories = []
        for cat in presales_categories:
            formatted_categories.append({
                'id': str(cat['_id']),
                'code': cat.get('category_code', ''),
                'name': cat.get('name', ''),
                'display_name': cat.get('name', '')
            })
        
        return jsonify({
            'success': True,
            'categories': formatted_categories
        })
    
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@presales_bp.route('/check-processed-updates', methods=['GET'])
def check_processed_updates():
    """API: Check for recently processed requests (for employees)"""
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        # Get last check timestamp
        last_check = request.args.get('last_check')
        if last_check:
            try:
                last_check_date = datetime.fromisoformat(last_check.replace('Z', '').replace('+00:00', ''))
            except:
                last_check_date = datetime.utcnow() - timedelta(minutes=5)
        else:
            last_check_date = datetime.utcnow() - timedelta(minutes=5)
        
        # Find requests submitted by this user that were processed since last check
        processed_cursor = mongo.db.points_request.find({
            "user_id": ObjectId(user_id),
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_date": {"$gt": last_check_date}
        }).sort("processed_date", -1)
        
        processed_requests = []
        for req in processed_cursor:
            category = mongo.db.categories.find_one({"_id": req["category_id"]})
            validator = mongo.db.users.find_one({"_id": req.get("processed_by")})
            
            if category:
                processed_requests.append({
                    'id': str(req["_id"]),
                    'category_name': category.get("name", "Unknown"),
                    'points': req.get("points", 0),
                    'status': req.get("status"),
                    'processed_date': req.get("processed_date").isoformat() if req.get("processed_date") else None,
                    'validator_name': validator.get("name", "Validator") if validator else "Validator",
                    'response_notes': req.get("response_notes", "")
                })
        
        return jsonify({
            "processed_requests": processed_requests,
            "count": len(processed_requests),
            "timestamp": datetime.utcnow().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error checking processed updates: {str(e)}")
        return jsonify({"error": "Server error"}), 500

@presales_bp.route('/validator_quarterly_stats', methods=['GET'])
def validator_quarterly_stats():
    """API: Get quarterly statistics for validator dashboard (matches PM logic)"""
    from .presales_helpers import get_financial_quarter_and_label
    from .constants import ALL_GRADES
    
    has_access, user = check_presales_access()
    
    if not has_access:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    user_id = user['_id']
    
    now = datetime.utcnow()
    
    # Get presales categories from hr_categories (matches PM logic)
    presales_categories = list(mongo.db.hr_categories.find({
        "category_department": "presales",
        "category_status": "active"
    }))
    
    if not presales_categories:
        return jsonify({'success': False, 'message': 'Presales categories not found'}), 404
    
    presales_category_ids = [cat['_id'] for cat in presales_categories]
    
    # Calculate quarterly stats
    quarterly_stats = {}
    q_num_stats, _, quarter_start_month_num, fiscal_year_start_val_stats, _ = get_financial_quarter_and_label(now)
    
    actual_calendar_year_of_quarter_start_stats = fiscal_year_start_val_stats
    if q_num_stats == 4:
        actual_calendar_year_of_quarter_start_stats = fiscal_year_start_val_stats + 1
    
    quarter_start_date_obj = datetime(actual_calendar_year_of_quarter_start_stats, quarter_start_month_num, 1)
    
    if presales_category_ids:
        for grade_key in ALL_GRADES:
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
            
            # Filter by current manager - check processed_by, assigned_validator, or manager_id
            manager_filter = {
                "$or": [
                    {"processed_by": ObjectId(user_id)},
                    {"assigned_validator": ObjectId(user_id)},
                    {"manager_id": ObjectId(user_id)}
                ]
            }
            
            employees_with_presales_rfp_q = mongo.db.points_request.distinct("user_id", {
                "user_id": {"$in": grade_employee_ids},
                "category_id": {"$in": presales_category_ids},
                "processed_date": {"$gte": quarter_start_date_obj},
                "status": "Approved",
                **manager_filter
            })
            
            total_presales_rfp_points_q_cursor = mongo.db.points_request.aggregate([
                {"$match": {
                    "user_id": {"$in": grade_employee_ids},
                    "category_id": {"$in": presales_category_ids},
                    "processed_date": {"$gte": quarter_start_date_obj},
                    "status": "Approved",
                    "$or": [
                        {"processed_by": ObjectId(user_id)},
                        {"assigned_validator": ObjectId(user_id)},
                        {"manager_id": ObjectId(user_id)}
                    ]
                }},
                {"$group": {"_id": None, "total_points": {"$sum": "$points"}}}
            ])
            
            total_presales_rfp_points_q_list = list(total_presales_rfp_points_q_cursor)
            total_presales_rfp_points_for_grade = total_presales_rfp_points_q_list[0]['total_points'] if total_presales_rfp_points_q_list else 0
            
            # Show all grades with total employees count, but only points under this manager
            quarterly_stats[grade_key] = {
                "total_employees": len(grade_employees),  # Total employees in this grade
                "employees_with_presales_rfp": len(employees_with_presales_rfp_q),
                "employees_with_points": len(employees_with_presales_rfp_q),
                "total_presales_rfp_points": total_presales_rfp_points_for_grade,
                "total_points": total_presales_rfp_points_for_grade,
            }
    
    return jsonify({'success': True, 'quarterly_stats': quarterly_stats})

@presales_bp.route('/api/grade_limits', methods=['GET'])
def api_get_grade_limits():
    """
    API: Get grade-wise maximum points for all presales categories
    Fetches dynamically from hr_categories collection (matches PM logic)
    Returns: {category_code: {grade: max_points}}
    """
    has_access, user = check_presales_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        from .presales_helpers import get_all_grade_limits
        
        grade_limits = get_all_grade_limits()
        
        return jsonify({
            'success': True,
            'grade_limits': grade_limits
        })
    
    except Exception as e:
        logger.error(f"Error fetching grade limits: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@presales_bp.route('/api/check_employee_limits', methods=['POST'])
def api_check_employee_limits():
    """
    API: Check employee limits for a specific category
    Fetches max points dynamically from hr_categories (matches PM logic)
    """
    has_access, user = check_presales_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        employee_id = request.form.get('employee_id') or request.json.get('employee_id')
        category_code = request.form.get('category_code') or request.json.get('category_code')
        
        if not employee_id or not category_code:
            return jsonify({
                'success': False,
                'message': 'Employee ID and category code are required'
            }), 400
        
        # Get employee details
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id), "role": "Employee"})
        if not employee:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
        
        grade = employee.get('grade', 'Unknown')
        
        # Get category from hr_categories
        category = mongo.db.hr_categories.find_one({
            "category_code": category_code,
            "category_department": "presales",
            "category_status": "active"
        })
        
        if not category:
            return jsonify({'success': False, 'message': 'Category not found'}), 404
        
        # Get grade-wise max points from category
        grade_points = category.get('grade_points', {})
        max_points_for_grade = grade_points.get(grade, 0)
        points_per_unit = category.get('points_per_unit', 500)
        
        return jsonify({
            'success': True,
            'grade': grade,
            'max_points': max_points_for_grade,
            'points_per_unit': points_per_unit,
            'request_limit': 9999,  # Unlimited requests
            'remaining_requests': 9999,
            'points_limit': max_points_for_grade,
            'remaining_points': max_points_for_grade
        })
    
    except Exception as e:
        logger.error(f"Error checking employee limits: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
