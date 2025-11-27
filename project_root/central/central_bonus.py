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
    """✅ FIXED: Get detailed employee information with proper utilization extraction"""
    # Verify user has Central access
    has_access, user = check_central_access()
    
    if not has_access:
        return jsonify({'error': 'Not authorized'}), 403
    
    try:

        # Get employee
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        if not employee:
            return jsonify({"error": "Employee not found"}), 404

        # Get quarter from query params
        quarter = request.args.get('quarter', '')
        if not quarter:
            current_qtr_name, current_qtr, current_year = get_current_quarter()
            quarter = current_qtr_name
        
        # Parse quarter (e.g., "Q3-2025")
        quarter_num = int(quarter[1])
        quarter_year = int(quarter[3:])
        
        qtr_start, qtr_end = get_quarter_date_range(quarter_num, quarter_year)
        
        # ✅ Get all categories from both collections
        categories_hr = list(mongo.db.hr_categories.find())
        categories_old = list(mongo.db.categories.find())
        
        all_categories = {}
        for cat in categories_old:
            all_categories[str(cat["_id"])] = cat
        for cat in categories_hr:
            all_categories[str(cat["_id"])] = cat
        
        # ✅ Find utilization category - PRIORITIZE HR_CATEGORIES!
        utilization_category_id = None
        utilization_category = None
        
        # Priority 1: Search hr_categories first
        for cat in categories_hr:
            cat_name = cat.get("name", "")
            cat_code = cat.get("category_code") or cat.get("code")
            
            if cat_name == "Utilization/Billable":
                utilization_category_id = cat["_id"]
                utilization_category = cat

                break
        
        # Priority 2: Fallback to categories
        if not utilization_category_id:
            for cat in categories_old:
                cat_name = cat.get("name", "")
                cat_code = cat.get("category_code") or cat.get("code")
                
                if cat_name == "Utilization/Billable":
                    utilization_category_id = cat["_id"]
                    utilization_category = cat
                    break
        
        if not utilization_category_id:
            pass  # Utilization category not found
        
        # Get all points_request records for this employee in this quarter
        points_records = []
        total_regular_points = 0
        total_bonus_points = 0
        
        summary_by_category = {}
        bonus_by_category = {}
        
        # Query with request_date only (simpler, more reliable)
        all_requests = mongo.db.points_request.find({
            "user_id": ObjectId(employee_id),
            "status": "Approved",
            "request_date": {"$gte": qtr_start, "$lte": qtr_end}
        }).sort("request_date", -1)

        request_count = 0
        for req in all_requests:
            request_count += 1
            category_id = req.get("category_id")
            category = all_categories.get(str(category_id), {})
            category_name = category.get("name", "Unknown Category")
            
            # Get category code from either field
            category_code = category.get("category_code") or category.get("code", "")
            
            # Check if utilization category
            is_utilization = False
            utilization_percentage = None
            
            if category_id == utilization_category_id or category_code == "utilization_billable" or category_name == "Utilization/Billable":
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
            request_date = req.get("request_date")
            
            # Build record
            record = {
                "date": request_date.strftime('%d/%m/%Y') if request_date else 'N/A',
                "category": category_name,
                "points": points_value,
                "is_bonus": is_bonus,
                "is_utilization": is_utilization,
                "utilization": f"{utilization_percentage}%" if utilization_percentage is not None else None,
                "submission_notes": req.get("submission_notes", ""),
                "manager_notes": req.get("response_notes", ""),
                "request_date": request_date
            }
            
            points_records.append(record)
            
            # Count points (skip utilization for point totals)
            if is_bonus:
                total_bonus_points += points_value
                if category_name not in bonus_by_category:
                    bonus_by_category[category_name] = 0
                bonus_by_category[category_name] += points_value
            elif not is_utilization:
                total_regular_points += points_value
                if category_name not in summary_by_category:
                    summary_by_category[category_name] = 0
                summary_by_category[category_name] += points_value

        # ✅ Calculate average utilization for the quarter
        average_utilization = 0.0
        if utilization_category_id:

            # Get all utilization records for this quarter
            utilization_records = list(mongo.db.points_request.find({
                "user_id": ObjectId(employee_id),
                "request_date": {"$gte": qtr_start, "$lte": qtr_end},
                "status": "Approved",
                "category_id": utilization_category_id
            }))
            
            if utilization_records:
                total_util = 0.0
                count_util = 0
                
                for util_rec in utilization_records:
                    # Extract utilization value
                    util_val = None
                    
                    if 'utilization_value' in util_rec:
                        util_val = util_rec.get('utilization_value')
                    elif 'submission_data' in util_rec:
                        submission_data = util_rec.get('submission_data', {})
                        if isinstance(submission_data, dict):
                            util_val = submission_data.get('utilization_value') or submission_data.get('utilization')
                    
                    if util_val is None:
                        points = util_rec.get('points', 0)
                        if points > 0 and points <= 100:
                            util_val = points / 100.0
                    
                    if util_val is not None and util_val > 0:
                        if util_val > 1:
                            util_val = util_val / 100.0  # Convert percentage to decimal
                        
                        total_util += util_val
                        count_util += 1
                
                if count_util > 0:
                    average_utilization = round((total_util / count_util) * 100, 2)

        # Get utilization data for each month in the quarter
        utilization_months = []
        
        # Determine all months in this quarter
        quarter_months = []
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
        
        if utilization_category_id:
            utilization_records = mongo.db.points_request.find({
                "user_id": ObjectId(employee_id),
                "request_date": {"$gte": qtr_start, "$lte": qtr_end},
                "status": "Approved",
                "category_id": utilization_category_id
            })
            
            # Process each utilization record
            for record in utilization_records:
                record_date = record.get("request_date")
                if record_date:
                    month_key = f"{record_date.year}-{record_date.month}"
                    
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
        
        # Calculate yearly bonus points
        yearly_bonus_points = calculate_yearly_bonus_points(ObjectId(employee_id), quarter_year)
        
        # Get config
        config = get_reward_config()
        
        # Format summary by category
        summary_list = [{"category": cat, "points": pts} for cat, pts in summary_by_category.items()]
        bonus_list = [{"category": cat, "points": pts} for cat, pts in bonus_by_category.items()]
        
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
            "total_regular_points": total_regular_points,
            "total_bonus_points": total_bonus_points,
            "average_utilization": average_utilization,
            "yearly_bonus_points": yearly_bonus_points,
            "yearly_bonus_limit": config.get("yearly_bonus_limit", 10000),
            "summary_by_category": summary_list,
            "bonus_by_category": bonus_list,
            "points_records": points_records,
            "utilization_months": utilization_months
        }

        return jsonify(response)
        
    except Exception as e:
        import traceback


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
                # Calculate total yearly points for milestone calculation
                total_yearly_points = 0
                yearly_requests = mongo.db.points_request.find({
                    "user_id": emp_id,
                    "status": "Approved",
                    "request_date": {"$gte": datetime(current_year, 1, 1), "$lte": datetime(current_year, 12, 31)},
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
