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
            return False
    
    except Exception as e:
        return False

@employee_dashboard_bp.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    PRESALES_CATEGORY_CODES = ['presales_e2e', 'presales_partial', 'presales_adhoc']
    
    category_codes_to_fetch = [
        "value_add", "initiative_ai", "mentoring",
        "mindshare", "interviews"
    ] + PRESALES_CATEGORY_CODES
    
    user_id = session.get('user_id')
        
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
            
            for cat_doc in categories_from_db:
                current_category_for_template = cat_doc.copy()
                current_category_for_template['contribution_types'] = cat_doc.get('contribution_types', [])
                template_categories.append(current_category_for_template)
                        
        except Exception as e:
            flash('Unable to load categories. Please contact support.', 'danger')
            template_categories = []
        
        # ============================================
        # ✅ CALCULATE TOTALS USING LEADERBOARD LOGIC (BOTH COLLECTIONS)
        # Same implementation as employee_leaderboard.py for consistency
        # ============================================
        try:
            # Get utilization category IDs to exclude
            utilization_category_ids = []
            util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
            if util_cat_hr:
                utilization_category_ids.append(util_cat_hr["_id"])
            util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
            if util_cat_old:
                utilization_category_ids.append(util_cat_old["_id"])
            
            # Track processed request IDs to avoid double counting
            processed_request_ids = set()
            
            # ✅ STEP 1: Query approved points_request with flexible date fields
            # This matches leaderboard logic - checks event_date, request_date, award_date
            approved_requests = list(mongo.db.points_request.find({
                "user_id": ObjectId(user_id),
                "status": "Approved"
            }))
            
            # ✅ FIXED: Separate regular and bonus points tracking
            total_regular_points = 0
            
            for req in approved_requests:
                category_id = req.get('category_id')
                points_value = req.get('points', 0)
                
                # Mark as processed to avoid double counting
                processed_request_ids.add(req['_id'])
                
                # Skip utilization category (unless specifically needed)
                if category_id in utilization_category_ids:
                    continue
                
                # Fetch category from both collections
                category = mongo.db.hr_categories.find_one({'_id': category_id})
                if not category:
                    category = mongo.db.categories.find_one({'_id': category_id})
                
                # Check if bonus
                is_bonus = req.get('is_bonus', False)
                if category and category.get('is_bonus'):
                    is_bonus = True
                
                # ✅ FIXED: Count regular and bonus separately
                if isinstance(points_value, (int, float)):
                    if is_bonus:
                        total_bonus_points += points_value
                    else:
                        total_regular_points += points_value
            
            # ✅ REMOVED: No longer fetching from points collection
            # Only use points_request collection for consistency with database export
            
            # ✅ FIXED: Total points = Regular only (bonus shown separately)
            total_points = total_regular_points
                    
        except Exception as e:
            pass
                    
        # ============================================
        # Get request history for display
        # ============================================
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
            
            request_history.sort(key=lambda x: x.get('request_date', datetime.min), reverse=True)
        
        except Exception as e:
            pass

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
        
        pmo_awards = []
        ta_awards = []
        ld_awards = []
        
        # ============================================
        # ✅ CALCULATE QUARTERLY & YEARLY TOTALS (LEADERBOARD LOGIC)
        # Uses flexible date matching: event_date → request_date → award_date
        # ============================================
        now_utc = datetime.utcnow()
        current_fq, current_fyscy = get_current_fiscal_quarter_and_year(now_utc)
        
        q_start_date, q_end_date = get_fiscal_period_date_range(current_fq, current_fyscy)
        fy_start_date, fy_end_date = get_current_fiscal_year_date_range(current_fyscy)
        
        try:
            # ✅ PROCESS APPROVED REQUESTS (points_request collection)
            for req in approved_requests:
                category_id = req.get('category_id')
                points_value = req.get('points', 0)
                
                # ✅ FLEXIBLE DATE EXTRACTION (same as leaderboard)
                # Priority: event_date → request_date → award_date
                event_date = req.get('event_date')
                request_date = req.get('request_date')
                award_date = req.get('award_date')
                
                effective_date = None
                if event_date and isinstance(event_date, datetime):
                    effective_date = event_date
                elif request_date and isinstance(request_date, datetime):
                    effective_date = request_date
                elif award_date and isinstance(award_date, datetime):
                    effective_date = award_date
                
                # Skip if no valid date
                if not effective_date:
                    continue
                
                # Skip utilization category
                if category_id in utilization_category_ids:
                    continue
                
                # Check if bonus
                is_bonus = req.get('is_bonus', False)
                if not is_bonus:
                    category = mongo.db.hr_categories.find_one({'_id': category_id})
                    if not category:
                        category = mongo.db.categories.find_one({'_id': category_id})
                    if category and category.get('is_bonus'):
                        is_bonus = True
                
                # ✅ COUNT REGULAR POINTS ONLY (exclude bonus)
                if not is_bonus and isinstance(points_value, (int, float)):
                    # Check if date falls in current quarter
                    if q_start_date <= effective_date <= q_end_date:
                        current_quarter_total_points += points_value
                    # Check if date falls in current fiscal year
                    if fy_start_date <= effective_date <= fy_end_date:
                        current_year_total_points += points_value
            
            # ✅ PROCESS HISTORICAL POINTS (points collection)
            for point in points_entries:
                # Skip if already counted from points_request
                request_id = point.get('request_id')
                if request_id and request_id in processed_request_ids:
                    continue
                
                category_id = point.get('category_id')
                points_value = point.get('points', 0)
                
                # ✅ FLEXIBLE DATE EXTRACTION (same as leaderboard)
                # Priority: event_date → award_date
                event_date = point.get('event_date')
                # Check metadata for event_date (some old records store it there)
                if not event_date and 'metadata' in point:
                    event_date = point['metadata'].get('event_date')
                
                award_date = point.get('award_date')
                
                effective_date = None
                if event_date and isinstance(event_date, datetime):
                    effective_date = event_date
                elif award_date and isinstance(award_date, datetime):
                    effective_date = award_date
                
                # Skip if no valid date
                if not effective_date:
                    continue
                
                # Skip utilization category
                if category_id in utilization_category_ids:
                    continue
                
                # Check if bonus
                is_bonus = point.get('is_bonus', False)
                if not is_bonus:
                    category = mongo.db.hr_categories.find_one({'_id': category_id})
                    if not category:
                        category = mongo.db.categories.find_one({'_id': category_id})
                    if category and category.get('is_bonus'):
                        is_bonus = True
                
                # ✅ COUNT REGULAR POINTS ONLY (exclude bonus)
                if not is_bonus and isinstance(points_value, (int, float)):
                    # Check if date falls in current quarter
                    if q_start_date <= effective_date <= q_end_date:
                        current_quarter_total_points += points_value
                    # Check if date falls in current fiscal year
                    if fy_start_date <= effective_date <= fy_end_date:
                        current_year_total_points += points_value
            
        except Exception as e:
            pass

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
                
                # ✅ FIXED: Handle both grade_points (Presales, PMArch, Marketing) and points_per_unit (PM, TA, etc.)
                user_grade = user.get('grade', 'D2')
                grade_points = category.get('grade_points', {})
                if grade_points and isinstance(grade_points, dict) and user_grade in grade_points:
                    # Use grade_points if available (Presales, PMArch, Marketing categories)
                    points_per_unit = grade_points.get(user_grade, 0)
                else:
                    # Fall back to points_per_unit (PM, TA, PMO, HR, L&D categories)
                    points_per_unit = category.get('points_per_unit', 0)
                
                if points_per_unit <= 0:
                    flash(f'This category does not have points configured for your grade', 'danger')
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
                                    
                except Exception as e:
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
                    except Exception as e:
                        pass
                
                frequency = category.get('frequency', 'Quarterly')
                if frequency.lower() == 'monthly':
                    period_text = "month"
                else:
                    period_text = "quarter"
                
                flash(f'Your request for {points_per_unit} points in {category["name"]} has been submitted!', 'success')
                
                return redirect(url_for('employee_dashboard.dashboard'))
            
            except Exception as e:
                flash(f'An error occurred while submitting your request: {str(e)}', 'danger')
                return redirect(url_for('employee_dashboard.dashboard'))
    
    except Exception as e:
        flash('An error occurred while loading the dashboard. Please try again later.', 'danger')
        if not user:
            return redirect(url_for('auth.login'))
    
    reward_config_doc_id = "683edf40324c60f7d28ed197"
    reward_config = mongo.db.reward_config.find_one({"_id": ObjectId(reward_config_doc_id)})
    
    if reward_config:
        grade_targets_from_db = reward_config.get("grade_targets", {})
        milestones_from_db = reward_config.get("milestones", [])
        milestones_from_db = sorted(milestones_from_db, key=get_milestone_display_order)
    else:
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
        leaderboard_filters_options = {
            'distinct_departments': [],
            'distinct_grades': [],
            'leaderboard_categories': [],
            'distinct_quarters': []
        }
        initial_leaderboard_data = {}
    
    # Fetch utilization data - ✅ FIXED: Fetch ALL utilization records (including old ones)
    # Same logic as Total Points History page

    try:

        # ✅ Get utilization category IDs from BOTH collections (old and new data)
        utilization_category_ids = []
        
        # Check hr_categories first (new data)
        util_cat_hr = mongo.db.hr_categories.find_one({
            "$or": [
                {"category_code": "utilization_billable"},
                {"name": "Utilization/Billable"},
                {"name": {"$regex": "utilization", "$options": "i"}}
            ]
        })
        if util_cat_hr:
            utilization_category_ids.append(util_cat_hr["_id"])
        
        # Check categories collection (old data)
        util_cat_old = mongo.db.categories.find_one({
            "$or": [
                {"code": "utilization_billable"},
                {"name": "Utilization/Billable"},
                {"name": {"$regex": "utilization", "$options": "i"}}
            ]
        })
        if util_cat_old:
            utilization_category_ids.append(util_cat_old["_id"])
        
        if utilization_category_ids:
            # ✅ FIXED: Fetch ALL approved utilization records (don't require utilization_value field)
            # This ensures old records are also fetched
            query = {
                "user_id": ObjectId(user_id),
                "category_id": {"$in": utilization_category_ids},
                "status": "Approved"
            }

            utilization_cursor = mongo.db.points_request.find(query).sort("event_date", -1)
            
            total_utilization = 0.0
            count = 0
            
            for util_record in utilization_cursor:
                # ✅ FIXED: Try multiple ways to extract utilization value (handles old and new data)
                utilization_value = None
                
                # Try 1: Direct field
                if 'utilization_value' in util_record and util_record.get('utilization_value'):
                    utilization_value = util_record.get('utilization_value')
                
                # Try 2: submission_data
                elif 'submission_data' in util_record:
                    submission_data = util_record.get('submission_data', {})
                    if isinstance(submission_data, dict):
                        utilization_value = submission_data.get('utilization_value') or submission_data.get('utilization')
                
                # Try 3: points field (as percentage) - for old records
                if utilization_value is None or utilization_value == 0:
                    points = util_record.get('points', 0)
                    if points > 0 and points <= 100:
                        utilization_value = points / 100.0  # Convert to decimal
                
                # Skip if no valid utilization value found
                if utilization_value is None or utilization_value == 0:
                    continue
                
                # ✅ Normalize to decimal (0-1 range)
                if utilization_value > 1:
                    utilization_value = utilization_value / 100.0
                
                # ✅ Get effective date (prioritize event_date, fallback to request_date)
                event_date = util_record.get('event_date')
                if not event_date or not isinstance(event_date, datetime):
                    event_date = util_record.get('request_date')
                
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
        pass

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
        total_points=int(total_points),
        total_bonus_points=int(total_bonus_points),
        current_quarter_total_points=int(current_quarter_total_points),
        current_year_total_points=int(current_year_total_points),
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
                    
    except Exception as e:
        pass
    
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

        # ✅ FIXED: Only query points_request collection (consistent with other fixes)
        req = mongo.db.points_request.find_one({
            '_id': ObjectId(request_id),
            'user_id': ObjectId(user_id)
        })
        
        if not req:

            flash('Request not found', 'danger')
            return redirect(url_for('employee_dashboard.dashboard'))
        
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




