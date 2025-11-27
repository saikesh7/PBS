"""
PM/Arch Notifications Module
Email notifications for PM/Arch requests (approval, rejection, new requests)
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime
from jinja2 import Template

# Email configuration
EMAIL_CONFIG = {
    'SMTP_SERVER': 'smtp-mail.outlook.com',
    'SMTP_PORT': 587,
    'SMTP_USERNAME': 'pbs@prowesssoft.com',
    'SMTP_PASSWORD': 'thffnrhmbjnjlsjd',
    'FROM_EMAIL': 'pbs@prowesssoft.com',
    'FROM_NAME': 'Point Based System'
}

def send_email_notification(to_email, to_name, subject, html_content, text_content=None):
    """Send email notification using SMTP with timeout"""
    try:
        if not to_email:
            return False
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = formataddr((EMAIL_CONFIG['FROM_NAME'], EMAIL_CONFIG['FROM_EMAIL']))
        msg['To'] = formataddr((to_name, to_email))
        
        if text_content:
            msg.attach(MIMEText(text_content, 'plain'))
        
        msg.attach(MIMEText(html_content, 'html'))
        
        # Send with timeout to prevent blocking
        with smtplib.SMTP(EMAIL_CONFIG['SMTP_SERVER'], EMAIL_CONFIG['SMTP_PORT'], timeout=10) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['SMTP_USERNAME'], EMAIL_CONFIG['SMTP_PASSWORD'])
            server.send_message(msg)
            
        return True
        
    except Exception as e:
        return False

def send_approval_notification(request_data, employee, validator, category):
    """Send approval notification email to employee"""
    try:
        # Validate inputs
        if not employee or not employee.get('email'):
            return False
        
        if not category:
            return False
        
        current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
        
        html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
            .container { max-width: 600px; margin: 0 auto; padding: 20px; }
            .header { background-color: #28a745; color: white; padding: 30px 20px; text-align: center; border-radius: 12px 12px 0 0; }
            .content { background-color: #f9f9f9; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 12px 12px; }
            .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
            .header h2 { margin: 0; font-size: 28px; font-weight: 700; }
            .header p { margin: 10px 0 0 0; font-size: 15px; opacity: 0.95; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>PM/Arch Points Approved</h2>
                <p>Request has been approved by validator</p>
            </div>
            <div class="content">
                <p>Hello <strong>{{ employee_name }}</strong>,</p>
                <p>Great news! Your PM/Arch points request has been approved and the points have been credited to your account.</p>
                
                <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Category:</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{{ category_name }}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Points Awarded:</td>
                            <td style="padding: 16px 20px; color: #10b981; font-size: 18px; font-weight: 700;">{{ points }}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approved By:</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{{ validator_name }}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Approval Date:</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{{ decision_date }}</td>
                        </tr>
                        {% if response_notes %}
                        <tr>
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb; vertical-align: top;">Notes:</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{{ response_notes }}</td>
                        </tr>
                        {% endif %}
                    </table>
                </div>
                
                <p style="margin-top: 20px;">These points have been successfully credited to your account. Keep up the excellent work!</p>
                
                <p style="text-align: center; margin-top: 30px;">
                    <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Dashboard</a>
                </p>
            </div>
            <div class="footer">
                <p>This is an automated notification from the Prowess Points System.</p>
            </div>
        </div>
    </body>
    </html>
        """
        
        template_vars = {
            'employee_name': employee.get('name', 'Employee'),
            'category_name': category.get('name', 'Category'),
            'points': request_data.get('points', 0),
            'validator_name': validator.get('name', 'Validator'),
            'decision_date': current_time,
            'response_notes': request_data.get('response_notes', '')
        }
        
        html_template_obj = Template(html_template)
        html_content = html_template_obj.render(**template_vars)
        
        text_content = f"""
Dear {template_vars['employee_name']},

Your PM/Arch points request for '{template_vars['category_name']}' has been approved.

Points Awarded: {template_vars['points']}
Approved By: {template_vars['validator_name']}
Approval Date: {template_vars['decision_date']}

{f"Note: {template_vars['response_notes']}" if template_vars['response_notes'] else ''}

Congratulations!
"""
        
        result = send_email_notification(
            employee.get('email'),
            employee.get('name'),
            "PM/Arch Points Request Approved",
            html_content,
            text_content
        )
        return result
    except Exception as e:
        return False

