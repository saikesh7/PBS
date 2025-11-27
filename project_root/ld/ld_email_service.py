"""
L&D Email Notification Service
MAXIMUM SPEED - Professional format matching PMO/TA/HR
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


def send_email_direct(app, to_email, subject, html_body):
    """Send email directly with app context - for use in background threads"""
    with app.app_context():
        server = None
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = app.config['MAIL_USERNAME']
            msg['To'] = to_email
            msg.attach(MIMEText(html_body, 'html'))
            
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


# ============================================================================
# UPDATER RAISES SINGLE REQUEST
# ============================================================================

def send_single_request_to_validator(app, mongo, request_data, employee, validator, category, updater):
    """
    Send email to validator when updater raises a single request - Professional format
    """
    try:
        event_date = request_data.get('event_date', request_data['request_date'])
        
        subject = f"New L&D Request - {employee.get('name')}"
        
        content = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f59e0b; border-radius: 12px 12px 0 0;">
            <tr>
                <td style="padding: 35px 30px; text-align: center;">
                    <div style="display: inline-block; background: rgba(255,255,255,0.2); padding: 12px 20px; border-radius: 25px; margin-bottom: 15px;">
                        <span style="font-size: 28px;"></span>
                    </div>
                    <h1 style="margin: 0; font-size: 24px; font-weight: 700; color: #ffffff; letter-spacing: -0.5px;">New L&D Request</h1>
                    <p style="margin: 10px 0 0 0; font-size: 15px; color: #ffffff; opacity: 0.95;">Action required - Please review and validate</p>
                </td>
            </tr>
        </table>
        <div style="padding: 35px; background: #ffffff;">
            <p style="font-size: 16px; color: #1f2937; margin-bottom: 8px;">Hello <strong>{validator.get('name')}</strong>,</p>
            <p style="font-size: 15px; color: #4b5563; line-height: 1.6; margin-bottom: 25px;">A new L&D points request has been submitted and requires your validation.</p>
            
            <div style="background: #f9fafb; border-left: 4px solid #3b82f6; padding: 25px; border-radius: 6px; margin: 25px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px; width: 140px;">Employee:</td>
                        <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 500;">{employee.get('name')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px;">Category:</td>
                        <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 500;">{category.get('name')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px;">Points:</td>
                        <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 500;">{request_data.get('points', 0)}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px;">Event Date:</td>
                        <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 500;">{event_date.strftime('%d-%m-%Y')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px; vertical-align: top;">Notes:</td>
                        <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 400;">
                            <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{request_data.get('submission_notes', 'No notes provided')}</div>
                        </td>
                    </tr>
                </table>
            </div>
            
            <p style="font-size: 15px; color: #4b5563; line-height: 1.6; margin-top: 25px;">Please review and take action on this request at your earliest convenience.</p>
        </div>
        
        <div style="padding: 35px; background: #ffffff; text-align: center; border-top: 1px solid #e5e7eb;">
            <p style="text-align: center; margin-top: 0;">
                <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Review Request</a>
            </p>
        </div>
        """
        
        html_body = get_email_template_base().format(content=content)
        send_email(validator.get('email'), subject, html_body)
        
    except Exception:
        pass


# ============================================================================
# UPDATER RAISES BULK UPLOAD
# ============================================================================

