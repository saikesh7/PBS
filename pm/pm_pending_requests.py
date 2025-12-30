from flask import render_template, request, session, redirect, url_for, flash
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import sys
from .pm_main import pm_bp

# ✅ IMPORT REAL-TIME PUBLISHER
from services.realtime_events import publish_request_approved, publish_request_rejected

def error_print(message, error=None):
    pass

def check_pm_access():
    """Check if user has PM dashboard access"""
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    return 'pm' in dashboard_access, user

def get_fiscal_quarter_for_date(date):
    """Calculate fiscal quarter for a given date"""
    if not date:
        return ""
    
    month = date.month
    
    if 4 <= month <= 6:
        return "Q1"
    elif 7 <= month <= 9:
        return "Q2"
    elif 10 <= month <= 12:
        return "Q3"
    else:  # 1-3
        return "Q4"

@pm_bp.route('/pending-requests')
def pending_requests():
    """Show pending requests assigned to this PM"""

    has_access, user = check_pm_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get ALL PM categories from hr_categories
        pm_categories = list(mongo.db.hr_categories.find({
            "category_department": "pm",
            "category_status": "active"
        }))
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        if not pm_category_ids:
            flash('PM categories not found. Please contact HR.', 'warning')
        
        # Fetch pending requests - ONLY PM category requests assigned to this PM
        pending_requests = []
        pending_cursor = mongo.db.points_request.find({
            "status": "Pending",
            "category_id": {"$in": pm_category_ids},  # ✅ Only PM categories
            "$or": [
                {"assigned_validator_id": ObjectId(user["_id"])},  # New field name
                {"pending_validator_id": ObjectId(user["_id"])},   # Old field name
                {"pm_id": ObjectId(user["_id"])}                   # Very old field name
            ]
        }).sort("request_date", -1)
        
        # Debug logging
        cursor_list = list(pending_cursor)

        for req_data in cursor_list:
            employee = mongo.db.users.find_one({"_id": req_data.get("user_id")})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            if not employee or not category:
                continue
            
            pending_requests.append({
                'id': str(req_data["_id"]),
                'employee_name': employee.get("name", "Unknown"),
                'employee_id': employee.get("employee_id", "N/A"),
                'employee_grade': employee.get("grade", "Unknown"),
                'category_name': category.get("name", "Unknown"),
                'points': req_data["points"],
                'request_date': req_data["request_date"].strftime('%d-%m-%Y') if req_data.get("request_date") else 'N/A',
                'notes': req_data.get("submission_notes", req_data.get("request_notes", "")),
                'has_attachment': req_data.get("has_attachment", False),
                'attachment_filename': req_data.get("attachment_filename", ""),
                'attachment_id': str(req_data.get("attachment_id")) if req_data.get("attachment_id") else None
            })
        
        # ✅ CALCULATE PENDING COUNT
        pending_count = len(pending_requests)
        
        # Format quarter and month display like pmarch
        now = datetime.utcnow()
        current_month = now.month
        current_year = now.year
        
        # Calculate fiscal year
        if current_month < 4:
            fiscal_year_start = current_year - 1
        else:
            fiscal_year_start = current_year
        
        # Calculate quarter
        if 4 <= current_month <= 6:
            quarter = 1
        elif 7 <= current_month <= 9:
            quarter = 2
        elif 10 <= current_month <= 12:
            quarter = 3
        else:
            quarter = 4
        
        fiscal_year_end = fiscal_year_start + 1
        display_quarter = f"Q{quarter} FY{fiscal_year_start}-{str(fiscal_year_end)[-2:]}"
        display_month = now.strftime("%b %Y").upper()
        
        # ✅ PASS ALL REQUIRED VARIABLES
        return render_template(
            'pm_pending_requests.html', 
            user=user,
            pending_requests=pending_requests,
            pending_count=pending_count,
            display_quarter=display_quarter,
            display_month=display_month,
            current_quarter=f"Q{quarter}",
            current_year=fiscal_year_start,
            current_month=now.strftime("%B")
        )
                             
    except Exception as e:
        error_print("Error loading pending requests", e)
        flash("An error occurred while loading requests", "danger")
        return redirect(url_for('pm.dashboard'))

