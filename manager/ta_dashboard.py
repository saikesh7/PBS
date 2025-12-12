from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import os
from flask import Blueprint
from flask import Flask, render_template


# Import necessary functions from employee.routes for email notifications
from utils.error_handling import error_print


# Define Blueprint
current_dir = os.path.dirname(os.path.abspath(__file__))

ta_bp = Blueprint(
    'ta', __name__,
    url_prefix='/talent-acquisition',
    template_folder=os.path.join(current_dir, 'templates'),
    static_folder=os.path.join(current_dir, 'static'),
    static_url_path='/ta/static'  # Important!
)

# Avoid circular imports by importing mongo within functions
def get_mongo():
    from app import mongo
    return mongo


# ============================================================================
# DASHBOARD ACCESS CONTROL HELPER FUNCTIONS
# ============================================================================

def check_dashboard_access(user, required_dashboard):
    """
    Check if user has access to a specific dashboard
    Works for ANY role (Employee, Manager, etc.)
    
    Args:
        user: User document from MongoDB
        required_dashboard: Dashboard name to check (e.g., 'TA - Updater')
    
    Returns:
        Boolean indicating if user has access
    """
    dashboard_access = user.get('dashboard_access', [])
    
    # Normalize dashboard names for comparison
    from dashboard_config import normalize_dashboard_name
    
    normalized_required = normalize_dashboard_name(required_dashboard)
    
    for user_dashboard in dashboard_access:
        normalized_user = normalize_dashboard_name(user_dashboard)
        if normalized_user == normalized_required:
            return True
    
    return False


def get_user_redirect(user):
    """
    Get appropriate redirect URL for user based on their dashboard_access
    """
    from dashboard_config import get_redirect_for_unauthorized_user
    return get_redirect_for_unauthorized_user(user)


# ============================================================================
# EXISTING HELPER FUNCTIONS
# ============================================================================

# Define a filter for users considered "selectable employees" for TA dropdowns.
# This includes actual employees and managers who have any validator ID assigned to them.
SELECTABLE_EMPLOYEE_FILTER_FOR_TA = {
    "$or": [
        {"role": "Employee"},
        {
            "role": "Manager", # Only consider users with the role "Manager"
            "$or": [ # Check if any of the relevant validator IDs exist and are not null
                {"marketing_validator_id": {"$exists": True, "$ne": None}},
                {"pm_arch_validator_id": {"$exists": True, "$ne": None}},
                {"pm_validator_id": {"$exists": True, "$ne": None}},
                {"presales_validator_id": {"$exists": True, "$ne": None}},
                # Add other specific validator_id fields here if they can be directly on a manager's document
                # and indicate they "have a validator id" in the sense of being managed by one.
            ]
        }
    ]
}

# Helper function to determine financial quarter for a given date
def get_financial_quarter_dates(for_date=None):
    """
    Determines the financial quarter (Apr-Mar) for a given date.
    If no date is provided, it uses the current date.
    """
    if for_date is None:
        for_date = datetime.utcnow()
        
    year = for_date.year
    month = for_date.month

    if 4 <= month <= 6:
        quarter = 1
        financial_year = year
        start_date = datetime(year, 4, 1)
        end_date = datetime(year, 6, 30, 23, 59, 59)
    elif 7 <= month <= 9:
        quarter = 2
        financial_year = year
        start_date = datetime(year, 7, 1)
        end_date = datetime(year, 9, 30, 23, 59, 59)
    elif 10 <= month <= 12:
        quarter = 3
        financial_year = year
        start_date = datetime(year, 10, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
    else:  # Jan, Feb, Mar
        quarter = 4
        financial_year = year - 1
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 3, 31, 23, 59, 59)
        
    return {
        "start_date": start_date,
        "end_date": end_date,
        "quarter": quarter,
        "year": financial_year # This is the start year of the financial year
    }


