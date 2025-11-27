from flask import Blueprint, request, session, jsonify
from extensions import mongo
from datetime import datetime, timedelta
import sys
import traceback
from bson.objectid import ObjectId

employee_api_bp = Blueprint('employee_api', __name__, url_prefix='/employee')

def debug_print(message, data=None):
    pass

def error_print(message, error=None):
    pass

def get_current_fiscal_quarter_and_year(now_utc=None):
    if now_utc is None:
        now_utc = datetime.utcnow()
    
    current_month = now_utc.month
    current_calendar_year = now_utc.year
    
    if 1 <= current_month <= 3:
        fiscal_quarter = 4
        fiscal_year_start_calendar_year = current_calendar_year - 1
    elif 4 <= current_month <= 6:
        fiscal_quarter = 1
        fiscal_year_start_calendar_year = current_calendar_year
    elif 7 <= current_month <= 9:
        fiscal_quarter = 2
        fiscal_year_start_calendar_year = current_calendar_year
    else:
        fiscal_quarter = 3
        fiscal_year_start_calendar_year = current_calendar_year
    
    return fiscal_quarter, fiscal_year_start_calendar_year

def get_fiscal_period_date_range(fiscal_quarter, fiscal_year_start_calendar_year):
    if fiscal_quarter == 1:
        start_date = datetime(fiscal_year_start_calendar_year, 4, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 6, 30, 23, 59, 59, 999999)
    elif fiscal_quarter == 2:
        start_date = datetime(fiscal_year_start_calendar_year, 7, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 9, 30, 23, 59, 59, 999999)
    elif fiscal_quarter == 3:
        start_date = datetime(fiscal_year_start_calendar_year, 10, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 12, 31, 23, 59, 59, 999999)
    elif fiscal_quarter == 4:
        start_date = datetime(fiscal_year_start_calendar_year + 1, 1, 1)
        end_date = datetime(fiscal_year_start_calendar_year + 1, 3, 31, 23, 59, 59, 999999)
    else:
        raise ValueError("Invalid fiscal quarter")
    return start_date, end_date

def get_current_fiscal_year_date_range(fiscal_year_start_calendar_year):
    start_date = datetime(fiscal_year_start_calendar_year, 4, 1)
    end_date = datetime(fiscal_year_start_calendar_year + 1, 3, 31, 23, 59, 59, 999999)
    return start_date, end_date

def get_validator_details(validator_id):
    if not validator_id:
        return None
    try:
        validator_object_id = ObjectId(validator_id)
        validator = mongo.db.users.find_one({"_id": validator_object_id})
        if validator:
            return {
                "id": str(validator["_id"]),
                "name": validator.get("name", "Unknown Validator"),
                "email": validator.get("email", "N/A"),
                "manager_level": validator.get("manager_level", "N/A")
            }
        return None
    except Exception as e:
        error_print(f"Error fetching validator details for ID {validator_id}", e)
        return None

def determine_request_source(req, current_user_id):
    if req.get('ta_id'):
        return 'ta'
    elif req.get('created_by_pmo_id') or req.get('pmo_id'):
        return 'pmo'
    elif req.get('created_by_ld_id') or req.get('actioned_by_ld_id'):
        return 'ld'
    elif req.get('created_by_market_id'):
        return 'marketing'
    elif req.get('created_by_presales_id'):
        return 'presales'
    elif req.get('created_by') and req.get('created_by') != current_user_id:
        return 'manager'
    return 'employee'

