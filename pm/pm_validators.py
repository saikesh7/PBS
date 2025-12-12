from flask import request, session, jsonify, redirect, url_for, flash
from extensions import mongo
from bson.objectid import ObjectId
from pm_helpers import (
    check_pm_dashboard_access,
    validate_employee_for_award,
    get_current_quarter_date_range
)

def register_validator_routes(bp):
    """Register all validator-related routes to the blueprint"""
    
    @bp.route('/validate-employee/<employee_id>')
    def validate_employee(employee_id):
        """Validate a single employee by ID"""
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Not authenticated"}), 401
        
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not check_pm_dashboard_access(user):
            return jsonify({"error": "Not authorized"}), 403
        
        try:
            validation_result = validate_employee_for_award(employee_id)
            
            if not validation_result["valid"]:
                if "employee" in validation_result and validation_result["employee"]:
                    employee = validation_result["employee"]
                    return jsonify({
                        "valid": False,
                        "employee_id": str(employee["_id"]),
                        "employee_name": employee.get("name", ""),
                        "email": employee.get("email", ""),
                        "employee_id_field": employee.get("employee_id", ""),
                        "grade": employee.get("grade", "Unknown"),
                        "department": employee.get("department", ""),
                        "current_quarter_count": validation_result.get("current_count", 0),
                        "total_quarter_points": validation_result.get("total_quarter_points", 0),
                        "expected_points": validation_result.get("expected_points", 0),
                        "error": validation_result["error"]
                    })
                else:
                    return jsonify({
                        "valid": False,
                        "error": validation_result["error"]
                    })
            
            employee = validation_result["employee"]
            
            return jsonify({
                "valid": True,
                "employee_id": str(employee["_id"]),
                "employee_name": employee.get("name", ""),
                "email": employee.get("email", ""),
                "employee_id_field": employee.get("employee_id", ""),
                "grade": employee.get("grade", "Unknown"),
                "department": employee.get("department", ""),
                "current_quarter_count": validation_result["current_count"],
                "total_quarter_points": validation_result["total_quarter_points"],
                "expected_points": validation_result["expected_points"]
            })
            
        except Exception:
            return jsonify({"valid": False, "error": "Server error"}), 500
    
    @bp.route('/check-quarterly-info/<employee_id>')
    def check_quarterly_info(employee_id):
        """Check quarterly request information for an employee"""
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Not authenticated"}), 401
        
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not check_pm_dashboard_access(user):
            return jsonify({"error": "Not authorized"}), 403
        
        try:
            validation_result = validate_employee_for_award(employee_id)
            
            if not validation_result["valid"]:
                if "employee" in validation_result and validation_result["employee"]:
                    employee = validation_result["employee"]
                    return jsonify({
                        "employee_id": str(employee["_id"]),
                        "employee_name": employee.get("name", ""),
                        "grade": employee.get("grade", "Unknown"),
                        "current_quarter_count": validation_result.get("current_count", 0),
                        "total_quarter_points": validation_result.get("total_quarter_points", 0),
                        "expected_points": validation_result.get("expected_points", 0),
                        "can_award": True,  # Always allow awards
                        "error": validation_result["error"]
                    })
                else:
                    return jsonify({"error": validation_result["error"]}), 404
            
            employee = validation_result["employee"]
            
            return jsonify({
                "employee_id": str(employee["_id"]),
                "employee_name": employee.get("name", ""),
                "grade": employee.get("grade", "Unknown"),
                "current_quarter_count": validation_result["current_count"],
                "total_quarter_points": validation_result["total_quarter_points"],
                "expected_points": validation_result["expected_points"],
                "can_award": True  # Always allow awards
            })
            
        except Exception:
            return jsonify({"error": "Server error"}), 500
    
    @bp.route('/find-employee-by-id/<employee_code>')
    def find_employee_by_id(employee_code):
        """Find employee by their employee ID code"""
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Not authenticated"}), 401
        
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not check_pm_dashboard_access(user):
            return jsonify({"error": "Not authorized"}), 403
        
        try:
            # Find employee by employee_id field
            employee = mongo.db.users.find_one({"employee_id": employee_code})
            
            if not employee:
                return jsonify({"found": False, "error": "Employee not found"}), 404
            
            # Return employee details
            return jsonify({
                "found": True,
                "employee": {
                    "id": str(employee["_id"]),
                    "name": employee.get("name", ""),
                    "email": employee.get("email", ""),
                    "employee_id": employee.get("employee_id", ""),
                    "grade": employee.get("grade", ""),
                    "department": employee.get("department", "")
                }
            })
            
        except Exception:
            return jsonify({"found": False, "error": "Server error"}), 500
    
    @bp.route('/get-employees', methods=['GET'])
    def get_employees():
        """Get all employees with optional filters"""
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'message': 'Not authenticated'}), 403
        
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not check_pm_dashboard_access(user):
            return jsonify({'success': False, 'message': 'Not authorized'}), 403
        
        try:
            query = {"role": "Employee"}
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
        except Exception:
            return jsonify({
                'success': False,
                'message': f'Error fetching employees: {str(e)}'
            }), 500
    
    @bp.route('/get-categories', methods=['GET'])
    def get_categories():
        """Get PM categories"""
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'message': 'Not authenticated'}), 403
        
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not check_pm_dashboard_access(user):
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
        except Exception:
            return jsonify({
                'success': False,
                'message': f'Error fetching categories: {str(e)}'
            }), 500
    
    @bp.route('/get-employee/<employee_id>')
    def get_employee(employee_id):
        """Get single employee details"""
        user_id = session.get('user_id')
        
        if not user_id:
            return jsonify({"error": "Not authenticated"}), 401
        
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not check_pm_dashboard_access(user):
            return jsonify({"error": "Not authorized"}), 403
        
        try:
            # Use the validation function
            validation_result = validate_employee_for_award(employee_id)
            
            if not validation_result["valid"]:
                return jsonify({"error": validation_result["error"]}), 403
            
            employee = validation_result["employee"]
            
            # Get total points
            total_points = 0
            points_cursor = mongo.db.points.find({"user_id": ObjectId(employee_id)})
            for point in points_cursor:
                total_points += point["points"]
            
            # Return employee details
            return jsonify({
                "id": str(employee["_id"]),
                "name": employee.get("name", ""),
                "email": employee.get("email", ""),
                "employee_id": employee.get("employee_id", ""),
                "grade": employee.get("grade", ""),
                "department": employee.get("department", ""),
                "total_points": total_points,
                "current_quarter_count": validation_result["current_count"],
                "total_quarter_points": validation_result["total_quarter_points"],
                "expected_points": validation_result["expected_points"],
                "can_award": True  # Always allow awards
            })
            
        except Exception:
            return jsonify({"error": "Server error"}), 500