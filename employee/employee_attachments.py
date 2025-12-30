from flask import Blueprint, request, session, redirect, url_for, flash, send_file
from extensions import mongo
import io
import sys
import traceback
from bson.objectid import ObjectId
from gridfs import GridFS

employee_attachments_bp = Blueprint('employee_attachments', __name__, url_prefix='/employee')



@employee_attachments_bp.route('/attachment/<request_id>', methods=['GET'])
def get_attachment(request_id):
    try:
        user_id = session.get('user_id')
        if not user_id:
            flash('You need to log in first', 'warning')
            return redirect(url_for('auth.login'))
        
        request_data = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not request_data or not request_data.get('has_attachment') or not request_data.get('attachment_id'):
            flash('No attachment found for this request', 'warning')
            return redirect(url_for('employee_dashboard.dashboard'))
        
        # Check if user can access this attachment
        current_user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        if not current_user:
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))
        
        # Check if it's the user's own request
        if str(request_data['user_id']) != user_id:
            # Check if user has validator access for this category
            category = mongo.db.categories.find_one({"_id": request_data.get('category_id')})
            validator_type = category.get('validator', '') if category else ''
            
            dashboard_access = current_user.get('dashboard_access', [])
            has_validator_access = False
            
            if validator_type:
                required_access = [
                    f"{validator_type} - Validator",
                    f"{validator_type} - Updater"
                ]
                has_validator_access = any(access in dashboard_access for access in required_access)
            
            # Also check if user has admin/HR access
            has_admin_access = any(access in ['hr', 'central'] for access in dashboard_access)
            
            if not has_validator_access and not has_admin_access:
                flash('You do not have permission to access this attachment', 'danger')
                return redirect(url_for('employee_dashboard.dashboard'))
        
        fs = GridFS(mongo.db)
        
        attachment_id = request_data['attachment_id']
        if not fs.exists(ObjectId(attachment_id)):
            flash('Attachment file not found', 'warning')
            return redirect(url_for('employee_dashboard.dashboard'))
        
        grid_out = fs.get(ObjectId(attachment_id))
        
        file_stream = io.BytesIO(grid_out.read())
        file_stream.seek(0)
        
        original_filename = grid_out.metadata.get('original_filename', 'attachment')
        content_type = grid_out.content_type
        
        return send_file(
            file_stream,
            mimetype=content_type,
            download_name=original_filename,
            as_attachment=True
        )
    
    except Exception as e:
        flash('An error occurred while retrieving the attachment', 'danger')
        return redirect(url_for('employee_dashboard.dashboard'))