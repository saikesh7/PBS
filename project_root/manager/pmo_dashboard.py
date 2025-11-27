from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, make_response
from extensions import mongo
from datetime import datetime, timedelta
import os
import traceback
import sys
from bson.objectid import ObjectId
import io
import csv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from jinja2 import Template
from config import Config

# Define Blueprint 
current_dir = os.path.dirname(os.path.abspath(__file__))

pmo_bp = Blueprint('pmo', __name__, url_prefix='/pmo', 
                      template_folder=os.path.join(current_dir, 'templates'),
                      static_folder=os.path.join(current_dir, 'static'),
                      static_url_path='/manager/static')



# Define a common filter for users considered "selectable employees" by PMO
# This includes actual employees and PM/Arch managers who have at least one validator ID assigned.
SELECTABLE_EMPLOYEE_FILTER = {
    "$or": [
        {"role": "Employee"}, # Actual employees
        { # Or, any user (typically a a manager) who has a validator ID assigned
            "$or": [ # Check if any of the relevant validator IDs exist and are not null
                {"marketing_validator_id": {"$exists": True, "$ne": None}},
                {"pm_arch_validator_id": {"$exists": True, "$ne": None}},
                {"pm_validator_id": {"$exists": True, "$ne": None}},
                {"presales_validator_id": {"$exists": True, "$ne": None}},
            ]
        }
    ]
}

# Error handling function
def error_print(message, error=None):
    print(f"ERROR - PMO: {message}", file=sys.stderr)
    if error:
        print(f"  Exception: {str(error)}", file=sys.stderr)

# Helper function to get current quarter (April-March fiscal year) - Standardized
def get_current_fiscal_quarter_details():
    now = datetime.utcnow()
    # adjusted_month_for_fiscal_quarter: April is 0, May is 1... March is 11
    adjusted_month_for_fiscal_quarter = (now.month - 4 + 12) % 12 
    current_quarter_num = (adjusted_month_for_fiscal_quarter // 3) + 1
    
    fiscal_year = now.year
    if now.month < 4: # Jan, Feb, March belong to previous fiscal year
        fiscal_year -= 1
        
    current_quarter_name = f"Q{current_quarter_num}-{fiscal_year}"
    return current_quarter_name, current_quarter_num, fiscal_year

# Helper function to get date range for a fiscal quarter (April-March) - Standardized
def get_fiscal_quarter_date_range(quarter_num, fiscal_year):
    if quarter_num == 1: # Q1 (Apr-Jun)
        start_date = datetime(fiscal_year, 4, 1)
        end_date = datetime(fiscal_year, 6, 30, 23, 59, 59)
    elif quarter_num == 2: # Q2 (Jul-Sep)
        start_date = datetime(fiscal_year, 7, 1)
        end_date = datetime(fiscal_year, 9, 30, 23, 59, 59)
    elif quarter_num == 3: # Q3 (Oct-Dec)
        start_date = datetime(fiscal_year, 10, 1)
        end_date = datetime(fiscal_year, 12, 31, 23, 59, 59)
    elif quarter_num == 4: # Q4 (Jan-Mar of next calendar year)
        start_date = datetime(fiscal_year + 1, 1, 1)
        end_date = datetime(fiscal_year + 1, 3, 31, 23, 59, 59)
    else:
        raise ValueError("Invalid quarter number")
    return start_date, end_date

def has_existing_utilization_record(employee_id, category_id, event_date):
    """Check if an employee already has a utilization_billable record for the specified month."""
    start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 else start_of_month.replace(year=start_of_month.year + 1, month=1))
    
    existing_record = mongo.db.points_request.find_one({
        "user_id": ObjectId(employee_id),
        "category_id": ObjectId(category_id),
        "event_date": {
            "$gte": start_of_month,
            "$lt": next_month
        },
        "status": {"$in": ["Approved", "Pending"]} # Check for both approved and pending
    })
    return existing_record
 
def _process_bulk_award_upload(file, user, pmo_validator_manager_id):
    """Helper function to process bulk award upload (Spot Award, Client Appreciation, R&R)"""
    errors = []
    successes = []
    successful_requests = []
    success_count = 0
    error_count = 0
    
    try:
        # It's better to leave the file stream open for the caller to handle if needed
        # but for this use case, reading it once is fine.
        # To be safe, let's ensure the file can be re-read if necessary.
        file.seek(0)
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        expected_headers = ['employee_id', 'event_date', 'category_code', 'department', 'notes']
        actual_headers = csv_reader.fieldnames
        if actual_headers != expected_headers:
            errors.append("Invalid template used. Expected headers: employee_id, event_date, category_code, department, notes.")
            return errors, successes, successful_requests, success_count, error_count

        valid_categories_for_bulk = ['spot_award', 'client_appreciation', 'r&r']
        
        for row_num, row in enumerate(csv_reader, start=1):
            try:
                employee_id = row.get('employee_id', '').strip()
                event_date_str = row.get('event_date', '').strip()
                category_code = row.get('category_code', '').strip()
                department = row.get('department', '').strip()
                notes = row.get('notes', '').strip()
                
                if not employee_id or not event_date_str or not category_code or not notes:
                    errors.append(f"Row {row_num}: Missing required fields (employee_id, event_date, category_code, or notes).")
                    error_count += 1
                    continue

                try:
                    event_date = datetime.strptime(event_date_str, '%d-%m-%Y')
                    if event_date.date() > datetime.utcnow().date():
                        errors.append(f"Row {row_num}: Event date '{event_date_str}' cannot be in the future.")
                        error_count += 1
                        continue
                except ValueError:
                    errors.append(f"Row {row_num}: Invalid event_date format for '{event_date_str}'. Use DD-MM-YYYY.")
                    error_count += 1
                    continue
                
                if category_code not in valid_categories_for_bulk:
                    errors.append(f"Row {row_num}: Invalid category_code '{category_code}'. Must be one of {valid_categories_for_bulk}.")
                    error_count += 1
                    continue
                
                employee_query = {"employee_id": employee_id}
                employee_query.update(SELECTABLE_EMPLOYEE_FILTER)
                employee = mongo.db.users.find_one(employee_query)
                if not employee:
                    errors.append(f"Row {row_num}: Employee ID {employee_id} not found in database.")
                    error_count += 1
                    continue
                
                category = mongo.db.categories.find_one({"code": category_code})
                if not category:
                    errors.append(f"Row {row_num}: Category code {category_code} not found in database.")
                    error_count += 1
                    continue
                
                employee_grade = employee.get('grade')
                if not employee_grade:
                    errors.append(f"Row {row_num}: Employee {employee_id} has no grade assigned.")
                    error_count += 1
                    continue
                
                points_per_unit = category.get('points_per_unit', 0)
                if points_per_unit <= 0:
                    errors.append(f"Row {row_num}: Category {category_code} has invalid or zero points_per_unit.")
                    error_count += 1
                    continue
                
                request_data = {
                    "user_id": ObjectId(employee["_id"]),
                    "category_id": ObjectId(category["_id"]),
                    "points": points_per_unit,
                    "request_notes": notes,
                    "updated_by": "PMO",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date,
                    "created_by_pmo_id": ObjectId(user['_id']),
                }
                
                # MODIFICATION: Route request to HR for 'r&r' category, otherwise to PMO Validator
                if category.get('code') == 'r&r':
                    request_data["pending_hr_approval"] = True
                else:
                    request_data["pending_validator_id"] = ObjectId(pmo_validator_manager_id)
                
                mongo.db.points_request.insert_one(request_data)
                
                successful_requests.append({
                    "employee_id": employee_id,
                    "points": points_per_unit,
                    "category_id": category["_id"],
                    "category_code": category.get("code") # Return category code for easier notification routing
                })
                
                success_count += 1
                successes.append(f"Row {row_num}: {category.get('name', category_code)} for {employee_id} ({points_per_unit} points) submitted.")
                
            except Exception as row_error:
                error_print(f"Error processing bulk award row {row_num}", row_error)
                errors.append(f"Row {row_num}: An unexpected error occurred: {str(row_error)}")
                error_count += 1
                
    except Exception as e:
        error_print("Error in _process_bulk_award_upload", e)
        errors.append(f"An unexpected error occurred during bulk upload processing: {str(e)}")
        
    return errors, successes, successful_requests, success_count, error_count

def get_current_utilization(file,employee_id, current_date,user,pmo_validator_manager_id):
    """Helper function to process bulk award upload (Spot Award, Client Appreciation, R&R)"""
    errors = []
    successes = []
    successful_requests = []
    success_count = 0
    error_count = 0
    
    try:
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        expected_headers = ['employee_id', 'category_code', 'department', 'notes']
        actual_headers = csv_reader.fieldnames
        if actual_headers != expected_headers:
            errors.append("Invalid template used. Expected headers: employee_id, category_code, department, notes.")
            return errors, successes, successful_requests # Return immediately if headers are wrong
        
        valid_categories_for_bulk = ['spot_award', 'client_appreciation', 'r&r']
        
        for row_num, row in enumerate(csv_reader, start=1):
            try:
                employee_id = row.get('employee_id', '').strip()
                category_code = row.get('category_code', '').strip()
                department = row.get('department', '').strip()
                notes = row.get('notes', '').strip()
                
                if not employee_id or not category_code or not notes:
                    errors.append(f"Row {row_num}: Missing required fields (employee_id, category_code, or notes).")
                    error_count += 1
                    continue
                
                if category_code not in valid_categories_for_bulk:
                    errors.append(f"Row {row_num}: Invalid category_code '{category_code}'. Must be one of {valid_categories_for_bulk}.")
                    error_count += 1
                    continue
                
                employee_query = {"employee_id": employee_id}
                employee_query.update(SELECTABLE_EMPLOYEE_FILTER)
                employee = mongo.db.users.find_one(employee_query)
                if not employee:
                    errors.append(f"Row {row_num}: Employee ID {employee_id} not found in database.")
                    error_count += 1
                    continue
                
                category = mongo.db.categories.find_one({"code": category_code})
                if not category:
                    errors.append(f"Row {row_num}: Category code {category_code} not found in database.")
                    error_count += 1
                    continue
                
                employee_grade = employee.get('grade')
                if not employee_grade:
                    errors.append(f"Row {row_num}: Employee {employee_id} has no grade assigned.")
                    error_count += 1
                    continue
                
                points_per_unit = category.get('points_per_unit', 0)
                if points_per_unit <= 0:
                    errors.append(f"Row {row_num}: Category {category_code} has invalid or zero points_per_unit.")
                    error_count += 1
                    continue
                
                # Create the points_request entry
                request_data = {
                    "user_id": ObjectId(employee["_id"]),
                    "category_id": ObjectId(category["_id"]),
                    "points": points_per_unit, # Use points_per_unit for these categories
                    "request_notes": notes,
                    "updated_by": "PMO",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "created_by_pmo_id": ObjectId(user['_id']),
                    "pending_validator_id": ObjectId(pmo_validator_manager_id)
                }
                
                mongo.db.points_request.insert_one(request_data)
                
                successful_requests.append({
                    "employee_id": employee_id,
                    "points": points_per_unit,
                    "category_id": category["_id"]
                })
                
                success_count += 1
                successes.append(f"Row {row_num}: {category.get('name', category_code)} for employee {employee_id} ({points_per_unit} points) submitted for approval.")
                
            except Exception as row_error:
                error_print(f"Error processing bulk award row {row_num}", row_error)
                errors.append(f"Row {row_num}: {str(row_error)}")
                error_count += 1
                
    except Exception as e:
        error_print("Error in _process_bulk_award_upload", e)
        errors.append(f"An unexpected error occurred during bulk upload processing: {str(e)}")
        
    return errors, successes, successful_requests

