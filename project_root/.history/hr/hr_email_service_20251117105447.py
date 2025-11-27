"""
HR Email Notification Service
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


def send_single_email(app, msg, to_email):
    """Send single email - fire and forget"""
    with app.app_context():
        server = None
        try:
            server = smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'], timeout=2)
            server.starttls()
            server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            server.send_message(msg)
            print(f"✅ {to_email}")
        except Exception as e:
            print(f"❌ {to_email}")
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
        error_print(f"Email queue error", e)


def get_email_template_base():
    """Base HTML template for emails"""
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
                background-color: #f4f4f4;
            }}
            .container {{
                max-width: 600px;
                margin: 20px auto;
                background: white;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
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
        <div class="container">
            {content}
            <div class="footer">
                <p>This is an automated notification from Prowess Points System</p>
                <p>Please do not reply to this email</p>
            </div>
        </div>
    </body>
    </html>
    """


def send_new_request_email(validator_email, validator_name, employee_name, category_name, points, event_date, notes):
    """Send email to validator when updater raises a new request"""
    subject = f"New Reward Request - {employee_name}"
    
    content = f"""
    <div class="header">
        <h1>🔔 New Reward Request</h1>
    </div>
    <div class="content">
        <p>Hello <strong>{validator_name}</strong>,</p>
        <p>A new reward request has been submitted and requires your validation.</p>
        
        <div class="info-box">
            <div class="info-row">
                <span class="label">Employee:</span>
                <span class="value">{employee_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Category:</span>
                <span class="value">{category_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Points:</span>
                <span class="value">{points}</span>
            </div>
            <div class="info-row">
                <span class="label">Event Date:</span>
                <span class="value">{event_date}</span>
            </div>
            <div class="info-row">
                <span class="label">Notes:</span>
                <span class="value">{notes}</span>
            </div>
        </div>
        
        <p>Please review and take action on this request at your earliest convenience.</p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(validator_email, subject, html_body)


def send_bulk_request_email(validator_email, validator_name, request_count, updater_name):
    """Send single email to validator for bulk requests"""
    subject = f"Bulk Reward Requests - {request_count} Requests Pending"
    
    content = f"""
    <div class="header">
        <h1>📦 Bulk Reward Requests</h1>
    </div>
    <div class="content">
        <p>Hello <strong>{validator_name}</strong>,</p>
        <p><strong>{updater_name}</strong> has submitted <strong class="warning">{request_count} reward requests</strong> that require your validation.</p>
        
        <div class="info-box">
            <div class="info-row">
                <span class="label">Total Requests:</span>
                <span class="value">{request_count}</span>
            </div>
            <div class="info-row">
                <span class="label">Submitted By:</span>
                <span class="value">{updater_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Date:</span>
                <span class="value">{datetime.now().strftime('%d-%m-%Y %H:%M')}</span>
            </div>
        </div>
        
        <p>Please review and take action on these requests at your earliest convenience.</p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(validator_email, subject, html_body)


def send_approval_email_to_updater(updater_email, updater_name, employee_name, category_name, points, validator_name):
    """Send approval notification to updater"""
    subject = f"Request Approved - {employee_name}"
    
    content = f"""
    <div class="header" style="background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%);">
        <h1>✅ Request Approved</h1>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Your reward request has been <span class="success">APPROVED</span> by the validator.</p>
        
        <div class="info-box" style="border-left-color: #28a745;">
            <div class="info-row">
                <span class="label">Employee:</span>
                <span class="value">{employee_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Category:</span>
                <span class="value">{category_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Points:</span>
                <span class="value">{points}</span>
            </div>
            <div class="info-row">
                <span class="label">Approved By:</span>
                <span class="value">{validator_name}</span>
            </div>
        </div>
        
        <p>The points have been credited to the employee's account.</p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_rejection_email_to_updater(updater_email, updater_name, employee_name, category_name, validator_name, rejection_notes):
    """Send rejection notification to updater"""
    subject = f"Request Rejected - {employee_name}"
    
    content = f"""
    <div class="header" style="background: linear-gradient(135deg, #dc3545 0%, #bd2130 100%);">
        <h1>❌ Request Rejected</h1>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p>Your reward request has been <span class="danger">REJECTED</span> by the validator.</p>
        
        <div class="info-box" style="border-left-color: #dc3545;">
            <div class="info-row">
                <span class="label">Employee:</span>
                <span class="value">{employee_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Category:</span>
                <span class="value">{category_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Rejected By:</span>
                <span class="value">{validator_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Reason:</span>
                <span class="value">{rejection_notes}</span>
            </div>
        </div>
        
        <p>Please review the rejection reason and take appropriate action.</p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_approval_email_to_employee(employee_email, employee_name, category_name, points, event_date):
    """Send approval notification to employee"""
    subject = f"Reward Approved - {points} Points Credited"
    
    content = f"""
    <div class="header" style="background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%);">
        <h1>🎉 Congratulations!</h1>
    </div>
    <div class="content">
        <p>Hello <strong>{employee_name}</strong>,</p>
        <p>Great news! You have been awarded points for your outstanding performance.</p>
        
        <div class="info-box" style="border-left-color: #28a745;">
            <div class="info-row">
                <span class="label">Category:</span>
                <span class="value">{category_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Points Awarded:</span>
                <span class="value success">{points} Points</span>
            </div>
            <div class="info-row">
                <span class="label">Event Date:</span>
                <span class="value">{event_date}</span>
            </div>
        </div>
        
        <p>These points have been credited to your account and can be redeemed for rewards.</p>
        <p>Keep up the excellent work!</p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(employee_email, subject, html_body)


def send_bulk_approval_email_to_updater(updater_email, updater_name, approved_count, validator_name):
    """Send single email to updater for bulk approval"""
    subject = f"Bulk Requests Approved - {approved_count} Requests"
    
    content = f"""
    <div class="header" style="background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%);">
        <h1>✅ Bulk Approval Completed</h1>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p><strong class="success">{approved_count} reward requests</strong> have been approved by the validator.</p>
        
        <div class="info-box" style="border-left-color: #28a745;">
            <div class="info-row">
                <span class="label">Approved Requests:</span>
                <span class="value success">{approved_count}</span>
            </div>
            <div class="info-row">
                <span class="label">Approved By:</span>
                <span class="value">{validator_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Date:</span>
                <span class="value">{datetime.now().strftime('%d-%m-%Y %H:%M')}</span>
            </div>
        </div>
        
        <p>All points have been credited to the respective employee accounts.</p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)


def send_bulk_rejection_email_to_updater(updater_email, updater_name, rejected_count, validator_name, rejection_notes):
    """Send single email to updater for bulk rejection"""
    subject = f"Bulk Requests Rejected - {rejected_count} Requests"
    
    content = f"""
    <div class="header" style="background: linear-gradient(135deg, #dc3545 0%, #bd2130 100%);">
        <h1>❌ Bulk Rejection Completed</h1>
    </div>
    <div class="content">
        <p>Hello <strong>{updater_name}</strong>,</p>
        <p><strong class="danger">{rejected_count} reward requests</strong> have been rejected by the validator.</p>
        
        <div class="info-box" style="border-left-color: #dc3545;">
            <div class="info-row">
                <span class="label">Rejected Requests:</span>
                <span class="value danger">{rejected_count}</span>
            </div>
            <div class="info-row">
                <span class="label">Rejected By:</span>
                <span class="value">{validator_name}</span>
            </div>
            <div class="info-row">
                <span class="label">Reason:</span>
                <span class="value">{rejection_notes}</span>
            </div>
            <div class="info-row">
                <span class="label">Date:</span>
                <span class="value">{datetime.now().strftime('%d-%m-%Y %H:%M')}</span>
            </div>
        </div>
        
        <p>Please review the rejection reason and take appropriate action.</p>
    </div>
    """
    
    html_body = get_email_template_base().format(content=content)
    send_email(updater_email, subject, html_body)
