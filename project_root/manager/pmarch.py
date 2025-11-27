from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, Response
from extensions import mongo
from datetime import datetime, timedelta
import os
import traceback
import sys
from bson.objectid import ObjectId
import csv
import io
from werkzeug.utils import secure_filename
from flask import Blueprint
from flask import Flask, render_template
from gridfs import GridFS  # Add this import
from flask import send_file

# Javeed added this: Imports for email notifications
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from jinja2 import Template




app = Flask(__name__)


current_dir = os.path.dirname(os.path.abspath(__file__))

pm_arch_bp = Blueprint('pm_arch', __name__, url_prefix='/pm-arch', 
                      template_folder=os.path.join(current_dir, 'templates'),
                      static_folder=os.path.join(current_dir, 'static'),
                      static_url_path='/manager/static')


# Enhanced debugging function - disabled for production
def debug_print(message, data=None):
    pass  # No-op function to disable debug output

# Enhanced error handling function
def error_print(message, error=None):
    print(f"ERROR - PM_ARCH: {message}", file=sys.stderr)
    if error:
        print(f"  Exception: {str(error)}", file=sys.stderr)

# Helper function to get departments managed by PM/Arch manager
def get_managed_departments(manager_id):
    try:
        manager = mongo.db.users.find_one({"_id": ObjectId(manager_id)})
        if not manager:
            return []
        
        # If manager has specific departments assigned, use those
        if 'managed_departments' in manager and manager['managed_departments']:
            return manager['managed_departments']
        
        # Otherwise, return the manager's own department (assumed to manage the same department)
        if 'department' in manager and manager['department']:
            return [manager['department']]
        
        return []
    except Exception as e:
        error_print("Error getting managed departments", e)
        return []

from datetime import datetime

# Helper function to calculate current quarter date range (April–March fiscal year)
def get_current_quarter_date_range():
    now = datetime.utcnow()
    current_month = now.month
    current_year = now.year

    if current_month < 4:  # Q4 (Jan-Mar) belongs to the fiscal year that started in the previous calendar year
        fiscal_year_start = current_year - 1
    else: # Q1, Q2, Q3 belong to the fiscal year that started in the current calendar year
        fiscal_year_start = current_year

    if 4 <= current_month <= 6:  # Q1: April-June
        quarter = 1
        quarter_start = datetime(fiscal_year_start, 4, 1)
        quarter_end = datetime(fiscal_year_start, 6, 30, 23, 59, 59, 999999)
    elif 7 <= current_month <= 9:  # Q2: July-September
        quarter = 2
        quarter_start = datetime(fiscal_year_start, 7, 1)
        quarter_end = datetime(fiscal_year_start, 9, 30, 23, 59, 59, 999999)
    elif 10 <= current_month <= 12:  # Q3: October-December
        quarter = 3
        quarter_start = datetime(fiscal_year_start, 10, 1)
        quarter_end = datetime(fiscal_year_start, 12, 31, 23, 59, 59, 999999)
    else:  # Q4: January-March (of the next calendar year, but part of current_fiscal_year_start)
        quarter = 4
        quarter_start = datetime(fiscal_year_start + 1, 1, 1)
        quarter_end = datetime(fiscal_year_start + 1, 3, 31, 23, 59, 59, 999999)

    return quarter_start, quarter_end, quarter, fiscal_year_start




# Helper function to get grade-based minimum expected points
def get_grade_minimum_expectations():
    return {
        'A1': 500, 'B1': 500, 'B2': 500, 'C1': 1000, 'C2': 1000, 'D1': 1000, 'D2': 500
    }

# Helper function to validate an employee for value add award
def validate_employee_for_award(employee_id):
    try:
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        
        if not employee:
            return {
                "valid": False,
                "error": "Employee not found",
                "employee": None
            }
        
        # Get the value add category
        value_add_category = mongo.db.categories.find_one({"code": "value_add"})
        
        if not value_add_category:
            return {
                "valid": False,
                "error": "Value Add category not found",
                "employee": employee
            }
        
        # Calculate current quarter dates
        quarter_start, quarter_end, current_quarter, current_year = get_current_quarter_date_range()
        
        # Count value add points awarded in current quarter (for informational purposes only)
        quarter_count = mongo.db.points.count_documents({
            "user_id": ObjectId(employee_id),
            "category_id": value_add_category["_id"],
            "award_date": {"$gte": quarter_start, "$lt": quarter_end}
        })
        
        # Get grade minimum expectations
        grade = employee.get("grade", "Unknown")
        minimum_expectations = get_grade_minimum_expectations()
        expected_points = minimum_expectations.get(grade, 0)
        
        # Calculate total points awarded in current quarter
        total_quarter_points = 0
        quarter_points_cursor = mongo.db.points.find({
            "user_id": ObjectId(employee_id),
            "category_id": value_add_category["_id"],
            "award_date": {"$gte": quarter_start, "$lt": quarter_end}
        })
        
        for point in quarter_points_cursor:
            total_quarter_points += point["points"]
        
        return {
            "valid": True,
            "employee": employee,
            "category": value_add_category,
            "current_count": quarter_count,
            "total_quarter_points": total_quarter_points,
            "expected_points": expected_points,
            "quarter": current_quarter,
            "year": current_year  # Add the fiscal year to the result
        }
        
    except Exception as e:
        error_print(f"Error validating employee {employee_id}", e)
        return {
            "valid": False,
            "error": f"System error: {str(e)}",
            "employee": None
        }

# Javeed added this: Email configuration (replicated from config.py)
EMAIL_CONFIG = {
    'SMTP_SERVER': 'smtp.outlook.com',
    'SMTP_PORT': 587,
    'SMTP_USE_TLS': True,
    'SMTP_USERNAME': 'pbs@prowesssoft.com',
    'SMTP_PASSWORD': 'thffnrhmbjnjlsjd',
    'FROM_EMAIL': 'pbs@prowesssoft.com',
    'FROM_NAME': 'Point Based System'
}

