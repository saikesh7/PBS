import os
import sys
import csv
import io
import json
import traceback
import logging
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from jinja2 import Template
from bson.objectid import ObjectId
from gridfs import GridFS, NoFile  # Updated import
from io import BytesIO
from werkzeug.utils import secure_filename
import uuid
from flask import (
    Blueprint, 
    request, 
    session, 
    flash, 
    redirect, 
    url_for,
    render_template,
    jsonify,
    Response,
    current_app,
    send_file
)
from extensions import mongo

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler('market_manager.log')
    ]
)
logger = logging.getLogger('market_manager')

# Get current directory for proper template and static file paths
current_dir = os.path.dirname(os.path.abspath(__file__))

# Create Blueprint with correct paths
market_manager_bp = Blueprint(
    'market_manager', 
    __name__, 
    url_prefix='/market_manager',
    template_folder='templates',  # Changed to relative path
    static_folder='static',       # Changed to relative path
    static_url_path='/manager/static'
)

# Debug to confirm blueprint registration
logger.debug(f"Market Manager Blueprint registered with url_prefix: {market_manager_bp.url_prefix}")
logger.debug(f"Template folder: {os.path.join(current_dir, 'templates')}")
logger.debug(f"Static folder: {os.path.join(current_dir, 'static')}")
# Email configuration for Outlook - Direct credentials
EMAIL_CONFIG = {
    'SMTP_SERVER': 'smtp-mail.outlook.com',
    'SMTP_PORT': 587,
    'SMTP_USERNAME': 'pbs@prowesssoft.com',  # Replace with your Outlook email
    'SMTP_PASSWORD': 'thffnrhmbjnjlsjd',    # Replace with your Outlook password
    'FROM_EMAIL': 'pbs@prowesssoft.com',      # Same as SMTP_USERNAME
    'FROM_NAME': 'Point Based System'
}

