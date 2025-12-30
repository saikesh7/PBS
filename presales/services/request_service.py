"""
Request Service
Handles business logic for presales request processing
"""
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
from gridfs import GridFS
import logging

logger = logging.getLogger(__name__)

class RequestService:
    """Service for handling presales request operations"""
    
    @staticmethod
    def get_request_by_id(request_id):
        """Get a request by ID"""
        try:
            return mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        except Exception as e:
            logger.error(f"Error fetching request {request_id}: {e}")
            return None
    
    @staticmethod
    def validate_request_access(request_data, user_id):
        """Validate if user has access to process this request"""
        if not request_data:
            return False, "Request not found"
        
        if str(request_data.get("assigned_validator_id")) != str(user_id):
            return False, "You are not authorized to process this request"
        
        return True, None
    
    @staticmethod
    def get_employee_by_id(user_id):
        """Get employee details"""
        try:
            return mongo.db.users.find_one({"_id": user_id})
        except Exception as e:
            logger.error(f"Error fetching employee {user_id}: {e}")
            return None
    
    @staticmethod
    def get_category_by_id(category_id):
        """Get category details - checks both hr_categories and old categories collection"""
        try:
            # Try hr_categories first (new code)
            category = mongo.db.hr_categories.find_one({"_id": category_id})
            if category:
                return category
            
            # Fall back to old categories collection
            category = mongo.db.categories.find_one({"_id": category_id})
            return category
        except Exception as e:
            logger.error(f"Error fetching category {category_id}: {e}")
            return None
    
    @staticmethod
    def approve_request(request_id, user_id, notes):
        """
        Approve a request and award points
        Returns: (success, message, points_award_data)
        """
        try:
            processed_time = datetime.utcnow()
            
            # Get request data
            request_data = RequestService.get_request_by_id(request_id)
            if not request_data:
                return False, "Request not found", None
            
            # ✅ FIXED: Always set processed_department to "presales" when approved via presales dashboard
            # This ensures the request is counted in presales quarterly stats
            processed_department = "presales"
            
            # Update request status
            update_data = {
                "status": "Approved",
                "processed_date": processed_time,
                "processed_by": ObjectId(user_id),
                "response_notes": notes,
                "manager_notes": notes,
                "processed_department": processed_department  # Always "presales" for presales approvals
            }
            
            mongo.db.points_request.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": update_data}
            )
            
            # Award points
            points_entry = {
                "user_id": request_data.get("user_id"),
                "category_id": request_data.get("category_id"),
                "points": request_data.get("points"),
                "award_date": processed_time,
                "awarded_by": ObjectId(user_id),
                "request_id": ObjectId(request_id),
                "notes": notes
            }
            
            result = mongo.db.points.insert_one(points_entry)
            points_award = mongo.db.points.find_one({"_id": result.inserted_id})
            
            return True, "Request approved successfully", points_award
            
        except Exception as e:
            logger.error(f"Error approving request {request_id}: {e}")
            return False, f"Error: {str(e)}", None
    
    @staticmethod
    def reject_request(request_id, user_id, notes):
        """
        Reject a request
        Returns: (success, message)
        """
        try:
            processed_time = datetime.utcnow()
            
            # Get request data to get category
            request_data = RequestService.get_request_by_id(request_id)
            if not request_data:
                return False, "Request not found"
            
            # ✅ FIXED: Always set processed_department to "presales" when rejected via presales dashboard
            processed_department = "presales"
            
            # Update request status
            update_data = {
                "status": "Rejected",
                "processed_date": processed_time,
                "processed_by": ObjectId(user_id),
                "response_notes": notes,
                "manager_notes": notes,
                "processed_department": processed_department  # Always "presales" for presales rejections
            }
            
            mongo.db.points_request.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": update_data}
            )
            
            return True, "Request rejected successfully"
            
        except Exception as e:
            logger.error(f"Error rejecting request {request_id}: {e}")
            return False, f"Error: {str(e)}"
    
    @staticmethod
    def get_attachment_info(request_data):
        """Get attachment information for a request"""
        attachment_info = {
            "has_attachment": False,
            "filename": "No attachment",
            "content_type": None,
            "size": 0,
            "download_url": None,
            "is_viewable": False
        }
        
        if not request_data.get("has_attachment") or not request_data.get("attachment_id"):
            return attachment_info
        
        try:
            fs = GridFS(mongo.db)
            att_id = request_data["attachment_id"]
            
            if not isinstance(att_id, ObjectId):
                att_id = ObjectId(att_id)
            
            file_meta = fs.find_one({"_id": att_id})
            if file_meta:
                filename = file_meta.metadata.get('original_filename', file_meta.filename) if file_meta.metadata else file_meta.filename
                filename = filename or "Unnamed Attachment"
                content_type = file_meta.content_type or "application/octet-stream"
                size = file_meta.length or 0
                viewable_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf']
                is_viewable = content_type in viewable_types
                
                attachment_info.update({
                    "has_attachment": True,
                    "filename": filename,
                    "content_type": content_type,
                    "size": size,
                    "download_url": f"/presales/get_attachment/{str(request_data['_id'])}",
                    "is_viewable": is_viewable
                })
        except Exception as e:
            logger.error(f"Error fetching attachment metadata: {e}")
        
        return attachment_info
    
    @staticmethod
    def get_pending_requests(user_id, category_ids):
        """Get all pending requests for a user - filtered by presales categories only"""
        try:
            # ✅ Filter by category_ids to show ONLY presales requests
            query = {
                "status": "Pending",
                "assigned_validator_id": ObjectId(user_id)
            }
            
            # Only add category filter if category_ids are provided
            if category_ids:
                query["category_id"] = {"$in": category_ids}
            
            cursor = mongo.db.points_request.find(query).sort("request_date", -1)
            return list(cursor)
        except Exception as e:
            logger.error(f"Error fetching pending requests: {e}")
            return []
    
    @staticmethod
    def get_processed_requests(user_id, category_ids, limit=200):
        """Get processed requests history - filtered by presales categories only"""
        try:
            # ✅ Filter by category_ids to show ONLY presales requests
            query = {
                "status": {"$in": ["Approved", "Rejected"]},
                "processed_by": ObjectId(user_id)
            }
            
            # Only add category filter if category_ids are provided
            if category_ids:
                query["category_id"] = {"$in": category_ids}
            
            cursor = mongo.db.points_request.find(query).sort("processed_date", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            logger.error(f"Error fetching processed requests: {e}")
            return []
    
    @staticmethod
    def format_request_for_display(request_data, employee, category):
        """Format request data for display"""
        # For pending requests: show request_notes
        # For processed requests: show response_notes/manager_notes
        notes = (
            request_data.get("response_notes") or 
            request_data.get("manager_notes") or 
            request_data.get("request_notes") or 
            request_data.get("notes", "")
        )
        
        return {
            'id': str(request_data["_id"]),
            'employee_name': employee.get("name", "Unknown"),
            'employee_id': employee.get("employee_id", "N/A"),
            'employee_grade': employee.get("grade", ""),
            'employee_department': employee.get("department", ""),
            'category_name': category.get("name", "Unknown"),
            'title': request_data.get("title", "N/A"),
            'request_date': request_data["request_date"].strftime('%d-%m-%Y') if request_data.get("request_date") else None,
            'event_date': request_data.get("event_date"),
            'points': request_data["points"],
            'notes': notes,
            'status': request_data["status"],
            'has_attachment': request_data.get("has_attachment", False),
            'attachment_filename': request_data.get("attachment_filename", "")
        }
