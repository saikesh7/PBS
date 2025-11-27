from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import logging
import os
from .hr_utils import check_hr_access

logging.basicConfig(
    filename='hr_app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

current_dir = os.path.dirname(os.path.abspath(__file__))

hr_points_mgmt_bp = Blueprint('hr_points_mgmt', __name__, url_prefix='/hr',
                              template_folder=os.path.join(current_dir, 'templates'),
                              static_folder=os.path.join(current_dir, 'static'),
                              static_url_path='/hr/static')


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_merged_categories():
    """
    Get categories from both hr_categories and categories collections
    Returns: dict with category_id -> category_info mapping
    """
    merged_categories = {}
    
    # Fetch from old categories collection
    old_categories = list(mongo.db.categories.find({}, {'_id': 1, 'name': 1, 'code': 1}))
    for cat in old_categories:
        merged_categories[cat['_id']] = {
            '_id': cat['_id'],
            'name': cat.get('name', 'Unknown'),
            'code': cat.get('code', 'unknown')
        }
    
    # Fetch from new hr_categories collection (takes priority)
    hr_categories = list(mongo.db.hr_categories.find({}, {'_id': 1, 'name': 1, 'category_code': 1}))
    for cat in hr_categories:
        merged_categories[cat['_id']] = {
            '_id': cat['_id'],
            'name': cat.get('name', 'Unknown'),
            'code': cat.get('category_code', 'unknown')
        }
    
    return merged_categories


def get_category_by_id(category_id):
    """
    Get category by ID from either collection
    """
    if not category_id:
        return None
    
    try:
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
        
        # Try hr_categories first
        category = mongo.db.hr_categories.find_one({'_id': category_id})
        if category:
            return {
                '_id': category['_id'],
                'name': category.get('name', 'Unknown'),
                'code': category.get('category_code', 'unknown')
            }
        
        # Fall back to old categories
        category = mongo.db.categories.find_one({'_id': category_id})
        if category:
            return {
                '_id': category['_id'],
                'name': category.get('name', 'Unknown'),
                'code': category.get('code', 'unknown')
            }
        
        return None
        
    except Exception as e:
        logging.error(f"Error fetching category {category_id}: {e}")
        return None


def get_current_fiscal_quarter_and_year(now_utc=None):
    """Get current fiscal quarter and year (April-March)"""
    if now_utc is None:
        now_utc = datetime.utcnow()
    
    current_month = now_utc.month
    current_calendar_year = now_utc.year

    if 1 <= current_month <= 3:
        fiscal_quarter = 4
        fiscal_year_start_calendar_year = current_calendar_year - 1
    elif 4 <= current_month <= 6:
        fiscal_quarter = 1
        fiscal_year_start_calendar_year = current_calendar_year
    elif 7 <= current_month <= 9:
        fiscal_quarter = 2
        fiscal_year_start_calendar_year = current_calendar_year
    else:
        fiscal_quarter = 3
        fiscal_year_start_calendar_year = current_calendar_year
    
    return fiscal_quarter, fiscal_year_start_calendar_year


def get_fiscal_period_date_range(fiscal_quarter, fiscal_year_start_calendar_year):
    """Get date range for a fiscal quarter"""
    if fiscal_quarter == 1:
        start_date = datetime(fiscal_year_start_calendar_year, 4, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 6, 30, 23, 59, 59, 999999)
    elif fiscal_quarter == 2:
        start_date = datetime(fiscal_year_start_calendar_year, 7, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 9, 30, 23, 59, 59, 999999)
    elif fiscal_quarter == 3:
        start_date = datetime(fiscal_year_start_calendar_year, 10, 1)
        end_date = datetime(fiscal_year_start_calendar_year, 12, 31, 23, 59, 59, 999999)
    elif fiscal_quarter == 4:
        start_date = datetime(fiscal_year_start_calendar_year + 1, 1, 1)
        end_date = datetime(fiscal_year_start_calendar_year + 1, 3, 31, 23, 59, 59, 999999)
    else:
        raise ValueError("Invalid fiscal quarter")
    return start_date, end_date


def get_current_fiscal_year_date_range(fiscal_year_start_calendar_year):
    """Get date range for entire fiscal year"""
    start_date = datetime(fiscal_year_start_calendar_year, 4, 1)
    end_date = datetime(fiscal_year_start_calendar_year + 1, 3, 31, 23, 59, 59, 999999)
    return start_date, end_date


def get_effective_date(point_entry):
    """
    Get effective date from point entry with fallback
    Priority: award_date > event_date > request_date
    """
    for field in ['award_date', 'event_date', 'request_date']:
        date_val = point_entry.get(field)
        if date_val and isinstance(date_val, datetime):
            return date_val
    return None


# ==========================================
# API ENDPOINTS
# ==========================================

@hr_points_mgmt_bp.route('/api/user-points-data/<user_id>', methods=['GET'])
def api_user_points_data(user_id):
    """API endpoint to fetch user points data"""
    has_access, current_user = check_hr_access()
    
    if not has_access:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        user_id_obj = ObjectId(user_id)
        user = mongo.db.users.find_one({"_id": user_id_obj})
        if not user:
            return jsonify({"error": "User not found"}), 404

        now_utc = datetime.utcnow()
        current_fq, current_fyscy = get_current_fiscal_quarter_and_year(now_utc)
        q_start_date, q_end_date = get_fiscal_period_date_range(current_fq, current_fyscy)
        fy_start_date, fy_end_date = get_current_fiscal_year_date_range(current_fyscy)

        # Get merged categories
        categories_map = get_merged_categories()

        # Initialize counters
        current_quarter_total_points = 0
        current_year_total_points = 0
        quarterly_breakdown = {}
        yearly_summary = {}
        points_history = []
        total_points_all_time = 0

        # Fetch all points for user
        all_points_for_user = list(mongo.db.points.find({"user_id": user_id_obj}))

        # Collect user IDs for name lookup
        user_ids_for_name_lookup = set()
        for point_entry in all_points_for_user:
            awarded_by_id = point_entry.get('awarded_by')
            if isinstance(awarded_by_id, ObjectId):
                user_ids_for_name_lookup.add(awarded_by_id)
            if point_entry.get('is_bonus'):
                bonus_approved_by_id_val = point_entry.get('bonus_approved_by_id')
                if isinstance(bonus_approved_by_id_val, ObjectId):
                    user_ids_for_name_lookup.add(bonus_approved_by_id_val)

        # Fetch user names
        user_name_map = {}
        if user_ids_for_name_lookup:
            try:
                user_docs = mongo.db.users.find({'_id': {'$in': list(user_ids_for_name_lookup)}}, {'_id': 1, 'name': 1})
                user_name_map = {str(user['_id']): user['name'] for user in user_docs}
            except Exception as e:
                logging.error(f"Error fetching user names for points history: {e}")

        # Sort by date
        all_points_for_user.sort(key=lambda x: get_effective_date(x) or datetime.min, reverse=True)

        # For collecting unique filter values
        temp_categories = set()
        temp_awarded_by = set()
        temp_periods = set()

        # Process each point entry
        for point in all_points_for_user:
            # Get effective date with fallback
            effective_date = get_effective_date(point)
            
            period = "N/A"
            if effective_date and isinstance(effective_date, datetime):
                fiscal_quarter, fiscal_year_start = get_current_fiscal_quarter_and_year(effective_date)
                period = f"Q{fiscal_quarter} {fiscal_year_start}-{fiscal_year_start + 1}"
                
                quarterly_breakdown.setdefault(f"Q{fiscal_quarter}", 0)
                quarterly_breakdown[f"Q{fiscal_quarter}"] += point['points']
                
                yearly_summary.setdefault(f"{fiscal_year_start}-{fiscal_year_start + 1}", 0)
                yearly_summary[f"{fiscal_year_start}-{fiscal_year_start + 1}"] += point['points']

                # Check if in current quarter/year
                if q_start_date <= effective_date <= q_end_date:
                    current_quarter_total_points += point['points']
                if fy_start_date <= effective_date <= fy_end_date:
                    current_year_total_points += point['points']

            # Get category name using merged categories
            category_id = point.get('category_id')
            category_info = categories_map.get(category_id)
            category_name = category_info['name'] if category_info else 'Unknown'

            # Get awarded by name
            awarded_by_val = point.get('awarded_by')
            awarded_by_name = 'Unknown'
            if isinstance(awarded_by_val, ObjectId):
                awarded_by_name = user_name_map.get(str(awarded_by_val), 'Unknown User')
            elif awarded_by_val == 'HR':
                awarded_by_name = 'HR'

            # Get bonus approver name
            bonus_approver_name = None
            if point.get('is_bonus') and point.get('bonus_approved_by_id'):
                bonus_approved_by_id_val = point.get('bonus_approved_by_id')
                if isinstance(bonus_approved_by_id_val, ObjectId):
                    bonus_approver_name = user_name_map.get(str(bonus_approved_by_id_val), 'Unknown Approver')

            points_history.append({
                'id': str(point['_id']),
                'category': category_name,
                'points': point['points'],
                'awarded_by': awarded_by_name,
                'award_date': effective_date.strftime('%d-%m-%Y') if effective_date else "N/A",
                'notes': point.get('notes', ''),
                'period': period,
                'is_bonus': point.get('is_bonus', False),
                'bonus_approver_name': bonus_approver_name
            })

            total_points_all_time += point['points']

            temp_categories.add(category_name)
            temp_awarded_by.add(awarded_by_name)
            temp_periods.add(period)

        unique_categories_for_filter = sorted(list(temp_categories))
        unique_awarded_by_for_filter = sorted(list(temp_awarded_by))
        unique_periods_for_filter = sorted(list(temp_periods))

        return jsonify({
            "user_id": str(user['_id']),
            "user_name": user['name'],
            "employee_id": user['employee_id'],
            "email": user['email'],
            "grade": user.get('grade', 'N/A'),
            "total_points_all_time": total_points_all_time,
            "current_quarter_total_points": current_quarter_total_points,
            "current_year_total_points": current_year_total_points,
            "quarterly_breakdown": quarterly_breakdown,
            "yearly_summary": yearly_summary,
            "points_history": points_history,
            "unique_categories_for_filter": unique_categories_for_filter,
            "unique_awarded_by_for_filter": unique_awarded_by_for_filter,
            "unique_periods_for_filter": unique_periods_for_filter
        })

    except Exception as e:
        logging.error(f"Error in api_user_points_data for user {user_id}: {str(e)}")
        return jsonify({"error": "An internal server error occurred."}), 500


# ==========================================
# MAIN ROUTES
# ==========================================

@hr_points_mgmt_bp.route('/update-user-points', methods=['GET', 'POST'])
def update_user_points_page():
    """Main page for updating user points"""
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))

    # Initialize variables
    user = None
    show_form = False
    current_quarter_total_points = 0
    current_year_total_points = 0
    search_query_val = ''
    points_history = []
    total_points_all_time = 0
    quarterly_breakdown = {}
    yearly_summary = {}
    unique_categories_for_filter = []
    unique_awarded_by_for_filter = []
    unique_periods_for_filter = []
    employees = []

    # Get merged categories
    categories_map = get_merged_categories()

    # Fetch all employees
    employees = list(mongo.db.users.find({
        'role': {'$in': ['Employee', 'Manager']}
    }).sort('name', 1))

    # Get manager names for display
    managers = list(mongo.db.users.find({'role': 'Manager'}, {'_id': 1, 'name': 1}))
    manager_dict = {str(manager['_id']): manager['name'] for manager in managers}
    for employee in employees:
        if employee.get('manager_id'):
            manager_id = str(employee['manager_id'])
            employee['manager_name'] = manager_dict.get(manager_id, 'Unknown')
        else:
            employee['manager_name'] = 'Not Assigned'

    # ==========================================
    # HANDLE POST REQUESTS
    # ==========================================
    
    if request.method == 'POST':
        search_query_val = request.form.get('search_query', '').strip()
        
        # ===== SEARCH EMPLOYEE =====
        if 'search_employee' in request.form:
            if search_query_val:
                user = mongo.db.users.find_one({
                    '$and': [
                        {'role': {'$in': ['Employee', 'Manager']}},
                        {'$or': [
                            {'email': {'$regex': '^' + search_query_val + '$', '$options': 'i'}},
                            {'employee_id': {'$regex': '^' + search_query_val + '$', '$options': 'i'}}
                        ]}
                    ]
                })
                if not user:
                    flash('Employee not found.', 'danger')
                else:
                    show_form = True
                    return redirect(url_for('hr_points_mgmt.update_user_points_page', search_query=search_query_val))
            else:
                flash('Please enter an Email or Employee ID.', 'warning')

        # ===== UPDATE POINT TRANSACTION =====
        elif 'update_point' in request.form:
            point_id = request.form.get('point_id')
            new_points_str = request.form.get('points')
            new_notes = request.form.get('notes')
            search_query_val = request.form.get('search_query', '').strip()
            
            try:
                new_points = int(new_points_str)
                
                # ✅ CRITICAL FIX: Get the original point entry to preserve dates
                original_point = mongo.db.points.find_one({'_id': ObjectId(point_id)})
                
                if not original_point:
                    flash('Point transaction not found.', 'danger')
                    return redirect(url_for('hr_points_mgmt.update_user_points_page', search_query=search_query_val))
                
                # ✅ Preserve original dates - DO NOT update award_date
                update_data = {
                    'points': new_points,
                    'notes': new_notes,
                    'last_updated_by': ObjectId(session.get('user_id')),
                    'last_updated_at': datetime.utcnow()
                }
                
                # Update points collection
                update_result_points_collection = mongo.db.points.update_one(
                    {'_id': ObjectId(point_id)},
                    {'$set': update_data}
                )
                
                if update_result_points_collection.matched_count == 0:
                    flash('Point transaction not found in points collection.', 'danger')
                    return redirect(url_for('hr_points_mgmt.update_user_points_page', search_query=search_query_val))

                # Update corresponding points_request if exists
                if 'request_id' in original_point and original_point['request_id']:
                    request_id = original_point['request_id']
                    
                    if not isinstance(request_id, ObjectId):
                        try:
                            request_id = ObjectId(request_id)
                        except Exception as e:
                            flash(f'Invalid request_id format: {str(e)}', 'warning')
                            logging.warning(f"Invalid request_id format {request_id} for point_id {point_id}: {e}")
                            request_id = None

                    if request_id:
                        # ✅ Also preserve original dates in points_request
                        update_request_result = mongo.db.points_request.update_one(
                            {'_id': request_id, "status": "Approved"},
                            {'$set': {
                                'points': new_points,
                                'response_notes': f"Updated by HR: {new_notes}",
                                'processed_by': ObjectId(session.get('user_id')),
                                'last_updated_at': datetime.utcnow()
                                # ✅ DO NOT update response_date or award_date
                            }}
                        )
                        
                        if update_request_result.matched_count > 0:
                            logging.info(f"HR {session.get('user_id')} updated points_request {request_id}")
                        else:
                            logging.warning(f"No matching 'Approved' points_request found for ID {request_id}")
                            flash('Point updated in points collection. Corresponding request might not have been updated.', 'warning')
                else:
                    logging.info(f"No associated request_id found for point {point_id}")
                
                flash('Point transaction updated successfully! Original date preserved.', 'success')
                logging.info(f"HR {session.get('user_id')} updated point {point_id} - preserved original dates")
                return redirect(url_for('hr_points_mgmt.update_user_points_page', search_query=search_query_val))
                
            except ValueError:
                flash('Invalid points value.', 'danger')
            except Exception as e:
                flash(f'Error updating point transaction: {str(e)}', 'danger')
                logging.error(f'Error updating point transaction for point_id {point_id}: {str(e)}')

        # ===== DELETE POINT TRANSACTION =====
        elif 'delete_point' in request.form:
            point_id = request.form.get('point_id')
            try:
                point_to_delete = mongo.db.points.find_one({'_id': ObjectId(point_id)})
                if not point_to_delete:
                    flash('Point transaction not found.', 'danger')
                    return redirect(url_for('hr_points_mgmt.update_user_points_page', search_query=search_query_val))

                # Delete from points_request if exists
                request_id_to_delete = point_to_delete.get('request_id')
                deleted_from_request_collection = False
                
                if request_id_to_delete:
                    if not isinstance(request_id_to_delete, ObjectId):
                        request_id_to_delete = ObjectId(request_id_to_delete)
                    delete_request_result = mongo.db.points_request.delete_one({'_id': request_id_to_delete})
                    if delete_request_result.deleted_count > 0:
                        deleted_from_request_collection = True
                        logging.info(f"HR {session.get('user_id')} deleted points_request {request_id_to_delete}")

                # Delete from points collection
                delete_point_result = mongo.db.points.delete_one({'_id': ObjectId(point_id)})
                
                flash_message = 'Point transaction deleted.'
                if deleted_from_request_collection:
                    flash_message += ' Corresponding request also removed.'
                flash(flash_message, 'success')
                
                logging.info(f"HR {session.get('user_id')} deleted point {point_id}")
                return redirect(url_for('hr_points_mgmt.update_user_points_page', search_query=search_query_val))
                
            except Exception as e:
                flash(f'Error deleting point: {str(e)}', 'danger')
                logging.error(f'Error deleting point: {str(e)}')

    # ==========================================
    # HANDLE GET REQUESTS
    # ==========================================
    
    elif request.method == 'GET':
        search_query_val = request.args.get('search_query', '').strip()
        if search_query_val:
            user = mongo.db.users.find_one({
                '$and': [
                    {'role': {'$in': ['Employee', 'Manager']}},
                    {'$or': [
                        {'email': {'$regex': '^' + search_query_val + '$', '$options': 'i'}},
                        {'employee_id': {'$regex': '^' + search_query_val + '$', '$options': 'i'}}
                    ]}
                ]
            })
            if user:
                show_form = True
            else:
                if request.args.get('search_query'):
                    flash('Employee not found for the provided search query.', 'info')

    # ==========================================
    # LOAD USER POINTS DATA
    # ==========================================
    
    if user:
        user_id_obj = user['_id']
        now_utc = datetime.utcnow()
        current_fq, current_fyscy = get_current_fiscal_quarter_and_year(now_utc)
        q_start_date, q_end_date = get_fiscal_period_date_range(current_fq, current_fyscy)
        fy_start_date, fy_end_date = get_current_fiscal_year_date_range(current_fyscy)
        
        # Calculate current quarter and year totals
        all_points_for_user = mongo.db.points.find({"user_id": user_id_obj})
        for point_entry in all_points_for_user:
            effective_date = get_effective_date(point_entry)
            points_value = point_entry.get("points", 0)
            
            if effective_date and isinstance(effective_date, datetime):
                if q_start_date <= effective_date <= q_end_date:
                    current_quarter_total_points += points_value
                if fy_start_date <= effective_date <= fy_end_date:
                    current_year_total_points += points_value

        # Fetch all points with sorting
        all_points = list(mongo.db.points.find({'user_id': user_id_obj}))
        all_points.sort(key=lambda x: get_effective_date(x) or datetime.min, reverse=True)
        
        # Collect user IDs for name lookup
        user_ids_for_name_lookup = set()
        for point_entry in all_points:
            awarded_by_id = point_entry.get('awarded_by')
            if isinstance(awarded_by_id, ObjectId):
                user_ids_for_name_lookup.add(awarded_by_id)
            if point_entry.get('is_bonus'):
                bonus_approved_by_id_val = point_entry.get('bonus_approved_by_id')
                if isinstance(bonus_approved_by_id_val, ObjectId):
                    user_ids_for_name_lookup.add(bonus_approved_by_id_val)

        # Fetch user names
        user_name_map = {}
        if user_ids_for_name_lookup:
            try:
                user_docs = mongo.db.users.find({'_id': {'$in': list(user_ids_for_name_lookup)}}, {'_id': 1, 'name': 1})
                user_name_map = {str(user['_id']): user['name'] for user in user_docs}
            except Exception as e:
                logging.error(f"Error fetching user names for points history: {e}")

        # Build points history
        points_history = []
        temp_categories = set()
        temp_awarded_by = set()
        temp_periods = set()
        
        for point in all_points:
            effective_date = get_effective_date(point)
            
            period = "N/A"
            if effective_date and isinstance(effective_date, datetime):
                fiscal_quarter, fiscal_year_start = get_current_fiscal_quarter_and_year(effective_date)
                period = f"Q{fiscal_quarter} {fiscal_year_start}-{fiscal_year_start + 1}"
                
                quarterly_breakdown.setdefault(f"Q{fiscal_quarter}", 0)
                quarterly_breakdown[f"Q{fiscal_quarter}"] += point['points']
                
                yearly_summary.setdefault(f"{fiscal_year_start}-{fiscal_year_start + 1}", 0)
                yearly_summary[f"{fiscal_year_start}-{fiscal_year_start + 1}"] += point['points']

            # Get category using merged categories
            category_id = point.get('category_id')
            category_info = categories_map.get(category_id)
            category_name = category_info['name'] if category_info else 'Unknown'
            
            # Get awarded by
            awarded_by_val = point.get('awarded_by')
            awarded_by_name = 'Unknown'
            if isinstance(awarded_by_val, ObjectId):
                awarded_by_name = user_name_map.get(str(awarded_by_val), 'Unknown User')
            elif awarded_by_val == 'HR':
                awarded_by_name = 'HR'
            
            # Get bonus approver
            bonus_approver_name = None
            if point.get('is_bonus') and point.get('bonus_approved_by_id'):
                bonus_approved_by_id_val = point.get('bonus_approved_by_id')
                if isinstance(bonus_approved_by_id_val, ObjectId):
                    bonus_approver_name = user_name_map.get(str(bonus_approved_by_id_val), 'Unknown Approver')

            points_history.append({
                'id': str(point['_id']),
                'category': category_name,
                'points': point['points'],
                'awarded_by': awarded_by_name,
                'award_date': effective_date.strftime('%d-%m-%Y') if effective_date else "N/A",
                'notes': point.get('notes', ''),
                'period': period,
                'is_bonus': point.get('is_bonus', False),
                'bonus_approver_name': bonus_approver_name
            })
            
            temp_categories.add(category_name)
            temp_awarded_by.add(awarded_by_name)
            temp_periods.add(period)

        total_points_all_time = sum(p['points'] for p in all_points)
        
        unique_categories_for_filter = sorted(list(temp_categories))
        unique_awarded_by_for_filter = sorted(list(temp_awarded_by))
        unique_periods_for_filter = sorted(list(temp_periods))

    return render_template(
        'update_points.html',
        user=user,
        show_form=show_form,
        employees=employees,
        current_quarter_total_points=current_quarter_total_points,
        current_year_total_points=current_year_total_points,
        search_query=search_query_val,
        points_history=points_history,
        total_points_all_time=total_points_all_time,
        quarterly_breakdown=quarterly_breakdown,
        yearly_summary=yearly_summary,
        unique_categories_for_filter=unique_categories_for_filter,
        unique_awarded_by_for_filter=unique_awarded_by_for_filter,
        unique_periods_for_filter=unique_periods_for_filter
    )


@hr_points_mgmt_bp.context_processor
def inject_hr_specific_permissions():
    """Context processor for HR-specific permissions"""
    can_access_update_points = False
    
    has_access, user = check_hr_access()
    
    if has_access:
        can_access_update_points = True
        logging.info(f"Context Processor: Access to Update Points Page GRANTED for user with HR dashboard access.")
    else:
        logging.info(f"Context Processor: Access to Update Points Page DENIED. User does not have HR dashboard access.")
        
    return dict(can_access_update_points_page=can_access_update_points)