def get_financial_quarter_and_month():
    now = datetime.utcnow()
    month = now.month
    year = now.year

    financial_year = year
    # Define April-March financial quarters
    if 4 <= month <= 6:
        quarter_label = "Q1"
    elif 7 <= month <= 9:
        quarter_label = "Q2"
    elif 10 <= month <= 12:
        quarter_label = "Q3"
    else:  # Jan, Feb, Mar
        quarter_label = "Q4"
        # For Q4 (Jan-Mar), the financial year is the one that started in April of the previous calendar year.
        financial_year = year - 1

    quarter_display = f"{quarter_label} {financial_year}"
    current_month_display = now.strftime("%B")  # Full month name like 'May'

    return quarter_display, current_month_display

def _parse_date_flexibly(date_str):
    """
    Parses a date string from common formats.
    Returns a datetime object or None.
    """
    if not date_str:
        return None
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None

def validate_event_date(event_date_str):
    """
    Validates event date string and returns datetime object or None
    Allows today and past dates, rejects future dates
    """
    if not event_date_str:
        return None, "Event date is required."
    
    event_date = _parse_date_flexibly(event_date_str)
    if not event_date:
        return None, "Invalid event date format. Please use a valid date format (e.g., DD-MM-YYYY)."
    
    today = datetime.utcnow().date()
    
    if event_date.date() > today:
        return None, "Event date cannot be in the future."
    
    return event_date, None


# ============================================================================
# DASHBOARD ROUTES WITH PROPER ACCESS CONTROL
# ============================================================================