def send_email_notification(to_email, to_name, subject, html_content, text_content=None):
    """
    Send email notification using SMTP
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = formataddr((EMAIL_CONFIG['FROM_NAME'], EMAIL_CONFIG['FROM_EMAIL']))
        msg['To'] = formataddr((to_name, to_email))
        
        if text_content:
            text_part = MIMEText(text_content, 'plain')
            msg.attach(text_part)
        
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        with smtplib.SMTP(EMAIL_CONFIG['SMTP_SERVER'], EMAIL_CONFIG['SMTP_PORT']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['SMTP_USERNAME'], EMAIL_CONFIG['SMTP_PASSWORD'])
            server.send_message(msg)
            
        logger.debug(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        error_print(f"Failed to send email to {to_email}", e)
        return False

def get_email_template(template_name):
 """
 Get email template based on template name
 """
 templates = {
 'new_request': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
                .header { background-color: #2196F3; color: white; padding: 10px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { padding: 20px; }
                .button { display: inline-block; padding: 10px 20px; background-color: #2196F3; color: white; text-decoration: none; border-radius: 5px; }
                .footer { text-align: center; padding-top: 20px; color: #666; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h2>New Points Request Submitted for Your Approval!</h2></div>
                <div class="content">
                    <p>Dear {{ validator_name }},</p>
                    <p>A new points request has been submitted by <strong>{{ employee_name }}</strong> for the <strong>{{ category_name }}</strong> category.</p>
                    <p><strong>Points Requested:</strong> {{ points }}</p>
                    {% if notes %}<p><strong>Notes:</strong> {{ notes }}</p>{% endif %}
                    <p>Please review this request on your dashboard.</p>
                    
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to Validator Dashboard</a></center>
                </div>
                
            
        </div>
            </div>
        </body>
        </html>
        ''',
 'request_approved': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
                .header { background-color: #4CAF50; color: white; padding: 10px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { padding: 20px; }
                .button { display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; }
                .footer { text-align: center; padding-top: 20px; color: #666; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h2>Your Points Request has been Approved!</h2></div>
                <div class="content">
                    <p>Dear {{ employee_name }},</p>
                    <p>Your request for points in the <strong>{{ category_name }}</strong> category has been approved.</p>
                    <p><strong>Points Awarded:</strong> {{ points }}</p>
                    <p><strong>Processed By:</strong> {{ validator_name }}</p>
                    {% if notes %}<p><strong>Validator's Notes:</strong> {{ notes }}</p>{% endif %}
                    <p>You can view your updated points total on your dashboard.</p>
                    
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to Validator Dashboard</a></center>
                </div>
                
            
        </div>
            </div>
        </body>
        </html>
        ''',
 'request_rejected': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
                .header { background-color: #f44336; color: white; padding: 10px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { padding: 20px; }
                .button { display: inline-block; padding: 10px 20px; background-color: #f44336; color: white; text-decoration: none; border-radius: 5px; }
                .footer { text-align: center; padding-top: 20px; color: #666; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h2>Your Points Request has been Rejected</h2></div>
                <div class="content">
                    <p>Dear {{ employee_name }},</p>
                    <p>Unfortunately, your request for points in the <strong>{{ category_name }}</strong> category has been rejected.</p>
                    <p><strong>Processed By:</strong> {{ validator_name }}</p>
                    {% if notes %}<p><strong>Validator's Notes:</strong> {{ notes }}</p>{% endif %}
                    <p>Please review the notes and contact your manager if you have any questions.</p>
                    
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to Validator Dashboard</a></center>
                </div>
                
            
        </div>
            </div>
        </body>
        </html>
        ''',
 'request_processed': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header-approved { background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .header-rejected { background-color: #f44336; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }
                .button { display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; }
                .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
                .info-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
                .info-table td { padding: 8px; border-bottom: 1px solid #ddd; }
                .info-table td:first-child { font-weight: bold; width: 40%; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header-{{ status_lower }}">
                    <h2>Points Request {{ status }}</h2>
                </div>
                <div class="content">
                    <p>Dear {{ employee_name }},</p>

                    <p>Your points request for <strong>{{ category_name }}</strong> has been <strong>{{ status }}</strong> by {{ processor_name }}.</p>

                    <table class="info-table">
                        <tr>
                            <td>Category:</td>
                            <td>{{ category_name }}</td>
                        </tr>
                        <tr>
                            <td>Points Requested:</td>
                            <td>{{ points }}</td>
                        </tr>
                        <tr>
                            <td>Submission Date:</td>
                            <td>{{ submission_date }}</td>
                        </tr>
                        <tr>
                            <td>Processed Date:</td>
                            <td>{{ processed_date }}</td>
                        </tr>
                        <tr>
                            <td>Processed By:</td>
                            <td>{{ processor_name }} ({{ processor_level }})</td>
                        </tr>
                    </table>

                    {% if manager_notes %}
                    <h3>{{ processor_name }}'s Notes:</h3>
                    <p style="background-color: #fff; padding: 10px; border-left: 3px solid {% if status == 'Approved' %}#4CAF50{% else %}#f44336{% endif %};">
                        {{ manager_notes }}
                    </p>
                    {% endif %}

                    <p>You can view your updated points and request history by logging into the system.</p>

                    
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to Validator Dashboard</a></center>
                </div>
                
            
        </div>
            </div>
        </body>
        </html>
        '''
 }
 return templates.get(template_name, '')

def send_new_request_notification(request_data, employee, validator, category):
    # This function is a simplified version for the market manager context
    # It's similar to the one in employee/routes.py
    try:
        employee_email = employee.get('email')
        employee_name = employee.get('name')
        validator_email = validator.get('email')
        validator_name = validator.get('name')
        category_name = category.get('name')
        notes = request_data.get('notes', '') # Original notes from the request

        if not validator_email:
            logger.warning(f"No email address for validator {validator_name} (ID: {validator.get('_id')}). Skipping new request notification.")
            return False

        subject = f"New Points Request for {category_name} from {employee_name}"
        template_content = get_email_template('new_request')
        template = Template(template_content)

        dashboard_url = url_for('market_manager.dashboard', _external=True) # Assuming validator dashboard is the target

        html_content = template.render(
            employee_name=employee_name,
            category_name=category_name,
            points=request_data.get('points'),
            notes=notes,
            validator_name=validator_name, # Pass validator_name for the new_request template
            dashboard_url=dashboard_url
        )

        return send_email_notification(validator_email, validator_name, subject, html_content)

    except Exception as e:
        error_print(f"Error in send_new_request_notification for request {request_data.get('_id')}", e)
        return False

def send_processed_request_notification(request_data, employee, validator, category, status):
    try:
        employee_email = employee.get('email')
        employee_name = employee.get('name')
        validator_name = validator.get('name')
        category_name = category.get('name')
        notes = request_data.get('response_notes', '') # Use response_notes for validator's feedback

        if not employee_email:
            logger.warning(f"No email address for employee {employee_name} (ID: {employee.get('_id')}). Skipping notification.")
            return False

        dashboard_url = url_for('employee.dashboard', _external=True) # Assuming employee dashboard is the target

        # Prepare variables for the new template
        submission_date = request_data.get('request_date').strftime('%B %d, %Y') if request_data.get('request_date') else ''
        processed_date = request_data.get('processed_date').strftime('%B %d, %Y') if request_data.get('processed_date') else ''
        processor_level = validator.get('manager_level', 'Manager') # Use the manager_level from the validator's document
        template_vars = {
            'employee_name': employee_name,
            'category_name': category_name,
            'points': request_data.get('points'),
            'submission_date': submission_date,
            'processed_date': processed_date,
            'processor_name': validator_name,
            'processor_level': processor_level,
            'status': status,
            'status_lower': status.lower(),
            'manager_notes': notes,
            'dashboard_url': dashboard_url
        }
        subject = f"Your Points Request for {category_name} Has Been {status}!"
        template_content = get_email_template('request_processed')
        template = Template(template_content)
        html_content = template.render(**template_vars)

        return send_email_notification(employee_email, employee_name, subject, html_content)

    except Exception as e:
        error_print(f"Error in send_processed_request_notification for request {request_data.get('_id')}", e)
        return False

# Register a shutdown hook to close MongoDB connection



# Enhanced debugging function - disabled for production
def debug_print(message, data=None):
    pass  # No-op function to disable debug output

# Enhanced error handling function
def error_print(message, error=None):
    print(f"ERROR - MARKET_MANAGER: {message}", file=sys.stderr)
    if error:
        print(f"  Exception: {str(error)}", file=sys.stderr)

# Helper function to get departments managed by Market Manager
def get_managed_departments(manager_id):
    try:
        manager = mongo.db.users.find_one({"_id": ObjectId(manager_id)})
        if not manager:
            debug_print(f"No manager found for ID: {manager_id}")
            return []
        
        if 'managed_departments' in manager and manager['managed_departments']:
            debug_print(f"Managed departments for {manager_id}: {manager['managed_departments']}")
            return manager['managed_departments']
        
        if 'department' in manager and manager['department']:
            debug_print(f"Manager department for {manager_id}: {manager['department']}")
            return [manager['department']]
        
        debug_print(f"No departments found for manager {manager_id}")
        return []
    except Exception as e:
        error_print("Error getting managed departments", e)
        return []

# Helper function to calculate current quarter date range
def get_current_quarter_date_range():
    # Get current time in UTC and adjust to IST (UTC+5:30)
    now_utc = datetime.utcnow()
    ist_offset = timedelta(hours=5, minutes=30)
    now_ist = now_utc + ist_offset

    # Determine fiscal year and quarter
    year = now_ist.year
    month = now_ist.month
    
    if month >= 4:  # April to December -> Current year is fiscal year
        fiscal_year = year
    else:  # January to March -> Previous year is fiscal year
        fiscal_year = year - 1
    
    # Calculate fiscal quarter
    if 4 <= month <= 6:
        current_quarter = 1
        quarter_start = datetime(fiscal_year, 4, 1)
        quarter_end = datetime(fiscal_year, 7, 1)
    elif 7 <= month <= 9:
        current_quarter = 2
        quarter_start = datetime(fiscal_year, 7, 1)
        quarter_end = datetime(fiscal_year, 10, 1)
    elif 10 <= month <= 12:
        current_quarter = 3
        quarter_start = datetime(fiscal_year, 10, 1)
        quarter_end = datetime(fiscal_year + 1, 1, 1)
    else:  # January to March
        current_quarter = 4
        quarter_start = datetime(fiscal_year, 1, 1)
        quarter_end = datetime(fiscal_year, 4, 1)
    
    debug_print(f"Fiscal Year: {fiscal_year}, Quarter: Q{current_quarter}, Start: {quarter_start}, End: {quarter_end}")
    return quarter_start, quarter_end, current_quarter, fiscal_year
# Helper function to get grade-based minimum expected points
def get_grade_minimum_expectations():
    expectations = {
        'A1': 200, 'B1': 400, 'B2': 400, 'C1': 400, 'C2': 400, 'D1': 400, 'D2': 400
    }
    debug_print("Grade minimum expectations", expectations)
    return expectations

# Helper function to validate an employee for award
def validate_employee_for_award(employee_id, category_id=None):
    try:
        # Fetch the employee
        current_date = datetime.utcnow()
        employee = mongo.db.users.find_one({
            "_id": ObjectId(employee_id),
            "role": {"$regex": "^Employee$", "$options": "i"},
            "$or": [
                {"exit_date": {"$exists": False}},
                {"exit_date": None},
                {"exit_date": {"$gt": current_date}}
            ]
        })
        if not employee:
            debug_print(f"Employee not found for ID: {employee_id}")
            return {"valid": False, "error": "Employee not found or inactive"}

        debug_print(f"Employee found: {employee.get('name', 'Unknown')} (ID: {employee_id})")

        # If category_id is provided, validate the category
        if category_id:
            category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
            if not category or category.get('validator', '').lower() != "marketing":
                debug_print(f"Invalid category for Market Manager, category_id: {category_id}")
                return {"valid": False, "error": "Invalid category for Market Manager"}

        # Get current quarter date range
        quarter_start, quarter_end, _, _ = get_current_quarter_date_range()

        # Calculate total points in the current quarter for this employee
        total_quarter_points = mongo.db.points.aggregate([
            {"$match": {
                "user_id": ObjectId(employee_id),
                "award_date": {"$gte": quarter_start, "$lt": quarter_end}
            }},
            {"$group": {
                "_id": None,
                "total": {"$sum": "$points"}
            }}
        ])
        total_quarter_points = next(total_quarter_points, {"total": 0})["total"]
        debug_print(f"Total quarter points for employee {employee_id}: {total_quarter_points}")

        # Get expected points based on grade
        grade_expectations = get_grade_minimum_expectations()
        expected_points = grade_expectations.get(employee.get('grade', ''), 0)

        # Prepare response
        result = {
            "valid": True,
            "employee_id": str(employee["_id"]),
            "employee_id_field": employee.get("employee_id", ""),
            "employee_name": employee.get("name", ""),
            "email": employee.get("email", ""),
            "grade": employee.get("grade", ""),
            "department": employee.get("department", ""),
            "total_quarter_points": total_quarter_points,
            "expected_points": expected_points
        }
        debug_print(f"Validation result for employee {employee_id}", result)
        return result
    except Exception as e:
        error_print("Error validating employee for award", e)
        return {"valid": False, "error": "An error occurred during validation"}

# Helper function to determine Market Manager role
def get_market_manager_info(mongo, user_id_str):
    """Enhanced function to handle both validator and manager roles"""
    user_id_obj = ObjectId(user_id_str)
    user = mongo.db.users.find_one({"_id": user_id_obj})
    if not user:
        return None, False, None
    
    manager_level = user.get('manager_level', '')
    # Market Manager Validator if they do NOT have a manager_id and their level is Marketing
    is_validator = (manager_level == 'Marketing' and not user.get('manager_id'))
    # If user is a manager (not validator), their manager_id is the validator's ID
    validator_id_for_updater = ObjectId(user.get('manager_id')) if not is_validator and manager_level == 'Marketing' and user.get('manager_id') else None
    
    return user, is_validator, validator_id_for_updater

# Helper function to augment request/award data with employee and category names
def _augment_request_data(requests_list):
    augmented_list = []
    for req_item in requests_list: # req_item is a dict from MongoDB
        try:
            req_item['id'] = str(req_item['_id']) # Add string ID for template

            # Add employee details
            if "user_id" in req_item and req_item["user_id"]:
                employee_doc = mongo.db.users.find_one({"_id": ObjectId(req_item["user_id"])})
                req_item["employee_name"] = employee_doc.get("name", "N/A") if employee_doc else "N/A"
                req_item["employee_grade"] = employee_doc.get("grade", "N/A") if employee_doc else "N/A"
                req_item["employee_department"] = employee_doc.get("department", "N/A") if employee_doc else "N/A"
            else:
                req_item["employee_name"] = "N/A"
                req_item["employee_grade"] = "N/A"
                req_item["employee_department"] = "N/A"

            # Add category details
            if "category_id" in req_item and req_item["category_id"]:
                category_doc = mongo.db.categories.find_one({"_id": ObjectId(req_item["category_id"])})
                req_item["category_name"] = category_doc.get("name", "N/A") if category_doc else "N/A"
            else:
                req_item["category_name"] = "N/A"
            
            # Set award_date for template consistency (used in recent_awards)
            # For processed requests, this should be the response_date
            if req_item.get('status') in ['Approved', 'Rejected']:
                # Prioritize 'processed_date', then 'response_date' (legacy)
                req_item['award_date'] = req_item.get('processed_date') or req_item.get('response_date')
            
            # Fallback to request_date if no processing date is found (e.g., for pending items or if data is old)
            # Ensure there's always an award_date, even if it's the request_date for pending items.
            if not req_item.get('award_date'): # Covers pending or cases where processed/response_date might be missing
                 req_item['award_date'] = req_item.get('request_date')

            # Determine if it's a manager-raised request and who raised it
            req_item['is_manager_request'] = False
            req_item['raised_by_manager'] = None # Default to None
            if req_item.get("created_by_market_id"): # This ID is the manager who raised it
                req_item['is_manager_request'] = True
                creator_doc = mongo.db.users.find_one({"_id": ObjectId(req_item["created_by_market_id"])})
                req_item['raised_by_manager'] = creator_doc.get("name", "Manager") if creator_doc else "Manager"

            # Ensure essential fields for the template are present
            req_item.setdefault('points', 'N/A')
            req_item.setdefault('request_date', req_item.get('request_date'))
            
            # 'notes' should hold the original submission notes.
            # Prioritize 'request_notes' (often used for employee submissions),
            # then fall back to 'notes' (used for manager submissions or general case).
            submission_notes = req_item.get("request_notes")
            if not submission_notes: # If request_notes is None or empty string
                submission_notes = req_item.get("notes", "")
            req_item['notes'] = submission_notes
            req_item.setdefault('response_notes', req_item.get('response_notes', '')) # Manager's processing notes
            req_item.setdefault('has_attachment', req_item.get('has_attachment', False))
            req_item.setdefault('attachment_filename', req_item.get('attachment_filename'))
            augmented_list.append(req_item)
        except Exception as e:
            error_print(f"Error augmenting request item {req_item.get('_id', 'Unknown')}", e)
    return augmented_list

# Main Dashboard Route
@market_manager_bp.route('/')
def dashboard():
    try:
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))

        user_id = session['user_id']
        user, is_validator, validator_id_for_updater = get_market_manager_info(mongo, user_id)
        
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('auth.login'))

        # Generate profile picture URL if exists
        profile_filename = user.get("profile_pic")
        user_profile_pic_url = url_for('market_manager.static', filename=f'uploads/profile_pics/{profile_filename}') if profile_filename else None

        # Get current quarter and month
        now_utc = datetime.utcnow()
        ist_offset = timedelta(hours=5, minutes=30)
        now_ist = now_utc + ist_offset
        current_month = now_ist.strftime('%B %Y')  # e.g., "May 2025"
        quarter_start, quarter_end, quarter_number, fiscal_year = get_current_quarter_date_range()
        current_quarter = f"Q{quarter_number} {fiscal_year}"  # Format as "Q1 2025"
        
        # Get all categories for the form
        categories = list(mongo.db.categories.find({
            "validator": {"$regex": "^marketing$", "$options": "i"}
        }))
        
        # Get filter options
        filter_grades = list(mongo.db.users.distinct("grade"))
        filter_years = list(range(2024, datetime.utcnow().year + 1))
        
        if is_validator:
            # Validator dashboard: show only manager-raised requests pending validator approval
            query_conditions = {
                "$or": [
                    { # Manager-raised requests assigned to this central validator
                        "created_by_market_id": {"$ne": None, "$exists": True},
                        "pending_validator_id": user["_id"],
                    },
                    { # Employee-raised requests assigned to this central validator
                        "$or": [
                            {"created_by_market_id": None},
                            {"created_by_market_id": {"$exists": False}}
                        ],
                        "assigned_validator_id": user["_id"], # Changed from validator_id
                    }
                ],
                "status": {"$regex": "^pending$", "$options": "i"},
                "validator": {"$regex": "^marketing$", "$options": "i"}
            }
            raw_pending_requests = list(mongo.db.points_request.find(query_conditions))
            pending_requests = _augment_request_data(raw_pending_requests) # Augment data after fetching

            raw_recent_awards = list(mongo.db.points_request.find({
                "processed_by": user["_id"],
                "status": {"$in": ["Approved", "Rejected"]},
                "validator": {"$regex": "^marketing$", "$options": "i"}
            }).sort([("processed_date", -1), ("response_date", -1)]).limit(50)) # Sort by most recent processing
            recent_awards = _augment_request_data(raw_recent_awards)

            managed_employees = []
        else:
            # Market Manager (Updater) dashboard:
            # "Pending Requests" for an updater should be items they need to action.
            # For "Marketing" category, employee-raised requests go to the Central Marketing Validator,
            # not the updater. So, this list should be empty for Marketing requests.
            # The query uses assigned_validator_id which will correctly result in an empty list
            # for an updater if the request is for the Central Marketing Validator.
            query_conditions_for_updater_pending = {
                "$or": [
                    {"created_by_market_id": None},
                    {"created_by_market_id": {"$exists": False}}
                ],
                "assigned_validator_id": user["_id"], # Checks if request is directly assigned to this updater
                "status": {"$regex": "^pending$", "$options": "i"},
                "validator": {"$regex": "^marketing$", "$options": "i"}
            }
            raw_pending_requests = list(mongo.db.points_request.find(query_conditions_for_updater_pending))
            pending_requests = _augment_request_data(raw_pending_requests)

            # "Recent Awards" for an updater:
            # - Requests they raised that have been processed by a validator.
            # - Requests (typically employee-raised) that were assigned to them AND they processed.
            query_recent_awards_updater = {
                "$or": [
                    { "created_by_market_id": user["_id"] }, # Raised by this updater
                    { "processed_by": user["_id"] }          # Or processed by this updater
                ],
                "status": {"$in": ["Approved", "Rejected"]},
                "validator": {"$regex": "^marketing$", "$options": "i"}
            }
            raw_recent_awards = list(mongo.db.points_request.find(query_recent_awards_updater)
                                     .sort([("processed_date", -1), ("response_date", -1)]) # Sort by most recent processing
                                     .limit(20)) # Limit for initial load
            recent_awards = _augment_request_data(raw_recent_awards)
            # If "Recent Awards" should also include items for their managed employees processed by others:
            # managed_employee_ids = [emp['_id'] for emp in mongo.db.users.find({"manager_id": user["_id"]}, {"_id": 1})]
            # raw_recent_awards_for_managed = list(mongo.db.points_request.find({
            #     "user_id": {"$in": managed_employee_ids},
            #     "status": {"$in": ["Approved", "Rejected"]},
            #     "validator": {"$regex": "^marketing$", "$options": "i"},
            #     "processed_by": {"$ne": user["_id"]} # Processed by someone else (e.g., central validator)
            # }).sort("response_date", -1).limit(10))
            # recent_awards.extend(_augment_request_data(raw_recent_awards_for_managed))
            # recent_awards = sorted(recent_awards, key=lambda x: x.get('award_date') or datetime.min, reverse=True)[:10]

            managed_employees = list(mongo.db.users.find({"manager_id": user["_id"]}))
        
        template = 'marketing_validator.html' if is_validator else 'marketing_dashboard.html'

        return render_template(
            template,
            user=user,
            is_validator=is_validator,
            user_profile_pic_url=user_profile_pic_url,
            categories=categories,
            pending_requests=pending_requests,
            recent_awards=recent_awards,
            managed_employees=managed_employees,
            current_quarter=current_quarter,
            current_month=current_month,
            filter_grades=filter_grades,
            filter_years=filter_years,
            user_name=user.get('name', 'User'),
            user_email=user.get('email', ''),
            user_role=user.get('role', 'role'),
            user_employee_id=user.get('employee_id', 'employee_id'),
            
            
            user_manager_level=user.get('manager_level', 'manager_level'),
            user_department=user.get('department', 'department'),
            user_grade=user.get('grade', 'Unknown')  # For debugging/display
        )

    except Exception as e:
        error_print("Error in dashboard route", e)
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

@market_manager_bp.route('/switch_to_employee_view')
def switch_to_employee_view():
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))

    user = mongo.db.users.find_one({"_id": ObjectId(session['user_id'])})
    if not user or user.get('role') != 'Manager': # Ensure only managers can switch
        flash('Invalid action.', 'danger')
        return redirect(url_for('auth.login'))

    session['is_acting_as_employee'] = True
    session['original_role'] = user.get('role') # Store 'Manager'
    session['original_view_url'] = url_for('market_manager.dashboard') # URL to switch back to
    
    return redirect(url_for('employee.dashboard'))

@market_manager_bp.route('/switch_to_manager_view')
def switch_to_manager_view():
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))

    original_url = session.get('original_view_url', url_for('market_manager.dashboard'))

    # Clear the session flags
    session.pop('is_acting_as_employee', None)
    session.pop('original_role', None)
    session.pop('original_view_url', None)
    
    flash('Switched back to Market Manager View.', 'info')
    # Redirect to the original manager dashboard or a default if not set
    # This handles if they were a market manager, pmo manager, etc.
    return redirect(original_url)


# Validate Employee Route
@market_manager_bp.route('/validate_employee/<employee_id>', methods=['GET'])
def validate_employee_route(employee_id):
    try:
        result = validate_employee_for_award(employee_id)
        return jsonify(result)
    except Exception as e:
        error_print(f"Error in validate_employee_route for employee_id {employee_id}", e)
        return jsonify({"valid": False, "error": "An error occurred while validating the employee."}), 500

# Find Employee by ID Route
@market_manager_bp.route('/find_employee/<employee_code>', methods=['GET'])
def find_employee_by_id(employee_code):
    try:
        current_date = datetime.utcnow()
        employee = mongo.db.users.find_one({
            "employee_id": employee_code,
            "role": {"$regex": "Employee", "$options": "i"},
            "$or": [
                {"exit_date": {"$exists": False}},
                {"exit_date": None},
                {"exit_date": {"$gt": current_date}}
            ]
        })
        if not employee:
            return jsonify({"found": False, "error": "Employee not found with this ID."})

        return jsonify({
            "found": True,
            "employee": {
                "id": str(employee['_id']),
                "name": employee.get("name", ""),
                "grade": employee.get("grade", ""),
                "department": employee.get("department", "")
            }
        })
    except Exception as e:
        error_print(f"Error in find_employee_by_id for employee_code {employee_code}", e)
        return jsonify({"found": False, "error": "An error occurred while searching for the employee."}), 500

@market_manager_bp.route('/ajax_get_dashboard_data')
def ajax_get_dashboard_data():
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Authentication required'}), 401

        user_id = session['user_id']
        user, is_validator, _ = get_market_manager_info(mongo, user_id)
        
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Fetch pending requests based on role
        if is_validator:
            query_conditions = {
                "$or": [
                    { "created_by_market_id": {"$ne": None, "$exists": True}, "pending_validator_id": user["_id"] },
                    { "$or": [{"created_by_market_id": None}, {"created_by_market_id": {"$exists": False}}], "assigned_validator_id": user["_id"] }
                ],
                "status": {"$regex": "^pending$", "$options": "i"},
                "validator": {"$regex": "^marketing$", "$options": "i"}
            }
            raw_pending_requests = list(mongo.db.points_request.find(query_conditions))
            pending_requests = _augment_request_data(raw_pending_requests)
        else:
            # For a regular market manager (updater), pending requests are those they need to action.
            # In the current logic, this list is often empty for marketing category as requests go to the central validator.
            # The dashboard logic already handles this, so we replicate it.
            query_conditions_for_updater_pending = {
                "$or": [{"created_by_market_id": None}, {"created_by_market_id": {"$exists": False}}],
                "assigned_validator_id": user["_id"],
                "status": {"$regex": "^pending$", "$options": "i"},
                "validator": {"$regex": "^marketing$", "$options": "i"}
            }
            raw_pending_requests = list(mongo.db.points_request.find(query_conditions_for_updater_pending))
            pending_requests = _augment_request_data(raw_pending_requests)

        # To check for *new* requests, we can compare against a timestamp from the client.
        last_check_str = request.args.get('last_check')
        new_requests = []
        if last_check_str:
            try:
                # Parse ISO format date and make it timezone-naive for comparison
                last_check_date = datetime.fromisoformat(last_check_str.replace('Z', '').replace('+00:00', ''))
                for req in pending_requests:
                    request_date = req.get('request_date')
                    if request_date:
                        # Ensure request_date from DB is offset-naive for comparison
                        # This prevents TypeError if the DB stores timezone-aware datetimes
                        if hasattr(request_date, 'tzinfo') and request_date.tzinfo is not None:
                            request_date = request_date.replace(tzinfo=None)
                        if request_date > last_check_date:
                            new_requests.append(req)
            except (ValueError, TypeError):
                # If timestamp is invalid or not a string, just return all pending as potentially new
                new_requests = pending_requests
        else:
            new_requests = pending_requests

        return jsonify({
            'success': True,
            'pending_count': len(pending_requests),
            'new_requests': new_requests, # List of new pending requests
            
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })

    except Exception as e:
        error_print("Error in ajax_get_dashboard_data", e)
        return jsonify({'success': False, 'message': 'An error occurred while fetching data.'}), 500

# Process Request Route
@market_manager_bp.route('/process_request/<request_id>', methods=['POST'])
def process_request(request_id):
    try:
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if 'user_id' not in session:
            message = 'Please log in to continue.'
            return (jsonify({"success": False, "message": message}), 401) if is_ajax else redirect(url_for('auth.login'))

        user_id_str = session['user_id']
        user, is_validator, validator_id_for_updater = get_market_manager_info(mongo, user_id_str)

        if not user:
            message = 'User not found.'
            return (jsonify({"success": False, "message": message}), 404) if is_ajax else redirect(url_for('auth.login'))

        action = request.form.get('action')
        notes_from_form = request.form.get('notes', '') # Get notes, default to empty string
        notes = notes_from_form.strip() # Strip whitespace

        if not action or not notes: # Check if notes are empty after stripping
            message = 'Action and notes (cannot be empty) are required.'
            return (jsonify({"success": False, "message": message}), 400) if is_ajax else redirect(request.referrer or url_for('.dashboard', _anchor='pending' if is_validator else 'history'))

        # Validate ObjectId
        try:
            request_oid = ObjectId(request_id)
        except Exception:
            message = 'Invalid request ID.'
            return (jsonify({"success": False, "message": message}), 400) if is_ajax else redirect(url_for('.dashboard'))

        # Get the request
        request_doc = mongo.db.points_request.find_one({"_id": request_oid})
        if not request_doc:
            message = 'Request not found.'
            return (jsonify({"success": False, "message": message}), 404) if is_ajax else redirect(url_for('.dashboard'))

        # Enhanced Debug Logging for Authorization
        logger.debug(f"--- Auth Debug for process_request ---")
        logger.debug(f"Request ID being processed: {request_id} (ObjectId: {request_oid})")
        logger.debug(f"Logged-in User ID: {user['_id']} (Type: {type(user['_id'])}, Name: {user.get('name')}, Level: {user.get('manager_level')})")
        logger.debug(f"User's manager_id from DB: {user.get('manager_id')}")
        logger.debug(f"Calculated is_validator: {is_validator}")

        request_pending_validator_id = request_doc.get("pending_validator_id")
        request_assigned_validator_id = request_doc.get("assigned_validator_id")
        request_validator_id_fallback = request_doc.get("validator_id") # Old field
        request_creator_market_id = request_doc.get("created_by_market_id")

        logger.debug(f"Request's pending_validator_id: {request_pending_validator_id} (Type: {type(request_pending_validator_id)})")
        logger.debug(f"Request's assigned_validator_id: {request_assigned_validator_id} (Type: {type(request_assigned_validator_id)})")
        logger.debug(f"Request's old validator_id field (fallback): {request_validator_id_fallback} (Type: {type(request_validator_id_fallback)})")
        logger.debug(f"Request's created_by_market_id: {request_creator_market_id} (Type: {type(request_creator_market_id)})")

        # Authorization check
        authorized_to_process = False
        is_manager_raised_request = bool(request_doc.get("created_by_market_id"))
        
        logger.debug(f"--- Authorization Logic Check ---")
        logger.debug(f"Is Manager-Raised Request: {is_manager_raised_request} (Creator Market ID: {request_creator_market_id})")
        logger.debug(f"Request's pending_validator_id: {request_pending_validator_id}")
        logger.debug(f"Request's assigned_validator_id: {request_assigned_validator_id}")
        logger.debug(f"Request's old validator_id field: {request_doc.get('validator_id')}") # For comparison

        if is_validator: # Current user is the Central Marketing Validator
            if is_manager_raised_request:
                # Manager-raised request, check if it's pending with this validator
                if request_pending_validator_id == user["_id"]:
                    authorized_to_process = True
                    logger.debug(f"Validator {user['_id']} AUTHORIZED for manager-raised request {request_id} via pending_validator_id.")
            else:
                # Employee-raised request, check if it's assigned to this validator
                if request_assigned_validator_id == user["_id"]:
                    authorized_to_process = True
                    logger.debug(f"Validator {user['_id']} AUTHORIZED for employee-raised request {request_id} via assigned_validator_id.")
                # Fallback for older requests that might still use validator_id_fallback by mistake (transitional)
                elif request_doc.get("validator_id") == user["_id"] and not request_assigned_validator_id:
                    authorized_to_process = True
                    logger.warning(f"Validator {user['_id']} AUTHORIZED for employee-raised request {request_id} via FALLBACK validator_id. Request should use assigned_validator_id.")
                else:
                    logger.debug(f"Validator {user['_id']} NOT AUTHORIZED for employee-raised request {request_id}. assigned_validator_id ({request_assigned_validator_id}) or fallback validator_id ({request_doc.get('validator_id')}) does not match.")
        else: # Current user is a Market Manager (Updater)
            # Market Manager Updaters can process requests that are directly assigned to them.
            # Employee-raised "Marketing" category requests are typically routed to the Central Marketing Validator.
            # However, if such a request *is* explicitly assigned to an updater (via assigned_validator_id),
            # and their dashboard query shows it, they should be able to action it.
            if request_doc.get("assigned_validator_id") == user["_id"]:
                authorized_to_process = True
                logger.info(f"Market Manager Updater {user['_id']} AUTHORIZED for request {request_id} via assigned_validator_id.")
            # Updaters should not process requests they raised themselves if those are pending a central validator.
            elif is_manager_raised_request and request_creator_market_id == user["_id"] and request_pending_validator_id != user["_id"]:
                authorized_to_process = False
                logger.warning(f"Market Manager Updater (User ID: {user['_id']}) attempt to process self-raised request {request_id} pending different validator DENIED.")
            else:
                authorized_to_process = False
                logger.warning(f"Market Manager Updater (User ID: {user['_id']}) attempt to process request {request_id} DENIED (not assigned or other restriction).")

        if not authorized_to_process:
            message = 'You are not authorized to process this request.'
            logger.error(f"Authorization FAILED for user {user['_id']} on request {request_id}. Message: {message}")
            return (jsonify({"success": False, "message": message}), 403) if is_ajax else redirect(url_for('.dashboard'))

        # Ensure the request is actually pending
        if request_doc.get('status', '').lower() != 'pending':
            message = f'This request is already {request_doc.get("status")}.'
            return (jsonify({"success": False, "message": message}), 400) if is_ajax else redirect(url_for('.dashboard'))

        # Update request status
        status = "Approved" if action == "approve" else "Rejected"
        update_data = {
            "status": status, # "Approved" or "Rejected"
            "processed_date": datetime.utcnow(), # Changed from response_date for consistency
            "processed_by": user["_id"],
            "response_notes": notes
        }

        result = mongo.db.points_request.update_one(
            {"_id": request_oid},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            message = "Failed to update request. It may have been processed already."
            return (jsonify({"success": False, "message": message}), 400) if is_ajax else redirect(url_for('.dashboard'))

        if status == "Approved":
            employee_doc = mongo.db.users.find_one({"_id": request_doc['user_id']})
            points_entry = {
                "user_id": request_doc['user_id'],
                "category_id": request_doc['category_id'],
                "points": request_doc['points'],
                "award_date": datetime.utcnow(),
                "awarded_by": user["_id"],
                "notes": notes,
                "grade": employee_doc.get("grade", "N/A") if employee_doc else "N/A",
                "request_id": request_oid,
                "is_bonus": request_doc.get('is_bonus', False),
                "has_attachment": request_doc.get('has_attachment', False),
                "attachment_id": request_doc.get('attachment_id'),
                "attachment_filename": request_doc.get('attachment_filename')
            }
            mongo.db.points.insert_one(points_entry)
            message = f"Request approved successfully and {request_doc['points']} points awarded."
        else:
            message = "Request rejected successfully."
        try:
            # The user who raised the request
            employee_doc = mongo.db.users.find_one({"_id": request_doc['user_id']})
            # The validator who is processing it
            validator_doc = user
            # The category of the request
            category_doc = mongo.db.categories.find_one({"_id": request_doc['category_id']})

            if employee_doc and validator_doc and category_doc:
                # We need to pass the updated request doc with response_notes
                updated_request_doc = mongo.db.points_request.find_one({"_id": request_oid})
                send_processed_request_notification(
                    updated_request_doc, # Pass the updated document
                    employee_doc,
                    validator_doc,
                    category_doc,
                    status # "Approved" or "Rejected"
                )
        except Exception as e:
            error_print(f"Failed to send email notification on request processing for request {request_id}", e)
        # End of email logic
        # Prepare data for the new history record if AJAX
        if is_ajax:
            updated_request_doc = mongo.db.points_request.find_one({"_id": request_oid})
            employee_doc = mongo.db.users.find_one({"_id": updated_request_doc['user_id']})
            category_doc = mongo.db.categories.find_one({"_id": updated_request_doc['category_id']})

            fs = GridFS(mongo.db)
            attachment_details_for_response = {
                "has_attachment": False,
                "filename": None, # GridFS internal filename
                "original_filename": None, # User-facing filename
                "download_url": None,
                "size": 0
            }
            if updated_request_doc.get("has_attachment") and updated_request_doc.get("attachment_id"):
                try:
                    grid_out = fs.get(updated_request_doc["attachment_id"])
                    if grid_out:
                        attachment_details_for_response["has_attachment"] = True
                        attachment_details_for_response["original_filename"] = grid_out.metadata.get('original_filename', grid_out.filename) if grid_out.metadata else grid_out.filename
                        if not attachment_details_for_response["original_filename"]:
                            attachment_details_for_response["original_filename"] = updated_request_doc.get("attachment_filename", "attachment")
                        attachment_details_for_response["filename"] = grid_out.filename
                        attachment_details_for_response["download_url"] = url_for('market_manager.get_attachment', request_id=str(updated_request_doc["_id"]))
                        attachment_details_for_response["size"] = grid_out.length
                except NoFile:
                    logger.warning(f"Attachment file with ID {updated_request_doc['attachment_id']} not found in GridFS for request {updated_request_doc['_id']}.")
                    attachment_details_for_response["has_attachment"] = False
                except Exception as e_gridfs:
                    error_print(f"Error fetching attachment details from GridFS for request {updated_request_doc['_id']}", e_gridfs)
                    attachment_details_for_response["has_attachment"] = False

            new_history_record = {
                'id': str(updated_request_doc['_id']),
                'award_date': updated_request_doc['processed_date'].isoformat() if updated_request_doc.get('processed_date') else datetime.utcnow().isoformat(),
                'employee_name': employee_doc.get('name', 'Unknown') if employee_doc else 'Unknown',
                'employee_grade': employee_doc.get('grade', 'N/A') if employee_doc else 'N/A',
                'employee_department': employee_doc.get('department', 'N/A') if employee_doc else 'N/A',
                'category_name': category_doc.get('name', 'Unknown') if category_doc else 'Unknown',
                'points': updated_request_doc.get('points', 0),
                'notes': updated_request_doc.get('notes', ''), # Original submission notes
                'status': updated_request_doc['status'],
                'response_notes': updated_request_doc.get('response_notes', ''),
                'attachment': attachment_details_for_response
            }
            return jsonify({"success": True, "message": message, "request_id": str(request_oid), "new_record": new_history_record})
        else:
            flash(message, 'success')
            return redirect(url_for('.dashboard'))

    except Exception as e:
        error_print("Error in process_request route", e)
        message = 'An unexpected error occurred while processing the request.'
        return jsonify({"success": False, "message": message}), 500 if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else redirect(url_for('.dashboard'))

# Award Points Route
@market_manager_bp.route('/award_points', methods=['POST'])
def award_points():
    try:
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))

        user_id = session['user_id']
        employee_id = request.form.get('employee_id')
        category_id = request.form.get('category_id')
        points = request.form.get('points')
        notes_from_form = request.form.get('notes', '')
        notes = notes_from_form.strip()

        if not all([employee_id, category_id, points, notes]): # Check stripped notes
            flash('All fields (including non-empty notes) are required.', 'danger')
            return redirect(url_for('market_manager.dashboard'))

        try:
            points = int(points)
            if points != 200:
                flash('Market Impact awards must be exactly 200 points.', 'danger')
                return redirect(url_for('market_manager.dashboard'))
        except ValueError:
            flash('Points must be a valid number.', 'danger')
            return redirect(url_for('market_manager.dashboard'))

        validation = validate_employee_for_award(employee_id, category_id)
        if not validation['valid']:
            flash(validation['error'], 'danger')
            return redirect(url_for('market_manager.dashboard'))

        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        if not category or category.get('validator', '').lower() != "marketing":
            flash('Invalid category for Market Manager.', 'danger')
            return redirect(url_for('market_manager.dashboard'))

        mongo.db.points.insert_one({
            "user_id": ObjectId(employee_id),
            "category_id": ObjectId(category_id),
            "category_name": category['name'],
            "points": 200,
            "notes": notes,
            "awarded_by": ObjectId(user_id),
            "award_date": datetime.utcnow()
        })

        flash(f"Successfully awarded 200 points for {category['name']}!", 'success')
        return redirect(url_for('market_manager.dashboard'))

    except Exception as e:
        error_print("Error in award_points route", e)
        flash('An error occurred while awarding points.', 'danger')
        return redirect(url_for('market_manager.dashboard'))

# Validate Award Route
@market_manager_bp.route('/validate_award', methods=['POST'])
def validate_award():
    try:
        employee_id = request.form.get('employee_id')
        category_id = request.form.get('category_id')

        if not employee_id or not category_id:
            return jsonify({"valid": False, "error": "Employee ID and category are required."}), 400

        result = validate_employee_for_award(employee_id, category_id)
        return jsonify(result)
    except Exception as e:
        error_print("Error in validate_award route", e)
        return jsonify({"valid": False, "error": "An error occurred during validation."}), 500

@market_manager_bp.route('/download_template')
def download_template():
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['employee_id', 'notes'])
        writer.writerow(['E123', 'Increased market share by 5%'])
        writer.writerow(['E456', 'Successful product launch'])

        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={"Content-Disposition": "attachment;filename=bulk_upload_template.csv"}
        )
    except Exception as e:
        error_print("Error in download_template route", e)
        flash('An error occurred while downloading the template.', 'danger')
        return redirect(url_for('market_manager.dashboard'))

@market_manager_bp.route('/attachment/<request_id>', methods=['GET'])
def get_attachment(request_id):
    """Download attachment for a specific request"""
    try:
        # Check authentication
        user_id = session.get('user_id')
        if not user_id:
            flash('You need to log in first', 'warning')
            return redirect(url_for('auth.login'))
        
        # Find the request and verify attachment exists
        request_data = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not request_data or not request_data.get('has_attachment') or not request_data.get('attachment_id'):
            flash('No attachment found for this request', 'warning')
            return redirect(url_for('market_manager.dashboard'))

        # Get the attachment ID
        attachment_id = request_data['attachment_id']
        
        # Create GridFS instance
        fs = GridFS(mongo.db)
        
        try:
            # Get the file with proper error handling
            grid_out = fs.get(ObjectId(attachment_id))
        except NoFile:
            logger.error(f"Attachment file not found: {attachment_id}")
            flash('File not found', 'warning')
            return redirect(url_for('market_manager.dashboard'))
        
        # Get the original filename
        filename_for_download = grid_out.filename # Default to GridFS filename
        if grid_out.metadata and 'original_filename' in grid_out.metadata:
            filename_for_download = grid_out.metadata['original_filename']
        elif request_data.get('attachment_filename'): # Fallback to request_data if metadata is missing
            filename_for_download = request_data.get('attachment_filename')

        # Ensure filename is secure
        filename_for_download = secure_filename(filename_for_download)
        
        # Read file data completely
        file_data = grid_out.read()
        
        # Create BytesIO object
        file_stream = BytesIO(file_data)
        file_stream.seek(0)
        
        # Determine content type
        content_type = grid_out.content_type
        if not content_type:
            # Determine content type based on file extension
            extension = os.path.splitext(filename_for_download)[1].lower()
            mime_types = {
                '.pdf': 'application/pdf',
                '.doc': 'application/msword',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.xls': 'application/vnd.ms-excel',
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.txt': 'text/plain',
                '': 'application/octet-stream'
            }
            content_type = mime_types.get(extension, 'application/octet-stream')
        
        # Log info
        logger.debug(f"Serving file: {filename_for_download}, type: {content_type}, size: {len(file_data)}")
        
        # Send the file
        response = send_file(
            file_stream,
            mimetype=content_type,
            download_name=filename_for_download,
            as_attachment=True
        )
        
        # Add cache control headers
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response

    except Exception as e:
        logger.error(f"Error retrieving attachment: {str(e)}")
        logger.error(traceback.format_exc())
        flash('An error occurred while retrieving the attachment', 'danger')
        return redirect(url_for('market_manager.dashboard'))

@market_manager_bp.route('/download_attachment/<attachment_id>', methods=['GET'])
def download_attachment(attachment_id):
    """Direct file download by attachment ID"""
    try:
        # Check authentication
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))

        # Create GridFS instance
        fs = GridFS(mongo.db)
        
        try:
            # Get the file with proper error handling
            grid_out = fs.get(ObjectId(attachment_id))
        except NoFile:
            logger.error(f"Attachment file not found: {attachment_id}")
            flash('File not found', 'warning')
            return redirect(url_for('market_manager.dashboard'))
        
        # Get file metadata
        filename_for_download = grid_out.filename # Default to GridFS filename
        if grid_out.metadata and 'original_filename' in grid_out.metadata:
            filename_for_download = grid_out.metadata['original_filename']
        # No need to fallback to request_data.get('attachment_filename') here as this is a direct download by attachment_id
        
        # Ensure filename is secure
        filename_for_download = secure_filename(filename_for_download)
        
        # Important: Read the entire file into memory first
        file_data = grid_out.read()
        
        # Create BytesIO object and reset position
        data = BytesIO(file_data)
        data.seek(0)
        
        # Determine content type
        content_type = grid_out.content_type
        if not content_type:
            # Determine content type based on file extension
            extension = os.path.splitext(filename_for_download)[1].lower()
            mime_types = {
                '.pdf': 'application/pdf',
                '.doc': 'application/msword',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.xls': 'application/vnd.ms-excel',
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.txt': 'text/plain',
                '': 'application/octet-stream'
            }
            content_type = mime_types.get(extension, 'application/octet-stream')
        
        # Log detailed information about the file being served
        logger.debug(f"Serving file: {filename_for_download}, type: {content_type}, size: {len(file_data)}")

        # Send file with appropriate headers
        response = send_file(
            data,
            mimetype=content_type,
            as_attachment=True,
            download_name=filename_for_download
        )
        
        # Add cache control headers to prevent browser caching issues
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response

    except Exception as e:
        logger.error(f"Error downloading attachment: {str(e)}")
        logger.error(traceback.format_exc())  # Add detailed stack trace
        flash('An error occurred while downloading the attachment', 'danger')
        return redirect(url_for('market_manager.dashboard'))

@market_manager_bp.route('/raise_request', methods=['POST'])
def raise_request():
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Please log in to continue.'}), 401
        user_id = session['user_id']
        user, is_validator, validator_id_for_updater = get_market_manager_info(mongo, user_id)
        if not user:
            return jsonify({'success': False, 'message': 'User not found.'}), 404
        category_id = request.form.get('category_id')
        points = int(request.form.get('points', 0))
        notes_from_form = request.form.get('notes', '')
        notes = notes_from_form.strip() # Strip whitespace

        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        if not category:
            return jsonify({'success': False, 'message': 'Invalid category selected.'}), 400
        
        if not notes: # Check if notes are empty after stripping
            return jsonify({'success': False, 'message': 'Notes are required and cannot be empty.'}), 400

        # Get the validator for this category
        validator = category.get('validator', '').lower()
        
        # Create the base request data
        request_data = {
            "user_id": ObjectId(user_id),
            "category_id": ObjectId(category_id),
            "points": points,
            "status": "Pending",
            "request_date": datetime.utcnow(),
            "notes": notes,  # Store submission notes in 'notes'
            "created_by_market_id": ObjectId(user_id),  # Mark as manager-raised request
            "validator": validator  # Store the validator type
        }

        # Route based on validator
        if validator == "marketing":
            # For marketing validator, set pending_validator_id to the marketing validator
            marketing_validator_user_doc = mongo.db.users.find_one({
                "role": "Manager",
                "manager_level": "Marketing",
                "manager_id": None  # Validator has no manager
            })
            if marketing_validator_user_doc:
                request_data["pending_validator_id"] = marketing_validator_user_doc["_id"]
            else:
                logger.error(f"Central Marketing Validator not found. Request from {user_id} for category {category_id} cannot be routed for central marketing validation.")
                return jsonify({
                    'success': False, 
                    'message': 'Central Marketing Validator is not configured in the system. This request cannot be submitted. Please contact HR or Admin.'
                }), 500
        elif validator == "pm/arch":
            # For PM/Arch validator, set pending_validator_id to the PM/Arch validator
            pm_arch_validator = mongo.db.users.find_one({
                "role": "Manager",
                "manager_level": "PM/Arch",
                "manager_id": None  # Validator has no manager
            })
            if pm_arch_validator:
                request_data["pending_validator_id"] = pm_arch_validator["_id"]
            else:
                logger.error(f"Central PM/Arch Validator not found. Request from {user_id} for category {category_id} cannot be routed for central PM/Arch validation.")
                return jsonify({
                    'success': False, 
                    'message': 'Central PM/Arch Validator is not configured. This request cannot be submitted. Please contact HR or Admin.'
                }), 500
        elif validator == "pmo":
            # For PMO validator, set pending_validator_id to the PMO validator
            pmo_validator = mongo.db.users.find_one({
                "role": "Manager",
                "manager_level": "PMO",
                "manager_id": None  # Validator has no manager
            })
            if pmo_validator:
                request_data["pending_validator_id"] = pmo_validator["_id"]
            else:
                logger.error(f"Central PMO Validator not found. Request from {user_id} for category {category_id} cannot be routed for central PMO validation.")
                return jsonify({
                    'success': False, 
                    'message': 'Central PMO Validator is not configured. This request cannot be submitted. Please contact HR or Admin.'
                }), 500
        
        if not request_data.get("pending_validator_id"):
            logger.error(f"Pending validator ID could not be determined for request by {user_id} for category {category_id} (validator type: {validator}).")
            return jsonify({'success': False, 'message': f'Could not determine the central validator for {validator}. Request cannot be submitted.'}), 500

        # Insert the request
        result = mongo.db.points_request.insert_one(request_data)
        
        if result.inserted_id:
            try:
                # Fetch validator details for the email
                validator_doc = mongo.db.users.find_one({"_id": request_data["pending_validator_id"]})
                if validator_doc:
                    # The 'employee' is the manager who is raising the request for themselves
                    employee_doc = user 
                    send_new_request_notification(
                        request_data,
                        employee_doc,
                        validator_doc,
                        category
                    )
            except Exception as e:
                error_print("Failed to send email notification on new request", e)
        # End of email logic

         
        if result.inserted_id:
            return jsonify({
                'success': True,
                'message': 'Request raised successfully',
                'request_id': str(result.inserted_id)
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to create request'
            }), 500

    except Exception as e:
        error_print("Error raising request", e)
        return jsonify({
            'success': False,
            'message': f'Error raising request: {str(e)}'
        }), 500

# Add employee-specific routes and functionality
@market_manager_bp.route('/points-history', methods=['GET', 'POST'])
def points_history():
    try:
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))

        user_id = session['user_id']
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('auth.login'))

        # Get date range from request or default to last 30 days
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        
        if not start_date:
            start_date = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.utcnow().strftime('%Y-%m-%d')

        # Convert string dates to datetime objects
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)  # Include end date

        # Get category filter
        category_id = request.form.get('category_id')
        category_filter = {"$in": [ObjectId(category_id)]} if category_id and category_id != 'all' else {}

        # Get all points data for the user
        points_data = list(mongo.db.points.find({
            "user_id": ObjectId(user_id),
            "award_date": {"$gte": start_date_obj, "$lt": end_date_obj},
            "category_id": category_filter
        }).sort("award_date", -1))

        # Get all bonus points data
        bonus_data = list(mongo.db.bonus_points.find({
            "user_id": ObjectId(user_id),
            "date": {"$gte": start_date_obj, "$lt": end_date_obj},
            "category_id": category_filter
        }).sort("date", -1))

        # Get utilization data
        utilization_data = list(mongo.db.utilization.find({
            "user_id": ObjectId(user_id),
            "date": {"$gte": start_date_obj, "$lt": end_date_obj},
            "category_id": category_filter
        }).sort("date", -1))

        # Calculate totals
        total_points = sum(point.get('points', 0) for point in points_data)
        total_bonus_points = sum(bonus.get('points', 0) for bonus in bonus_data)

        # Get all categories for filter dropdown
        categories = list(mongo.db.categories.find())

        # Process points data for display
        for point in points_data:
            point['date'] = point.get('award_date')
            point['points'] = point.get('points', 0)
            point['numeric_value'] = point['points']
            category = mongo.db.categories.find_one({"_id": point.get('category_id')})
            point['category'] = category.get('name', 'Unknown') if category else 'Unknown'
            point['status'] = 'Approved'  # Points are always approved
            point['notes'] = point.get('notes', '')

        # Process bonus data for display
        for bonus in bonus_data:
            bonus['date'] = bonus.get('date')
            bonus['points'] = bonus.get('points', 0)
            bonus['numeric_value'] = bonus['points']
            category = mongo.db.categories.find_one({"_id": bonus.get('category_id')})
            bonus['category'] = category.get('name', 'Unknown') if category else 'Unknown'
            bonus['status'] = 'Approved'  # Bonus points are always approved
            bonus['notes'] = bonus.get('notes', '')

        # Process utilization data for display
        for util in utilization_data:
            util['date'] = util.get('date')
            util['percentage'] = util.get('percentage', 0)
            category = mongo.db.categories.find_one({"_id": util.get('category_id')})
            util['category'] = category.get('name', 'Unknown') if category else 'Unknown'
            util['status'] = 'Approved'  # Utilization is always approved
            util['notes'] = util.get('notes', '')

        return render_template(
            'points_history.html',
            user=user,
            points_data=points_data,
            bonus_data=bonus_data,
            utilization_data=utilization_data,
            total_points=total_points,
            total_bonus_points=total_bonus_points,
            categories=categories,
            start_date=start_date,
            end_date=end_date
        )

    except Exception as e:
        error_print("Error in points_history route", e)
        flash('An error occurred while fetching points history.', 'danger')
        return redirect(url_for('market_manager.dashboard'))

@market_manager_bp.route('/get-category-details/<category_id>')
def get_category_details(category_id):
    try:
        if 'user_id' not in session:
            return jsonify({'error': 'Please log in to continue.'}), 401

        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        if not category:
            return jsonify({'error': 'Category not found.'}), 404

        # Get user's grade
        user_id = session['user_id']
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            return jsonify({'error': 'User not found.'}), 404

        grade = user.get('grade', '')
        expected_points = category.get('grade_points', {}).get(grade, 0)

        return jsonify({
            'name': category.get('name', ''),
            'description': category.get('description', ''),
            'points_per_unit': category.get('points_per_unit', 0),
            'frequency': category.get('frequency', ''),
            'expected_points': expected_points,
            'validator': category.get('validator', '')
        })

    except Exception as e:
        error_print("Error in get_category_details route", e)
        return jsonify({'error': 'An error occurred while fetching category details.'}), 500

@market_manager_bp.route('/raise-points-request', methods=['POST'])
def raise_points_request():
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': 'Please log in to continue.'}), 401

        user_id = session['user_id']
        category_id = request.form.get('category_id')
        notes_from_form = request.form.get('notes', '')
        notes = notes_from_form.strip() # Strip whitespace
        attachment = request.files.get('attachment')

        if not category_id or not notes: # Check stripped notes
            return jsonify({'success': False, 'message': 'Category and non-empty notes are required.'}), 400

        # Get category details
        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        if not category:
            return jsonify({'success': False, 'message': 'Invalid category selected.'}), 400

        # Get the validator for this category
        validator = category.get('validator', '').lower()
        
        # Create request data
        request_data = {
            "user_id": ObjectId(user_id),
            "category_id": ObjectId(category_id),
            "points": category.get('points_per_unit', 0),
            "status": "Pending",
            "request_date": datetime.utcnow(),
            "notes": notes, # Store submission notes in 'notes'
            "created_by_market_id": ObjectId(user_id),  # Mark as manager-raised request
            "validator": validator  # Store the validator type
        }

        # Route based on validator
        if validator == "marketing":
            # For marketing validator, set pending_validator_id to the marketing validator
            marketing_validator = mongo.db.users.find_one({
                "role": "Manager",
                "manager_level": "Marketing",
                "manager_id": None  # Validator has no manager
            })
            if marketing_validator:
                request_data["pending_validator_id"] = marketing_validator["_id"]
        elif validator == "pm/arch":
            # For PM/Arch validator, set pending_validator_id to the PM/Arch validator
            pm_arch_validator = mongo.db.users.find_one({
                "role": "Manager",
                "manager_level": "PM/Arch",
                "manager_id": None  # Validator has no manager
            })
            if pm_arch_validator:
                request_data["pending_validator_id"] = pm_arch_validator["_id"]
        elif validator == "pmo":
            # For PMO validator, set pending_validator_id to the PMO validator
            pmo_validator = mongo.db.users.find_one({
                "role": "Manager",
                "manager_level": "PMO",
                "manager_id": None  # Validator has no manager
            })
            if pmo_validator:
                request_data["pending_validator_id"] = pmo_validator["_id"]

        # Handle attachment if provided
        if attachment and attachment.filename:
            fs = GridFS(mongo.db)
            file_id = fs.put(
                attachment.read(),
                filename=secure_filename(attachment.filename),
                content_type=attachment.content_type,
                metadata={'original_filename': attachment.filename}
            )
            request_data.update({
                "has_attachment": True,
                "attachment_id": file_id,
                "attachment_filename": attachment.filename
            })

        # Insert request
        result = mongo.db.points_request.insert_one(request_data)
        
        if result.inserted_id:
            return jsonify({
                'success': True,
                'message': 'Points request raised successfully',
                'request_id': str(result.inserted_id)
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to create request'
            }), 500

    except Exception as e:
        error_print("Error raising points request", e)
        return jsonify({
            'success': False,
            'message': f'Error raising request: {str(e)}'
        }), 500

@market_manager_bp.route('/upload-profile-pic', methods=['POST'])
def upload_profile_pic():
    if 'fileToUpload' not in request.files:
        flash('No file part in the request', 'danger')
        return redirect(url_for('market_manager.dashboard'))

    file = request.files['fileToUpload']
    if file.filename == '':
        flash('No selected file', 'warning')
        return redirect(url_for('market_manager.dashboard'))

    if file:
        from werkzeug.utils import secure_filename
        import os

        user_id = session.get('user_id')
        filename = f"{user_id}_profile.jpg"

        # Safe directory creation
        upload_dir = os.path.join(market_manager_bp.static_folder, 'uploads', 'profile_pics')
        if os.path.exists(upload_dir) and not os.path.isdir(upload_dir):
            os.remove(upload_dir)
        os.makedirs(upload_dir, exist_ok=True)

        save_path = os.path.join(upload_dir, filename)
        file.save(save_path)

        # Update user document with profile pic filename
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"profile_pic": filename}}
        )

        flash('Profile picture updated', 'success')
        return redirect(url_for('market_manager.dashboard'))

@market_manager_bp.route('/check-new-requests', methods=['GET'])
def check_new_requests():
    """
    Check for new pending requests for the Market Manager.
    Returns count of pending requests (simple approach like PM dashboard).
    """
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    debug_print(f"check_new_requests called - user_id: {user_id}, manager_level: {manager_level}")
    
    if not user_id:
        debug_print("No user_id in session")
        return jsonify({"error": "Not authenticated"}), 401
    
    # Check if user is Marketing manager or validator
    if manager_level != 'Marketing':
        debug_print(f"User not authorized - manager_level: {manager_level}")
        return jsonify({"error": "Not authorized"}), 403
    
    try:
        # Get current user details to check if they're a validator
        current_user_details = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not current_user_details:
            debug_print("User not found in database")
            return jsonify({"error": "User not found"}), 404
        
        # Check if user is a validator (no manager_id) or regular manager
        is_validator = (manager_level == 'Marketing' and not current_user_details.get('manager_id'))
        debug_print(f"User is_validator: {is_validator}")
        
        # Get Market Impact categories
        market_categories = list(mongo.db.categories.find({
            "validator": {"$regex": "^marketing$", "$options": "i"}
        }))
        
        debug_print(f"Found {len(market_categories)} market categories")
        
        if not market_categories:
            debug_print("No market categories found")
            return jsonify({"pending_count": 0})
        
        market_category_ids = [cat["_id"] for cat in market_categories]
        
        # Build query based on whether user is validator or manager (same logic as dashboard)
        if is_validator:
            # Validator dashboard: show only manager-raised requests pending validator approval
            query_conditions = {
                "$or": [
                    { # Manager-raised requests assigned to this central validator
                        "created_by_market_id": {"$ne": None, "$exists": True},
                        "pending_validator_id": current_user_details["_id"],
                    },
                    { # Employee-raised requests assigned to this central validator
                        "$or": [
                            {"created_by_market_id": None},
                            {"created_by_market_id": {"$exists": False}}
                        ],
                        "assigned_validator_id": current_user_details["_id"],
                    }
                ],
                "status": {"$regex": "^pending$", "$options": "i"},
                "validator": {"$regex": "^marketing$", "$options": "i"}
            }
        else:
            # Market Manager (Updater) dashboard: show requests assigned to this updater
            query_conditions = {
                "$or": [
                    {"created_by_market_id": None},
                    {"created_by_market_id": {"$exists": False}}
                ],
                "assigned_validator_id": current_user_details["_id"],
                "status": {"$regex": "^pending$", "$options": "i"},
                "validator": {"$regex": "^marketing$", "$options": "i"}
            }
        
        debug_print(f"Query conditions: {query_conditions}")
        
        # Count pending requests
        pending_count = mongo.db.points_request.count_documents(query_conditions)
        
        debug_print(f"Found {pending_count} pending requests")
        
        return jsonify({
            "pending_count": pending_count
        })
        
    except Exception as e:
        error_print("Error checking new requests for market manager", e)
        return jsonify({"error": "Server error"}), 500

