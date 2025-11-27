from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, send_file, flash
from extensions import mongo
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from gridfs import GridFS
import io
import traceback

employee_points_total_bp = Blueprint(
    'employee_points_total', 
    __name__, 
    url_prefix='/employee',
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

def get_category_for_employee(category_id):
    """
    Fetch category for employee data with robust error handling
    Priority: hr_categories (new data) → categories (old data)
    """
    if not category_id:
        return None
    
    try:
        # Convert to ObjectId if string
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
        
        # Try hr_categories FIRST (where new employee categories are stored)
        category = mongo.db.hr_categories.find_one({'_id': category_id})
        if category:
            return category
        
        # Fallback to categories (where old employee categories were stored)
        category = mongo.db.categories.find_one({'_id': category_id})
        if category:
            return category
        
        return None
        
    except Exception as e:
        return None

def is_utilization_category(category):
    """Check if category is utilization/billable"""
    if not category:
        return False
    
    category_name = category.get('name', '').lower()
    category_code = category.get('code', '').lower()
    
    return 'utilization' in category_name or 'billable' in category_name or category_code == 'utilization_billable'

# ✅ HELPER FUNCTION: Get effective date with error handling
def get_effective_date(entry):
    """Priority: event_date > request_date > award_date"""
    try:
        event_date = entry.get('event_date')
        if event_date and isinstance(event_date, datetime):
            return event_date
        
        request_date = entry.get('request_date')
        if request_date and isinstance(request_date, datetime):
            return request_date
        
        award_date = entry.get('award_date')
        if award_date and isinstance(award_date, datetime):
            return award_date
        
        return None
    except Exception as e:
        return None

# ✅ HELPER FUNCTION: Get fiscal quarter from date
def get_fiscal_quarter_year(date_obj):
    """
    Returns fiscal quarter and year (April-March)
    Q1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar
    """
    if not date_obj or not isinstance(date_obj, datetime):
        return None, None
    
    try:
        month = date_obj.month
        year = date_obj.year
        
        if 1 <= month <= 3:
            quarter = 4
            fiscal_year = year - 1
        elif 4 <= month <= 6:
            quarter = 1
            fiscal_year = year
        elif 7 <= month <= 9:
            quarter = 2
            fiscal_year = year
        else:  # 10-12
            quarter = 3
            fiscal_year = year
        
        return quarter, fiscal_year
    except Exception as e:
        return None, None

@employee_points_total_bp.route('/points-total')
def points_total():
    """Total points history page - Using HR Analytics Logic"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return redirect(url_for('auth.login'))
    
    # Initialize totals
    total_points = 0
    total_bonus_points = 0
    request_history = []
    
    try:
        # ============================================
        # SIMPLE APPROACH: Get ALL points from points collection (like HR Analytics)
        # ============================================
        
        # Get utilization category IDs to exclude from totals
        utilization_category_ids = []
        util_cat_hr = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
        if util_cat_hr:
            utilization_category_ids.append(util_cat_hr["_id"])
        util_cat_old = mongo.db.categories.find_one({"code": "utilization_billable"})
        if util_cat_old:
            utilization_category_ids.append(util_cat_old["_id"])
        
        # Query ALL points for this user
        points_entries = list(mongo.db.points.find({
            'user_id': ObjectId(user_id)
        }).sort('award_date', -1))
        
        for point in points_entries:
            try:
                point_id = str(point['_id'])
                category_id = point.get('category_id')
                points_value = point.get('points', 0)
                
                # Fetch category
                category = get_category_for_employee(category_id)
                category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
                
                # Check if utilization
                is_utilization = is_utilization_category(category)
                
                # Check if bonus
                is_bonus = point.get('is_bonus', False)
                if category and category.get('is_bonus'):
                    is_bonus = True
                
                # ✅ COUNT POINTS (like HR Analytics does)
                if isinstance(points_value, (int, float)):
                    if is_bonus:
                        total_bonus_points += points_value
                    elif not is_utilization:
                        total_points += points_value
                
                # Get display value
                display_value = points_value
                utilization_percentage = None
                
                if is_utilization:
                    # Try to get utilization percentage
                    point_request_id = point.get('request_id')
                    if point_request_id:
                        try:
                            original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                            if original_request and 'utilization_value' in original_request:
                                utilization_value = original_request.get('utilization_value', 0)
                                utilization_percentage = round(utilization_value * 100, 2)
                                display_value = f"{utilization_percentage}%"
                        except:
                            pass
                    
                    if not utilization_percentage and 'utilization_value' in point:
                        utilization_value = point.get('utilization_value', 0)
                        utilization_percentage = round(utilization_value * 100, 2)
                        display_value = f"{utilization_percentage}%"
                    
                    if not utilization_percentage:
                        display_value = "N/A"
                
                # Get dates
                award_date = point.get('award_date')
                if not isinstance(award_date, datetime):
                    award_date = datetime.utcnow()
                
                event_date = point.get('event_date')
                if 'metadata' in point and 'event_date' in point['metadata']:
                    event_date = point['metadata']['event_date']
                
                effective_date = event_date if event_date and isinstance(event_date, datetime) else award_date
                
                # Calculate fiscal quarter
                quarter, fiscal_year = get_fiscal_quarter_year(effective_date)
                quarter_label = f"FY{fiscal_year} Q{quarter}" if quarter and fiscal_year else None
                
                # Determine source
                source = 'manager'
                point_request_id = point.get('request_id')
                if point_request_id:
                    try:
                        original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                        if original_request:
                            if original_request.get('source') == 'employee_request':
                                source = 'employee'
                            elif original_request.get('created_by') and str(original_request.get('created_by')) == str(user_id):
                                source = 'employee'
                    except:
                        pass
                
                if source == 'manager' and point.get('awarded_by'):
                    try:
                        awarded_by_user = mongo.db.users.find_one({"_id": point['awarded_by']})
                        if awarded_by_user:
                            dashboard_access = awarded_by_user.get('dashboard_access', [])
                            if 'central' in dashboard_access:
                                source = 'central'
                            elif 'hr' in dashboard_access:
                                source = 'hr'
                    except:
                        pass
                
                display_source = 'Employee Request' if source == 'employee' else 'Direct Award'
                
                # ✅ Get validator name
                validator_name = None
                
                # For bonus points, check bonus_approved_by_id first
                if is_bonus and point.get('bonus_approved_by_id'):
                    try:
                        bonus_approver = mongo.db.users.find_one({'_id': point['bonus_approved_by_id']})
                        if bonus_approver:
                            validator_name = bonus_approver.get('name')
                    except:
                        pass
                
                # If not found, check request_id for validator
                if not validator_name:
                    point_request_id = point.get('request_id')
                    if point_request_id:
                        try:
                            original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                            if original_request and original_request.get('assigned_validator_id'):
                                validator = mongo.db.users.find_one({'_id': original_request['assigned_validator_id']})
                                if validator:
                                    validator_name = validator.get('name')
                        except:
                            pass
                
                # If still not found and it's a direct award, check awarded_by
                if not validator_name and point.get('awarded_by'):
                    try:
                        awarded_by_user = mongo.db.users.find_one({'_id': point['awarded_by']})
                        if awarded_by_user:
                            validator_name = awarded_by_user.get('name')
                    except:
                        pass
                
                entry = {
                    'id': point_id,
                    'category_name': category_name,
                    'points': points_value,
                    'display_value': display_value,
                    'is_utilization': is_utilization,
                    'utilization_percentage': utilization_percentage,
                    'request_date': award_date,
                    'event_date': event_date,
                    'display_date': effective_date,
                    'quarter_label': quarter_label,
                    'status': 'Approved',
                    'submission_notes': point.get('notes', ''),
                    'response_notes': point.get('notes', ''),
                    'has_attachment': point.get('has_attachment', False),
                    'attachment_filename': point.get('attachment_filename', ''),
                    'source': source,
                    'display_source': display_source,
                    'is_bonus': is_bonus,
                    'validator_name': validator_name,
                    'from_collection': 'points'
                }
                
                request_history.append(entry)
                
            except Exception as point_error:
                continue
        
        # ============================================
        # Add Pending/Rejected employee requests
        # ============================================
        try:
            pending_requests = list(mongo.db.points_request.find({
                'user_id': ObjectId(user_id),
                'status': {'$in': ['Pending', 'Rejected']},
                '$or': [
                    {'source': 'employee_request'},
                    {'created_by': ObjectId(user_id)}
                ]
            }).sort('request_date', -1))
            
            for req in pending_requests:
                try:
                    category = get_category_for_employee(req.get('category_id'))
                    category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
                    
                    is_utilization = is_utilization_category(category)
                    is_bonus = req.get('is_bonus', False)
                    if category and category.get('is_bonus'):
                        is_bonus = True
                    
                    points_value = req.get('points', 0)
                    display_value = points_value
                    utilization_percentage = None
                    
                    if is_utilization and 'utilization_value' in req:
                        utilization_value = req.get('utilization_value', 0)
                        utilization_percentage = round(utilization_value * 100, 2)
                        display_value = f"{utilization_percentage}%"
                    
                    request_date = req.get('request_date')
                    if not isinstance(request_date, datetime):
                        request_date = datetime.utcnow()
                    
                    event_date = req.get('event_date')
                    effective_date = event_date if event_date and isinstance(event_date, datetime) else request_date
                    
                    quarter, fiscal_year = get_fiscal_quarter_year(effective_date)
                    quarter_label = f"FY{fiscal_year} Q{quarter}" if quarter and fiscal_year else None
                    
                    # ✅ Get validator name
                    validator_name = None
                    
                    # For bonus points, check bonus_approved_by_id first
                    if is_bonus and req.get('bonus_approved_by_id'):
                        try:
                            bonus_approver = mongo.db.users.find_one({'_id': req['bonus_approved_by_id']})
                            if bonus_approver:
                                validator_name = bonus_approver.get('name')
                        except:
                            pass
                    
                    # If not found, check assigned_validator_id
                    if not validator_name and req.get('assigned_validator_id'):
                        try:
                            validator = mongo.db.users.find_one({'_id': req['assigned_validator_id']})
                            if validator:
                                validator_name = validator.get('name')
                        except:
                            pass
                    
                    entry = {
                        'id': str(req['_id']),
                        'category_name': category_name,
                        'points': points_value,
                        'display_value': display_value,
                        'is_utilization': is_utilization,
                        'utilization_percentage': utilization_percentage,
                        'request_date': request_date,
                        'event_date': event_date,
                        'display_date': effective_date,
                        'quarter_label': quarter_label,
                        'status': req.get('status', 'Pending'),
                        'submission_notes': get_submission_notes(req),
                        'response_notes': get_response_notes(req),
                        'has_attachment': req.get('has_attachment', False),
                        'attachment_filename': req.get('attachment_filename', ''),
                        'source': 'employee',
                        'display_source': 'Employee Request',
                        'is_bonus': is_bonus,
                        'validator_name': validator_name,
                        'from_collection': 'points_request'
                    }
                    
                    request_history.append(entry)
                    
                except Exception as req_error:
                    continue
        
        except Exception as pending_error:
            pass
        
        # Sort by date
        request_history.sort(
            key=lambda x: x['display_date'] if x['display_date'] else datetime.min,
            reverse=True
        )
        
    except Exception as e:
        flash('Error loading points history. Please contact support if this persists.', 'danger')
        request_history = []
        total_points = 0
        total_bonus_points = 0
    
    return render_template('employee_points_total.html',
                         user=user,
                         request_history=request_history,
                         total_points=total_points,
                         total_bonus_points=total_bonus_points,
                         other_dashboards=[],
                         user_profile_pic_url=None)

@employee_points_total_bp.route('/get-attachment/<request_id>')
def get_attachment(request_id):
    """Download attachment for a request"""
    user_id = session.get('user_id')
    if not user_id:
        flash('Please log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    try:
        req = mongo.db.points_request.find_one({
            '_id': ObjectId(request_id),
            'user_id': ObjectId(user_id)
        })
        
        # If not found, try points collection
        if not req:
            req = mongo.db.points.find_one({
                '_id': ObjectId(request_id),
                'user_id': ObjectId(user_id)
            })
        
        if not req:
            flash('Request not found', 'danger')
            return redirect(url_for('employee_points_total.points_total'))
        
        if not req.get('has_attachment'):
            flash('No attachment found', 'warning')
            return redirect(url_for('employee_points_total.points_total'))
        
        attachment_id = req.get('attachment_id')
        if not attachment_id:
            flash('Attachment ID missing', 'warning')
            return redirect(url_for('employee_points_total.points_total'))
        
        fs = GridFS(mongo.db)
        
        if isinstance(attachment_id, str):
            attachment_id = ObjectId(attachment_id)
        
        if not fs.exists(attachment_id):
            flash('Attachment file not found in storage', 'warning')
            return redirect(url_for('employee_points_total.points_total'))
        
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
        flash(f'Error downloading attachment: {str(e)}', 'danger')
        return redirect(url_for('employee_points_total.points_total'))