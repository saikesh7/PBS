"""
PM/Arch API Module
RESTful API endpoints for AJAX calls and real-time updates
"""
from flask import request, session, jsonify
from extensions import mongo
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import logging

from .pmarch_main import pmarch_bp
from .pmarch_helpers import check_pmarch_access, get_pmarch_category_ids
from .services.request_service import RequestService

logger = logging.getLogger(__name__)

@pmarch_bp.route('/api/pending_requests', methods=['GET'])
@pmarch_bp.route('/validator/api/pending_requests', methods=['GET'])
def api_pending_requests():
    """API: Get all pending requests for the current user"""
    has_access, user = check_pmarch_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    user_id = user['_id']
    
    try:
        pmarch_category_ids = get_pmarch_category_ids()
        
        if not pmarch_category_ids:
            return jsonify({'success': False, 'pending_requests': []})
        
        pending_cursor = RequestService.get_pending_requests(user_id, pmarch_category_ids)
        
        pending_requests = []
        for req_data in pending_cursor:
            employee = RequestService.get_employee_by_id(req_data["user_id"])
            category = RequestService.get_category_by_id(req_data["category_id"])
            
            if not employee or not category:
                continue
            
            formatted = RequestService.format_request_for_display(req_data, employee, category)
            formatted['request_date'] = req_data["request_date"].strftime('%d-%m-%Y')
            pending_requests.append(formatted)
        
        return jsonify({'success': True, 'pending_requests': pending_requests})
    
    except Exception as e:
        logger.error(f"Error getting pending requests: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@pmarch_bp.route('/check-new-requests', methods=['GET'])
@pmarch_bp.route('/validator/check-new-requests', methods=['GET'])
def check_new_requests():
    """API: Check for new pending requests since last check"""
    has_access, user = check_pmarch_access()
    
    if not has_access:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    user_id = user['_id']
    
    try:
        pmarch_category_ids = get_pmarch_category_ids()
        
        if not pmarch_category_ids:
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
            "category_id": {"$in": pmarch_category_ids},
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
            employee = RequestService.get_employee_by_id(req_data["user_id"])
            category = RequestService.get_category_by_id(req_data["category_id"])
            
            if not employee or not category:
                continue
            
            formatted = RequestService.format_request_for_display(req_data, employee, category)
            new_requests.append(formatted)
        
        logger.debug(f"Found {len(new_requests)} new requests out of {pending_count} total pending")
        
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


@pmarch_bp.route('/fetch_employees', methods=['POST'])
def fetch_employees():
    """API: Fetch employees filtered by department and grade"""
    has_access, user = check_pmarch_access()
    
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


@pmarch_bp.route('/get_categories', methods=['GET'])
def get_categories():
    """API: Fetch all PM/Arch categories with full names"""
    try:
        # Get PM/Arch categories (value_add from categories collection)
        from .pmarch_helpers import get_pmarch_categories
        pmarch_categories = get_pmarch_categories()
        
        # Format categories for frontend
        formatted_categories = []
        for cat in pmarch_categories:
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


@pmarch_bp.route('/check-processed-updates', methods=['GET'])
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
            category = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
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
