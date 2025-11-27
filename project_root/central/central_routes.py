from flask import render_template, request, redirect, session, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
from . import central_bp
from .central_utils import (
    check_central_access, get_eligible_users, get_current_quarter,
    get_quarter_date_range, get_quarters_in_year, get_reward_config,
    calculate_yearly_bonus_points,
    check_bonus_eligibility, calculate_bonus_points, check_bonus_awarded_for_quarter,
    debug_print, error_print
)

@central_bp.route('/dashboard', methods=['GET'])
def dashboard():
    """Main central dashboard view showing all employees and managers with assigned managers"""
    # Check dashboard access
    has_access, user = check_central_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the Central dashboard', 'danger')
        return redirect(url_for('auth.login'))

    try:
        # Get current quarter and year
        current_qtr_name, current_qtr, current_year = get_current_quarter()

        # Get date range for current quarter
        qtr_start, qtr_end = get_quarter_date_range(current_qtr, current_year)

        # Get all quarters in current year up to now
        quarters = get_quarters_in_year(current_year)

        # Get all eligible users (employees + managers with assigned managers)
        all_users = get_eligible_users()
        
        # Count employees and managers separately
        employees = [u for u in all_users if u.get("role") == "Employee"]
        managers_with_assigned = [u for u in all_users if u.get("role") == "Manager"]

        # Get all categories from BOTH collections
        categories_hr = list(mongo.db.hr_categories.find())
        categories_old = list(mongo.db.categories.find())
        
        all_categories = {}
        for cat in categories_old:
            all_categories[str(cat["_id"])] = cat
        for cat in categories_hr:
            all_categories[str(cat["_id"])] = cat
        
        categories = list(all_categories.values())
        category_map = all_categories

        # FIND UTILIZATION CATEGORY - PRIORITIZE HR_CATEGORIES
        utilization_category_id = None
        
        # Priority 1: Search hr_categories first (newer location)
        for cat in categories_hr:
            if cat.get("name") == "Utilization/Billable":
                utilization_category_id = cat["_id"]
                break
        
        # Priority 2: Fallback to categories (older location)
        if not utilization_category_id:
            for cat in categories_old:
                if cat.get("name") == "Utilization/Billable":
                    utilization_category_id = cat["_id"]
                    break

        # Get reward configuration for grade targets
        config = get_reward_config()

        # Process each user (employee or manager with assigned manager) to calculate their points and eligibility
        employee_data = []
        eligible_employees = []
        non_eligible_employees = []

        for emp in all_users:
            emp_id = emp["_id"]
            emp_grade = emp.get("grade", "Unknown")
            emp_department = emp.get("department", "Unassigned")
            emp_role = emp.get("role", "Employee")
            emp_name = emp.get("name", "Unknown")

            # Initialize data for this user with all fields
            emp_info = {
                "id": str(emp_id),
                "name": emp_name,
                "email": emp.get("email", ""),
                "grade": emp_grade,
                "department": emp_department,
                "role": emp_role,
                "manager_id": emp.get("manager_id", None),
                "total_points": 0,
                "quarterly_points": 0,
                "bonus_points": 0,
                "yearly_bonus_points": 0,
                "quarterly_bonus": 0,
                "all_quarters": {},
                "billable_utilization": 0,
                "categories_breakdown": {},
                "categories_by_quarter": {},
                "yearly_progress": 0,
                "quarterly_progress": 0,
                "is_eligible": False,
                "eligibility_reason": None,
                "potential_bonus": 0,
                "quarterly_target": 0,
                "yearly_target": 0,
                "achieved_milestones": [],
                "bonus_already_awarded": False
            }

            for q in quarters:
                emp_info["all_quarters"][q["name"]] = {"regular": 0, "bonus": 0}
                emp_info["categories_by_quarter"][q["name"]] = {}

            for quarter in quarters:
                quarter_start = quarter["start_date"]
                quarter_end = quarter["end_date"]
                quarter_name = quarter["name"]

                regular_requests = mongo.db.points_request.find({
                    "user_id": emp_id,
                    "status": "Approved",
                    "request_date": {"$gte": quarter_start, "$lte": quarter_end},
                    "is_bonus": {"$ne": True}
                })

                for req in regular_requests:
                    category_id = req.get("category_id")
                    
                    # Skip utilization records for points calculation
                    if category_id == utilization_category_id:
                        continue
                    
                    category = category_map.get(str(category_id), {})
                    if category.get("name") == "Utilization/Billable":
                        continue
                    
                    points_value = req.get("points", 0)
                    emp_info["total_points"] += points_value
                    emp_info["all_quarters"][quarter_name]["regular"] += points_value
                    if quarter_name == current_qtr_name:
                        emp_info["quarterly_points"] += points_value
                    category_id_str = str(category_id)
                    category_name = category.get("name", "Unknown Category")
                    
                    # Overall categories breakdown
                    if category_id_str not in emp_info["categories_breakdown"]:
                        emp_info["categories_breakdown"][category_id_str] = {
                            "name": category_name,
                            "points": 0
                        }
                    emp_info["categories_breakdown"][category_id_str]["points"] += points_value
                    
                    # Categories by quarter
                    if category_id_str not in emp_info["categories_by_quarter"][quarter_name]:
                        emp_info["categories_by_quarter"][quarter_name][category_id_str] = {
                            "name": category_name,
                            "points": 0
                        }
                    emp_info["categories_by_quarter"][quarter_name][category_id_str]["points"] += points_value

                bonus_requests = mongo.db.points_request.find({
                    "user_id": emp_id,
                    "status": "Approved",
                    "request_date": {"$gte": quarter_start, "$lte": quarter_end},
                    "is_bonus": True
                })

                for req in bonus_requests:
                    points_value = req.get("points", 0)
                    category_id = req.get("category_id")
                    emp_info["bonus_points"] += points_value
                    emp_info["all_quarters"][quarter_name]["bonus"] += points_value
                    if quarter_name == current_qtr_name:
                        emp_info["quarterly_bonus"] += points_value
                    category_id_str = str(category_id)
                    category = category_map.get(category_id_str, {})
                    category_name = category.get("name", "Unknown Category")
                    
                    # Overall categories breakdown
                    if category_id_str not in emp_info["categories_breakdown"]:
                        emp_info["categories_breakdown"][category_id_str] = {
                            "name": category_name,
                            "points": 0
                        }
                    emp_info["categories_breakdown"][category_id_str]["points"] += points_value
                    
                    # Categories by quarter (bonus)
                    if category_id_str not in emp_info["categories_by_quarter"][quarter_name]:
                        emp_info["categories_by_quarter"][quarter_name][category_id_str] = {
                            "name": category_name,
                            "points": 0
                        }
                    emp_info["categories_by_quarter"][quarter_name][category_id_str]["points"] += points_value

            # CALCULATE UTILIZATION INLINE
            utilization_avg = 0.0
            
            if utilization_category_id:
                try:
                    # Get all utilization records for current quarter
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
                            # Extract utilization value (try multiple locations)
                            util_val = None
                            
                            # Try 1: Direct field
                            if 'utilization_value' in util_rec:
                                util_val = util_rec.get('utilization_value')
                            
                            # Try 2: submission_data
                            elif 'submission_data' in util_rec:
                                submission_data = util_rec.get('submission_data', {})
                                if isinstance(submission_data, dict):
                                    util_val = submission_data.get('utilization_value') or submission_data.get('utilization')
                            
                            # Try 3: points field
                            if util_val is None or util_val == 0:
                                points = util_rec.get('points', 0)
                                if points > 0 and points <= 100:
                                    util_val = points / 100.0
                            
                            if util_val is not None and util_val > 0:
                                # Convert to decimal if it's a percentage
                                if util_val > 1:
                                    util_val = util_val / 100.0
                                
                                total_util += util_val
                                count_util += 1
                        
                        if count_util > 0:
                            utilization_avg = round((total_util / count_util) * 100, 2)
                
                except Exception as e:
                    error_print(f"Error calculating utilization for {emp_name}", e)
                    utilization_avg = 0.0
            
            emp_info["billable_utilization"] = utilization_avg

            yearly_bonus_points = calculate_yearly_bonus_points(emp_id, current_year)
            emp_info["yearly_bonus_points"] = yearly_bonus_points

            grade_targets = config.get("grade_targets", {})
            quarterly_target = grade_targets.get(emp_grade, 0)
            yearly_target = quarterly_target * 4

            bonus_already_awarded = check_bonus_awarded_for_quarter(emp_id, current_qtr_name)

            is_eligible, reason = check_bonus_eligibility(
                emp_info["quarterly_points"],
                emp_grade,
                utilization_avg,
                bonus_already_awarded,
                yearly_bonus_points
            )

            potential_bonus = 0
            achieved_milestones = []

            # Calculate bonus using the cumulative milestone logic
            if is_eligible:
                milestone_bonus, achieved_milestones = calculate_bonus_points(
                    emp_info["total_points"],
                    yearly_target,
                    current_qtr
                )
                potential_bonus = milestone_bonus
                
                # Check if yearly bonus limit would be exceeded
                if (yearly_bonus_points + potential_bonus) > config.get("yearly_bonus_limit", 10000):
                    is_eligible = False
                    reason = f"Bonus would exceed yearly limit: {yearly_bonus_points}/{config.get('yearly_bonus_limit', 10000)}"

            emp_info["is_eligible"] = is_eligible
            emp_info["eligibility_reason"] = reason if not is_eligible else None
            emp_info["potential_bonus"] = potential_bonus
            emp_info["quarterly_target"] = quarterly_target
            emp_info["yearly_target"] = yearly_target
            emp_info["achieved_milestones"] = achieved_milestones
            emp_info["bonus_already_awarded"] = bonus_already_awarded

            emp_info["quarterly_progress"] = round((emp_info["quarterly_points"] / quarterly_target * 100) if quarterly_target > 0 else 0, 1)
            emp_info["yearly_progress"] = round((emp_info["total_points"] / yearly_target * 100) if yearly_target > 0 else 0, 1)

            if is_eligible:
                eligible_employees.append(emp_info)
            else:
                non_eligible_employees.append(emp_info)

            employee_data.append(emp_info)

        # Department-based grouping
        departments_data = {}
        for emp in employee_data:
            dept = emp["department"]
            if dept not in departments_data:
                departments_data[dept] = {
                    "name": dept,
                    "employees": [],
                    "total_points": 0,
                    "eligible_count": 0,
                    "employee_count": 0,
                    "manager_count": 0
                }
            departments_data[dept]["employees"].append(emp)
            departments_data[dept]["total_points"] += emp["total_points"]
            if emp["is_eligible"]:
                departments_data[dept]["eligible_count"] += 1
            
            # Count employees vs managers
            if emp["role"] == "Employee":
                departments_data[dept]["employee_count"] += 1
            else:
                departments_data[dept]["manager_count"] += 1
        
        # Convert to list and sort by total points
        departments_list = list(departments_data.values())
        departments_list.sort(key=lambda x: x["total_points"], reverse=True)

        employee_data.sort(key=lambda x: x["total_points"], reverse=True)
        eligible_employees.sort(key=lambda x: x["total_points"], reverse=True)
        non_eligible_employees.sort(key=lambda x: x["total_points"], reverse=True)

        return render_template(
            'central_dashboard.html',
            user=user,
            quarters=quarters,
            current_quarter=current_qtr_name,
            employee_data=employee_data,
            eligible_employees=eligible_employees,
            non_eligible_employees=non_eligible_employees,
            departments=departments_list,
            categories=categories,
            config=config,
            total_employees=len(employees),
            total_managers=len(managers_with_assigned)
        )

    except Exception as e:
        error_print("Dashboard error", e)
        flash('An error occurred while loading the dashboard', 'danger')
        return redirect(url_for('auth.login'))