@ta_bp.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    """
    TA Updater Dashboard
    Accessible by ANY user (regardless of role) who has 'TA - Updater' in their dashboard_access
    """
    tab = request.args.get('tab', 'reward_points')  # Default to 'reward_points'

    user_id = session.get('user_id')
    current_quarter, current_month = get_financial_quarter_and_month()

    # Check if user is logged in
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))

    try:
        mongo = get_mongo()
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))

        # ✅ NEW: Check dashboard_access instead of manager_level
        # This works for ANY role - Employee, Manager, etc.
        if not check_dashboard_access(user, 'TA - Updater'):
            flash('You do not have permission to access this page', 'danger')
            redirect_url = get_user_redirect(user)
            return redirect(redirect_url)

        # If user is a TA validator (has TA - Validator access and no manager_id),
        # redirect them to validator dashboard
        if check_dashboard_access(user, 'TA - Validator') and not user.get("manager_id"):
            return redirect(url_for('ta.validator_dashboard'))

        # Rest of your existing dashboard code continues here...
        if request.method == 'POST':
            action_type = request.form.get('action_type')

            # Single Interview Points Assignment
            if action_type == 'assign_interview_points':
                # Ensure non-validators (those with a manager_id) can perform this
                if not user.get("manager_id"):
                    flash("Validators should use the validator dashboard.", "warning")
                    return redirect(url_for('ta.validator_dashboard'))
                    
                employee_id = request.form.get('employee_id')
                notes = request.form.get('notes', '')
                event_date_str = request.form.get('event_date') # NEW: Get event date

                try:
                    number_of_interviews = int(request.form.get('number_of_interviews', 0))
                except (ValueError, TypeError):
                    flash('Number of interviews must be a valid number.', 'danger')
                    return redirect(url_for('ta.dashboard'))
                
                # NEW: Validate event_date
                event_date = None
                if event_date_str:
                    event_date = _parse_date_flexibly(event_date_str)
                    
                    if event_date is None:
                        flash('Invalid event date format. Please use a valid date format (e.g., YYYY-MM-DD).', 'danger')
                        return redirect(url_for('ta.dashboard'))

                    if event_date.date() > datetime.utcnow().date():
                        flash('Event date cannot be in the future.', 'danger')
                        return redirect(url_for('ta.dashboard'))

                if not employee_id or not notes or number_of_interviews <= 0:
                    flash('Employee, notes, and number of interviews (>0) are required.', 'danger')
                    return redirect(url_for('ta.dashboard'))

                employee = mongo.db.users.find_one({"employee_id": employee_id})
                if not employee:
                    flash('Employee not found. Please enter a valid Employee ID.', 'danger')
                    return redirect(url_for('ta.dashboard'))

                category = mongo.db.categories.find_one({"code": "interviews"})
                if not category:
                    flash('Interview category not found in database.', 'danger')
                    return redirect(url_for('ta.dashboard'))

                points_per_interview = category.get('points_per_unit', 0)
                if points_per_interview <= 0:
                    flash('Interview category has invalid points configuration.', 'danger')
                    return redirect(url_for('ta.dashboard'))

                total_points = points_per_interview * number_of_interviews

                manager_id = user.get('manager_id')
                if not manager_id:
                    flash('You do not have a validator assigned. Please contact HR.', 'danger')
                    return redirect(url_for('ta.dashboard'))

                request_data = {
                    "user_id": ObjectId(employee["_id"]),
                    "category_id": ObjectId(category["_id"]),
                    "points": total_points,
                    "request_notes": notes,
                    "updated_by": "TA",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date if event_date else datetime.utcnow(),
                    "assigned_validator_id": ObjectId(manager_id),
                    "created_by_ta_id": ObjectId(user['_id']),
                    "number_of_interviews": number_of_interviews
                }

                mongo.db.points_request.insert_one(request_data)
                flash(f'Successfully submitted request for {total_points} points ({number_of_interviews} interviews) to your validator.', 'success')
                
                try:
                    emit_pending_request_update()
                except:
                    pass

                return redirect(url_for('ta.dashboard'))

            # Bulk CSV Upload for Interview Points
            elif action_type == 'bulk_upload_interview_points':
                if not user.get("manager_id"):
                    flash("Validators should use the validator dashboard.", "warning")
                    return redirect(url_for('ta.validator_dashboard'))

                file = request.files.get('csv_file')
                if not file or file.filename == '':
                    flash('Please select a CSV file to upload.', 'danger')
                    return redirect(url_for('ta.dashboard'))

                manager_id = user.get('manager_id')
                if not manager_id:
                    flash('You do not have a validator assigned. Please contact HR.', 'danger')
                    return redirect(url_for('ta.dashboard'))

                errors, successes, success_count, error_count = process_bulk_upload(file, user, manager_id)

                if errors:
                    error_summary = "<br>".join(errors[:10])
                    if len(errors) > 10:
                        error_summary += f"<br>... and {len(errors) - 10} more errors."
                    flash(f'{error_count} error(s) encountered:<br>{error_summary}', 'danger')

                if successes:
                    flash(f'Successfully uploaded {success_count} interview point requests for approval.', 'success')
                    try:
                        emit_pending_request_update()
                    except:
                        pass

                return redirect(url_for('ta.dashboard'))

        # GET request - render dashboard
        managed_departments = []
        if user.get('managed_departments'):
            managed_departments = user['managed_departments']
        elif user.get('department'):
            managed_departments = [user['department']]

        employees_query = SELECTABLE_EMPLOYEE_FILTER_FOR_TA.copy()
        if managed_departments:
            employees_query["department"] = {"$in": managed_departments}

        employees = list(mongo.db.users.find(employees_query).sort("name", 1))

        # Fetch assignment history if user has a manager
        history = []
        if user.get('manager_id'):
            category = mongo.db.categories.find_one({"code": "interviews"})
            if category:
                history_query = {
                    "created_by_ta_id": ObjectId(user['_id']),
                    "category_id": ObjectId(category['_id']),
                    "status": {"$in": ["Approved", "Rejected"]}
                }
                
                history_cursor = mongo.db.points_request.find(history_query).sort("request_date", -1)
                
                for req_data in history_cursor:
                    employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
                    validator = mongo.db.users.find_one({"_id": req_data.get("assigned_validator_id")})
                    
                    if employee:
                        history.append({
                            'request_date': req_data["request_date"],
                            'employee_name': employee.get("name", "Unknown"),
                            'employee_id': employee.get("employee_id", "N/A"),
                            'number_of_interviews': req_data.get("number_of_interviews", 0),
                            'points': req_data.get("points", 0),
                            'validator_name': validator.get("name", "Unknown") if validator else "Unknown",
                            'status': req_data.get("status", "Unknown"),
                            'response_notes': req_data.get("response_notes", "")
                        })

        return render_template(
            'ta/dashboard.html',
            user=user,
            employees=employees,
            current_quarter=current_quarter,
            current_month=current_month,
            history=history,
            tab=tab
        )

    except Exception as e:
        error_print("Error in TA dashboard", e)
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))