def send_bulk_upload_to_validator(app, mongo, requests_data, validator, updater):
    """
    Send single consolidated email to validator for bulk upload - Professional format
    Args:
        requests_data: List of request documents with employee and category info
    """
    try:
        total_requests = len(requests_data)
        total_points = sum(req['points'] for req in requests_data)
        current_date = datetime.utcnow().strftime('%d-%m-%Y')
        
        subject = f"L&D Bulk Upload - {total_requests} Requests Pending"
        
        content = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f59e0b; border-radius: 12px 12px 0 0;">
            <tr>
                <td style="padding: 35px 30px; text-align: center;">
                    <div style="display: inline-block; background: rgba(255,255,255,0.2); padding: 12px 20px; border-radius: 25px; margin-bottom: 15px;">
                        <span style="font-size: 28px;"></span>
                    </div>
                    <h1 style="margin: 0; font-size: 24px; font-weight: 700; color: #ffffff; letter-spacing: -0.5px;">L&D Bulk Upload Notification</h1>
                    <p style="margin: 10px 0 0 0; font-size: 15px; color: #ffffff; opacity: 0.95;">Multiple requests require your validation</p>
                </td>
            </tr>
        </table>
        <div style="padding: 35px; background: #ffffff;">
            <p style="font-size: 16px; color: #1f2937; margin-bottom: 8px;">Hello <strong>{validator.get('name')}</strong>,</p>
            <p style="font-size: 15px; color: #4b5563; line-height: 1.6; margin-bottom: 25px;"><strong>{updater.get('name')}</strong> has submitted multiple L&D points requests that require your validation.</p>
            
            <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr style="border-bottom: 1px solid #e5e7eb;">
                        <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Total Requests:</td>
                        <td style="padding: 16px 20px; color: #f59e0b; font-size: 20px; font-weight: 700;">{total_requests} Requests</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #e5e7eb;">
                        <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Submitted By:</td>
                        <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{updater.get('name')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Submission Date:</td>
                        <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{current_date}</td>
                    </tr>
                </table>
            </div>
            
            <p style="font-size: 15px; color: #4b5563; line-height: 1.6; margin-top: 25px;">Please review and take action on these requests at your earliest convenience.</p>
            
            <p style="text-align: center; margin-top: 35px;">
                <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Review Requests</a>
            </p>
        </div>
        """
        
        html_body = get_email_template_base().format(content=content)
        send_email(validator.get('email'), subject, html_body)
        
    except Exception:
        pass


# ============================================================================
# VALIDATOR APPROVES SINGLE REQUEST
# ============================================================================

def send_single_approval_emails(app, mongo, request_data, employee, validator, category, updater):
    """
    Send emails to both employee and updater when validator approves single request - Professional format
    """
    try:
        event_date = request_data.get('event_date', request_data['request_date'])
        current_date = datetime.utcnow().strftime('%d-%m-%Y')
        
        # 1. Email to Employee
        employee_subject = f"L&D Points Approved - {request_data.get('points', 0)} Points Awarded"
        
        employee_content = f"""
        <div class="header" style="background-color: #10b981;">
            <h1>L&D Points Approved</h1>
            <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Congratulations! Your points have been approved</p>
        </div>
        <div class="content">
            <p>Hello <strong>{employee.get('name')}</strong>,</p>
            <p>Great news! Your L&D points request has been approved.</p>
            
            <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background-color: #10b981; color: white;">
                            <th style="padding: 16px 20px; font-weight: 700; font-size: 13px; text-align: left; text-transform: uppercase; letter-spacing: 0.5px; width: 180px;">Details</th>
                            <th style="padding: 16px 20px; font-weight: 700; font-size: 13px; text-align: left; text-transform: uppercase; letter-spacing: 0.5px;">Information</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Category</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{category.get('name')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb; background: #f9fafb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Points Awarded</td>
                            <td style="padding: 16px 20px; color: #10b981; font-size: 16px; font-weight: 700;">{request_data.get('points', 0)} Points</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Approved By</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{validator.get('name')}</td>
                        </tr>
                        <tr style="background: #f9fafb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Approval Date</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{current_date}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <p style="margin-top: 20px;">These points have been successfully credited to your account. Keep up the excellent work!</p>
        </div>
        
        <div style="padding: 35px; background: #ffffff; text-align: center; border-top: 1px solid #e5e7eb;">
            <p style="text-align: center; margin-top: 0;">
                <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
            </p>
        </div>
        """
        
        employee_html = get_email_template_base().format(content=employee_content)
        send_email(employee.get('email'), employee_subject, employee_html)
        
        # 2. Email to Updater
        updater_subject = f"Request Approved - {employee.get('name')}"
        
        # Build notes section - ONLY show validator notes for approval
        validator_notes = truncate_notes(request_data.get('response_notes', ''))
        notes_section = ""
        if validator_notes:
            notes_section = f'''<tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px; vertical-align: top;">Validator Notes</td>
                            <td style="padding: 16px 20px; color: #10b981; font-size: 15px; font-weight: 500;">
                                <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{validator_notes}</div>
                            </td>
                        </tr>'''
        
        updater_content = f"""
        <div class="header" style="background-color: #10b981;">
            <h1>L&D Request Approved</h1>
            <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Request has been approved by validator</p>
        </div>
        <div class="content">
            <p>Hello <strong>{updater.get('name')}</strong>,</p>
            <p>Your L&D points request has been approved by the validator.</p>
            
            <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background-color: #10b981; color: white;">
                            <th style="padding: 16px 20px; font-weight: 700; font-size: 13px; text-align: left; text-transform: uppercase; letter-spacing: 0.5px; width: 180px;">Details</th>
                            <th style="padding: 16px 20px; font-weight: 700; font-size: 13px; text-align: left; text-transform: uppercase; letter-spacing: 0.5px;">Information</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Employee</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{employee.get('name')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb; background: #f9fafb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Category</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{category.get('name')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Points</td>
                            <td style="padding: 16px 20px; color: #10b981; font-size: 16px; font-weight: 700;">{request_data.get('points', 0)} Points</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb; background: #f9fafb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Approved By</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{validator.get('name')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Approval Date</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{current_date}</td>
                        </tr>
                        {notes_section}
                    </tbody>
                </table>
            </div>
            
            <p style="margin-top: 20px;">The points have been credited to the employee's account.</p>
        </div>
        
        <div style="padding: 35px; background: #ffffff; text-align: center; border-top: 1px solid #e5e7eb;">
            <p style="text-align: center; margin-top: 0;">
                <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
            </p>
        </div>
        """
        
        updater_html = get_email_template_base().format(content=updater_content)
        send_email(updater.get('email'), updater_subject, updater_html)
        
    except Exception:
        pass


# ============================================================================
# VALIDATOR REJECTS SINGLE REQUEST
# ============================================================================

def send_single_rejection_email(app, mongo, request_data, employee, validator, category, updater):
    """
    Send email ONLY to updater when validator rejects single request - Professional format
    (Employee does NOT receive rejection emails)
    """
    try:
        current_date = datetime.utcnow().strftime('%d-%m-%Y')
        
        subject = f"L&D Request Rejected - {employee.get('name')}"
        
        # Build submission notes section if exists
        submission_notes = (
            request_data.get("submission_notes") or 
            request_data.get("request_notes") or 
            request_data.get("notes") or 
            ""
        )
        submission_notes_section = ""
        if submission_notes:
            submission_notes_section = f'''<tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px; vertical-align: top;">Your Notes</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">
                                <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{submission_notes}</div>
                            </td>
                        </tr>'''
        
        content = f"""
        <div class="header" style="background-color: #ef4444;">
            <h1>L&D Request Rejected</h1>
            <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Request has been rejected by validator</p>
        </div>
        <div class="content">
            <p>Hello <strong>{updater.get('name')}</strong>,</p>
            <p>Your L&D points request has been rejected by the validator. Please review the details below.</p>
            
            <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background-color: #ef4444; color: white;">
                            <th style="padding: 16px 20px; font-weight: 700; font-size: 13px; text-align: left; text-transform: uppercase; letter-spacing: 0.5px; width: 180px;">Details</th>
                            <th style="padding: 16px 20px; font-weight: 700; font-size: 13px; text-align: left; text-transform: uppercase; letter-spacing: 0.5px;">Information</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Employee</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{employee.get('name')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb; background: #f9fafb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Category</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{category.get('name')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Points</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{request_data.get('points', 0)}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb; background: #f9fafb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Rejected By</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{validator.get('name')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px;">Rejection Date</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px; font-weight: 500;">{current_date}</td>
                        </tr>
                        {submission_notes_section}
                        <tr style="background: #f9fafb;">
                            <td style="padding: 16px 20px; color: #6b7280; font-weight: 600; font-size: 14px; vertical-align: top;">Rejection Reason</td>
                            <td style="padding: 16px 20px; color: #dc2626; font-size: 15px; font-weight: 600;">
                                <div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{request_data.get('response_notes', 'No reason provided')}</div>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <p style="margin-top: 20px;">Please review the rejection reason and take appropriate action if needed.</p>
        </div>
        
        <div style="padding: 35px; background: #ffffff; text-align: center; border-top: 1px solid #e5e7eb;">
            <p style="text-align: center; margin-top: 0;">
                <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
            </p>
        </div>
        """
        
        html_body = get_email_template_base().format(content=content)
        send_email(updater.get('email'), subject, html_body)
        
    except Exception:
        pass


# ============================================================================
# VALIDATOR BULK APPROVES
# ============================================================================

def send_bulk_approval_email_to_updater(updater_email, updater_name, approved_count, validator_name):
    """Send single email to updater for bulk approval - Professional format"""
    subject = f"L&D Bulk Approval - {approved_count} Requests Approved"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <div class="header" style="background-color: #10b981;">
        <h1>L&D Bulk Points Approved</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Multiple requests have been approved successfully</p>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Great news! Your bulk L&D points requests have been approved by the validator.</p>
        
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
                    <td style="padding: 16px 20px; color: #10b981; font-size: 15px; font-weight: 700;">✓ Approved</td>
                </tr>
            </table>
        </div>
        
        <p style="margin-top: 20px;">All employees have been notified individually about their approved requests and points have been credited to their accounts.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_bulk_approval_emails(app, mongo, approved_requests, validator, updater):
    """
    Send:
    1. Single consolidated email to updater
    2. Individual emails to each employee (sent concurrently)
    
    Args:
        approved_requests: List of dicts with request_data, employee, category
    """
    try:
        with app.app_context():
            total_approved = len(approved_requests)
            
            # 1. Send consolidated email to updater
            send_bulk_approval_email_to_updater(
                updater.get('email'),
                updater.get('name'),
                total_approved,
                validator.get('name')
            )
            
            # 2. Individual emails to each employee
            for req in approved_requests:
                emp = req['employee']
                cat = req['category']
                req_data = req['request_data']
                event_date = req_data.get('event_date', req_data['request_date'])
                
                emp_subject = f"L&D Points Approved - {cat.get('name')}"
                emp_body = f"""
Dear {emp.get('name')},

Congratulations! Your L&D points request has been approved.

APPROVED REQUEST:
-----------------
Category: {cat.get('name')}
Quantity: {req_data.get('quantity', 1)}
Points Awarded: {req_data.get('points', 0)}
Event Date: {event_date.strftime('%d-%m-%Y')}

Approved By: {validator.get('name')}
Approval Date: {datetime.utcnow().strftime('%d-%m-%Y')}

These points have been added to your account.

Best regards,
Prowess Points System
"""
                
                # Convert plain text to HTML
                html_content = f"<pre>{emp_body}</pre>"
                send_email_direct(app, emp.get('email'), emp_subject, html_content)
        
    except Exception:
        pass


# ============================================================================
# VALIDATOR BULK REJECTS
# ============================================================================

def send_bulk_rejection_email_to_updater(updater_email, updater_name, rejected_count, validator_name, rejection_notes):
    """Send single email to updater for bulk rejection - Professional format"""
    subject = f"L&D Bulk Rejection - {rejected_count} Requests Rejected"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    rejection_notes = truncate_notes(rejection_notes, max_length=500)
    
    content = f"""
    <div class="header" style="background-color: #ef4444;">
        <h1>L&D Bulk Points Rejected</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.95;">Multiple requests have been rejected</p>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Your bulk L&D points requests have been rejected by the validator. Please review the details below.</p>
        
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Total Requests Rejected:</td>
                    <td style="padding: 16px 20px; color: #ef4444; font-size: 20px; font-weight: 700;">{rejected_count} Requests</td>
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
        
        <p style="margin-top: 20px;">Please review the rejection reason and take appropriate action if needed.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 14px 36px; background-color: #667eea !important; color: white !important; text-decoration: none; border-radius: 6px; font-weight: 700; font-size: 15px; border: 2px solid #667eea; mso-padding-alt: 14px 36px; mso-border-alt: 2px solid #667eea;">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_bulk_rejection_email(app, mongo, rejected_requests, validator, updater, rejection_notes):
    """
    Send single consolidated email ONLY to updater for bulk rejection
    (Employees do NOT receive rejection emails)
    
    Args:
        rejected_requests: List of dicts with request_data, employee, category
    """
    try:
        with app.app_context():
            total_rejected = len(rejected_requests)
            
            # Send consolidated email to updater
            send_bulk_rejection_email_to_updater(
                updater.get('email'),
                updater.get('name'),
                total_rejected,
                validator.get('name'),
                rejection_notes
            )
        
    except Exception:
        pass


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_employee_and_category(mongo, request_data):
    """Helper to fetch employee and category from request data"""
    employee = mongo.db.users.find_one({"_id": request_data["user_id"]})
    category = mongo.db.hr_categories.find_one({"_id": request_data["category_id"]})
    return employee, category


def shutdown_email_executor():
    """Gracefully shutdown the email thread pool"""
    email_executor.shutdown(wait=True)