# DEPRECATED: Old leaderboard route removed - replaced by optimized version in central_leaderboard.py
# The old implementation had N+1 query problems causing slow performance (8-30 seconds)
# New implementation uses batch queries and is 85-90% faster (1-2 seconds)

@central_bp.route('/export-data', methods=['GET'])
def export_data():
    """Export data page with filters and date range"""
    has_access, user = check_central_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the Central dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get current quarter and year
        current_qtr_name, current_qtr, current_year = get_current_quarter()
        
        # Get all eligible users
        all_users = get_eligible_users()
        
        # Get reward configuration
        config = get_reward_config()
        
        # Get all quarters in current year
        quarters = get_quarters_in_year(current_year)
        
        # Process employee data (simplified for export view)
        employee_data = []
        
        for emp in all_users:
            emp_id = emp["_id"]
            emp_grade = emp.get("grade", "Unknown")
            
            emp_info = {
                "id": str(emp_id),
                "name": emp.get("name", "Unknown"),
                "email": emp.get("email", ""),
                "grade": emp_grade,
                "department": emp.get("department", "Unassigned"),
                "total_points": 0,
                "quarterly_points": 0,
                "bonus_points": 0,
                "yearly_bonus_points": 0,
                "quarterly_bonus": 0,
                "all_quarters": {},
                "status": "not-eligible"
            }
            
            # Initialize quarters
            for q in quarters:
                emp_info["all_quarters"][q["name"]] = {"regular": 0, "bonus": 0}
            
            # Get points for each quarter
            for quarter in quarters:
                quarter_start = quarter["start_date"]
                quarter_end = quarter["end_date"]
                quarter_name = quarter["name"]
                
                # Regular points
                regular_requests = mongo.db.points_request.find({
                    "user_id": emp_id,
                    "status": "Approved",
                    "request_date": {"$gte": quarter_start, "$lte": quarter_end},
                    "is_bonus": {"$ne": True}
                })
                
                for req in regular_requests:
                    points_value = req.get("points", 0)
                    emp_info["total_points"] += points_value
                    emp_info["all_quarters"][quarter_name]["regular"] += points_value
                    if quarter_name == current_qtr_name:
                        emp_info["quarterly_points"] += points_value
                
                # Bonus points
                bonus_requests = mongo.db.points_request.find({
                    "user_id": emp_id,
                    "status": "Approved",
                    "request_date": {"$gte": quarter_start, "$lte": quarter_end},
                    "is_bonus": True
                })
                
                for req in bonus_requests:
                    points_value = req.get("points", 0)
                    emp_info["bonus_points"] += points_value
                    emp_info["all_quarters"][quarter_name]["bonus"] += points_value
                    if quarter_name == current_qtr_name:
                        emp_info["quarterly_bonus"] += points_value
            
            # Calculate yearly bonus
            yearly_bonus_points = calculate_yearly_bonus_points(emp_id, current_year)
            emp_info["yearly_bonus_points"] = yearly_bonus_points
            
            # Determine eligibility status
            grade_targets = config.get("grade_targets", {})
            quarterly_target = grade_targets.get(emp_grade, 0)
            
            if emp_info["quarterly_points"] >= quarterly_target:
                emp_info["status"] = "eligible"
            
            employee_data.append(emp_info)
        
        # Sort by total points
        employee_data.sort(key=lambda x: x["total_points"], reverse=True)
        
        return render_template(
            'central_export_data.html',
            user=user,
            employee_data=employee_data,
            current_quarter=current_qtr_name,
            config=config
        )
        
    except Exception as e:
        error_print("Export data page error", e)
        flash('An error occurred while loading the export data page', 'danger')
        return redirect(url_for('central.dashboard'))