@ta_bp.route('/validator_dashboard', methods=['GET', 'POST'])
def validator_dashboard():
    """
    TA Validator Dashboard
    Accessible by ANY user (regardless of role) who has 'TA - Validator' in their dashboard_access
    """
    user_id = session.get('user_id')
    current_quarter, current_month = get_financial_quarter_and_month()

    # Check if user is logged in
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))

    try:
        mongo = get_mongo()
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))

        # ✅ NEW: Check dashboard_access instead of manager_level
        # This works for ANY role - Employee, Manager, etc.
        if not check_dashboard_access(user, 'TA - Validator'):
            flash('You do not have permission to access this page', 'danger')
            redirect_url = get_user_redirect(user)
            return redirect(redirect_url)

        # Validator should not have a manager_id (they are top-level)
        # But allow access if they have the dashboard access regardless
        
        if request.method == 'POST':
            action_type = request.form.get('action_type')

            # Handle bulk approval
            if action_type == 'bulk_approve':
                selected_request_ids = request.form.getlist('selected_requests')
                
                if not selected_request_ids:
                    flash('No requests selected for approval.', 'warning')
                    return redirect(url_for('ta.validator_dashboard'))

                approved_count = 0
                approved_requests = []
                
                for request_id_str in selected_request_ids:
                    try:
                        request_id = ObjectId(request_id_str)
                        request_doc = mongo.db.points_request.find_one({"_id": request_id})
                        
                        if not request_doc or request_doc.get("status") != "Pending":
                            continue

                        mongo.db.points_request.update_one(
                            {"_id": request_id},
                            {
                                "$set": {
                                    "status": "Approved",
                                    "response_date": datetime.utcnow(),
                                    "response_notes": "Bulk approved"
                                }
                            }
                        )

                        employee = mongo.db.users.find_one({"_id": request_doc["user_id"]})
                        if employee:
                            current_points = employee.get("points", 0)
                            new_total = current_points + request_doc.get("points", 0)
                            
                            mongo.db.users.update_one(
                                {"_id": employee["_id"]},
                                {"$set": {"points": new_total}}
                            )

                        approved_requests.append(request_doc)
                        approved_count += 1

                    except Exception as e:
                        error_print(f"Error approving request {request_id_str}", e)
                        continue

                flash(f'Successfully approved {approved_count} requests.', 'success')
                
                try:
                    emit_updater_history_update()
                except:
                    pass

                return redirect(url_for('ta.validator_dashboard'))

            # Handle bulk rejection
            elif action_type == 'bulk_reject':
                selected_request_ids = request.form.getlist('selected_requests')
                rejection_notes = request.form.get('rejection_notes', 'No reason provided')
                
                if not selected_request_ids:
                    flash('No requests selected for rejection.', 'warning')
                    return redirect(url_for('ta.validator_dashboard'))

                rejected_count = 0
                
                for request_id_str in selected_request_ids:
                    try:
                        request_id = ObjectId(request_id_str)
                        request_doc = mongo.db.points_request.find_one({"_id": request_id})
                        
                        if not request_doc or request_doc.get("status") != "Pending":
                            continue

                        mongo.db.points_request.update_one(
                            {"_id": request_id},
                            {
                                "$set": {
                                    "status": "Rejected",
                                    "response_date": datetime.utcnow(),
                                    "response_notes": rejection_notes
                                }
                            }
                        )

                        rejected_count += 1

                    except Exception as e:
                        error_print(f"Error rejecting request {request_id_str}", e)
                        continue

                flash(f'Successfully rejected {rejected_count} requests.', 'success')
                
                try:
                    emit_updater_history_update()
                except:
                    pass

                return redirect(url_for('ta.validator_dashboard'))

        # GET request - render validator dashboard
        category = mongo.db.categories.find_one({"code": "interviews"})
        
        if not category:
            flash('Interview category not found in database.', 'danger')
            pending_requests = []
        else:
            pending_query = {
                "category_id": ObjectId(category['_id']),
                "assigned_validator_id": ObjectId(user_id),
                "status": "Pending"
            }
            
            pending_cursor = mongo.db.points_request.find(pending_query).sort("request_date", 1)
            pending_requests = []
            
            for req_data in pending_cursor:
                employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
                updater = mongo.db.users.find_one({"_id": req_data.get("created_by_ta_id")})
                
                if employee:
                    pending_requests.append({
                        'request_id': str(req_data['_id']),
                        'request_date': req_data["request_date"],
                        'employee_name': employee.get("name", "Unknown"),
                        'employee_id': employee.get("employee_id", "N/A"),
                        'department': employee.get("department", "N/A"),
                        'number_of_interviews': req_data.get("number_of_interviews", 0),
                        'points': req_data.get("points", 0),
                        'notes': req_data.get("request_notes", ""),
                        'updater_name': updater.get("name", "Unknown") if updater else "Unknown"
                    })

        return render_template(
            'ta/validator_dashboard.html',
            user=user,
            pending_requests=pending_requests,
            current_quarter=current_quarter,
            current_month=current_month
        )

    except Exception as e:
        error_print("Error in TA validator dashboard", e)
        flash('An error occurred while loading the validator dashboard.', 'danger')
        return redirect(url_for('auth.login'))