def send_rejection_notification(request_data, employee, validator, category):
    """Send rejection notification email to employee"""
    try:
        # Validate inputs
        if not employee or not employee.get('email'):
            return False
        
        if not category:
            return False
        
        current_time = datetime.now().strftime('%d-%m-%Y %H:%M')
        
        html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
            .container { max-width: 600px; margin: 0 auto; padding: 20px; }
            .header { background-color: #dc3545; color: white; padding: 30px 20px; text-align: center; border-radius: 12px 12px 0 0; }
            .content { background-color: #f9f9f9; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 12px 12px; }
            .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
            .header h2 { margin: 0; font-size: 28px; font-weight: 700; }
            .header p { margin: 10px 0 0 0; font-size: 15px; opacity: 0.95; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>PM/Arch Points Rejected</h2>
                <p>Request has been rejected by validator</p>
            </div>
            <div class="content">
                <p>Hello <strong>{{ employee_name }}</strong>,</p>
                <p>Your PM/Arch points request has been rejected by the validator. Please review the details below.</p>
                
                <div style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; margin: 25px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; width: 200px; background: #f9fafb;">Category:</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{{ category_name }}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Points Requested:</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{{ points }}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Rejected By:</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{{ validator_name }}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb;">Rejection Date:</td>
                            <td style="padding: 16px 20px; color: #1f2937; font-size: 15px;">{{ decision_date }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 16px 20px; color: #1f2937; font-weight: 600; font-size: 15px; background: #f9fafb; vertical-align: top;">Rejection Reason:</td>
                            <td style="padding: 16px 20px; color: #dc2626; font-size: 15px; font-weight: 600;">{{ response_notes }}</td>
                        </tr>
                    </table>
                </div>
                
                <p style="margin-top: 20px;">Please review the rejection reason and take appropriate action if needed.</p>
                
                <p style="text-align: center; margin-top: 30px;">
                    <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Dashboard</a>
                </p>
            </div>
            <div class="footer">
                <p>This is an automated notification from the Prowess Points System.</p>
            </div>
        </div>
    </body>
    </html>
        """
        
        template_vars = {
            'employee_name': employee.get('name', 'Employee'),
            'category_name': category.get('name', 'Category'),
            'points': request_data.get('points', 0),
            'validator_name': validator.get('name', 'Validator'),
            'decision_date': current_time,
            'response_notes': request_data.get('response_notes', '')
        }
        
        html_template_obj = Template(html_template)
        html_content = html_template_obj.render(**template_vars)
        
        text_content = f"""
Dear {template_vars['employee_name']},

Your PM/Arch points request for '{template_vars['category_name']}' has been rejected.

Points Requested: {template_vars['points']}
Rejected By: {template_vars['validator_name']}
Rejection Date: {template_vars['decision_date']}

{f"Reason: {template_vars['response_notes']}" if template_vars['response_notes'] else ''}

You may contact your manager if you need further clarification.
"""
        
        result = send_email_notification(
            employee.get('email'),
            employee.get('name'),
            "PM/Arch Points Request Rejected",
            html_content,
            text_content
        )
        return result
    except Exception as e:
        return False

def send_new_request_notification(request_data, employee, validator, category):
    """Send notification to validator about new PM/Arch request"""
    try:
        # Validate inputs
        if not validator or not validator.get('email'):
            return False
        
        if not employee:
            return False
        
        if not category:
            return False
        
        submission_date = datetime.now().strftime('%B %d, %Y at %I:%M %p')
        
        html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
            .container { max-width: 600px; margin: 0 auto; padding: 20px; }
            .header { background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
            .content { background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }
            .button { display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; }
            .footer { text-align: center; padding: 20px; color: #666; font-size: 12px; }
            .info-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            .info-table td { padding: 8px; border-bottom: 1px solid #ddd; }
            .info-table td:first-child { font-weight: bold; width: 40%; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>New PM/Arch Points Request for Validation</h2>
            </div>
            <div class="content">
                <p>Dear {{ validator_name }},</p>
                <p>You have received a new PM/Arch points request that requires your validation:</p>
                <table class="info-table">
                    <tr>
                        <td>Employee Name:</td>
                        <td>{{ employee_name }}</td>
                    </tr>
                    <tr>
                        <td>Employee Grade:</td>
                        <td>{{ employee_grade }}</td>
                    </tr>
                    <tr>
                        <td>Department:</td>
                        <td>{{ employee_department }}</td>
                    </tr>
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
                    {% if has_attachment %}
                    <tr>
                        <td>Attachment:</td>
                        <td>Yes ({{ attachment_filename }})</td>
                    </tr>
                    {% endif %}
                </table>
                {% if notes %}
                <h3>Employee's Notes:</h3>
                <p style="background-color: #fff; padding: 10px; border-left: 3px solid #4CAF50;">
                    {{ notes }}
                </p>
                {% endif %}
                <p>Please log in to the system to review and process this request.</p>
                <p style="text-align: center; margin-top: 25px;">
                    <a href="https://pbs.prowesssoft.com/auth/login" style="display: inline-block; padding: 16px 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);">Login to Review Request</a>
                </p>
            </div>
            <div class="footer">
                <p>This is an automated notification from the Prowess Points System.</p>
                <p>Please do not reply to this email.</p>
            </div>
        </div>
    </body>
    </html>
        """
        
        template_vars = {
            'validator_name': validator.get('name', 'Validator'),
            'employee_name': employee.get('name', 'Employee'),
            'employee_grade': employee.get('grade', 'Unknown'),
            'employee_department': employee.get('department', 'Unknown'),
            'category_name': category.get('name', 'Unknown Category'),
            'points': request_data.get('points', 0),
            'submission_date': submission_date,
            'has_attachment': request_data.get('has_attachment', False),
            'attachment_filename': request_data.get('attachment_filename', ''),
            'notes': request_data.get('request_notes', '')
        }
        
        html_template_obj = Template(html_template)
        html_content = html_template_obj.render(**template_vars)
        
        return send_email_notification(
            validator.get('email'),
            validator.get('name'),
            f"New PM/Arch Points Request from {employee.get('name')}",
            html_content
        )
    except Exception as e:
        return False