@employee_api_bp.route('/get-current-points')
def get_current_points():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not authenticated'}), 401
    
    try:
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        total_points = 0
        total_bonus_points = 0
        processed_request_ids = set()
        
        now_utc = datetime.utcnow()
        current_fq, current_fyscy = get_current_fiscal_quarter_and_year(now_utc)
        q_start_date, q_end_date = get_fiscal_period_date_range(current_fq, current_fyscy)
        fy_start_date, fy_end_date = get_current_fiscal_year_date_range(current_fyscy)
        
        utilization_category = mongo.db.categories.find_one({"code": "utilization_billable"})
        utilization_category_id = utilization_category["_id"] if utilization_category else None
        
        quarterly_points = 0
        yearly_points = 0
        
        approved_requests = mongo.db.points_request.find({
            "user_id": ObjectId(user_id),
            "status": "Approved"
        })
        
        for req in approved_requests:
            processed_request_ids.add(req['_id'])
            if req.get('category_id') != utilization_category_id:
                points = req.get('points', 0)
                if req.get('is_bonus', False):
                    total_bonus_points += points
                else:
                    total_points += points
                
                req_date = req.get('request_date')
                if req_date:
                    if q_start_date <= req_date <= q_end_date:
                        quarterly_points += points
                    if fy_start_date <= req_date <= fy_end_date:
                        yearly_points += points
        
        points_entries = mongo.db.points.find({"user_id": ObjectId(user_id)})
        
        for point in points_entries:
            request_id = point.get('request_id')
            if request_id and request_id in processed_request_ids:
                continue
            
            if point.get('category_id') != utilization_category_id:
                points_val = point.get('points', 0)
                if point.get('is_bonus', False):
                    total_bonus_points += points_val
                else:
                    total_points += points_val
                
                award_date = point.get('award_date')
                if award_date:
                    if q_start_date <= award_date <= q_end_date:
                        quarterly_points += points_val
                    if fy_start_date <= award_date <= fy_end_date:
                        yearly_points += points_val
        
        quarterly_target = 5000
        yearly_target = 20000
        reward_config = mongo.db.reward_config.find_one({"_id": ObjectId("683edf40324c60f7d28ed197")})
        if reward_config and user.get('grade'):
            grade_targets = reward_config.get("grade_targets", {})
            user_grade = user.get('grade')
            if user_grade in grade_targets:
                quarterly_target = int(grade_targets[user_grade])
                yearly_target = quarterly_target * 4
        
        current_utilization = None
        if utilization_category:
            latest_utilization_req = mongo.db.points_request.find_one({
                "user_id": ObjectId(user_id),
                "status": "Approved",
                "category_id": utilization_category["_id"]
            }, sort=[("request_date", -1)])
            
            if latest_utilization_req and "utilization_value" in latest_utilization_req:
                util_value = latest_utilization_req.get("utilization_value")
                numeric_value = round(util_value * 100) if isinstance(util_value, (int, float)) else 0
                date_obj = latest_utilization_req.get("request_date")
                current_utilization = {
                    "numeric_value": numeric_value,
                    "date": date_obj.strftime('%b %Y') if date_obj else "N/A"
                }
        
        return jsonify({
            'total_points': total_points + total_bonus_points,
            'quarterly_points': quarterly_points,
            'yearly_points': yearly_points,
            'regular_points': total_points,
            'bonus_points': total_bonus_points,
            'quarterly_target': quarterly_target,
            'yearly_target': yearly_target,
            'current_utilization': current_utilization,
        })
    
    except Exception as e:
        error_print("Error fetching current points", e)
        return jsonify({'error': 'Server error'}), 500

