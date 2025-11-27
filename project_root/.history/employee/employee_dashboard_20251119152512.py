from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, send_file
from werkzeug.utils import secure_filename
import uuid
from extensions import mongo
from datetime import datetime, timedelta
import os
import traceback
import sys
from bson.objectid import ObjectId
from collections import defaultdict
from dashboard_config import get_user_dashboard_configs

current_dir = os.path.dirname(os.path.abspath(__file__))

employee_dashboard_bp = Blueprint('employee_dashboard', __name__, url_prefix='/employee',
                                 template_folder=os.path.join(current_dir, 'templates'),
                                 static_folder=os.path.join(current_dir, 'static'),
                                 static_url_path='/employee/static')

PRESALES_CATEGORY_CODES = ['presales_e2e', 'presales_partial', 'presales_adhoc']

def debug_print(message, data=None):
    pass

def error_print(message, error=None):
    pass

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
                "dashboard_access": validator.get("dashboard_access", [])
            }
        return None
    except Exception as e:
        error_print(f"Error fetching validator details for ID {validator_id}", e)
        return None

def get_validator_by_id_for_template(validator_id_str):
    if isinstance(validator_id_str, ObjectId):
        validator_id_str = str(validator_id_str)
    return get_validator_details(validator_id_str)

def get_milestone_display_order(milestone):
    name = milestone.get('name', '')
    if name.startswith('Milestone ') and len(name.split(' ')) > 1:
        try:
            return int(name.split(' ')[1])
        except ValueError:
            return float('inf')
    return float('inf')

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

def get_manager_info(user):
    try:
        if not user or 'manager_id' not in user or not user['manager_id']:
            return None
        
        manager = mongo.db.users.find_one({"_id": ObjectId(user['manager_id'])})
        if not manager:
            return None
        
        return {
            "id": str(manager["_id"]),
            "name": manager.get("name", "Unknown"),
            "dashboard_access": manager.get("dashboard_access", [])
        }
    except Exception as e:
        error_print(f"Error getting manager info: {str(e)}")
        return None

def check_reward_eligibility(user_id, category_id):
    try:
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            return False, "Employee not found"
        
        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        if not category:
            return False, "Reward category not found"
        
        employee_grade = user.get('grade')
        if not employee_grade:
            return False, "Employee grade not found"
        
        grade_limits = category.get('grade_limits', {})
        if employee_grade not in grade_limits:
            return False, f"Your grade ({employee_grade}) is not eligible for this category"
        
        grade_points = category.get('grade_points', {}).get(employee_grade, 0)
        if grade_points <= 0:
            return False, f"Your grade ({employee_grade}) cannot submit requests for this category"
        
        return True, {
            "min_points": grade_points,
            "points_per_unit": category.get('points_per_unit', 0)
        }
    except Exception as e:
        error_print("Error checking reward eligibility", e)
        return False, f"Error checking reward eligibility: {str(e)}"

def send_new_request_notification(request_data, employee, validator, category):
    try:
        from employee_notifications import send_email_notification
        from jinja2 import Template
        
        submission_date = request_data['request_date'].strftime('%B %d, %Y at %I:%M %p')
        
        base_url = request.url_root.rstrip('/')
        dashboard_url = base_url + url_for('auth.login')
        
        # Determine validator's dashboard URL based on dashboard_access
        dashboard_access = validator.get('dashboard_access', [])
        if 'pm' in dashboard_access:
            dashboard_url = base_url + url_for('pm.dashboard')
        elif 'pm_arch' in dashboard_access:
            dashboard_url = base_url + url_for('pm_arch.dashboard')
        elif 'presales' in dashboard_access:
            dashboard_url = base_url + url_for('presales.dashboard')
        elif 'marketing' in dashboard_access:
            dashboard_url = base_url + url_for('market_manager.dashboard')
        
        template_vars = {
            'validator_name': validator.get('name', 'Validator'),
            'employee_name': employee.get('name', 'Unknown'),
            'employee_grade': employee.get('grade', 'N/A'),
            'employee_department': employee.get('department', 'N/A'),
            'category_name': category.get('name', 'Unknown Category'),
            'points': request_data.get('points', 0),
            'submission_date': submission_date,
            'notes': request_data.get('request_notes', ''),
            'has_attachment': request_data.get('has_attachment', False),
            'attachment_filename': request_data.get('attachment_filename', ''),
            'dashboard_url': dashboard_url
        }
        
        html_template = '''<!DOCTYPE html>
        <html>
        <head><style>
            body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
            .container { max-width: 600px; margin: 0 auto; padding: 20px; }
            .header { background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
            .content { background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }
            .button { display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; }
            .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
            .info-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            .info-table td { padding: 8px; border-bottom: 1px solid #ddd; }
            .info-table td:first-child { font-weight: bold; width: 40%; }
        </style></head>
        <body>
            <div class="container">
                <div class="header"><h2>New Points Request for Validation</h2></div>
                <div class="content">
                    <p>Dear {{ validator_name }},</p>
                    <p>You have received a new points request that requires your validation:</p>
                    <table class="info-table">
                        <tr><td>Employee Name:</td><td>{{ employee_name }}</td></tr>
                        <tr><td>Employee Grade:</td><td>{{ employee_grade }}</td></tr>
                        <tr><td>Department:</td><td>{{ employee_department }}</td></tr>
                        <tr><td>Category:</td><td>{{ category_name }}</td></tr>
                        <tr><td>Points Requested:</td><td>{{ points }}</td></tr>
                        <tr><td>Submission Date:</td><td>{{ submission_date }}</td></tr>
                        {% if has_attachment %}
                        <tr><td>Attachment:</td><td>Yes ({{ attachment_filename }})</td></tr>
                        {% endif %}
                    </table>
                    {% if notes %}
                    <h3>Employee's Notes:</h3>
                    <p style="background-color: #fff; padding: 10px; border-left: 3px solid #4CAF50;">{{ notes }}</p>
                    {% endif %}
                    <p>Please log in to the system to review and process this request.</p>
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="{{ dashboard_url }}" class="button" style="color: #ffff; text-decoration: none;">Go to Dashboard</a></center>
                </div>
                <div class="footer"><p>This is an automated notification from the Employee Recognition System.</p></div>
            </div>
        </body>
        </html>'''
        
        html_content = Template(html_template).render(**template_vars)
        
        text_content = f"""
Dear {template_vars['validator_name']},

You have received a new points request that requires your validation:

Employee Name: {template_vars['employee_name']}
Employee Grade: {template_vars['employee_grade']}
Department: {template_vars['employee_department']}
Category: {template_vars['category_name']}
Points Requested: {template_vars['points']}
Submission Date: {template_vars['submission_date']}

{'Employee Notes: ' + template_vars['notes'] if template_vars['notes'] else ''}

Please log in to the system to review and process this request.

Dashboard URL: {template_vars['dashboard_url']}

This is an automated notification from the Employee Recognition System.
        """
        
        validator_email = validator.get('email')
        if validator_email:
            subject = f"New Points Request from {employee.get('name', 'Employee')} - {category.get('name', 'Category')}"
            return send_email_notification(
                validator_email,
                validator.get('name', 'Validator'),
                subject,
                html_content,
                text_content
            )
        else:
            debug_print(f"No email address found for validator {validator.get('name')}")
            return False
    
    except Exception as e:
        error_print("Failed to send new request notification", e)
        return False