# Helper function to process utilization upload
def _process_utilization_upload(file, user, pmo_validator_manager_id):
    errors = []
    successes = []
    successful_requests = []
    success_count = 0
    error_count = 0
    
    try:
        # Ensure file can be re-read
        file.seek(0)
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        expected_headers = ['employee_id', 'event_date', 'category_code', 'department', 'utilization', 'notes']
        actual_headers = csv_reader.fieldnames
        if actual_headers != expected_headers:
            errors.append("Invalid template used. Expected headers: employee_id, event_date, category_code, department, utilization, notes.")
            return errors, successes, successful_requests, success_count, error_count
        
        valid_category_for_utilization = 'utilization_billable'
        current_date = datetime.utcnow()
        
        for row_num, row in enumerate(csv_reader, start=1):
            try:
                employee_id = row.get('employee_id', '').strip()
                event_date_str = row.get('event_date', '').strip()
                category_code = row.get('category_code', '').strip()
                department = row.get('department', '').strip()
                utilization_str = row.get('utilization', '').strip()
                notes = row.get('notes', '').strip()
                
                if not employee_id or not event_date_str or not category_code or not utilization_str or not notes:
                    errors.append(f"Row {row_num}: Missing required fields (employee_id, event_date, category_code, utilization, or notes).")
                    error_count += 1
                    continue

                try:
                    event_date = datetime.strptime(event_date_str, '%d-%m-%Y')
                    # MODIFICATION: Check if event date is in the future and skip if it is.
                    if event_date.date() > datetime.utcnow().date():
                        errors.append(f"Row {row_num}: Event date '{event_date_str}' cannot be in the future.")
                        error_count += 1
                        continue
                except ValueError:
                    errors.append(f"Row {row_num}: Invalid event_date format for '{event_date_str}'. Use DD-MM-YYYY.")
                    error_count += 1
                    continue
                
                if category_code != valid_category_for_utilization:
                    errors.append(f"Row {row_num}: Invalid category_code '{category_code}'. Only '{valid_category_for_utilization}' is allowed for utilization upload.")
                    error_count += 1
                    continue
                
                employee_query = {"employee_id": employee_id}
                employee_query.update(SELECTABLE_EMPLOYEE_FILTER)
                employee = mongo.db.users.find_one(employee_query)
                if not employee:
                    errors.append(f"Row {row_num}: Employee ID {employee_id} not found in database.")
                    error_count += 1
                    continue
                
                category = mongo.db.categories.find_one({"code": category_code})
                if not category:
                    errors.append(f"Row {row_num}: Category code {category_code} not found in database.")
                    error_count += 1
                    continue
                
                employee_grade = employee.get('grade')
                if not employee_grade:
                    errors.append(f"Row {row_num}: Employee {employee_id} has no grade assigned.")
                    error_count += 1
                    continue
                
                existing_record = has_existing_utilization_record(employee["_id"], category["_id"], event_date)
                if existing_record:
                    errors.append(f"Row {row_num}: Utilization record for {employee_id} already exists for the month of {event_date.strftime('%B %Y')}.")
                    error_count += 1
                    continue
                
                try:
                    utilization_cleaned = utilization_str.replace('%', '').strip()
                    utilization_value = float(utilization_cleaned)
                    if utilization_value > 1:
                        utilization_value /= 100.0
                    if not (0 <= utilization_value <= 1):
                        errors.append(f"Row {row_num}: Utilization value must be between 0 and 1 (or 0% to 100%).")
                        error_count += 1
                        continue
                except ValueError:
                    errors.append(f"Row {row_num}: Invalid utilization value (enter a number like 0.88 or 88%).")
                    error_count += 1
                    continue
                
                request_data = {
                    "user_id": ObjectId(employee["_id"]),
                    "category_id": ObjectId(category["_id"]),
                    "points": 0,
                    "utilization_value": utilization_value,
                    "request_notes": notes,
                    "updated_by": "PMO",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date,
                    "created_by_pmo_id": ObjectId(user['_id']),
                    "pending_validator_id": ObjectId(pmo_validator_manager_id)
                }
                
                mongo.db.points_request.insert_one(request_data)
                
                successful_requests.append({
                    "employee_id": employee_id,
                    "points": 0,
                    "category_id": category["_id"],
                    "utilization_value": utilization_value
                })
                
                success_count += 1
                successes.append(f"Row {row_num}: Utilization ({utilization_value:.2%}) for {employee_id} submitted for approval.")
                
            except Exception as row_error:
                error_print(f"Error processing utilization upload row {row_num}", row_error)
                errors.append(f"Row {row_num}: An unexpected error occurred: {str(row_error)}")
                error_count += 1
                
    except Exception as e:
        error_print("Error in _process_utilization_upload", e)
        errors.append(f"An unexpected error occurred during utilization upload processing: {str(e)}")
        
    return errors, successes, successful_requests, success_count, error_count

def _get_current_utilization(employee_id, current_date):
    """Fetch the most recent utilization value for an employee for the current month."""
    start_of_month = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 else start_of_month.replace(year=start_of_month.year + 1, month=1))
    
    # Find the category for utilization_billable
    category = mongo.db.categories.find_one({"code": "utilization_billable"})
    if not category:
        return None
    
    # Find the most recent approved utilization record for the current month
    utilization_record = mongo.db.points_request.find_one({
        "user_id": ObjectId(employee_id),
        "category_id": ObjectId(category["_id"]),
        "event_date": {
            "$gte": start_of_month,
            "$lt": next_month
        },
        "status": "Approved"
    }, sort=[("event_date", -1)])  # Sort by event_date descending to get the most recent
    
    if utilization_record and "utilization_value" in utilization_record:
        return utilization_record["utilization_value"]
    return None

@pmo_bp.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    # Get user ID from the session
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    

    # Define valid grades that should be displayed
    VALID_GRADES = ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']

    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    employee_filter = {
    **SELECTABLE_EMPLOYEE_FILTER,
    "grade": {"$in": VALID_GRADES}
}

    # Verify manager level
    if manager_level != 'PMO':
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('manager.dashboard')) # Or a generic access denied page
    

    try:
        # Get manager information
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))

        # If the PMO user does NOT have a manager_id, they are a Validator.
        # Redirect them to the pmo_validator_dashboard.
        if not user.get('manager_id'):
            return redirect(url_for('pmo.validator_dashboard'))

        is_pmo_updater = True # This route is now only for updaters
        pmo_validator_manager_id = user.get('manager_id')

        # Clear previous bulk_upload_errors at the start of the request
        bulk_upload_errors = session.pop('bulk_upload_errors', [])
        bulk_upload_successes = session.pop('bulk_upload_successes', [])  # Added to track successes
        
        # Handle POST request for assigning rewards
        if request.method == 'POST': # This block handles all POST actions
            action_type = request.form.get('action_type') # Determine which form was submitted
            if action_type == 'assign_reward': # Single Reward Assignment
                employee_id = request.form.get('employee_id') # Get employee ID from form
                category_id = request.form.get('category_id')
                notes = request.form.get('notes', '')
                category_id = request.form.get('category_id')
                event_date_str = request.form.get('event_date') # Get event date string

                if event_date_str:
                    try:
                        event_date = datetime.strptime(event_date_str, '%Y-%m-%d')
                    except ValueError:
                        flash('Invalid event date format.', 'danger')
                        return redirect(url_for('pmo.dashboard'))
                else:
                    event_date = datetime.utcnow()

                confirmed = request.form.get('confirmed', 'false')
                utilization = request.form.get('utilization')  # Added to capture utilization from form
                
                if not employee_id or not category_id:
                    flash('Invalid request parameters', 'danger')
                elif confirmed != 'true':
                    flash('Please confirm your submission', 'warning')
                else:
                    # Get employee and category details
                    employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
                    category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
                    
                    if not employee or not category:
                        flash('Employee or category not found', 'danger')
                    else:
                        # Get the employee's grade
                        employee_grade = employee.get('grade')
                        if not employee_grade:
                            flash('Employee grade not found', 'danger')
                        else:
                            # Check for existing utilization record in the current month
                            if category.get('code') == 'utilization_billable':
                                existing_record = has_existing_utilization_record(employee_id, category_id, event_date)
                                if existing_record:
                                    flash(f"Utilization record for {employee['name']} already exists for this month. Please edit the existing record.", 'danger')
                                    return redirect(url_for('pmo.dashboard'))
                            
                            assigned_utilization = None
                            if category.get('code') == 'utilization_billable':
                                if not utilization:
                                    flash('Utilization value required for Utilization/Billable category', 'danger')
                                    return redirect(url_for('pmo.dashboard'))
                                try:
                                    utilization_value = float(utilization)
                                    assigned_utilization = utilization_value
                                    points_per_unit = 0  # No points for utilization_billable
                                except ValueError:
                                    flash('Invalid utilization value', 'danger')
                                    return redirect(url_for('pmo.dashboard'))
                            else: # Non-utilization categories
                                points_per_unit = category.get('points_per_unit', 0)
                            event_date = datetime.strptime(event_date_str, '%Y-%m-%d') if event_date_str else datetime.utcnow()
                            # PMO Updater: Request goes to Pending
                            request_data = {
                                "user_id": ObjectId(employee_id),
                                "category_id": ObjectId(category_id),
                                "points": points_per_unit if category.get('code') != 'utilization_billable' else 0,
                                "status": "Pending",
                                "request_date": datetime.utcnow(),
                                "event_date": event_date, 
                                "request_notes":f" {notes}" if notes else "",
                                "created_by_pmo_id": ObjectId(user_id),
                                "updated_by": "PMO",
                            }
                            if assigned_utilization is not None:
                                request_data["utilization_value"] = assigned_utilization

                            # MODIFIED: Route request to HR for 'r&r' category, otherwise to PMO Validator
                            if category.get('code') == 'r&r':
                                request_data["pending_hr_approval"] = True
                                mongo.db.points_request.insert_one(request_data)
                                
                                # --- MODIFICATION START ---
                                # A notification to HR should be sent here
                                hr_request_details = [{
                                    "employee_id": employee.get("employee_id", "N/A"),
                                    "employee_name": employee.get("name"),
                                    "department": employee.get("department", "N/A"),
                                    "points": request_data.get("points"),
                                    "notes": request_data.get("request_notes", "")
                                }]
                                # Assuming a function 'send_hr_approval_notification' exists
                                send_hr_approval_notification(hr_request_details, user)
                                # --- MODIFICATION END ---
                                
                                flash(f'R&R request for {employee["name"]} has been submitted to HR for approval.', 'info')
                            else:
                                request_data["pending_validator_id"] = ObjectId(pmo_validator_manager_id)
                                # Insert the request
                                mongo.db.points_request.insert_one(request_data)

                                # Get validator details for notification
                                validator = mongo.db.users.find_one({"_id": ObjectId(pmo_validator_manager_id)})
                                
                                # Send notification to validator
                                send_single_request_notification(
                                    request_data=request_data,
                                    employee=employee,
                                    validator=validator,
                                    updater=user,
                                    category=category
                                )

                                if category.get('code') == 'utilization_billable':
                                    flash(f'Utilization submission for {employee["name"]} sent for approval.', 'info')
                                else:
                                    flash(f'Reward request for {employee["name"]} submitted for approval.', 'info')
            
            # Edit Utilization Record
            elif action_type == 'edit_utilization': # This action is handled by both updater and validator
                request_id = request.form.get('request_id')
                new_utilization = request.form.get('new_utilization')
                notes = request.form.get('notes', '')
                
                if not request_id or not new_utilization:
                    flash('Missing required fields for editing utilization', 'danger')
                else:
                    try:
                        # Validate and parse the new utilization value
                        new_utilization_cleaned = new_utilization.replace('%', '').strip()
                        if not new_utilization_cleaned:
                            flash('Utilization value cannot be empty', 'danger')
                            return redirect(url_for('pmo.dashboard'))
                        utilization_value = float(new_utilization_cleaned)
                        if utilization_value > 1:
                            utilization_value = utilization_value / 100.0
                        if utilization_value < 0 or utilization_value > 1:
                            flash('Utilization value must be between 0 and 1 (or 0% to 100%)', 'danger')
                            return redirect(url_for('pmo.dashboard'))
                        
                        # Find the existing record
                        existing_request = mongo.db.points_request.find_one({
                            "_id": ObjectId(request_id),
                            "pmo_id": ObjectId(user_id), # Ensures only the PMO who actioned it can edit
                            "status": "Approved"
                        })
                        if not existing_request:
                            flash('Utilization record not found or you do not have permission to edit it', 'danger')
                            return redirect(url_for('pmo.dashboard'))
                        
                        # Verify the record is for utilization_billable
                        category = mongo.db.categories.find_one({"_id": existing_request["category_id"]})
                        if not category or category.get('code') != 'utilization_billable':
                            flash('This record is not a Utilization/Billable entry', 'danger')
                            return redirect(url_for('pmo.dashboard'))
                        
                        # Verify the record is from the current month
                        current_date = datetime.utcnow()
                        start_of_month = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                        next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 else start_of_month.replace(year=start_of_month.year + 1, month=1))
                        # Check if the event_date (the month the utilization is for) is in the current month
                        event_date = existing_request.get("event_date", existing_request["request_date"])
                        if not (start_of_month <= event_date < next_month):
                            flash('Can only edit utilization records from the current month', 'danger')
                            return redirect(url_for('pmo.dashboard'))
                        
                        # Update the existing record
                        mongo.db.points_request.update_one(
                            {"_id": ObjectId(request_id)},
                            {
                                "$set": {
                                    "utilization_value": utilization_value,
                                    # Standardized notes for Updater editing (if they are the pmo_id)
                                    "response_notes": f"Utilization updated to {utilization_value:.2%} by PMO: {user.get('name', 'N/A')}" + (f" - Notes: {notes}" if notes else ""),
                                    "response_date": datetime.utcnow(),
                                    "updated_by": "PMO"
                                }
                            }
                        )
                        flash(f'Utilization record updated to {utilization_value:.2%}', 'success')
                    except ValueError:
                        flash('Invalid utilization value (enter a number like 0.88 or 88%)', 'danger')
                    except Exception as e:
                        error_print("Error editing utilization record", e)
                        flash('Error editing utilization record', 'danger')

            # MODIFICATION: This block now calls the helper function to ensure correct validation logic is used.
            elif action_type == 'bulk_upload':
                print("Processing bulk award upload request...", file=sys.stderr)
                if 'csv_file' not in request.files:
                    flash('No file uploaded', 'danger')
                else:
                    file = request.files['csv_file']
                    if file.filename == '':
                        flash('No file selected', 'danger')
                    elif not file.filename.endswith('.csv'):
                        flash('Please upload a CSV file', 'danger')
                    else:
                        # Use the helper function for consistent and correct validation, including future date checks.
                        errors, successes, successful_requests, success_count, error_count = _process_bulk_award_upload(file, user, pmo_validator_manager_id)

                        session['bulk_upload_errors'] = errors if errors else []
                        session['bulk_upload_successes'] = successes if successes else []

                        # After processing, send consolidated notifications
                        if success_count > 0:
                            requests_for_validator = []
                            requests_for_hr = []

                            for req in successful_requests:
                                # The helper now returns 'category_code' to simplify routing
                                if req.get('category_code') == 'r&r':
                                    employee = mongo.db.users.find_one({"employee_id": req['employee_id']})
                                    if employee:
                                        requests_for_hr.append({
                                            "employee_id": employee.get("employee_id", "N/A"),
                                            "employee_name": employee.get("name"),
                                            "department": employee.get("department", "N/A"),
                                            "points": req.get("points"),
                                            "notes": "From bulk upload"
                                        })
                                else:
                                    requests_for_validator.append(req)

                            if requests_for_validator:
                                validator = mongo.db.users.find_one({"_id": ObjectId(pmo_validator_manager_id)})
                                send_bulk_requests_notification(
                                    requests_data=requests_for_validator,
                                    validator=validator,
                                    updater=user
                                )
                            
                            if requests_for_hr:
                                send_hr_approval_notification(requests_for_hr, user)
                            
                            flash(f'Successfully processed {success_count} records from CSV', 'success')
                        else:
                            flash('No records were processed successfully. Check the errors below.', 'warning')
                        
                        if error_count > 0:
                            flash(f'{error_count} errors occurred during processing. See details below.', 'warning')

            # Utilization Upload via CSV (for Utilization/Billable only)
            elif action_type == 'utilization_upload': # This is for Utilization/Billable only
                print("Processing utilization upload request...", file=sys.stderr)
                if 'csv_file' not in request.files:
                    print("No csv_file found in request.files", file=sys.stderr)
                    flash('No file uploaded', 'danger')
                else:
                    file = request.files['csv_file']
                    print(f"File received: {file.filename}", file=sys.stderr)
                    if file.filename == '':
                        print("Empty filename detected", file=sys.stderr)
                        flash('No file selected', 'danger')
                    elif not file.filename.endswith('.csv'):
                        print("File is not a CSV", file=sys.stderr)
                        flash('Please upload a CSV file', 'danger')
                    else:
                        # Call the utilization processing helper function, which has the correct validation logic.
                        errors, successes, successful_requests, success_count, error_count = _process_utilization_upload(file, user, pmo_validator_manager_id)
                        
                        session['bulk_upload_errors'] = errors if errors else []
                        session['bulk_upload_successes'] = successes if successes else []
                        
                        if success_count > 0:
                            validator = mongo.db.users.find_one({"_id": ObjectId(pmo_validator_manager_id)})
                            if successful_requests and validator:
                                send_bulk_requests_notification(
                                    requests_data=successful_requests,
                                    validator=validator,
                                    updater=user
                                )
                            flash(f'Successfully processed {success_count} utilization records from CSV', 'success')
                        else:
                            flash('No records were processed successfully. Check the errors below.', 'warning')
                        
                        if error_count > 0:
                            flash(f'{error_count} errors occurred during processing. See details below.', 'warning')

                return redirect(url_for('pmo.dashboard'))

            return redirect(url_for('pmo.dashboard'))

        # Clear previous bulk_upload_errors at the start of GET request or after POST
        bulk_upload_errors = session.pop('bulk_upload_errors', [])
        bulk_upload_successes = session.pop('bulk_upload_successes', [])

        # Define the required PMO categories
        required_categories = [
            {
                "name": "Spot Award",
                "code": "spot_award",
                "description": "Recognition for exceptional performance",
                "frequency": "Quarterly",
                "updated_by": "PMO",
                "points_per_unit": 400,
                "minimum_points_for_bonus": 800
            },
            {
                "name": "Client Appreciation",
                "code": "client_appreciation",
                "description": "Recognition for client appreciation",
                "frequency": "Quarterly",
                "updated_by": "PMO",
                "points_per_unit": 400,
                "minimum_points_for_bonus": 800
            },
            {
                "name": "R&R",
                "code": "r&r",
                "description": "Rewards and Recognition for outstanding contributions",
                "frequency": "Quarterly",
                "updated_by": "PMO",
                "points_per_unit": 400,
                "minimum_points_for_bonus": 800
            },
            {
                "name": "Utilization/Billable",
                "code": "utilization_billable",
                "description": "Tracks utilization percentages for employees (recorded as a percentage like 88%)",
                "frequency": "Monthly",
                "updated_by": "PMO",
                "points_per_unit": 0
            }
        ]

        pmo_categories = []
        for category in required_categories:
            existing_category = mongo.db.categories.find_one({"code": category["code"]})
            if not existing_category:
                mongo.db.categories.insert_one(category)
                pmo_categories.append(category)
            else:
                pmo_categories.append(existing_category)
        
        # Create category_name_map
        category_name_map = {category['code']: category['name'] for category in pmo_categories}
        
        # This variable can remain if it's used for other specific "Employee" role purposes.
        # For the dropdowns, we'll use a more inclusive list.
        category_points_map = {category['code']: category['points_per_unit'] for category in pmo_categories}
        
        # Only fetch employees that match the valid grades
        all_employees = list(mongo.db.users.find({
                **SELECTABLE_EMPLOYEE_FILTER,
                "grade": {"$in": VALID_GRADES}
            }))

        
        # Fetch users for populating department and grade dropdowns in "Assign Rewards"
        users_for_dept_grade_map_cursor = mongo.db.users.find({
            "$and": [
                {'department': {'$exists': True, '$ne': None}},
                {'grade': {'$exists': True, '$ne': None}},
                {"grade": {"$in": VALID_GRADES}},
                SELECTABLE_EMPLOYEE_FILTER
            ]
        })
        
        department_grades_map = {}
        for emp in users_for_dept_grade_map_cursor:
            department = emp.get('department') # Already checked for existence and not None
            grade = emp.get('grade')         # Already checked for existence and not None
            
            if department not in department_grades_map:
                department_grades_map[department] = set()
            department_grades_map[department].add(grade)
        
        # Sort grades within each department and then sort departments by name
        for department_key in department_grades_map:
            department_grades_map[department_key] = sorted(list(department_grades_map[department_key]))
        sorted_department_grades_map = dict(sorted(department_grades_map.items()))
        
        # Fetch history data for the Updater PMO
        (all_requests_history, _, 
         departments_for_assign_form, pmo_categories_for_assign_form, _, # _ is for all_employees_list
         filter_quarters_list, filter_categories_list, filter_departments_list, sorted_history_fiscal_years) = _get_history_data_for_pmo(user_id, is_pmo_updater=True)


        
        # Updaters do not see pending requests to review on their dashboard
        pending_requests_to_review = [] 
        
        # Get current fiscal quarter details
        current_quarter_name_display, _, _ = get_current_fiscal_quarter_details()
        now = datetime.utcnow()
        current_month = now.strftime("%B %Y")
        return render_template('pmo_dashboard.html',
                              user=user,
                              pmo_categories=pmo_categories,
                              category_points_map=category_points_map,
                              category_name_map=category_name_map, 
                              all_employees=all_employees, # This remains Employee-only if used elsewhere for that
                              departments=departments_for_assign_form, # For assign reward department dropdown keys
                              department_grades_map=sorted_department_grades_map, # For JS in assign reward to populate grades
                              all_requests=all_requests_history, # For the history tab
                              pending_requests=pending_requests_to_review, # Empty for updaters
                              is_pmo_updater=is_pmo_updater, # Will be True
                              bulk_upload_errors=bulk_upload_errors,
                              bulk_upload_successes=bulk_upload_successes,  # Pass successes to template
                              # Dynamic filter options
                              filter_quarters=filter_quarters_list,
                              filter_categories=filter_categories_list,
                              filter_departments=filter_departments_list,
                              filter_years=sorted_history_fiscal_years, # Pass fiscal years for the filter
                              current_quarter=current_quarter_name_display, # Use April-March fiscal quarter
                              current_month=current_month)
    
    except Exception as e:
        error_print("PMO Dashboard Error", e)
        flash('An error occurred while loading the dashboard', 'danger')
        return redirect(url_for('auth.login'))

