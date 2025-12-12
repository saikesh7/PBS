from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
from gridfs import GridFS
import io
import logging
from threading import Thread

logger = logging.getLogger(__name__)

# Import email notification function
try:
    from pm.pm_notifications import send_new_request_notification
except ImportError:
    logger.warning("pm_notifications module not found, email notifications will be disabled")
    send_new_request_notification = None

employee_raise_request_bp = Blueprint(
    'employee_raise_request', 
    __name__, 
    url_prefix='/employee',
    template_folder='templates',
    static_folder='static'
)

@employee_raise_request_bp.route('/raise-request')
def raise_request():
    """Render the raise request page"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return redirect(url_for('auth.login'))
    
    # Get categories from hr_categories collection
    categories = list(mongo.db.hr_categories.find(
        {
            'category_type': 'Employee raised',
            'category_status': 'active'
        }
    ).sort('name', 1))
    
    # Convert ObjectId to string for template
    for category in categories:
        category['_id'] = str(category['_id'])
    
    # Get pending requests
    pending_requests = []
    pending_reqs = mongo.db.points_request.find({
        'user_id': ObjectId(user_id),
        'status': 'Pending'
    }).sort('request_date', -1)
    
    for req in pending_reqs:
        category = mongo.db.hr_categories.find_one({'_id': req.get('category_id')})
        validator = mongo.db.users.find_one({'_id': req.get('assigned_validator_id')})
        
        pending_requests.append({
            'id': str(req['_id']),
            'category_name': category.get('name', 'Unknown') if category else 'Unknown',
            'category_department': category.get('category_department', 'Unknown') if category else 'Unknown',
            'points': req.get('points', 0),
            'assigned_validator_name': validator.get('name') if validator else None,
            'assigned_validator_emp_id': validator.get('employee_id') if validator else None,
            'request_date': req.get('request_date'),
            'submission_notes': req.get('submission_notes'),
            'has_attachment': req.get('has_attachment', False),
            'attachment_filename': req.get('attachment_filename', '')
        })
    
    return render_template('employee_raise_request.html',
                         user=user,
                         categories=categories,
                         pending_requests=pending_requests,
                         other_dashboards=[],
                         user_profile_pic_url=None)

@employee_raise_request_bp.route('/submit-request', methods=['POST'])
def submit_request():
    """Handle form submission for raise request"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    try:
        category_id = request.form.get('category_id')
        validator_id = request.form.get('selected_validator_id')
        notes = request.form.get('notes')
        attachment = request.files.get('attachment')
        
        if not all([category_id, validator_id, notes]):
            flash('All required fields must be filled', 'danger')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        # Get category details from hr_categories
        category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        if not category or not user:
            flash('Invalid category or user', 'danger')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        # Calculate points based on user grade
        points = 0
        user_grade = user.get('grade', 'D2')
        
        points_per_unit = category.get('points_per_unit', {})
        if isinstance(points_per_unit, dict):
            points = points_per_unit.get(user_grade, points_per_unit.get('base', 0))
        else:
            points = points_per_unit
        
        # ✅ Handle file upload using GridFS
        attachment_id = None
        attachment_filename = None
        has_attachment = False
        
        if attachment and attachment.filename:
            try:
                # Read file data
                file_data = attachment.read()
                
                if len(file_data) > 0:
                    fs = GridFS(mongo.db)
                    
                    # Secure the filename
                    secure_name = secure_filename(attachment.filename)
                    original_filename = secure_name
                    
                    # Save to GridFS
                    attachment_id = fs.put(
                        file_data,
                        filename=original_filename,
                        content_type=attachment.content_type or 'application/octet-stream',
                        metadata={
                            'original_filename': original_filename,
                            'user_id': str(user_id),
                            'upload_date': datetime.utcnow(),
                            'category_id': str(category_id)
                        }
                    )
                    
                    attachment_filename = original_filename
                    has_attachment = True
                else:
                    flash('Uploaded file is empty', 'warning')
                    
            except Exception as e:
                logger.error(f"Error uploading file: {str(e)}")
                flash(f'Error uploading attachment: {str(e)}', 'warning')
        
        # Create request document
        request_doc = {
            'user_id': ObjectId(user_id),
            'category_id': ObjectId(category_id),
            'assigned_validator_id': ObjectId(validator_id),
            'points': points,
            'user_grade': user_grade,
            'submission_notes': notes,
            'request_notes': notes,
            'has_attachment': has_attachment,
            'attachment_id': attachment_id,
            'attachment_filename': attachment_filename,
            'status': 'Pending',
            'request_date': datetime.utcnow(),
            'event_date': datetime.utcnow(),
            'source': 'employee',
            'created_by': ObjectId(user_id),
            'updated_by': 'Employee',
            'category_name': category.get('name'),
            'category_department': category.get('category_department'),
            'frequency': category.get('frequency')
        }
        
        result = mongo.db.points_request.insert_one(request_doc)
        
        # Send email notification to validator asynchronously
        if send_new_request_notification:
            try:
                validator = mongo.db.users.find_one({'_id': ObjectId(validator_id)})
                
                if validator and user and category:
                    # Prepare request data for email
                    email_request_data = {
                        '_id': result.inserted_id,
                        'points': points,
                        'request_notes': notes,
                        'submission_notes': notes,
                        'has_attachment': has_attachment,
                        'attachment_filename': attachment_filename
                    }
                    
                    Thread(target=send_new_request_notification, args=(
                        email_request_data,
                        user,
                        validator,
                        category
                    )).start()
            except Exception as e:
                logger.error(f"Error sending email notification: {str(e)}")
                # Don't fail the request submission if email fails
        
        flash('Request submitted successfully!', 'success')
        
    except Exception as e:
        logger.error(f"Error in submit_request: {str(e)}")
        flash(f'Error submitting request: {str(e)}', 'danger')
    
    return redirect(url_for('employee_raise_request.raise_request'))

