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
                    <h2>🎉 Bonus Eligibility Notification</h2>
                </div>
                <div class="content">
                    <p>Dear {{ name }},</p>
                    <p>
                        Congratulations! You are eligible for a <b>bonus</b> for <b>{{ quarter }}</b>.
                    </p>
                    <table class="info-table">
                    <tr>
                        <td>Role:</td>
                        <td>{{ role }}</td>
                    </tr>
                    <tr>
                        <td>Grade:</td>
                        <td>{{ grade }}</td>
                    </tr>
                    <tr>
                        <td>Department:</td>
                        <td>{{ department }}</td>
                    </tr>
                    <tr>
                        <td>Potential Bonus:</td>
                        <td>{{ potential_bonus }} points</td>
                    </tr>
                    {% if notes %}
                    <tr>
                        <td>Notes:</td>
                        <td><div style="max-height: 150px; overflow-y: auto; padding: 8px; background: #ffffff; border: 1px solid #ddd; border-radius: 4px; word-wrap: break-word; white-space: pre-wrap;">{{ notes }}</div></td>
                    </tr>
                    {% endif %}
                </table>

                    <p>Keep up the great work!</p>
                </div>
            </div>
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
