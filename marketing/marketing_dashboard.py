from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import sys
import traceback
from threading import Thread

# ✅ USE UNIVERSAL REAL-TIME EVENTS
from services.realtime_events import publish_request_approved, publish_request_rejected

# ✅ IMPORT EMAIL NOTIFICATIONS (matches pmarch/presales/pm pattern)
from marketing.marketing_notifications import send_approval_notification, send_rejection_notification

# ✅ MARKETING DASHBOARD
marketing_dashboard_bp = Blueprint(
    'marketing_dashboard',
    __name__,
    url_prefix='/marketing',
    template_folder='templates',
    static_folder='static'
)

# ✅ HELPER FUNCTIONS TO HANDLE OLD & NEW DATA STRUCTURES
def get_submission_notes(request_data):
    """Get submission notes from either old or new field name"""
    return request_data.get('submission_notes') or request_data.get('request_notes', '')

def get_response_notes(request_data):
    """Get response notes from either old or new field name"""
    return request_data.get('response_notes') or request_data.get('manager_notes', '')

def get_response_date(request_data):
    """Get response date from either old or new field name"""
    return request_data.get('response_date') or request_data.get('processed_date')

def get_event_date(request_data):
    """Get event date, fallback to request_date"""
    return request_data.get('event_date') or request_data.get('request_date')

def is_marketing_request(request_data, category_data):
    """
    Check if a request belongs to MARKETING ONLY (not presales)
    Handles both old and new data structures
    """
    # Check old validator field (string)
    validator_field = request_data.get('validator', '').lower()
    
    # ✅ ONLY Marketing - exclude presales
    if validator_field == 'marketing':
        return True
    
    # ❌ Exclude presales explicitly
    if 'presales' in validator_field or 'pre-sales' in validator_field:
        return False
    
    # Check category department
    if category_data:
        category_dept = category_data.get('category_department', '').lower()
        category_validator = category_data.get('validator', '').lower()
        
        # ❌ Exclude presales
        if 'presales' in category_dept or 'pre-sales' in category_dept:
            return False
        if 'presales' in category_validator or 'pre-sales' in category_validator:
            return False
        
        # ✅ Only include marketing
        return any([
            category_dept == 'marketing',
            category_validator == 'marketing',
            'marketing' in category_dept,
            'marketing' in category_validator
        ])
    
    return False

# ✅ HELPER FUNCTION: Get marketing category IDs from BOTH collections
def get_marketing_category_ids():
    """Get marketing category IDs from both hr_categories and categories collections"""
    marketing_category_ids = set()
    
    # Get from hr_categories
    hr_marketing_categories = list(mongo.db.hr_categories.find({
        '$or': [
            {'category_department': {'$regex': 'marketing', '$options': 'i'}},
            {'validator': {'$regex': 'marketing', '$options': 'i'}}
        ]
    }))
    
    # Get from categories (old collection)
    old_marketing_categories = list(mongo.db.categories.find({
        '$or': [
            {'category_department': {'$regex': 'marketing', '$options': 'i'}},
            {'validator': {'$regex': 'marketing', '$options': 'i'}}
        ]
    }))
    
    # Combine both
    marketing_categories = hr_marketing_categories + old_marketing_categories
    marketing_category_ids = [cat['_id'] for cat in marketing_categories]
    
    return marketing_category_ids

def check_marketing_access():
    """Check if user has Marketing dashboard access"""
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    # ✅ Check for marketing access (case-insensitive, flexible matching)
    # Check for any of: 'marketing', 'Marketing', 'Marketing - Validator', 'Marketing - Updater'
    has_access = any(
        'marketing' in str(access).lower() and 'presales' not in str(access).lower()
        for access in dashboard_access
    )
    
    return has_access, user