@employee_dashboard_bp.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    PRESALES_CATEGORY_CODES = ['presales_e2e', 'presales_partial', 'presales_adhoc']
    
    category_codes_to_fetch = [
        "value_add", "initiative_ai", "mentoring",
        "mindshare", "interviews"
    ] + PRESALES_CATEGORY_CODES
    
    user_id = session.get('user_id')
    debug_print(f"Dashboard accessed by user ID: {user_id}")
    
    # ✅ INITIALIZE ALL TEMPLATE VARIABLES AT THE TOP
    user = None
    categories = []
    template_categories = []  # ✅ CRITICAL FIX
    pending_requests = []
    request_history = []
    total_points = 0
    total_bonus_points = 0
    current_quarter_total_points = 0
    current_year_total_points = 0
    manager = None
    missing_validators_details = []
    grade_targets_from_db = {}
    milestones_from_db = []
    quarterly_target = 0
    yearly_target = 0
    quarterly_percentage = 0.0
    yearly_percentage = 0.0
    user_profile_pic_url = None
    current_utilization = None
    pmo_awards = []
    ta_awards = []
    ld_awards = []
    employee_submitted_history = []
    user_dashboards = []
    other_dashboards = []
    leaderboard_filters_options = {
        'distinct_departments': [],
        'distinct_grades': [],
        'leaderboard_categories': [],
        'distinct_quarters': []
    }
    initial_leaderboard_data = {}
    utilization_records = []
    average_utilization = 0.0
    utilization_months = []
    
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'gif', 'txt'}
    
    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
    try:
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            flash('You need to log in first', 'warning')
            return redirect(url_for('auth.login'))
        
        # No role checks - all authenticated users can access employee dashboard
        
        
        
        if user and user.get('manager_id'):
            manager = get_manager_info(user)
            debug_print(f"User's manager: {manager['name'] if manager else 'None'}")
        else:
            debug_print("No manager found for this user")
        
        # Check for missing validators
        validator_fields_for_warning = {
            "PM/Arch Validator": "pm_arch_validator_id",
            "PM Validator": "pm_validator_id",
            "Marketing Validator": "marketing_validator_id",
            "Pre-sales Validator": "presales_validator_id"
        }
        for name, field_key in validator_fields_for_warning.items():
            if not user.get(field_key):
                missing_validators_details.append(name)
        
        try:
            categories_from_db = list(mongo.db.categories.find({
                "category_type": "employee_raised",
                "active": True
            }).sort("name", 1))
            debug_print(f"Raw employee_raised categories from DB ({len(categories_from_db)}): {[cat.get('name') for cat in categories_from_db]}")
            
            for cat_doc in categories_from_db:
                current_category_for_template = cat_doc.copy()
                current_category_for_template['contribution_types'] = cat_doc.get('contribution_types', [])
                template_categories.append(current_category_for_template)
            
            if not template_categories:
                debug_print("WARNING: No employee_raised categories found.")
        
        except Exception as e:
            error_print("Failed to fetch categories", e)
            flash('Unable to load categories. Please contact support.', 'danger')
            template_categories = []
        
        processed_request_ids = set()
        
        try:
            all_requests_cursor = mongo.db.points_request.find({
                "user_id": ObjectId(user_id),
                "$or": [
                    {"created_by": ObjectId(user_id)},
                    {"ta_id": {"$exists": True}}
                ]
            }).sort("request_date", -1)
            
            for req in all_requests_cursor:
                category = mongo.db.categories.find_one({"_id": req['category_id']})
                category_name = category['name'] if category else "Unknown Category"
                
                is_ta_awarded_interview = bool(req.get('ta_id'))
                if is_ta_awarded_interview and req.get('status') == 'Pending':
                    continue
                
                is_bonus_request = req.get('is_bonus', False)
                if not is_bonus_request and category and category.get('is_bonus', False):
                    is_bonus_request = True
                
                employee_submission_notes = req.get('request_notes', '')
                manager_feedback_notes = req.get('response_notes', '')
                
                if is_ta_awarded_interview:
                    history_display_notes = employee_submission_notes
                elif req.get('status') == 'Pending':
                    history_display_notes = employee_submission_notes
                elif req.get('status') != 'Pending' and manager_feedback_notes:
                    history_display_notes = manager_feedback_notes
                else:
                    history_display_notes = employee_submission_notes
                
                milestone = None
                notes_to_check_for_milestone = history_display_notes
                if "Milestone bonus" in notes_to_check_for_milestone:
                    milestone_parts = notes_to_check_for_milestone.split("Milestone bonus")
                    if len(milestone_parts) > 1:
                        milestone_info = milestone_parts[1].strip(": ")
                        milestone = milestone_info.split(" in ")[0] if " in " in milestone_info else milestone_info
                
                actioner_name_display = 'N/A'
                actioner_dashboard_access = []
                
                if req.get('status') != 'Pending' and req.get('processed_by'):
                    processor_details = get_validator_details(req.get('processed_by'))
                    if processor_details:
                        actioner_name_display = processor_details.get('name', 'N/A')
                        actioner_dashboard_access = processor_details.get('dashboard_access', [])
                elif req.get('assigned_validator_id'):
                    assigned_validator_details = get_validator_details(req.get('assigned_validator_id'))
                    if assigned_validator_details:
                        actioner_name_display = assigned_validator_details.get('name', 'N/A')
                        actioner_dashboard_access = assigned_validator_details.get('dashboard_access', [])
                
                source = 'employee'
                if req.get('ta_id'):
                    source = 'ta'
                elif req.get('created_by_pmo_id') or req.get('pmo_id'):
                    source = 'pmo'
                elif req.get('created_by_ld_id') or req.get('actioned_by_ld_id'):
                    source = 'ld'
                elif req.get('created_by_market_id'):
                    source = 'marketing'
                elif req.get('created_by_presales_id'):
                    source = 'presales'
                elif req.get('created_by') and req.get('created_by') != ObjectId(user_id):
                    if is_bonus_request and "Milestone bonus" in req.get('response_notes', ""):
                        source = 'central'
                    else:
                        source = 'manager'
                elif not req.get('created_by') and req.get('manager_id') and req.get('manager_id') != ObjectId(user_id):
                    source = 'manager'
                
                event_date = None
                if source == 'ld':
                    event_date = req.get('metadata', {}).get('event_date')
                elif source in ['ta', 'pmo']:
                    event_date = req.get('event_date')
                
                debug_print(f"Processing request {req['_id']} from source '{source}'. Found event date: {event_date}")
                
                entry = {
                    'id': req['_id'],
                    'category_id': req['category_id'],
                    'category_name': category_name,
                    'points': req['points'],
                    'status': req['status'],
                    'request_date': req['request_date'],
                    'event_date': event_date,
                    'submission_notes': employee_submission_notes,
                    'response_notes': history_display_notes,
                    'assigned_validator_name': actioner_name_display,
                    'assigned_validator_dashboard_access': actioner_dashboard_access,
                    'has_attachment': req.get('has_attachment', False),
                    'attachment_filename': req.get('attachment_filename', ''),
                    'source': source,
                    'is_bonus': is_bonus_request,
                    'milestone': milestone,
                    'interviews_count': req.get('interviews_count', 0)
                }
                
                include_in_history = True
                if source in ['ta', 'pmo', 'ld'] and req.get('status') == 'Rejected':
                    pass
                
                if include_in_history:
                    request_history.append(entry)
                
                if req['status'] == 'Pending':
                    pending_requests.append(entry)
                
                if req['status'] == 'Approved':
                    if is_bonus_request:
                        total_bonus_points += req['points']
                    else:
                        if not (category and (category.get("code") == "utilization_billable" or category.get("name") == "Utilization/Billable")):
                            total_points += req['points']
                    processed_request_ids.add(req['_id'])
            
            debug_print(f"Phase 1 (points_request processing): total_points={total_points}, total_bonus_points={total_bonus_points}, processed_ids_count={len(processed_request_ids)}")
        
        except Exception as e:
            error_print("Failed to fetch employee requests", e)
        
        try:
            points_cursor = mongo.db.points.find({"user_id": ObjectId(user_id)})
            
            for point in points_cursor:
                point_request_id = point.get('request_id')
                if point_request_id and point_request_id in processed_request_ids:
                    debug_print(f"Skipping point entry {point['_id']} as its linked request_id {point_request_id} was already processed from points_request.")
                    continue
                
                category = mongo.db.categories.find_one({"_id": point['category_id']})
                category_name = category['name'] if category else "Unknown Category"
                is_point_bonus = point.get('is_bonus', False) or (category and category.get('is_bonus', False))
                
                is_bonus = point.get('is_bonus', False)
                if not is_bonus and category and category.get('is_bonus', False):
                    is_bonus = True
                
                milestone = None
                notes = point.get("notes", "")
                if "Milestone bonus" in notes:
                    milestone_parts = notes.split("Milestone bonus")
                    if len(milestone_parts) > 1:
                        milestone_info = milestone_parts[1].strip(": ")
                        milestone = milestone_info.split(" in ")[0] if " in " in milestone_info else milestone_info
                
                point_source = 'hr_direct_award'
                if point.get('awarded_by'):
                    awarded_by_user = mongo.db.users.find_one({"_id": point['awarded_by']})
                    if awarded_by_user:
                        dashboard_access = awarded_by_user.get('dashboard_access', [])
                        if 'central' in dashboard_access:
                            point_source = 'central'
                        elif 'hr' in dashboard_access:
                            point_source = 'hr'
                        else:
                            point_source = 'manager'
                
                award_date = point.get('award_date', point.get('request_date'))
                
                event_date = None
                if 'metadata' in point and 'event_date' in point['metadata']:
                    point_source = 'ld'
                    event_date = point['metadata']['event_date']
                elif 'event_date' in point:
                    event_date = point['event_date']
                
                if not isinstance(event_date, datetime):
                    debug_print(f"Invalid event_date found for point {point['_id']}: {event_date}. Setting to None.")
                    event_date = None
                
                debug_print(f"Processing point {point['_id']} from source '{point_source}'. Found event date: {event_date}")
                
                if award_date:
                    entry = {
                        'id': point['_id'],
                        'category_id': point['category_id'],
                        'category_name': category_name,
                        'points': point['points'],
                        'status': 'Approved',
                        'request_date': award_date,
                        'event_date': event_date,
                        'response_notes': point.get('notes', 'Points awarded'),
                        'has_attachment': point.get('has_attachment', False),
                        'attachment_filename': point.get('attachment_filename', ''),
                        'source': point_source,
                        'is_bonus': is_point_bonus,
                        'milestone': milestone
                    }
                    request_history.append(entry)
                    
                    if is_point_bonus:
                        total_bonus_points += point['points']
                    elif not (category and (category.get("code") == "utilization_billable" or category.get("name") == "Utilization/Billable")):
                        total_points += point['points']
            
            bonus_cursor = mongo.db.points_request.find({
                "user_id": ObjectId(user_id),
                "status": "Approved",
                "is_bonus": True,
                "_id": {"$nin": list(processed_request_ids)}
            })
            
            for bonus in bonus_cursor:
                category = mongo.db.categories.find_one({"_id": bonus['category_id']})
                category_name = category['name'] if category else "Bonus Points"
                
                milestone = None
                notes = bonus.get("response_notes", "")
                if "Milestone bonus" in notes:
                    milestone_parts = notes.split("Milestone bonus")
                    if len(milestone_parts) > 1:
                        milestone_info = milestone_parts[1].strip(": ")
                        milestone = milestone_info.split(" in ")[0] if " in " in milestone_info else milestone_info
                
                bonus_date = bonus.get('request_date')
                if bonus_date:
                    entry = {
                        'id': bonus['_id'],
                        'category_id': bonus['category_id'],
                        'category_name': category_name,
                        'points': bonus['points'],
                        'status': 'Approved',
                        'request_date': bonus_date,
                        'event_date': None,
                        'response_notes': notes,
                        'has_attachment': bonus.get('has_attachment', False),
                        'attachment_filename': bonus.get('attachment_filename', ''),
                        'source': 'central',
                        'is_bonus': True,
                        'milestone': milestone
                    }
                    request_history.append(entry)
                    total_bonus_points += bonus['points']
            
            debug_print(f"Phase 2 (points and other bonus_requests processing): total_points={total_points}, total_bonus_points={total_bonus_points}")
            request_history.sort(key=lambda x: x.get('request_date', datetime.min), reverse=True)
        
        except Exception as e:
            error_print("Failed to fetch manager/central awards", e)
        
        filtered_request_history = [
            req for req in request_history
            if not (
                req.get('status') == 'Rejected' and
                req.get('source') in ['ta', 'pmo', 'ld']
            )
        ]
        
        employee_submitted_history = [
            req for req in filtered_request_history
            if req.get('source') == 'employee'
        ]
        
        request_history = filtered_request_history
        
        pmo_awards = [req for req in request_history if req.get('source') == 'pmo' and req.get('status') == 'Approved']
        ta_awards = [req for req in request_history if req.get('source') == 'ta' and req.get('status') == 'Approved']
        ld_awards = [req for req in request_history if req.get('source') == 'ld' and req.get('status') == 'Approved']
        
        now_utc = datetime.utcnow()
        current_fq, current_fyscy = get_current_fiscal_quarter_and_year(now_utc)
        
        q_start_date, q_end_date = get_fiscal_period_date_range(current_fq, current_fyscy)
        fy_start_date, fy_end_date = get_current_fiscal_year_date_range(current_fyscy)
        
        debug_print(f"Current Fiscal Quarter: Q{current_fq} of FY starting {current_fyscy}",
                    {"Q Start": q_start_date, "Q End": q_end_date})
        debug_print(f"Current Fiscal Year: FY starting {current_fyscy}",
                    {"FY Start": fy_start_date, "FY End": fy_end_date})
        
        # ✅ Calculate current quarter and year totals correctly
        for hist_entry in request_history:
            if hist_entry.get('status') == 'Approved' and isinstance(hist_entry.get('request_date'), datetime):
                entry_date = hist_entry['request_date']
                entry_points_value = hist_entry.get('points', 0)
                
                # ✅ Fetch category properly
                category_doc_for_hist = None
                if 'category_id' in hist_entry:
                    category_doc_for_hist = mongo.db.hr_categories.find_one({"_id": hist_entry['category_id']})
                    if not category_doc_for_hist:
                        category_doc_for_hist = mongo.db.categories.find_one({"_id": hist_entry['category_id']})
                else:
                    category_doc_for_hist = mongo.db.hr_categories.find_one({"name": hist_entry.get('category_name')})
                    if not category_doc_for_hist:
                        category_doc_for_hist = mongo.db.categories.find_one({"name": hist_entry.get('category_name')})
                
                is_utilization_hist_entry = False
                if category_doc_for_hist and (category_doc_for_hist.get("code") == "utilization_billable" or category_doc_for_hist.get("name") == "Utilization/Billable"):
                    is_utilization_hist_entry = True
                
                # ✅ Don't include bonus points in regular totals
                is_bonus_entry = hist_entry.get('is_bonus', False)
                
                if not is_utilization_hist_entry and not is_bonus_entry and hist_entry.get('status') == 'Approved':
                    if q_start_date <= entry_date <= q_end_date:
                        current_quarter_total_points += entry_points_value
                    if fy_start_date <= entry_date <= fy_end_date:
                        current_year_total_points += entry_points_value
        
        if request.method == 'POST':
            try:
                from gridfs import GridFS
                
                category_id = request.form.get('category_id')
                notes = request.form.get('notes', '')
                
                attachment = request.files.get('attachment')
                attachment_filename = None
                attachment_id = None
                
                if attachment and attachment.filename:
                    if not allowed_file(attachment.filename):
                        flash('File type not allowed. Please upload PDF, DOC, DOCX, XLS, XLSX, JPG, JPEG, PNG, GIF, or TXT files.', 'danger')
                        return redirect(url_for('employee_dashboard.dashboard'))
                    
                    if attachment.content_length and attachment.content_length > MAX_CONTENT_LENGTH:
                        flash('File too large. Maximum file size is 5MB.', 'danger')
                        return redirect(url_for('employee_dashboard.dashboard'))
                    
                    secure_name = secure_filename(attachment.filename)
                    original_filename = secure_name
                    file_extension = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
                    unique_filename = f"{uuid.uuid4().hex}.{file_extension}" if file_extension else f"{uuid.uuid4().hex}"
                    
                    fs = GridFS(mongo.db)
                    
                    with fs.new_file(
                        filename=unique_filename,
                        content_type=attachment.content_type,
                        metadata={
                            'original_filename': original_filename,
                            'user_id': user_id,
                            'upload_date': datetime.utcnow()
                        }
                    ) as f:
                        f.write(attachment.read())
                        attachment_id = f._id
                    
                    attachment_filename = original_filename
                    debug_print(f"File uploaded: {original_filename}, stored as: {unique_filename}, ID: {attachment_id}")
                
                if not category_id:
                    flash('Please select a category', 'danger')
                    return redirect(url_for('employee_dashboard.dashboard'))
                
                category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
                
                if not category:
                    flash('Invalid category selected', 'danger')
                    return redirect(url_for('employee_dashboard.dashboard'))
                
                employee_grade = user.get('grade')
                if not employee_grade:
                    flash('Your employee profile does not have a grade assigned. Please contact HR.', 'danger')
                    return redirect(url_for('employee_dashboard.dashboard'))
                
                can_request, result = check_reward_eligibility(user_id, category_id)
                
                if not can_request:
                    flash(result, 'danger')
                    return redirect(url_for('employee_dashboard.dashboard'))
                
                points_per_unit = category.get('points_per_unit', 0)
                
                if points_per_unit <= 0:
                    flash(f'This category does not have points configured', 'danger')
                    return redirect(url_for('employee_dashboard.dashboard'))
                
                validator = category.get('validator', '')
                is_bonus = category.get('is_bonus', False)
                
                new_request = {
                    "user_id": ObjectId(user_id),
                    "category_id": ObjectId(category_id),
                    "points": points_per_unit,
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "request_notes": notes,
                    "validator": validator,
                    "created_by": ObjectId(user_id),
                    "is_bonus": is_bonus,
                    "has_attachment": attachment_id is not None,
                    "attachment_id": attachment_id,
                    "attachment_filename": attachment_filename,
                    "assigned_validator_id": None,
                    "source": "employee"
                }
                
                selected_validator_id = request.form.get('selected_validator_id')
                validator_type_from_category = category.get('validator', '')
                
                debug_print(f"Employee {user.get('name')} (ID: {user_id}, Grade: {employee_grade}) submitting for category '{category['name']}'.")
                debug_print(f"  Category's designated validator type: {validator_type_from_category}")
                debug_print(f"  Selected validator ID from form: {selected_validator_id}")
                
                if not selected_validator_id:
                    flash('Please select a validator for this request', 'danger')
                    return redirect(url_for('employee_dashboard.dashboard'))
                
                try:
                    validator_user = mongo.db.users.find_one({"_id": ObjectId(selected_validator_id), "active": True})
                    if not validator_user:
                        flash('Selected validator not found', 'danger')
                        return redirect(url_for('employee_dashboard.dashboard'))
                    
                    dashboard_access = validator_user.get('dashboard_access', [])
                    required_access = [
                        f"{validator_type_from_category} - Validator",
                        f"{validator_type_from_category} - Updater",
                        validator_type_from_category.lower()
                    ]
                    
                    has_access = any(access in dashboard_access for access in required_access)
                    
                    if not has_access:
                        flash('Selected user does not have validator access for this category', 'danger')
                        return redirect(url_for('employee_dashboard.dashboard'))
                    
                    new_request["assigned_validator_id"] = ObjectId(selected_validator_id)
                    specific_assigned_validator_id = selected_validator_id
                    debug_print(f"  Request's 'assigned_validator_id' SET TO: {new_request['assigned_validator_id']}")
                
                except Exception as e:
                    error_print(f"Error validating selected validator: {str(e)}")
                    flash('Error processing selected validator', 'danger')
                    return redirect(url_for('employee_dashboard.dashboard'))
                
                result = mongo.db.points_request.insert_one(new_request)
                new_request_id = result.inserted_id

                from services.realtime_events import publish_request_raised
                new_request['_id'] = new_request_id
                validator_user = mongo.db.users.find_one({"_id": ObjectId(selected_validator_id)})
                if validator_user:
                    publish_request_raised(new_request, user, validator_user, category)
                
                if 'recent_submissions' not in session:
                    session['recent_submissions'] = []
                
                submission_info = {
                    'id': str(new_request_id),
                    'category': category['name'],
                    'points': points_per_unit,
                    'timestamp': datetime.utcnow().isoformat(),
                    'notified': False
                }
                session['recent_submissions'].append(submission_info)
                session['recent_submissions'] = session['recent_submissions'][-10:]
                session.modified = True
                
                if specific_assigned_validator_id:
                    try:
                        validator_user = mongo.db.users.find_one({"_id": ObjectId(specific_assigned_validator_id)})
                        if validator_user and validator_user.get('email'):
                            email_sent = send_new_request_notification(
                                new_request,
                                user,
                                validator_user,
                                category
                            )
                            if email_sent:
                                debug_print(f"Email notification sent to validator {validator_user.get('name')}")
                            else:
                                debug_print(f"Failed to send email notification to validator {validator_user.get('name')}")
                        else:
                            debug_print(f"Validator found but no email address available")
                    except Exception as e:
                        error_print(f"Email notification error: {str(e)}")
                
                frequency = category.get('frequency', 'Quarterly')
                if frequency.lower() == 'monthly':
                    period_text = "month"
                else:
                    period_text = "quarter"
                
                flash(f'Your request for {points_per_unit} points in {category["name"]} has been submitted!', 'success')
                
                return redirect(url_for('employee_dashboard.dashboard'))
            
            except Exception as e:
                error_print("Failed to create point request", e)
                flash(f'An error occurred while submitting your request: {str(e)}', 'danger')
                return redirect(url_for('employee_dashboard.dashboard'))
    
    except Exception as e:
        error_print("Dashboard error", e)
        flash('An error occurred while loading the dashboard. Please try again later.', 'danger')
        if not user:
            return redirect(url_for('auth.login'))
    
    reward_config_doc_id = "683edf40324c60f7d28ed197"
    reward_config = mongo.db.reward_config.find_one({"_id": ObjectId(reward_config_doc_id)})
    
    if reward_config:
        grade_targets_from_db = reward_config.get("grade_targets", {})
        milestones_from_db = reward_config.get("milestones", [])
        milestones_from_db = sorted(milestones_from_db, key=get_milestone_display_order)
        debug_print("Successfully fetched reward_config from DB for dashboard.", {"grade_targets_count": len(grade_targets_from_db), "milestones_count": len(milestones_from_db)})
    else:
        debug_print(f"Reward config with ID {reward_config_doc_id} not found for dashboard. Using empty defaults.")
        flash(f"Critical: Reward configuration not found (ID: {reward_config_doc_id}). Points target display may be affected. Please contact admin.", "warning")
    
    user_grade = user.get('grade')
    if user_grade and user_grade in grade_targets_from_db:
        quarterly_target = int(grade_targets_from_db[user_grade])
        yearly_target = quarterly_target * 4
        
        if quarterly_target > 0:
            quarterly_percentage = (current_quarter_total_points / quarterly_target) * 100
        if yearly_target > 0:
            yearly_percentage = (current_year_total_points / yearly_target) * 100
    
    profile_filename = user.get("profile_pic")
    user_profile_pic_url = url_for('employee_dashboard.static', filename=f'uploads/profile_pics/{profile_filename}') if profile_filename else None
    
    now = datetime.utcnow()
    start_of_month = datetime(now.year, now.month, 1)
    
    if now.month == 12:
        end_of_month = datetime(now.year + 1, 1, 1) - timedelta(microseconds=1)
    else:
        end_of_month = datetime(now.year, now.month + 1, 1) - timedelta(microseconds=1)
    
    # Check hr_categories FIRST (where PMO categories are stored)
    utilization_category = mongo.db.hr_categories.find_one({
        "$or": [
            {"code": "utilization_billable"},
            {"name": "Utilization/Billable"}
        ]
    })
    
    if not utilization_category:
        utilization_category = mongo.db.categories.find_one({
            "$or": [
                {"code": "utilization_billable"},
                {"name": "Utilization/Billable"}
            ]
        })
    
    if utilization_category:
        utilization_record = mongo.db.points.find_one({
            "user_id": user["_id"],
            "category_id": utilization_category["_id"],
            "award_date": {
                "$gte": start_of_month,
                "$lte": end_of_month
            }
        })
        if utilization_record:
            current_utilization = {
                "numeric_value": utilization_record.get("points", 0),
                "date": utilization_record.get("award_date")
            }
        else:
            current_utilization = {
                "numeric_value": 0,
                "date": now
            }
    else:
        current_utilization = {
            "numeric_value": 0,
            "date": now
        }
    
    # Import leaderboard functions
    try:
        from .employee_leaderboard import get_leaderboard_filter_options, get_leaderboard_data_with_rank
        leaderboard_filters_options = get_leaderboard_filter_options()
        initial_leaderboard_data = get_leaderboard_data_with_rank(str(user_id), {'quarter': 'all'})
    except Exception as e:
        error_print("Error loading leaderboard", e)
        leaderboard_filters_options = {
            'distinct_departments': [],
            'distinct_grades': [],
            'leaderboard_categories': [],
            'distinct_quarters': []
        }
        initial_leaderboard_data = {}
    
    # Fetch utilization data

    try:

        # Get utilization category - CHECK HR_CATEGORIES FIRST (where PMO categories are)
        utilization_category = mongo.db.hr_categories.find_one({
            "$or": [
                {"name": "Utilization/Billable"},
                {"name": {"$regex": "utilization", "$options": "i"}}
            ]
        })
        
        if not utilization_category:
            # Fallback to categories collection if not found in hr_categories
            utilization_category = mongo.db.categories.find_one({
                "$or": [
                    {"name": "Utilization/Billable"},
                    {"name": {"$regex": "utilization", "$options": "i"}}
                ]
            })
        
        if utilization_category:
            # Fetch all approved utilization records for this user
            query = {
                "user_id": ObjectId(user_id),
                "category_id": utilization_category["_id"],
                "status": "Approved",
                "utilization_value": {"$exists": True}
            }

            utilization_cursor = mongo.db.points_request.find(query).sort("event_date", -1)
            
            total_utilization = 0.0
            count = 0
            
            for util_record in utilization_cursor:
                utilization_value = util_record.get('utilization_value', 0)
                event_date = util_record.get('event_date')
                
                if event_date and isinstance(event_date, datetime):
                    month_year_str = event_date.strftime('%B %Y')
                    month_year_value = event_date.strftime('%Y-%m')
                    
                    record_data = {
                        'month_year': month_year_str,
                        'month_year_value': month_year_value,
                        'utilization_percentage': round(utilization_value * 100, 2),
                        'event_date': event_date,
                        'request_date': util_record.get('request_date'),
                        'notes': util_record.get('submission_notes', ''),
                        'response_notes': util_record.get('response_notes', '')
                    }
                    utilization_records.append(record_data)
                    total_utilization += utilization_value
                    count += 1
            
            # Calculate average
            if count > 0:
                average_utilization = round((total_utilization / count) * 100, 2)
            
            # Get unique months for dropdown
            seen_months = set()
            for record in utilization_records:
                if record['month_year_value'] not in seen_months:
                    utilization_months.append({
                        'value': record['month_year_value'],
                        'label': record['month_year']
                    })
                    seen_months.add(record['month_year_value'])
    
    except Exception as e:
        error_print("Error fetching utilization records", e)
    
    # Get dashboard access for navigation
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    try:
        user_dashboards = get_user_dashboard_configs(dashboard_access)
        other_dashboards = [d for d in user_dashboards if d['normalized_name'] != 'Employee']
        
        # Sort dashboards by priority
        priority_order = {'Central': 0, 'HR': 1, 'DP': 2}
        other_dashboards.sort(key=lambda x: (
            priority_order.get(x['normalized_name'], 99),
            x['display_name']
        ))
    except Exception as e:
        error_print("Error loading dashboard configs", e)
        user_dashboards = []
        other_dashboards = []
    
    # Final debug before rendering

    return render_template(
        'employee_dashboard.html',
        user=user,
        categories=template_categories,  # ✅ Always defined now
        pending_requests=pending_requests,
        request_history=request_history,
        employee_submitted_history=employee_submitted_history,
        total_points=total_points,
        total_bonus_points=total_bonus_points,
        current_quarter_total_points=current_quarter_total_points,
        current_year_total_points=current_year_total_points,
        quarterly_target=quarterly_target,
        yearly_target=yearly_target,
        quarterly_percentage=quarterly_percentage,
        yearly_percentage=yearly_percentage,
        manager=manager,
        missing_validators=missing_validators_details,
        user_profile_pic_url=user_profile_pic_url,
        grade_targets=grade_targets_from_db,
        milestones=milestones_from_db,
        leaderboard_distinct_departments=leaderboard_filters_options["distinct_departments"],
        leaderboard_distinct_grades=leaderboard_filters_options["distinct_grades"],
        leaderboard_categories_options=leaderboard_filters_options["leaderboard_categories"],
        leaderboard_distinct_quarters=leaderboard_filters_options["distinct_quarters"],
        initial_leaderboard_data=initial_leaderboard_data,
        pmo_awards=pmo_awards,
        ta_awards=ta_awards,
        ld_awards=ld_awards,
        current_utilization=current_utilization,
        user_dashboards=user_dashboards,
        other_dashboards=other_dashboards,
        utilization_records=utilization_records,
        average_utilization=average_utilization,
        utilization_months=utilization_months
    )