@pm_bp.route('/process-request/<request_id>', methods=['POST'])
def process_request(request_id):
    """Process (approve/reject) a pending request"""
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        points_request = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        
        if not points_request:
            flash('Request not found', 'danger')
            return redirect(url_for('pm.pending_requests'))
        
        # Verify request is assigned to this PM (check all possible field names)
        assigned_validator = (
            points_request.get("assigned_validator_id") or 
            points_request.get("pending_validator_id") or 
            points_request.get("pm_id")
        )
        if str(assigned_validator) != str(user["_id"]):
            flash('You are not authorized to process this request', 'danger')
            return redirect(url_for('pm.pending_requests'))
        
        # Get employee and category data
        employee = mongo.db.users.find_one({"_id": points_request["user_id"]})
        
        # Try to get category from hr_categories first, then fall back to old categories collection
        category = mongo.db.hr_categories.find_one({"_id": points_request["category_id"]})
        if not category:
            category = mongo.db.categories.find_one({"_id": points_request["category_id"]})
        
        if not employee or not category:
            flash('Employee or category not found', 'danger')
            return redirect(url_for('pm.pending_requests'))
        
        # Get action and notes
        action = request.form.get('action')
        notes = request.form.get('notes', '')
        
        if action not in ['approve', 'reject']:
            flash('Invalid action', 'danger')
            return redirect(url_for('pm.pending_requests'))
        
        # Update request
        processed_time = datetime.utcnow()
        
        update_data = {
            "status": "Approved" if action == 'approve' else "Rejected",
            "processed_date": processed_time,
            "processed_by": ObjectId(user["_id"]),
            "response_notes": notes
        }
        
        mongo.db.points_request.update_one(
            {"_id": ObjectId(request_id)},
            {"$set": update_data}
        )
        
        # ✅ CREATE POINTS AWARD IF APPROVED
        points_award = None
        if action == 'approve':
            # Get fiscal quarter
            quarter = get_fiscal_quarter_for_date(processed_time)
            year = processed_time.year if processed_time.month >= 4 else processed_time.year - 1
            
            # Create points entry
            points_award = {
                "_id": ObjectId(),
                "user_id": points_request["user_id"],
                "category_id": points_request["category_id"],
                "points": points_request["points"],
                "award_date": processed_time,
                "awarded_by": ObjectId(user["_id"]),
                "notes": notes,
                "request_id": ObjectId(request_id),
                "quarter": quarter,
                "year": year
            }
            
            mongo.db.points.insert_one(points_award)
            
            # ✅ PUBLISH APPROVAL EVENT
            publish_request_approved(
                request_data=update_data | {"_id": ObjectId(request_id), "category_id": points_request["category_id"], "points": points_request["points"], "created_by_ta_id": points_request.get("created_by_ta_id")},
                employee_data=employee,
                approver_data=user,
                points_award_data=points_award
            )
            
            flash(f'Request approved! {points_request["points"]} points awarded to {employee.get("name", "employee")}', 'success')
        else:
            # ✅ PUBLISH REJECTION EVENT
            publish_request_rejected(
                request_data=update_data | {"_id": ObjectId(request_id), "category_id": points_request["category_id"], "points": points_request["points"], "created_by_ta_id": points_request.get("created_by_ta_id")},
                employee_data=employee,
                rejector_data=user
            )
            
            flash('Request rejected', 'warning')
        
        return redirect(url_for('pm.pending_requests'))
        
    except Exception as e:
        error_print(f"Error processing request {request_id}", e)
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('pm.pending_requests'))

@pm_bp.route('/processed-requests')
def processed_requests():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get PM categories
        pm_categories = list(mongo.db.hr_categories.find({
            "category_department": "pm",
            "category_status": "active"
        }))
        
        pm_category_ids = [cat["_id"] for cat in pm_categories]
        
        # Get processed requests - ONLY PM categories
        processed_requests = []
        processed_cursor = mongo.db.points_request.find({
            "status": {"$in": ["Approved", "Rejected"]},
            "category_id": {"$in": pm_category_ids},  # ✅ Only PM categories
            "processed_by": ObjectId(user["_id"])
        }).sort("processed_date", -1)
        
        for req in processed_cursor:
            employee = mongo.db.users.find_one({"_id": req["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req.get("category_id")})
            
            if employee and category:
                processed_date = req.get("processed_date")
                quarter = get_fiscal_quarter_for_date(processed_date) if processed_date else ""
                
                processed_requests.append({
                    'id': str(req["_id"]),
                    'employee_id': str(req["user_id"]),
                    'employee_name': employee.get("name", "Unknown"),
                    'employee_grade': employee.get("grade", "Unknown"),
                    'employee_department': employee.get("department", ""),
                    'category_name': category.get("name", "Unknown"),
                    'title': req.get("title", "N/A"),
                    'points': req["points"],
                    'request_date': req.get("request_date"),
                    'processed_date': processed_date,
                    'status': req["status"],
                    'response_notes': req.get("response_notes", ""),
                    'manager_notes': req.get("manager_notes", ""),
                    'notes': req.get("response_notes") or req.get("manager_notes") or req.get("notes", ""),
                    'quarter': quarter,
                    'has_attachment': req.get('has_attachment', False),
                    'attachment_filename': req.get('attachment_filename', ''),
                    'attachment_id': str(req.get('attachment_id')) if req.get('attachment_id') else None
                })
        
        # ✅ GET PENDING COUNT FOR BADGE - ONLY PM categories
        pending_count = mongo.db.points_request.count_documents({
            "status": "Pending",
            "category_id": {"$in": pm_category_ids},  # ✅ Only PM categories
            "$or": [
                {"assigned_validator_id": ObjectId(user["_id"])},  # New field name
                {"pending_validator_id": ObjectId(user["_id"])},   # Old field name
                {"pm_id": ObjectId(user["_id"])}                   # Very old field name
            ]
        })
        
        # Format quarter and month display like pmarch
        now = datetime.utcnow()
        current_month = now.month
        current_year = now.year
        
        # Calculate fiscal year
        if current_month < 4:
            fiscal_year_start = current_year - 1
        else:
            fiscal_year_start = current_year
        
        # Calculate quarter
        if 4 <= current_month <= 6:
            quarter = 1
        elif 7 <= current_month <= 9:
            quarter = 2
        elif 10 <= current_month <= 12:
            quarter = 3
        else:
            quarter = 4
        
        fiscal_year_end = fiscal_year_start + 1
        display_quarter = f"Q{quarter} FY{fiscal_year_start}-{str(fiscal_year_end)[-2:]}"
        display_month = now.strftime("%b %Y").upper()
        
        return render_template(
            'pm_processed_requests.html',
            user=user,
            processed_requests=processed_requests,
            display_quarter=display_quarter,
            display_month=display_month,
            current_quarter=f"Q{quarter}",
            current_year=fiscal_year_start,
            current_month=now.strftime("%B"),
            pending_count=pending_count
        )
        
    except Exception as e:
        error_print("Error loading processed requests", e)
        flash("An error occurred while loading processed requests", "danger")
        return redirect(url_for('pm.dashboard'))