@pmo_bp.route('/get-employees-by-department-grade', methods=['POST'])
def get_employees_by_department_grade():
    """API to get employees filtered by department and grade"""
    if session.get('manager_level') != 'PMO':
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        department = request.form.get('department')
        grade = request.form.get('grade')
        
        if not department or not grade:
            return jsonify({'error': 'Department and grade are required'}), 400
        
        # Find employees matching criteria, including Employees and PM/Arch managers
        # PMO dashboard should only see actual employees for selection
        # Updated to use SELECTABLE_EMPLOYEE_FILTER
        query = {
            "$and": [
                SELECTABLE_EMPLOYEE_FILTER,
                {"employee_id": {"$exists": True, "$ne": None}},
                {"department": {"$exists": True, "$ne": None}}, # Useful if "all" departments is selected
                {"grade": {"$exists": True, "$ne": None}}      # Useful if "all" grades is selected
            ]
        }
        
        if department != "all":
            query["department"] = department
        
        if grade != "all":
            query["grade"] = grade
        
        employees = list(mongo.db.users.find(query, {"name": 1, "employee_id": 1, "_id": 1}))
        
        # Format for response
        employee_list = []
        for emp in employees:
            employee_list.append({
                'id': str(emp['_id']),
                'name': emp.get('name', 'Unknown'),
                'employee_id': emp.get('employee_id', 'N/A')
            })
        
        return jsonify({
            'success': True,
            'employees': employee_list
        })
    
    except Exception as e:
        error_print("Error fetching employees", e)
        return jsonify({'error': str(e)}), 500

@pmo_bp.route('/get-category-details', methods=['POST'])
def get_category_details():
    """API to get category details for selected category"""
    if session.get('manager_level') != 'PMO':
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        category_id = request.form.get('category_id')
        employee_id = request.form.get('employee_id')
        new_utilization = request.form.get('new_utilization')  # Added to handle dynamic utilization updates
        event_date_str = request.form.get('event_date')  # Added to handle event date for utilization checks
        
        if not category_id:
            return jsonify({'error': 'Category ID is required'}), 400
        
        # Get category details
        category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        if not category:
            return jsonify({'error': 'Category not found'}), 404
        
        result = {
            'id': str(category['_id']),
            'name': category.get('name', ''),
            'description': category.get('description', ''),
            'frequency': category.get('frequency', 'Quarterly'),
            'points_per_unit': category.get('points_per_unit', 0),
            'code': category.get('code', '')
        }
        
        # If employee ID is provided, fetch additional details
        if employee_id:
            employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
            if employee:
                grade = employee.get('grade')
                if grade:
                    result['employee_grade'] = grade
                    # Check if employee grade is A1 and category is Utilization/Billable
                    # if grade == 'A1' and category.get('code') == 'utilization_billable':
                    #     result['can_award'] = False
                    #     result['error'] = 'A1 employees are not eligible for Utilization/Billable category'
                    if category.get('code') == 'utilization_billable':
                        # Use event date if provided, otherwise use current date
                        if event_date_str:
                            try:
                                check_date = datetime.strptime(event_date_str, '%Y-%m-%d')
                            except ValueError:
                                check_date = datetime.utcnow()
                        else:
                            check_date = datetime.utcnow()
                        
                        # Define these dates for the check based on the event date
                        start_of_month_for_check = check_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                        next_month_start = (start_of_month_for_check.replace(month=start_of_month_for_check.month % 12 + 1) if start_of_month_for_check.month < 12 else start_of_month_for_check.replace(year=start_of_month_for_check.year + 1, month=1))
                        
                        # Check for existing utilization record for the specified month
                        existing_record = mongo.db.points_request.find_one({
                            "user_id": ObjectId(employee_id),
                            "category_id": ObjectId(category_id),
                            "event_date": {"$gte": start_of_month_for_check, "$lt": next_month_start},
                            "status": {"$in": ["Approved", "Pending"]}
                        })
                        if existing_record:
                            result['can_award'] = False
                            month_year = check_date.strftime('%B %Y')
                            result['error'] = f'A utilization record for this employee for {month_year} already exists (Status: {existing_record["status"]}).'
                        else:
                            # Include the new utilization value if provided, otherwise use 0 as a placeholder
                            employee_utilization = float(new_utilization) if new_utilization else 0
                            result['utilization'] = employee_utilization
                            result['can_award'] = True  # Always allow assignment if no existing record for that month
                            result['error'] = None
                    else:
                        # For Spot Award, Client Appreciation, R&R: no limit
                        result['can_award'] = True
                        result['error'] = None
        
        return jsonify(result)
    
    except Exception as e:
        error_print("Error fetching category details", e)
        return jsonify({'error': str(e)}), 500