@employee_dashboard_bp.route('/upload-profile-pic', methods=['POST'])
def upload_profile_pic():
    user_id = session.get('user_id')
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    file = request.files.get('fileToUpload')
    if not file or file.filename == '':
        flash('No file selected for upload', 'warning')
        return redirect(url_for('employee_dashboard.dashboard'))
    
    allowed_extensions = {'jpg', 'jpeg', 'png'}
    filename = file.filename
    extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if extension not in allowed_extensions:
        flash('Invalid file type. Please upload JPG, JPEG, or PNG.', 'danger')
        return redirect(url_for('employee_dashboard.dashboard'))
    
    try:
        filename = f"{user_id}_profile.jpg"
        upload_dir = os.path.join(employee_dashboard_bp.static_folder, 'uploads', 'profile_pics')
        
        if os.path.exists(upload_dir) and not os.path.isdir(upload_dir):
            os.remove(upload_dir)
        os.makedirs(upload_dir, exist_ok=True)
        
        save_path = os.path.join(upload_dir, filename)
        file.save(save_path)
        
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"profile_pic": filename, "last_updated": datetime.utcnow()}}
        )
        
        flash('Profile picture updated successfully!', 'success')
    except Exception as e:
        error_print("Error uploading profile picture", e)
        flash(f'Error uploading profile picture: {str(e)}', 'danger')
    
    return redirect(url_for('employee_dashboard.dashboard'))

