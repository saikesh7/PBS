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
        
        # ✅ Try hr_categories FIRST (where new employee categories are stored)
        category = mongo.db.hr_categories.find_one({'_id': category_id})
        if category:
            print(f"✅ Found category in hr_categories: {category.get('name', 'Unknown')}", flush=True)
            return category
        
        # ✅ Fallback to categories (where old employee categories were stored)
        category = mongo.db.categories.find_one({'_id': category_id})
        if category:
            print(f"✅ Found category in categories: {category.get('name', 'Unknown')}", flush=True)
            return category
        
        print(f"⚠️ Category not found for ID: {category_id}", flush=True)
        return None
        
    except Exception as e:
        print(f"❌ Error fetching category {category_id}: {str(e)}", flush=True)
        return None

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
        print(f"❌ Error in get_effective_date: {str(e)}", flush=True)
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
        print(f"❌ Error in get_fiscal_quarter_year: {str(e)}", flush=True)
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
        # ✅ THIS IS THE ONLY PLACE WE COUNT TOTALS
        # ============================================
        print("\n=== PHASE 1: Processing points collection ===", flush=True)
        points_entries = list(mongo.db.points.find({
            'user_id': ObjectId(user_id)
        }).sort('award_date', -1))
        
        print(f"Found {len(points_entries)} points entries", flush=True)
        
        for point in points_entries:
            try:
                point_id = str(point['_id'])
                point_request_id = point.get('request_id')
                
                print(f"\n--- Processing point {point_id} ---", flush=True)
                print(f"Category ID: {point.get('category_id')}", flush=True)
                print(f"Points: {point.get('points')}", flush=True)
                
                # ✅ Fetch category with robust error handling
                category = get_category_for_employee(point.get('category_id'))
                category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
                
                print(f"Resolved category name: {category_name}", flush=True)
                
                # Determine if it's a bonus
                is_bonus = point.get('is_bonus', False)
                if category and category.get('is_bonus'):
                    is_bonus = True
                
                # ✅ CRITICAL: COUNT POINTS HERE (ONLY FROM POINTS COLLECTION)
                points_value = point.get('points', 0)
                if isinstance(points_value, (int, float)):
                    if is_bonus:
                        total_bonus_points += points_value
                        print(f"Added {points_value} to bonus total", flush=True)
                    else:
                        # Check if it's utilization (don't count in regular totals)
                        is_utilization = False
                        if category:
                            category_code = category.get('code', '')
                            if category_code == 'utilization_billable':
                                is_utilization = True
                        
                        if not is_utilization:
                            total_points += points_value
                            print(f"Added {points_value} to regular total", flush=True)
                
                # ✅ Get event_date and source
                event_date = None
                source = 'manager'
                
                # If linked to request, fetch request details for event_date
                if point_request_id:
                    try:
                        original_request = mongo.db.points_request.find_one({'_id': point_request_id})
                        
                        if original_request:
                            # Extract source and event_date from request
                            if original_request.get('created_by_ta_id') or original_request.get('ta_id'):
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
                        print(f"⚠️ Error fetching linked request: {str(e)}", flush=True)
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
                            print(f"⚠️ Error checking awarded_by user: {str(e)}", flush=True)
                    
                    # Check for event_date in metadata
                    if 'metadata' in point and 'event_date' in point['metadata']:
                        source = 'ld'
                        event_date = point['metadata']['event_date']
                    elif 'event_date' in point:
                        event_date = point['event_date']
                
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
                
                print(f"✅ Successfully processed point {point_id}", flush=True)
                
            except Exception as point_error:
                print(f"❌ Error processing point {point.get('_id')}: {str(point_error)}", flush=True)
                print(traceback.format_exc(), flush=True)
                continue  # Skip this point but continue processing others
        
        print(f"\n=== Phase 1 Complete ===", flush=True)
        print(f"Total Points (from points collection): {total_points}", flush=True)
        print(f"Total Bonus Points (from points collection): {total_bonus_points}", flush=True)
        print(f"Processed {len(request_history)} entries", flush=True)
        
        # ============================================
        # PHASE 2: Get points_request entries for DISPLAY ENRICHMENT
        # ✅ NO COUNTING OF TOTALS HERE - ONLY FOR DISPLAY
        # ============================================
        print("\n=== PHASE 2: Processing points_request for display enrichment ===", flush=True)
        
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
                        
                        enriched_count += 1
                        print(f"✅ Enriched entry {req_id}", flush=True)
                        continue
                    
                    # ✅ If status is Pending or Rejected, add to display (not counted in totals)
                    if req.get('status') in ['Pending', 'Rejected']:
                        category = get_category_for_employee(req.get('category_id'))
                        category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
                        
                        is_bonus = req.get('is_bonus', False)
                        if category and category.get('is_bonus'):
                            is_bonus = True
                        
                        # Extract event_date and source
                        event_date = None
                        source = 'employee'
                        
                        if req.get('created_by_ta_id') or req.get('ta_id'):
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
                        
                        request_date = req.get('request_date')
                        if not isinstance(request_date, datetime):
                            request_date = datetime.utcnow()
                        
                        effective_date = event_date if event_date and isinstance(event_date, datetime) else request_date
                        quarter, fiscal_year = get_fiscal_quarter_year(effective_date)
                        quarter_label = f"FY{fiscal_year} Q{quarter}" if quarter and fiscal_year else None
                        
                        entry = {
                            'id': req_id,
                            'category_name': category_name,
                            'points': req.get('points', 0),
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
                        print(f"✅ Added {req.get('status')} request {req_id}", flush=True)
                
                except Exception as req_error:
                    print(f"❌ Error processing request {req.get('_id')}: {str(req_error)}", flush=True)
                    continue  # Skip this request but continue processing others
            
            print(f"\n=== Phase 2 Complete ===", flush=True)
            print(f"Enriched {enriched_count} entries", flush=True)
            print(f"Added {pending_count} pending/rejected requests", flush=True)
            
        except Exception as phase2_error:
            print(f"❌ Error in Phase 2: {str(phase2_error)}", flush=True)
            print(traceback.format_exc(), flush=True)
            # Continue even if Phase 2 fails
        
        # ============================================
        # PHASE 3: Sort by effective date
        # ============================================
        request_history.sort(
            key=lambda x: x['display_date'] if x['display_date'] else datetime.min, 
            reverse=True
        )
        
        print(f"\n=== FINAL TOTALS ===", flush=True)
        print(f"Regular Points: {total_points}", flush=True)
        print(f"Bonus Points: {total_bonus_points}", flush=True)
        print(f"Total Display Entries: {len(request_history)}", flush=True)
        
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR in points_total: {str(e)}", flush=True)
        print(traceback.format_exc(), flush=True)
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
        print(f"📥 EMPLOYEE HISTORY DEBUG: Downloading attachment for request: {request_id}", flush=True)
        
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
            print(f"❌ EMPLOYEE HISTORY DEBUG: Request not found", flush=True)
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
        print(f"❌ Error downloading attachment: {str(e)}", flush=True)
        print(traceback.format_exc(), flush=True)
        flash(f'Error downloading attachment: {str(e)}', 'danger')
        return redirect(url_for('employee_points_total.points_total'))