@pmo_bp.route('/validate-bulk-upload', methods=['POST'])
def validate_bulk_upload():
    """API to validate a CSV file for bulk upload (Spot Award, Client Appreciation, R&R only)"""
    if session.get('manager_level') != 'PMO':
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        if 'csv_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['csv_file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'Please upload a CSV file'}), 400
        
        # Process CSV for validation only
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        validation_results = {
            'total_rows': 0,
            'valid_rows': 0,
            'invalid_rows': 0,
            'warnings': [],
            'errors': [],
            'summary': {
                'categories': {},
                'departments_entered': 0,
                'notes_entered': 0
            },
            'rows': []  # To store row data for preview
        }
        
        # Validate the template structure
        expected_headers = ['employee_id', 'event_date', 'category_code', 'department', 'notes']
        actual_headers = csv_reader.fieldnames
        if actual_headers != expected_headers:
            validation_results['errors'].append(
                "Invalid template used. Please use the Bulk Upload template. Expected headers: employee_id, event_date, category_code, department, notes."
            )
            return jsonify(validation_results), 400
        valid_categories = ['spot_award', 'client_appreciation', 'r&r']
        
        # Reset file pointer
        file.seek(0)
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        approved_requests = []
        rejected_requests = []
        # Dictionary to group approved requests by employee_id for bulk notifications
        employee_approved_requests = {}
        
        # Get the updater (assuming the current user is the PMO updater)
        updater = mongo.db.users.find_one({'_id': ObjectId(session.get('user_id'))})
        if not updater:
            return jsonify({'error': 'Updater not found'}), 400
        
        # Get the validator (modify based on your system's validator logic)
        validator = updater  # Adjust this to fetch the correct validator
        print(f"Updater: {updater.get('name', 'Unknown')} ({updater.get('email', 'Unknown')})")
        print(f"Validator: {validator.get('name', 'Unknown')} ({validator.get('email', 'Unknown')})")
        
        # Validate each row
        for row_num, row in enumerate(csv_reader, start=1):
            validation_results['total_rows'] += 1
            row_result = {'row': row_num, 'valid': True, 'issues': [], 'data': {}}
            
            # Extract data from row
            employee_id = row.get('employee_id', '').strip()
            event_date_str = row.get('event_date', '').strip()
            category_code = row.get('category_code', '').strip()
            department = row.get('department', '').strip()
            notes = row.get('notes', '').strip()
            
            # Count individual field entries
            if department and department.strip():
                validation_results['summary']['departments_entered'] += 1
            if notes and notes.strip():
                validation_results['summary']['notes_entered'] += 1
            
            # Basic field validation
            if not employee_id:
                row_result['valid'] = False
                row_result['issues'].append("Missing employee_id")
            
            if not category_code:
                row_result['valid'] = False
                row_result['issues'].append("Missing category_code")
            
            if category_code not in valid_categories:
                row_result['valid'] = False
                row_result['issues'].append(f"Invalid category_code '{category_code}'. Must be one of {valid_categories}")
            
            if not notes:
                row_result['valid'] = False
                row_result['issues'].append("Missing notes - notes field is mandatory")
            
            if not event_date_str:
                row_result['valid'] = False
                row_result['issues'].append("Missing event_date")
            else:
                event_date = None
                try:
                    event_date = datetime.strptime(event_date_str, '%d-%m-%Y')
                except ValueError:
                    row_result['valid'] = False
                    row_result['issues'].append("Invalid event_date format. Use DD-MM-YYYY.")
                
                if event_date and event_date.date() > datetime.utcnow().date():
                    row_result['valid'] = False
                    row_result['issues'].append(f"Event date '{event_date_str}' is in the future. Please use today's date or a past date.")
            
            if not row_result['valid']:
                row_result['data'] = row
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                rejected_requests.append({
                    'employee_name': 'Unknown',
                    'employee_id': employee_id,
                    'notes': ', '.join(row_result['issues']),
                    'category_code': category_code
                })
                validation_results['rows'].append(row_result)
                continue

            if category_code == 'utilization_billable':
                row_result['valid'] = False
                row_result['issues'].append("Utilization/Billable uploads are not allowed via Bulk Upload. Please use the Utilization Upload template.")
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                rejected_requests.append({
                    'employee_name': 'Unknown',
                    'employee_id': employee_id,
                    'notes': ', '.join(row_result['issues']),
                    'category_code': category_code
                })
                validation_results['rows'].append(row_result)
                continue
            
            # Find employee and category
            employee_query = {"employee_id": employee_id}
            employee_query.update(SELECTABLE_EMPLOYEE_FILTER)
            employee = mongo.db.users.find_one(employee_query)
            if not employee:
                row_result['valid'] = False
                row_result['issues'].append(f"Employee ID {employee_id} not found in database.")
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                rejected_requests.append({
                    'employee_name': 'Unknown',
                    'employee_id': employee_id,
                    'notes': ', '.join(row_result['issues']),
                    'category_code': category_code
                })
                validation_results['rows'].append(row_result)
                continue

            category = mongo.db.categories.find_one({"code": category_code})
            if not category:
                row_result['valid'] = False
                row_result['issues'].append(f"Category code {category_code} not found in database.")
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                rejected_requests.append({
                    'employee_name': employee.get('name', 'Unknown'),
                    'employee_id': employee_id,
                    'notes': ', '.join(row_result['issues']),
                    'category_code': category_code
                })
                validation_results['rows'].append(row_result)
                continue
            
            employee_grade = employee.get('grade', 'N/A')
            employee_department = employee.get('department', '') or 'Not Entered'

            if not employee_grade or employee_grade == 'N/A':
                row_result['valid'] = False
                row_result['issues'].append(f"Employee {employee_id} has no grade assigned.")
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                rejected_requests.append({
                    'employee_name': employee.get('name', 'Unknown'),
                    'employee_id': employee_id,
                    'notes': ', '.join(row_result['issues']),
                    'category_code': category_code
                })
                validation_results['rows'].append(row_result)
                continue

            # Validate department if provided in CSV
            if department and department.strip():
                actual_department = employee.get('department', '').strip()
                if actual_department and department.strip().lower() != actual_department.lower():
                    row_result['valid'] = False
                    row_result['issues'].append(f"Department mismatch: CSV shows '{department}' but employee {employee_id} belongs to '{actual_department}'.")
                    validation_results['invalid_rows'] += 1
                    validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                    rejected_requests.append({
                        'employee_name': employee.get('name', 'Unknown'),
                        'employee_id': employee_id,
                        'notes': ', '.join(row_result['issues']),
                        'category_code': category_code
                    })
                    validation_results['rows'].append(row_result)
                    continue

            # Store row data for preview
            row_result['data'] = {
                'employee_id': employee_id,
                'employee_name': employee.get('name', f'Employee {employee_id}'),
                'event_date': event_date_str,
                'category_code': category_code,
                'category_name': category.get('name', 'N/A'),
                'points': category.get('points_per_unit', 0),
                'department': department or 'Not Entered',
                'grade': employee_grade,
                'notes': notes
            }
            
            # Debug: Print what we're storing
            print(f"DEBUG BULK - Row {row_num}: CSV dept='{department}', Stored dept='{department or 'Not Entered'}', Employee ID={employee_id}", file=sys.stderr)

            # Add to approved requests
            approved_request = {
                'employee_name': employee.get('name', 'Unknown'),
                'employee_id': employee_id,
                'interviews_count': 1,  # Adjust if multiple interviews per row
                'points': category.get('points_per_unit', 0),
                'notes': notes,
                'category_name': category.get('name', 'N/A')
            }
            approved_requests.append(approved_request)

            # Group approved requests by employee for bulk notification
            if employee_id not in employee_approved_requests:
                employee_approved_requests[employee_id] = {
                    'employee': employee,
                    'requests': []
                }
            employee_approved_requests[employee_id]['requests'].append(approved_request)

            validation_results['rows'].append(row_result)
            validation_results['valid_rows'] += 1

            # Update summary statistics
            cat_name = category.get('name', 'Unknown')
            if cat_name not in validation_results['summary']['categories']:
                validation_results['summary']['categories'][cat_name] = 0
            validation_results['summary']['categories'][cat_name] += 1
        
        # Send bulk notifications
        if approved_requests:
            print(f"Sending bulk approval notification to updater: {updater.get('email')}")
            send_bulk_approval_notification_to_updater(updater, validator, approved_requests)

            # Send a single bulk approval email to each employee for all their approved requests
            for employee_id, data in employee_approved_requests.items():
                employee = data['employee']
                requests = data['requests']
                print(f"Sending bulk approval notification to employee: {employee.get('email')}")
                send_bulk_approval_notification_to_employee(employee, validator, requests)

        if rejected_requests:
            print(f"Sending bulk rejection notification to updater: {updater.get('email')}")
            send_bulk_rejection_notification_to_updater(updater, validator, rejected_requests)

        return jsonify(validation_results)

    except Exception as e:
        error_print("Error validating CSV file", e)
        return jsonify({'error': str(e)}), 500

