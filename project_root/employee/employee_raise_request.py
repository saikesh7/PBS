from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_mail import Message
from extensions import mongo, mail
from datetime import datetime
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
from gridfs import GridFS
import io
import smtplib
import email.utils
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

ENABLE_EMAIL_NOTIFICATIONS = True

def truncate_notes(notes, max_length=200):
    """Truncate notes to maximum length for email templates"""
    if not notes:
        return ''
    notes_str = str(notes).strip()
    if len(notes_str) > max_length:
        return notes_str[:max_length] + '...'
    return notes_str

# Email configuration
EMAIL_CONFIG = {
    'SMTP_SERVER': 'smtp-mail.outlook.com',
    'SMTP_PORT': 587,
    'SMTP_USERNAME': 'pbs@prowesssoft.com',
    'SMTP_PASSWORD': 'thffnrhmbjnjlsjd',
    'FROM_EMAIL': 'pbs@prowesssoft.com',
    'FROM_NAME': 'ProwessSoft Points System',
    'REPLY_TO_EMAIL': 'pbs@prowesssoft.com',
    'REPLY_TO_NAME': 'Prowess Points Support'
}

employee_raise_request_bp = Blueprint(
    'employee_raise_request', 
    __name__, 
    url_prefix='/employee',
    template_folder='templates',
    static_folder='static'
)


def send_validator_notification(request_doc, employee, validator, category):
    """Send email notification to validator when an employee raises a request"""
    
    if not ENABLE_EMAIL_NOTIFICATIONS:
        return True
    
    try:
        employee_name = employee.get('name', 'Unknown Employee')
        employee_id = employee.get('employee_id', 'N/A')
        employee_email = employee.get('email', 'N/A')
        employee_grade = employee.get('grade', 'N/A')
        employee_department = employee.get('department', 'N/A')
        
        validator_name = validator.get('name', 'Validator')
        validator_email = validator.get('email')
        
        if not validator_email:
            return False
        
        category_name = category.get('name', 'Unknown Category')
        category_department = category.get('category_department', 'N/A')
        category_frequency = category.get('frequency', 'One-time')
        
        points = request_doc.get('points', 0)
        submission_notes = truncate_notes(request_doc.get('submission_notes', 'No notes provided'))
        request_date = request_doc.get('request_date', datetime.utcnow())
        has_attachment = request_doc.get('has_attachment', False)
        attachment_filename = request_doc.get('attachment_filename', '')
        is_pm_category = request_doc.get('is_pm_category', False)
        
        if isinstance(request_date, datetime):
            formatted_date = request_date.strftime('%B %d, %Y at %I:%M %p')
        else:
            formatted_date = 'Unknown date'
        
        # Set dashboard URL - all validators redirect to login page
        dashboard_url = "https://pbs.prowesssoft.com/auth/login"
        
        request_type = "PM (Project Management)" if is_pm_category else category_department.upper()
        subject = f"New Points Request from {employee_name} - {category_name}"
        
        html_body = create_email_html_template(
            validator_name, employee_name, employee_id, employee_email, 
            employee_grade, employee_department, category_name, category_department,
            category_frequency, points, submission_notes, formatted_date, 
            has_attachment, attachment_filename, is_pm_category, dashboard_url
        )
        
        text_body = create_email_text_template(
            validator_name, employee_name, employee_id, employee_email,
            employee_grade, employee_department, category_name, request_type,
            points, submission_notes, formatted_date, has_attachment, attachment_filename
        )
        
        # Create email message using SMTP directly (more reliable than Flask-Mail)
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = formataddr((EMAIL_CONFIG['FROM_NAME'], EMAIL_CONFIG['FROM_EMAIL']))
        msg['To'] = formataddr((validator_name, validator_email))
        msg['Message-ID'] = email.utils.make_msgid()
        msg['Date'] = email.utils.formatdate(localtime=True)
        msg['Reply-To'] = EMAIL_CONFIG['FROM_EMAIL']
        msg['X-Mailer'] = 'Python SMTP'
        msg['Content-Type'] = 'text/html; charset=utf-8'
        msg.add_header('List-Unsubscribe', f"<mailto:{EMAIL_CONFIG['FROM_EMAIL']}>")
        
        # Attach text and HTML parts
        text_part = MIMEText(text_body, 'plain', _charset='utf-8')
        html_part = MIMEText(html_body, 'html', _charset='utf-8')
        msg.attach(text_part)
        msg.attach(html_part)
        
        # Send email with timeout to prevent blocking
        with smtplib.SMTP(EMAIL_CONFIG['SMTP_SERVER'], EMAIL_CONFIG['SMTP_PORT'], timeout=10) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['SMTP_USERNAME'], EMAIL_CONFIG['SMTP_PASSWORD'])
            server.send_message(msg)
        
        return True
        
    except Exception as e:
        return False


