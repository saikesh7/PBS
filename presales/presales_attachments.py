"""
Presales Attachments Module
Handles file attachment upload, download, and management for presales requests
"""
from flask import request, session, redirect, url_for, flash, send_file
from extensions import mongo
from bson.objectid import ObjectId
from gridfs import GridFS
import io
import traceback
import logging

logger = logging.getLogger(__name__)

def register_attachment_routes(bp):
    """Register ONLY attachment route to the blueprint"""
    
    @bp.route('/get_attachment/<request_id>', methods=['GET'])
    def get_attachment(request_id):
        """Get attachment for a presales request"""
        try:
            user_id = session.get('user_id')
            
            if not user_id:
                flash('You need to log in first', 'warning')
                return redirect(url_for('auth.login'))
            
            # Check dashboard access
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            
            # Check Presales access
            dashboard_access = user.get('dashboard_access', []) if user else []
            if isinstance(dashboard_access, str):
                dashboard_access = [dashboard_access]
            
            # Convert to lowercase for case-insensitive comparison
            dashboard_access_lower = [d.lower() if isinstance(d, str) else d for d in dashboard_access]
            
            has_presales_access = ('presales' in dashboard_access_lower or 
                                  user.get('manager_level') == 'Pre-sales')
            
            if not has_presales_access:
                flash('You do not have permission to access this attachment', 'danger')
                return redirect(url_for('presales.dashboard'))
            
            # Find the request to get the attachment ID
            request_data = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
            
            if not request_data:
                flash('Request not found', 'warning')
                return redirect(url_for('presales.dashboard'))
            
            # Check if request is assigned to this user or processed by them
            if str(request_data.get("assigned_validator_id")) != str(user["_id"]) and \
               str(request_data.get("processed_by", "")) != str(user["_id"]) and \
               str(request_data.get("user_id")) != str(user["_id"]):
                flash('You are not authorized to view this attachment', 'danger')
                return redirect(url_for('presales.dashboard'))
            
            if not request_data.get('has_attachment'):
                flash('No attachment found for this request', 'warning')
                return redirect(url_for('presales.dashboard'))
            
            attachment_id = request_data.get('attachment_id')
            if not attachment_id:
                flash('Attachment ID is missing', 'warning')
                return redirect(url_for('presales.dashboard'))
            
            # Create GridFS instance
            fs = GridFS(mongo.db)
            
            # Convert to ObjectId if string
            if isinstance(attachment_id, str):
                attachment_id = ObjectId(attachment_id)
            
            # Get the file from GridFS
            if not fs.exists(attachment_id):
                flash('Attachment file not found in storage', 'warning')
                return redirect(url_for('presales.dashboard'))
            
            # Get the file and its metadata
            grid_out = fs.get(attachment_id)
            file_data = grid_out.read()
            
            # Prepare the response
            file_stream = io.BytesIO(file_data)
            file_stream.seek(0)
            
            # Get the original filename from metadata
            original_filename = grid_out.metadata.get('original_filename', 
                                                     request_data.get('attachment_filename', 'attachment'))
            content_type = grid_out.content_type or 'application/octet-stream'
            
            # Determine if file should be displayed inline or downloaded
            viewable_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf']
            as_attachment = content_type not in viewable_types
            
            # Send the file to the user
            return send_file(
                file_stream,
                mimetype=content_type,
                download_name=original_filename,
                as_attachment=as_attachment
            )
            
        except Exception as e:
            logger.error(f"❌ PRESALES: Error retrieving attachment: {str(e)}")
            logger.error(traceback.format_exc())
            flash('An error occurred while retrieving the attachment', 'danger')
            return redirect(url_for('presales.dashboard'))