@pmo_bp.route('/validate-utilization-upload', methods=['POST'])
def validate_utilization_upload():
    """API to validate a CSV file for utilization upload (Utilization/Billable only)"""
    if session.get('manager_level') != 'PMO':
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        if 'csv_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['csv_file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'Please upload a CSV file'}), 400
        
        # Process CSV for validation only
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        validation_results = {
            'total_rows': 0,
            'valid_rows': 0,
            'invalid_rows': 0,
            'warnings': [],
            'errors': [],
            'summary': {
                'categories': {},
                'departments_entered': 0,
                'utilization_entered': 0,
                'notes_entered': 0
            },
            'rows': []  # To store row data for preview
        }
        
        # Validate the template structure
        expected_headers = ['employee_id', 'event_date', 'category_code', 'department', 'utilization', 'notes']
        actual_headers = csv_reader.fieldnames
        if actual_headers != expected_headers:
            validation_results['errors'].append("Invalid template used. Please use the Utilization Upload template. Expected headers: employee_id, event_date, category_code, department, utilization, notes.")
            return jsonify(validation_results), 400
        
        valid_categories = ['spot_award', 'client_appreciation', 'r&r', 'utilization_billable']
        
        current_date = datetime.utcnow()
        
        # Reset file pointer
        file.seek(0)
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        processed_utilization_entries = set()
        # Validate each row
        for row_num, row in enumerate(csv_reader, start=1):
            validation_results['total_rows'] += 1
            row_result = {'row': row_num, 'valid': True, 'issues': [], 'data': {}}
            
            # Extract data from row
            employee_id = row.get('employee_id', '').strip()
            event_date_str = row.get('event_date', '').strip()
            category_code = row.get('category_code', '').strip()
            department = row.get('department', '').strip()
            utilization = row.get('utilization', '').strip()
            notes = row.get('notes', '').strip() # 'notes' is now mandatory
            
            # Count individual field entries
            if department and department.strip():
                validation_results['summary']['departments_entered'] += 1
            if utilization and utilization.strip():
                validation_results['summary']['utilization_entered'] += 1
            if notes and notes.strip():
                validation_results['summary']['notes_entered'] += 1
            
            # Basic field validation
            if not employee_id:
                row_result['valid'] = False
                row_result['issues'].append("Missing employee_id")
            
            if not category_code:
                row_result['valid'] = False
                row_result['issues'].append("Missing category_code")
            
            if not utilization:
                row_result['valid'] = False
                row_result['issues'].append("Missing utilization value")

            if not notes: # Validate notes as mandatory
                row_result['valid'] = False
                row_result['issues'].append("Missing notes - notes field is mandatory")
            
            event_date = None
            if not event_date_str:
                row_result['valid'] = False
                row_result['issues'].append("Missing event_date")
            else:
                try:
                    # Validate date format and future date
                    event_date = datetime.strptime(event_date_str, '%d-%m-%Y')
                    if event_date.date() > datetime.utcnow().date():
                        row_result['valid'] = False
                        row_result['issues'].append(f"Event date '{event_date_str}' is in the future. Please use today's date or a past date.")
                except ValueError:
                    row_result['valid'] = False
                    row_result['issues'].append("Invalid event_date format. Use DD-MM-YYYY.")
            if category_code not in valid_categories:
                row_result['valid'] = False
                row_result['issues'].append(f"Invalid category_code '{category_code}'. Must be one of {valid_categories}")
                
            # Skip further validation if basic fields are invalid
            if not row_result['valid']:
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                validation_results['rows'].append(row_result)
                continue
            
            # Only allow utilization_billable for utilization upload
            if category_code != 'utilization_billable':
                row_result['valid'] = False
                row_result['issues'].append("Only Utilization/Billable category is allowed via Utilization Upload. Please use the Bulk Upload template for other categories.")
            
            if not row_result['valid']:
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                validation_results['rows'].append(row_result)
                continue
            
            # Find employee and category
            # Find user by employee_id, strictly role: "Employee"
            employee_query = {"employee_id": employee_id}
            employee_query.update(SELECTABLE_EMPLOYEE_FILTER)
            employee = mongo.db.users.find_one(employee_query)
            if not employee:
                row_result['valid'] = False
                row_result['issues'].append(f"Employee ID {employee_id} not found in database.")

            category = mongo.db.categories.find_one({"code": category_code})
            if not category:
                row_result['valid'] = False
                row_result['issues'].append(f"Category code {category_code} not found in database.")

            # Skip further validation if employee or category not found
            if not row_result['valid']:
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                validation_results['rows'].append(row_result)
                continue

            # Get the employee's grade and department
            employee_grade = employee.get('grade', 'N/A')
            employee_department = employee.get('department', '') or 'Not Entered'

            if not employee_grade or employee_grade == 'N/A':
                row_result['valid'] = False
                row_result['issues'].append(f"Employee {employee_id} has no grade assigned.")

            # if employee_grade == 'A1':
            #     row_result['valid'] = False
            #     row_result['issues'].append("A1 employees are not eligible for Utilization/Billable category")

            if event_date:
                utilization_month_year = (employee_id, event_date.month, event_date.year)
                if utilization_month_year in processed_utilization_entries:
                    row_result['valid'] = False
                    row_result['issues'].append(f"Duplicate utilization record for employee {employee_id} for this month in the same file.")
                else:
                    # Check for existing utilization record in the current month
                    existing_record = has_existing_utilization_record(employee["_id"], category["_id"], event_date)
                    if existing_record:
                        row_result['valid'] = False
                        row_result['issues'].append(f"Utilization record for employee {employee_id} already exists for this month. Please edit the existing record.")

            # Validate department if provided in CSV
            if department and department.strip():
                actual_department = employee.get('department', '').strip()
                if actual_department and department.strip().lower() != actual_department.lower():
                    row_result['valid'] = False
                    row_result['issues'].append(f"Department mismatch: CSV shows '{department}' but employee {employee_id} belongs to '{actual_department}'.")

            # Skip further validation if grade, eligibility, or department issues
            if not row_result['valid']:
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                validation_results['rows'].append(row_result)
                continue
            
            processed_utilization_entries.add(utilization_month_year)

            # Validate utilization value
            try:
                # Remove % sign if present
                utilization_cleaned = utilization.replace('%', '').strip()
                if not utilization_cleaned:  # Check for empty string after cleaning
                    row_result['valid'] = False
                    row_result['issues'].append("Utilization value cannot be empty")
                else:
                    utilization_value = float(utilization_cleaned)
                    # If the value is > 1, assume it's a percentage and convert to decimal
                    if utilization_value > 1:
                        utilization_value = utilization_value / 100.0
                    # Validate the final value
                    if utilization_value < 0 or utilization_value > 1:
                        row_result['valid'] = False
                        row_result['issues'].append("Utilization value must be between 0 and 1 (or 0% to 100%)")
            except ValueError:
                row_result['valid'] = False
                row_result['issues'].append("Invalid utilization value (enter a number like 0.88 or 88%)")

            if not row_result['valid']:
                validation_results['invalid_rows'] += 1
                validation_results['errors'].append(f"Row {row_num}: {', '.join(row_result['issues'])}")
                validation_results['rows'].append(row_result)
                continue

            # Store row data for preview
            row_result['data'] = {
                'employee_id': employee_id,
                'event_date': event_date_str,
                'category_code': category_code,
                'category_name': category.get('name', 'N/A'),
                'utilization': utilization,
                'department': department or 'Not Entered',
                'grade': employee_grade,
                'notes': notes if notes else 'None'
            }
            
            # Debug: Print what we're storing
            print(f"DEBUG - Row {row_num}: CSV dept='{department}', Stored dept='{department or 'Not Entered'}', Employee ID={employee_id}", file=sys.stderr)

            validation_results['rows'].append(row_result)

            # Update summary statistics for Utilization/Billable
            validation_results['valid_rows'] += 1
            cat_name = category.get('name', 'Unknown')
            if cat_name not in validation_results['summary']['categories']:
                validation_results['summary']['categories'][cat_name] = 0
            validation_results['summary']['categories'][cat_name] += 1

        return jsonify(validation_results)

    except Exception as e:
        error_print("Error validating utilization CSV file", e)
        return jsonify({'error': str(e)}), 500

@pmo_bp.route('/download_template/<template_type>', methods=['GET'])
def download_template(template_type):
    """Route to download a CSV template for bulk upload"""
    if session.get('manager_level') != 'PMO':
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Define the CSV headers based on template type
        output = io.StringIO()
        writer = csv.writer(output)
        
        if template_type == 'bulk':
            # Template for Bulk Upload (Spot Award, Client Appreciation, R&R only)
            headers = ['employee_id', 'event_date', 'category_code', 'department', 'notes']
            writer.writerow(headers)

            today_date = datetime.utcnow().strftime('%d-%m-%Y')
            sample_rows = [
                ['EMP123', today_date, 'spot_award', 'PMO', 'Example notes for the Spot Award.'],
                ['EMP456', today_date, 'r&r', 'HR', 'Received recognition for outstanding teamwork.'],
                ['EMP789', today_date, 'client_appreciation', 'PMO', 'Client praised delivery team for project success.']
            ]

            # ✅ Write each list as its own row
            writer.writerows(sample_rows)
        elif template_type == 'utilization':
    # Template for Utilization Upload (Utilization/Billable only)
            headers = ['employee_id', 'event_date', 'category_code', 'department', 'utilization', 'notes']
            today_date = datetime.utcnow().strftime('%d-%m-%Y')
            example_row = ['EMP123', today_date, 'utilization_billable', 'TA', '88%', 'Monthly utilization target met.']
            writer.writerow(headers)
            writer.writerow(example_row)
        else:
            flash('Invalid template type', 'danger')
            return redirect(url_for('pmo.dashboard'))
        
        # Prepare the response
        response = make_response(output.getvalue())
        response.headers['Content-Disposition'] = f'attachment; filename={template_type}_upload_template.csv'
        response.headers['Content-Type'] = 'text/csv'
        
        return response
    
    except Exception as e:
        error_print(f"Error generating {template_type} template", e)
        flash('Error generating template', 'danger')
        return redirect(url_for('pmo.dashboard'))

@pmo_bp.route('/employees', methods=['GET'])
def employees():
    # Get user ID from the session
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    # Verify manager level
    if manager_level != 'PMO':
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('manager.dashboard'))
    
    try:
        # Get manager information
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))
        
        # Fetch all employees
        employees = list(mongo.db.users.find(SELECTABLE_EMPLOYEE_FILTER).sort("name", 1))
        
        # Format employee data for the template and fetch utilization
        current_date = datetime.utcnow()
        for emp in employees:
            emp['created_at'] = emp.get('created_at', datetime.utcnow())  # Ensure created_at exists
            emp['department'] = emp.get('department', 'Unassigned')
            emp['grade'] = emp.get('grade', 'Unassigned')
            emp['email'] = emp.get('email', 'N/A')
            emp['employee_id'] = emp.get('employee_id', 'N/A')
            # Fetch the most recent utilization value for the current month
            utilization = _get_current_utilization(emp["_id"], current_date)
            emp['utilization'] = utilization  # Will be None if no record exists
        
        return render_template('employees.html',
                              user=user,
                              employees=employees)
    
    except Exception as e:
        error_print("Employees Page Error", e)
        flash('An error occurred while loading the employees page', 'danger')
        return redirect(url_for('auth.login'))
    


@pmo_bp.route('/validator-dashboard', methods=['GET', 'POST'])
def validator_dashboard():
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')

    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))

    if manager_level != 'PMO':
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('manager.dashboard')) 

    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('auth.login'))

    # This dashboard is for Validators (PMOs without a reporting manager)
    if user.get('manager_id'):
        flash('Access denied. This dashboard is for PMO Validators.', 'danger')
        return redirect(url_for('pmo.dashboard'))
    
    if request.method == 'POST': # This block handles all POST actions
        action_type = request.form.get('action_type') # Determine which form was submitted
        if action_type == 'review_requests': # Reviewing pending requests
            request_ids = request.form.getlist('request_ids[]') # Get list of selected request IDs
            action = request.form.get('action')
            notes = request.form.get('review_notes', '')

            if not request_ids or not action or action not in ['approve', 'reject']:
                flash('No requests selected or invalid action', 'danger')
            else:
                success_count = 0
                error_count = 0
                
                # --- START: MODIFIED LOGIC FOR BULK NOTIFICATIONS ---

                # Dictionaries to group requests for bulk emailing
                # Key: updater_id, Value: list of request details for that updater
                approved_by_updater = {}
                rejected_by_updater = {}
                # Key: employee_id, Value: list of request details for that employee
                approved_for_employee = {}

                for req_id_str in request_ids:
                    try:
                        req_id = ObjectId(req_id_str)
                        req_item = mongo.db.points_request.find_one({"_id": req_id, "pending_validator_id": ObjectId(user_id)})
                        if not req_item or req_item.get('status') != 'Pending':
                            error_count += 1
                            continue

                        update_doc = {
                            "status": "Approved" if action == "approve" else "Rejected",
                            "response_date": datetime.utcnow(),
                            "response_notes": f"{action.capitalize()}d by PMO Validator: {user.get('name', 'N/A')}" + (f" - Notes: {notes}" if notes else ""),
                            "updated_by": "PMO Validator",
                            "pmo_id": ObjectId(user_id)
                        }
                        mongo.db.points_request.update_one({"_id": req_id}, {"$set": update_doc, "$unset": {"pending_validator_id": ""}})
                        
                        # --- Database write logic for points (on approval) ---
                        if action == "approve":
                            category = mongo.db.categories.find_one({"_id": req_item["category_id"]})
                            if category and category.get("code") != "utilization_billable" and req_item.get("points", 0) > 0:
                                points_data = {
                                    "user_id": req_item["user_id"],
                                    "category_id": req_item["category_id"],
                                    "points": req_item["points"],
                                    "notes": req_item.get("request_notes", ""),
                                    "event_date": req_item.get("event_date"), # <-- FIX: This line was added to store the event date
                                    "awarded_by": ObjectId(user_id),
                                    "award_date": datetime.utcnow(),
                                    "request_id": req_item["_id"],
                                    "updated_by": "PMO Validator"
                                }
                                mongo.db.points.insert_one(points_data)
                        
                        # --- Collect data for bulk notification ---
                        employee = mongo.db.users.find_one({"_id": req_item["user_id"]})
                        updater_id = req_item.get("created_by_pmo_id")

                        if not employee or not updater_id:
                            error_print(f"Could not find employee or updater for request {req_id_str}", None)
                            error_count += 1
                            continue
                        
                        request_details = {
                            'employee_name': employee.get('name', 'N/A'),
                            'employee_id': employee.get('employee_id', 'N/A'),
                            'interviews_count': 1,  # Assuming 1 request = 1 unit of work for the template
                            'points': req_item.get('points', 0),
                            'notes': notes if action == 'reject' else req_item.get("request_notes", ""),
                        }
                        
                        if action == "approve":
                            # Group by updater for their summary email
                            if updater_id not in approved_by_updater:
                                approved_by_updater[updater_id] = []
                            approved_by_updater[updater_id].append(request_details)
                            
                            # Group by employee for their summary email
                            if employee['_id'] not in approved_for_employee:
                                approved_for_employee[employee['_id']] = []
                            approved_for_employee[employee['_id']].append(request_details)

                        elif action == "reject":
                            # Group by updater for their summary email
                            if updater_id not in rejected_by_updater:
                                rejected_by_updater[updater_id] = []
                            rejected_by_updater[updater_id].append(request_details)

                        success_count += 1
                    except Exception as e:
                        error_print(f"Error processing request {req_id_str} for validator", e)
                        error_count += 1

                # --- Send the consolidated bulk emails after processing all requests ---
                validator = user
                
                # Send approval summary to each updater
                for uid, requests in approved_by_updater.items():
                    updater = mongo.db.users.find_one({"_id": uid})
                    if updater:
                        send_bulk_approval_notification_to_updater(updater, validator, requests)

                # Send rejection summary to each updater
                for uid, requests in rejected_by_updater.items():
                    updater = mongo.db.users.find_one({"_id": uid})
                    if updater:
                        send_bulk_rejection_notification_to_updater(updater, validator, requests)

                # Send approval summary to each employee
                for eid, requests in approved_for_employee.items():
                    employee = mongo.db.users.find_one({"_id": eid})
                    if employee:
                        send_bulk_approval_notification_to_employee(employee, validator, requests)
                
                # --- END: MODIFIED LOGIC ---

                if success_count > 0:
                    flash(f'Successfully {action}ed {success_count} requests.', 'success')
                if error_count > 0:
                    flash(f'Failed to process {error_count} requests.', 'warning')
            return redirect(url_for('pmo.validator_dashboard'))
        
        elif action_type == 'edit_utilization':
            # This logic remains unchanged as it's a single action
            request_id = request.form.get('request_id')
            new_utilization_str = request.form.get('new_utilization')
            notes = request.form.get('notes', '')

            if not request_id or not new_utilization_str:
                flash('Missing required fields for editing utilization.', 'danger')
                return redirect(url_for('pmo.validator_dashboard'))

            try:
                new_utilization_cleaned = new_utilization_str.replace('%', '').strip()
                if not new_utilization_cleaned:
                    flash('Utilization value cannot be empty.', 'danger')
                    return redirect(url_for('pmo.validator_dashboard'))
                
                utilization_value = float(new_utilization_cleaned)
                if utilization_value > 1:
                    utilization_value = utilization_value / 100.0
                
                if not (0 <= utilization_value <= 1):
                    flash('Utilization value must be between 0 and 1 (or 0% to 100%).', 'danger')
                    return redirect(url_for('pmo.validator_dashboard'))

                existing_request = mongo.db.points_request.find_one({
                    "_id": ObjectId(request_id),
                    "pmo_id": ObjectId(user_id),
                    "status": "Approved"
                })

                if not existing_request:
                    flash('Utilization record not found or you do not have permission to edit it.', 'danger')
                    return redirect(url_for('pmo.validator_dashboard'))

                category = mongo.db.categories.find_one({"_id": existing_request["category_id"]})
                if not category or category.get('code') != 'utilization_billable':
                    flash('This record is not a Utilization/Billable entry.', 'danger')
                    return redirect(url_for('pmo.validator_dashboard'))

                mongo.db.points_request.update_one(
                    {"_id": ObjectId(request_id)},
                    {"$set": {
                        "utilization_value": utilization_value,
                        "response_notes": f"Utilization updated to {utilization_value:.2%} by PMO Validator: {user.get('name', 'N/A')}" + (f" - Notes: {notes}" if notes else ""),
                        "response_date": datetime.utcnow(),
                        "updated_by": "PMO Validator"
                    }}
                )
                flash(f'Utilization record updated to {utilization_value:.2%}.', 'success')
            except ValueError:
                flash('Invalid utilization value format. Please enter a number (e.g., 88 or 0.88).', 'danger')
            except Exception as e:
                error_print("Error editing utilization record in validator_dashboard", e)
                flash('An error occurred while editing the utilization record.', 'danger')
            return redirect(url_for('pmo.validator_dashboard'))

    # The GET request logic remains unchanged
    pending_requests_data = _get_pending_requests_for_validator(user_id)
    (all_requests_data, category_name_map, 
     departments_for_assign_form, pmo_categories_for_assign_form, _,
    filter_quarters_list, filter_categories_list, filter_departments_list,
    sorted_history_fiscal_years) = _get_history_data_for_pmo(user_id, is_pmo_updater=False)

    current_quarter_name_display, _, _ = get_current_fiscal_quarter_details()
    now = datetime.utcnow()
    current_month_str = now.strftime("%B %Y")

    return render_template('pmo_validator.html',
                           user=user,
                           pending_requests=pending_requests_data,
                           all_requests=all_requests_data,
                           category_name_map=category_name_map,
                           departments=departments_for_assign_form,
                           pmo_categories=pmo_categories_for_assign_form,
                           filter_quarters=filter_quarters_list,
                           filter_categories=filter_categories_list,
                           filter_departments=filter_departments_list,
                           filter_years=sorted_history_fiscal_years,
                           current_quarter=current_quarter_name_display,
                           current_month=current_month_str)   