@employee_raise_request_bp.route('/api/get-validators-by-category/<category_id>')
def get_validators_by_category(category_id):
    """API to get validators for a specific category"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated', 'success': False}), 401
    
    try:
        category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        
        if not category:
            return jsonify({'error': 'Category not found', 'success': False}), 404
        
        category_department = category.get('category_department')
        
        if not category_department:
            return jsonify({'error': 'Category department not configured', 'success': False})
        
        # Find validators (excluding current user)
        validators = list(mongo.db.users.find({
            'dashboard_access': category_department,
            'is_active': True,
            '_id': {'$ne': ObjectId(user_id)}
        }))
        
        if not validators:
            return jsonify({
                'error': f'No validators found with {category_department} access.',
                'success': False
            })
        
        validators_list = [{
            'id': str(v['_id']),
            'name': v.get('name', 'Unknown'),
            'employee_id': v.get('employee_id', 'N/A'),
            'role': v.get('role', 'Employee'),
            'grade': v.get('grade', 'N/A')
        } for v in validators]
        
        validators_list.sort(key=lambda x: x['name'])
        
        return jsonify({
            'success': True,
            'validators': validators_list,
            'department': category_department
        })
        
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}', 'success': False}), 500

@employee_raise_request_bp.route('/get-category-details/<category_id>')
def get_category_details(category_id):
    """Get category details including points for user's grade"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not authenticated', 'success': False}), 401
    
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        
        if not category:
            return jsonify({'error': 'Category not found', 'success': False}), 404
        
        if not user:
            return jsonify({'error': 'User not found', 'success': False}), 404
        
        user_grade = user.get('grade', 'D2')
        
        # Get points for user's grade
        points_per_unit_config = category.get('points_per_unit', {})
        if isinstance(points_per_unit_config, dict):
            points_per_unit = points_per_unit_config.get(user_grade, points_per_unit_config.get('base', 0))
        else:
            points_per_unit = points_per_unit_config
        
        return jsonify({
            'success': True,
            'grade': user_grade,
            'points_per_unit': points_per_unit,
            'category_name': category.get('name'),
            'category_department': category.get('category_department', 'N/A'),
            'description': category.get('description', '')
        })
        
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}', 'success': False}), 500

@employee_raise_request_bp.route('/get-attachment/<request_id>')
def get_attachment(request_id):
    """Download attachment for a request"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    try:
        # Get the request
        req = mongo.db.points_request.find_one({'_id': ObjectId(request_id)})
        
        if not req:
            flash('Request not found', 'danger')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        # Check if user owns this request
        if str(req.get('user_id')) != str(user_id):
            flash('Unauthorized access', 'danger')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        if not req.get('has_attachment'):
            flash('No attachment found', 'warning')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        attachment_id = req.get('attachment_id')
        if not attachment_id:
            flash('Attachment ID missing', 'warning')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        # Get from GridFS
        fs = GridFS(mongo.db)
        
        # Convert to ObjectId if needed
        if isinstance(attachment_id, str):
            attachment_id = ObjectId(attachment_id)
        
        if not fs.exists(attachment_id):
            flash('Attachment file not found in storage', 'warning')
            return redirect(url_for('employee_raise_request.raise_request'))
        
        grid_out = fs.get(attachment_id)
        file_data = grid_out.read()
        
        file_stream = io.BytesIO(file_data)
        file_stream.seek(0)
        
        original_filename = grid_out.metadata.get('original_filename', req.get('attachment_filename', 'attachment'))
        content_type = grid_out.content_type or 'application/octet-stream'
        
        return send_file(
            file_stream,
            mimetype=content_type,
            download_name=original_filename,
            as_attachment=True
        )
        
    except Exception as e:
        logger.error(f"Error downloading attachment: {str(e)}")
        flash(f'Error downloading attachment: {str(e)}', 'danger')
        return redirect(url_for('employee_raise_request.raise_request'))