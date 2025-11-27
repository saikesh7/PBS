"""
TA Email Notification Service
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
email_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="ta_email")


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
        msg.attach(MIMEText(html_body, 'html'))
        
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
                background: linear-gradient(135deg, #2c5aa0 0%, #1e3c72 100%);
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
                <div class="footer">
                    <p>This is an automated notification from Prowess Points System</p>
                    <p>Please do not reply to this email</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


def send_new_request_email(validator_email, validator_name, employee_name, category_name, points, event_date, notes):
    """Send email to validator when updater raises a new request - Professional format"""
    subject = f"New TA Reward Request - {employee_name}"
    
    content = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); border-radius: 12px 12px 0 0;">
        <tr>
            <td style="padding: 35px 30px; text-align: center;">
                <div style="display: inline-block; background: rgba(255,255,255,0.2); padding: 12px 20px; border-radius: 25px; margin-bottom: 15px;">
                    <span style="font-size: 28px;">🔔</span>
                </div>
                <h1 style="margin: 0; font-size: 24px; font-weight: 700; color: #ffffff; letter-spacing: -0.5px;">New TA Reward Request</h1>
                <p style="margin: 10px 0 0 0; font-size: 15px; color: #ffffff; opacity: 0.95;">Action required - Please review and validate</p>
            </td>
        </tr>
    </table>
    <div style="padding: 35px; background: #ffffff;">
        <p style="font-size: 16px; color: #1f2937; margin-bottom: 8px;">Hello <strong>{validator_name}</strong>,</p>
        <p style="font-size: 15px; color: #4b5563; line-height: 1.6; margin-bottom: 25px;">A new TA reward request has been submitted and requires your validation.</p>
        
        <div style="background: #f9fafb; border-left: 4px solid #3b82f6; padding: 25px; border-radius: 6px; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px; width: 140px;">Employee:</td>
                    <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 500;">{employee_name}</td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px;">Category:</td>
                    <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 500;">{category_name}</td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px;">Points:</td>
                    <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 500;">{points}</td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px;">Event Date:</td>
                    <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 500;">{event_date}</td>
                </tr>
                <tr>
                    <td style="padding: 10px 0; color: #6b7280; font-weight: 600; font-size: 14px; vertical-align: top;">Notes:</td>
                    <td style="padding: 10px 0; color: #1f2937; font-size: 15px; font-weight: 400;">{notes}</td>
                </tr>
            </table>
        </div>
        
        <p style="font-size: 15px; color: #4b5563; line-height: 1.6; margin-top: 25px;">Please review and take action on this request at your earliest convenience.</p>
        
        <p style="text-align: center; margin-top: 35px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Review Request</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(validator_email, subject, html_body)


def send_bulk_request_email(validator_email, validator_name, request_count, updater_name):
    """Send single email to validator for bulk requests - Professional format"""
    subject = f"TA Bulk Upload - {request_count} Requests Pending"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); border-radius: 12px 12px 0 0;">
        <tr>
            <td style="padding: 35px 30px; text-align: center;">
                <div style="display: inline-block; background: rgba(255,255,255,0.2); padding: 12px 20px; border-radius: 25px; margin-bottom: 15px;">
                    <span style="font-size: 28px;">📦</span>
                </div>
                <h1 style="margin: 0; font-size: 24px; font-weight: 700; color: #ffffff; letter-spacing: -0.5px;">TA Bulk Upload Notification</h1>
                <p style="margin: 10px 0 0 0; font-size: 15px; color: #ffffff; opacity: 0.95;">Multiple requests require your validation</p>
            </td>
        </tr>
    </table>
    <div style="padding: 35px; background: #ffffff;">
        <p style="font-size: 16px; color: #1f2937; margin-bottom: 8px;">Hello <strong>{validator_name}</strong>,</p>
        <p style="font-size: 15px; color: #4b5563; line-height: 1.6; margin-bottom: 25px;"><strong>{updater_name}</strong> has submitted multiple TA reward requests that require your validation.</p>
        
        <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Total Requests:</td>
                    <td style="padding: 16px 20px; color: #f59e0b; font-size: 20px; font-weight: 700;">{request_count} Requests</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Submitted By:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{updater_name}</td>
                </tr>
                <tr>
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Submission Date:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{current_time}</td>
                </tr>
            </table>
        </div>
        
        <p style="font-size: 15px; color: #4b5563; line-height: 1.6; margin-top: 25px;">Please review and take action on these requests at your earliest convenience.</p>
        
        <p style="text-align: center; margin-top: 35px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Review Requests</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(validator_email, subject, html_body)


def send_approval_email_to_updater(updater_email, updater_name, employee_name, category_name, points, validator_name, event_date=None):
    """Send approval notification to updater - Professional format with date and login"""
    subject = f"TA Request Approved - {employee_name}"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <div class="header" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%);">
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
                <tr>
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approval Date:</td>
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{current_time}</td>
                </tr>
            </table>
        </div>
        
        <p style="margin-top: 20px;">The points have been credited to the employee's account.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_rejection_email_to_updater(updater_email, updater_name, employee_name, category_name, validator_name, rejection_notes, points=0):
    """Send rejection notification to updater - Professional format"""
    subject = f"TA Request Rejected - {employee_name}"
    
    current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    content = f"""
    <div class="header" style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);">
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
                <tr>
                    <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb; vertical-align: top;">Rejection Reason:</td>
                    <td style="padding: 16px 20px; color: #dc2626; font-size: 15px; font-weight: 600;">{rejection_notes}</td>
                </tr>
            </table>
        </div>
        
        <p style="margin-top: 20px;">Please review the rejection reason and take appropriate action if needed.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Dashboard</a>
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
    <div class="header" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%);">
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
                    <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{notes}</td>
                </tr>''' if notes else ''}
            </table>
        </div>
        
        <p style="margin-top: 20px;">These points have been successfully credited to your account. Keep up the excellent work!</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Dashboard</a>
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
    <div class="header" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%);">
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
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Dashboard</a>
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
    <div class="header" style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);">
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
                    <td style="padding: 16px 20px; color: #dc2626; font-size: 15px; font-weight: 600;">{rejection_notes}</td>
                </tr>
            </table>
        </div>
        
        <p style="margin-top: 20px;">All {rejected_count} requests have been rejected. Please review the rejection reason and take appropriate action if needed.</p>
        
        <p style="text-align: center; margin-top: 30px;">
            <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Dashboard</a>
        </p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)
