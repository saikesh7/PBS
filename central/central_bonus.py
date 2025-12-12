from flask import request, jsonify, session, current_app
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import calendar
from . import central_bp
from .central_utils import (
    check_central_access, get_current_quarter, get_quarter_date_range,
    get_reward_config, calculate_yearly_bonus_points, check_bonus_eligibility,
    calculate_bonus_points, get_eligible_users,
    check_bonus_awarded_for_quarter, debug_print, error_print
)
from .central_email import send_bonus_eligibility_email

def get_fiscal_quarter_from_date(date):
    """Get fiscal quarter number (1-4) from a date based on April-March fiscal year"""
    if not date or not isinstance(date, datetime):
        return None
    
    month = date.month
    # Fiscal year: April=Q1, July=Q2, October=Q3, January=Q4
    if 4 <= month <= 6:
        return 1
    elif 7 <= month <= 9:
        return 2
    elif 10 <= month <= 12:
        return 3
    else:  # 1-3 (Jan-Mar)
        return 4

@central_bp.route('/award-bonus/<employee_id>', methods=['POST'])
def award_bonus(employee_id):
    """Award bonus points to an eligible employee or manager"""
    # Check dashboard access
    has_access, current_user = check_central_access()
    
    # Verify user has Central access
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        # Get the bonus points amount and notes from the form
        bonus_points = int(request.form.get('bonus_points', 0))
        notes = request.form.get('notes', '')
        milestones = request.form.get('milestones', '')  # Multiple milestones
        
        if bonus_points <= 0:
            return jsonify({'error': 'Invalid bonus points amount'}), 400
        
        # Get the user (employee or manager)
        user = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Verify user is eligible (employee or manager with manager_id)
        user_role = user.get("role")
        if user_role == "Manager" and not user.get("manager_id"):
            return jsonify({'error': 'Manager must have manager_id to receive bonus'}), 400
        
        # Get current quarter and year
        current_qtr_name, current_qtr, current_year = get_current_quarter()
        
        # Check if bonus already awarded this quarter
        if check_bonus_awarded_for_quarter(employee_id, current_qtr_name):
            return jsonify({'error': 'Bonus already awarded to this user for this quarter'}), 400
        
        # Calculate yearly bonus points to check against limit
        yearly_bonus_points = calculate_yearly_bonus_points(ObjectId(employee_id), current_year)
        config = get_reward_config()
        yearly_bonus_limit = config.get("yearly_bonus_limit", 10000)
        
        # Check if yearly bonus points limit would be exceeded
        if (yearly_bonus_points + bonus_points) > yearly_bonus_limit:
            return jsonify({'error': f'Awarding {bonus_points} bonus points would exceed the yearly bonus limit of {yearly_bonus_limit}'}), 400
        
        # Check if a bonus category exists
        bonus_category = mongo.db.categories.find_one({"code": "bonus_points"})
        
        # If bonus category doesn't exist, create it
        if not bonus_category:
            bonus_category = {
                "name": "Bonus Points",
                "code": "bonus_points",
                "description": "Quarterly bonus points awarded for reaching milestones",
                "frequency": "Quarterly",
                "updated_by": "Central",
                "validator": "Central",
                "grade_limits": {},
                "grade_points": {},
                "points_per_unit": 0,
                "applicability": "All"
            }
            result = mongo.db.categories.insert_one(bonus_category)
            bonus_category_id = result.inserted_id
        else:
            bonus_category_id = bonus_category["_id"]
        
        # Create points request record
        points_request = {
            "user_id": ObjectId(employee_id),
            "category_id": bonus_category_id,
            "points": bonus_points,
            "status": "Approved",
            "request_date": datetime.utcnow(),
            "response_date": datetime.utcnow(),
            "response_notes": f"Milestone bonuses: {milestones} in {current_qtr_name}. {notes}",
            "validator": "Central",
            "validated_by": ObjectId(current_user["_id"]),
            "is_bonus": True
        }
        
        result = mongo.db.points_request.insert_one(points_request)
        
        if result.inserted_id:
            # ✅ CRITICAL FIX: Also insert into points collection so it appears in Total Points History
            points_entry = {
                "user_id": ObjectId(employee_id),
                "category_id": bonus_category_id,
                "points": bonus_points,
                "award_date": datetime.utcnow(),
                "awarded_by": ObjectId(current_user["_id"]),
                "notes": f"Milestone bonuses: {milestones} in {current_qtr_name}. {notes}",
                "is_bonus": True,
                "request_id": result.inserted_id
            }
            mongo.db.points.insert_one(points_entry)
            
            # ✅ SEND REAL-TIME NOTIFICATION TO EMPLOYEE
            try:
                redis_service = current_app.config.get('redis_service')
                if redis_service:
                    # Determine user role for proper room routing
                    user_role_lower = user.get("role", "employee").lower()
                    
                    notification_data = {
                        'title': 'Bonus Points Awarded! 🎉',
                        'message': f'You received {bonus_points} bonus points for {milestones}',
                        'points': bonus_points,
                        'milestones': milestones,
                        'quarter': current_qtr_name,
                        'awarded_by': current_user.get("name", "Central"),
                        'notes': notes,
                        'timestamp': datetime.utcnow().isoformat()
                    }
                    
                    redis_service.publish_event(
                        event_type='bonus_points_awarded',
                        data=notification_data,
                        target_user_id=str(employee_id),
                        target_role=user_role_lower
                    )
                    
                    debug_print(f"✅ Real-time notification sent to {user.get('name')} ({user_role_lower})")
            except Exception as e:
                error_print("Failed to send real-time notification", e)
            
            # Send email notification
            emp_info = {
                "email": user.get("email", ""),
                "name": user.get("name", ""),
                "role": user.get("role", ""),
                "grade": user.get("grade", ""),
                "department": user.get("department", ""),
                "potential_bonus": bonus_points
            }
            send_bonus_eligibility_email(emp_info, current_qtr_name, notes)
            
            return jsonify({
                'success': True,
                'message': f'Awarded {bonus_points} bonus points to {user.get("name")} for {milestones}'
            })
        else:
            return jsonify({'error': 'Failed to award bonus points'}), 500
            
    except Exception as e:
        error_print(f"Error awarding bonus points", e)
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@central_bp.route('/employee-details/<employee_id>', methods=['GET'])
def employee_details(employee_id):
    """✅ FIXED: Get detailed employee information with proper utilization extraction and date filtering support"""
    # Verify user has Central access
    has_access, user = check_central_access()
    
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:

        # Get employee
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        if not employee:
            return jsonify({"error": "Employee not found"}), 404

        # ✅ Check for date filter parameters (from Apply Filters)
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        use_date_filter = False
        qtr_start = None
        qtr_end = None
        quarter = None
        quarter_year = None
        selected_q_num = None  # Initialize here to avoid UnboundLocalError
        
        if start_date_str and end_date_str:
            # Use filtered date range
            try:
                qtr_start = datetime.strptime(start_date_str, '%Y-%m-%d')
                qtr_end = datetime.strptime(end_date_str, '%Y-%m-%d')
                qtr_end = qtr_end.replace(hour=23, minute=59, second=59, microsecond=999999)
                use_date_filter = True
                quarter = f"Filtered ({start_date_str} to {end_date_str})"
                quarter_year = qtr_start.year
            except ValueError:
                pass  # Fall back to quarter-based filtering
        
        if not use_date_filter:
            # Get quarter from query params
            quarter = request.args.get('quarter', '')
            if not quarter:
                current_qtr_name, current_qtr, current_year = get_current_quarter()
                quarter = current_qtr_name
            
            # Parse quarter (e.g., "Q3-2025", "All-2025", "All-all", "Q1-all")
            
            if quarter == "All-all":
                # All years, all quarters - use all available data
                qtr_start = datetime(1900, 1, 1)
                qtr_end = datetime(2100, 12, 31, 23, 59, 59, 999999)
                quarter_year = datetime.now().year
            elif quarter.startswith("All-") and quarter != "All-all":
                # ✅ FIXED: All quarters selected for specific year - use full FISCAL year (April to March next year)
                quarter_year = int(quarter.split('-')[1])
                qtr_start = datetime(quarter_year, 4, 1)  # Fiscal year starts April 1
                qtr_end = datetime(quarter_year + 1, 3, 31, 23, 59, 59, 999999)  # Ends March 31 next year
            elif quarter.endswith("-all"):
                # ✅ Specific quarter across all years (Q1-all, Q2-all, etc.)
                # Extract quarter number and use wide date range, filter by quarter in post-processing
                selected_q_num = int(quarter[1])
                qtr_start = datetime(1900, 1, 1)
                qtr_end = datetime(2100, 12, 31, 23, 59, 59, 999999)
                quarter_year = datetime.now().year
            else:
                # Specific quarter for specific year
                quarter_num = int(quarter[1])
                quarter_year = int(quarter[3:])
                qtr_start, qtr_end = get_quarter_date_range(quarter_num, quarter_year)
        
        # ✅ Get category filter from query params
        selected_category_id = request.args.get('category', '')
        
        # ✅ Get include_bonus filter from query params
        include_bonus = request.args.get('include_bonus', 'false') == 'true'
        
        # ✅ Get all categories from both collections and build merged categories
        categories_hr = list(mongo.db.hr_categories.find())
        categories_old = list(mongo.db.categories.find())
        
        all_categories = {}
        for cat in categories_old:
            all_categories[str(cat["_id"])] = cat
        for cat in categories_hr:
            all_categories[str(cat["_id"])] = cat
        
        # Build merged categories (same logic as leaderboard)
        merged_categories = {}
        for cat in categories_old:
            cat_name = cat.get('name', '')
            if cat_name:
                merged_categories[cat_name] = {
                    'name': cat_name,
                    'code': cat.get('code', ''),
                    'ids': [cat['_id']]
                }
        
        for cat in categories_hr:
            cat_name = cat.get('name', '')
            if cat_name:
                if cat_name in merged_categories:
                    merged_categories[cat_name]['ids'].append(cat['_id'])
                    merged_categories[cat_name]['code'] = cat.get('category_code', merged_categories[cat_name]['code'])
                else:
                    merged_categories[cat_name] = {
                        'name': cat_name,
                        'code': cat.get('category_code', ''),
                        'ids': [cat['_id']]
                    }
        
        # ✅ FIXED: Find ALL utilization category IDs from BOTH collections
        # There may be multiple "Utilization/Billable" categories with different IDs
        utilization_category_ids = []
        
        # Search hr_categories
        for cat in categories_hr:
            cat_name = cat.get("name", "")
            cat_code = cat.get("category_code") or cat.get("code")
            
            if cat_name == "Utilization/Billable" or cat_code == "utilization_billable":
                utilization_category_ids.append(cat["_id"])
        
        # Search categories (old)
        for cat in categories_old:
            cat_name = cat.get("name", "")
            cat_code = cat.get("category_code") or cat.get("code")
            
            if cat_name == "Utilization/Billable" or cat_code == "utilization_billable":
                if cat["_id"] not in utilization_category_ids:  # Avoid duplicates
                    utilization_category_ids.append(cat["_id"])
        
        # Get all points_request records for this employee in the date range
        points_records = []
        total_regular_points = 0
        total_bonus_points = 0
        
        summary_by_category = {}
        bonus_by_category = {}
        
        # ✅ Build query with optional category filter - Use event_date (or request_date as fallback)
        # This matches the logic in central_routes.py and central_routes_optimized.py
        query = {
            "user_id": ObjectId(employee_id),
            "status": "Approved"
        }
        
        # ✅ Add category filter if specified - handle merged category IDs (same as leaderboard)
        selected_category_ids = []
        selected_category_name = ""
        if selected_category_id:
            try:
                # Try to find the category in merged categories
                for cat_name, cat_info in merged_categories.items():
                    if str(cat_info['ids'][0]) == selected_category_id:
                        selected_category_ids = cat_info['ids']
                        selected_category_name = cat_name
                        break
                
                # If not found in merged, use the ID directly
                if not selected_category_ids:
                    selected_category_ids = [ObjectId(selected_category_id)]
                
                # Apply filter using $in to match any of the merged IDs
                query["category_id"] = {"$in": selected_category_ids}
            except:
                pass  # Invalid category ID, ignore filter
        
        # ✅ FETCH from points_request collection ONLY
        # REMOVED: No longer fetching from points collection for consistency with leaderboard and analytics
        all_requests = list(mongo.db.points_request.find(query).sort("request_date", -1))
        
        # No need to track processed request IDs since we're only using one collection
        historical_points = []

        # ✅ Helper function to process a single point record (used for both collections)
        def process_point_record(req, source="points_request"):
            # ✅ Filter by effective date (event_date or request_date as fallback)
            event_date = req.get('event_date')
            request_date = req.get('request_date')
            award_date = req.get('award_date')
            
            effective_date = event_date if event_date and isinstance(event_date, datetime) else \
                            request_date if request_date and isinstance(request_date, datetime) else \
                            award_date if award_date and isinstance(award_date, datetime) else None
            
            # ✅ FIXED: Skip date filtering for "All Years, All Quarters" (matching leaderboard logic)
            # Only filter by date if NOT viewing "All-all"
            if quarter != "All-all":
                # Skip if effective date is not in the quarter range
                if not effective_date or not (qtr_start <= effective_date <= qtr_end):
                    return False
            
            # ✅ Additional filtering for specific quarter across all years (Q1-all, Q2-all, etc.)
            if selected_q_num is not None:
                req_quarter = get_fiscal_quarter_from_date(effective_date)
                if req_quarter != selected_q_num:
                    return False
            
            category_id = req.get("category_id")
            category = all_categories.get(str(category_id), {})
            category_name = category.get("name", "Unknown Category")
            
            # Get category code from either field
            category_code = category.get("category_code") or category.get("code", "")
            
            # Check if utilization category
            is_utilization = False
            utilization_percentage = None
            
            if category_id in utilization_category_ids or category_code == "utilization_billable" or category_name == "Utilization/Billable":
                is_utilization = True

                # ✅ Try multiple field names for utilization value (EXACTLY like employee dashboard)
                utilization_value = None
                
                # Try 1: Direct field
                if 'utilization_value' in req:
                    utilization_value = req.get('utilization_value')

                # Try 2: submission_data.utilization_value
                elif 'submission_data' in req:
                    submission_data = req.get('submission_data', {})
                    if isinstance(submission_data, dict):
                        if 'utilization_value' in submission_data:
                            utilization_value = submission_data.get('utilization_value')

                        elif 'utilization' in submission_data:
                            utilization_value = submission_data.get('utilization')

                # Try 3: points field as fallback
                if utilization_value is None or utilization_value == 0:
                    points = req.get('points', 0)
                    if points > 0 and points <= 100:
                        # Likely already a percentage
                        utilization_value = points / 100.0

                # Convert to percentage
                if utilization_value is not None and utilization_value > 0:
                    if utilization_value <= 1:
                        # It's a decimal (0.85 = 85%)
                        utilization_percentage = round(utilization_value * 100, 2)
                    else:
                        # It's already a percentage (85 = 85%)
                        utilization_percentage = round(utilization_value, 2)
                else:
                    pass  # No utilization value found
            
            points_value = req.get("points", 0)
            is_bonus = req.get("is_bonus", False)
            
            # Build record (only for points_request, not historical)
            if source == "points_request":
                # ✅ NEW: If include_bonus filter is active, only show bonus records
                if include_bonus and not is_bonus:
                    pass  # Skip adding to records, but continue counting
                else:
                    # ✅ FIX: Get notes from multiple possible fields
                    submission_notes = req.get("submission_notes") or req.get("request_notes", "")
                    manager_notes = req.get("response_notes") or req.get("manager_notes", "")
                    
                    # Combine notes for display (prefer manager notes if available, otherwise submission notes)
                    display_notes = manager_notes if manager_notes else submission_notes
                    
                    record = {
                        "date": effective_date.strftime('%d/%m/%Y') if effective_date else 'N/A',
                        "category": category_name,
                        "points": points_value,
                        "is_bonus": is_bonus,
                        "is_utilization": is_utilization,
                        "utilization": f"{utilization_percentage}%" if utilization_percentage is not None else None,
                        "submission_notes": submission_notes,
                        "manager_notes": manager_notes,
                        "notes": display_notes,  # ✅ NEW: Combined notes field for frontend
                        "request_date": request_date,
                        "event_date": event_date,
                        "effective_date": effective_date
                    }
                    
                    points_records.append(record)
            
            # ✅ Count points based on type and filter
            # Skip utilization from point totals
            if not is_utilization:
                # ✅ NEW: If include_bonus filter is active, only count bonus points
                if include_bonus and not is_bonus:
                    return True  # Skip regular points but continue processing
                
                if is_bonus:
                    nonlocal total_bonus_points
                    total_bonus_points += points_value
                    if category_name not in bonus_by_category:
                        bonus_by_category[category_name] = 0
                    bonus_by_category[category_name] += points_value
                else:
                    nonlocal total_regular_points
                    total_regular_points += points_value
                    if category_name not in summary_by_category:
                        summary_by_category[category_name] = 0
                    summary_by_category[category_name] += points_value
            
            return True
        
        # Process points_request collection only
        request_count = 0
        for req in all_requests:
            if process_point_record(req, source="points_request"):
                request_count += 1
        
        # ✅ REMOVED: No longer processing historical points collection
        # Only use points_request for consistency with leaderboard and analytics
        
        # ✅ FIXED: Total points ALWAYS includes both regular and bonus (matching leaderboard)
        # The include_bonus flag only affects the display breakdown, not the total
        total_points_display = total_regular_points + total_bonus_points

        # ✅ Calculate average utilization for the date range (quarter or filtered)
        # ✅ FIXED: Fetch ALL records first (don't filter by date in query)
        average_utilization = 0.0
        if utilization_category_ids:

            # ✅ FIXED: Get ALL utilization records from BOTH collections using ALL category IDs
            # This ensures old records are fetched, then we filter by effective date
            
            # Get from points_request collection
            util_records_pr = list(mongo.db.points_request.find({
                "user_id": ObjectId(employee_id),
                "status": "Approved",
                "category_id": {"$in": utilization_category_ids}
            }))
            
            # ✅ ALSO check points collection (historical data)
            util_records_points = list(mongo.db.points.find({
                "user_id": ObjectId(employee_id),
                "category_id": {"$in": utilization_category_ids}
            }))
            
            # Combine both sources
            all_util_records = util_records_pr + util_records_points
            
            # If no records found, skip this user
            # Skip if no utilization records found
            if len(all_util_records) == 0:
                pass
            
            utilization_records = []
            for util_rec in all_util_records:
                # ✅ Get effective date (handle both collections)
                # points_request: event_date → request_date
                # points: event_date → award_date
                event_date = util_rec.get('event_date')
                request_date = util_rec.get('request_date')
                award_date = util_rec.get('award_date')
                
                effective_date = None
                if event_date and isinstance(event_date, datetime):
                    effective_date = event_date
                elif request_date and isinstance(request_date, datetime):
                    effective_date = request_date
                elif award_date and isinstance(award_date, datetime):
                    effective_date = award_date
                
                # ✅ FIXED: Skip date filtering for "All Years, All Quarters" (matching leaderboard logic)
                if quarter != "All-all":
                    if not effective_date or not (qtr_start <= effective_date <= qtr_end):
                        continue
                
                # ✅ Additional filtering for specific quarter across all years
                if selected_q_num is not None and effective_date:
                    req_quarter = get_fiscal_quarter_from_date(effective_date)
                    if req_quarter != selected_q_num:
                        continue
                
                utilization_records.append(util_rec)
            
            if utilization_records:
                total_util = 0.0
                count_util = 0
                
                for util_rec in utilization_records:
                    # ✅ Extract utilization value (try multiple locations - same as dashboard)
                    util_val = None
                    
                    # Try 1: Direct field
                    if 'utilization_value' in util_rec:
                        util_val = util_rec.get('utilization_value')
                        if util_val is not None and util_val != 0:
                            # Found valid value, use it
                            pass
                        else:
                            util_val = None  # Reset to try other sources
                    
                    # Try 2: submission_data
                    if util_val is None and 'submission_data' in util_rec:
                        submission_data = util_rec.get('submission_data', {})
                        if isinstance(submission_data, dict):
                            util_val = submission_data.get('utilization_value') or submission_data.get('utilization')
                    
                    # Try 3: points field (as percentage) - for old records
                    if util_val is None or util_val == 0:
                        points = util_rec.get('points', 0)
                        if points > 0 and points <= 100:
                            util_val = points / 100.0
                    
                    if util_val is not None and util_val > 0:
                        # Normalize to decimal (0-1 range)
                        if util_val > 1:
                            util_val = util_val / 100.0
                        
                        total_util += util_val
                        count_util += 1
                
                if count_util > 0:
                    average_utilization = round((total_util / count_util) * 100, 2)

        # Get utilization data for each month in the date range (quarter or filtered)
        utilization_months = []
        
        # Determine all months in this date range
        quarter_months = []
        
        # ✅ FIXED: For "All-all", don't generate month list (would be too large)
        # Instead, we'll dynamically build it from actual data
        if quarter != "All-all":
            current_date = qtr_start
            while current_date <= qtr_end:
                month_key = f"{current_date.year}-{current_date.month}"
                quarter_months.append({
                    "key": month_key,
                    "name": current_date.strftime("%B"),
                    "year": current_date.year,
                    "month": current_date.month
                })
                # Move to next month
                if current_date.month == 12:
                    next_month = 1
                    next_year = current_date.year + 1
                else:
                    next_month = current_date.month + 1
                    next_year = current_date.year
                current_date = datetime(next_year, next_month, 1)
        
        # Initialize all months with 0% utilization
        monthly_utilization = {}
        for month in quarter_months:
            monthly_utilization[month["key"]] = 0
        
        if utilization_category_ids:
            # ✅ Use event_date (or request_date as fallback) for filtering
            all_util_records = mongo.db.points_request.find({
                "user_id": ObjectId(employee_id),
                "status": "Approved",
                "category_id": {"$in": utilization_category_ids}
            })
            
            # Process each utilization record
            for record in all_util_records:
                # Filter by effective date
                event_date = record.get('event_date')
                req_date = record.get('request_date')
                effective_date = event_date if event_date and isinstance(event_date, datetime) else req_date
                
                # ✅ FIXED: Skip date filtering for "All Years, All Quarters" (matching leaderboard logic)
                if quarter != "All-all":
                    if not effective_date or not (qtr_start <= effective_date <= qtr_end):
                        continue
                
                # ✅ Additional filtering for specific quarter across all years
                if selected_q_num is not None and effective_date:
                    req_quarter = get_fiscal_quarter_from_date(effective_date)
                    if req_quarter != selected_q_num:
                        continue
                
                record_date = record.get("request_date")
                if record_date:
                    month_key = f"{record_date.year}-{record_date.month}"
                    
                    # ✅ FIXED: For "All-all", dynamically add months as we encounter them
                    if quarter == "All-all" and month_key not in monthly_utilization:
                        quarter_months.append({
                            "key": month_key,
                            "name": record_date.strftime("%B"),
                            "year": record_date.year,
                            "month": record_date.month
                        })
                        monthly_utilization[month_key] = 0
                    
                    # Try to get utilization value
                    utilization_value = None
                    
                    if 'utilization_value' in record:
                        utilization_value = record.get('utilization_value')
                    elif 'submission_data' in record:
                        submission_data = record.get('submission_data', {})
                        if isinstance(submission_data, dict):
                            utilization_value = submission_data.get('utilization_value') or submission_data.get('utilization')
                    
                    if utilization_value is None:
                        points = record.get('points', 0)
                        if points > 0 and points <= 100:
                            utilization_value = points / 100.0
                    
                    if utilization_value is not None and utilization_value > 0:
                        if utilization_value <= 1:
                            percentage = utilization_value * 100
                        else:
                            percentage = utilization_value
                        
                        if month_key in monthly_utilization:
                            monthly_utilization[month_key] = percentage
        
        # Build utilization months data for display
        for month in quarter_months:
            utilization_months.append({
                "month": month["name"],
                "value": round(monthly_utilization[month["key"]], 2),
                "has_data": monthly_utilization[month["key"]] > 0
            })
        
        # ✅ Calculate yearly bonus points (only within date range if filtered)
        if use_date_filter:
            yearly_bonus_points = total_bonus_points  # Only bonuses in filtered range
        else:
            yearly_bonus_points = calculate_yearly_bonus_points(ObjectId(employee_id), quarter_year)
        
        # Get config
        config = get_reward_config()
        
        # Calculate progress percentage
        employee_grade = employee.get("grade", "Unknown")
        grade_targets = config.get("grade_targets", {})
        quarterly_target = grade_targets.get(employee_grade, 0)
        
        # ✅ Adjust target for filtered date ranges
        if use_date_filter:
            days_in_filter = (qtr_end - qtr_start).days + 1
            days_in_year = 365
            yearly_target = int((quarterly_target * 4) * (days_in_filter / days_in_year))
        else:
            yearly_target = quarterly_target * 4
        
        # Calculate progress
        quarterly_progress = 0
        yearly_progress = 0
        if use_date_filter:
            # For filtered view, show single progress against adjusted target
            if yearly_target > 0:
                yearly_progress = round((total_regular_points / yearly_target) * 100, 1)
                quarterly_progress = yearly_progress
        else:
            if quarterly_target > 0:
                quarterly_progress = round((total_regular_points / quarterly_target) * 100, 1)
            if yearly_target > 0:
                yearly_progress = round((total_regular_points / yearly_target) * 100, 1)
        
        # ✅ Format summary by category - ONLY include categories with points > 0
        summary_list = [{"category": cat, "points": pts} for cat, pts in summary_by_category.items() if pts > 0]
        bonus_list = [{"category": cat, "points": pts} for cat, pts in bonus_by_category.items() if pts > 0]
        
        manager_id_val = employee.get("manager_id")
        
        response = {
            "employee": {
                "id": str(employee["_id"]),
                "name": employee.get("name", "Unknown"),
                "email": employee.get("email", ""),
                "grade": employee.get("grade", "Unknown"),
                "department": employee.get("department", "Unknown"),
                "role": employee.get("role", "Employee"),
                "manager_id": str(manager_id_val) if manager_id_val else None
            },
            "quarter": quarter,
            "selected_category": selected_category_name if selected_category_name else None,
            "total_regular_points": total_regular_points,
            "total_bonus_points": total_bonus_points,
            "total_points": total_points_display,
            "include_bonus": include_bonus,
            "average_utilization": average_utilization,
            "yearly_bonus_points": yearly_bonus_points,
            "yearly_bonus_limit": config.get("yearly_bonus_limit", 10000),
            "quarterly_target": quarterly_target,
            "yearly_target": yearly_target,
            "quarterly_progress": quarterly_progress,
            "yearly_progress": yearly_progress,
            "summary_by_category": summary_list,
            "bonus_by_category": bonus_list,
            "points_records": points_records,
            "utilization_months": utilization_months
        }

        return jsonify(response)
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print("=" * 80)
        print("EMPLOYEE DETAILS ERROR:")
        print(f"Employee ID: {employee_id}")
        print(f"Error: {str(e)}")
        print("-" * 80)
        print(error_trace)
        print("=" * 80)
        error_print("Employee details error", e)
        return jsonify({"error": str(e)}), 500


