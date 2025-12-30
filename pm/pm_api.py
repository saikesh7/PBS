from flask import request, session, jsonify
from extensions import mongo
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import sys
from .pm_main import pm_bp

def error_print(message, error=None):
    pass

def check_pm_access():
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    return 'pm' in dashboard_access, user

@pm_bp.route('/api/pending_requests')
def api_pending_requests():
    has_access, user = check_pm_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        # Get PM categories
        pm_categories = list(mongo.db.categories.find({
            "code": {"$in": ["initiative_ai", "mentoring"]},
            "validator": "PM"
        }))
        
        if not pm_categories:
            return jsonify({'success': False, 'pending_requests': []})
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        # Check if validator
        is_validator = not any(user.get(f) for f in ['pm_arch_validator_id', 'pm_validator_id',
                                                      'marketing_validator_id', 'presales_validator_id'])
        
        if is_validator:
            # Get requests assigned to validator
            pending_cursor = mongo.db.points_request.find({
                "category_id": {"$in": pm_category_ids},
                "status": "Pending",
                "validator": "PM",
                "assigned_validator_id": ObjectId(user["_id"])
            }).sort("request_date", -1)
        else:
            # Get requests from managed employees
            managed_employees = mongo.db.users.find({"pm_validator_id": ObjectId(user["_id"])})
            managed_employee_ids = [emp["_id"] for emp in managed_employees]
            
            pending_cursor = mongo.db.points_request.find({
                "user_id": {"$in": managed_employee_ids},
                "category_id": {"$in": pm_category_ids},
                "status": "Pending",
                "validator": "PM"
            }).sort("request_date", -1)
        
        pending_requests = []
        for req_data in pending_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            if not employee:
                continue
            
            category_obj = next((cat for cat in pm_categories if cat["_id"] == req_data["category_id"]), None)
            if category_obj:
                pending_requests.append({
                    'id': str(req_data["_id"]),
                    'employee_name': employee.get("name", "Unknown"),
                    'employee_grade': employee.get("grade", "Unknown"),
                    'category_name': category_obj.get("name", "Unknown"),
                    'points': req_data["points"],
                    'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                    'notes': req_data.get("request_notes", ""),
                    'has_attachment': req_data.get("has_attachment", False),
                    'attachment_filename': req_data.get("attachment_filename", "")
                })
        
        return jsonify({'success': True, 'pending_requests': pending_requests})
        
    except Exception as e:
        error_print("Error getting pending requests", e)
        return jsonify({'success': False, 'error': str(e)})

@pm_bp.route('/check-new-requests')
def check_new_requests():
    has_access, user = check_pm_access()
    
    if not has_access:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        # Get PM categories
        pm_categories = list(mongo.db.categories.find({
            "code": {"$in": ["initiative_ai", "mentoring"]},
            "validator": "PM"
        }))
        
        if not pm_categories:
            return jsonify({"pending_count": 0, "new_requests": []})
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        # Get last check time
        last_check = request.args.get('last_check')
        if last_check:
            try:
                last_check_date = datetime.fromisoformat(last_check.replace('Z', '').replace('+00:00', ''))
            except:
                last_check_date = datetime.utcnow() - timedelta(minutes=5)
        else:
            last_check_date = datetime.utcnow() - timedelta(minutes=5)
        
        # Check if validator
        is_validator = not any(user.get(f) for f in ['pm_arch_validator_id', 'pm_validator_id',
                                                      'marketing_validator_id', 'presales_validator_id'])
        
        # Build query
        if is_validator:
            query = {
                "category_id": {"$in": pm_category_ids},
                "status": "Pending",
                "validator": "PM",
                "assigned_validator_id": ObjectId(user["_id"])
            }
        else:
            managed_employees = mongo.db.users.find({"pm_validator_id": ObjectId(user["_id"])})
            managed_employee_ids = [emp["_id"] for emp in managed_employees]
            
            query = {
                "user_id": {"$in": managed_employee_ids},
                "category_id": {"$in": pm_category_ids},
                "status": "Pending",
                "validator": "PM"
            }
        
        # Get total pending count
        pending_count = mongo.db.points_request.count_documents(query)
        
        # Get new requests
        query["request_date"] = {"$gt": last_check_date}
        new_requests_cursor = mongo.db.points_request.find(query).sort("request_date", -1)
        
        new_requests = []
        for req_data in new_requests_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            if not employee:
                continue
            
            category_obj = next((cat for cat in pm_categories if cat["_id"] == req_data["category_id"]), None)
            if not category_obj:
                continue
            
            new_requests.append({
                'id': str(req_data["_id"]),
                'employee_name': employee.get("name", "Unknown"),
                'employee_grade': employee.get("grade", "Unknown"),
                'category_name': category_obj.get("name", "Unknown"),
                'points': req_data["points"],
                'request_date': req_data["request_date"].isoformat(),
                'notes': req_data.get("request_notes", ""),
                'has_attachment': req_data.get("has_attachment", False)
            })
        
        return jsonify({
            "pending_count": pending_count,
            "new_requests": new_requests,
            "count": len(new_requests),
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        error_print("Error checking new requests", e)
        return jsonify({"error": "Server error"}), 500

@pm_bp.route('/api/get-categories')
def get_categories():
    has_access, user = check_pm_access()
    
    if not has_access:
        return jsonify({'success': False, 'message': 'Not authorized'}), 403
    
    try:
        categories = list(mongo.db.categories.find({
            "code": {"$in": ["initiative_ai", "mentoring"]},
            "validator": "PM"
        }))
        
        result = []
        for cat in categories:
            result.append({
                "id": str(cat["_id"]),
                "name": cat.get("name", "Unknown"),
                "description": cat.get("description", ""),
                "points_per_unit": cat.get("points_per_unit", 0),
                "code": cat.get("code", "")
            })
        
        return jsonify({
            'success': True,
            'categories': result,
            'count': len(result)
        })
        
    except Exception as e:
        error_print("Get categories error", e)
        return jsonify({
            'success': False,
            'message': f'Error fetching categories: {str(e)}'
        }), 500

@pm_bp.route('/api/get-employees')
def get_employees():
    has_access, user = check_pm_access()
    
    if not has_access:
        return jsonify({'success': False, 'message': 'Not authorized'}), 403
    
    try:
        query = {"role": "Employee"}
        
        # Apply filters
        department = request.args.get('department', '')
        grade = request.args.get('grade', '')
        
        if department:
            query["department"] = department
        if grade:
            query["grade"] = grade
        
        employees = list(mongo.db.users.find(query, {
            "_id": 1,
            "name": 1,
            "email": 1,
            "grade": 1,
            "department": 1,
            "employee_id": 1
        }))
        
        result = []
        for emp in employees:
            result.append({
                "id": str(emp["_id"]),
                "name": emp.get("name", "Unknown"),
                "email": emp.get("email", ""),
                "grade": emp.get("grade", ""),
                "department": emp.get("department", ""),
                "employee_id": emp.get("employee_id", "")
            })
        
        return jsonify({
            'success': True,
            'employees': result,
            'count': len(result)
        })
        
    except Exception as e:
        error_print("Get employees error", e)
        return jsonify({
            'success': False,
            'message': f'Error fetching employees: {str(e)}'
        }), 500