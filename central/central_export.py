from flask import request, jsonify, send_file
from extensions import mongo
from datetime import datetime, timedelta
from bson import ObjectId
import io
import xlsxwriter
import traceback
from . import central_bp
from .central_utils import (
    check_central_access, get_eligible_users, get_reward_config,
    get_quarter_date_range, calculate_quarter_utilization,
    calculate_yearly_bonus_points, check_bonus_eligibility,
    get_monthly_billable_utilization, error_print, debug_print
)

@central_bp.route('/export/excel', methods=['GET'])
def export_excel():
    """
    Handles the GET request to generate and download an Excel report using MongoDB.
    """
    try:
        # --- Authorization ---
        has_access, user = check_central_access()
        
        if not has_access:
            return jsonify({'error': 'Not authorized'}), 403

        # --- Get and Validate Date Parameters ---
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        if not start_date_str or not end_date_str:
            return jsonify({'error': 'Start date and end date are required'}), 400

        # Validate date format
        try:
            start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD.'}), 400

        # Validate date range
        if start_dt > end_dt:
            return jsonify({'error': 'Start date cannot be after end date'}), 400

        # ✅ REMOVED: Future date validation - now supports past, current, and future dates
        # Users can now export data for any date range including future dates

        # --- Fetch Data From MongoDB ---
        try:
            employee_data, all_categories = get_all_employee_data_for_export(start_dt, end_dt)
        except Exception as e:
            error_print("Error fetching data from MongoDB", e)
            return jsonify({'error': 'Failed to fetch employee data'}), 500

        if not employee_data:
            return jsonify({'error': 'No employee data found for the selected date range'}), 404

        # --- Generate Excel File in Memory ---
        output = io.BytesIO()
        try:
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            
            # --- Cell Formats ---
            title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#4F81BD', 'font_color': 'white'})
            header_format = workbook.add_format({'bold': True, 'bg_color': '#DCE6F1', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True})
            data_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})
            number_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00', 'valign': 'vcenter'})
            percent_format = workbook.add_format({'border': 1, 'num_format': '0.0%', 'valign': 'vcenter'})
            total_format = workbook.add_format({'bold': True, 'bg_color': '#E8F1FF', 'border': 1, 'num_format': '#,##0.00'})

            # --- Worksheet 1: Employee Points Data ---
            worksheet_summary = workbook.add_worksheet('Employee Points Data')
            create_summary_worksheet(worksheet_summary, employee_data, all_categories, start_date_str, end_date_str,
                                    title_format, header_format, data_format, number_format, percent_format, total_format)

            # --- Worksheet 2: Point Breakdown ---
            worksheet_breakdown = workbook.add_worksheet('Point Breakdown')
            create_breakdown_worksheet(worksheet_breakdown, employee_data, start_date_str, end_date_str,
                                      title_format, header_format, data_format, number_format)

            # --- Worksheet 3: Category Summary ---
            worksheet_category = workbook.add_worksheet('Category Summary')
            create_category_summary_worksheet(worksheet_category, employee_data, all_categories, start_date_str, end_date_str,
                                            title_format, header_format, data_format, number_format)
            
            # --- Worksheet 4: Monthly Utilization ---
            worksheet_util = workbook.add_worksheet('Monthly Utilization')
            create_utilization_worksheet(workbook, worksheet_util, employee_data, start_date_str, end_date_str,
                                        title_format, header_format, data_format, number_format)

            workbook.close()
            output.seek(0)
        except Exception as e:
            error_print("Error generating Excel file", e)
            return jsonify({'error': f'Failed to generate Excel file: {str(e)}'}), 500

        # --- Send File to User ---
        filename = f'Employee_Points_Report_{start_date_str}_to_{end_date_str}.xlsx'
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        error_print("FATAL ERROR IN /export/excel", e)

        return jsonify({'error': 'An internal server error occurred. Please check the server logs.'}), 500