# Helper function to get pending requests for a validator

def _get_pending_requests_for_validator(validator_user_id):
    pending_requests = []
    pending_cursor = mongo.db.points_request.find({
        "status": "Pending",
        "pending_validator_id": ObjectId(validator_user_id)
    }).sort("request_date", 1)
    for req in pending_cursor:
        emp = mongo.db.users.find_one({"_id": req["user_id"]})
        category = mongo.db.categories.find_one({"_id": req["category_id"]})
        submitted_by_pmo = mongo.db.users.find_one({"_id": req.get("created_by_pmo_id")})
        if emp and category:
            pending_requests.append({
                'id': req["_id"],
                'employee_name': emp["name"],
                'employee_id': emp.get("employee_id", "N/A"),
                'category': category["name"],
                'category_code': category.get("code", ""),
                'points': req["points"],
                'utilization_value': req.get("utilization_value"),
                'event_date': req.get("event_date"),
                'request_date': req["request_date"],
                'submitted_by_pmo_name': submitted_by_pmo["name"] if submitted_by_pmo else "N/A",
                'request_notes': req.get("request_notes", "")
            })
    return pending_requests

# Helper function to get history data (can be reused by main dashboard too)
def _get_history_data_for_pmo(pmo_user_id, is_pmo_updater):
    history_query = {
        "$or": [
            {"created_by_pmo_id": ObjectId(pmo_user_id)}, 
            {"pmo_id": ObjectId(pmo_user_id)}            
        ]
    }
    all_requests_cursor = mongo.db.points_request.find(history_query).sort([("request_date", -1)])
    
    all_requests_data = []
    current_date = datetime.utcnow()
    start_of_month = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month_start = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 else start_of_month.replace(year=start_of_month.year + 1, month=1))

    # For dynamic filters
    history_quarters_set = set()
    history_category_codes_set = set()
    history_departments_set = set()
    history_fiscal_years_set = set() # To store fiscal years for the year filter

    for req in all_requests_cursor:
        emp = mongo.db.users.find_one({"_id": req["user_id"]})
        category = mongo.db.categories.find_one({"_id": req["category_id"]})
        actor_pmo = mongo.db.users.find_one({"_id": req.get("pmo_id")}) if req.get("pmo_id") else None
        creator_pmo = mongo.db.users.find_one({"_id": req.get("created_by_pmo_id")}) if req.get("created_by_pmo_id") else None
        
        if emp and category:
            category_code = category.get("code", "").lower().strip()
            can_edit_utilization = False
            # Validators can edit utilization they approved in the current month
            if not is_pmo_updater and \
               str(req.get("pmo_id")) == str(pmo_user_id) and \
               category_code == 'utilization_billable' and \
               req.get("status") == "Approved" and \
               start_of_month <= req.get("request_date", datetime.min) < next_month_start:
                can_edit_utilization = True

            req_date_obj = req.get("request_date")
            if req_date_obj:
                year = req_date_obj.year
                # CORRECTED: April-March fiscal year logic for history
                adj_month = (req_date_obj.month - 4 + 12) % 12 # April is 0
                q_num = (adj_month // 3) + 1
                fiscal_year_for_req = year
                if req_date_obj.month < 4: # Jan, Feb, March belong to previous fiscal year
                    fiscal_year_for_req -= 1
                history_quarters_set.add(f"Q{q_num}-{fiscal_year_for_req}")
                history_fiscal_years_set.add(str(fiscal_year_for_req)) # Add fiscal year as string
            history_category_codes_set.add(category_code)
            if emp.get("department"):
                history_departments_set.add(emp.get("department"))

            request_data = {
                'id': req["_id"],
                'employee_name': emp["name"],
                'employee_id': emp.get("employee_id", "N/A"),
                'employee_grade': emp.get("grade", ""),
                'employee_department': emp.get("department", "") or "Not Entered",
                'category': category["name"],
                'category_id': req["category_id"], # Added for consistency if needed by template
                'category_code': category_code,
                'points': req["points"],
                'utilization_value': req.get("utilization_value"),
                'event_date': req.get("event_date"),
                'request_date': req["request_date"],
                'status': req["status"], # This is the original updater's note
                'notes': req.get("request_notes", ""), # Always use the original request_notes for history display
                'submitted_by_name': creator_pmo["name"] if creator_pmo else (actor_pmo["name"] if req.get("status") == "Approved" and not creator_pmo else "N/A"),
                'actioned_by_name': actor_pmo["name"] if actor_pmo and req.get("status") != "Pending" else ("Pending with " + mongo.db.users.find_one({"_id": req.get("pending_validator_id")}).get("name", "Validator") if req.get("pending_validator_id") else "Pending"),
                'can_edit': can_edit_utilization
            }
            
            # Add all original fields from the request to the request_data
            request_data.update(req)
            
            all_requests_data.append(request_data)

    # Categories for assign forms (all defined PMO categories)
    pmo_categories_for_assign_form = list(mongo.db.categories.find({"code": {"$in": ["spot_award", "client_appreciation", "r&r", "utilization_billable"]}}))
    category_name_map = {cat['code']: cat['name'] for cat in pmo_categories_for_assign_form} # For display in tables
    
    all_employees_list = list(mongo.db.users.find(SELECTABLE_EMPLOYEE_FILTER))
    departments_for_assign_form = {} # For assign forms (dept -> list of grades)
    for emp_item in all_employees_list:
        department = emp_item.get('department', 'Unassigned')
        if department != 'Unassigned':
            if department not in departments_for_assign_form:
                departments_for_assign_form[department] = set()
            departments_for_assign_form[department].add(emp_item.get('grade', 'Unassigned'))
    for dept_key in departments_for_assign_form:
        departments_for_assign_form[dept_key] = sorted(list(d for d in departments_for_assign_form[dept_key] if d != 'Unassigned'))

    # Prepare dynamic filter options
    # Sort quarters: by year desc, then quarter desc (e.g., Q4 2023, Q1 2023, Q4 2022)
    # Corrected sorting for "Q#-YYYY" format
    sorted_history_quarters = sorted(
        list(history_quarters_set), 
        key=lambda q_name: (int(q_name.split('-')[1]), int(q_name.split('-')[0][1:])), 
        reverse=True
    )
    
    sorted_history_fiscal_years = sorted(list(history_fiscal_years_set), reverse=True) # Sort fiscal years
    history_categories_for_filter = []
    cat_codes_from_history = list(history_category_codes_set)
    if cat_codes_from_history:
        history_categories_for_filter = list(mongo.db.categories.find({"code": {"$in": cat_codes_from_history}}, {"name": 1, "code": 1, "_id":0}).sort("name", 1))

    sorted_history_departments = sorted([dep for dep in list(history_departments_set) if dep and dep != "Unassigned"])
    # Return sorted_history_fiscal_years as well
    return all_requests_data, category_name_map, departments_for_assign_form, pmo_categories_for_assign_form, all_employees_list, sorted_history_quarters, history_categories_for_filter, sorted_history_departments, sorted_history_fiscal_years

def send_email_notification(to_email, to_name, subject, html_content, text_content=None):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = formataddr(('PBS System', Config.MAIL_USERNAME))
        msg['To'] = formataddr((to_name, to_email))
        if text_content:
            text_part = MIMEText(text_content, 'plain')
            msg.attach(text_part)
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT) as server:
            server.starttls()
            server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            server.send_message(msg)
        print(f"Email sent successfully to {to_email}", file=sys.stderr)
        return True
    except Exception as e:
        error_print(f"Failed to send email to {to_email}", e)
        return False

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
        ''',
        'new_single_request': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #007bff; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
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
                <div class="header">
                    <h2>New Request for Approval</h2>
                </div>
                <div class="content">
                    <p>Dear {validator_name},</p>
                    <p>A new request has been submitted by {updater_name} and requires your approval.</p>
                    <table class="info-table">
                        <tr>
                            <td>Employee Name:</td>
                            <td>{employee_name}</td>
                        </tr>
                        <tr>
                            <td>Employee ID:</td>
                            <td>{employee_id}</td>
                        </tr>
                        <tr>
                            <td>Department:</td>
                            <td>{department}</td>
                        </tr>
                        <tr>
                            <td>Category:</td>
                            <td>{category_name}</td>
                        </tr>
                        <tr>
                            <td>Points:</td>
                            <td>{points}</td>
                        </tr>
                        {utilization_row}
                        <tr>
                            <td>Submission Date:</td>
                            <td>{submission_date}</td>
                        </tr>
                        <tr>
                            <td>Notes:</td>
                            <td>{notes}</td>
                        </tr>
                    </table>
                    
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to  Dashboard</a></center>
                </div>
                
            
                </div>
            </div>
        </body>
        </html>
        ''',
        'new_bulk_requests': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 800px; margin: 0 auto; padding: 20px; }
                .header { background-color: #007bff; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }
                .button { display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; }
                .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
                .requests-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
                .requests-table th, .requests-table td { padding: 8px; border: 1px solid #ddd; text-align: left; }
                .requests-table th { background-color: #f5f5f5; }
                .summary { margin: 20px 0; padding: 15px; background-color: #e9ecef; border-radius: 5px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>New Bulk Upload for Approval</h2>
                </div>
                <div class="content">
                    <p>Dear {validator_name},</p>
                    <p>A bulk upload has been submitted by {updater_name} and requires your approval.</p>
                    <div class="summary">
                        <h3>Upload Summary</h3>
                        <p>Total Requests: {total_requests}</p>
                        <p>Upload Type: {upload_type}</p>
                        <p>Submission Date: {submission_date}</p>
                    </div>
                    <h3>Request Details</h3>
                    <table class="requests-table">
                        <thead>
                            <tr>
                                <th>Employee ID</th>
                                <th>Employee Name</th>
                                <th>Department</th>
                                <th>Category</th>
                                <th>Points/Utilization</th>
                            </tr>
                        </thead>
                        <tbody>
                            {request_rows}
                        </tbody>
                    </table>
                    
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to  Dashboard</a></center>
                </div>
                
            
                </div>
            </div>
        </body>
        </html>
        ''',
        'utilization_processed': '''
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
                    <h2>Utilization Request {{ status }}</h2>
                </div>
                <div class="content">
                    <p>Dear {{ employee_name }},</p>
                    <p>Your utilization request for <strong>{{ category_name }}</strong> has been <strong>{{ status }}</strong> by {{ processor_name }}.</p>
                    <table class="info-table">
                        <tr>
                            <td>Category:</td>
                            <td>{{ category_name }}</td>
                        </tr>
                        <tr>
                            <td>Utilization Requested:</td>
                            <td>{{ utilization_value }}</td>
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
                    <p>You can view your updated utilization and request history by logging into the system.</p>
                    
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to  Dashboard</a></center>
                </div>
                
            
                </div>
            </div>
        </body>
        </html> ''',
        'bulk_approved_to_updater': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }
                .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
                .info-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
                .info-table th, .info-table td { padding: 8px; border-bottom: 1px solid #ddd; text-align: left; }
                .info-table th { background-color: #f2f2f2; }
                .summary { font-weight: bold; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h2>Bulk Approval Processed</h2></div>
                <div class="content">
                    <p>Dear {{ updater_name }},</p>
                    <p>The following <strong>{{ count }} interview requests</strong> you submitted have been approved by {{ validator_name }}.</p>
                    <table class="info-table">
                        <thead>
                            <tr>
                                <th>Employee Name</th>
                                <th>Interviews</th>
                                <th>Points</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for req in requests %}
                            <tr>
                                <td>{{ req.employee_name }}</td>
                                <td>{{ req.interviews_count }}</td>
                                <td>{{ req.points }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    <p class="summary">Total Points Awarded: {{ total_points }}</p>
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to  Dashboard</a></center>
                </div>
                
            
                </div>
            </div>
        </body>
        </html>
        ''',

        'bulk_rejected_to_updater': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #D32F2F; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }
                .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
                .info-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
                .info-table th, .info-table td { padding: 8px; border-bottom: 1px solid #ddd; text-align: left; }
                .info-table th { background-color: #f2f2f2; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h2>Bulk Rejection Processed</h2></div>
                <div class="content">
                    <p>Dear {{ updater_name }},</p>
                    <p>The following <strong>{{ count }} interview requests</strong> you submitted have been rejected by {{ validator_name }}.</p>
                    <table class="info-table">
                        <thead>
                            <tr>
                                <th>Employee Name</th>
                                <th>Reason / Notes</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for req in requests %}
                            <tr>
                                <td>{{ req.employee_name }}</td>
                                <td>{{ req.notes }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to  Dashboard</a></center>
                </div>
                
            
                </div>
            </div>
        </body>
        </html>''',
        

        'bulk_approved_to_employee': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }
                .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
                .info-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
                .info-table th, .info-table td { padding: 8px; border-bottom: 1px solid #ddd; text-align: left; }
                .info-table th { background-color: #f2f2f2; }
                .summary { font-weight: bold; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header"><h2>Congratulations! Your Interview Points Were Approved</h2></div>
                <div class="content">
                    <p>Dear {{ employee_name }},</p>
                    <p>Congratulations! The following <strong>{{ count }} interview point submissions</strong> for you have been approved by {{ validator_name }}.</p>
                    <table class="info-table">
                        <thead>
                            <tr>
                                <th>Interviews</th>
                                <th>Points Awarded</th>
                                <th>Notes</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for req in requests %}
                            <tr>
                                <td>{{ req.interviews_count }}</td>
                                <td>{{ req.points }}</td>
                                <td>{{ req.notes }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    <p class="summary">Total Points Awarded: {{ total_points }}</p>
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to  Dashboard</a></center>
                </div>
                
            
                </div>
            </div>
        </body>
        </html>
        ''',
        'new_hr_requests': '''
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 800px; margin: 0 auto; padding: 20px; }
                .header { background-color: #FFC107; color: #333; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }
                .button { display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; }
                .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
                .requests-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
                .requests-table th, .requests-table td { padding: 8px; border: 1px solid #ddd; text-align: left; }
                .requests-table th { background-color: #f5f5f5; }
                .summary { margin: 20px 0; padding: 15px; background-color: #e9ecef; border-radius: 5px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>New R&R Requests for HR Approval</h2>
                </div>
                <div class="content">
                    <p>Dear HR Team,</p>
                    <p>The following R&R (Rewards & Recognition) requests have been submitted by {updater_name} and require your approval.</p>
                    <div class="summary">
                        <h3>Summary</h3>
                        <p>Total Requests: {total_requests}</p>
                        <p>Submission Date: {submission_date}</p>
                    </div>
                    <h3>Request Details</h3>
                    <table class="requests-table">
                        <thead>
                            <tr>
                                <th>Employee ID</th>
                                <th>Employee Name</th>
                                <th>Department</th>
                                <th>Points</th>
                                <th>Notes</th>
                            </tr>
                        </thead>
                        <tbody>
                            {request_rows}
                        </tbody>
                    </table>
                </div>
                <div class="footer">
                    <p>Please log in to the system to review and process these requests.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to Dashboard</a></center>
                    
                </div>
            </div>
        </body>
        </html>
        '''
    
    }
    return templates.get(template_name, '')

def send_request_processed_notification(request_data, employee, processor, category, status, manager_notes, recipient_type='both'):
    """
    Send notification about processed request
    recipient_type: 'employee', 'updater', or 'both'
    """
    try:
        submission_date = request_data['request_date'].strftime('%B %d, %Y at %I:%M %p') if request_data.get('request_date') else 'N/A'
        processed_date = datetime.utcnow().strftime('%B %d, %Y at %I:%M %p')
        base_url = request.url_root.rstrip('/')
        dashboard_url = base_url + url_for('auth.login')
        
        if employee.get('role') == 'Employee' or (employee.get('role') == 'Manager' and employee.get('manager_level') in ['PM', 'PM/Arch', 'Pre-sales', 'Marketing', 'TA', 'L & D', 'PMO', 'CoE/DH']):
            dashboard_url = base_url + url_for('employee.dashboard')
        
        is_utilization = category.get('code') == 'utilization_billable'
        utilization_value = None
        if is_utilization:
            utilization_value = request_data.get('utilization_value')
            if utilization_value is not None:
                utilization_value = f"{utilization_value:.2%}"
            else:
                utilization_value = 'N/A'
        
        template_vars = {
            'employee_name': employee.get('name', 'Employee'),
            'category_name': category.get('name', 'Unknown Category'),
            'points': request_data.get('points', 0),
            'utilization_value': utilization_value,
            'status': status,
            'status_lower': status.lower(),
            'submission_date': submission_date,
            'processed_date': processed_date,
            'processor_name': processor.get('name', 'Processor'),
            'processor_level': processor.get('manager_level', 'N/A'),
            'manager_notes': manager_notes,
            'dashboard_url': dashboard_url
        }
        
        if is_utilization:
            html_template = Template(get_email_template('utilization_processed'))
            html_content = html_template.render(**template_vars)
            subject = f"Your Utilization Request for {category.get('name', 'Category')} has been {status}"
            text_content = f"""
Dear {template_vars['employee_name']},

Your utilization request for {template_vars['category_name']} has been {template_vars['status']} by {template_vars['processor_name']}.

Category: {template_vars['category_name']}
Utilization Requested: {template_vars['utilization_value']}
Status: {template_vars['status']}
Submission Date: {template_vars['submission_date']}
Processed Date: {template_vars['processed_date']}
Processed By: {template_vars['processor_name']} ({template_vars['processor_level']})

{template_vars['processor_name']}'s Notes: {template_vars['manager_notes'] if template_vars['manager_notes'] else 'N/A'}

You can view your updated utilization and request history by logging into the system.

Dashboard URL: {template_vars['dashboard_url']}
            """
        else:
            html_template = Template(get_email_template('request_processed'))
            html_content = html_template.render(**template_vars)
            subject = f"Your Points Request for {category.get('name', 'Category')} has been {status}"
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
        
        # Get the updater's information
        updater = None
        if request_data.get('created_by_pmo_id'):
            updater = mongo.db.users.find_one({"_id": request_data['created_by_pmo_id']})
        
        success = True
        
        # Send email to employee only if approved and recipient_type allows it
        if status == "Approved" and employee.get('email') and recipient_type in ['employee', 'both']:
            success &= send_email_notification(
                employee.get('email'),
                employee.get('name', 'Employee'),
                subject,
                html_content,
                text_content
            )
        
        # Send email to updater only if recipient_type allows it
        if updater and updater.get('email') and recipient_type in ['updater', 'both']:
            # Customize subject for updater
            if recipient_type == 'updater':
                updater_subject = f"Request for {employee.get('name', 'Employee')} has been {status}"
            else:
                updater_subject = subject if is_utilization else f"Points Request for {employee.get('name', 'Employee')} has been {status}"
            
            success &= send_email_notification(
                updater.get('email'),
                updater.get('name', 'PMO Updater'),
                updater_subject,
                html_content,
                text_content
            )
        
        if not success:
            print(f"Failed to send some notifications for request {request_data.get('_id')}", file=sys.stderr)
        
        return success
        
    except Exception as e:
        error_print("Failed to send request processed notification", e)
        return False

def send_single_request_notification(request_data, employee, validator, updater, category):
    try:
        submission_date = request_data['request_date'].strftime('%B %d, %Y at %I:%M %p')
        base_url = request.url_root.rstrip('/')
        validator_dashboard_url = base_url + url_for('pmo.validator_dashboard')
        
        # Handle utilization value if present
        utilization_row = ''
        if 'utilization_value' in request_data:
            utilization_row = f'''
            <tr>
                <td>Utilization:</td>
                <td>{request_data['utilization_value']:.2%}</td>
            </tr>'''
        
        template_vars = {
            'validator_name': validator.get('name', 'Validator'),
            'updater_name': updater.get('name', 'PMO Updater'),
            'employee_name': employee.get('name', 'Employee'),
            'employee_id': employee.get('employee_id', 'N/A'),
            'department': employee.get('department', 'N/A'),
            'category_name': category.get('name', 'Unknown Category'),
            'points': request_data.get('points', 0),
            'submission_date': submission_date,
            'notes': request_data.get('request_notes', ''),
            'validator_dashboard_url': validator_dashboard_url,
            'utilization_row': utilization_row
        }
        
        html_content = get_email_template('new_single_request')
        for key, value in template_vars.items():
            html_content = html_content.replace('{' + key + '}', str(value))
        
        subject = f'New Request for Approval - {employee.get("name", "Employee")}'
        
        return send_email_notification(
            to_email=validator.get('email'),
            to_name=validator.get('name', 'Validator'),
            subject=subject,
            html_content=html_content
        )
    except Exception as e:
        error_print("Failed to send single request notification", e)
        return False

def send_bulk_requests_notification(requests_data, validator, updater):
    try:
        base_url = request.url_root.rstrip('/')
        validator_dashboard_url = base_url + url_for('pmo.validator_dashboard')
        submission_date = datetime.utcnow().strftime('%B %d, %Y at %I:%M %p')
        
        # Determine upload type based on first request
        upload_type = "Points Upload"
        if requests_data and 'utilization_value' in requests_data[0]:
            upload_type = "Utilization Upload"
        
        # Generate request rows HTML
        request_rows = []
        for req in requests_data:
            # Get employee details
            employee = mongo.db.users.find_one({"employee_id": req['employee_id']})
            if not employee:
                continue
                
            # Get category details
            category = mongo.db.categories.find_one({"_id": req['category_id']})
            if not category:
                continue
            
            # Format points/utilization value
            value_display = str(req['points'])
            if 'utilization_value' in req:
                value_display = f"{req['utilization_value']:.2%}"
            
            row = f'''
            <tr>
                <td>{req['employee_id']}</td>
                <td>{employee.get('name', 'N/A')}</td>
                <td>{employee.get('department', 'N/A')}</td>
                <td>{category.get('name', 'N/A')}</td>
                <td>{value_display}</td>
            </tr>'''
            request_rows.append(row)
        
        template_vars = {
            'validator_name': validator.get('name', 'Validator'),
            'updater_name': updater.get('name', 'PMO Updater'),
            'total_requests': len(requests_data),
            'upload_type': upload_type,
            'submission_date': submission_date,
            'validator_dashboard_url': validator_dashboard_url,
            'request_rows': '\n'.join(request_rows)
        }
        
        html_content = get_email_template('new_bulk_requests')
        for key, value in template_vars.items():
            html_content = html_content.replace('{' + key + '}', str(value))
        
        subject = f'New Bulk {upload_type} for Approval - {len(requests_data)} Requests'
        
        return send_email_notification(
            to_email=validator.get('email'),
            to_name=validator.get('name', 'Validator'),
            subject=subject,
            html_content=html_content
        )
    except Exception as e:
        error_print("Failed to send bulk requests notification", e)
        return False

@pmo_bp.route('/validator/check-new-requests', methods=['GET'])
def validator_check_new_requests():
    """
    Check for new pending requests for the PMO Validator.
    Returns count of new requests and their details.
    """
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')

    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    # Only allow PMO validators (no manager_id)
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user or user.get('manager_id'):
        return jsonify({"error": "Not authorized"}), 403

    # Get last check timestamp from session or use a default
    last_check_key = f"pmo_validator_last_check_{user_id}"
    last_check = session.get(last_check_key)
    
    if last_check:
        try:
            last_check_date = datetime.fromisoformat(last_check.replace('Z', '').replace('+00:00', ''))
        except Exception:
            last_check_date = datetime.utcnow() - timedelta(minutes=5)
    else:
        last_check_date = datetime.utcnow() - timedelta(minutes=5)

    try:
        # Find all pending requests assigned to this validator
        query = {
            "status": "Pending",
            "pending_validator_id": ObjectId(user_id)
        }
        pending_cursor = mongo.db.points_request.find(query).sort("request_date", 1)
        pending_count = mongo.db.points_request.count_documents(query)
        new_requests = []
        for req in pending_cursor:
            request_date = req.get("request_date", datetime.utcnow())
            if hasattr(request_date, 'tzinfo') and request_date.tzinfo is not None:
                request_date = request_date.replace(tzinfo=None)
            if request_date > last_check_date:
                emp = mongo.db.users.find_one({"_id": req["user_id"]})
                category = mongo.db.categories.find_one({"_id": req["category_id"]})
                if not emp or not category:
                    continue
                new_requests.append({
                    'id': str(req["_id"]),
                    'employee_name': emp.get("name", "Unknown"),
                    'employee_grade': emp.get("grade", "Unknown"),
                    'category_name': category.get("name", "Unknown"),
                    'points': req.get("points", 0),
                    'utilization_value': req.get("utilization_value"),
                    'request_date': req["request_date"].isoformat() if req.get("request_date") else None,
                    'notes': req.get("request_notes", ""),
                })
        
        # Store current timestamp in session for next check
        current_timestamp = datetime.utcnow().isoformat()
        session[last_check_key] = current_timestamp
        
        return jsonify({
            "pending_count": pending_count,
            "new_requests": new_requests,
            "timestamp": current_timestamp
        })
    except Exception as e:
        error_print("Error checking new requests for PMO validator", e)
        return jsonify({"error": "Server error"}), 500

@pmo_bp.route('/updater/check-processed-requests', methods=['GET'])
def updater_check_processed_requests():
    """
    Endpoint for PMO Updater to poll for processed (approved/rejected) requests they submitted.
    Returns processed requests since the last check.
    """
    user_id = session.get('user_id')
    manager_level = session.get('manager_level')
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401
    # Only allow PMO updaters (must have manager_level == 'PMO' and have a manager_id)
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user or user.get('manager_level') != 'PMO' or not user.get('manager_id'):
        return jsonify({"error": "Not authorized"}), 403

    # Get last check timestamp from session or use a default
    last_check_key = f"pmo_updater_last_check_{user_id}"
    last_check = session.get(last_check_key)
    
    if last_check:
        try:
            last_check_date = datetime.fromisoformat(last_check.replace('Z', '').replace('+00:00', ''))
        except Exception:
            last_check_date = datetime.utcnow() - timedelta(minutes=5)
    else:
        last_check_date = datetime.utcnow() - timedelta(minutes=5)

    processed_requests = []
    # Find requests created by this updater that have been processed (approved/rejected) since last check
    query = {
        "created_by_pmo_id": ObjectId(user_id),
        "status": {"$in": ["Approved", "Rejected"]},
        "response_date": {"$gte": last_check_date}
    }
    cursor = mongo.db.points_request.find(query).sort("response_date", -1)
    for req in cursor:
        employee = mongo.db.users.find_one({"_id": req["user_id"]})
        validator = mongo.db.users.find_one({"_id": req.get("pmo_id")})
        category = mongo.db.categories.find_one({"_id": req["category_id"]})
        processed_requests.append({
            "id": str(req["_id"]),
            "employee_name": employee.get("name", "Unknown") if employee else "Unknown",
            "employee_id": employee.get("employee_id", "") if employee else "",
            "employee_department": (employee.get("department", "") if employee else "") or "Not Entered",
            "category_name": category.get("name", "Unknown") if category else "Unknown",
            "category_code": req.get("category_code", ""),
            "category_id": str(req.get("category_id", "")),
            "points": req.get("points", 0),
            "status": req.get("status"),
            "validator_name": validator.get("name", "Validator") if validator else "Validator",
            "notes": req.get("request_notes", ""),
            "actioned_by_name": validator.get("name", "Validator") if validator else "Validator",
            "submitted_by_name": user.get("name", "Updater") if user else "Updater",
            "request_date": req.get("request_date").strftime('%d-%m-%Y') if req.get("request_date") else "",
            "event_date": req.get("event_date").strftime('%d-%m-%Y') if req.get("event_date") else "", # Add this
            "response_notes": req.get("response_notes", ""),
            "response_date": req.get("response_date").strftime('%d-%m-%Y') if req.get("response_date") else "",
            "utilization_value": req.get("utilization_value"),
        })
    
    # Store current timestamp in session for next check
    current_timestamp = datetime.utcnow().isoformat()
    session[last_check_key] = current_timestamp
    
    return jsonify({
        "processed_requests": processed_requests,
        "timestamp": current_timestamp
    })

@pmo_bp.route('/updater/history-json', methods=['GET'])
def updater_history_json():
    """
    Returns the full processed request history for the logged-in PMO updater.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not authenticated"}), 401

    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user or user.get('manager_level') != 'PMO' or not user.get('manager_id'):
        return jsonify({"error": "Not authorized"}), 403

    # Get all requests created by this updater
    query = {
        "created_by_pmo_id": ObjectId(user_id),
        "status": {"$in": ["Approved", "Rejected", "Pending"]}
    }
    cursor = mongo.db.points_request.find(query).sort("request_date", -1)
    history = []
    category_name_map = {}
    for req in cursor:
        employee = mongo.db.users.find_one({"_id": req["user_id"]})
        validator = mongo.db.users.find_one({"_id": req.get("pmo_id")})
        category = mongo.db.categories.find_one({"_id": req["category_id"]})
        if category:
            category_name_map[req.get("category_code", "")] = category.get("name", "")
        request_notes = req.get("request_notes", "")
        cleaned_notes = request_notes
        history.append({
            "id": str(req["_id"]),
            "employee_name": employee.get("name", "Unknown") if employee else "Unknown",
            "employee_id": employee.get("employee_id", "") if employee else "",
            "employee_department": (employee.get("department", "") if employee else "") or "Not Entered",
            "category": category.get("name", "Unknown") if category else "Unknown",
            "category_code": req.get("category_code", ""),
            "category_id": str(req.get("category_id", "")),
            "points": req.get("points", 0),
            "status": req.get("status"),
            "validator_name": validator.get("name", "Validator") if validator else "Validator",
            "notes": request_notes,
            "actioned_by_name": validator.get("name", "Validator") if validator else "Validator",
            "submitted_by_name": user.get("name", "Updater") if user else "Updater",
            "request_date": req.get("request_date").strftime('%d-%m-%Y') if req.get("request_date") else "",
            "response_notes": req.get("response_notes", ""),
            "response_date": req.get("response_date").strftime('%d-%m-%Y') if req.get("response_date") else "",
            "cleaned_notes": cleaned_notes,
        })
    return jsonify({
        "history": history,
        "category_name_map": category_name_map
    })




def send_bulk_approval_notification_to_updater(updater, validator, approved_requests):
    """Sends a single summary email to the PMO updater for all approved requests."""
    try:
        total_points = sum(req.get('points', 0) for req in approved_requests)
        
        template_vars = {
            'updater_name': updater.get('name', 'PMO Updater'),
            'validator_name': validator.get('name', 'Validator'),
            'count': len(approved_requests),
            'requests': approved_requests,
            'total_points': total_points
        }

        from jinja2 import Template
        html_template = Template(get_email_template('bulk_approved_to_updater'))
        html_content = html_template.render(**template_vars)
        
        # Create plain text version
        text_content = f"""
Dear {template_vars['updater_name']},

Your bulk interview points upload has been processed. {template_vars['count']} requests have been approved by {template_vars['validator_name']}.

Total Points Awarded: {template_vars['total_points']}

"""
        
        return send_email_notification(
            updater.get('email'),
            updater.get('name'),
            f"Bulk Approval Summary: {len(approved_requests)} Requests Approved",
            html_content,
            text_content
        )
    except Exception as e:
        print(f"Error in send_bulk_approval_notification_to_updater: {str(e)}")
        return False


def send_bulk_rejection_notification_to_updater(updater, validator, rejected_requests):
    """Sends a single summary email to the PMo updater for all rejected requests."""
    try:
        template_vars = {
            'updater_name': updater.get('name', 'pmo Updater'),
            'validator_name': validator.get('name', 'Validator'),
            'count': len(rejected_requests),
            'requests': rejected_requests
        }

        from jinja2 import Template
        html_template = Template(get_email_template('bulk_rejected_to_updater'))
        html_content = html_template.render(**template_vars)
        
        # Create plain text version
        text_content = f"""
Dear {template_vars['updater_name']},

Your bulk interview points upload has been processed. {template_vars['count']} requests have been rejected by {template_vars['validator_name']}.

Please review the rejection reasons and resubmit if necessary.

"""
        
        return send_email_notification(
            updater.get('email'),
            updater.get('name'),
            f"Bulk Rejection Summary: {len(rejected_requests)} Requests Rejected",
            html_content,
            text_content
        )
    except Exception as e:
        print(f"Error in send_bulk_rejection_notification_to_updater: {str(e)}")
        return False



def send_bulk_approval_notification_to_employee(employee, validator, approved_requests):
    """Sends a single summary email to the employee for all their approved requests."""
    try:
        total_points = sum(req.get('points', 0) for req in approved_requests)
        
        template_vars = {
            'employee_name': employee.get('name', 'Employee'),
            'validator_name': validator.get('name', 'Validator'),
            'count': len(approved_requests),
            'requests': approved_requests,
            'total_points': total_points
        }

        from jinja2 import Template
        html_template = Template(get_email_template('bulk_approved_to_employee'))
        html_content = html_template.render(**template_vars)
        
        # Create plain text version
        text_content = f"""
Dear {template_vars['employee_name']},

Congratulations! Your {template_vars['count']} interview point submissions have been approved by {template_vars['validator_name']}.

Total Points Awarded: {template_vars['total_points']}

"""
        
        return send_email_notification(
            employee.get('email'),
            employee.get('name'),
            f"Interview Points Approved: {len(approved_requests)} Submissions",
            html_content,
            text_content
        )
    except Exception as e:
        print(f"Error in send_bulk_approval_notification_to_employee: {str(e)}")
        return False



def send_hr_approval_notification(requests_data, updater):
    """Sends a notification to all HR users about new R&R requests."""
    try:
        # Find all users with the 'HR' role who have an email
        hr_recipients = list(mongo.db.users.find({"role": "HR", "email": {"$exists": True}}))

        if not hr_recipients:
            error_print("No HR users with email found to send R&R notification.", None)
            return False

        base_url = request.url_root.rstrip('/')
        # NOTE: You may need to create a specific dashboard URL for HR
        hr_dashboard_url = base_url + url_for('auth.login') 
        submission_date = datetime.utcnow().strftime('%B %d, %Y at %I:%M %p')

        # Generate HTML table rows for each request
        request_rows = []
        for req in requests_data:
            row = f'''
            <tr>
                <td>{req.get('employee_id', 'N/A')}</td>
                <td>{req.get('employee_name', 'N/A')}</td>
                <td>{req.get('department', 'N/A')}</td>
                <td>{req.get('points', 0)}</td>
                <td>{req.get('notes', '')}</td>
            </tr>'''
            request_rows.append(row)

        template_vars = {
            'updater_name': updater.get('name', 'PMO Updater'),
            'total_requests': len(requests_data),
            'submission_date': submission_date,
            'hr_dashboard_url': hr_dashboard_url,
            'request_rows': '\n'.join(request_rows)
        }

        html_content = get_email_template('new_hr_requests')
        for key, value in template_vars.items():
            html_content = html_content.replace('{' + key + '}', str(value))
        
        subject = f'New R&R Requests for Approval - {len(requests_data)} Request(s)'
        
        # Send the email to each HR recipient
        for hr_user in hr_recipients:
            send_email_notification(
                to_email=hr_user.get('email'),
                to_name=hr_user.get('name', 'HR Team'),
                subject=subject,
                html_content=html_content
            )
        
        return True
    except Exception as e:
        error_print("Failed to send R&R requests notification to HR", e)
        return False