def create_email_html_template(validator_name, employee_name, employee_id, employee_email, 
                               employee_grade, employee_department, category_name, category_department,
                               category_frequency, points, submission_notes, formatted_date, 
                               has_attachment, attachment_filename, is_pm_category, dashboard_url):
    """Create HTML email template with single unified table"""
    
    display_notes = submission_notes if submission_notes else 'No notes provided'
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Points Request for Validation</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">New Points Request for Validation</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {validator_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">You have received a new points request that requires your validation:</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Employee Name:</td>
                                    <td style="color: #333; font-size: 14px;">{employee_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Employee ID:</td>
                                    <td style="color: #333; font-size: 14px;">{employee_id}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Email:</td>
                                    <td style="color: #333; font-size: 14px;">{employee_email}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Employee Grade:</td>
                                    <td style="color: #333; font-size: 14px;">{employee_grade}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Department:</td>
                                    <td style="color: #333; font-size: 14px;">{employee_department}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Category:</td>
                                    <td style="color: #333; font-size: 14px;">{category_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Points Requested:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{points}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Submission Date:</td>
                                    <td style="color: #333; font-size: 14px;">{formatted_date}</td>
                                </tr>
                                {f'''<tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Attachment:</td>
                                    <td style="color: #333; font-size: 14px;">Yes ({attachment_filename})</td>
                                </tr>''' if has_attachment else ''}
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Employee Notes -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <h3 style="color: #333; margin: 0 0 10px 0; font-size: 16px; font-weight: bold;">Employee's Notes:</h3>
                            <div style="background-color: #fff; padding: 15px; border-left: 3px solid #4CAF50; border: 1px solid #e0e0e0;">
                                <p style="color: #333; font-size: 14px; line-height: 1.6; margin: 0; white-space: pre-wrap;">{display_notes}</p>
                            </div>
                        </td>
                    </tr>
                    
                    <!-- Action Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">Please log in to the system to review and process this request.</p>
                        </td>
                    </tr>
                    
                    <!-- Button -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px; text-align: center;">
                            <a href="{dashboard_url}" style="display: inline-block; background-color: #4CAF50; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">Go to Dashboard</a>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f9f9f9; padding: 20px 30px; border-top: 1px solid #e0e0e0; text-align: center;">
                           
                            
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
    
    return html


def create_email_text_template(validator_name, employee_name, employee_id, employee_email,
                               employee_grade, employee_department, category_name, category_department,
                               points, submission_notes, formatted_date, has_attachment, attachment_filename):
    """Create plain text email template"""
    
    attachment_text = f"\nAttachment: {attachment_filename}" if has_attachment else ""
    
    text = f"""
═══════════════════════════════════════════════════════════
🎯 NEW POINTS REQUEST - PROWESS POINTS SYSTEM
═══════════════════════════════════════════════════════════

Hello {validator_name},

You have received a new points request that requires your review and approval.

───────────────────────────────────────────────────────────
👤 EMPLOYEE INFORMATION
───────────────────────────────────────────────────────────
Name:          {employee_name}
Employee ID:   {employee_id}
Email:         {employee_email}
Grade:         {employee_grade}
Department:    {employee_department}

───────────────────────────────────────────────────────────
📋 REQUEST DETAILS
───────────────────────────────────────────────────────────
Category:      {category_name}
Department:    {category_department}
Points:        ⭐ {points} Points
Submitted:     {formatted_date}{attachment_text}

───────────────────────────────────────────────────────────
📝 SUBMISSION NOTES
───────────────────────────────────────────────────────────
{submission_notes}

───────────────────────────────────────────────────────────

© 2025 Prowess Software Services. All rights reserved.
    """
    
    return text.strip()


@employee_raise_request_bp.route('/raise-request')
def raise_request():
    """Render the raise request page"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return redirect(url_for('auth.login'))
    
    assigned_manager = None
    if user.get('manager_id'):
        assigned_manager = mongo.db.users.find_one({'_id': user['manager_id']})
    
    categories = list(mongo.db.hr_categories.find({
        'category_type': 'Employee raised',
        'category_status': 'active'
    }).sort('name', 1))
    
    for category in categories:
        category['_id'] = str(category['_id'])
    
    pending_requests = []
    # ✅ Only show employee-raised pending requests (exclude direct awards)
    pending_reqs = mongo.db.points_request.find({
        'user_id': ObjectId(user_id),
        'status': 'Pending',
        # Exclude direct awards by ensuring these fields don't exist
        'created_by_ta_id': {'$exists': False},
        'created_by_pmo_id': {'$exists': False},
        'created_by_hr_id': {'$exists': False},
        'created_by_ld_id': {'$exists': False},
        'created_by_manager_id': {'$exists': False},
        # Also ensure if created_by exists, it's the employee themselves
        '$or': [
            {'created_by': {'$exists': False}},
            {'created_by': ObjectId(user_id)}
        ]
    }).sort('request_date', -1)
    
    for req in pending_reqs:
        category = mongo.db.hr_categories.find_one({'_id': req.get('category_id')})
        validator = mongo.db.users.find_one({'_id': req.get('assigned_validator_id')})
        
        pending_requests.append({
            'id': str(req['_id']),
            'category_name': category.get('name', 'Unknown') if category else 'Unknown',
            'category_department': category.get('category_department', 'Unknown') if category else 'Unknown',
            'points': req.get('points', 0),
            'assigned_validator_name': validator.get('name') if validator else None,
            'assigned_validator_emp_id': validator.get('employee_id') if validator else None,
            'request_date': req.get('request_date'),
            'submission_notes': req.get('submission_notes'),
            'has_attachment': req.get('has_attachment', False),
            'attachment_filename': req.get('attachment_filename', '')
        })
    
    return render_template('employee_raise_request.html',
                         user=user,
                         assigned_manager=assigned_manager,
                         categories=categories,
                         pending_requests=pending_requests,
                         other_dashboards=[],
                         user_profile_pic_url=None)


@employee_raise_request_bp.route('/submit-request', methods=['POST'])
def submit_request():
    """Handle form submission for raise request"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    try:
        category_id = request.form.get('category_id', '').strip()
        validator_id = request.form.get('selected_validator_id', '').strip() or request.form.get('validator_id', '').strip()
        notes = request.form.get('notes', '').strip()
        attachment = request.files.get('attachment')
        
        if not category_id:
            flash('Please select a category', 'danger')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        if not notes:
            flash('Please provide submission notes', 'danger')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        try:
            category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        except:
            flash('Invalid category selected', 'danger')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        if not category:
            flash('Selected category not found', 'danger')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            flash('User account not found', 'danger')
            return redirect(url_for('auth.login'))
        
        category_department = category.get('category_department', '').strip().lower()
        is_pm_category = category_department == 'pm'
        
        if is_pm_category:
            if not user.get('manager_id'):
                flash('You do not have an assigned manager. Please contact HR to assign a manager before raising PM requests.', 'danger')
                return redirect(url_for('employee_raise_request.raise_request'))
            
            validator_id = str(user['manager_id'])
            
            manager = mongo.db.users.find_one({'_id': user['manager_id']})
            if not manager:
                flash('Your assigned manager was not found in the system. Please contact HR.', 'danger')
                return redirect(url_for('employee_raise_request.raise_request'))
            
            dashboard_access = manager.get('dashboard_access', [])
            if 'pm' not in dashboard_access:
                flash('Your assigned manager does not have PM dashboard access. Please contact HR to update manager permissions.', 'danger')
                return redirect(url_for('employee_raise_request.raise_request'))
                
        else:
            if not validator_id:
                flash('Please select a validator from the dropdown list', 'danger')
                return redirect(url_for('employee_raise_request.raise_request'))
            
            try:
                validator = mongo.db.users.find_one({'_id': ObjectId(validator_id)})
            except:
                flash('Invalid validator selected. Please try again.', 'danger')
                return redirect(url_for('employee_raise_request.raise_request'))
            
            if not validator:
                flash('Selected validator not found in the system. Please try again or contact HR.', 'danger')
                return redirect(url_for('employee_raise_request.raise_request'))
            
            validator_access = validator.get('dashboard_access', [])
            if category_department not in validator_access:
                flash(f'Selected validator does not have access to {category_department.upper()} dashboard. Please select another validator or contact HR.', 'danger')
                return redirect(url_for('employee_raise_request.raise_request'))
        
        user_grade = user.get('grade', 'D2')
        points_per_unit = category.get('points_per_unit', {})
        
        if isinstance(points_per_unit, dict):
            points = points_per_unit.get(user_grade, points_per_unit.get('base', 0))
        else:
            points = int(points_per_unit) if points_per_unit else 0
        
        attachment_id = None
        attachment_filename = None
        has_attachment = False
        
        if attachment and attachment.filename:
            try:
                file_data = attachment.read()
                file_size = len(file_data)
                
                if file_size > 5 * 1024 * 1024:
                    flash('Attachment file size exceeds 5MB limit. Request will be submitted without attachment.', 'warning')
                elif file_size > 0:
                    fs = GridFS(mongo.db)
                    secure_name = secure_filename(attachment.filename)
                    
                    attachment_id = fs.put(
                        file_data,
                        filename=secure_name,
                        content_type=attachment.content_type or 'application/octet-stream',
                        metadata={
                            'original_filename': secure_name,
                            'user_id': str(user_id),
                            'upload_date': datetime.utcnow(),
                            'category_id': str(category_id),
                            'file_size': file_size
                        }
                    )
                    
                    attachment_filename = secure_name
                    has_attachment = True
                    
            except:
                flash('Error uploading attachment. Request will be submitted without attachment.', 'warning')
        
        request_doc = {
            'user_id': ObjectId(user_id),
            'category_id': ObjectId(category_id),
            'assigned_validator_id': ObjectId(validator_id),
            'points': points,
            'user_grade': user_grade,
            'submission_notes': notes,
            'request_notes': notes,
            'has_attachment': has_attachment,
            'attachment_id': attachment_id,
            'attachment_filename': attachment_filename,
            'status': 'Pending',
            'request_date': datetime.utcnow(),
            'event_date': datetime.utcnow(),
            'source': 'employee_request',
            'created_by': ObjectId(user_id),
            'updated_by': 'Employee',
            'category_name': category.get('name'),
            'category_department': category.get('category_department'),
            'frequency': category.get('frequency'),
            'validator': category.get('category_department', 'Unknown').upper(),
            'is_pm_category': is_pm_category,
            'is_bonus': False
        }
        
        result = mongo.db.points_request.insert_one(request_doc)
        request_doc['_id'] = result.inserted_id
        
        # Publish realtime event
        try:
            from services.realtime_events import publish_request_raised
            validator_user = mongo.db.users.find_one({"_id": ObjectId(validator_id)})
            if validator_user:
                publish_request_raised(request_doc, user, validator_user, category)
        except Exception as e:
            pass
        
        # Send email notification to assigned validator (single email, no duplicates)
        try:
            validator_user = mongo.db.users.find_one({"_id": ObjectId(validator_id)})
            if validator_user:
                send_validator_notification(request_doc, user, validator_user, category)
        except Exception as e:
            pass
        
        if is_pm_category:
            manager = mongo.db.users.find_one({"_id": ObjectId(validator_id)})
            manager_name = manager.get('name', 'your manager') if manager else 'your manager'
            flash(f'Request submitted successfully to {manager_name}! You will receive {points} points upon approval.', 'success')
        else:
            validator_user = mongo.db.users.find_one({"_id": ObjectId(validator_id)})
            validator_name = validator_user.get('name', 'the validator') if validator_user else 'the validator'
            flash(f'Request submitted successfully to {validator_name} ({category_department.upper()})! You will receive {points} points upon approval.', 'success')
        
        return redirect(url_for('employee_raise_request.raise_request'))
        
    except:
        flash('An unexpected error occurred while submitting your request. Please try again or contact support.', 'danger')
        return redirect(url_for('employee_raise_request.raise_request'))


@employee_raise_request_bp.route('/api/get-validators-by-category/<category_id>')
def get_validators_by_category(category_id):
    """API to get validators for a specific category"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated', 'success': False}), 401
    
    try:
        category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        
        if not category:
            return jsonify({'error': 'Category not found', 'success': False}), 404
        
        category_department = category.get('category_department', '').strip().lower()
        is_pm_category = category_department == 'pm'
        
        if is_pm_category:
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            
            if not user or not user.get('manager_id'):
                return jsonify({
                    'error': 'You do not have an assigned manager. Please contact HR.',
                    'success': False,
                    'is_pm_category': True,
                    'has_manager': False
                }), 400
            
            manager = mongo.db.users.find_one({'_id': user['manager_id']})
            
            if not manager:
                return jsonify({
                    'error': 'Your assigned manager was not found. Please contact HR.',
                    'success': False,
                    'is_pm_category': True,
                    'has_manager': False
                }), 400
            
            if 'pm' not in manager.get('dashboard_access', []):
                return jsonify({
                    'error': 'Your assigned manager does not have PM dashboard access. Please contact HR.',
                    'success': False,
                    'is_pm_category': True,
                    'has_manager': True
                }), 400
            
            return jsonify({
                'success': True,
                'is_pm_category': True,
                'has_manager': True,
                'assigned_manager': {
                    'id': str(manager['_id']),
                    'name': manager.get('name', 'Unknown'),
                    'employee_id': manager.get('employee_id', 'N/A'),
                    'role': manager.get('role', 'Manager'),
                    'grade': manager.get('grade', 'N/A'),
                    'email': manager.get('email', 'N/A')
                },
                'department': category_department.upper(),
                'department_name': 'PM (Project Management)',
                'message': 'This request will be assigned to your designated manager.'
            })
        
        validators = list(mongo.db.users.find({
            'dashboard_access': category_department,
            'is_active': {'$ne': False},
            '_id': {'$ne': ObjectId(user_id)}
        }, {
            '_id': 1,
            'name': 1,
            'employee_id': 1,
            'role': 1,
            'grade': 1,
            'email': 1
        }).sort('name', 1))
        
        if not validators:
            return jsonify({
                'error': f'No active validators found for {category_department.upper()} department. Please contact HR.',
                'success': False,
                'is_pm_category': False
            }), 404
        
        validators_list = [{
            'id': str(v['_id']),
            'name': v.get('name', 'Unknown'),
            'employee_id': v.get('employee_id', 'N/A'),
            'role': v.get('role', 'Employee'),
            'grade': v.get('grade', 'N/A'),
            'email': v.get('email', 'N/A')
        } for v in validators]
        
        return jsonify({
            'success': True,
            'is_pm_category': False,
            'validators': validators_list,
            'count': len(validators_list),
            'department': category_department.upper(),
            'department_name': category_department.replace('_', ' ').upper()
        })
        
    except:
        return jsonify({
            'error': 'Unable to retrieve validators. Please try again.',
            'success': False
        }), 500


@employee_raise_request_bp.route('/get-category-details/<category_id>')
def get_category_details(category_id):
    """Get category details including points for user's grade"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated', 'success': False}), 401
    
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        
        if not category or not user:
            return jsonify({'error': 'Not found', 'success': False}), 404
        
        user_grade = user.get('grade', 'D2')
        
        points_per_unit_config = category.get('points_per_unit', {})
        if isinstance(points_per_unit_config, dict):
            points_per_unit = points_per_unit_config.get(user_grade, points_per_unit_config.get('base', 0))
        else:
            points_per_unit = points_per_unit_config
        
        min_points_config = category.get('min_points_per_frequency', {})
        if isinstance(min_points_config, dict):
            min_points = min_points_config.get(user_grade, 0)
        else:
            min_points = min_points_config
        
        category_department = category.get('category_department', 'N/A')
        
        return jsonify({
            'success': True,
            'grade': user_grade,
            'points_per_unit': points_per_unit,
            'min_points_per_frequency': min_points,
            'frequency': category.get('frequency', 'One-time'),
            'category_name': category.get('name'),
            'category_department': category_department,
            'is_pm_category': category_department.lower() == 'pm',
            'description': category.get('description', '')
        })
        
    except:
        return jsonify({'error': 'Unable to retrieve category details', 'success': False}), 500


@employee_raise_request_bp.route('/get-attachment/<request_id>')
def get_attachment(request_id):
    """Download attachment for a request"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    try:
        req = mongo.db.points_request.find_one({
            '_id': ObjectId(request_id),
            'user_id': ObjectId(user_id)
        })
        
        if not req or not req.get('has_attachment'):
            flash('Attachment not found', 'warning')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        attachment_id = req.get('attachment_id')
        if isinstance(attachment_id, str):
            attachment_id = ObjectId(attachment_id)
        
        fs = GridFS(mongo.db)
        if not fs.exists(attachment_id):
            flash('Attachment file not found in storage', 'warning')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        grid_out = fs.get(attachment_id)
        file_data = grid_out.read()
        
        file_stream = io.BytesIO(file_data)
        file_stream.seek(0)
        
        return send_file(
            file_stream,
            mimetype=grid_out.content_type or 'application/octet-stream',
            download_name=grid_out.metadata.get('original_filename', req.get('attachment_filename', 'attachment')),
            as_attachment=True
        )
        
    except:
        flash('Error downloading attachment', 'danger')
        return redirect(url_for('employee_raise_request.raise_request'))
