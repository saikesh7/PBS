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
    """Total points history page"""
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
    points_map = {}
    
    try:
        # ============================================
        # PHASE 1: Get ALL points entries (for totals AND display)
        # THIS IS THE ONLY PLACE WE COUNT TOTALS
        points_entries = list(mongo.db.points.find({
            'user_id': ObjectId(user_id)
        }).sort('award_date', -1))
        
        for point in points_entries:
            try:
                point_id = str(point['_id'])
                point_request_id = point.get('request_id')

                print(f"Category ID: {point.get('category_id')}", flush=True)
                print(f"Points: {point.get('points')}", flush=True)
                
                # ✅ Fetch category with robust error handling
                category = get_category_for_employee(point.get('category_id'))
                category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'

                # ✅ Check if this is a utilization category
                is_utilization = is_utilization_category(category)
                
                # Determine if it's a bonus
                is_bonus = point.get('is_bonus', False)
                if category and category.get('is_bonus'):
                    is_bonus = True
                # ✅ Also check category name for "bonus" keyword
                if category and 'bonus' in category_name.lower():
                    is_bonus = True
                
                # ✅ CRITICAL: Get display value (utilization % or points)
                display_value = None
                points_value = point.get('points', 0)
                utilization_percentage = None
                
                if is_utilization:
                    # For utilization, try to get the percentage from linked request

                    if point_request_id:
                        try:
                            original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                            if original_request and 'utilization_value' in original_request:
                                utilization_value = original_request.get('utilization_value', 0)
                                utilization_percentage = round(utilization_value * 100, 2)
                                display_value = f"{utilization_percentage}%"
                        except Exception as e:
                            pass  # Error fetching utilization from request
                    
                    # If still no display value, check the point itself
                    if not display_value and 'utilization_value' in point:
                        utilization_value = point.get('utilization_value', 0)
                        utilization_percentage = round(utilization_value * 100, 2)
                        display_value = f"{utilization_percentage}%"

                    # Final fallback
                    if not display_value:
                        display_value = "N/A"

                else:
                    # Regular points
                    display_value = points_value
                
                # ✅ COUNT POINTS HERE (ONLY FROM POINTS COLLECTION)
                if isinstance(points_value, (int, float)):
                    if is_bonus:
                        total_bonus_points += points_value

                    elif not is_utilization:  # Don't count utilization in regular totals
                        total_points += points_value

                # ✅ Get event_date and source
                event_date = None
                source = 'manager'
                
                # If linked to request, fetch request details for event_date
                if point_request_id:
                    try:
                        original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                        
                        if original_request:
                            # Extract source and event_date from request
                            # First check if source field exists in request (new format)
                            if original_request.get('source') == 'employee_request':
                                source = 'employee'
                                event_date = original_request.get('event_date')
                            elif original_request.get('created_by_hr_id') or original_request.get('hr_id'):
                                source = 'hr'
                                event_date = original_request.get('event_date')
                            elif original_request.get('created_by_ta_id') or original_request.get('ta_id'):
                                source = 'ta'
                                event_date = original_request.get('event_date')
                            elif original_request.get('created_by_pmo_id') or original_request.get('pmo_id'):
                                source = 'pmo'
                                event_date = original_request.get('event_date')
                            elif original_request.get('created_by_ld_id') or original_request.get('actioned_by_ld_id'):
                                source = 'ld'
                                event_date = original_request.get('metadata', {}).get('event_date')
                            elif original_request.get('created_by') and str(original_request.get('created_by')) != str(user_id):
                                source = 'manager'
                            else:
                                source = 'employee'
                    except Exception as e:
                        pass  # Error fetching linked request
                
                else:
                    # No request_id - direct award
                    if point.get('awarded_by'):
                        try:
                            awarded_by_user = mongo.db.users.find_one({"_id": point['awarded_by']})
                            if awarded_by_user:
                                dashboard_access = awarded_by_user.get('dashboard_access', [])
                                if 'central' in dashboard_access:
                                    source = 'central'
                                elif 'hr' in dashboard_access:
                                    source = 'hr'
                        except Exception as e:
                            pass  # Error checking awarded_by user
                    
                    # Check for event_date in metadata
                    if 'metadata' in point and 'event_date' in point['metadata']:
                        source = 'ld'
                        event_date = point['metadata']['event_date']
                    elif 'event_date' in point:
                        event_date = point['event_date']
                
                # Determine display source based on actual source
                if source == 'employee':
                    display_source = 'Employee Request'
                else:
                    display_source = 'Direct Award'
                
                # ✅ Get effective date (event_date > award_date)
                award_date = point.get('award_date')
                if not isinstance(award_date, datetime):
                    award_date = datetime.utcnow()
                
                effective_date = event_date if event_date and isinstance(event_date, datetime) else award_date
                
                # ✅ Calculate fiscal quarter
                quarter, fiscal_year = get_fiscal_quarter_year(effective_date)
                quarter_label = f"FY{fiscal_year} Q{quarter}" if quarter and fiscal_year else None
                
                entry = {
                    'id': point_id,
                    'category_name': category_name,
                    'points': points_value,
                    'display_value': display_value,  # ✅ NEW: Display value (percentage or points)
                    'is_utilization': is_utilization,  # ✅ NEW: Flag for utilization
                    'utilization_percentage': utilization_percentage,  # ✅ NEW: Numeric percentage
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
                    'from_collection': 'points'
                }
                
                request_history.append(entry)
                points_map[point_id] = entry
                
                # Also track by request_id if it exists
                if point_request_id:
                    points_map[str(point_request_id)] = entry

            except Exception as point_error:

                continue  # Skip this point but continue processing others

        print(f"Total Points (from points collection): {total_points}", flush=True)
        print(f"Total Bonus Points (from points collection): {total_bonus_points}", flush=True)
        print(f"Processed {len(request_history)} entries", flush=True)
        
        # ============================================
        # PHASE 2: Get points_request entries for DISPLAY ENRICHMENT
        # ✅ NO COUNTING OF TOTALS HERE - ONLY FOR DISPLAY
        # ============================================

        try:
            points_requests = list(mongo.db.points_request.find({
                'user_id': ObjectId(user_id)
            }).sort('request_date', -1))
            
            print(f"Found {len(points_requests)} points_request entries", flush=True)
            
            enriched_count = 0
            pending_count = 0
            
            for req in points_requests:
                try:
                    req_id = str(req['_id'])
                    
                    # ✅ Check if we already have this in our display from points collection
                    if req_id in points_map:
                        # This request has already been counted in points collection
                        # Enrich the existing entry with request details
                        existing_entry = points_map[req_id]
                        
                        # Update with better details from request
                        existing_entry['submission_notes'] = get_submission_notes(req)
                        existing_entry['response_notes'] = get_response_notes(req)
                        existing_entry['status'] = req.get('status', 'Approved')
                        
                        if req.get('has_attachment'):
                            existing_entry['has_attachment'] = True
                            existing_entry['attachment_filename'] = req.get('attachment_filename', '')
                        
                        # Update utilization display if needed
                        if existing_entry.get('is_utilization') and 'utilization_value' in req:
                            utilization_value = req.get('utilization_value', 0)
                            utilization_percentage = round(utilization_value * 100, 2)
                            existing_entry['display_value'] = f"{utilization_percentage}%"
                            existing_entry['utilization_percentage'] = utilization_percentage
                        
                        enriched_count += 1

                        continue
                    
                    # ✅ If status is Pending or Rejected, add to display (not counted in totals)
                    if req.get('status') in ['Pending', 'Rejected']:
                        # Extract event_date and source to determine if it's employee-raised or direct award
                        event_date = None
                        source = 'employee'
                        
                        # Check source field first (new format)
                        if req.get('source') == 'employee_request':
                            source = 'employee'
                            event_date = req.get('event_date')
                        elif req.get('created_by_hr_id') or req.get('hr_id'):
                            source = 'hr'
                            event_date = req.get('event_date')
                        elif req.get('created_by_ta_id') or req.get('ta_id'):
                            source = 'ta'
                            event_date = req.get('event_date')
                        elif req.get('created_by_pmo_id') or req.get('pmo_id'):
                            source = 'pmo'
                            event_date = req.get('event_date')
                        elif req.get('created_by_ld_id') or req.get('actioned_by_ld_id'):
                            source = 'ld'
                            event_date = req.get('metadata', {}).get('event_date')
                        elif req.get('created_by_market_id'):
                            source = 'marketing'
                        elif req.get('created_by_presales_id'):
                            source = 'presales'
                        elif req.get('created_by') and str(req.get('created_by')) != str(user_id):
                            source = 'manager'
                        
                        display_source = 'Employee Request' if source == 'employee' else 'Direct Award'
                        
                        # ✅ REQUIREMENT: Hide pending/rejected DIRECT AWARDS from HR/TA/PMO/LD/Manager
                        # Only show employee-raised pending/rejected requests
                        if source != 'employee' and req.get('status') in ['Pending', 'Rejected']:
                            # Skip direct award pending/rejected entries from:
                            # - HR Updater/Validator (created_by_hr_id)
                            # - TA Updater/Validator (created_by_ta_id)
                            # - PMO Updater/Validator (created_by_pmo_id)
                            # - L&D Updater/Validator (created_by_ld_id)
                            # - Manager (created_by != user_id)
                            continue
                        
                        category = get_category_for_employee(req.get('category_id'))
                        category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
                        
                        is_utilization = is_utilization_category(category)
                        is_bonus = req.get('is_bonus', False)
                        if category and category.get('is_bonus'):
                            is_bonus = True
                        # ✅ Also check category name for "bonus" keyword
                        if category and 'bonus' in category_name.lower():
                            is_bonus = True
                        
                        # Get display value
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
                        
                        effective_date = event_date if event_date and isinstance(event_date, datetime) else request_date
                        quarter, fiscal_year = get_fiscal_quarter_year(effective_date)
                        quarter_label = f"FY{fiscal_year} Q{quarter}" if quarter and fiscal_year else None
                        
                        entry = {
                            'id': req_id,
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
                            'source': source,
                            'display_source': display_source,
                            'is_bonus': is_bonus,
                            'from_collection': 'points_request'
                        }
                        
                        request_history.append(entry)
                        pending_count += 1

                except Exception as req_error:
                    continue  # Skip this request but continue processing others
        
        except Exception as phase2_error:
            pass  # Continue even if Phase 2 fails
        
        # ============================================
        # PHASE 3: Sort by effective date
        # ============================================
        request_history.sort(
            key=lambda x: x['display_date'] if x['display_date'] else datetime.min, 
            reverse=True
        )

        print(f"Total Display Entries: {len(request_history)}", flush=True)
        
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR in points_total: {str(e)}", flush=True)
        flash('Error loading points history. Please contact support if this persists.', 'danger')
        # Return with empty data rather than crashing
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

        # Try points_request first
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