# Javeed added this: Function to send email notification
def send_email_notification(to_email, to_name, subject, html_content, text_content=None):
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
            
        debug_print(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        error_print(f"Failed to send email to {to_email}", e)
        return False

# Javeed added this: Function to get email templates
def get_email_template(template_name):
    templates = {
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
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to  Dashboard</a></center>
                </div>
            
        </div>
            </div>
        </body>
        </html>
        '''
    }
    return templates.get(template_name, '')

# Javeed added this: Function to send notification after request is processed
def send_request_processed_notification(request_data, employee, processor, category, status, manager_notes):
    try:
        # Prepare email data
        submission_date = request_data['request_date'].strftime('%B %d, %Y') if request_data.get('request_date') else 'N/A'
        processed_date = datetime.utcnow().strftime('%B %d, %Y at %I:%M %p')
        
        # Determine the correct dashboard URL for the employee
        base_url = request.url_root.rstrip('/')
        dashboard_url = base_url + url_for('auth.login') # Default to login
        
        # If the employee is also a manager, they might need to go to their employee dashboard
        # This logic should be robust enough to handle PM/Arch acting as employee
        if employee.get('role') == 'Employee' or (employee.get('role') == 'Manager' and employee.get('manager_level') in ['PM', 'PM/Arch', 'Pre-sales', 'Marketing', 'TA', 'L & D', 'PMO', 'CoE/DH']):
            dashboard_url = base_url + url_for('employee.dashboard')
        
        template_vars = {
            'employee_name': employee.get('name', 'Employee'),
            'category_name': category.get('name', 'Unknown Category'),
            'points': request_data.get('points', 0),
            'status': status,
            'status_lower': status.lower(),
            'submission_date': submission_date,
            'processed_date': processed_date,
            'processor_name': processor.get('name', 'Processor'),
            'processor_level': processor.get('manager_level', 'N/A'),
            'manager_notes': manager_notes,
            'dashboard_url': dashboard_url
        }
        
        html_template = Template(get_email_template('request_processed'))
        html_content = html_template.render(**template_vars)
        
        text_content = f"""
Dear {template_vars['employee_name']},

Your points request for {template_vars['category_name']} has been {template_vars['status']} by {template_vars['processor_name']}.

Category: {template_vars['category_name']}
Points Requested: {template_vars['points']}
Status: {template_vars['status']}
Submission Date: {template_vars['submission_date']}
Processed Date: {template_vars['processed_date']}
Processed By: {template_vars['processor_name']} ({template_vars['processor_level']})

{template_vars['processor_name']}'s Notes: {template_vars['manager_notes'] if template_vars['manager_notes'] else 'N/A'}

You can view your updated points and request history by logging into the system.

Dashboard URL: {template_vars['dashboard_url']}
        """
        
        employee_email = employee.get('email')
        if employee_email:
            subject = f"Your Points Request for {category.get('name', 'Category')} has been {status}"
            return send_email_notification(
                employee_email,
                employee.get('name', 'Employee'),
                subject,
                html_content,
                text_content
            )
        else:
            debug_print(f"No email address found for employee {employee.get('name')}")
            return False
            
    except Exception as e:
        error_print("Failed to send request processed notification", e)
        return False

# Route to check quarterly request information for an employee
@pm_arch_bp.route('/check-quarterly-info/<employee_id>')
def check_quarterly_info(employee_id):
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Verify manager level
    if manager_level != 'PM/Arch':
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
                    "can_award": True,  # Always allow awards regardless of current points
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
        error_print(f"Error checking quarterly info for {employee_id}", e)
        return jsonify({"error": "Server error"}), 500

# Route to validate a single employee by ID
@pm_arch_bp.route('/validate-employee/<employee_id>')
def validate_employee(employee_id):
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Verify manager level
    if manager_level != 'PM/Arch':
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
            "employee_id_field": employee.get("employee_id", ""), # Employee ID field
            "grade": employee.get("grade", "Unknown"),
            "department": employee.get("department", ""),
            "current_quarter_count": validation_result["current_count"],
            "total_quarter_points": validation_result["total_quarter_points"],
            "expected_points": validation_result["expected_points"]
        })
        
    except Exception as e:
        error_print(f"Error validating employee {employee_id}", e)
        return jsonify({"valid": False, "error": "Server error"}), 500

# ---- PM/Arch Manager Dashboard Route ----

@pm_arch_bp.route('/dashboard', methods=['GET'])
def dashboard():
    # Get user ID from the session
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')

    # Standard authentication and role checks
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))

    # New Rule Implementation:
    # If the user is a 'PM/Arch' manager AND they do not have a 'pm_arch_validator_id' 
    # assigned to them, they should be treated as a PM/Arch Validator.
    # UPDATED RULE: If a 'PM/Arch' manager has NO validators of ANY type assigned to them,
    # they are treated as a PM/Arch Validator.
    if manager_level == 'PM/Arch':
        # Check if this PM/Arch manager has a validator assigned to them.
        has_any_assigned_validator = False
        validator_fields_to_check = [
            'pm_arch_validator_id', 
            'pm_validator_id', 
            'marketing_validator_id', 
            'presales_validator_id'
        ]
        for field in validator_fields_to_check:
            if user.get(field): # If any validator field is set
                has_any_assigned_validator = True
                break
        if not has_any_assigned_validator:
            debug_print(f"User {user.get('name')} is PM/Arch and has no pm_arch_validator_id. Redirecting to validator dashboard.")
            return redirect(url_for('pm_arch.validator_dashboard'))
        # If they DO have an assigned validator, they see the regular PM/Arch dashboard.
    elif manager_level != 'PM/Arch': # If not PM/Arch at all
        flash('You do not have permission to access this PM/Arch manager dashboard.', 'danger')
        return redirect(url_for('auth.login')) # Or a more generic dashboard/error page
    
    # Set default values
    pending_requests = []
    recent_awards = []
    processed_requests = []  # Add this to store approved and rejected requests
    managed_employees = []
    all_employees = []
    
    try:
        quarter_start, quarter_end, current_quarter, current_year = get_current_quarter_date_range()

        
        # Get managed departments (for showing employees in their team)
        managed_departments = get_managed_departments(user_id)
        debug_print(f"Managed departments: {managed_departments}")
        
        # Get Value Add category
        value_add_category = mongo.db.categories.find_one({"code": "value_add"})
        
        if not value_add_category:
            flash('Value Add category not found', 'danger')
            return redirect(url_for('manager.dashboard'))
        
        # Get pending requests - Value Add category requests where the logged-in PM/Arch manager
        # is the assigned 'pm_arch_validator_id' for the employee who made the request.
        try:
            # Find all pending requests for the Value Add category routed to PM/Arch validators
            all_pending_value_add_reqs_cursor = mongo.db.points_request.find({
                "category_id": value_add_category["_id"],
                "status": "Pending",
                "validator": "PM/Arch"  # Ensures these are requests meant for PM/Arch review
            }).sort("request_date", -1)
            
            filtered_pending_requests = []
            added_request_ids = set() # To avoid duplicates, if any

            for req_data in all_pending_value_add_reqs_cursor:
                if str(req_data["_id"]) in added_request_ids:
                    continue

                employee_of_request = mongo.db.users.find_one({"_id": req_data["user_id"]})
                if not employee_of_request:
                    debug_print(f"Employee not found for request {req_data['_id']}, user_id {req_data['user_id']}")
                    continue

                # NEW LOGIC: Check if the logged-in PM/Arch manager (user_id) is the assigned
                # pm_arch_validator_id for the employee who raised the request.
                assigned_validator_id = employee_of_request.get("pm_arch_validator_id")
                should_display_request = False
                if assigned_validator_id and str(assigned_validator_id) == str(user_id):
                    should_display_request = True

                debug_print(
                    f"Pending Request Check: Request ID: {req_data['_id']}, "
                    f"Employee: {employee_of_request.get('name')}, "
                    f"Assigned PM/Arch Validator ID: {assigned_validator_id}, "
                    f"Logged-in Manager (User ID): {user_id}, Should Display: {should_display_request}")

                if should_display_request:
                    request_to_display = {
                        'id': str(req_data["_id"]),
                        'employee_id': str(req_data["user_id"]),
                        'employee_name': employee_of_request.get("name", "Unknown"),
                        'employee_grade': employee_of_request.get("grade", "Unknown"),
                        'category_id': str(req_data["category_id"]),
                        'category_name': value_add_category.get("name", "Unknown"), # value_add_category is confirmed not None
                        'points': req_data["points"],
                        'request_date': req_data["request_date"],
                        'notes': req_data.get("request_notes") or req_data.get("notes", ""),  # Prioritize employee's submission notes
                        'has_attachment': req_data.get("has_attachment", False),
                        'attachment_filename': req_data.get("attachment_filename", "")
                    }
                    filtered_pending_requests.append(request_to_display)
                    added_request_ids.add(str(req_data["_id"]))

            pending_requests = filtered_pending_requests
            debug_print(f"Filtered to {len(pending_requests)} pending Value Add requests for manager {user.get('name')} based on assigned validator role.")
        
        except Exception as e:
            error_print("Failed to fetch and filter pending requests based on assigned validator", e)
            pending_requests = [] # Ensure it's an empty list on error
        
        # NEW SECTION: Get processed requests (both approved and rejected)
        try:
            # Find all Value Add requests that have been processed (approved or rejected)
            # and were intended for PM/Arch validation stream.
            all_processed_value_add_reqs_cursor = mongo.db.points_request.find({
                "category_id": value_add_category["_id"],
                "status": {"$in": ["Approved", "Rejected"]},
                "validator": "PM/Arch" 
            }).sort("processed_date", -1) # Consider limiting if performance becomes an issue
            
            filtered_processed_requests = []
            added_processed_request_ids = set()

            for req_data in all_processed_value_add_reqs_cursor:
                if str(req_data["_id"]) in added_processed_request_ids:
                    continue

                employee_of_request = mongo.db.users.find_one({"_id": req_data["user_id"]})
                if not employee_of_request:
                    debug_print(f"Employee not found for processed request {req_data['_id']}, user_id {req_data['user_id']}")
                    continue

                processor_id = req_data.get("processed_by")
                processor_details = mongo.db.users.find_one({"_id": ObjectId(processor_id)}) if processor_id else None
                processor_name = processor_details.get("name", "Unknown Processor") if processor_details else "System/Unknown"

                should_display_request = False

                # Condition 1: Logged-in PM/Arch (user_id) processed this request
                if processor_id and str(processor_id) == str(user_id):
                    should_display_request = True

                # Condition 2: Logged-in PM/Arch is the direct manager of the employee who raised the request
                if not should_display_request and \
                   employee_of_request.get("manager_id") and \
                   str(employee_of_request.get("manager_id")) == str(user_id):
                    should_display_request = True
                
                # Condition 3: Logged-in PM/Arch is the reporting manager of the employee's direct PM/Arch manager
                if not should_display_request and employee_of_request.get("manager_id"):
                    direct_manager_of_employee_id = employee_of_request.get("manager_id")
                    direct_manager_details = mongo.db.users.find_one({"_id": direct_manager_of_employee_id})

                    if direct_manager_details and \
                       direct_manager_details.get("manager_level") == "PM/Arch" and \
                       direct_manager_details.get("manager_id") and \
                       str(direct_manager_details.get("manager_id")) == str(user_id):
                        should_display_request = True
                
                if should_display_request:
                    processed_req_display = {
                        'id': str(req_data["_id"]),
                        'employee_id': str(req_data["user_id"]),
                        'employee_name': employee_of_request.get("name", "Unknown"),
                        'employee_grade': employee_of_request.get("grade", "Unknown"),
                        'category_id': str(req_data["category_id"]),
                        'category_name': value_add_category.get("name", "Unknown"),
                        'points': req_data["points"],
                        'request_date': req_data.get("request_date"),
                        'processed_date': req_data.get("processed_date"),
                        'status': req_data["status"],
                        'manager_notes': req_data.get("manager_notes", req_data.get("response_notes", "")), # Notes from the actual processor
                        'processed_by_name': processor_name, # Name of the manager who processed
                        'has_attachment': req_data.get("has_attachment", False),
                        'attachment_filename': req_data.get("attachment_filename", ""),
                        'quarter': req_data.get("quarter", ""), # For filtering
                        'year': req_data.get("year", "")       # For filtering
                    }
                    filtered_processed_requests.append(processed_req_display)
                    added_processed_request_ids.add(str(req_data["_id"]))
            
            processed_requests = filtered_processed_requests
            debug_print(f"Filtered to {len(processed_requests)} processed requests for manager {user.get('name')}")
        
        except Exception as e:
            error_print("Failed to fetch processed requests", e)
            processed_requests = []
        
        # Get recent awards given by this PM/Arch manager
        try:
            awards_cursor = mongo.db.points.find({
                "awarded_by": ObjectId(user_id),
                "category_id": value_add_category["_id"]  # Only get Value Add awards
            }).sort("award_date", -1).limit(10)
            
            recent_awards = []
            for award in awards_cursor:
                employee = mongo.db.users.find_one({"_id": award["user_id"]})
                
                # Check if this award was based on a request with an attachment
                has_attachment = False
                attachment_filename = ""
                request_id = None
                
                if "request_id" in award:
                    request_data = mongo.db.points_request.find_one({"_id": award["request_id"]})
                    if request_data and request_data.get("has_attachment"):
                        has_attachment = True
                        attachment_filename = request_data.get("attachment_filename", "")
                        request_id = str(request_data["_id"])
                
                recent_awards.append({
                    'id': str(award["_id"]),
                    'employee_id': str(award["user_id"]),
                    'employee_name': employee.get("name", "Unknown") if employee else "Unknown",
                    'employee_grade': employee.get("grade", "Unknown") if employee else "Unknown",
                    'category_name': value_add_category.get("name", "Unknown"),
                    'points': award["points"],
                    'award_date': award["award_date"],
                    'notes': award.get("notes", ""),
                    'has_attachment': has_attachment,
                    'attachment_filename': attachment_filename,
                    'request_id': request_id,
                    'quarter': award.get("quarter", ""),
                    'year': award.get("year", "")
                })
            
            debug_print(f"Found {len(recent_awards)} recent awards")
            
        except Exception as e:
            error_print("Failed to fetch recent awards", e)
            recent_awards = []
        
        # MODIFIED SECTION: Get ALL employees instead of just managed ones for Team tab
        try:
            # Query for ALL employees with role = Employee
            employees_cursor = mongo.db.users.find({
                "role": "Employee"
            }).sort("name", 1)
            
            managed_employees = []
            for emp in employees_cursor:
                # Skip if the employee is the manager
                if str(emp["_id"]) == user_id:
                    continue
                
                # Get total points for the employee
                total_points = 0
                points_cursor = mongo.db.points.find({"user_id": emp["_id"]})
                for point in points_cursor:
                    total_points += point["points"]
                
                # Calculate current quarter dates
                quarter_start, quarter_end, current_quarter, year = get_current_quarter_date_range()
                
                # Count value add points awarded in current quarter for informational purposes only
                quarter_count = 0
                total_quarter_points = 0
                
                if value_add_category:
                    # Count requests
                    quarter_count = mongo.db.points.count_documents({
                        "user_id": emp["_id"],
                        "category_id": value_add_category["_id"],
                        "award_date": {"$gte": quarter_start, "$lt": quarter_end}
                    })
                    
                    # Calculate total points
                    quarter_points_cursor = mongo.db.points.find({
                        "user_id": emp["_id"],
                        "category_id": value_add_category["_id"],
                        "award_date": {"$gte": quarter_start, "$lt": quarter_end}
                    })
                    
                    for point in quarter_points_cursor:
                        total_quarter_points += point["points"]
                
                # Get minimum expectations for grade
                grade = emp.get("grade", "Unknown")
                minimum_expectations = get_grade_minimum_expectations()
                expected_points = minimum_expectations.get(grade, 0)
                
                managed_employees.append({
                    'id': str(emp["_id"]),
                    'name': emp.get("name", "Unknown"),
                    'email': emp.get("email", ""),
                    'employee_id': emp.get("employee_id", ""),
                    'grade': grade,
                    'department': emp.get("department", "Unknown"),
                    'total_points': total_points,
                    'quarter_count': quarter_count,
                    'total_quarter_points': total_quarter_points,
                    'expected_points': expected_points,
                    'can_award': True  # Always allow awards regardless of current count
                })
            
            debug_print(f"Found {len(managed_employees)} employees")
            
        except Exception as e:
            error_print("Failed to fetch employees", e)
            managed_employees = []
        
        # Get ALL employees with role = Employee (for award selection)
        try:
            all_employees_cursor = mongo.db.users.find({"role": "Employee"}).sort("name", 1)
            
            all_employees = []
            for emp in all_employees_cursor:
                if str(emp["_id"]) != user_id:  # Skip self
                    grade = emp.get("grade", "Unknown")
                    minimum_expectations = get_grade_minimum_expectations()
                    expected_points = minimum_expectations.get(grade, 0)
                    
                    all_employees.append({
                        'id': str(emp["_id"]),
                        'name': emp.get("name", "Unknown"),
                        'email': emp.get("email", ""),
                        'employee_id': emp.get("employee_id", ""),
                        'grade': grade,
                        'department': emp.get("department", "Unknown"),
                        'expected_points': expected_points
                    })
            
            debug_print(f"Found {len(all_employees)} total employees")
        except Exception as e:
            error_print("Failed to fetch all employees", e)
            all_employees = []
        
    except Exception as e:
        error_print("Dashboard error", e)
        flash("An error occurred while loading the dashboard", "danger")
        return redirect(url_for('auth.login'))
    
    # Get available categories - Only Value Add for PM/Arch
    categories = []
    try:
        if value_add_category:
            categories.append(value_add_category)
    except Exception as e:
        error_print("Failed to fetch categories", e)


    # Get current quarter, month, and fiscal year for display
    # Uses the centrally defined get_current_quarter_date_range()
    # and formats them for the template, consistent with validator_dashboard
    display_quarter_str = "N/A"
    display_month_str = "N/A"
    display_fiscal_year = "N/A"
    try:
        # current_quarter_num and current_fiscal_year are already fetched from get_current_quarter_date_range()
        # earlier in this route, aliased as 'current_quarter' and 'current_year' respectively.
        display_quarter_str = f"Q{current_quarter}" # current_quarter holds the quarter number
        display_fiscal_year = current_year # current_year holds the fiscal year start
        display_month_str = datetime.utcnow().strftime("%B")
    except Exception as e:
        error_print("Error getting current quarter and month", e)
        # Default values in case of error, though current_quarter and current_year should exist
        display_quarter_str = f"Q{current_quarter}" if 'current_quarter' in locals() else "N/A"
        display_fiscal_year = current_year if 'current_year' in locals() else "N/A"

    return render_template(
        'pm_arch_dashboard.html',
        user=user,
        pending_requests=pending_requests,
        recent_awards=recent_awards,
        processed_requests=processed_requests,  # Pass the processed requests to the template
        managed_employees=managed_employees,
        all_employees=all_employees,
        categories=categories,
        current_quarter=display_quarter_str,
        current_month=display_month_str,
        current_year=display_fiscal_year # This is the fiscal year
    )


# ---- Approve/Reject Request ----
@pm_arch_bp.route('/process-request/<request_id>', methods=['POST'])
def process_request(request_id):
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    # Verify manager level
    if manager_level != 'PM/Arch':
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('manager.dashboard'))
    
    try:
        # Attempt to convert to ObjectId and log it
        try:
            object_id_instance = ObjectId(request_id)
            debug_print(f"Converted request_id '{request_id}' to ObjectId: {object_id_instance}")
        except Exception as e_oid:
            error_print(f"Failed to convert request_id '{request_id}' to ObjectId.", e_oid)
            flash(f'Invalid request ID format: {request_id}', 'danger')
            return redirect(url_for('pm_arch.dashboard'))

        # Get the request using the converted ObjectId
        points_request = mongo.db.points_request.find_one({"_id": object_id_instance})
        
        if not points_request:
            debug_print(f"Request not found in database for ObjectId: {object_id_instance} (derived from string '{request_id}')")
            flash('Request not found', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        debug_print(f"Request found: {points_request['_id']}, Status: {points_request.get('status')}")
        
        # Get the category and verify it's Value Add
        category = mongo.db.categories.find_one({"_id": points_request["category_id"]})
        if not category or category.get("code") != "value_add":
            flash('You can only process Value Add requests', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Validate employee for award (this just checks if employee exists and gets info)
        validation_result = validate_employee_for_award(str(points_request["user_id"]))
        
        if not validation_result["valid"]:
            flash(validation_result["error"], 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Get form data
        action = request.form.get('action')
        notes_from_form = request.form.get('notes', '')
        notes = notes_from_form.strip() # Strip whitespace
        
        if action not in ['approve', 'reject']:
            flash('Invalid action', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        if action == 'reject' and not notes: # Rejection notes are mandatory
            flash('Rejection notes are required and cannot be empty.', 'danger')
            return redirect(url_for('pm_arch.dashboard'))

        
        # Update the request status
        update_data = {
            "status": "Approved" if action == 'approve' else "Rejected",
            "processed_date": datetime.utcnow(),
            "processed_by": ObjectId(user_id),
            "manager_notes": notes,
            "response_notes": notes  # Ensure employee view gets these notes
        }
        
        mongo.db.points_request.update_one(
            {"_id": ObjectId(request_id)},
            {"$set": update_data}
        )
        
        # If approved, create points entry
        if action == 'approve':
            # Create points entry
            points_entry = {
                "user_id": points_request["user_id"],
                "category_id": points_request["category_id"],
                "points": points_request["points"],
                "award_date": datetime.utcnow(),
                "awarded_by": ObjectId(user_id),
                "request_id": ObjectId(request_id),
                "notes": notes,
                "quarter": validation_result["quarter"],
                "year": validation_result["year"]
            }
            
            mongo.db.points.insert_one(points_entry)
            
            employee = validation_result["employee"]

            # Javeed added this: Send email notification to the employee
            try:
                requester_employee = mongo.db.users.find_one({"_id": points_request["user_id"]})
                processor_manager = mongo.db.users.find_one({"_id": ObjectId(user_id)})
                if requester_employee and processor_manager and category:
                    send_request_processed_notification(
                        points_request, requester_employee, processor_manager, category, 'Approved', notes
                    )
            except Exception as e:
                error_print(f"Error sending approval email notification for request {request_id}", e)

            flash(f'Request approved and {points_request["points"]} points awarded to {employee.get("name", "employee")}', 'success')
        else:
            employee = validation_result["employee"]

            # Javeed added this: Send email notification to the employee for rejection
            try:
                requester_employee = mongo.db.users.find_one({"_id": points_request["user_id"]})
                processor_manager = mongo.db.users.find_one({"_id": ObjectId(user_id)})
                if requester_employee and processor_manager and category:
                    send_request_processed_notification(
                        points_request, requester_employee, processor_manager, category, 'Rejected', notes
                    )
            except Exception as e:
                error_print(f"Error sending rejection email notification for request {request_id}", e)

            flash(f'Request rejected for {employee.get("name", "employee")}', 'warning')
        
        return redirect(url_for('pm_arch.dashboard'))
    except Exception as e:
        error_print(f"Error processing request {request_id}", e)
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('pm_arch.dashboard'))

# Route to validate an employee before awarding
@pm_arch_bp.route('/validate-award', methods=['POST'])
def validate_award():
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Verify manager level
    if manager_level != 'PM/Arch':
        return jsonify({"error": "Not authorized"}), 403
    
    try:
        # Get form data
        employee_id = request.form.get('employee_id')
        category_id = request.form.get('category_id')
        notes = request.form.get('notes', '')
        
        if not employee_id or not category_id:
            return jsonify({
                "valid": False,
                "error": "Missing required fields"
            })
        
        # Validate employee (just checks if employee exists and gets info)
        validation_result = validate_employee_for_award(employee_id)
        
        if not validation_result["valid"]:
            return jsonify({
                "valid": False,
                "error": validation_result["error"],
                "employee": {
                    "name": validation_result["employee"].get("name", "") if validation_result.get("employee") else "",
                    "grade": validation_result["employee"].get("grade", "") if validation_result.get("employee") else ""
                } if validation_result.get("employee") else None
            })
        
        # Get the category
        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        
        if not category:
            return jsonify({
                "valid": False,
                "error": "Category not found"
            })
        
        # Check if this is a Value Add category (the only one PM/Arch can award)
        if category.get('code') != 'value_add':
            return jsonify({
                "valid": False,
                "error": "You can only award points for Value Add category"
            })
        
        employee = validation_result["employee"]
        return jsonify({
            "valid": True,
            "employee": {
                "id": str(employee["_id"]),
                "name": employee.get("name", ""),
                "email": employee.get("email", ""),
                "employee_id": employee.get("employee_id", ""),
                "grade": employee.get("grade", ""),
                "department": employee.get("department", ""),
                "current_quarter_count": validation_result["current_count"],
                "total_quarter_points": validation_result["total_quarter_points"],
                "expected_points": validation_result["expected_points"]
            },
            "category": {
                "id": str(category["_id"]),
                "name": category.get("name", "")
            }
        })
        
    except Exception as e:
        error_print("Error validating award", e)
        return jsonify({"valid": False, "error": f"Server error: {str(e)}"}), 500

# ---- Award Points to an Employee ----
@pm_arch_bp.route('/award-points', methods=['POST'])
def award_points():
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    # Verify manager level
    if manager_level != 'PM/Arch':
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('manager.dashboard'))
    
    try:
        # Get form data
        employee_id = request.form.get('employee_id')
        category_id = request.form.get('category_id')
        notes_from_form = request.form.get('notes', '')
        notes = notes_from_form.strip() # Strip whitespace
        
        if not employee_id or not category_id:
            flash('Missing required fields', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        if not notes: # Notes are required for awarding points
            flash('Reason for award (notes) is required and cannot be empty.', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Force points to be 500 for Value Add category
        points = 500
        
        # Validate employee (just checks if employee exists and gets info)
        validation_result = validate_employee_for_award(employee_id)
        
        if not validation_result["valid"]:
            flash(validation_result["error"], 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Get the category
        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        
        if not category:
            flash('Category not found', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Check if this is a Value Add category (the only one PM/Arch can award)
        if category.get('code') != 'value_add':
            flash('You can only award points for Value Add category', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Create points entry with additional metadata
        points_entry = {
            "user_id": ObjectId(employee_id),
            "category_id": ObjectId(category_id),
            "points": points,
            "award_date": datetime.utcnow(),
            "awarded_by": ObjectId(user_id),
            "notes": notes,
            "quarter": validation_result["quarter"],
            "year": validation_result["year"]
        }
        
        mongo.db.points.insert_one(points_entry)
        
        employee = validation_result["employee"]
        flash(f'{points} points awarded to {employee.get("name", "employee")} for {category.get("name", "category")}', 'success')
        return redirect(url_for('pm_arch.dashboard'))
        
    except Exception as e:
        error_print("Error awarding points", e)
        flash('An error occurred while awarding points', 'danger')
        return redirect(url_for('pm_arch.dashboard'))

# ---- Validate bulk upload ----
@pm_arch_bp.route('/validate-bulk-upload', methods=['POST'])
def validate_bulk_upload():
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Verify manager level
    if manager_level != 'PM/Arch':
        return jsonify({"error": "Not authorized"}), 403
    
    try:
        # Check if file was uploaded
        if 'csv_file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files['csv_file']
        
        # Check if file is empty
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Check file extension
        if not file.filename.endswith('.csv'):
            return jsonify({"error": "File must be a CSV file"}), 400
        
        # Process CSV file
        csv_data = file.read().decode('utf-8')
        csv_file = io.StringIO(csv_data)
        csv_reader = csv.DictReader(csv_file)
        
        # Validate CSV headers
        required_headers = ['employee_id', 'notes']
        headers = csv_reader.fieldnames
        
        if not headers or not all(header in headers for header in required_headers):
            return jsonify({"error": f"CSV file must contain headers: {', '.join(required_headers)}"}), 400
        
        # Get Value Add category
        value_add_category = mongo.db.categories.find_one({"code": "value_add"})
        
        if not value_add_category:
            return jsonify({"error": "Value Add category not found"}), 500
        
        # Process each row for validation
        valid_rows = []
        invalid_rows = []
        
        for i, row in enumerate(csv_reader, start=1):
            try:
                # Get required fields
                employee_id = row['employee_id'].strip()
                notes_from_csv = row.get('notes', '').strip() # Get notes and strip
                
                # Basic validation
                if not employee_id or not notes_from_csv: # Check if notes are empty after stripping
                    invalid_rows.append({
                        "row": i,
                        "data": row,
                        "error": "Missing required fields: employee_id and notes (cannot be empty) are required"
                    })
                    continue
                
                # Find employee by employee_id field
                employee = mongo.db.users.find_one({"employee_id": employee_id})
                
                if not employee:
                    invalid_rows.append({
                        "row": i,
                        "data": row,
                        "error": f"Employee with ID {employee_id} not found"
                    })
                    continue
                
                # Calculate current quarter dates
                quarter_start, quarter_end, current_quarter, year = get_current_quarter_date_range()
                
                # Count value add points awarded in current quarter (informational only)
                quarter_count = mongo.db.points.count_documents({
                    "user_id": employee["_id"],
                    "category_id": value_add_category["_id"],
                    "award_date": {"$gte": quarter_start, "$lt": quarter_end}
                })
                
                # Calculate total points awarded in current quarter
                total_quarter_points = 0
                quarter_points_cursor = mongo.db.points.find({
                    "user_id": employee["_id"],
                    "category_id": value_add_category["_id"],
                    "award_date": {"$gte": quarter_start, "$lt": quarter_end}
                })
                
                for point in quarter_points_cursor:
                    total_quarter_points += point["points"]
                
                # Get grade minimum expectations
                grade = employee.get("grade", "Unknown")
                minimum_expectations = get_grade_minimum_expectations()
                expected_points = minimum_expectations.get(grade, 0)
                
                # Valid row - always allowed regardless of current count
                valid_rows.append({
                    "row": i,
                    "employee_id": employee_id,
                    "employee_name": employee.get("name", "Unknown"),
                    "email": employee.get("email", ""),
                    "grade": grade,
                    "department": employee.get("department", "Unknown"),
                    "notes": notes_from_csv,
                    "points": 500,
                    "current_quarter_count": quarter_count,
                    "total_quarter_points": total_quarter_points,
                    "expected_points": expected_points,
                    "mongo_id": str(employee["_id"])
                })
                
            except Exception as e:
                error_print(f"Error processing CSV row {i}", e)
                invalid_rows.append({
                    "row": i,
                    "data": row,
                    "error": f"Error processing row: {str(e)}"
                })
        
        # Return validation results
        return jsonify({
            "valid": len(invalid_rows) == 0,
            "total_rows": len(valid_rows) + len(invalid_rows),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "category": {
                "id": str(value_add_category["_id"]),
                "name": value_add_category.get("name", "Value Add")
            }
        })
        
    except Exception as e:
        error_print("Error validating bulk upload", e)
        return jsonify({"error": f"Server error: {str(e)}"}), 500

# ---- Bulk Upload Awards ----
@pm_arch_bp.route('/bulk-upload', methods=['POST'])
def bulk_upload():
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    # Verify manager level
    if manager_level != 'PM/Arch':
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('manager.dashboard'))
    
    try:
        # Check if it's a validation-only request
        validate_only = request.form.get('validate_only') == 'true'
        
        # If it's validate only, redirect to the validation endpoint
        if validate_only and 'csv_file' in request.files:
            return validate_bulk_upload()
        
        # Process the pre-validated data
        processed_data = request.form.get('processed_data')
        
        if processed_data:
            # Parse the JSON data
            import json
            data = json.loads(processed_data)
            
            valid_rows = data.get('valid_rows', [])
            category_id = data.get('category', {}).get('id')
            
            if not valid_rows or not category_id:
                flash('No valid data to process', 'warning')
                return redirect(url_for('pm_arch.dashboard'))
            
            # Convert ObjectId string to ObjectId
            category_id = ObjectId(category_id)
            
            # Calculate current quarter dates
            quarter_start, quarter_end, current_quarter, year = get_current_quarter_date_range()
            
            # Process each pre-validated row
            success_count = 0
            
            for row in valid_rows:
                try:
                    # Create points entry
                    points_entry = {
                        "user_id": ObjectId(row["mongo_id"]),
                        "category_id": category_id,
                        "points": 500,  # Fixed for Value Add
                        "award_date": datetime.utcnow(),
                        "awarded_by": ObjectId(user_id),
                        "notes": row["notes"],
                        "uploaded_via_csv": True,
                        "quarter": current_quarter,
                        "year": year
                    }
                    
                    mongo.db.points.insert_one(points_entry)
                    success_count += 1
                    
                except Exception as e:
                    error_print(f"Error processing pre-validated row", e)
            
            flash(f'Successfully awarded points to {success_count} employees', 'success')
            return redirect(url_for('pm_arch.dashboard'))
            
        else:
            # If no processed data, this is an error
            flash('No data to process', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
    except Exception as e:
        error_print("Error processing bulk upload", e)
        flash('An error occurred while processing the bulk upload', 'danger')
        return redirect(url_for('pm_arch.dashboard'))

# ---- Get Employee Details ----
@pm_arch_bp.route('/get-employee/<employee_id>')
def get_employee(employee_id):
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Verify manager level
    if manager_level != 'PM/Arch':
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
        error_print(f"Error getting employee {employee_id}", e)
        return jsonify({"error": "Server error"}), 500

# Route to find employee by ID
@pm_arch_bp.route('/find-employee-by-id/<employee_code>')
def find_employee_by_id(employee_code):
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Verify manager level
    if manager_level != 'PM/Arch':
        return jsonify({"error": "Not authorized"}), 403
    
    try:
        # Find employee by employee_id field
        employee = mongo.db.users.find_one({"employee_id": employee_code})
        
        if not employee:
            return jsonify({"found": False, "error": "Employee not found"}), 404
        
        # Return employee details - PM/Arch can see any employee
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
        error_print(f"Error finding employee by ID {employee_code}", e)
        return jsonify({"found": False, "error": "Server error"}), 500

# ---- Download CSV Template ----
@pm_arch_bp.route('/download-template')
def download_template():
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    # Verify manager level
    if manager_level != 'PM/Arch':
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('manager.dashboard'))
    
    # Create CSV template
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header - updated to use employee_id instead of email
    writer.writerow(['employee_id', 'notes'])
    
    # Write sample row
    writer.writerow(['E123', 'Value Add award for project X'])
    
    # Prepare response
    response_data = output.getvalue()
    output.close()
    
    # Return CSV file
    response = Response(
        response_data,
        mimetype='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename=points_upload_template.csv',
            'Content-Type': 'text/csv'
        }
    )
    
    return response


# Add this to the pm_arch_bp blueprint file
@pm_arch_bp.route('/attachment/<request_id>', methods=['GET'])
def get_attachment(request_id):
    try:
        user_id = session.get('user_id')
        manager_level = session.get('manager_level')
        
        if not user_id:
            flash('You need to log in first', 'warning')
            return redirect(url_for('auth.login'))
        
        # Verify manager level
        if manager_level != 'PM/Arch':
            flash('You do not have permission to access this attachment', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Find the request to get the attachment ID
        request_data = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not request_data or not request_data.get('has_attachment') or not request_data.get('attachment_id'):
            flash('No attachment found for this request', 'warning')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Create GridFS instance
        fs = GridFS(mongo.db)
        
        # Get the file from GridFS
        attachment_id = request_data['attachment_id']
        if not fs.exists(ObjectId(attachment_id)):
            flash('Attachment file not found', 'warning')
            return redirect(url_for('pm_arch.dashboard'))
        
        # Get the file and its metadata
        grid_out = fs.get(ObjectId(attachment_id))
        
        # Prepare the response
        file_stream = io.BytesIO(grid_out.read())
        file_stream.seek(0)
        
        # Get the original filename from metadata
        original_filename = grid_out.metadata.get('original_filename', 'attachment')
        content_type = grid_out.content_type
        
        # Send the file to the user
        return send_file(
            file_stream,
            mimetype=content_type,
            download_name=original_filename,
            as_attachment=True
        )
        
    except Exception as e:
        error_print(f"Error retrieving attachment: {str(e)}")
        flash('An error occurred while retrieving the attachment', 'danger')
        return redirect(url_for('pm_arch.dashboard'))

@pm_arch_bp.route('/switch_to_employee_view')
def switch_to_employee_view():
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))

    user = mongo.db.users.find_one({"_id": ObjectId(session['user_id'])})
    if not user or user.get('role') != 'Manager':
        flash('Invalid action.', 'danger')
        return redirect(url_for('auth.login'))

    session['is_acting_as_employee'] = True
    session['original_role'] = user.get('role')
    session['original_view_url'] = url_for('pm_arch.dashboard')
    flash('Switched to Employee View. You can now raise requests for yourself.', 'info')
    return redirect(url_for('employee.dashboard'))

@pm_arch_bp.route('/switch_to_manager_view')
def switch_to_manager_view():
    if 'user_id' not in session:
        flash('Please log in to continue.', 'warning')
        return redirect(url_for('auth.login'))

    original_url = session.get('original_view_url', url_for('pm_arch.dashboard'))

    session.pop('is_acting_as_employee', None)
    session.pop('original_role', None)
    session.pop('original_view_url', None)
    
    flash('Switched back to PM/Arch Manager View.', 'info')
    return redirect(original_url)

# --- AJAX Data Endpoints for PM/Arch Manager Dashboard ---
@pm_arch_bp.route('/ajax/pending-requests-data', methods=['GET'])
def ajax_pending_requests_data():
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')

    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    current_user_details = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not current_user_details:
        return jsonify({"error": "User not found"}), 404

    # Authorization: Ensure user is PM/Arch and not an acting validator who should see the validator dashboard
    if manager_level == 'PM/Arch':
        is_acting_validator = not any(current_user_details.get(field) for field in ['pm_arch_validator_id', 'pm_validator_id', 'marketing_validator_id', 'presales_validator_id'])
        if is_acting_validator: # This user should be on validator dashboard, not here
            return jsonify({"error": "Unauthorized, should be on validator view"}), 403
    elif manager_level != 'PM/Arch': # Not a PM/Arch manager at all
        return jsonify({"error": "Unauthorized"}), 403

    try:
        value_add_category = mongo.db.categories.find_one({"code": "value_add"})
        if not value_add_category:
            return jsonify({"error": "Value Add category not found"}), 500

        all_pending_value_add_reqs_cursor = mongo.db.points_request.find({
            "category_id": value_add_category["_id"],
            "status": "Pending",
            "validator": "PM/Arch"
        }).sort("request_date", -1)
        
        pending_requests_list = []
        added_request_ids = set()

        for req_data in all_pending_value_add_reqs_cursor:
            if str(req_data["_id"]) in added_request_ids:
                continue
            employee_of_request = mongo.db.users.find_one({"_id": req_data["user_id"]})
            if not employee_of_request:
                continue
            
            assigned_validator_id = employee_of_request.get("pm_arch_validator_id")
            if assigned_validator_id and str(assigned_validator_id) == str(user_id):
                request_date_str = req_data["request_date"].strftime('%d-%m-%Y') if req_data.get("request_date") else 'N/A'
                
                pending_requests_list.append({
                    'id': str(req_data["_id"]),
                    'employee_name': employee_of_request.get("name", "Unknown"),
                    'employee_grade': employee_of_request.get("grade", "Unknown"),
                    'category_name': value_add_category.get("name", "Unknown"),
                    'points': req_data["points"],
                    'request_date_str': request_date_str,
                    'notes': req_data.get("request_notes") or req_data.get("notes", ""),
                    'has_attachment': req_data.get("has_attachment", False),
                    'attachment_url': url_for('pm_arch.get_attachment', request_id=str(req_data["_id"])) if req_data.get("has_attachment") else None
                })
                added_request_ids.add(str(req_data["_id"]))
        
        return jsonify({
            "pending_requests_count": len(pending_requests_list),
            "pending_requests": pending_requests_list
        })
    except Exception as e:
        error_print("Error fetching AJAX PM/Arch pending requests data", e)
        return jsonify({"error": "Server error"}), 500

# --- AJAX Data Endpoints for PM/Arch Validator Dashboard ---
@pm_arch_bp.route('/ajax/validator-pending-requests-data', methods=['GET'])
def ajax_validator_pending_requests_data():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    current_user_details = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not current_user_details:
        return jsonify({"error": "User not found"}), 404

    manager_level = current_user_details.get('manager_level')
    is_explicit_validator = (manager_level == 'PM/Arch Validator')
    is_acting_validator = False
    if manager_level == 'PM/Arch':
        has_any_assigned_validator = any(current_user_details.get(field) for field in ['pm_arch_validator_id', 'pm_validator_id', 'marketing_validator_id', 'presales_validator_id'])
        if not has_any_assigned_validator:
            is_acting_validator = True

    if not (is_explicit_validator or is_acting_validator):
        return jsonify({"error": "Unauthorized"}), 403

    # The rest of the logic is similar to the main validator_dashboard pending requests fetch
    # For brevity, this part is condensed. Ensure it mirrors the logic in `validator_dashboard()`
    # for fetching `pending_requests_list`.
    # This is a placeholder for the actual data fetching logic from validator_dashboard
    # You would replicate the database query and data processing here.
    # For the purpose of this diff, I'm showing the structure.
    try:
        # Simplified logic from validator_dashboard route to fetch pending requests
        value_add_category = mongo.db.categories.find_one({"code": "value_add"})
        if not value_add_category:
            return jsonify({"error": "Value Add category not found"}), 500

        validator_object_id_for_query = ObjectId(user_id)
        pending_requests_cursor = mongo.db.points_request.find({
            "category_id": value_add_category["_id"],
            "status": "Pending",
            "validator": "PM/Arch",
            "assigned_validator_id": validator_object_id_for_query 
        }).sort("request_date", -1)

        pending_requests_list_for_validator = []
        for req_data in pending_requests_cursor:
            requester_details = mongo.db.users.find_one({"_id": req_data["user_id"]})
            if not requester_details:
                continue
            
            request_date_str = req_data["request_date"].strftime('%d-%m-%Y') if req_data.get("request_date") else 'N/A'

            pending_requests_list_for_validator.append({
                'id': str(req_data["_id"]),
                'employee_name': requester_details.get("name", "Unknown Requester"),
                'employee_grade': requester_details.get("grade", "N/A"),
                'category_name': value_add_category.get("name", "Value Add"),
                'points': req_data["points"],
                'request_date_str': request_date_str,
                'notes': req_data.get("request_notes") or req_data.get("notes", ""),
                'has_attachment': req_data.get("has_attachment", False),
                'attachment_url': url_for('pm_arch.validator_get_attachment', request_id=str(req_data["_id"])) if req_data.get("has_attachment") else None
            })
        
        return jsonify({
            "pending_requests_count": len(pending_requests_list_for_validator),
            "pending_requests": pending_requests_list_for_validator
        })
    except Exception as e:
        error_print("Error fetching AJAX validator pending requests data", e)
        return jsonify({"error": "Server error"}), 500

# ---- PM/Arch Validator Routes ----

@pm_arch_bp.route('/validator/dashboard', methods=['GET'])
def validator_dashboard():
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')

    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    # Determine if the user should access this validator dashboard
    is_explicit_validator = (manager_level == 'PM/Arch Validator')
    is_acting_validator = False

    current_user_details = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not current_user_details:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))

    if manager_level == 'PM/Arch':
        has_any_assigned_validator = False
        validator_fields_to_check = [
            'pm_arch_validator_id', 
            'pm_validator_id', 
            'marketing_validator_id', 
            'presales_validator_id'
        ]
        for field in validator_fields_to_check:
            if current_user_details.get(field):
                has_any_assigned_validator = True
                break
        if not has_any_assigned_validator:
            is_acting_validator = True
            debug_print(f"User {current_user_details.get('name')} is PM/Arch and acting as validator.")

    if not (is_explicit_validator or is_acting_validator):
        flash('You do not have permission to access the PM/Arch Validator page.', 'danger')
        return redirect(url_for('auth.login')) # Or a more generic dashboard

    user = None
    pending_requests_list = []
    processed_requests_list = []
    
    try:
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not user: # Should not happen if current_user_details was found
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))

        quarter_start, quarter_end, current_quarter_num, current_fiscal_year = get_current_quarter_date_range()

        value_add_category = mongo.db.categories.find_one({"code": "value_add"})
        if not value_add_category:
            flash('Value Add category not found', 'danger')
            return render_template('pmarch_validator.html', user=user, pending_requests=[], processed_requests=[],
                                   current_quarter=f"Q{current_quarter_num}", current_year=current_fiscal_year, 
                                   current_month=datetime.utcnow().strftime("%B"))

        debug_print(f"PM_ARCH_VALIDATOR_DASHBOARD for validator: {user.get('name')} (ID from session: {user_id}, Type: {type(user_id)})")
        validator_object_id_for_query = ObjectId(user_id)
        debug_print(f"  Validator ObjectId for query: {validator_object_id_for_query} (Type: {type(validator_object_id_for_query)})")
        debug_print(f"  Querying for: category_id={value_add_category['_id']}, status='Pending', validator='PM/Arch', assigned_validator_id={validator_object_id_for_query}")

        # Fetch pending Value Add requests where the 'assigned_validator_id' on the request
        # matches the ID of the currently logged-in validator.
        # The 'validator' field on the request should also be 'PM/Arch'.
        pending_requests_cursor = mongo.db.points_request.find({
            "category_id": value_add_category["_id"],
            "status": "Pending",
            "validator": "PM/Arch", # Ensures it's a request for PM/Arch validation stream
            "assigned_validator_id": validator_object_id_for_query 
        }).sort("request_date", -1)

        # Consume cursor to list for easier debugging of raw results
        raw_pending_requests_from_db = list(pending_requests_cursor)
        debug_print(f"  RAW pending requests found by DB query: {len(raw_pending_requests_from_db)}")
        if not raw_pending_requests_from_db and len(pending_requests_list) == 0 : # If query returned nothing
             debug_print(f"  DB query returned NO pending requests matching criteria for validator {user.get('name')}.")
        else:
            for i, rpr in enumerate(raw_pending_requests_from_db):
                debug_print(f"    Raw req {i}: _id={rpr['_id']}, user_id={rpr['user_id']}, category_id={rpr['category_id']}, status={rpr['status']}, validator_field='{rpr.get('validator')}', assigned_validator_id={rpr.get('assigned_validator_id')}")

        for req_data in raw_pending_requests_from_db: # Iterate over the fetched list
            requester_name = "Unknown Requester"
            requester_grade = "N/A"
            requester_user_id_str = str(req_data.get("user_id", "Unknown_User_ID"))

            # Fetch the details of the user who submitted the request (can be Employee or PM/Arch Manager)
            requester_details = mongo.db.users.find_one({"_id": req_data["user_id"]})
            if requester_details:
                requester_name = requester_details.get("name", "Unknown Requester")
                requester_grade = requester_details.get("grade", "N/A")
            else:
                debug_print(f"PM_ARCH_VALIDATOR: Requester details not found for user_id {requester_user_id_str} on request {req_data['_id']}. Request will be displayed with default requester info.")

            pending_requests_list.append({
                'id': str(req_data["_id"]),
                'employee_id': requester_user_id_str, 
                'employee_name': requester_name,
                'employee_grade': requester_grade,
                'category_id': str(req_data["category_id"]),
                'category_name': value_add_category.get("name", "Value Add"), 
                'points': req_data["points"],
                'request_date': req_data["request_date"],
                'notes': req_data.get("request_notes") or req_data.get("notes", ""), # Prioritize employee's submission notes
                'has_attachment': req_data.get("has_attachment", False),
                'attachment_filename': req_data.get("attachment_filename", "")
            })

        
        debug_print(f"PM_ARCH_VALIDATOR: Found {len(pending_requests_list)} pending requests for PM/Arch Validator {user.get('name')}")

        processed_requests_cursor = mongo.db.points_request.find({
            "category_id": value_add_category["_id"],
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_by": ObjectId(user_id) 
        }).sort("processed_date", -1)

        for req_data in processed_requests_cursor:
            # Fetch the details of the user who submitted the request
            requester_details = mongo.db.users.find_one({"_id": req_data["user_id"]})
            # The request was processed by this validator, so we show it.
            # We still need requester details for display.
            if not requester_details:
                debug_print(f"PM_ARCH_VALIDATOR: Requester details not found for processed request {req_data['_id']}, user_id {req_data['user_id']}")
                continue 

            req_quarter, req_year = None, None
            date_to_use_for_q_y = req_data.get("processed_date") or req_data.get("request_date")
            if date_to_use_for_q_y:
                m = date_to_use_for_q_y.month
                y = date_to_use_for_q_y.year
                if 4 <= m <= 6: req_quarter = "Q1"
                elif 7 <= m <= 9: req_quarter = "Q2"
                elif 10 <= m <= 12: req_quarter = "Q3"
                elif 1 <= m <= 3: req_quarter = "Q4"
                req_year = y

            processed_requests_list.append({
                'id': str(req_data["_id"]),
                'employee_name': requester_details.get("name", "Unknown Requester"),
                'employee_grade': requester_details.get("grade", "N/A"),
                'category_name': value_add_category.get("name", "Value Add"),
                'points': req_data["points"],
                'request_date': req_data.get("request_date"),
                'processed_date': req_data.get("processed_date"),
                'status': req_data["status"],
                'manager_notes': req_data.get("manager_notes", req_data.get("response_notes", "")),
                'processed_by_name': user.get("name", "You"),
                'has_attachment': req_data.get("has_attachment", False),
                'attachment_filename': req_data.get("attachment_filename", ""),
                'quarter': req_quarter,
                'year': req_year
            })
        debug_print(f"PM_ARCH_VALIDATOR: Found {len(processed_requests_list)} processed requests by PM/Arch Validator {user.get('name')}")

    except Exception as e:
        error_print("PM_ARCH_VALIDATOR: Dashboard error", e)
        flash("An error occurred while loading the validator dashboard", "danger")
        return redirect(url_for('auth.login'))

    now = datetime.utcnow()
    current_month_name = now.strftime("%B")
    _, _, current_q_num, current_fy = get_current_quarter_date_range()

    return render_template(
        'pmarch_validator.html', 
        user=user,
        pending_requests=pending_requests_list,
        processed_requests=processed_requests_list,
        current_quarter=f"Q{current_q_num}",
        current_month=current_month_name,
        current_year=current_fy 
    )

@pm_arch_bp.route('/validator/process-request/<request_id>', methods=['POST'])
def validator_process_request(request_id):
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')

    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    # Updated permission check for acting as validator
    is_explicit_validator = (manager_level == 'PM/Arch Validator')
    is_acting_validator = False

    current_user_details = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not current_user_details: # Should not happen if user is logged in
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))

    if manager_level == 'PM/Arch':
        has_any_assigned_validator = False
        validator_fields_to_check = [
            'pm_arch_validator_id', 
            'pm_validator_id', 
            'marketing_validator_id', 
            'presales_validator_id'
        ]
        for field in validator_fields_to_check:
            if current_user_details.get(field):
                has_any_assigned_validator = True
                break
        if not has_any_assigned_validator:
            is_acting_validator = True
            debug_print(f"User {current_user_details.get('name')} is PM/Arch and acting as validator for processing request.")

    if not (is_explicit_validator or is_acting_validator):
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('pm_arch.validator_dashboard'))


    try:
        req_object_id = ObjectId(request_id)
        points_request_data = mongo.db.points_request.find_one({"_id": req_object_id})

        if not points_request_data:
            flash('Request not found', 'danger')
            return redirect(url_for('pm_arch.validator_dashboard'))

        # Authorization Check: The 'assigned_validator_id' on the request must match the logged-in validator's ID.
        if str(points_request_data.get("assigned_validator_id")) != str(user_id):
            flash(f'You are not authorized to process this specific request. Request assigned to {points_request_data.get("assigned_validator_id")}, you are {user_id}.', 'danger')
            debug_print(f"PM_ARCH_VALIDATOR: Auth fail. Request assigned_validator_id: {points_request_data.get('assigned_validator_id')}, current validator: {user_id}")
            return redirect(url_for('pm_arch.validator_dashboard'))

        action = request.form.get('action')
        notes = request.form.get('notes', '')

        # Fetch details of the user who submitted the request for flash messages
        requester_user_id = points_request_data.get("user_id")
        requester_name_for_flash = "Unknown Requester" # Default name
        if requester_user_id:
            # Assuming user_id in points_request_data is already an ObjectId
            requester_details_doc = mongo.db.users.find_one({"_id": requester_user_id})
            if requester_details_doc:
                requester_name_for_flash = requester_details_doc.get("name", "Requester")
            else:
                debug_print(f"PM_ARCH_VALIDATOR: Requester user document not found for _id {requester_user_id} during request processing.")

        if action not in ['approve', 'reject']:
            flash('Invalid action', 'danger')
            return redirect(url_for('pm_arch.validator_dashboard'))

        update_data = {
            "status": "Approved" if action == 'approve' else "Rejected",
            "processed_date": datetime.utcnow(),
            "processed_by": ObjectId(user_id),
            "manager_notes": notes,
            "response_notes": notes 
        }
        mongo.db.points_request.update_one({"_id": req_object_id}, {"$set": update_data})

        if action == 'approve':
            award_date = datetime.utcnow()
            award_month = award_date.month
            award_year = award_date.year
            points_fiscal_year = award_year if award_month >= 4 else award_year - 1
            if 4 <= award_month <= 6: points_quarter = 1
            elif 7 <= award_month <= 9: points_quarter = 2
            elif 10 <= award_month <= 12: points_quarter = 3
            else: points_quarter = 4
            
            points_entry = {
                "user_id": points_request_data["user_id"],
                "category_id": points_request_data["category_id"],
                "points": points_request_data["points"],
                "award_date": award_date,
                "awarded_by": ObjectId(user_id),
                "request_id": req_object_id,
                "notes": notes,
                "quarter": points_quarter, 
                "year": award_year # Using calendar year of award date for points table
            }
            mongo.db.points.insert_one(points_entry)

            # Javeed added this: Send email notification to the employee
            try:
                requester_employee = mongo.db.users.find_one({"_id": points_request_data["user_id"]})
                processor_validator = mongo.db.users.find_one({"_id": ObjectId(user_id)})
                category = mongo.db.categories.find_one({"_id": points_request_data["category_id"]})
                if requester_employee and processor_validator and category:
                    send_request_processed_notification(
                        points_request_data, requester_employee, processor_validator, category, 'Approved', notes
                    )
            except Exception as e:
                error_print(f"Error sending validator approval email notification for request {request_id}", e)

            flash(f'Request approved and {points_request_data["points"]} points awarded to {requester_name_for_flash}.', 'success')
        else:
            # Javeed added this: Send email notification to the employee for rejection
            try:
                requester_employee = mongo.db.users.find_one({"_id": points_request_data["user_id"]})
                processor_validator = mongo.db.users.find_one({"_id": ObjectId(user_id)})
                category = mongo.db.categories.find_one({"_id": points_request_data["category_id"]})
                if requester_employee and processor_validator and category:
                    send_request_processed_notification(
                        points_request_data, requester_employee, processor_validator, category, 'Rejected', notes
                    )
            except Exception as e:
                error_print(f"Error sending validator rejection email notification for request {request_id}", e)

            flash(f'Request from {requester_name_for_flash} rejected.', 'warning')
        
        return redirect(url_for('pm_arch.validator_dashboard'))

    except Exception as e:
        error_print(f"PM_ARCH_VALIDATOR: Error processing request {request_id}", e)
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('pm_arch.validator_dashboard'))

@pm_arch_bp.route('/validator/attachment/<request_id>', methods=['GET'])
def validator_get_attachment(request_id):
    try:
        user_id = session.get('user_id')
        manager_level = session.get('manager_level')
        
        if not user_id:
            flash('You need to log in first', 'warning')
            return redirect(url_for('auth.login'))
        
    # Updated permission check for acting as validator
        is_explicit_validator = (manager_level == 'PM/Arch Validator')
        is_acting_validator = False

        current_user_details = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not current_user_details: # Should not happen if user is logged in
            flash('User not found.', 'danger')
            return redirect(url_for('auth.login'))

        if manager_level == 'PM/Arch':
            has_any_assigned_validator = False
            validator_fields_to_check = [
                'pm_arch_validator_id', 
                'pm_validator_id', 
                'marketing_validator_id', 
                'presales_validator_id'
            ]
            for field in validator_fields_to_check:
                if current_user_details.get(field):
                    has_any_assigned_validator = True
                    break
            if not has_any_assigned_validator:
                is_acting_validator = True
                debug_print(f"User {current_user_details.get('name')} is PM/Arch and acting as validator for getting attachment.")

        if not (is_explicit_validator or is_acting_validator):
            flash('You do not have permission to access this attachment.', 'danger')
            return redirect(url_for('pm_arch.validator_dashboard'))
        request_data = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        if not request_data or not request_data.get('has_attachment') or not request_data.get('attachment_id'):
            flash('No attachment found for this request', 'warning')
            return redirect(url_for('pm_arch.validator_dashboard'))
        
        # Authorization Check: The 'assigned_validator_id' on the request must match the logged-in validator's ID.
        if str(request_data.get("assigned_validator_id")) != str(user_id):
            flash(f'You are not authorized to view this attachment. Request assigned to {request_data.get("assigned_validator_id")}, you are {user_id}.', 'danger')
            debug_print(f"PM_ARCH_VALIDATOR: Attachment Auth fail. Request assigned_validator_id: {request_data.get('assigned_validator_id')}, current validator: {user_id}")
            return redirect(url_for('pm_arch.validator_dashboard'))

        fs = GridFS(mongo.db)
        attachment_id = request_data['attachment_id']
        if not fs.exists(ObjectId(attachment_id)):
            flash('Attachment file not found', 'warning')
            return redirect(url_for('pm_arch.validator_dashboard'))
        
        grid_out = fs.get(ObjectId(attachment_id))
        file_stream = io.BytesIO(grid_out.read())
        file_stream.seek(0)
        
        original_filename = grid_out.metadata.get('original_filename', 'attachment')
        content_type = grid_out.content_type
        
        return send_file(
            file_stream,
            mimetype=content_type,
            download_name=original_filename,
            as_attachment=True
        )
        
    except Exception as e:
        error_print(f"PM_ARCH_VALIDATOR: Error retrieving attachment: {str(e)}")
        flash('An error occurred while retrieving the attachment', 'danger')
        return redirect(url_for('pm_arch.validator_dashboard'))

@pm_arch_bp.route('/check-new-requests', methods=['GET'])
def check_new_requests():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    
    manager_level = session.get('manager_level')
    if manager_level != 'PM/Arch':
        return jsonify({"error": "Not authorized"}), 403

    last_check_str = request.args.get('last_check')
    if last_check_str:
        try:
            last_check_date = datetime.fromisoformat(last_check_str.replace('Z', ''))
        except ValueError:
            last_check_date = datetime.utcnow() - timedelta(minutes=5)
    else:
        last_check_date = datetime.utcnow() - timedelta(minutes=5)

    try:
        value_add_category = mongo.db.categories.find_one({"code": "value_add"})
        if not value_add_category:
            return jsonify({"error": "Value Add category not found"}), 500

        new_requests_cursor = mongo.db.points_request.find({
            "status": "Pending",
            "category_id": value_add_category['_id'],
            "assigned_validator_id": ObjectId(user_id),
            "request_date": {"$gt": last_check_date}
        }).sort("request_date", 1)

        new_requests_list = []
        for req in new_requests_cursor:
            requester = mongo.db.users.find_one({"_id": req["user_id"]})
            if requester:
                new_requests_list.append({
                    'id': str(req["_id"]),
                    'employee_name': requester.get("name", "N/A"),
                    'category_name': value_add_category.get("name", "N/A"),
                    'points': req.get("points", 0),
                    'notes': req.get("request_notes", "")[:100]
                })

        total_pending_count = mongo.db.points_request.count_documents({
            "status": "Pending",
            "category_id": value_add_category['_id'],
            "assigned_validator_id": ObjectId(user_id)
        })

        return jsonify({
            "new_requests": new_requests_list,
            "pending_count": total_pending_count,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })

    except Exception as e:
        error_print("Error checking new PM/Arch requests", e)
        return jsonify({"error": "Server error"}), 500

@pm_arch_bp.route('/check-processed-requests', methods=['GET'])
def check_processed_requests():
    """
    Checks for requests SUBMITTED BY the current user (acting as an employee)
    that have been recently approved or rejected by a validator.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    last_check_str = request.args.get('last_check')
    if last_check_str:
        try:
            # Using fromisoformat for robust ISO 8601 parsing
            last_check_date = datetime.fromisoformat(last_check_str.replace('Z', '+00:00'))
        except ValueError:
            last_check_date = datetime.utcnow() - timedelta(minutes=5)
    else:
        # Default to checking the last 5 minutes if no timestamp is provided
        last_check_date = datetime.utcnow() - timedelta(minutes=5)

    try:
        # Find requests submitted BY this user that were recently processed
        processed_requests_cursor = mongo.db.points_request.find({
            "user_id": ObjectId(user_id), # The requester is the logged-in user
            "status": {"$in": ["Approved", "Rejected"]},
            "processed_date": {"$gt": last_check_date}
        }).sort("processed_date", 1)

        processed_requests_list = []
        for req in processed_requests_cursor:
            category = mongo.db.categories.find_one({"_id": req["category_id"]})
            validator = mongo.db.users.find_one({"_id": req.get("processed_by")})
            
            if category:
                processed_requests_list.append({
                    'id': str(req["_id"]),
                    'category_name': category.get("name", "N/A"),
                    'status': req.get("status"),
                    'validator_name': validator.get("name", "N/A") if validator else "N/A",
                    'response_notes': req.get("response_notes", "")[:100] # Truncate notes
                })

        return jsonify({
            "processed_requests": processed_requests_list,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })

    except Exception as e:
        error_print("Error checking processed PM/Arch requests", e)
        return jsonify({"error": "Server error"}), 500