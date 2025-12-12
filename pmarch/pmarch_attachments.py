"""
PM/Arch Attachments Module
Handles file attachment upload, download, and management for PM/Arch requests
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
    
    @bp.route('/test_attachment')
    def test_attachment():
        """Test route to verify blueprint is working"""
        return "PMArch attachment route is working!"
    
    @bp.route('/get_attachment/<request_id>', methods=['GET'])
    def get_attachment(request_id):
        """Get attachment for a PM/Arch request"""
        try:
            logger.debug(f"📥 PMARCH: Attachment download requested for request_id: {request_id}")
            
            user_id = session.get('user_id')
            
            if not user_id:
                logger.warning(f"❌ PMARCH: No user_id in session")
                flash('You need to log in first', 'warning')
                return redirect(url_for('auth.login'))
            
            logger.debug(f"📥 PMARCH: Downloading attachment for request: {request_id}")
            
            # Check dashboard access
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                logger.warning(f"❌ PMARCH: User not found in database: {user_id}")
                flash('User not found', 'danger')
                return redirect(url_for('auth.login'))
            
            logger.debug(f"📥 PMARCH: User found: {user.get('name')}, dashboard_access: {user.get('dashboard_access')}")
            
            # Check PM/Arch access
            dashboard_access = user.get('dashboard_access', [])
            if isinstance(dashboard_access, str):
                dashboard_access = [dashboard_access]
            
            # Convert to lowercase for case-insensitive comparison
            dashboard_access_lower = [d.lower() if isinstance(d, str) else d for d in dashboard_access]
            
            # Check for pm_arch dashboard access (matching pm, presales format)
            has_pmarch_access = 'pm_arch' in dashboard_access_lower
            
            logger.debug(f"📥 PMARCH: Access check - dashboard_access_lower: {dashboard_access_lower}, has_access: {has_pmarch_access}")
            
            if not has_pmarch_access:
                logger.warning(f"❌ PMARCH: User doesn't have PM/Arch access. dashboard_access: {dashboard_access}")
                flash('You do not have permission to access this attachment', 'danger')
                return redirect(url_for('pm_arch.dashboard'))
            
            # Find the request to get the attachment ID
            request_data = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
            
            if not request_data:
                logger.warning(f"❌ PMARCH: Request not found")
                flash('Request not found', 'warning')
                return redirect(url_for('pm_arch.dashboard'))
            
            logger.debug(f"📥 PMARCH: Request found. has_attachment: {request_data.get('has_attachment')}, attachment_id: {request_data.get('attachment_id')}")
            
            # Check if request is assigned to this user or processed by them
            if str(request_data.get("assigned_validator_id")) != str(user["_id"]) and \
               str(request_data.get("processed_by", "")) != str(user["_id"]) and \
               str(request_data.get("user_id")) != str(user["_id"]):
                logger.warning(f"❌ PMARCH: User not authorized for this request")
                flash('You are not authorized to view this attachment', 'danger')
                return redirect(url_for('pm_arch.dashboard'))
            
            if not request_data.get('has_attachment'):
                logger.warning(f"❌ PMARCH: No attachment flag set")
                flash('No attachment found for this request', 'warning')
                return redirect(url_for('pm_arch.dashboard'))
            
            attachment_id = request_data.get('attachment_id')
            if not attachment_id:
                logger.warning(f"❌ PMARCH: No attachment_id in request")
                flash('Attachment ID is missing', 'warning')
                return redirect(url_for('pm_arch.dashboard'))
            
            # Create GridFS instance
            fs = GridFS(mongo.db)
            
            # Convert to ObjectId if string
            if isinstance(attachment_id, str):
                attachment_id = ObjectId(attachment_id)
            
            logger.debug(f"📥 PMARCH: Looking for file with ID: {attachment_id}")
            
            # Get the file from GridFS
            if not fs.exists(attachment_id):
                logger.error(f"❌ PMARCH: File doesn't exist in GridFS")
                flash('Attachment file not found in storage', 'warning')
                return redirect(url_for('pm_arch.dashboard'))
            
            logger.debug(f"✅ PMARCH: File exists, retrieving...")
            
            # Get the file and its metadata
            grid_out = fs.get(attachment_id)
            file_data = grid_out.read()
            
            logger.debug(f"✅ PMARCH: File retrieved, size: {len(file_data)} bytes")
            
            # Prepare the response
            file_stream = io.BytesIO(file_data)
            file_stream.seek(0)
            
            # Get the original filename from metadata
            original_filename = grid_out.metadata.get('original_filename', 
                                                     request_data.get('attachment_filename', 'attachment'))
            content_type = grid_out.content_type or 'application/octet-stream'
            
            logger.debug(f"✅ PMARCH: Sending file: {original_filename}, content_type: {content_type}")
            
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
            logger.error(f"❌ PMARCH: Error retrieving attachment: {str(e)}")
            logger.error(traceback.format_exc())
            flash('An error occurred while retrieving the attachment', 'danger')
            return redirect(url_for('pm_arch.dashboard'))