# ============================================================================
# HELPER FUNCTIONS FOR BULK UPLOAD
# ============================================================================

def process_bulk_upload(file, user, manager_id):
    """Process bulk CSV upload for interview points"""
    import csv
    import io
    
    errors = []
    successes = []
    success_count = 0
    error_count = 0
    
    try:
        mongo = get_mongo()
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        expected_headers = ['employee_id', 'event_date', 'number_of_interviews', 'notes']
        if csv_reader.fieldnames != expected_headers:
            errors.append("Invalid CSV template. Expected headers: employee_id, event_date, number_of_interviews, notes")
            return errors, successes, success_count, error_count

        category = mongo.db.categories.find_one({"code": "interviews"})
        if not category:
            errors.append("Interview category not found in database.")
            return errors, successes, success_count, error_count

        points_per_interview = category.get('points_per_unit', 0)
        if points_per_interview <= 0:
            errors.append("Interview category has invalid points configuration.")
            return errors, successes, success_count, error_count

        for row_num, row in enumerate(csv_reader, start=2):
            try:
                employee_id = row.get('employee_id', '').strip()
                event_date_str = row.get('event_date', '').strip()
                number_of_interviews_str = row.get('number_of_interviews', '').strip()
                notes = row.get('notes', '').strip()

                if not employee_id or not event_date_str or not number_of_interviews_str or not notes:
                    errors.append(f"Row {row_num}: Missing required fields.")
                    error_count += 1
                    continue

                try:
                    number_of_interviews = int(number_of_interviews_str)
                    if number_of_interviews <= 0:
                        raise ValueError("Must be positive")
                except ValueError:
                    errors.append(f"Row {row_num}: Invalid number of interviews '{number_of_interviews_str}'.")
                    error_count += 1
                    continue

                event_date = _parse_date_flexibly(event_date_str)
                if not event_date:
                    errors.append(f"Row {row_num}: Invalid event date '{event_date_str}'.")
                    error_count += 1
                    continue

                if event_date.date() > datetime.utcnow().date():
                    errors.append(f"Row {row_num}: Event date cannot be in the future.")
                    error_count += 1
                    continue

                employee = mongo.db.users.find_one({"employee_id": employee_id})
                if not employee:
                    errors.append(f"Row {row_num}: Employee ID '{employee_id}' not found.")
                    error_count += 1
                    continue

                total_points = points_per_interview * number_of_interviews

                request_data = {
                    "user_id": ObjectId(employee["_id"]),
                    "category_id": ObjectId(category["_id"]),
                    "points": total_points,
                    "request_notes": notes,
                    "updated_by": "TA",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date,
                    "assigned_validator_id": ObjectId(manager_id),
                    "created_by_ta_id": ObjectId(user['_id']),
                    "number_of_interviews": number_of_interviews
                }

                mongo.db.points_request.insert_one(request_data)
                successes.append(f"Row {row_num}: Success - {employee.get('name')} - {total_points} points")
                success_count += 1

            except Exception as e:
                errors.append(f"Row {row_num}: Error - {str(e)}")
                error_count += 1
                continue

    except Exception as e:
        errors.append(f"File processing error: {str(e)}")
        error_count += 1

    return errors, successes, success_count, error_count