@central_bp.route('/analytics', methods=['GET'])
def analytics():
    """Analytics dashboard with charts and statistics"""
    # Check dashboard access
    has_access, user = check_central_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the Central dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get current quarter and year
        current_qtr_name, current_qtr, current_year = get_current_quarter()
        
        # Get date range for current quarter
        qtr_start, qtr_end = get_quarter_date_range(current_qtr, current_year)
        
        # Get all eligible users
        all_users = get_eligible_users()
        
        # Get all reward categories from both collections
        categories_hr = list(mongo.db.hr_categories.find())
        categories_old = list(mongo.db.categories.find())
        
        all_categories = {}
        for cat in categories_old:
            all_categories[str(cat["_id"])] = cat
        for cat in categories_hr:
            all_categories[str(cat["_id"])] = cat
        
        categories = list(all_categories.values())
        category_map = all_categories
        
        # Find utilization category - prioritize hr_categories
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
        
        # Get reward configuration
        config = get_reward_config()
        
        # Process each user to calculate their points
        employee_data = []
        
        for emp in all_users:
            emp_id = emp["_id"]
            emp_grade = emp.get("grade", "Unknown")
            emp_department = emp.get("department", "Unassigned")
            emp_role = emp.get("role", "Employee")
            
            # Initialize data for this user
            emp_info = {
                "id": str(emp_id),
                "name": emp.get("name", "Unknown"),
                "email": emp.get("email", ""),
                "grade": emp_grade,
                "department": emp_department,
                "role": emp_role,
                "total_points": 0,
                "quarterly_points": 0,
                "categories_breakdown": {}
            }
            
            # Get all approved points for this user
            all_requests = mongo.db.points_request.find({
                "user_id": emp_id,
                "status": "Approved",
                "is_bonus": {"$ne": True}  # Exclude bonus points for analytics
            })
            
            for req in all_requests:
                category_id = req.get("category_id")
                
                # Skip utilization records
                if category_id == utilization_category_id:
                    continue
                
                category = category_map.get(str(category_id), {})
                if category.get("name") == "Utilization/Billable":
                    continue
                
                points_value = req.get("points", 0)
                request_date = req.get("request_date")
                
                # Add to total points
                emp_info["total_points"] += points_value
                
                # Add to quarterly points if in current quarter
                if request_date and qtr_start <= request_date <= qtr_end:
                    emp_info["quarterly_points"] += points_value
                
                # Add to category breakdown
                category_id_str = str(category_id)
                if category_id_str not in emp_info["categories_breakdown"]:
                    emp_info["categories_breakdown"][category_id_str] = {
                        "name": category.get("name", "Unknown Category"),
                        "points": 0
                    }
                emp_info["categories_breakdown"][category_id_str]["points"] += points_value
            
            # Only include users with points
            if emp_info["total_points"] > 0:
                employee_data.append(emp_info)
        
        # Sort by total points
        employee_data.sort(key=lambda x: x["total_points"], reverse=True)
        
        return render_template(
            'central_analytics.html',
            user=user,
            employee_data=employee_data,
            categories=categories,
            config=config,
            current_quarter=current_qtr_name
        )
        
    except Exception as e:
        error_print("Analytics error", e)
        flash('An error occurred while loading analytics', 'danger')
        return redirect(url_for('central.dashboard'))