@employee_dashboard_bp.context_processor
def inject_utilization_data():
    user_id = session.get('user_id')
    if not user_id:
        return {'current_utilization': None}
    
    today = datetime.utcnow()
    first_day = datetime(today.year, today.month, 1)
    if today.month == 12:
        last_day = datetime(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = datetime(today.year, today.month + 1, 1) - timedelta(days=1)
    last_day = datetime.combine(last_day.date(), datetime.max.time())
    
    utilization_data = None
    
    try:
        # Check hr_categories FIRST (where PMO categories are stored)
        utilization_category = mongo.db.hr_categories.find_one({
            "$or": [
                {"code": "utilization_billable"},
                {"name": "Utilization/Billable"}
            ]
        })
        if not utilization_category:
            utilization_category = mongo.db.categories.find_one({
                "$or": [
                    {"code": "utilization_billable"},
                    {"name": "Utilization/Billable"}
                ]
            })
        if not utilization_category:
            debug_print("No utilization category found")
            return {'current_utilization': None}
        
        utilization_request = mongo.db.points_request.find_one({
            "user_id": ObjectId(user_id),
            "status": "Approved",
            "request_date": {"$gte": first_day, "$lte": last_day},
            "category_id": utilization_category["_id"]
        }, sort=[("request_date", -1)])
        
        if utilization_request and "utilization_value" in utilization_request:
            utilization_value = utilization_request.get("utilization_value")
            if utilization_value is not None:
                utilization_data = {
                    "percentage": f"{utilization_value*100:.2f}%",
                    "numeric_value": utilization_value * 100,
                    "date": utilization_request["request_date"]
                }
                debug_print(f"Found utilization in points_request: {utilization_data}")
        else:
            utilization_point = mongo.db.points.find_one({
                "user_id": ObjectId(user_id),
                "award_date": {"$gte": first_day, "$lte": last_day},
                "category_id": utilization_category["_id"]
            }, sort=[("award_date", -1)])
            
            if utilization_point:
                utilization_value = utilization_point.get("utilization_value", 0)
                utilization_data = {
                    "percentage": f"{utilization_value*100:.2f}%",
                    "numeric_value": utilization_value * 100,
                    "date": utilization_point["award_date"]
                }
                debug_print(f"Found utilization in points: {utilization_data}")
            else:
                debug_print("No utilization data found for current month")
    
    except Exception as e:
        error_print(f"Error fetching utilization data: {str(e)}")
    
    return {'current_utilization': utilization_data}

@employee_dashboard_bp.context_processor
def utility_processor():
    return dict(get_validator_by_id=get_validator_by_id_for_template)

@employee_dashboard_bp.context_processor
def inject_now():
    return {'now': datetime.utcnow}

@employee_dashboard_bp.route('/check-rejected-requests')
def check_rejected_requests():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'User not logged in'}), 401
        
        rejected_count = mongo.db.points_request.count_documents({
            "user_id": ObjectId(user_id),
            "status": "Rejected"
        })
        
        return jsonify({
            'hasRejected': rejected_count > 0,
            'rejectedCount': rejected_count
        })
    
    except Exception as e:
        error_print(f"Error checking rejected requests: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@employee_dashboard_bp.route('/get-grade-targets')
def get_grade_targets():
    try:
        targets = mongo.db.reward_config.find_one({"_id": ObjectId("683edf40324c60f7d28ed197")})
        
        if not targets:
            return jsonify({"error": "Grade targets not found"}), 404
        
        return jsonify({
            "grade_targets": targets.get("grade_targets", {}),
            "milestones": targets.get("milestones", [])
        })
    
    except Exception as e:
        error_print(f"Error fetching grade targets: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@employee_dashboard_bp.route('/get-request-attachment/<request_id>')
def get_request_attachment(request_id):
    """Download attachment for a request from history page"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    try:
        from gridfs import GridFS
        import io

        # Try points_request first
        req = mongo.db.points_request.find_one({
            '_id': ObjectId(request_id),
            'user_id': ObjectId(user_id)
        })
        
        # If not found, try points collection
        if not req:
            req = mongo.db.points.find_one({
                '_id': ObjectId(request_id),
                'user_id': ObjectId(user_id)
            })
        
        if not req:

            flash('Request not found', 'danger')
            return redirect(url_for('employee_dashboard.dashboard'))
        
        print(f"📥 EMPLOYEE REQUEST HISTORY DEBUG: has_attachment: {req.get('has_attachment')}, attachment_id: {req.get('attachment_id')}", flush=True)
        
        if not req.get('has_attachment'):
            flash('No attachment found', 'warning')
            return redirect(url_for('employee_dashboard.dashboard'))
        
        attachment_id = req.get('attachment_id')
        if not attachment_id:
            flash('Attachment ID missing', 'warning')
            return redirect(url_for('employee_dashboard.dashboard'))
        
        # Get from GridFS
        fs = GridFS(mongo.db)
        
        if isinstance(attachment_id, str):
            attachment_id = ObjectId(attachment_id)

        if not fs.exists(attachment_id):

            # Debug: List all files
            all_files = list(mongo.db.fs.files.find())
            print(f"📥 EMPLOYEE REQUEST HISTORY DEBUG: Total files in GridFS: {len(all_files)}", flush=True)
            if all_files:
                for idx, f in enumerate(all_files[:5]):
                    print(f"  - File {idx+1}: ID={f['_id']}, filename={f.get('filename')}", flush=True)
            
            flash('Attachment file not found in storage', 'warning')
            return redirect(url_for('employee_dashboard.dashboard'))

        grid_out = fs.get(attachment_id)
        file_data = grid_out.read()

        file_stream = io.BytesIO(file_data)
        file_stream.seek(0)
        
        original_filename = grid_out.metadata.get('original_filename', req.get('attachment_filename', 'attachment'))
        content_type = grid_out.content_type or 'application/octet-stream'

        return send_file(
            file_stream,
            mimetype=content_type,
            download_name=original_filename,
            as_attachment=True
        )
        
    except Exception as e:

        flash(f'Error downloading attachment: {str(e)}', 'danger')
        return redirect(url_for('employee_dashboard.dashboard'))