# ============================================================================
# EMAIL NOTIFICATION FUNCTIONS (Keep your existing ones)
# ============================================================================

def get_email_template(template_name):
    """Get email template - placeholder, implement based on your system"""
    # Import your email template system here
    from employee.routes import get_email_template as employee_get_template
    return employee_get_template(template_name)


def send_email_notification(to_email, to_name, subject, html_content):
    """Send email notification - placeholder, implement based on your system"""
    # Import your email sending function here
    from employee.routes import send_email_notification as employee_send_email
    return employee_send_email(to_email, to_name, subject, html_content)


def send_bulk_request_notification_to_validator(validator, updater, requests, category):
    """
    Sends a notification to the validator about bulk requests from a TA updater.
    """
    try:
        template = get_email_template('bulk_request_to_validator')
        
        request_rows_html = ""
        mongo = get_mongo()
        for req in requests:
            employee = mongo.db.users.find_one({"_id": req["user_id"]})
            request_rows_html += f"""
            <tr>
                <td>{employee.get('employee_id', 'N/A')}</td>
                <td>{employee.get('name', 'Unknown')}</td>
                <td>{employee.get('department', 'N/A')}</td>
                <td>{category.get('name', 'Interviews')}</td>
                <td>{req['points']}</td>
            </tr>
            """

        html_content = template.render(
            validator_name=validator.get('name', 'Validator'),
            updater_name=updater.get('name', 'TA Updater'),
            total_requests=len(requests),
            request_rows=request_rows_html,
            validator_dashboard_url=url_for('ta.validator_dashboard', _external=True)
        )
        
        subject = f"Bulk Interview Points Upload from {updater.get('name')} for Approval"
        send_email_notification(validator.get('email'), validator.get('name'), subject, html_content)

    except Exception as e:
        error_print(f"Error sending bulk request notification to validator {validator.get('email')}", e)


def send_approval_notification(request_data, recipient, validator, category):
    """
    Send email notification to the employee or updater that their request has been approved.
    """
    try:
        template = get_email_template('approved_request')
        
        html_content = template.render(
            recipient_name=recipient.get('name', 'User'),
            category_name=category.get('name', 'Unknown Category'),
            points=request_data.get('points', 0),
            validator_name=validator.get('name', 'Validator'),
            decision_date=datetime.utcnow().strftime('%d-%m-%Y'),
            response_notes=request_data.get('response_notes', 'Approved')
        )
        
        subject = f"Your Points Request for '{category.get('name')}' has been Approved"
        send_email_notification(recipient.get('email'), recipient.get('name'), subject, html_content)

    except Exception as e:
        error_print(f"Error sending approval notification for request {request_data.get('_id')}", e)


def send_rejection_notification(request_data, recipient, validator, category):
    """
    Send email notification to the employee or updater that their request has been rejected.
    """
    try:
        template = get_email_template('rejected_request')
        
        html_content = template.render(
            recipient_name=recipient.get('name', 'User'),
            category_name=category.get('name', 'Unknown Category'),
            points=request_data.get('points', 0),
            validator_name=validator.get('name', 'Validator'),
            decision_date=datetime.utcnow().strftime('%d-%m-%Y'),
            response_notes=request_data.get('response_notes', 'No reason provided')
        )
        
        subject = f"Update on Your Points Request for '{category.get('name')}'"
        send_email_notification(recipient.get('email'), recipient.get('name'), subject, html_content)

    except Exception as e:
        error_print(f"Error sending rejection notification for request {request_data.get('_id')}", e)


