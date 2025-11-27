from flask import render_template, request, session, redirect, url_for, flash, jsonify, Response
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import sys
import io
import csv
import json
from .pm_main import pm_bp

def error_print(message, error=None):
    pass

def check_pm_access():
    user_id = session.get('user_id')
    if not user_id:
        return False, None
    
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        return False, None
    
    dashboard_access = user.get('dashboard_access', [])
    if isinstance(dashboard_access, str):
        dashboard_access = [dashboard_access]
    
    return 'pm' in dashboard_access, user

def get_current_quarter_date_range():
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

def is_employee_eligible_for_category(employee_grade, category_code):
    if employee_grade == 'A1' and category_code.lower() == 'mentoring':
        return False
    return True

def get_grade_minimum_expectations():
    return {
        'A1': 500, 'B1': 500, 'B2': 500, 'C1': 1000, 
        'C2': 1000, 'D1': 1000, 'D2': 500
    }

@pm_bp.route('/bulk-upload-form')
def bulk_upload_form():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    return render_template('pm_bulk_upload.html', user=user)

@pm_bp.route('/validate-bulk-upload', methods=['POST'])
def validate_bulk_upload():
    has_access, user = check_pm_access()
    
    if not has_access:
        return jsonify({"error": "Not authorized"}), 403
    
    try:
        if 'csv_file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files['csv_file']
        
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({"error": "File must be a CSV file"}), 400
        
        # Process CSV file
        csv_data = file.read().decode('utf-8')
        csv_file = io.StringIO(csv_data)
        csv_reader = csv.DictReader(csv_file)
        
        # Validate CSV headers
        required_headers = ['employee_id', 'category_id', 'points', 'notes']
        headers = csv_reader.fieldnames
        
        if not headers or not all(header in headers for header in required_headers):
            return jsonify({"error": f"CSV must contain headers: {', '.join(required_headers)}"}), 400
        
        # Get PM categories
        pm_categories = list(mongo.db.categories.find({
            "code": {"$in": ["initiative_ai", "mentoring"]},
            "validator": "PM"
        }))
        
        if not pm_categories:
            return jsonify({"error": "PM categories not found"}), 500
        
        # Create category lookup map
        category_map = {}
        for cat in pm_categories:
            category_map[str(cat['_id'])] = cat
            category_map[cat['code']] = cat
        
        # Get quarter info
        quarter_start, quarter_end, current_quarter, year = get_current_quarter_date_range()
        
        # Process each row
        valid_rows = []
        invalid_rows = []
        
        for i, row in enumerate(csv_reader, start=1):
            try:
                employee_id = row['employee_id'].strip()
                category_id = row['category_id'].strip()
                points_str = row['points'].strip()
                notes = row['notes'].strip()
                
                # Basic validation
                if not all([employee_id, category_id, points_str, notes]):
                    invalid_rows.append({
                        "row": i,
                        "data": row,
                        "error": "Missing required fields"
                    })
                    continue
                
                # Find employee
                employee = mongo.db.users.find_one({"employee_id": employee_id})
                
                if not employee:
                    invalid_rows.append({
                        "row": i,
                        "data": row,
                        "error": f"Employee ID {employee_id} not found"
                    })
                    continue
                
                # Find category
                category = category_map.get(category_id)
                
                if not category:
                    invalid_rows.append({
                        "row": i,
                        "data": row,
                        "error": f"Invalid category: {category_id}"
                    })
                    continue
                
                # Validate points
                try:
                    points = int(points_str)
                    if points != 250:
                        invalid_rows.append({
                            "row": i,
                            "data": row,
                            "error": "Points must be 250"
                        })
                        continue
                except ValueError:
                    invalid_rows.append({
                        "row": i,
                        "data": row,
                        "error": "Invalid points value"
                    })
                    continue
                
                # Check eligibility
                if not is_employee_eligible_for_category(employee.get('grade', ''), category.get('code', '')):
                    invalid_rows.append({
                        "row": i,
                        "data": row,
                        "error": f"Grade {employee.get('grade')} not eligible for {category.get('name')}"
                    })
                    continue
                
                # Calculate quarter points
                quarter_points = 0
                quarter_points_cursor = mongo.db.points.find({
                    "user_id": employee["_id"],
                    "category_id": {"$in": [cat["_id"] for cat in pm_categories]},
                    "award_date": {"$gte": quarter_start, "$lt": quarter_end}
                })
                
                for point in quarter_points_cursor:
                    quarter_points += point["points"]
                
                # Get expected points
                grade = employee.get("grade", "Unknown")
                minimum_expectations = get_grade_minimum_expectations()
                expected_points = minimum_expectations.get(grade, 0)
                
                # Valid row
                valid_rows.append({
                    "row": i,
                    "employee_id": employee_id,
                    "employee_name": employee.get("name", "Unknown"),
                    "email": employee.get("email", ""),
                    "grade": grade,
                    "department": employee.get("department", "Unknown"),
                    "category_id": category_id,
                    "category_name": category.get("name", "Unknown"),
                    "notes": notes,
                    "points": points,
                    "total_quarter_points": quarter_points,
                    "expected_points": expected_points,
                    "mongo_id": str(employee["_id"])
                })
                
            except Exception as e:
                error_print(f"Error processing CSV row {i}", e)
                invalid_rows.append({
                    "row": i,
                    "data": row,
                    "error": f"Error: {str(e)}"
                })
        
        return jsonify({
            "valid": len(invalid_rows) == 0,
            "total_rows": len(valid_rows) + len(invalid_rows),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "categories": [{
                "id": str(cat["_id"]),
                "name": cat.get("name", "Unknown")
            } for cat in pm_categories]
        })
        
    except Exception as e:
        error_print("Error validating bulk upload", e)
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@pm_bp.route('/bulk-upload', methods=['POST'])
def bulk_upload():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        # Get processed data
        processed_data = request.form.get('processed_data')
        
        if not processed_data:
            flash('No data to process', 'danger')
            return redirect(url_for('pm.bulk_upload_form'))
        
        # Parse data
        data = json.loads(processed_data)
        valid_rows = data.get('valid_rows', [])
        
        if not valid_rows:
            flash('No valid data to process', 'warning')
            return redirect(url_for('pm.bulk_upload_form'))
        
        # Get quarter info
        quarter_start, quarter_end, current_quarter, year = get_current_quarter_date_range()
        
        # Process each row
        success_count = 0
        
        for row in valid_rows:
            try:
                # Get category
                category = mongo.db.categories.find_one({
                    "$or": [
                        {"_id": ObjectId(row["category_id"]) if ObjectId.is_valid(row["category_id"]) else None},
                        {"code": row["category_id"]}
                    ]
                })
                
                if not category:
                    continue
                
                # Create points entry
                points_entry = {
                    "user_id": ObjectId(row["mongo_id"]),
                    "category_id": category["_id"],
                    "points": row["points"],
                    "award_date": datetime.utcnow(),
                    "awarded_by": ObjectId(user["_id"]),
                    "notes": row["notes"],
                    "uploaded_via_csv": True,
                    "quarter": current_quarter,
                    "year": year
                }
                
                mongo.db.points.insert_one(points_entry)
                success_count += 1
                
            except Exception as e:
                error_print(f"Error processing row", e)
        
        flash(f'Successfully awarded points to {success_count} employees', 'success')
        return redirect(url_for('pm.dashboard'))
        
    except Exception as e:
        error_print("Error processing bulk upload", e)
        flash('An error occurred while processing the upload', 'danger')
        return redirect(url_for('pm.bulk_upload_form'))

@pm_bp.route('/download-template')
def download_template():
    has_access, user = check_pm_access()
    
    if not has_access:
        flash('You do not have permission to access this', 'danger')
        return redirect(url_for('auth.login'))
    
    # Create CSV template
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['employee_id', 'category_id', 'points', 'notes'])
    
    # Write sample rows
    writer.writerow(['E123', 'initiative_ai', '250', 'AI Initiative award for project X'])
    writer.writerow(['E456', 'mentoring', '250', 'Mentoring award for helping team member'])
    
    # Prepare response
    response_data = output.getvalue()
    output.close()
    
    return Response(
        response_data,
        mimetype='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename=pm_points_template.csv',
            'Content-Type': 'text/csv'
        }
    )