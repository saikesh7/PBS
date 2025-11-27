from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import logging
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))

hr_rr_review_bp = Blueprint('hr_rr_review', __name__, url_prefix='/hr',
                            template_folder=os.path.join(current_dir, 'templates'),
                            static_folder=os.path.join(current_dir, 'static'),
                            static_url_path='/hr/static')


# ============================================================================
# EMAIL CONFIGURATION AND NOTIFICATION FUNCTIONS
# ============================================================================

EMAIL_CONFIG = {
    'SMTP_SERVER': 'smtp-mail.outlook.com',
    'SMTP_PORT': 587,
    'SMTP_USERNAME': 'pbs@prowesssoft.com',
    'SMTP_PASSWORD': 'thffnrhmbjnjlsjd',
    'FROM_EMAIL': 'pbs@prowesssoft.com',
    'FROM_NAME': 'Point Based System'
}


def send_email_notification(to_email, to_name, subject, html_content, text_content=None):
    """Send email notification using SMTP."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = formataddr((EMAIL_CONFIG['FROM_NAME'], EMAIL_CONFIG['FROM_EMAIL']))
        msg['To'] = formataddr((to_name, to_email))

        if text_content:
            msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))

        with smtplib.SMTP(EMAIL_CONFIG['SMTP_SERVER'], EMAIL_CONFIG['SMTP_PORT']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['SMTP_USERNAME'], EMAIL_CONFIG['SMTP_PASSWORD'])
            server.send_message(msg)
        return True
    except Exception:
        return False


def send_r_and_r_approval_notification_to_updater(approved_requests):
    """Sends approval notification to the PMO user (updater) for R&R requests"""
    if not approved_requests:
        return
    
    grouped_by_updater = {}
    for req in approved_requests:
        updater_email = req['updater_email']
        if updater_email not in grouped_by_updater:
            grouped_by_updater[updater_email] = {
                'updater_name': req['updater_name'],
                'processor_name': req['processor_name'],
                'requests': []
            }
        grouped_by_updater[updater_email]['requests'].append(req)
    
    for updater_email, data in grouped_by_updater.items():
        if not updater_email:
            continue
            
        subject = f"R&R Requests Approved: {len(data['requests'])} Request(s)"
        
        request_rows = ""
        total_points = 0
        for req in data['requests']:
            request_rows += f"""
            <tr>
                <td>{req['employee_name']} ({req['employee_id_code']})</td>
                <td>{req['points']}</td>
                <td>{req['category_name']}</td>
                <td>{req['request_notes']}</td>
            </tr>
            """
            total_points += req['points']
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
                .info-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                .info-table th, .info-table td {{ padding: 8px; border: 1px solid #ddd; text-align: left; }}
                .info-table th {{ background-color: #f2f2f2; }}
                .summary {{ font-weight: bold; margin-top: 20px; }}
                .button {{ display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>R&R Requests Approved</h2>
                </div>
                <div class="content">
                    <p>Dear {data['updater_name']},</p>
                    <p>Your <strong>{len(data['requests'])} R&R request(s)</strong> have been approved by <strong>{data['processor_name']}</strong>.</p>
                    
                    <table class="info-table">
                        <thead>
                            <tr>
                                <th>Employee</th>
                                <th>Points</th>
                                <th>Category</th>
                                <th>Notes</th>
                            </tr>
                        </thead>
                        <tbody>
                            {request_rows}
                        </tbody>
                    </table>
                    
                    <p class="summary">Total Points Awarded: {total_points}</p>
                    <p>Processed Date: {data['requests'][0]['processed_date']}</p>
                </div>
                <div class="footer">
                    <p>Please log in to the system to view updated records.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to Dashboard</a></center>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email_notification(
            updater_email,
            data['updater_name'],
            subject,
            html_content
        )


def send_r_and_r_approval_notification_to_employees(approved_employees):
    """Sends approval notification to employees for their R&R requests"""
    for emp_id, emp_data in approved_employees.items():
        employee_details = emp_data['employee_details']
        requests = emp_data['requests']
        
        if not employee_details['employee_email']:
            continue
            
        subject = f"Congratulations! Your R&R Request(s) Approved"
        
        request_rows = ""
        total_points = 0
        for req in requests:
            request_rows += f"""
            <tr>
                <td>{req['category_name']}</td>
                <td>{req['points']}</td>
                <td>{req['request_notes']}</td>
                <td>{req['event_date']}</td>
            </tr>
            """
            total_points += req['points']
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
                .info-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                .info-table th, .info-table td {{ padding: 8px; border: 1px solid #ddd; text-align: left; }}
                .info-table th {{ background-color: #f2f2f2; }}
                .summary {{ font-weight: bold; margin-top: 20px; color: #4CAF50; }}
                .button {{ display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; margin-top: 15px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🎉 Congratulations! Your R&R Points Approved</h2>
                </div>
                <div class="content">
                    <p>Dear {employee_details['employee_name']},</p>
                    <p>Great news! Your <strong>{len(requests)} R&R request(s)</strong> have been approved by <strong>{employee_details['processor_name']}</strong>.</p>
                    
                    <table class="info-table">
                        <thead>
                            <tr>
                                <th>Category</th>
                                <th>Points Awarded</th>
                                <th>Notes</th>
                                <th>Event Date</th>
                            </tr>
                        </thead>
                        <tbody>
                            {request_rows}
                        </tbody>
                    </table>
                    
                    <p class="summary">🏆 Total Points Awarded: {total_points}</p>
                    <p>Processed Date: {employee_details['processed_date']}</p>
                    
                    <p>These points have been added to your account. You can view your updated points balance by logging into the system.</p>
                </div>
                <div class="footer">
                    <p>Please log in to the system to view your updated points balance.</p>
                    <center><a href="https://pbs.prowesssoft.com/" class="button" style="color: #ffff; text-decoration: none;">Go to Dashboard</a></center>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email_notification(
            employee_details['employee_email'],
            employee_details['employee_name'],
            subject,
            html_content
        )


# ============================================================================
# VALIDATION AND PROCESSING HELPER FUNCTIONS
# ============================================================================

def validate_request_data(request_ids, action):
    """Enhanced validation for request data"""
    if not request_ids:
        return {
            'valid': False,
            'message': 'No requests selected. Please select at least one request to process.',
            'category': 'warning'
        }
    
    if not action or action not in ['approve', 'reject']:
        return {
            'valid': False,
            'message': f'Invalid action specified: {action}. Please try again.',
            'category': 'error'
        }

    valid_request_ids = []
    for req_id in request_ids:
        try:
            ObjectId(req_id)
            valid_request_ids.append(req_id)
        except Exception as e:
            logger.warning(f"Invalid request ID format: {req_id}, Error: {e}")
            continue
    
    if not valid_request_ids:
        return {
            'valid': False,
            'message': 'Invalid request IDs provided. Please refresh the page and try again.',
            'category': 'error'
        }
    
    return {
        'valid': True,
        'message': 'Validation successful',
        'valid_ids': valid_request_ids
    }


def create_points_record(point_request, user_id):
    """Create a points record for approved request"""
    try:
        points_data = {
            "user_id": point_request["user_id"],
            "category_id": point_request["category_id"],
            "points": point_request["points"],
            "notes": point_request.get("request_notes", ""),
            "event_date": point_request.get("event_date"),
            "awarded_by": ObjectId(user_id),
            "award_date": datetime.utcnow(),
            "request_id": point_request["_id"],
            "updated_by": "HR"
        }
        
        result = mongo.db.points.insert_one(points_data)
        
        return {
            'success': True,
            'points_id': str(result.inserted_id)
        }
        
    except Exception as e:
        logger.error(f"Error creating points record: {str(e)}")
        return {
            'success': False,
            'reason': str(e)
        }


def prepare_notification_data(point_request, employee, updater, user, r_and_r_category):
    """Prepare notification data for approved requests"""
    try:
        updater_notification = {
            'employee_name': employee.get('name', 'N/A'),
            'employee_id_code': employee.get('employee_id', 'N/A'),
            'updater_email': updater.get('email', ''),
            'updater_name': updater.get('name', 'N/A'),
            'processor_name': user.get('name', 'HR User'),
            'category_name': r_and_r_category.get('name', 'R&R'),
            'points': point_request.get('points', 0),
            'request_notes': point_request.get('request_notes', ''),
            'event_date': point_request.get('event_date', '').strftime('%d-%m-%Y') if point_request.get('event_date') else 'N/A',
            'processed_date': datetime.utcnow().strftime('%d-%m-%Y %H:%M')
        }
        
        employee_notification = {
            'employee_id': str(employee['_id']),
            'employee_details': {
                'employee_name': employee.get('name', 'N/A'),
                'employee_email': employee.get('email', ''),
                'processor_name': user.get('name', 'HR User'),
                'processed_date': datetime.utcnow().strftime('%d-%m-%Y %H:%M')
            },
            'requests': [{
                'category_name': r_and_r_category.get('name', 'R&R'),
                'points': point_request.get('points', 0),
                'request_notes': point_request.get('request_notes', ''),
                'event_date': point_request.get('event_date', '').strftime('%d-%m-%Y') if point_request.get('event_date') else 'N/A'
            }]
        }
        
        return {
            'updater': updater_notification,
            'employee': employee_notification
        }
        
    except Exception as e:
        logger.error(f"Error preparing notification data: {str(e)}")
        return None


def process_single_request(req_id, action, user_id, user, r_and_r_category, review_notes=None):
    """Process a single R&R request"""
    try:
        point_request = mongo.db.points_request.find_one({
            "_id": ObjectId(req_id),
            "status": "Pending",
            "pending_hr_approval": True,
            "category_id": r_and_r_category['_id'],
        })
        
        if not point_request:
            return {
                'success': False,
                'reason': 'Request not found or not eligible for processing'
            }

        employee = mongo.db.users.find_one({"_id": point_request["user_id"]})
        updater = mongo.db.users.find_one({"_id": point_request["created_by_pmo_id"]})

        if not employee:
            return {
                'success': False,
                'reason': 'Employee record not found'
            }

        update_data = {
            "status": "Approved" if action == "approve" else "Rejected",
            "response_date": datetime.utcnow(),
            "pmo_id": ObjectId(user_id),
            "updated_by": "HR"
        }
        
        if review_notes and review_notes.strip():
            update_data["review_notes"] = review_notes.strip()
        
        if action == 'approve':
            points_result = create_points_record(point_request, user_id)
            if not points_result['success']:
                return {
                    'success': False,
                    'reason': f'Failed to create points record: {points_result["reason"]}'
                }
        
        result = mongo.db.points_request.update_one(
            {"_id": ObjectId(req_id)},
            {"$set": update_data, "$unset": {"pending_hr_approval": ""}}
        )
        
        if result.modified_count == 0:
            return {
                'success': False,
                'reason': 'Failed to update request status'
            }

        notification_data = None
        if action == 'approve' and employee and updater:
            notification_data = prepare_notification_data(
                point_request, employee, updater, user, r_and_r_category
            )

        return {
            'success': True,
            'notification_data': notification_data
        }
        
    except Exception as e:
        logger.error(f"Error in process_single_request for {req_id}: {str(e)}")
        return {
            'success': False,
            'reason': f'Processing error: {str(e)}'
        }


def process_requests(request_ids, action, user_id, user, r_and_r_category, review_notes):
    """Process R&R requests with enhanced error handling and notifications."""
    processed_count = 0
    failed_count = 0
    approval_notifications = []
    employee_notifications = {}
    failed_requests = []

    for req_id in request_ids:
        try:
            result = process_single_request(req_id, action, user_id, user, r_and_r_category, review_notes)
            
            if result['success']:
                processed_count += 1
                if action == 'approve' and result.get('notification_data'):
                    approval_notifications.append(result['notification_data']['updater'])
                    
                    emp_data = result['notification_data']['employee']
                    emp_id = emp_data['employee_id']
                    if emp_id not in employee_notifications:
                        employee_notifications[emp_id] = emp_data
                    else:
                        employee_notifications[emp_id]['requests'].extend(emp_data['requests'])
            else:
                failed_count += 1
                failed_requests.append({
                    'id': req_id,
                    'reason': result.get('reason', 'Unknown error')
                })
                
        except Exception as e:
            logger.error(f"Critical error processing request {req_id}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            failed_count += 1
            failed_requests.append({
                'id': req_id,
                'reason': f'A critical server error occurred: {str(e)}'
            })

    if action == 'approve' and (approval_notifications or employee_notifications):
        send_approval_notifications(approval_notifications, employee_notifications)

    return {
        'processed_count': processed_count,
        'failed_count': failed_count,
        'failed_requests': failed_requests,
        'total_requests': len(request_ids)
    }


def send_approval_notifications(approval_notifications, employee_notifications):
    """Send email notifications for approved requests"""
    try:
        if approval_notifications:
            send_r_and_r_approval_notification_to_updater(approval_notifications)
            logger.info(f"Sent approval notifications to {len(approval_notifications)} updaters")
        
        if employee_notifications:
            send_r_and_r_approval_notification_to_employees(employee_notifications)
            logger.info(f"Sent approval notifications to {len(employee_notifications)} employees")
            
    except Exception as e:
        logger.error(f"Error sending email notifications: {str(e)}")


def provide_user_feedback(result, action):
    """Provide enhanced user feedback based on processing results"""
    processed = result['processed_count']
    failed = result['failed_count']
    total = result['total_requests']
    
    action_text = "approved" if action == "approve" else "rejected"
    
    if processed > 0:
        if processed == total:
            flash(f'✅ Successfully {action_text} all {processed} request(s)!', 'success')
        else:
            flash(f'✅ Successfully {action_text} {processed} out of {total} request(s).', 'success')
            if failed > 0:
                flash(f'⚠️ {failed} request(s) could not be processed. They may have been already processed by another user.', 'warning')
    else:
        if failed > 0:
            flash(f'❌ No requests were processed. {failed} request(s) failed processing. Please refresh the page and try again.', 'error')
        else:
            flash('ℹ️ No requests were processed. Please check your selections and try again.', 'info')
    
    logger.info(f"Processing complete - Action: {action}, Processed: {processed}, Failed: {failed}, Total: {total}")
    if result.get('failed_requests'):
        for failed_req in result['failed_requests']:
            logger.warning(f"Failed request {failed_req['id']}: {failed_req['reason']}")


# ============================================================================
# DATA RETRIEVAL HELPER FUNCTIONS
# ============================================================================

def determine_urgency_level(request):
    """Determine urgency level based on request age and points"""
    try:
        request_date = request.get('request_date', datetime.utcnow())
        days_old = (datetime.utcnow() - request_date).days
        points = request.get('points', 0)
        
        if days_old > 7:
            return 'high'
        elif days_old > 3 or points > 50:
            return 'medium'
        else:
            return 'low'
    except:
        return 'low'


def calculate_time_since_submission(request):
    """Calculate time since request submission"""
    try:
        request_date = request.get('request_date', datetime.utcnow())
        time_diff = datetime.utcnow() - request_date
        
        if time_diff.days > 0:
            return f"{time_diff.days} days ago"
        elif time_diff.seconds > 3600:
            hours = time_diff.seconds // 3600
            return f"{hours} hours ago"
        else:
            minutes = time_diff.seconds // 60
            return f"{minutes} minutes ago"
    except:
        return "Unknown"


def calculate_processing_time(request):
    """Calculate processing time in hours"""
    try:
        request_date = request.get('request_date', datetime.utcnow())
        response_date = request.get('response_date', datetime.utcnow())
        
        time_diff = response_date - request_date
        hours = round(time_diff.total_seconds() / 3600, 1)
        
        return hours
    except:
        return 0


def get_pending_r_and_r_requests(category_id):
    """Enhanced helper function to get formatted pending R&R requests"""
    try:
        pending_requests_cursor = mongo.db.points_request.find({
            "status": "Pending",
            "pending_hr_approval": True,
            "category_id": category_id
        }).sort("request_date", 1)

        pending_requests = []
        for req in pending_requests_cursor:
            employee = mongo.db.users.find_one({"_id": req["user_id"]})
            submitted_by = mongo.db.users.find_one({"_id": req.get("created_by_pmo_id")})
            category = mongo.db.categories.find_one({"_id": category_id})

            if employee and category:
                submitted_by_name = submitted_by.get('name', 'Unknown User') if submitted_by else 'Unknown User'
                submitted_by_email = submitted_by.get('email', '') if submitted_by else ''

                request_data = {
                    'id': str(req['_id']),
                    'request_date': req.get('request_date', datetime.utcnow()).strftime('%d-%m-%Y'),
                    'event_date': req.get('event_date', datetime.utcnow()).strftime('%d-%m-%Y') if req.get('event_date') else 'N/A',
                    'employee_name': employee.get('name', 'N/A'),
                    'employee_id_code': employee.get('employee_id', 'N/A'),
                    'submitted_by_name': submitted_by_name,
                    'category_name': category.get('name', 'R&R'),
                    'points': req.get('points', 0),
                    'request_notes': req.get('request_notes', '') or '',
                    'urgency_level': determine_urgency_level(req),
                    'time_since_submission': calculate_time_since_submission(req),
                    'submitted_by_email': submitted_by_email,
                    'employee_email': employee.get('email', ''),
                    'department': employee.get('department', 'N/A'),
                    'employee_phone': employee.get('phone', ''),
                }
                pending_requests.append(request_data)
            elif not employee:
                logger.warning(f"Skipping request {req['_id']} because employee with ID {req.get('user_id')} was not found.")
            elif not category:
                logger.warning(f"Skipping request {req['_id']} because category with ID {category_id} was not found.")

        logger.info(f"Retrieved {len(pending_requests)} pending R&R requests")
        return pending_requests
        
    except Exception as e:
        logger.error(f"Error in get_pending_r_and_r_requests: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return []


def get_review_history_data(category_id, limit=100):
    """Enhanced helper function to get formatted review history"""
    try:
        reviewed_requests_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "category_id": category_id,
            "response_date": {"$exists": True}
        }).sort("response_date", -1).limit(limit)

        reviewed_requests = []
        for req in reviewed_requests_cursor:
            try:
                employee = mongo.db.users.find_one({"_id": req["user_id"]})
                reviewed_by = mongo.db.users.find_one({"_id": req.get("pmo_id")})
                submitted_by = mongo.db.users.find_one({"_id": req.get("created_by_pmo_id")})
                category = mongo.db.categories.find_one({"_id": category_id})
                
                if employee and category:
                    history_data = {
                        'id': str(req['_id']),
                        'reviewed_at': req.get('response_date', datetime.utcnow()).strftime('%d-%m-%Y'),
                        'employee_name': employee.get('name', 'N/A'),
                        'employee_id_code': employee.get('employee_id', 'N/A'),
                        'category_name': category.get('name', 'R&R'),
                        'points': req.get('points', 0),
                        'status': req.get('status', 'Unknown'),
                        'reviewed_by_name': reviewed_by.get('name', 'HR User') if reviewed_by else 'HR User',
                        'request_date': req.get('request_date', datetime.utcnow()).strftime('%d-%m-%Y'),
                        'event_date': req.get('event_date', datetime.utcnow()).strftime('%d-%m-%Y') if req.get('event_date') else 'N/A',
                        'submitted_by_name': submitted_by.get('name', 'Unknown User') if submitted_by else 'Unknown User',
                        'request_notes': req.get('request_notes', '') or '',
                        'processing_time_hours': calculate_processing_time(req),
                    }
                    reviewed_requests.append(history_data)
                else:
                    logger.warning(f"Missing related data for reviewed request {req['_id']}")
                    
            except Exception as e:
                logger.error(f"Error processing review history {req.get('_id', 'unknown')}: {str(e)}")
                continue

        logger.info(f"Retrieved {len(reviewed_requests)} review history records")
        return reviewed_requests
        
    except Exception as e:
        logger.error(f"Error in get_review_history_data: {str(e)}")
        return []


def handle_post_request(user_id, user):
    """Handle POST request for processing R&R requests with robust error handling"""
    try:
        logger.info("=== PROCESSING R&R REQUESTS ===")
        form_data = dict(request.form)
        logger.info(f"Form data: {form_data}")
        
        request_ids = request.form.getlist('request_ids[]')
        action = request.form.get('action')
        review_notes = request.form.get('review_notes', '').strip()
        
        validation_result = validate_request_data(request_ids, action)
        if not validation_result['valid']:
            flash(validation_result['message'], validation_result['category'])
            return redirect(url_for('hr_rr_review.review_r_and_r_requests'))

        r_and_r_category = mongo.db.categories.find_one({"code": "r&r"})
        if not r_and_r_category:
            flash('R&R category not found. Please contact system administrator.', 'danger')
            return redirect(url_for('hr_rr_review.review_r_and_r_requests'))

        result = process_requests(request_ids, action, user_id, user, r_and_r_category, review_notes)
        
        provide_user_feedback(result, action)
        
        return redirect(url_for('hr_rr_review.review_r_and_r_requests'))
        
    except Exception as e:
        logger.error(f"An unexpected error occurred in handle_post_request: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        flash('An unexpected error occurred while processing the requests. Please try again or contact support.', 'danger')
        return redirect(url_for('hr_rr_review.review_r_and_r_requests'))


def handle_get_request(user):
    """Handle GET request for displaying R&R requests"""
    try:
        r_and_r_category = mongo.db.categories.find_one({"code": "r&r"})
        if not r_and_r_category:
            flash('R&R category not found. Please contact system administrator.', 'danger')
            return render_template('review_r_and_r_requests.html', 
                                 user=user, 
                                 pending_requests=[], 
                                 review_history=[])

        pending_requests = get_pending_r_and_r_requests(r_and_r_category['_id'])
        review_history = get_review_history_data(r_and_r_category['_id'])
        
        logger.info(f"Loaded {len(pending_requests)} pending requests and {len(review_history)} history items")

        return render_template('review_r_and_r_requests.html', 
                             user=user, 
                             pending_requests=pending_requests,
                             review_history=review_history)
    
    except Exception as e:
        logger.error(f"Error in GET request: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        flash('An error occurred while loading the page. Please try again.', 'error')
        return render_template('review_r_and_r_requests.html', 
                             user=user, 
                             pending_requests=[], 
                             review_history=[])


# ============================================================================
# FLASK ROUTES
# ============================================================================

@hr_rr_review_bp.route('/review-requests', methods=['GET', 'POST'])
def review_r_and_r_requests():
    """Enhanced R&R request review with improved error handling and notifications"""
    if session.get('user_role') != 'HR':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('auth.login'))

    user_id = session.get('user_id')
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})

    if request.method == 'POST':
        return handle_post_request(user_id, user)
    else:
        return handle_get_request(user)


@hr_rr_review_bp.route('/api/pending-requests', methods=['GET'])
def get_pending_requests_api():
    """Enhanced API endpoint for pending R&R requests with better error handling"""
    try:
        if session.get('user_role') != 'HR':
            return jsonify({
                'success': False, 
                'message': 'Unauthorized access',
                'error_code': 'UNAUTHORIZED'
            }), 403

        r_and_r_category = mongo.db.categories.find_one({"code": "r&r"})
        if not r_and_r_category:
            return jsonify({
                'success': False, 
                'message': 'R&R category not found',
                'error_code': 'CATEGORY_NOT_FOUND'
            }), 404

        pending_requests = get_pending_r_and_r_requests(r_and_r_category['_id'])

        response_data = {
            'success': True,
            'data': pending_requests,
            'count': len(pending_requests),
            'last_updated': datetime.utcnow().isoformat(),
            'category_name': r_and_r_category.get('name', 'R&R'),
            'server_time': datetime.utcnow().strftime('%Y-%m-%d UTC')
        }
        
        logger.info(f"API: Returned {len(pending_requests)} pending requests")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error in get_pending_requests_api: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False, 
            'message': 'Internal server error',
            'error_code': 'INTERNAL_ERROR'
        }), 500


@hr_rr_review_bp.route('/api/review-history', methods=['GET'])
def get_review_history_api():
    """Enhanced API endpoint for R&R review history"""
    try:
        if session.get('user_role') != 'HR':
            return jsonify({
                'success': False, 
                'message': 'Unauthorized access',
                'error_code': 'UNAUTHORIZED'
            }), 403

        r_and_r_category = mongo.db.categories.find_one({"code": "r&r"})
        if not r_and_r_category:
            return jsonify({
                'success': False, 
                'message': 'R&R category not found',
                'error_code': 'CATEGORY_NOT_FOUND'
            }), 404

        review_history = get_review_history_data(r_and_r_category['_id'])

        response_data = {
            'success': True,
            'data': review_history,
            'count': len(review_history),
            'last_updated': datetime.utcnow().isoformat(),
            'category_name': r_and_r_category.get('name', 'R&R')
        }
        
        logger.info(f"API: Returned {len(review_history)} history records")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error in get_review_history_api: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'Internal server error',
            'error_code': 'INTERNAL_ERROR'
        }), 500


@hr_rr_review_bp.route('/api/request-count', methods=['GET'])
def get_request_count():
    """Lightweight API endpoint for request count polling"""
    try:
        if session.get('user_role') != 'HR':
            return jsonify({
                'success': False, 
                'message': 'Unauthorized access'
            }), 403

        r_and_r_category = mongo.db.categories.find_one({"code": "r&r"})
        if not r_and_r_category:
            return jsonify({
                'success': False, 
                'message': 'R&R category not found'
            }), 404

        count = mongo.db.points_request.count_documents({
            "status": "Pending",
            "pending_hr_approval": True,
            "category_id": r_and_r_category['_id']
        })

        return jsonify({
            'success': True,
            'count': count,
            'last_updated': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error in get_request_count: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'Internal server error'
        }), 500


@hr_rr_review_bp.route('/api/notifications/mark-read', methods=['POST'])
def mark_notifications_read():
    """API endpoint to mark notifications as read"""
    try:
        if session.get('user_role') != 'HR':
            return jsonify({
                'success': False, 
                'message': 'Unauthorized access'
            }), 403

        user_id = session.get('user_id')
        notification_ids = request.json.get('notification_ids', [])

        if notification_ids:
            object_ids = []
            for nid in notification_ids:
                try:
                    object_ids.append(ObjectId(nid))
                except:
                    continue
            
            if object_ids:
                result = mongo.db.notifications.update_many(
                    {
                        "_id": {"$in": object_ids},
                        "user_id": ObjectId(user_id)
                    },
                    {"$set": {
                        "read": True, 
                        "read_date": datetime.utcnow()
                    }}
                )
                
                logger.info(f"Marked {result.modified_count} notifications as read for user {user_id}")

        return jsonify({
            'success': True, 
            'message': 'Notifications marked as read'
        })

    except Exception as e:
        logger.error(f"Error in mark_notifications_read: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'Internal server error'
        }), 500


@hr_rr_review_bp.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    try:
        mongo.db.categories.find_one({"code": "r&r"})
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'service': 'HR R&R Management API'
        })
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@hr_rr_review_bp.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'message': 'Endpoint not found',
        'error_code': 'NOT_FOUND'
    }), 404


@hr_rr_review_bp.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({
        'success': False,
        'message': 'Internal server error',
        'error_code': 'INTERNAL_ERROR'
    }), 500