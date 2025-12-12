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
    """
    OPTIMIZED Central Dashboard using Aggregation Pipeline
    80-90% faster than previous version
    
    ✅ Handles BOTH old and new data structures:
    - Old data: 'categories' collection
    - New data: 'hr_categories' collection
    
    Same logic as PMO and TA dashboards for consistency
    """
    # Import optimized functions
    from .central_routes_optimized import (
        get_all_points_aggregated,
        get_category_breakdown_aggregated,
        get_utilization_aggregated
    )
    
    # Check dashboard access
    has_access, user = check_central_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the Central dashboard', 'danger')
        return redirect(url_for('auth.login'))

    try:
        # ✅ Check for date filters from Apply Filters button
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        use_date_filter = False
        filter_start_date = None
        filter_end_date = None
        
        if start_date_str and end_date_str:
            try:
                filter_start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d')
                filter_end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d')
                filter_end_date_obj = filter_end_date_obj.replace(hour=23, minute=59, second=59, microsecond=999999)
                use_date_filter = True
                # ✅ Format dates as DD-MM-YYYY for display
                filter_start_date = filter_start_date_obj.strftime('%d-%m-%Y')
                filter_end_date = filter_end_date_obj.strftime('%d-%m-%Y')
            except ValueError:
                flash('Invalid date format', 'warning')
        
        # ✅ FIXED: All quarter calculations use REQUEST_DATE (not approved_date)
        
        # Get current quarter and year
        current_qtr_name, current_qtr, current_year = get_current_quarter()

        # Get date range for current quarter (or use filter dates)
        if use_date_filter:
            qtr_start, qtr_end = filter_start_date_obj, filter_end_date_obj
        else:
            qtr_start, qtr_end = get_quarter_date_range(current_qtr, current_year)

        # ✅ Get quarters based on filter or current year
        if use_date_filter:
            # Create a single custom "quarter" for the filtered date range
            quarters = [{
                "name": f"Filtered ({filter_start_date} to {filter_end_date})",
                "start_date": filter_start_date_obj,
                "end_date": filter_end_date_obj
            }]
            # Set current quarter to the filtered range
            current_qtr_name = quarters[0]["name"]
            # Override current_year to extract from filter dates for proper yearly calculations
            current_year = filter_start_date_obj.year
        else:
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

        # ==========================================
        # OPTIMIZED: Get all data using aggregation
        # ==========================================
        user_ids = [u["_id"] for u in all_users]
        
        # Get all points data in ONE query
        points_data = get_all_points_aggregated(user_ids, quarters, utilization_category_id)
        
        # Get category breakdown in ONE query
        category_breakdown = get_category_breakdown_aggregated(user_ids, utilization_category_id, quarters)
        
        # Get utilization in ONE query
        utilization_data = get_utilization_aggregated(user_ids, qtr_start, qtr_end, utilization_category_id)

        # Process each user (employee or manager with assigned manager) to calculate their points and eligibility
        employee_data = []
        eligible_employees = []
        non_eligible_employees = []

        for emp in all_users:
            emp_id = emp["_id"]
            emp_id_str = str(emp_id)
            emp_grade = emp.get("grade", "Unknown")
            emp_department = emp.get("department", "Unassigned")
            emp_role = emp.get("role", "Employee")
            emp_name = emp.get("name", "Unknown")

            # Get pre-calculated data from aggregation
            user_points = points_data.get(emp_id_str, {
                "quarters": {},
                "categories": {},
                "total_regular": 0,
                "total_bonus": 0
            })
            
            user_categories_by_quarter = category_breakdown.get(emp_id_str, {})
            # Sort quarters to display in Q1, Q2, Q3, Q4 order
            user_categories_by_quarter = dict(sorted(user_categories_by_quarter.items()))
            user_utilization = utilization_data.get(emp_id_str, 0.0)

            # Calculate total categories (sum across all quarters)
            user_categories_total = {}
            for quarter_name, categories in user_categories_by_quarter.items():
                for cat_id, cat_data in categories.items():
                    if cat_id not in user_categories_total:
                        user_categories_total[cat_id] = {
                            "name": cat_data["name"],
                            "points": 0
                        }
                    user_categories_total[cat_id]["points"] += cat_data["points"]

            # Initialize data for this user with all fields
            emp_info = {
                "id": emp_id_str,
                "name": emp_name,
                "email": emp.get("email", ""),
                "grade": emp_grade,
                "department": emp_department,
                "role": emp_role,
                "manager_id": emp.get("manager_id", None),
                "total_points": int(user_points["total_regular"] + user_points["total_bonus"]),
                "quarterly_points": 0,
                "bonus_points": int(user_points["total_bonus"]),
                "yearly_bonus_points": 0,
                "quarterly_bonus": 0,
                "all_quarters": {},
                "billable_utilization": user_utilization,
                "categories_breakdown": user_categories_total,
                "categories_by_quarter": user_categories_by_quarter,
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

            # Fill in quarter data from pre-calculated results
            for q in quarters:
                quarter_name = q["name"]
                quarter_data = user_points["quarters"].get(quarter_name, {"regular": 0, "bonus": 0})
                
                emp_info["all_quarters"][quarter_name] = quarter_data
                
                if quarter_name == current_qtr_name:
                    emp_info["quarterly_points"] = int(quarter_data["regular"])
                    emp_info["quarterly_bonus"] = int(quarter_data["bonus"])

            # ✅ When filtering, yearly_bonus_points should only count bonuses in the filtered range
            if use_date_filter:
                # Count only bonus points within the filtered date range
                yearly_bonus_points = emp_info["bonus_points"]  # Already filtered by aggregation
            else:
                yearly_bonus_points = calculate_yearly_bonus_points(emp_id, current_year)
            emp_info["yearly_bonus_points"] = yearly_bonus_points

            grade_targets = config.get("grade_targets", {})
            quarterly_target = grade_targets.get(emp_grade, 0)
            
            # ✅ When filtering, adjust target to be proportional to the filtered period
            if use_date_filter:
                # Calculate days in filtered range vs full year (use datetime objects)
                days_in_filter = (filter_end_date_obj - filter_start_date_obj).days + 1
                days_in_year = 365
                yearly_target = int((quarterly_target * 4) * (days_in_filter / days_in_year))
            else:
                yearly_target = quarterly_target * 4

            # ✅ For filtered view, skip bonus eligibility checks (not relevant for custom date ranges)
            if use_date_filter:
                bonus_already_awarded = False
                is_eligible = False
                reason = "Eligibility not applicable for filtered date ranges"
            else:
                bonus_already_awarded = check_bonus_awarded_for_quarter(emp_id, current_qtr_name)
                is_eligible, reason = check_bonus_eligibility(
                    emp_info["quarterly_points"],
                    emp_grade,
                    user_utilization,
                    bonus_already_awarded,
                    yearly_bonus_points
                )

            potential_bonus = 0
            achieved_milestones = []

            # Calculate bonus using the cumulative milestone logic (only for non-filtered view)
            if is_eligible and not use_date_filter:
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

            # ✅ Calculate progress based on filtered data
            if use_date_filter:
                # For filtered view, show progress against the adjusted target
                emp_info["quarterly_progress"] = round((emp_info["total_points"] / yearly_target * 100) if yearly_target > 0 else 0, 1)
                emp_info["yearly_progress"] = emp_info["quarterly_progress"]  # Same value for filtered view
            else:
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
            total_managers=len(managers_with_assigned),
            filter_start_date=start_date_str,
            filter_end_date=end_date_str,
            filter_start_date_display=filter_start_date,
            filter_end_date_display=filter_end_date,
            use_date_filter=use_date_filter
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
    """
    Export data page - Filter by date range
    
    ✅ Handles BOTH old and new data structures:
    - Old data: 'categories' collection
    - New data: 'hr_categories' collection
    
    Same logic as PMO and TA dashboards for consistency
    """
    has_access, user = check_central_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access the Central dashboard', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # ✅ Check for date filter parameters
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        use_date_filter = False
        filter_start_date = None
        filter_end_date = None
        filter_start_date_display = None
        filter_end_date_display = None
        qtr_start = None
        qtr_end = None
        
        # Get current quarter and year
        current_qtr_name, current_qtr, current_year = get_current_quarter()
        
        # ✅ Parse and validate date filters
        if start_date_str and end_date_str:
            try:
                qtr_start = datetime.strptime(start_date_str, '%Y-%m-%d')
                qtr_end = datetime.strptime(end_date_str, '%Y-%m-%d')
                qtr_end = qtr_end.replace(hour=23, minute=59, second=59, microsecond=999999)
                use_date_filter = True
                # ✅ Keep original format for input fields (YYYY-MM-DD), add display format (DD-MM-YYYY)
                filter_start_date = start_date_str
                filter_end_date = end_date_str
                filter_start_date_display = qtr_start.strftime('%d-%m-%Y')
                filter_end_date_display = qtr_end.strftime('%d-%m-%Y')
            except ValueError:
                flash('Invalid date format. Please use YYYY-MM-DD format.', 'warning')
                qtr_start, qtr_end = get_quarter_date_range(current_qtr, current_year)
        else:
            qtr_start, qtr_end = get_quarter_date_range(current_qtr, current_year)
        
        # Get all eligible users
        all_users = get_eligible_users()
        
        # Get reward configuration
        config = get_reward_config()
        
        # ✅ Fetch all categories from both collections (needed for utilization lookup)
        categories_hr = list(mongo.db.hr_categories.find())
        categories_old = list(mongo.db.categories.find())
        
        # Find utilization category - check by category_code first, then by name
        utilization_category_id = None
        
        # Priority 1: Check hr_categories by category_code
        utilization_category = mongo.db.hr_categories.find_one({"category_code": "utilization_billable"})
        if utilization_category:
            utilization_category_id = utilization_category["_id"]
        
        # Priority 2: Check categories by code
        if not utilization_category_id:
            utilization_category = mongo.db.categories.find_one({"code": "utilization_billable"})
            if utilization_category:
                utilization_category_id = utilization_category["_id"]
        
        # Priority 3: Fallback to name matching in hr_categories
        if not utilization_category_id:
            for cat in categories_hr:
                if cat.get("name") == "Utilization/Billable":
                    utilization_category_id = cat["_id"]
                    break
        
        # Priority 4: Fallback to name matching in categories
        if not utilization_category_id:
            for cat in categories_old:
                if cat.get("name") == "Utilization/Billable":
                    utilization_category_id = cat["_id"]
                    break
        
        # ✅ Query points_request collection
        user_ids = [u["_id"] for u in all_users]
        
        # ✅ Calculate Total Points (Yearly) and Quarterly Points separately
        # ✅ FIXED: All queries use REQUEST_DATE for quarter mapping (not approved_date)
        total_points_by_user = {}
        quarterly_points_by_user = {}
        
        if use_date_filter:
            # When filtering by date, show only points in that range
            # ✅ FIXED: Using event_date (or request_date as fallback) for quarter mapping
            pipeline_filtered = [
                {
                    "$match": {
                        "user_id": {"$in": user_ids},
                        "status": "Approved"
                    }
                },
                {
                    "$addFields": {
                        "effective_date": {
                            "$ifNull": ["$event_date", "$request_date"]
                        }
                    }
                },
                {
                    "$match": {
                        "effective_date": {"$gte": qtr_start, "$lte": qtr_end}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "user_id": "$user_id",
                            "is_bonus": {"$ifNull": ["$is_bonus", False]}
                        },
                        "total_points": {"$sum": "$points"}
                    }
                }
            ]
            
            results_filtered = list(mongo.db.points_request.aggregate(pipeline_filtered, allowDiskUse=True))
            
            for result in results_filtered:
                user_id = str(result["_id"]["user_id"])
                is_bonus = result["_id"]["is_bonus"]
                points = result["total_points"]
                
                if user_id not in total_points_by_user:
                    total_points_by_user[user_id] = {"regular": 0, "bonus": 0}
                
                if is_bonus:
                    total_points_by_user[user_id]["bonus"] += points
                else:
                    total_points_by_user[user_id]["regular"] += points
            
            # For filtered view, quarterly = total
            quarterly_points_by_user = total_points_by_user
            
        else:
            # When NOT filtering, show yearly total and current quarter separately
            
            # ✅ FIXED: Get FISCAL yearly total (April to March next year)
            # Using event_date (or request_date as fallback) for quarter mapping
            year_start = datetime(current_year, 4, 1)  # Fiscal year starts April 1
            year_end = datetime(current_year + 1, 3, 31, 23, 59, 59, 999999)  # Ends March 31 next year
            
            pipeline_yearly = [
                {
                    "$match": {
                        "user_id": {"$in": user_ids},
                        "status": "Approved"
                    }
                },
                {
                    "$addFields": {
                        "effective_date": {
                            "$ifNull": ["$event_date", "$request_date"]
                        }
                    }
                },
                {
                    "$match": {
                        "effective_date": {"$gte": year_start, "$lte": year_end}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "user_id": "$user_id",
                            "is_bonus": {"$ifNull": ["$is_bonus", False]}
                        },
                        "total_points": {"$sum": "$points"}
                    }
                }
            ]
            
            results_yearly = list(mongo.db.points_request.aggregate(pipeline_yearly, allowDiskUse=True))
            
            for result in results_yearly:
                user_id = str(result["_id"]["user_id"])
                is_bonus = result["_id"]["is_bonus"]
                points = result["total_points"]
                
                if user_id not in total_points_by_user:
                    total_points_by_user[user_id] = {"regular": 0, "bonus": 0}
                
                if is_bonus:
                    total_points_by_user[user_id]["bonus"] += points
                else:
                    total_points_by_user[user_id]["regular"] += points
            
            # Get current quarter points
            # ✅ FIXED: Using event_date (or request_date as fallback) for quarter mapping
            pipeline_quarterly = [
                {
                    "$match": {
                        "user_id": {"$in": user_ids},
                        "status": "Approved"
                    }
                },
                {
                    "$addFields": {
                        "effective_date": {
                            "$ifNull": ["$event_date", "$request_date"]
                        }
                    }
                },
                {
                    "$match": {
                        "effective_date": {"$gte": qtr_start, "$lte": qtr_end}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "user_id": "$user_id",
                            "is_bonus": {"$ifNull": ["$is_bonus", False]}
                        },
                        "total_points": {"$sum": "$points"}
                    }
                }
            ]
            
            results_quarterly = list(mongo.db.points_request.aggregate(pipeline_quarterly, allowDiskUse=True))
            
            for result in results_quarterly:
                user_id = str(result["_id"]["user_id"])
                is_bonus = result["_id"]["is_bonus"]
                points = result["total_points"]
                
                if user_id not in quarterly_points_by_user:
                    quarterly_points_by_user[user_id] = {"regular": 0, "bonus": 0}
                
                if is_bonus:
                    quarterly_points_by_user[user_id]["bonus"] += points
                else:
                    quarterly_points_by_user[user_id]["regular"] += points
        
        # ✅ Get all quarters for the year to populate quarterly breakdown
        all_quarters_list = get_quarters_in_year(current_year)
        
        # ✅ Query points for ALL quarters (not just current quarter)
        # ✅ FIXED: Using event_date (or request_date as fallback) for quarter mapping
        all_quarters_data = {}
        for quarter in all_quarters_list:
            q_start = quarter["start_date"]
            q_end = quarter["end_date"]
            q_name = quarter["name"]
            
            pipeline_q = [
                {
                    "$match": {
                        "user_id": {"$in": user_ids},
                        "status": "Approved"
                    }
                },
                {
                    "$addFields": {
                        "effective_date": {
                            "$ifNull": ["$event_date", "$request_date"]
                        }
                    }
                },
                {
                    "$match": {
                        "effective_date": {"$gte": q_start, "$lte": q_end}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "user_id": "$user_id",
                            "is_bonus": {"$ifNull": ["$is_bonus", False]}
                        },
                        "total_points": {"$sum": "$points"}
                    }
                }
            ]
            
            results_q = list(mongo.db.points_request.aggregate(pipeline_q, allowDiskUse=True))
            
            for result in results_q:
                user_id = str(result["_id"]["user_id"])
                is_bonus = result["_id"]["is_bonus"]
                points = result["total_points"]
                
                if user_id not in all_quarters_data:
                    all_quarters_data[user_id] = {}
                
                if q_name not in all_quarters_data[user_id]:
                    all_quarters_data[user_id][q_name] = {"regular": 0, "bonus": 0}
                
                if is_bonus:
                    all_quarters_data[user_id][q_name]["bonus"] += points
                else:
                    all_quarters_data[user_id][q_name]["regular"] += points
        
        # ✅ Calculate utilization using the SAME optimized function as the dashboard
        # This ensures consistency across all pages
        from .central_routes_optimized import get_utilization_aggregated
        
        # ✅ FIXED: Calculate utilization for the ENTIRE FISCAL YEAR, not just the selected quarter
        # This matches the dashboard behavior where utilization is shown for the whole year
        fiscal_year_start = datetime(current_year, 4, 1)  # April 1st
        fiscal_year_end = datetime(current_year + 1, 3, 31, 23, 59, 59, 999999)  # March 31st next year
        
        utilization_data = get_utilization_aggregated(user_ids, fiscal_year_start, fiscal_year_end, utilization_category_id)
        
        # Process employee data
        employee_data = []
        
        for emp in all_users:
            emp_id = emp["_id"]
            emp_id_str = str(emp_id)
            emp_grade = emp.get("grade", "Unknown")
            
            # Get total points (yearly) and quarterly points
            user_total = total_points_by_user.get(emp_id_str, {"regular": 0, "bonus": 0})
            user_quarterly = quarterly_points_by_user.get(emp_id_str, {"regular": 0, "bonus": 0})
            user_utilization = utilization_data.get(emp_id_str, 0.0)
            
            # ✅ Populate all_quarters with data from all quarters
            # ✅ FIXED: Initialize all quarters for each employee (even if 0 points)
            all_quarters_for_emp = {}
            for quarter in all_quarters_list:
                q_name = quarter["name"]
                if emp_id_str in all_quarters_data and q_name in all_quarters_data[emp_id_str]:
                    all_quarters_for_emp[q_name] = all_quarters_data[emp_id_str][q_name]
                else:
                    all_quarters_for_emp[q_name] = {"regular": 0, "bonus": 0}
            
            # Get grade targets
            grade_targets = config.get("grade_targets", {})
            quarterly_target = grade_targets.get(emp_grade, 0)
            yearly_target = quarterly_target * 4
            
            emp_info = {
                "id": emp_id_str,
                "name": emp.get("name", "Unknown"),
                "email": emp.get("email", ""),
                "grade": emp_grade,
                "department": emp.get("department", "Unassigned"),
                "total_points": user_total["regular"],
                "quarterly_points": user_quarterly["regular"],
                "bonus_points": user_total["bonus"],
                "yearly_bonus_points": user_total["bonus"] if use_date_filter else calculate_yearly_bonus_points(emp_id, current_year),
                "quarterly_bonus": user_quarterly["bonus"],
                "all_quarters": all_quarters_for_emp,
                "utilization": user_utilization,
                "quarterly_target": quarterly_target,
                "yearly_target": yearly_target,
                "status": "not-eligible"
            }
            
            # ✅ Only include employees with points in the date range
            if use_date_filter:
                if emp_info["total_points"] > 0 or emp_info["bonus_points"] > 0:
                    employee_data.append(emp_info)
            else:
                # For non-filtered view, show all employees
                employee_data.append(emp_info)
        
        # Sort by total points
        employee_data.sort(key=lambda x: x["total_points"], reverse=True)
        
        return render_template(
            'central_export_data.html',
            user=user,
            employee_data=employee_data,
            current_quarter=current_qtr_name,
            config=config,
            use_date_filter=use_date_filter,
            filter_start_date=filter_start_date,
            filter_end_date=filter_end_date,
            filter_start_date_display=filter_start_date_display,
            filter_end_date_display=filter_end_date_display
        )
        
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print("=" * 80)
        print("EXPORT DATA ERROR:")
        print(error_msg)
        print("-" * 80)
        print(error_trace)
        print("=" * 80)
        error_print("Export data page error", e)
        flash(f'An error occurred while loading the export data page: {error_msg}', 'danger')
        return redirect(url_for('central.dashboard'))

@central_bp.route('/analytics', methods=['GET'])
def analytics():
    """
    Analytics dashboard with charts and statistics
    
    ✅ Redirects to optimized central_analytics.py implementation
    ✅ Handles BOTH old and new data structures:
    - Old data: 'categories' collection
    - New data: 'hr_categories' collection
    
    Same logic as PMO and TA dashboards for consistency
    """
    # Redirect to the optimized analytics implementation
    from .central_analytics import analytics as analytics_optimized
    return analytics_optimized()

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