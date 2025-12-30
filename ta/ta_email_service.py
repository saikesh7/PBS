"""
TA Email Notification Service
MAXIMUM SPEED - Just queue and forget, emails sent in background
Uses universal email templates compatible with all email clients
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from flask import current_app
from utils.error_handling import error_print

# Large thread pool for maximum parallelism
email_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="ta_email")

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
        error_print(f"TA Email queue error", e)


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


def send_new_request_email(validator_email, validator_name, employee_name, category_name, points, event_date, notes):
    """Send email to validator when updater raises a new request - Matches Employee Raise Request template"""
    notes = truncate_notes(notes, max_length=200)
    display_notes = notes if notes else 'No notes provided'
    subject = f"New TA Reward Request - {employee_name}"
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New TA Request for Validation</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">New TA Request for Validation</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {validator_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">You have received a new TA request that requires your validation:</p>
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


def send_bulk_request_email(validator_email, validator_name, request_count, updater_name):
    """Send single email to validator for bulk requests - Matches Employee Raise Request template"""
    subject = f"TA Bulk Upload - {request_count} Requests Pending"
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TA Bulk Upload Notification</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">TA Bulk Upload Notification</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {validator_name},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">{updater_name} has submitted multiple TA requests that require your validation:</p>
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


def send_approval_email_to_updater(updater_email, updater_name, employee_name, category_name, points, validator_name, event_date=None, submission_notes="", validator_notes=""):
    """Send approval notification to updater - Professional format with date and login"""
    subject = f"TA Request Approved - {employee_name}"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    # Build notes section - ONLY show validator notes for approval
    notes_section = ""
    if validator_notes:
        notes_section = f'''<tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb; vertical-align: top;">Validator Notes:</td>
                    <td style="padding: 16px 20px; color: #10b981; font-size: 15px; font-weight: 500;">
                        <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{validator_notes}</div>
                    </td>
                </tr>'''
    
    content = f"""
    <div class="header" style="background-color: #10b981;">
        <h1>TA Request Approved</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Request has been approved by validator</p>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Your TA reward request has been approved by the validator.</p>
        
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Employee:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{employee_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Category:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{category_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Points:</td>
                    <td style="padding: 16px 20px; color: #10b981; font-size: 18px; font-weight: 700;">{points}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approved By:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{validator_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approval Date:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{current_time}</td>
                </tr>
                {notes_section}
            </table>
        </div>
        
        <p style="margin-top: 20px;">The points have been credited to the employee's account.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_rejection_email_to_updater(updater_email, updater_name, employee_name, category_name, validator_name, rejection_notes, points=0, submission_notes=""):
    """Send rejection notification to updater - Professional format"""
    subject = f"TA Request Rejected - {employee_name}"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    # Build submission notes section if exists
    submission_notes_section = ""
    if submission_notes:
        submission_notes_section = f'''<tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb; vertical-align: top;">Your Notes:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">
                        <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{submission_notes}</div>
                    </td>
                </tr>'''
    
    content = f"""
    <div class="header" style="background-color: #ef4444;">
        <h1>TA Points Rejected</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Request has been rejected by validator</p>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Your TA reward request has been rejected by the validator. Please review the details below.</p>
        
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Employee:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{employee_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Category:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{category_name}</td>
                </tr>
                {f'''<tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Points:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{points}</td>
                </tr>''' if points > 0 else ''}
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Rejected By:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{validator_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Rejection Date:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{current_time}</td>
                </tr>
                {submission_notes_section}
                <tr>
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb; vertical-align: top;">Rejection Reason:</td>
                    <td style="padding: 16px 20px; color: #dc2626; font-size: 15px; font-weight: 600;">
                        <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{rejection_notes}</div>
                    </td>
                </tr>
            </table>
        </div>
        
        <p style="margin-top: 20px;">Please review the rejection reason and take appropriate action if needed.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_approval_email_to_employee(employee_email, employee_name, category_name, points, event_date, validator_name="TA Validator", notes=""):
    """Send approval notification to employee - Professional format"""
    subject = f"TA Points Approved - {points} Points Awarded"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <div class="header" style="background-color: #10b981;">
        <h1>TA Points Approved</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Congratulations! Your points have been approved</p>
    </div>
    <div class="content">
        <p>Hello <strong>{employee_name}</strong>,</p>
        <p>Great news! Your TA points request has been approved and the points have been credited to your account.</p>
        
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Category:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{category_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Points Awarded:</td>
                    <td style="padding: 16px 20px; color: #10b981; font-size: 18px; font-weight: 700;">{points}</td>
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
        
        <p style="margin-top: 20px;">These points have been successfully credited to your account. Keep up the excellent work!</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(employee_email, subject, html_body)


def send_bulk_approval_email_to_updater(updater_email, updater_name, approved_count, validator_name):
    """Send single email to updater for bulk approval - Professional format"""
    subject = f"TA Bulk Approval - {approved_count} Requests Approved"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <div class="header" style="background-color: #10b981;">
        <h1>TA Bulk Points Approved</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Multiple requests have been approved successfully</p>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Great news! Your bulk TA reward requests have been approved by the validator.</p>
        
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
    subject = f"TA Bulk Rejection - {rejected_count} Requests Rejected"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <div class="header" style="background-color: #ef4444;">
        <h1>TA Bulk Points Rejected</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Multiple requests have been rejected</p>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Your bulk TA reward requests have been rejected by the validator. Please review the details below.</p>
        
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