def send_bulk_approval_notification_to_updater(updater, validator, approved_requests):
    """
    Sends a single summary email to the TA updater about all approved requests.
    """
    try:
        template = get_email_template('bulk_approved_to_updater')
        total_points = sum(req['points'] for req in approved_requests)
        
        mongo = get_mongo()
        request_details = []
        for req in approved_requests:
            employee = mongo.db.users.find_one({"_id": req["user_id"]})
            request_details.append({
                'employee_id': employee.get('employee_id', 'N/A'),
                'employee_name': employee.get('name', 'Unknown'),
                'department': employee.get('department', 'N/A'),
                'category': 'Interviews',
                'points': req['points']
            })

        html_content = template.render(
            updater_name=updater.get('name', 'Updater'),
            validator_name=validator.get('name', 'Validator'),
            count=len(approved_requests),
            total_points=total_points,
            request_rows=request_details
        )
        
        subject = f"Bulk Interview Requests Approved by {validator.get('name')}"
        send_email_notification(updater.get('email'), updater.get('name'), subject, html_content)

    except Exception as e:
        error_print(f"Error sending bulk approval to updater {updater.get('email')}", e)


def send_bulk_rejection_notification_to_updater(updater, validator, rejected_requests):
    """
    Sends a single summary email to the TA updater about all rejected requests.
    """
    try:
        template = get_email_template('bulk_rejected_to_updater')
        
        mongo = get_mongo()
        request_details = []
        for req in rejected_requests:
            employee = mongo.db.users.find_one({"_id": req["user_id"]})
            request_details.append({
                'employee_id': employee.get('employee_id', 'N/A'),
                'employee_name': employee.get('name', 'Unknown'),
                'department': employee.get('department', 'N/A'),
                'category': 'Interviews',
                'points': req['points']
            })

        html_content = template.render(
            updater_name=updater.get('name', 'Updater'),
            validator_name=validator.get('name', 'Validator'),
            count=len(rejected_requests),
            request_rows=request_details
        )
        
        subject = f"Bulk Interview Requests Rejected by {validator.get('name')}"
        send_email_notification(updater.get('email'), updater.get('name'), subject, html_content)

    except Exception as e:
        error_print(f"Error sending bulk rejection to updater {updater.get('email')}", e)


def send_bulk_approval_notification_to_employee(employee, validator, approved_requests):
    """
    Sends a single summary email to an employee about all their approved requests from a bulk action.
    """
    try:
        template = get_email_template('bulk_approved_to_employee')
        total_points = sum(req['points'] for req in approved_requests)

        html_content = template.render(
            employee_name=employee.get('name', 'Employee'),
            validator_name=validator.get('name', 'Validator'),
            count=len(approved_requests),
            total_points=total_points,
            requests=approved_requests
        )
        
        subject = f"You Have Received {total_points} Points for Interviews"
        send_email_notification(employee.get('email'), employee.get('name'), subject, html_content)

    except Exception as e:
        error_print(f"Error sending bulk approval to employee {employee.get('email')}", e)


# ============================================================================
# SOCKETIO INTEGRATION
# ============================================================================

try:
    from app import socketio
    from flask_socketio import emit

    def emit_pending_request_update():
        """ Emits an event to all clients to refresh the validator dashboard. """
        try:
            socketio.emit('refresh_validator_dashboard', {'source': 'ta_updater'})
        except Exception as e:
            error_print("SocketIO emit failed in TA dashboard", e)
            
    def emit_updater_history_update():
        """ Emits an event to all TA updaters to refresh their history table. """
        try:
            socketio.emit('updater_history_updated', {'source': 'ta_validator'})
        except Exception as e:
            error_print("SocketIO emit failed for updater history update", e)

except ImportError:
    print("SocketIO not installed or initialized. Real-time updates will be disabled.")
    def emit_pending_request_update():
        pass # No-op if socketio is not available
    def emit_updater_history_update():
        pass 


# ============================================================================
# UTILITY FUNCTIONS FOR LOGGING
# ============================================================================

def debug_print(message):
    """Prints a debug message with timestamp if in debug mode."""
    # In a real app, you'd check app.debug, but this is a simple way
    if os.environ.get('FLASK_DEBUG') == '1':
        print(f"[DEBUG - {datetime.now()}] {message}")