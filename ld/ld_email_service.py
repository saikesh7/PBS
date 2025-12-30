"""
L&D Email Notification Service - Professional format matching PMO design style.
Supports both new and old category IDs for backward compatibility with existing requests.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from flask import current_app
from utils.error_handling import error_print

# Large thread pool for maximum parallelism
email_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="ld_email")

def truncate_notes(notes, max_length=200):
    """Truncate notes to maximum length for email templates"""
    if not notes:
        return ''
    notes_str = str(notes).strip()
    if len(notes_str) > max_length:
        return notes_str[:max_length] + '...'
    return notes_str


def send_single_email(app, msg, to_email):
    """Send single email - fire and forget"""
    with app.app_context():
        server = None
        try:
            server = smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'], timeout=2)
            server.starttls()
            server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            server.send_message(msg)
        except Exception as e:
            pass
        finally:
            if server:
                try:
                    server.quit()
                except:
                    pass


def send_email(to_email, subject, html_body):
    """
    Queue email - INSTANT return (microseconds)
    Email sent in background by thread pool
    """
    if not to_email:
        return
    
    try:
        # Try to get app from current context, if not available, import it
        try:
            app = current_app._get_current_object()
        except RuntimeError:
            # We're outside of application context, import app directly
            from app import app as flask_app
            app = flask_app
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = app.config['MAIL_USERNAME']
        msg['To'] = to_email
        msg['Content-Type'] = 'text/html; charset=utf-8'
        
        html_part = MIMEText(html_body, 'html', _charset='utf-8')
        msg.attach(html_part)
        
        # Fire and forget - INSTANT
        email_executor.submit(send_single_email, app, msg, to_email)
        
    except Exception as e:
        error_print(f"Email queue error for {to_email}", e)


def send_single_request_to_validator(app, mongo, request_data, employee, validator, category, updater):
    """Send email to validator when updater raises a new L&D request"""
    validator_email = validator.get('email')
    if not validator_email:
        return
    
    validator_name = validator.get('name', 'Validator')
    employee_name = employee.get('name', 'Unknown')
    category_name = category.get('name', 'Unknown')
    points = request_data.get('points', 0)
    event_date = request_data.get('event_date', datetime.utcnow()).strftime('%d-%m-%Y')
    notes = truncate_notes(request_data.get('submission_notes', ''), max_length=200)
    display_notes = notes if notes else 'No notes provided'
    
    subject = f"New L&D Request - {employee_name}"
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New L&D Request for Validation</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">New L&D Request for Validation</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {validator_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">You have received a new L&D request that requires your validation:</p>
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
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Category:</td>
                                    <td style="color: #333; font-size: 14px;">{category_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Points:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{points}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Event Date:</td>
                                    <td style="color: #333; font-size: 14px;">{event_date}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Notes -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <h3 style="color: #333; margin: 0 0 10px 0; font-size: 16px; font-weight: bold;">Submission Notes:</h3>
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
                            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; background-color: #4CAF50; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">Go to Dashboard</a>
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
    
    send_email(validator_email, subject, html_body)


def send_bulk_upload_to_validator(app, mongo, requests_data, validator, updater):
    """Send bulk upload notification to validator"""
    validator_email = validator.get('email')
    if not validator_email:
        return
    
    validator_name = validator.get('name', 'Validator')
    updater_name = updater.get('name', 'Updater')
    request_count = len(requests_data)
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    subject = f"L&D Bulk Upload - {request_count} Requests Pending"
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L&D Bulk Upload Notification</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">L&D Bulk Upload Notification</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {validator_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">{updater_name} has submitted multiple L&D requests that require your validation:</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Total Requests:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{request_count} Requests</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Submitted By:</td>
                                    <td style="color: #333; font-size: 14px;">{updater_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Submission Date:</td>
                                    <td style="color: #333; font-size: 14px;">{current_time}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Action Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">Please log in to the system to review and process these requests.</p>
                        </td>
                    </tr>
                    
                    <!-- Button -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px; text-align: center;">
                            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; background-color: #4CAF50; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">Go to Dashboard</a>
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
    
    send_email(validator_email, subject, html_body)


def send_single_approval_emails(app, mongo, request_data, employee, validator, category, updater):
    """Send approval notification to employee and updater"""
    employee_email = employee.get('email')
    updater_email = updater.get('email') if updater else None
    
    employee_name = employee.get('name', 'Unknown')
    validator_name = validator.get('name', 'Validator')
    category_name = category.get('name', 'Unknown')
    points = request_data.get('points', 0)
    event_date = request_data.get('event_date', datetime.utcnow()).strftime('%d-%m-%Y')
    response_notes = truncate_notes(request_data.get('response_notes', ''), max_length=200)
    display_notes = response_notes if response_notes else ''
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    # Build notes row if validator notes exist
    notes_row = ""
    if display_notes:
        notes_row = f'''<tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Validator Notes:</td>
                                    <td style="color: #333; font-size: 14px;">{display_notes}</td>
                                </tr>'''
    
    # Email to employee
    if employee_email:
        subject = f"L&D Request Approved - {category_name}"
        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L&D Request Approved</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">L&D Request Approved</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {employee_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Congratulations! Your L&D request has been approved:</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Category:</td>
                                    <td style="color: #333; font-size: 14px;">{category_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Points Awarded:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{points}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Event Date:</td>
                                    <td style="color: #333; font-size: 14px;">{event_date}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Approval Date:</td>
                                    <td style="color: #333; font-size: 14px;">{current_time}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">The points have been credited to your account.</p>
                        </td>
                    </tr>
                    
                    <!-- Button -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px; text-align: center;">
                            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; background-color: #4CAF50; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">View Dashboard</a>
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
        send_email(employee_email, subject, html_body)
    
    # Email to updater
    if updater_email and updater:
        updater_name = updater.get('name', 'Updater')
        subject = f"L&D Request Approved - {employee_name}"
        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L&D Request Approved</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">L&D Request Approved</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {updater_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Your L&D request has been approved by the validator:</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Employee:</td>
                                    <td style="color: #333; font-size: 14px;">{employee_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Category:</td>
                                    <td style="color: #333; font-size: 14px;">{category_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Points:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{points}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Approved By:</td>
                                    <td style="color: #333; font-size: 14px;">{validator_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Approval Date:</td>
                                    <td style="color: #333; font-size: 14px;">{current_time}</td>
                                </tr>
                                {notes_row}
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">The points have been credited to the employee's account.</p>
                        </td>
                    </tr>
                    
                    <!-- Button -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px; text-align: center;">
                            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; background-color: #4CAF50; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">Go to Dashboard</a>
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
        send_email(updater_email, subject, html_body)


def send_single_rejection_email(app, mongo, request_data, employee, validator, category, updater):
    """Send rejection notification to updater only"""
    if not updater:
        return
    updater_email = updater.get('email')
    if not updater_email:
        return
    
    updater_name = updater.get('name', 'Updater')
    employee_name = employee.get('name', 'Unknown')
    validator_name = validator.get('name', 'Validator')
    category_name = category.get('name', 'Unknown')
    points = request_data.get('points', 0)
    rejection_notes = truncate_notes(request_data.get('response_notes', ''), max_length=200)
    display_rejection = rejection_notes if rejection_notes else 'No reason provided'
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    subject = f"L&D Request Rejected - {employee_name}"
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L&D Request Rejected</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #dc3545; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">L&D Request Rejected</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {updater_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Your L&D request has been rejected by the validator:</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Employee:</td>
                                    <td style="color: #333; font-size: 14px;">{employee_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Category:</td>
                                    <td style="color: #333; font-size: 14px;">{category_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Points:</td>
                                    <td style="color: #333; font-size: 14px;">{points}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Rejected By:</td>
                                    <td style="color: #333; font-size: 14px;">{validator_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Rejection Date:</td>
                                    <td style="color: #333; font-size: 14px;">{current_time}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Rejection Reason -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <h3 style="color: #333; margin: 0 0 10px 0; font-size: 16px; font-weight: bold;">Rejection Reason:</h3>
                            <div style="background-color: #fff; padding: 15px; border-left: 3px solid #dc3545; border: 1px solid #e0e0e0;">
                                <p style="color: #333; font-size: 14px; line-height: 1.6; margin: 0; white-space: pre-wrap;">{display_rejection}</p>
                            </div>
                        </td>
                    </tr>
                    
                    <!-- Action Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">Please review the rejection reason and take appropriate action if needed.</p>
                        </td>
                    </tr>
                    
                    <!-- Button -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px; text-align: center;">
                            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; background-color: #dc3545; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">Go to Dashboard</a>
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
    
    send_email(updater_email, subject, html_body)


def send_bulk_approval_emails(app, mongo, approved_requests_data, validator, updater):
    """Send bulk approval emails to updater"""
    if not updater:
        return
    
    updater_email = updater.get('email')
    if not updater_email:
        # Try to get email from different field names
        updater_email = updater.get('user_email') or updater.get('mail')
    
    if not updater_email:
        return
    
    updater_name = updater.get('name', 'Updater')
    validator_name = validator.get('name', 'Validator')
    approved_count = len(approved_requests_data)
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    subject = f"L&D Bulk Approval - {approved_count} Requests Approved"
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L&D Bulk Approval Notification</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">L&D Bulk Approval Notification</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {updater_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Your L&D requests have been approved by the validator:</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Total Requests Approved:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{approved_count} Requests</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Approved By:</td>
                                    <td style="color: #333; font-size: 14px;">{validator_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Approval Date:</td>
                                    <td style="color: #333; font-size: 14px;">{current_time}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">All points have been credited to the respective employees' accounts.</p>
                        </td>
                    </tr>
                    
                    <!-- Button -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px; text-align: center;">
                            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; background-color: #4CAF50; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">Go to Dashboard</a>
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
    
    send_email(updater_email, subject, html_body)


def send_bulk_rejection_email(app, mongo, rejected_requests_data, validator, updater, rejection_notes):
    """Send bulk rejection email to updater"""
    if not updater:
        return
    
    updater_email = updater.get('email')
    if not updater_email:
        # Try to get email from different field names
        updater_email = updater.get('user_email') or updater.get('mail')
    
    if not updater_email:
        return
    
    updater_name = updater.get('name', 'Updater')
    validator_name = validator.get('name', 'Validator')
    rejected_count = len(rejected_requests_data)
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    rejection_notes = truncate_notes(rejection_notes, max_length=200)
    display_notes = rejection_notes if rejection_notes else 'No reason provided'
    
    subject = f"L&D Bulk Rejection - {rejected_count} Requests Rejected"
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L&D Bulk Rejection Notification</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #dc3545; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">L&D Bulk Rejection Notification</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {updater_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Your L&D requests have been rejected by the validator:</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Total Requests Rejected:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{rejected_count} Requests</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Rejected By:</td>
                                    <td style="color: #333; font-size: 14px;">{validator_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Rejection Date:</td>
                                    <td style="color: #333; font-size: 14px;">{current_time}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Rejection Reason -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <h3 style="color: #333; margin: 0 0 10px 0; font-size: 16px; font-weight: bold;">Rejection Reason:</h3>
                            <div style="background-color: #fff; padding: 15px; border-left: 3px solid #dc3545; border: 1px solid #e0e0e0;">
                                <p style="color: #333; font-size: 14px; line-height: 1.6; margin: 0; white-space: pre-wrap;">{display_notes}</p>
                            </div>
                        </td>
                    </tr>
                    
                    <!-- Action Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">Please review the rejection reason and take appropriate action if needed.</p>
                        </td>
                    </tr>
                    
                    <!-- Button -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px; text-align: center;">
                            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; background-color: #dc3545; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">Go to Dashboard</a>
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
    
    send_email(updater_email, subject, html_body)


def send_approval_email_to_employee(employee_email, employee_name, category_name, points, event_date):
    """Send approval notification to employee - standalone function for bulk operations"""
    if not employee_email:
        return
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    subject = f"L&D Request Approved - {category_name}"
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L&D Request Approved</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">L&D Request Approved</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {employee_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Congratulations! Your L&D request has been approved:</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Category:</td>
                                    <td style="color: #333; font-size: 14px;">{category_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Points Awarded:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{points}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Event Date:</td>
                                    <td style="color: #333; font-size: 14px;">{event_date}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Approval Date:</td>
                                    <td style="color: #333; font-size: 14px;">{current_time}</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">The points have been credited to your account.</p>
                        </td>
                    </tr>
                    
                    <!-- Button -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px; text-align: center;">
                            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; background-color: #4CAF50; color: #ffffff; text-decoration: none; padding: 12px 30px; border-radius: 4px; font-size: 16px; font-weight: bold;">View Dashboard</a>
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
    
    send_email(employee_email, subject, html_body)