@central_bp.route('/send-bonus-analysis', methods=['POST'])
def send_bonus_analysis():
    """Send bonus analysis emails to all eligible employees for the current quarter"""
    # Check dashboard access
    has_access, current_user = check_central_access()
    
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:
        # Get current quarter and year
        current_qtr_name, current_qtr, current_year = get_current_quarter()
        qtr_start, qtr_end = get_quarter_date_range(current_qtr, current_year)
        
        # Get all eligible users
        all_users = get_eligible_users()
        
        # Get reward configuration
        config = get_reward_config()
        grade_targets = config.get("grade_targets", {})
        
        # Find utilization category
        categories_hr = list(mongo.db.hr_categories.find())
        categories_old = list(mongo.db.categories.find())
        
        utilization_category_id = None
        for cat in categories_hr:
            if cat.get("name") == "Utilization/Billable":
                utilization_category_id = cat["_id"]
                break
        if not utilization_category_id:
            for cat in categories_old:
                if cat.get("name") == "Utilization/Billable":
                    utilization_category_id = cat["_id"]
                    break
        
        eligible_employees = []
        emails_sent = 0
        emails_failed = 0
        
        # Process each user to find eligible ones
        for emp in all_users:
            emp_id = emp["_id"]
            emp_grade = emp.get("grade", "Unknown")
            emp_name = emp.get("name", "Unknown")
            
            # Calculate quarterly points (excluding utilization)
            quarterly_points = 0
            regular_requests = mongo.db.points_request.find({
                "user_id": emp_id,
                "status": "Approved",
                "request_date": {"$gte": qtr_start, "$lte": qtr_end},
                "is_bonus": {"$ne": True}
            })
            
            for req in regular_requests:
                category_id = req.get("category_id")
                if category_id != utilization_category_id:
                    quarterly_points += req.get("points", 0)
            
            # Calculate utilization
            utilization_avg = 0.0
            if utilization_category_id:
                utilization_records = list(mongo.db.points_request.find({
                    "user_id": emp_id,
                    "request_date": {"$gte": qtr_start, "$lte": qtr_end},
                    "status": "Approved",
                    "category_id": utilization_category_id
                }))
                
                if utilization_records:
                    total_util = 0.0
                    count_util = 0
                    
                    for util_rec in utilization_records:
                        util_val = None
                        if 'utilization_value' in util_rec:
                            util_val = util_rec.get('utilization_value')
                        elif 'submission_data' in util_rec:
                            submission_data = util_rec.get('submission_data', {})
                            if isinstance(submission_data, dict):
                                util_val = submission_data.get('utilization_value') or submission_data.get('utilization')
                        
                        if util_val is None or util_val == 0:
                            points = util_rec.get('points', 0)
                            if points > 0 and points <= 100:
                                util_val = points / 100.0
                        
                        if util_val is not None and util_val > 0:
                            if util_val > 1:
                                util_val = util_val / 100.0
                            total_util += util_val
                            count_util += 1
                    
                    if count_util > 0:
                        utilization_avg = round((total_util / count_util) * 100, 2)
            
            # Calculate yearly bonus points
            yearly_bonus_points = calculate_yearly_bonus_points(emp_id, current_year)
            
            # Check if bonus already awarded
            bonus_already_awarded = check_bonus_awarded_for_quarter(emp_id, current_qtr_name)
            
            # Check eligibility
            is_eligible, reason = check_bonus_eligibility(
                quarterly_points,
                emp_grade,
                utilization_avg,
                bonus_already_awarded,
                yearly_bonus_points
            )
            
            if is_eligible:
                # ✅ FIXED: Calculate total FISCAL yearly points for milestone calculation
                total_yearly_points = 0
                yearly_requests = mongo.db.points_request.find({
                    "user_id": emp_id,
                    "status": "Approved",
                    "request_date": {"$gte": datetime(current_year, 4, 1), "$lte": datetime(current_year + 1, 3, 31, 23, 59, 59, 999999)},
                    "is_bonus": {"$ne": True}
                })
                
                for req in yearly_requests:
                    category_id = req.get("category_id")
                    if category_id != utilization_category_id:
                        total_yearly_points += req.get("points", 0)
                
                quarterly_target = grade_targets.get(emp_grade, 0)
                yearly_target = quarterly_target * 4
                
                # Calculate bonus using milestone logic
                milestone_bonus, achieved_milestones = calculate_bonus_points(
                    total_yearly_points,
                    yearly_target,
                    current_qtr
                )
                
                # Check if yearly bonus limit would be exceeded
                if (yearly_bonus_points + milestone_bonus) <= config.get("yearly_bonus_limit", 10000):
                    emp_info = {
                        "email": emp.get("email", ""),
                        "name": emp_name,
                        "role": emp.get("role", "Employee"),
                        "grade": emp_grade,
                        "department": emp.get("department", "Unassigned"),
                        "potential_bonus": milestone_bonus,
                        "quarterly_points": quarterly_points,
                        "utilization": utilization_avg,
                        "achieved_milestones": achieved_milestones
                    }
                    
                    eligible_employees.append(emp_info)
                    
                    # Send email
                    milestones_text = ", ".join([m.get("name", "") for m in achieved_milestones])
                    notes = f"Quarterly Points: {quarterly_points}, Utilization: {utilization_avg}%, Milestones: {milestones_text}"
                    
                    if send_bonus_eligibility_email(emp_info, current_qtr_name, notes):
                        emails_sent += 1
                    else:
                        emails_failed += 1
        
        return jsonify({
            'success': True,
            'message': f'Bonus analysis sent to {emails_sent} eligible employees',
            'emails_sent': emails_sent,
            'emails_failed': emails_failed,
            'eligible_count': len(eligible_employees)
        })
        
    except Exception as e:
        error_print("Error sending bonus analysis", e)
        return jsonify({'error': f'Server error: {str(e)}'}), 500