@employee_api_bp.route('/get-request-history')
def get_request_history():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not authenticated'}), 401
    
    try:
        all_requests_unfiltered = []
        
        all_requests_cursor = mongo.db.points_request.find({
            "user_id": ObjectId(user_id)
        }).sort("request_date", -1)
        
        processed_request_ids = set()
        
        for req in all_requests_cursor:
            processed_request_ids.add(req['_id'])
            category = mongo.db.categories.find_one({"_id": req['category_id']})
            category_name = category['name'] if category else "Unknown Category"
            
            is_bonus_request = req.get('is_bonus', False) or (category and category.get('is_bonus', False))
            
            actioner_name_display = 'N/A'
            actioner_level_display = ''
            
            if req.get('status') != 'Pending' and req.get('processed_by'):
                processor_details = get_validator_details(req.get('processed_by'))
                if processor_details:
                    actioner_name_display = processor_details.get('name', 'N/A')
                    actioner_level_display = processor_details.get('manager_level', '')
            elif req.get('assigned_validator_id'):
                assigned_validator_details = get_validator_details(req.get('assigned_validator_id'))
                if assigned_validator_details:
                    actioner_name_display = assigned_validator_details.get('name', 'N/A')
                    actioner_level_display = assigned_validator_details.get('manager_level', '')
            
            source = 'employee'
            if req.get('ta_id'): source = 'ta'
            elif req.get('created_by_pmo_id') or req.get('pmo_id'): source = 'pmo'
            elif req.get('created_by_ld_id') or req.get('actioned_by_ld_id'): source = 'ld'
            elif req.get('created_by_market_id'): source = 'marketing'
            elif req.get('created_by_presales_id'): source = 'presales'
            elif req.get('created_by') and req.get('created_by') != ObjectId(user_id): source = 'manager'
            
            event_date = None
            if source == 'ld':
                metadata = req.get('metadata', {})
                if isinstance(metadata, dict) and 'event_date' in metadata:
                    event_date = metadata.get('event_date')
                elif 'event_date' in req:
                    event_date = req.get('event_date')
            elif source in ['ta', 'pmo']:
                event_date = req.get('event_date')
            
            debug_print(f"API: Processing request {req['_id']} from source '{source}'. Event date: {event_date}")
            
            milestone = None
            response_notes = req.get('response_notes', '')
            if "Milestone bonus:" in response_notes:
                milestone_parts = response_notes.split("Milestone bonus:")
                if len(milestone_parts) > 1:
                    milestone_info = milestone_parts[1].strip().split(" in ")[0]
                    milestone = milestone_info.strip()
            
            entry = {
                'id': str(req['_id']),
                'category_name': category_name,
                'points': req.get('points', 0),
                'status': req.get('status', 'N/A'),
                'request_date': req.get('request_date').isoformat() if req.get('request_date') else None,
                'event_date': event_date.isoformat() if event_date else None,
                'response_notes': response_notes,
                'submission_notes': req.get('request_notes', ''),
                'assigned_validator_name': actioner_name_display,
                'assigned_validator_level': actioner_level_display,
                'has_attachment': req.get('has_attachment', False),
                'attachment_filename': req.get('attachment_filename', ''),
                'source': source,
                'is_bonus': is_bonus_request,
                'milestone': milestone,
            }
            all_requests_unfiltered.append(entry)
        
        points_cursor = mongo.db.points.find({
            "user_id": ObjectId(user_id),
            "request_id": {"$nin": list(processed_request_ids)}
        })
        
        for point in points_cursor:
            category = mongo.db.categories.find_one({"_id": point['category_id']})
            
            actioner_name_display = 'N/A'
            actioner_level_display = ''
            source = 'manager'
            if point.get('awarded_by'):
                 awarder_details = get_validator_details(point['awarded_by'])
                 if awarder_details:
                     actioner_name_display = awarder_details.get('name', 'N/A')
                     actioner_level_display = awarder_details.get('manager_level', '')
                 
                 awarded_by_user = mongo.db.users.find_one({"_id": point['awarded_by']})
                 if awarded_by_user and awarded_by_user.get('role') == 'Central':
                     source = 'central'
            
            event_date = None
            if 'metadata' in point and isinstance(point['metadata'], dict) and 'event_date' in point['metadata']:
                source = 'ld'
                event_date = point['metadata']['event_date']
            elif 'event_date' in point:
                event_date = point['event_date']
                if not point.get('awarded_by'):
                    if 'ta_id' in point: source = 'ta'
                    elif 'pmo_id' in point: source = 'pmo'
            
            debug_print(f"API: Processing point {point['_id']} from source '{source}'. Event date: {event_date}")
            
            entry = {
                'id': str(point['_id']),
                'category_name': category['name'] if category else "Direct Award",
                'points': point.get('points', 0),
                'status': 'Approved',
                'request_date': point.get('award_date').isoformat() if point.get('award_date') else None,
                'event_date': event_date.isoformat() if event_date else None,
                'response_notes': point.get('notes', ''),
                'submission_notes': '',
                'assigned_validator_name': actioner_name_display,
                'assigned_validator_level': actioner_level_display,
                'has_attachment': point.get('has_attachment', False),
                'attachment_filename': point.get('attachment_filename', ''),
                'source': source,
                'is_bonus': point.get('is_bonus', False) or (category and category.get('is_bonus', False)),
            }
            all_requests_unfiltered.append(entry)
        
        all_requests_filtered = []
        for req in all_requests_unfiltered:
            if req.get('source') == 'employee':
                all_requests_filtered.append(req)
            elif req.get('status') == 'Approved':
                all_requests_filtered.append(req)
        
        pending_requests_filtered = [
            req for req in all_requests_filtered
            if req.get('source') == 'employee' and req.get('status') == 'Pending'
        ]
        
        all_requests_filtered.sort(key=lambda x: x.get('request_date') or '', reverse=True)
        
        return jsonify({
            'pending_requests': pending_requests_filtered,
            'all_requests': all_requests_filtered
        })
    
    except Exception as e:
        error_print("Error fetching request history for API", e)
        return jsonify({'error': 'Server error'}), 500

