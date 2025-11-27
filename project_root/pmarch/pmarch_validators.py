"""
PM/Arch Validators Module
Handles employee validation and lookup endpoints for PM/Arch dashboard
"""
from flask import request, session, jsonify
from extensions import mongo
from bson.objectid import ObjectId
from .pmarch_helpers import (
    check_pmarch_access,
    get_current_quarter_date_range,
    get_pmarch_category_ids
)
from .constants import GRADE_MINIMUM_EXPECTATIONS



def validate_employee_for_award(employee_id):
    """
    Validate if an employee can receive awards
    Returns validation result with employee details and quarterly info
    """
    try:
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        
        if not employee:
            return {
                "valid": False,
                "error": "Employee not found",
                "employee": None
            }
        
        # Get PM/Arch category IDs
        pmarch_category_ids = get_pmarch_category_ids()
        
        # Get quarter info
        quarter_start, quarter_end, quarter, year = get_current_quarter_date_range()
        
        # Calculate quarterly points
        quarter_points = 0
        quarter_count = 0
        
        if pmarch_category_ids:
            quarter_count = mongo.db.points.count_documents({
                "user_id": ObjectId(employee_id),
                "category_id": {"$in": pmarch_category_ids},
                "award_date": {"$gte": quarter_start, "$lt": quarter_end}
            })
            
            quarter_points_cursor = mongo.db.points.find({
                "user_id": ObjectId(employee_id),
                "category_id": {"$in": pmarch_category_ids},
                "award_date": {"$gte": quarter_start, "$lt": quarter_end}
            })
            
            for point in quarter_points_cursor:
                quarter_points += point["points"]
        
        # Get expected points
        grade = employee.get("grade", "Unknown")
        expected_points = GRADE_MINIMUM_EXPECTATIONS.get(grade, 0)
        
        return {
            "valid": True,
            "employee": employee,
            "current_count": quarter_count,
            "total_quarter_points": quarter_points,
            "expected_points": expected_points
        }
        
    except Exception:
        return {
            "valid": False,
            "error": "Server error during validation",
            "employee": None
        }

def register_validator_routes(bp):
    """Register all validator-related routes to the blueprint"""
    
    @bp.route('/validate-employee/<employee_id>')
    def validate_employee(employee_id):
        """Validate a single employee by ID"""
        has_access, user = check_pmarch_access()
        
        if not has_access:
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
            
        except Exception as e:
            return jsonify({"valid": False, "error": "Server error"}), 500
    
    @bp.route('/check-quarterly-info/<employee_id>')
    def check_quarterly_info(employee_id):
        """Check quarterly request information for an employee"""
        has_access, user = check_pmarch_access()
        
        if not has_access:
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
            
        except Exception as e:
            return jsonify({"error": "Server error"}), 500
    
    @bp.route('/find-employee-by-id/<employee_code>')
    def find_employee_by_id(employee_code):
        """Find employee by their employee ID code"""
        has_access, user = check_pmarch_access()
        
        if not has_access:
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
            
        except Exception as e:
            return jsonify({"found": False, "error": "Server error"}), 500
    

    @bp.route('/get-employee/<employee_id>')
    def get_employee(employee_id):
        """Get single employee details"""
        has_access, user = check_pmarch_access()
        
        if not has_access:
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
            
        except Exception as e:
            return jsonify({"error": "Server error"}), 500
