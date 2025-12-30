import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from jinja2 import Template
from .central_utils import debug_print, error_print

def truncate_notes(notes, max_length=200):
    """Truncate notes to maximum length for email templates"""
    if not notes:
        return ''
    notes_str = str(notes).strip()
    if len(notes_str) > max_length:
        return notes_str[:max_length] + '...'
    return notes_str

# Email configuration for Outlook - Direct credentials
EMAIL_CONFIG = {
    'SMTP_SERVER': 'smtp-mail.outlook.com',
    'SMTP_PORT': 587,
    'SMTP_USERNAME': 'pbs@prowesssoft.com',
    'SMTP_PASSWORD': 'thffnrhmbjnjlsjd',
    'FROM_EMAIL': 'pbs@prowesssoft.com',
    'FROM_NAME': 'Point Based System'
}

def send_email_notification(to_email, to_name, subject, html_content, text_content=None):
    """
    Send email notification using SMTP with UTF-8 charset for cross-platform compatibility
    """
    try:
        if not to_email:
            return False
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = formataddr((EMAIL_CONFIG['FROM_NAME'], EMAIL_CONFIG['FROM_EMAIL']))
        msg['To'] = formataddr((to_name, to_email))
        msg['Content-Type'] = 'text/html; charset=utf-8'
        
        # Create the plain-text and HTML version of your message
        if text_content:
            text_part = MIMEText(text_content, 'plain', _charset='utf-8')
            msg.attach(text_part)
        
        html_part = MIMEText(html_content, 'html', _charset='utf-8')
        msg.attach(html_part)
        
        # Send the message via SMTP server with timeout
        with smtplib.SMTP(EMAIL_CONFIG['SMTP_SERVER'], EMAIL_CONFIG['SMTP_PORT'], timeout=10) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['SMTP_USERNAME'], EMAIL_CONFIG['SMTP_PASSWORD'])
            server.send_message(msg)
            
        return True
        
    except Exception:
        return False

def get_email_template(template_name):
    """
    Get email template based on template name
    """
    templates = {
        'bonus_eligibility': '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bonus Eligibility Notification</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; max-width: 600px; border: 1px solid #e0e0e0;">
                    <!-- Header -->
                    <tr>
                        <td style="background-color: #4CAF50; padding: 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: bold;">🎉 Bonus Eligibility Notification</h1>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 30px 30px 20px 30px;">
                            <p style="color: #555; margin: 0; font-size: 16px; line-height: 1.5;">Dear {{ name }},</p>
                            <p style="color: #555; margin: 15px 0 0 0; font-size: 16px; line-height: 1.5;">Congratulations! You are eligible for a bonus for {{ quarter }}.</p>
                        </td>
                    </tr>
                    
                    <!-- Single Unified Table -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table width="100%" cellpadding="12" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; width: 40%; background-color: #f9f9f9;">Role:</td>
                                    <td style="color: #333; font-size: 14px;">{{ role }}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Grade:</td>
                                    <td style="color: #333; font-size: 14px;">{{ grade }}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Department:</td>
                                    <td style="color: #333; font-size: 14px;">{{ department }}</td>
                                </tr>
                                <tr style="border-bottom: 1px solid #ddd;">
                                    <td style="color: #555; font-size: 14px; font-weight: bold; background-color: #f9f9f9;">Potential Bonus:</td>
                                    <td style="color: #333; font-size: 14px; font-weight: bold;">{{ potential_bonus }} points</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    {% if notes %}
                    <!-- Notes -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <h3 style="color: #333; margin: 0 0 10px 0; font-size: 16px; font-weight: bold;">Notes:</h3>
                            <div style="background-color: #fff; padding: 15px; border-left: 3px solid #4CAF50; border: 1px solid #e0e0e0;">
                                <p style="color: #333; font-size: 14px; line-height: 1.6; margin: 0; white-space: pre-wrap;">{{ notes }}</p>
                            </div>
                        </td>
                    </tr>
                    {% endif %}
                    
                    <!-- Message -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <p style="color: #555; font-size: 14px; line-height: 1.5; margin: 0;">Keep up the great work!</p>
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
</html>
        '''
    }
    return templates.get(template_name, '')

def send_bonus_eligibility_email(emp_info, quarter, notes=''):
    """
    Send bonus eligibility notification email to the employee/manager.
    """
    # Truncate notes to 100 characters
    notes = truncate_notes(notes) or "No additional notes provided."
    subject = "Congratulations! You are eligible for a bonus"
    recipient = emp_info.get("email")
    name = emp_info.get("name", "")
    role = emp_info.get("role", "")
    grade = emp_info.get("grade", "")
    department = emp_info.get("department", "")
    potential_bonus = emp_info.get("potential_bonus", "")

    # Render HTML content using the template
    html_template = Template(get_email_template('bonus_eligibility'))
    html_content = html_template.render(
        name=name,
        quarter=quarter,
        role=role,
        grade=grade,
        department=department,
        potential_bonus=potential_bonus,
        notes=notes
    )

    # Plain text fallback
    text_content = f"""Dear {name},

Congratulations! You are eligible for a bonus for {quarter}.

Role: {role}
Grade: {grade}
Department: {department}
Potential Bonus: {potential_bonus} points
Notes: {notes}

Keep up the great work!
"""

    return send_email_notification(
        recipient,
        name,
        subject,
        html_content,
        text_content
    )