@central_bp.route('/api/central-points-summary', methods=['GET'])
def central_points_summary():
    """API endpoint for central points summary"""
    has_access, user = check_central_access()
    
    if not has_access:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        current_quarter = 2
        fiscal_year = 2025
        qtr_name = f"Q{current_quarter}-{fiscal_year}"
        qtr_start, qtr_end = get_quarter_date_range(current_quarter, fiscal_year)

        users = mongo.db.users.find({"role": {"$in": ["Employee", "Manager"]}})
        config = get_reward_config()
        grade_targets = config.get("grade_targets", {})
        yearly_bonus_limit = config.get("yearly_bonus_limit", 10000)

        data = []

        for user_doc in users:
            user_id = user_doc["_id"]
            grade = user_doc.get("grade", "").upper()
            name = user_doc.get("name", "")
            email = user_doc.get("email", "")
            department = user_doc.get("department", "")
            role = user_doc.get("role", "")

            total = 0
            quarterly = 0
            bonus = 0
            yearly_bonus = 0

            approved = mongo.db.points_request.find({
                "user_id": user_id,
                "status": "Approved"
            })

            for req in approved:
                pts = req.get("points", 0)
                is_bonus = req.get("is_bonus", False)
                dt = req.get("request_date")

                if is_bonus:
                    bonus += pts
                    if dt and dt.year == fiscal_year:
                        yearly_bonus += pts
                else:
                    total += pts
                    if dt and qtr_start <= dt <= qtr_end:
                        quarterly += pts

            target = grade_targets.get(grade, 0)
            yearly_target = target * 4
            progress_q = round((quarterly / target) * 100, 1) if target else 0
            progress_y = round((total / yearly_target) * 100, 1) if yearly_target else 0

            eligible = quarterly >= target and (grade == "A1" or bonus >= 0) and yearly_bonus < yearly_bonus_limit
            status = "Eligible" if eligible else "Not Eligible"

            data.append({
                "name": name,
                "email": email,
                "grade": grade,
                "department": department,
                "yearly_target": yearly_target,
                "quarterly_target": target,
                "quarterly_points": quarterly,
                "yearly_bonus_points": yearly_bonus,
                "progress_quarter": progress_q,
                "progress_year": progress_y,
                "q1": 0,
                "q2": quarterly,
                "status": status
            })

        return jsonify({"success": True, "data": data})
    
    except Exception as e:
        error_print("Error in central points summary", e)
        return jsonify({"error": "Internal server error"}), 500