def get_current_quarter_date_range():
    """Get current fiscal quarter date range"""
    now = datetime.utcnow()
    current_month = now.month
    current_year = now.year

    if current_month < 4:
        fiscal_year_start = current_year - 1
    else:
        fiscal_year_start = current_year

    if 4 <= current_month <= 6:
        quarter = 1
        quarter_start = datetime(fiscal_year_start, 4, 1)
        quarter_end = datetime(fiscal_year_start, 6, 30, 23, 59, 59, 999999)
    elif 7 <= current_month <= 9:
        quarter = 2
        quarter_start = datetime(fiscal_year_start, 7, 1)
        quarter_end = datetime(fiscal_year_start, 9, 30, 23, 59, 59, 999999)
    elif 10 <= current_month <= 12:
        quarter = 3
        quarter_start = datetime(fiscal_year_start, 10, 1)
        quarter_end = datetime(fiscal_year_start, 12, 31, 23, 59, 59, 999999)
    else:
        quarter = 4
        quarter_start = datetime(fiscal_year_start + 1, 1, 1)
        quarter_end = datetime(fiscal_year_start + 1, 3, 31, 23, 59, 59, 999999)

    return quarter_start, quarter_end, quarter, fiscal_year_start


@marketing_dashboard_bp.route('/dashboard')
def dashboard():
    """Marketing dashboard - stats and overview"""
    has_access, user = check_marketing_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    # ✅ Check if user still has marketing dashboard access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    has_marketing_access = any('marketing' in str(access).lower() and 'presales' not in str(access).lower() for access in dashboard_access)
    if not has_marketing_access:
        flash('You no longer have access to the Marketing dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        quarter_start, quarter_end, current_quarter, current_year = get_current_quarter_date_range()
        
        # ✅ Get marketing category IDs from BOTH collections
        marketing_category_ids = get_marketing_category_ids()
        
        # ✅ Get ONLY marketing pending requests count
        query = {
            'assigned_validator_id': ObjectId(user['_id']),
            'status': 'Pending'
        }
        
        # Add category filter if marketing categories exist
        if marketing_category_ids:
            query['category_id'] = {'$in': marketing_category_ids}
        
        pending_count = mongo.db.points_request.count_documents(query)
        
        # Get stats
        
        stats_filter = {}
        if marketing_category_ids:
            stats_filter = {'category_id': {'$in': marketing_category_ids}}
        
        # If no marketing categories found, still show stats but they'll be 0
        processed_this_quarter = 0
        approved_this_quarter = 0
        total_points_awarded = 0
        
        if marketing_category_ids:
            processed_this_quarter = mongo.db.points_request.count_documents({
                'status': {'$in': ['Approved', 'Rejected']},
                'processed_by': ObjectId(user['_id']),
                '$or': [
                    {'response_date': {'$gte': quarter_start, '$lte': quarter_end}},
                    {'processed_date': {'$gte': quarter_start, '$lte': quarter_end}}
                ],
                **stats_filter
            })
            
            approved_this_quarter = mongo.db.points_request.count_documents({
                'status': 'Approved',
                'processed_by': ObjectId(user['_id']),
                '$or': [
                    {'response_date': {'$gte': quarter_start, '$lte': quarter_end}},
                    {'processed_date': {'$gte': quarter_start, '$lte': quarter_end}}
                ],
                **stats_filter
            })
            
            # Calculate total points awarded this quarter
            total_points_pipeline = [
                {
                    '$match': {
                        'status': 'Approved',
                        'processed_by': ObjectId(user['_id']),
                        '$or': [
                            {'response_date': {'$gte': quarter_start, '$lte': quarter_end}},
                            {'processed_date': {'$gte': quarter_start, '$lte': quarter_end}}
                        ],
                        **stats_filter
                    }
                },
                {
                    '$group': {
                        '_id': None,
                        'total_points': {'$sum': '$points'}
                    }
                }
            ]
            
            total_points_result = list(mongo.db.points_request.aggregate(total_points_pipeline))
            total_points_awarded = total_points_result[0]['total_points'] if total_points_result else 0
        
        # ✅ Get ALL pending requests for dashboard display (not filtered by category)
        pending_requests_list = []
        pending_cursor = mongo.db.points_request.find(query).sort('request_date', -1).limit(5)
        
        for req in pending_cursor:
            category = mongo.db.hr_categories.find_one({'_id': req.get('category_id')})
            if not category:
                category = mongo.db.categories.find_one({'_id': req.get('category_id')})
            
            if category:
                employee = mongo.db.users.find_one({'_id': req.get('user_id')})
                if employee:
                    pending_requests_list.append({
                        'id': str(req['_id']),
                        'employee_name': employee.get('name', 'Unknown'),
                        'employee_grade': employee.get('grade', 'N/A'),
                        'category_name': category.get('name', 'Unknown'),
                        'points': req.get('points', 0),
                        'request_date': req.get('request_date')
                    })
        
        # ✅ Get ONLY marketing recent activity (filtered by category)
        all_records = []
        history_query = {
            'status': {'$in': ['Approved', 'Rejected']},
            'processed_by': ObjectId(user['_id'])
        }
        
        # Add category filter if marketing categories exist
        if marketing_category_ids:
            history_query['category_id'] = {'$in': list(marketing_category_ids)}
        
        history_cursor = mongo.db.points_request.find(history_query).sort([('response_date', -1), ('processed_date', -1)]).limit(10)
        
        for req in history_cursor:
            category = mongo.db.hr_categories.find_one({'_id': req.get('category_id')})
            if not category:
                category = mongo.db.categories.find_one({'_id': req.get('category_id')})
            
            if category:
                employee = mongo.db.users.find_one({'_id': req['user_id']})
                if employee:
                    all_records.append({
                        'id': str(req['_id']),
                        'employee_name': employee.get('name', 'Unknown'),
                        'category_name': category.get('name', 'Unknown'),
                        'points': req['points'],
                        'processed_date': get_response_date(req),
                        'status': req['status'],
                        'type': 'Request'
                    })
        
        return render_template(
            'marketing_dashboard_home.html',
            user=user,
            pending_count=pending_count,
            pending_requests=pending_requests_list,
            processed_this_quarter=processed_this_quarter,
            approved_this_quarter=approved_this_quarter,
            total_points_awarded=total_points_awarded,
            all_records=all_records,
            current_quarter=f"Q{current_quarter}",
            current_year=current_year,
            current_month=datetime.utcnow().strftime("%B")
        )
    
    except Exception:
        flash('An error occurred while loading the dashboard', 'danger')
        return redirect(url_for('auth.login'))


@marketing_dashboard_bp.route('/pending-requests')
def pending_requests():
    """Marketing pending requests - table view only"""
    has_access, user = check_marketing_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login', next=request.url))
    
    # ✅ Check if user still has marketing dashboard access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    has_marketing_access = any('marketing' in str(access).lower() and 'presales' not in str(access).lower() for access in dashboard_access)
    if not has_marketing_access:
        flash('You no longer have access to the Marketing dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        quarter_start, quarter_end, current_quarter, current_year = get_current_quarter_date_range()
        
        # ✅ Get marketing category IDs from BOTH collections
        marketing_category_ids = get_marketing_category_ids()
        
        # ✅ Get ONLY marketing pending requests assigned to this validator
        query = {
            'assigned_validator_id': ObjectId(user['_id']),
            'status': 'Pending'
        }
        
        # Add category filter if marketing categories exist
        if marketing_category_ids:
            query['category_id'] = {'$in': marketing_category_ids}
        
        all_requests_cursor = mongo.db.points_request.find(query).sort('request_date', -1)
        
        pending_requests_list = []
        
        # ✅ Include ONLY marketing requests assigned to this validator
        for req in all_requests_cursor:
            # Get the category
            category = mongo.db.hr_categories.find_one({'_id': req.get('category_id')})
            if not category:
                category = mongo.db.categories.find_one({'_id': req.get('category_id')})
            
            if not category:
                continue
            
            # Get employee
            employee = mongo.db.users.find_one({'_id': req.get('user_id')})
            
            if employee:
                # ✅ HANDLE BOTH OLD AND NEW FIELD NAMES
                pending_requests_list.append({
                    'id': str(req['_id']),
                    'employee_name': employee.get('name', 'Unknown'),
                    'employee_id': employee.get('employee_id', 'N/A'),
                    'employee_grade': employee.get('grade', 'N/A'),
                    'category_name': category.get('name', 'Unknown'),
                    'points': req.get('points', 0),
                    'request_date': req.get('request_date'),
                    'notes': get_submission_notes(req),  # ✅ Handles both old & new
                    'has_attachment': req.get('has_attachment', False),
                    'attachment_filename': req.get('attachment_filename', ''),
                    'attachment_id': str(req.get('attachment_id')) if req.get('attachment_id') else None
                })
        
        return render_template(
            'marketing_pending_requests.html',
            user=user,
            pending_requests=pending_requests_list,
            pending_count=len(pending_requests_list),
            current_quarter=f"Q{current_quarter}",
            current_year=current_year,
            current_month=datetime.utcnow().strftime("%B")
        )
    
    except Exception:
        flash('An error occurred while loading pending requests', 'danger')
        return redirect(url_for('auth.login'))


# Root route redirects to dashboard
@marketing_dashboard_bp.route('/')
def index():
    return redirect(url_for('marketing_dashboard.dashboard'))


@marketing_dashboard_bp.route('/process-request/<request_id>', methods=['POST'])
def process_request(request_id):
    """Process (approve/reject) a request"""
    has_access, user = check_marketing_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        points_request = mongo.db.points_request.find_one({'_id': ObjectId(request_id)})
        
        if not points_request:
            flash('Request not found', 'danger')
            return redirect(url_for('marketing_dashboard.pending_requests'))
        
        # Verify request is assigned to this validator
        if str(points_request.get('assigned_validator_id')) != str(user['_id']):
            flash('You are not authorized to process this request', 'danger')
            return redirect(url_for('marketing_dashboard.pending_requests'))
        
        # Get employee and category
        employee = mongo.db.users.find_one({'_id': points_request['user_id']})
        category = mongo.db.hr_categories.find_one({'_id': points_request['category_id']})
        if not category:
            category = mongo.db.categories.find_one({'_id': points_request['category_id']})
        
        if not employee or not category:
            flash('Employee or category not found', 'danger')
            return redirect(url_for('marketing_dashboard.pending_requests'))
        
        # Get action and notes
        action = request.form.get('action')
        notes = request.form.get('notes', '')
        
        if action not in ['approve', 'reject']:
            flash('Invalid action', 'danger')
            return redirect(url_for('marketing_dashboard.pending_requests'))
        
        # Update request
        processed_time = datetime.utcnow()
        
        update_data = {
            'status': 'Approved' if action == 'approve' else 'Rejected',
            'response_date': processed_time,
            'processed_by': ObjectId(user['_id']),
            'response_notes': notes
        }
        
        mongo.db.points_request.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': update_data}
        )
        
        # ✅ CREATE POINTS AWARD IF APPROVED
        points_award = None
        if action == 'approve':
            points_award = {
                '_id': ObjectId(),
                'user_id': points_request['user_id'],
                'category_id': points_request['category_id'],
                'points': points_request['points'],
                'award_date': processed_time,
                'awarded_by': ObjectId(user['_id']),
                'notes': notes,
                'request_id': ObjectId(request_id)
            }
            
            mongo.db.points.insert_one(points_award)
            
            # ✅ PUBLISH APPROVAL EVENT
            try:
                publish_request_approved(
                    request_data=update_data | {
                        '_id': ObjectId(request_id), 
                        'category_id': points_request['category_id'], 
                        'points': points_request['points'], 
                        'created_by_ta_id': points_request.get('created_by_ta_id'),
                        'created_by': points_request.get('created_by')
                    },
                    employee_data=employee,
                    approver_data=user,
                    points_award_data=points_award
                )
            except Exception:
                pass
            
            # ✅ Update points_request with response_notes for email (matches pmarch/presales/pm pattern)
            points_request["response_notes"] = notes
            
            # ✅ Send email notifications asynchronously (non-blocking) - matches pmarch/presales/pm
            Thread(target=send_approval_notification, args=(
                points_request, employee, user, category
            ), daemon=True).start()
            
            flash(f'Request approved! {points_request["points"]} points awarded to {employee.get("name", "employee")}', 'success')
        else:
            # ✅ PUBLISH REJECTION EVENT
            try:
                publish_request_rejected(
                    request_data=update_data | {
                        '_id': ObjectId(request_id), 
                        'category_id': points_request['category_id'], 
                        'points': points_request['points'], 
                        'created_by_ta_id': points_request.get('created_by_ta_id'),
                        'created_by': points_request.get('created_by')
                    },
                    employee_data=employee,
                    rejector_data=user
                )
            except Exception:
                pass
            
            # ✅ Update points_request with response_notes for email (matches pmarch/presales/pm pattern)
            points_request["response_notes"] = notes
            
            # ✅ Send email notifications asynchronously (non-blocking) - matches pmarch/presales/pm
            Thread(target=send_rejection_notification, args=(
                points_request, employee, user, category
            ), daemon=True).start()
            
            flash('Request rejected', 'warning')
        
        return redirect(url_for('marketing_dashboard.pending_requests'))
        
    except Exception:
        flash('An error occurred while processing the request', 'danger')
        return redirect(url_for('marketing_dashboard.pending_requests'))


@marketing_dashboard_bp.route('/processed-requests')
def processed_requests():
    """Show processed requests history"""
    has_access, user = check_marketing_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    # ✅ Check if user still has marketing dashboard access
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    has_marketing_access = any('marketing' in str(access).lower() and 'presales' not in str(access).lower() for access in dashboard_access)
    if not has_marketing_access:
        flash('You no longer have access to the Marketing dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        quarter_start, quarter_end, current_quarter, current_year = get_current_quarter_date_range()
        
        # ✅ Get marketing category IDs from BOTH collections
        marketing_category_ids = get_marketing_category_ids()
        
        # ✅ Get ONLY marketing processed requests by this user
        processed_query = {
            'status': {'$in': ['Approved', 'Rejected']},
            'processed_by': ObjectId(user['_id'])
        }
        
        # Add category filter if marketing categories exist
        if marketing_category_ids:
            processed_query['category_id'] = {'$in': marketing_category_ids}
        
        all_processed_cursor = mongo.db.points_request.find(processed_query).sort([
            ('response_date', -1),
            ('processed_date', -1)
        ])
        
        processed_requests = []
        
        # ✅ Include ONLY marketing processed requests
        for req in all_processed_cursor:
            # Get the category
            category = mongo.db.hr_categories.find_one({'_id': req.get('category_id')})
            if not category:
                category = mongo.db.categories.find_one({'_id': req.get('category_id')})
            
            if not category:
                continue
            
            # Get employee
            employee = mongo.db.users.find_one({'_id': req['user_id']})
            
            if employee:
                # ✅ HANDLE BOTH OLD AND NEW FIELD NAMES
                processed_requests.append({
                    'id': str(req['_id']),
                    'employee_name': employee.get('name', 'Unknown'),
                    'employee_id': employee.get('employee_id', 'N/A'),
                    'employee_grade': employee.get('grade', 'Unknown'),
                    'category_name': category.get('name', 'Unknown'),
                    'points': req['points'],
                    'request_date': req.get('request_date'),
                    'processed_date': get_response_date(req),  # ✅ Handles both old & new
                    'status': req['status'],
                    'response_notes': get_response_notes(req),  # ✅ Handles both old & new
                    'has_attachment': req.get('has_attachment', False),
                    'attachment_id': str(req.get('attachment_id')) if req.get('attachment_id') else None
                })
        
        # ✅ Get pending count (only marketing categories)
        pending_query = {
            'assigned_validator_id': ObjectId(user['_id']),
            'status': 'Pending'
        }
        
        # Add category filter if marketing categories exist
        if marketing_category_ids:
            pending_query['category_id'] = {'$in': marketing_category_ids}
        
        pending_count = mongo.db.points_request.count_documents(pending_query)
        
        return render_template(
            'marketing_processed_requests.html',
            user=user,
            processed_requests=processed_requests,
            current_quarter=f"Q{current_quarter}",
            current_year=current_year,
            current_month=datetime.utcnow().strftime("%B"),
            pending_count=pending_count
        )
        
    except Exception:
        flash("An error occurred while loading processed requests", "danger")
        return redirect(url_for('marketing_dashboard.dashboard'))


@marketing_dashboard_bp.route('/get_attachment/<request_id>')
def get_attachment(request_id):
    """Download attachment"""
    from gridfs import GridFS
    from flask import send_file
    import io
    
    has_access, user = check_marketing_access()
    if not has_access:
        flash('Please log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    try:
        req = mongo.db.points_request.find_one({'_id': ObjectId(request_id)})
        if not req or not req.get('has_attachment'):
            flash('Attachment not found', 'warning')
            return redirect(url_for('marketing_dashboard.dashboard'))
        
        fs = GridFS(mongo.db)
        attachment_id = req.get('attachment_id')
        if isinstance(attachment_id, str):
            attachment_id = ObjectId(attachment_id)
        
        if not fs.exists(attachment_id):
            flash('Attachment file not found', 'warning')
            return redirect(url_for('marketing_dashboard.dashboard'))
        
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
    
    except Exception:
        flash('Error downloading attachment', 'danger')
        return redirect(url_for('marketing_dashboard.dashboard'))


@marketing_dashboard_bp.route('/search-employees')
def search_employees():
    """Search for employees to raise requests for"""
    has_access, user = check_marketing_access()
    if not has_access:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        search_term = request.args.get('q', '').strip()
        if len(search_term) < 2:
            return jsonify({'employees': []})
        
        # Search for active employees
        query = {
            'role': {'$regex': '^Employee$', '$options': 'i'},
            'is_active': True,
            '$or': [
                {'name': {'$regex': search_term, '$options': 'i'}},
                {'employee_id': {'$regex': search_term, '$options': 'i'}},
                {'email': {'$regex': search_term, '$options': 'i'}}
            ]
        }
        
        employees = list(mongo.db.users.find(query).limit(10))
        
        result = []
        for emp in employees:
            result.append({
                'id': str(emp['_id']),
                'name': emp.get('name', 'Unknown'),
                'employee_id': emp.get('employee_id', 'N/A'),
                'grade': emp.get('grade', 'N/A'),
                'department': emp.get('department', 'N/A')
            })
        
        return jsonify({'employees': result})
    
    except Exception:
        return jsonify({'error': 'Search failed'}), 500


@marketing_dashboard_bp.route('/employees')
def employees():
    """View all employees with their marketing points"""
    has_access, user = check_marketing_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        quarter_start, quarter_end, current_quarter, current_year = get_current_quarter_date_range()
        
        # ✅ Get marketing category IDs from BOTH collections
        marketing_category_ids = get_marketing_category_ids()
        
        # Get all active employees
        employees_cursor = mongo.db.users.find({
            'role': {'$regex': '^Employee$', '$options': 'i'},
            'is_active': True
        }).sort('name', 1)
        
        employees_list = []
        for emp in employees_cursor:
            # Skip current user
            if str(emp['_id']) == str(user['_id']):
                continue
            
            # Calculate total points
            total_points = 0
            points_cursor = mongo.db.points.find({'user_id': emp['_id']})
            for point in points_cursor:
                total_points += point.get('points', 0)
            
            # Calculate quarterly marketing points
            quarter_points = 0
            if marketing_category_ids:
                quarter_points_cursor = mongo.db.points.find({
                    'user_id': emp['_id'],
                    'category_id': {'$in': marketing_category_ids},
                    'award_date': {'$gte': quarter_start, '$lte': quarter_end}
                })
                for point in quarter_points_cursor:
                    quarter_points += point.get('points', 0)
            
            # Get pending requests count
            pending_count = mongo.db.points_request.count_documents({
                'user_id': emp['_id'],
                'status': 'Pending',
                'assigned_validator_id': user['_id']
            })
            
            employees_list.append({
                'id': str(emp['_id']),
                'name': emp.get('name', 'Unknown'),
                'employee_id': emp.get('employee_id', 'N/A'),
                'grade': emp.get('grade', 'N/A'),
                'department': emp.get('department', 'N/A'),
                'total_points': total_points,
                'quarter_points': quarter_points,
                'pending_requests': pending_count
            })
        
        # Get pending count for sidebar
        pending_query = {
            'assigned_validator_id': ObjectId(user['_id']),
            'status': 'Pending'
        }
        all_pending = mongo.db.points_request.find(pending_query)
        pending_count = 0
        for req in all_pending:
            category = mongo.db.hr_categories.find_one({'_id': req.get('category_id')})
            if not category:
                category = mongo.db.categories.find_one({'_id': req.get('category_id')})
            if category and is_marketing_request(req, category):
                pending_count += 1
        
        return render_template(
            'marketing_employees.html',
            user=user,
            employees=employees_list,
            pending_count=pending_count,
            current_quarter=f"Q{current_quarter}",
            current_year=current_year,
            current_month=datetime.utcnow().strftime("%B")
        )
    
    except Exception:
        flash('An error occurred while loading employees', 'danger')
        return redirect(url_for('marketing_dashboard.dashboard'))


@marketing_dashboard_bp.route('/raise-request', methods=['POST'])
def raise_request():
    """Raise a points request for an employee"""
    has_access, user = check_marketing_access()
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get form data
        employee_id = request.form.get('employee_id')
        category_id = request.form.get('category_id')
        points = request.form.get('points')
        notes = request.form.get('notes', '').strip()
        
        if not all([employee_id, category_id, points, notes]):
            flash('All fields are required', 'danger')
            return redirect(url_for('marketing_dashboard.dashboard'))
        
        # Validate employee
        employee = mongo.db.users.find_one({'_id': ObjectId(employee_id)})
        if not employee:
            flash('Employee not found', 'danger')
            return redirect(url_for('marketing_dashboard.dashboard'))
        
        # Validate category
        category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        if not category:
            category = mongo.db.categories.find_one({'_id': ObjectId(category_id)})
        
        if not category:
            flash('Category not found', 'danger')
            return redirect(url_for('marketing_dashboard.dashboard'))
        
        # Handle file attachment
        attachment_id = None
        attachment_filename = None
        has_attachment = False
        
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename:
                from gridfs import GridFS
                from werkzeug.utils import secure_filename
                
                fs = GridFS(mongo.db)
                filename = secure_filename(file.filename)
                
                # Store file in GridFS
                attachment_id = fs.put(
                    file,
                    filename=filename,
                    content_type=file.content_type,
                    metadata={'original_filename': filename}
                )
                attachment_filename = filename
                has_attachment = True
        
        # Create the request
        request_data = {
            'user_id': ObjectId(employee_id),
            'category_id': ObjectId(category_id),
            'points': int(points),
            'status': 'Pending',
            'request_date': datetime.utcnow(),
            'request_notes': notes,
            'submission_notes': notes,
            'assigned_validator_id': ObjectId(user['_id']),
            'created_by_marketing_id': ObjectId(user['_id']),
            'raised_by_manager': True,
            'has_attachment': has_attachment
        }
        
        if has_attachment:
            request_data['attachment_id'] = attachment_id
            request_data['attachment_filename'] = attachment_filename
        
        result = mongo.db.points_request.insert_one(request_data)
        
        # ✅ Publish real-time event to notify validator
        try:
            from services.realtime_events import publish_request_raised
            publish_request_raised(
                request_data={'_id': result.inserted_id, **request_data},
                employee_data=employee,
                validator_data=user,  # ✅ FIXED: Use 'user' (the current marketing manager) as the validator
                category_data=category
            )
        except Exception as e:
            # Log the error but don't fail the request
            import traceback
            traceback.print_exc()
            pass
        
        flash(f'Points request raised successfully for {employee.get("name")}!', 'success')
        return redirect(url_for('marketing_dashboard.dashboard'))
    
    except Exception:
        flash('An error occurred while raising the request', 'danger')
        return redirect(url_for('marketing_dashboard.dashboard'))


@marketing_dashboard_bp.route('/api/pending-count', methods=['GET'])
def api_pending_count():
    """API endpoint to get current pending request count"""
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'count': 0}), 200
    
    try:
        # ✅ Get marketing category IDs from BOTH collections
        marketing_category_ids = get_marketing_category_ids()
        
        # Count pending requests assigned to this validator
        query = {
            'assigned_validator_id': ObjectId(user_id),
            'status': 'Pending'
        }
        
        # Add category filter if marketing categories exist
        if marketing_category_ids:
            query['category_id'] = {'$in': marketing_category_ids}
        
        pending_count = mongo.db.points_request.count_documents(query)
        
        return jsonify({'count': pending_count}), 200
        
    except Exception:
        return jsonify({'count': 0}), 200