@employee_api_bp.route('/api/dashboard-updates')
def dashboard_updates():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        current_user_id = ObjectId(user_id)
        
        pending_count = mongo.db.points_request.count_documents({
            "user_id": current_user_id,
            "status": "Pending"
        })
        
        five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
        
        newly_processed_requests = list(mongo.db.points_request.find({
            "user_id": current_user_id,
            "status": {"$in": ["Approved", "Rejected"]},
            "user_notified": {"$ne": True},
            "$or": [
                {"processed_date": {"$gte": five_minutes_ago}},
                {"response_date": {"$gte": five_minutes_ago}},
                {"updated_at": {"$gte": five_minutes_ago}},
                {"_id": {"$gte": ObjectId.from_datetime(five_minutes_ago)}}
            ]
        }).sort("_id", -1))
        
        new_approvals = []
        new_rejections = []
        ids_to_mark_as_notified = []
        
        for req in newly_processed_requests:
            source = determine_request_source(req, current_user_id)
            
            category = mongo.db.categories.find_one({"_id": req['category_id']})
            category_name = category['name'] if category else "Unknown Category"
            category_code = category.get('code') if category else None
            
            points_value = req['points']
            notes_value = req.get('response_notes', f'Request {req["status"].lower()}')
            
            if category_code == 'utilization_billable':
                util_value = req.get('utilization_value')
                if isinstance(util_value, (int, float)):
                    points_value = round(util_value * 100)
                    if not req.get('response_notes'):
                         notes_value = f"Your billable utilization was updated to {points_value}%."
                else:
                    points_value = None
            
            processed_time = req.get('processed_date', req.get('response_date', req['_id'].generation_time))
            
            notification_data = {
                'id': str(req['_id']),
                'category': category_name,
                'points': points_value,
                'notes': notes_value,
            }
            
            if req['status'] == 'Approved':
                notification_data['approved_at'] = processed_time.isoformat()
                notification_data['unit'] = '%' if category_code == 'utilization_billable' else 'points'
                new_approvals.append(notification_data)
            
            elif req['status'] == 'Rejected':
                if source not in ['pmo', 'ta', 'ld']:
                    notification_data['rejected_at'] = processed_time.isoformat()
                    notification_data['unit'] = 'points'
                    new_rejections.append(notification_data)
            
            ids_to_mark_as_notified.append(req['_id'])
        
        if ids_to_mark_as_notified:
            mongo.db.points_request.update_many(
                {"_id": {"$in": ids_to_mark_as_notified}},
                {"$set": {"user_notified": True}}
            )
        
        recent_submissions = session.get('recent_submissions', [])
        unnotified_submissions = []
        if recent_submissions:
            for submission in recent_submissions:
                if not submission.get('notified', False):
                    unnotified_submissions.append(submission)
                    submission['notified'] = True
            if unnotified_submissions:
                session.modified = True
        
        last_request = mongo.db.points_request.find_one(
            {"user_id": current_user_id},
            sort=[("_id", -1)]
        )
        last_request_id = str(last_request['_id']) if last_request else None
        
        return jsonify({
            'pending_count': pending_count,
            'last_request_id': last_request_id,
            'new_approvals': new_approvals,
            'new_rejections': new_rejections,
            'new_submissions': unnotified_submissions,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    except Exception as e:

        return jsonify({'error': 'An internal server error occurred'}), 500

@employee_api_bp.route('/api/get-latest-utilization')
def get_latest_utilization():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        utilization_category = mongo.db.categories.find_one({"code": "utilization_billable"})
        if not utilization_category:
            return jsonify({'utilization': None})
        
        latest_utilization_req = mongo.db.points_request.find_one({
            "user_id": ObjectId(user_id),
            "status": "Approved",
            "category_id": utilization_category["_id"]
        }, sort=[("request_date", -1)])
        
        if latest_utilization_req and "utilization_value" in latest_utilization_req:
            util_value = latest_utilization_req.get("utilization_value")
            
            numeric_value = round(util_value * 100) if isinstance(util_value, (int, float)) else 0
            date_obj = latest_utilization_req.get("request_date")
            
            utilization_data = {
                "numeric_value": numeric_value,
                "date": date_obj.strftime('%b %Y') if date_obj else "N/A"
            }
            return jsonify({'utilization': utilization_data})
        else:
             return jsonify({'utilization': None})
    
    except Exception as e:
        error_print(f"Error fetching latest utilization data via API: {str(e)}")
        return jsonify({'error': 'Server error while fetching utilization'}), 500