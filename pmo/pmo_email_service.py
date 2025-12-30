"""
PMO Email Notification Service
MAXIMUM SPEED - Just queue and forget, emails sent in background
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from flask import current_app
from utils.error_handling import error_print

# Large thread pool for maximum parallelism
email_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="email")

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
        app = current_app._get_current_object()
        
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
        error_print(f"Email queue error", e)


def get_email_template_base():
    """Base HTML template for emails - Professional with attractive background"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                margin: 0;
                padding: 0;
                background: #f5f7fa;
            }}
            .email-wrapper {{
                background: #f5f7fa;
                padding: 40px 20px;
                min-height: 100vh;
            }}
            .container {{
                max-width: 650px;
                margin: 0 auto;
                background: white;
                border-radius: 16px;
                overflow: hidden;
                box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            }}
            .header {{
                background-color: #2c5aa0;
                color: white;
                padding: 30px;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                font-size: 24px;
            }}
            .content {{
                padding: 30px;
            }}
            .info-box {{
                background: #f8f9fa;
                border-left: 4px solid #2c5aa0;
                padding: 15px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .info-row {{
                margin: 10px 0;
            }}
            .label {{
                font-weight: bold;
                color: #555;
                display: inline-block;
                min-width: 120px;
            }}
            .value {{
                color: #333;
            }}
            .button {{
                display: inline-block;
                padding: 12px 30px;
                background: #2c5aa0;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                margin: 20px 0;
                font-weight: bold;
            }}
            .footer {{
                background: #f8f9fa;
                padding: 20px;
                text-align: center;
                font-size: 12px;
                color: #666;
                border-top: 1px solid #ddd;
            }}
            .success {{
                color: #28a745;
                font-weight: bold;
            }}
            .danger {{
                color: #dc3545;
                font-weight: bold;
            }}
            .warning {{
                color: #ffc107;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="email-wrapper">
            <div class="container">
                {content}
            </div>
        </div>
    </body>
    </html>
    """


def send_new_request_email(validator_email, validator_name, employee_name, category_name, points, event_date, notes, utilization_value=None):
    """Send email to validator when updater raises a new request - Matches Employee Raise Request template"""
    notes = truncate_notes(notes, max_length=200)
    display_notes = notes if notes else 'No notes provided'
    subject = f"New PMO Reward Request - {employee_name}"
    
    # Determine if this is utilization or points
    if utilization_value is not None:
        points_or_util_label = "Utilization:"
        points_or_util_value = f"{int(utilization_value * 100)}%"
    else:
        points_or_util_label = "Points:"
        points_or_util_value = points
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New PMO Request for Validation</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">New PMO Request for Validation</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {validator_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">You have received a new PMO request that requires your validation:</p>
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
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">{points_or_util_label}</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{points_or_util_value}</td>
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


def send_bulk_request_email(validator_email, validator_name, request_count, updater_name):
    """Send single email to validator for bulk requests - Matches Employee Raise Request template"""
    subject = f"PMO Bulk Upload - {request_count} Requests Pending"
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PMO Bulk Upload Notification</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">PMO Bulk Upload Notification</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {validator_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">{updater_name} has submitted multiple PMO requests that require your validation:</p>
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


def send_approval_email_to_updater(updater_email, updater_name, employee_name, category_name, points, validator_name, event_date=None, utilization_value=None, submission_notes="", validator_notes=""):
    """Send approval notification to updater - Matches Employee Raise Request template"""
    validator_notes = truncate_notes(validator_notes, max_length=200)
    display_notes = validator_notes if validator_notes else ''
    subject = f"Request Approved - {employee_name}"
    
    # Determine if this is utilization or points
    if utilization_value is not None:
        points_or_util_label = "Utilization:"
        points_or_util_value = f"{int(utilization_value * 100)}%"
        credit_message = "The utilization has been recorded in the employee's account."
    else:
        points_or_util_label = "Points:"
        points_or_util_value = points
        credit_message = "The points have been credited to the employee's account."
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    # Build notes row if validator notes exist
    notes_row = ""
    if display_notes:
        notes_row = f'''<tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Validator Notes:</td>
                                    <td style="color: #333; font-size: 14px;">{display_notes}</td>
                                </tr>'''
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PMO Request Approved</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">PMO Request Approved</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {updater_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Your PMO request has been approved by the validator:</p>
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
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">{points_or_util_label}</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{points_or_util_value}</td>
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
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">{credit_message}</p>
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


def send_rejection_email_to_updater(updater_email, updater_name, employee_name, category_name, validator_name, rejection_notes, points=0, submission_notes=""):
    """Send rejection notification to updater - Matches Employee Raise Request template"""
    rejection_notes = truncate_notes(rejection_notes, max_length=200)
    submission_notes = truncate_notes(submission_notes, max_length=200)
    display_rejection = rejection_notes if rejection_notes else 'No reason provided'
    subject = f"PMO Request Rejected - {employee_name}"
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    # Build submission notes row if exists
    submission_row = ""
    if submission_notes:
        submission_row = f'''<tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Your Notes:</td>
                                    <td style="color: #333; font-size: 14px;">{submission_notes}</td>
                                </tr>'''
    
    # Build points row if points > 0
    points_row = ""
    if points > 0:
        points_row = f'''<tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Points:</td>
                                    <td style="color: #333; font-size: 14px;">{points}</td>
                                </tr>'''
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PMO Request Rejected</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #dc3545; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">PMO Request Rejected</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {updater_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Your PMO request has been rejected by the validator:</p>
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
                                {points_row}
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Rejected By:</td>
                                    <td style="color: #333; font-size: 14px;">{validator_name}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Rejection Date:</td>
                                    <td style="color: #333; font-size: 14px;">{current_time}</td>
                                </tr>
                                {submission_row}
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


def send_approval_email_to_employee(employee_email, employee_name, category_name, points, event_date, validator_name="PMO Validator", notes="", utilization_value=None):
    """Send approval notification to employee - Professional format"""
    # Truncate notes to 100 characters
    notes = truncate_notes(notes)
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    # Determine if this is utilization or points
    if utilization_value is not None:
        subject = f"PMO Utilization Approved - {int(utilization_value * 100)}% Recorded"
        points_or_util_label = "Utilization:"
        points_or_util_value = f"{int(utilization_value * 100)}%"
        message = "Great news! Your utilization has been approved and recorded."
        credit_message = "This utilization has been successfully recorded in your account."
    else:
        subject = f"PMO Points Approved - {points} Points Awarded"
        points_or_util_label = "Points Awarded:"
        points_or_util_value = f"{points} Points"
        message = "Great news! Your PMO points request has been approved."
        credit_message = "These points have been successfully credited to your account."
    
    content = f"""
    <div class="header" style="background-color: #10b981;">
        <h1>PMO Points Approved</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Congratulations! Your points have been approved</p>
    </div>
    <div class="content">
        <p>Hello <strong>{employee_name}</strong>,</p>
        <p>{message}</p>
        
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Category:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{category_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">{points_or_util_label}</td>
                    <td style="padding: 16px 20px; color: #10b981; font-size: 18px; font-weight: 700;">{points_or_util_value}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approved By:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{validator_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approval Date:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{current_time}</td>
                </tr>
                {f'''<tr>
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb; vertical-align: top;">Notes:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">
                        <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{notes}</div>
                    </td>
                </tr>''' if notes else ''}
            </table>
        </div>
        
        <p style="margin-top: 20px;">{credit_message} Keep up the excellent work!</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(employee_email, subject, html_body)


def send_bulk_approval_email_to_updater(updater_email, updater_name, approved_count, validator_name):
    """Send single email to updater for bulk approval - Professional format"""
    subject = f"PMO Bulk Approval - {approved_count} Requests Approved"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <div class="header" style="background-color: #10b981;">
        <h1>PMO Bulk Points Approved</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Multiple requests have been approved successfully</p>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Great news! Your bulk PMO reward requests have been approved by the validator.</p>
        
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Total Requests Approved:</td>
                    <td style="padding: 16px 20px; color: #10b981; font-size: 20px; font-weight: 700;">{approved_count} Requests</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approved By:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{validator_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approval Date:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{current_time}</td>
                </tr>
                <tr>
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Status:</td>
                    <td style="padding: 16px 20px; color: #10b981; font-size: 15px; font-weight: 600;">All points have been credited to employee accounts</td>
                </tr>
            </table>
        </div>
        
        <p style="margin-top: 20px;">All {approved_count} requests have been successfully processed and points have been credited to the respective employee accounts.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_bulk_rejection_email_to_updater(updater_email, updater_name, rejected_count, validator_name, rejection_notes):
    """Send single email to updater for bulk rejection - Professional format"""
    subject = f"PMO Bulk Rejection - {rejected_count} Requests Rejected"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <div class="header" style="background-color: #ef4444;">
        <h1>PMO Bulk Points Rejected</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Multiple requests have been rejected</p>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Your bulk PMO reward requests have been rejected by the validator. Please review the details below.</p>
        
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Total Requests Rejected:</td>
                    <td style="padding: 16px 20px; color: #dc2626; font-size: 20px; font-weight: 700;">{rejected_count} Requests</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Rejected By:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{validator_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Rejection Date:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{current_time}</td>
                </tr>
                <tr>
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb; vertical-align: top;">Rejection Reason:</td>
                    <td style="padding: 16px 20px; color: #dc2626; font-size: 15px; font-weight: 600;">
                        <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{rejection_notes}</div>
                    </td>
                </tr>
            </table>
        </div>
        
        <p style="margin-top: 20px;">All {rejected_count} requests have been rejected. Please review the rejection reason and take appropriate action if needed.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)