def create_summary_worksheet(worksheet, employee_data, all_categories, start_date_str, end_date_str,
                            title_format, header_format, data_format, number_format, percent_format, total_format):
    """Create the employee summary worksheet"""
    row, col = 0, 0
    total_cols = 13 + len(all_categories) + 1
    
    worksheet.merge_range(row, 0, row, total_cols - 1, 
                         f'EMPLOYEE POINTS REPORT ({start_date_str} to {end_date_str})', title_format)
    worksheet.set_row(row, 30)
    row += 1
    
    worksheet.write(row, 0, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    row += 1
    worksheet.write(row, 0, f'Total Employees: {len(employee_data)}')
    row += 2
    
    # Headers
    headers = ['Name', 'Email', 'Department', 'Grade', 'Yearly Target', 'Quarterly Target', 
               'Target Achievement %', 'Regular Points', 'Bonus Points', 'Yearly Bonus Total', 
               'Utilization %', 'Eligibility Status']
    headers.extend(all_categories)
    headers.append('Total Points')
    
    col = 0
    for header in headers:
        worksheet.write(row, col, header, header_format)
        col += 1
    worksheet.set_row(row, 45)
    row += 1
    
    # Data rows
    category_totals = {cat: 0 for cat in all_categories}
    total_regular, total_bonus, total_all = 0, 0, 0
    
    for emp_data in employee_data:
        col = 0
        worksheet.write(row, col, emp_data.get('name', ''), data_format); col += 1
        worksheet.write(row, col, emp_data.get('email', ''), data_format); col += 1
        worksheet.write(row, col, emp_data.get('department', ''), data_format); col += 1
        worksheet.write(row, col, emp_data.get('grade', ''), data_format); col += 1
        worksheet.write(row, col, emp_data.get('yearly_target', 0), number_format); col += 1
        worksheet.write(row, col, emp_data.get('quarterly_target', 0), number_format); col += 1
        
        target_achievement = emp_data.get('target_achievement_percentage', 0)
        if isinstance(target_achievement, (int, float)):
            target_achievement = target_achievement / 100 if target_achievement > 1 else target_achievement
        worksheet.write(row, col, target_achievement, percent_format); col += 1
        
        regular_pts = emp_data.get('points_in_period_regular', 0)
        bonus_pts = emp_data.get('points_in_period_bonus', 0)
        worksheet.write(row, col, regular_pts, number_format); col += 1
        worksheet.write(row, col, bonus_pts, number_format); col += 1
        worksheet.write(row, col, emp_data.get('yearly_bonus_total', 0), number_format); col += 1
        
        # Write utilization as percentage
        utilization_val = emp_data.get('utilization', 0)
        if utilization_val > 0:
            # Convert to decimal for percentage format (e.g., 85% -> 0.85)
            utilization_decimal = utilization_val / 100 if utilization_val > 1 else utilization_val
            worksheet.write(row, col, utilization_decimal, percent_format)
        else:
            worksheet.write(row, col, 'N/A', data_format)
        col += 1
        
        worksheet.write(row, col, emp_data.get('eligibility_status', ''), data_format); col += 1
        
        emp_total = 0
        for category in all_categories:
            cat_points = emp_data.get('categories', {}).get(category, 0)
            worksheet.write(row, col, cat_points, number_format)
            category_totals[category] += cat_points
            emp_total += cat_points
            col += 1
        
        total_pts = emp_data.get('total_points_in_period', emp_total)
        worksheet.write(row, col, total_pts, number_format)
        
        total_regular += regular_pts
        total_bonus += bonus_pts
        total_all += total_pts
        row += 1
    
    # Totals row
    row += 1
    worksheet.write(row, 7, total_regular, total_format)
    worksheet.write(row, 8, total_bonus, total_format)
    col = 12
    for category in all_categories:
        worksheet.write(row, col, category_totals[category], total_format)
        col += 1
    worksheet.write(row, col, total_all, total_format)
    
    # Column widths
    worksheet.set_column('A:A', 25)
    worksheet.set_column('B:B', 30)
    worksheet.set_column('C:C', 15)
    worksheet.set_column('D:D', 10)
    worksheet.set_column('E:F', 12)
    worksheet.set_column('G:G', 15)
    worksheet.set_column('H:I', 12)
    worksheet.set_column('J:J', 14)
    worksheet.set_column('K:K', 12)
    worksheet.set_column('L:L', 20)
    
    if all_categories:
        start_col = 12
        for i, category in enumerate(all_categories):
            width = max(15, min(len(category) * 0.8, 30))
            worksheet.set_column(start_col + i, start_col + i, width)

def create_breakdown_worksheet(worksheet, employee_data, start_date_str, end_date_str,
                               title_format, header_format, data_format, number_format):
    """Create the point breakdown worksheet"""
    row, col = 0, 0
    breakdown_headers = ['Employee Name', 'Email', 'Category', 'Points', 'Request Date', 'Bonus']
    
    worksheet.merge_range(row, 0, row, len(breakdown_headers) - 1, 
                         f'POINT BREAKDOWN ({start_date_str} to {end_date_str})', title_format)
    worksheet.set_row(row, 30)
    row += 2
    
    for col, header in enumerate(breakdown_headers):
        worksheet.write(row, col, header, header_format)
    row += 1
    
    for emp_data in employee_data:
        for point in emp_data.get('point_breakdown', []):
            col = 0
            worksheet.write(row, col, emp_data.get('name', ''), data_format); col += 1
            worksheet.write(row, col, emp_data.get('email', ''), data_format); col += 1
            worksheet.write(row, col, point.get('category', ''), data_format); col += 1
            worksheet.write(row, col, point.get('points', 0), number_format); col += 1
            worksheet.write(row, col, point.get('request_date', ''), data_format); col += 1
            worksheet.write(row, col, 'Yes' if point.get('is_bonus', False) else 'No', data_format); col += 1
            row += 1
    
    worksheet.set_column('A:A', 25)
    worksheet.set_column('B:B', 30)
    worksheet.set_column('C:C', 30)
    worksheet.set_column('D:D', 12)
    worksheet.set_column('E:E', 15)
    worksheet.set_column('F:F', 10)

def create_category_summary_worksheet(worksheet, employee_data, all_categories, start_date_str, end_date_str,
                                      title_format, header_format, data_format, number_format):
    """Create the category summary worksheet"""
    row = 0
    worksheet.merge_range(row, 0, row, 3, 
                         f'CATEGORY SUMMARY ({start_date_str} to {end_date_str})', title_format)
    row += 2
    
    worksheet.write(row, 0, 'Category', header_format)
    worksheet.write(row, 1, 'Total Points', header_format)
    worksheet.write(row, 2, 'Employee Count', header_format)
    worksheet.write(row, 3, 'Average Points', header_format)
    row += 1
    
    category_totals = {}
    for category in all_categories:
        total_points = sum(emp.get('categories', {}).get(category, 0) for emp in employee_data)
        emp_count = sum(1 for emp in employee_data if emp.get('categories', {}).get(category, 0) > 0)
        avg_points = total_points / emp_count if emp_count > 0 else 0
        category_totals[category] = total_points
        
        worksheet.write(row, 0, category, data_format)
        worksheet.write(row, 1, total_points, number_format)
        worksheet.write(row, 2, emp_count, number_format)
        worksheet.write(row, 3, avg_points, number_format)
        row += 1
    
    worksheet.set_column('A:A', 45)
    worksheet.set_column('B:D', 15)

def create_utilization_worksheet(workbook, worksheet, employee_data, start_date_str, end_date_str,
                                 title_format, header_format, data_format, number_format):
    """Create the monthly utilization worksheet"""
    row, col = 0, 0
    all_months = sorted(list(set(month for emp in employee_data for month in emp.get('monthly_utilization', {}))))
    
    # Add average utilization column
    util_headers = ['Name', 'Email', 'Average Utilization %'] + all_months
    
    worksheet.merge_range(row, 0, row, len(util_headers) - 1, 
                         f'MONTHLY UTILIZATION ({start_date_str} to {end_date_str})', title_format)
    worksheet.set_row(row, 30)
    row += 2
    
    for col, header in enumerate(util_headers):
        worksheet.write(row, col, header, header_format)
    row += 1
    
    # Create percentage format for utilization
    percent_format_util = workbook.add_format({'border': 1, 'num_format': '0.0"%"', 'valign': 'vcenter'})
    
    for emp_data in employee_data:
        col = 0
        worksheet.write(row, col, emp_data.get('name', ''), data_format); col += 1
        worksheet.write(row, col, emp_data.get('email', ''), data_format); col += 1
        
        # Write average utilization
        avg_util = emp_data.get('utilization', 0)
        if avg_util > 0:
            worksheet.write(row, col, avg_util, percent_format_util)
        else:
            worksheet.write(row, col, 'N/A', data_format)
        col += 1
        
        # Write monthly utilization data
        emp_monthly_util = emp_data.get('monthly_utilization', {})
        for month_header in all_months:
            util_value = emp_monthly_util.get(month_header, 0)
            if util_value > 0:
                worksheet.write(row, col, util_value, percent_format_util)
            else:
                worksheet.write(row, col, 'N/A', data_format)
            col += 1
        row += 1
    
    worksheet.set_column('A:A', 25)
    worksheet.set_column('B:B', 30)
    worksheet.set_column('C:C', 18)
    if all_months:
        worksheet.set_column(3, 3 + len(all_months) - 1, 15)

def get_all_employee_data_for_export(start_dt, end_dt):
    """Orchestrates fetching all data from MongoDB for the report."""
    try:
        # Fetch categories from both collections
        db_categories_old = [cat.get('name', '').strip() 
                            for cat in mongo.db.categories.find({"status": "active"}, {"name": 1}) 
                            if cat.get('name', '').strip()]
        
        db_categories_hr = [cat.get('name', '').strip() 
                           for cat in mongo.db.hr_categories.find({"status": "active"}, {"name": 1}) 
                           if cat.get('name', '').strip()]
        
        # Combine and deduplicate
        all_categories = sorted(list(set(db_categories_old + db_categories_hr)))
        
        # If no categories found, use standard list as fallback
        if not all_categories:
            all_categories = sorted(['Bonus Points', 'Client Appreciation', 'Feedback', 
                                    'Initiative (AI Adoption)', 'Interviews', 'Mentoring', 
                                    'Mindshare Content (Blogs, White Papers & Community activities)', 
                                    'Next Level Certification', 'Pre-Sales Contribution (Ad-hoc Support)', 
                                    'Pre-Sales Contribution (End to End with Ownership)', 
                                    'Pre-Sales Contribution (Partial)', 'Pre-Sales/RFP', 'R&R', 
                                    'Spot Award', 'Technical Sessions', 'Utilization/Billable', 
                                    'Value Add (Accelerator Solutions)'])
    except Exception as e:
        error_print("Error fetching categories from MongoDB", e)
        all_categories = sorted(['Bonus Points', 'Client Appreciation', 'Feedback', 
                                'Initiative (AI Adoption)', 'Interviews', 'Mentoring', 
                                'Mindshare Content (Blogs, White Papers & Community activities)', 
                                'Next Level Certification', 'Pre-Sales Contribution (Ad-hoc Support)', 
                                'Pre-Sales Contribution (End to End with Ownership)', 
                                'Pre-Sales Contribution (Partial)', 'Pre-Sales/RFP', 'R&R', 
                                'Spot Award', 'Technical Sessions', 'Utilization/Billable', 
                                'Value Add (Accelerator Solutions)'])
    
    try:
        all_users = get_eligible_users()
    except Exception as e:
        error_print("Error fetching eligible users", e)
        raise
    
    if not all_users:
        return [], all_categories
    
    employee_data_list = [
        processed_data 
        for user in all_users 
        if (processed_data := process_employee_for_export(user, all_categories, start_dt, end_dt)) is not None
    ]
    
    return employee_data_list, all_categories

def process_employee_for_export(user, all_categories, start_dt, end_dt):
    """Processes a single employee's points and data for the export using MongoDB."""
    try:
        user_id = user['_id']
        user_name = user.get('name', 'Unknown')
        
        category_points = {category: 0 for category in all_categories}
        
        # Build category map from both collections
        category_map = {}
        for cat in mongo.db.categories.find():
            category_map[str(cat['_id'])] = cat.get('name', 'Unknown')
        for cat in mongo.db.hr_categories.find():
            category_map[str(cat['_id'])] = cat.get('name', 'Unknown')
        
        total_points, regular_points, bonus_points = 0, 0, 0
        point_breakdown = []
        processed_request_ids = set()
        
        # ✅ STEP 1: Get approved points_request in the date range
        # Use event_date as primary, fallback to request_date
        pr_query = {
            "user_id": user_id, 
            "status": "Approved"
        }
        
        points_request_results = list(mongo.db.points_request.find(pr_query).sort('request_date', 1))
        
        for point_record in points_request_results:
            # Get effective date (prioritize event_date)
            event_date = point_record.get('event_date')
            request_date = point_record.get('request_date')
            award_date = point_record.get('award_date')
            
            effective_date = event_date if event_date and isinstance(event_date, datetime) else \
                            request_date if request_date and isinstance(request_date, datetime) else \
                            award_date if award_date and isinstance(award_date, datetime) else None
            
            # Check if effective date is in range
            if not effective_date or not (start_dt <= effective_date <= end_dt):
                continue
            
            # Mark as processed
            processed_request_ids.add(point_record['_id'])
            
            points_val = point_record.get('points', 0)
            category_id = point_record.get('category_id')
            category_name = category_map.get(str(category_id), 'Unknown').strip()
            is_bonus = point_record.get('is_bonus', False)
            
            # Skip if no points value
            if points_val == 0:
                continue
            
            # Match category name to the standard categories list
            matched_category = next((cat for cat in all_categories if cat.lower() == category_name.lower()), None)
            if matched_category:
                category_points[matched_category] += points_val
            
            total_points += points_val
            if is_bonus:
                bonus_points += points_val
            else:
                regular_points += points_val
            
            point_breakdown.append({
                'category': category_name,
                'points': points_val,
                'request_date': effective_date.strftime('%Y-%m-%d') if effective_date else '',
                'is_bonus': is_bonus
            })
        
        # ✅ REMOVED: No longer fetching from points collection (historical data)
        # Only use points_request collection for consistency with leaderboard, analytics, and dashboard
        
        config = get_reward_config()
        grade = user.get("grade", "Unknown")
        quarterly_target = config.get("grade_targets", {}).get(grade, 0)
        yearly_target = quarterly_target * 4
        
        utilization = calculate_quarter_utilization(user_id, start_dt, end_dt)
        yearly_bonus = calculate_yearly_bonus_points(user_id, start_dt.year)
        
        is_eligible, reason = check_bonus_eligibility(regular_points, grade, utilization, False, yearly_bonus)
        target_achievement = (total_points / yearly_target * 100) if yearly_target > 0 else 0
        
        # Get monthly utilization data
        monthly_utilization_data = get_monthly_billable_utilization(user_id, start_dt, end_dt)

        return {
            'name': user.get('name', ''),
            'email': user.get('email', ''),
            'department': user.get('department', ''),
            'grade': grade,
            'categories': category_points,
            'total_points_in_period': total_points,
            'points_in_period_regular': regular_points,
            'points_in_period_bonus': bonus_points,
            'yearly_target': yearly_target,
            'quarterly_target': quarterly_target,
            'target_achievement_percentage': target_achievement,
            'yearly_bonus_total': yearly_bonus,
            'utilization': utilization,
            'eligibility_status': "Eligible" if is_eligible else f"Not Eligible ({reason})",
            'point_breakdown': point_breakdown,
            'monthly_utilization': monthly_utilization_data
        }
    except Exception as e:
        error_print(f"Error processing employee '{user.get('name', 'Unknown')}' for export", e)
        return None