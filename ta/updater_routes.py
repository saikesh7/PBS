from flask import render_template, request, session, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import csv
import io
import json

from .ta_main import ta_bp
from .helpers import (
    check_ta_updater_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, parse_date_flexibly,
    validate_event_date, SELECTABLE_EMPLOYEE_FILTER_FOR_TA,
    emit_pending_request_update, get_financial_quarter_dates,
    get_ta_categories, get_ta_validators, get_month_year_options
)
from .ta_email_service import send_new_request_email, send_bulk_request_email
from utils.error_handling import error_print


@ta_bp.route('/updater/dashboard', methods=['GET', 'POST'])
def updater_dashboard():
    """TA Updater Dashboard"""
    # ✅ FIXED: Changed default to 'overview' to match frontend
    tab = request.args.get('tab', 'overview')
    
    has_access, user = check_ta_updater_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
            redirect_url = get_user_redirect(user)
            return redirect(redirect_url)
        return redirect(url_for('auth.login'))
    
    current_quarter, current_month = get_financial_quarter_and_month()
    
    try:
        mongo = get_mongo()
        
        # Handle POST requests
        if request.method == 'POST':
            action_type = request.form.get('action_type')
            
            # ✅ FIXED: Changed to use hyphens instead of underscores
            if action_type == 'assign_points':
                return handle_single_assignment(user, 'single-request')
            elif action_type == 'bulk_upload_confirmed':
                return handle_bulk_upload_confirmed(user, 'bulk-upload')
        
        # GET request - render dashboard
        # Fetch ALL employees (like PMO does) - no department restrictions
        employees = list(mongo.db.users.find(SELECTABLE_EMPLOYEE_FILTER_FOR_TA).sort("name", 1))
        
        # Get TA categories
        ta_categories = get_ta_categories()
        
        # Get TA validators (exclude self if user has both updater and validator access)
        ta_validators = get_ta_validators()
        ta_validators = [v for v in ta_validators if str(v['_id']) != str(user['_id'])]
        
        if not ta_validators:
            flash('No other validators found. You cannot submit requests to yourself.', 'warning')
        
        # Get month/year options for backdating
        month_year_options = get_month_year_options()
        
        # Get today's date for max date validation
        today = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Build department and grade mapping for dynamic dropdowns (like PMO)
        departments = {}
        department_grades_map = {}
        
        for emp in employees:
            dept = emp.get('department')
            grade = emp.get('grade')
            
            if dept and dept.strip():
                if dept not in departments:
                    departments[dept] = []
                departments[dept].append(emp)
                
                if dept not in department_grades_map:
                    department_grades_map[dept] = set()
                if grade and grade.strip():
                    department_grades_map[dept].add(grade)
        
        # Convert sets to sorted lists
        for dept in department_grades_map:
            department_grades_map[dept] = sorted(list(department_grades_map[dept]))
        
        # Sort departments
        department_grades_map = dict(sorted(department_grades_map.items()))
        
        # Fetch ALL assignment history (including Pending)
        history = []
        history_data = []
        seen_request_ids = set()
        
        if ta_categories:
            category_ids = [cat["_id"] for cat in ta_categories]
            
            # Records with Direct Award category filter
            # Only show records for Direct Award categories (not Employee Raised)
            # ✅ FIXED: Only show requests created by this TA updater
            history_cursor = mongo.db.points_request.find({
                "category_id": {"$in": category_ids},
                "status": {"$in": ["Pending", "Approved", "Rejected"]},
                "created_by_ta_id": ObjectId(user['_id'])
            }).sort("request_date", -1)

            # OLD records - fetch historical data with different field names
            # ✅ FIXED: Only show records actually created by this TA updater
            # Exclude employee-raised requests (where user_id equals the submitter)
            old_history_cursor = mongo.db.points_request.find({
                "status": {"$in": ["Pending", "Approved", "Rejected"]},
                "created_by_ta_id": ObjectId(user['_id'])  # Only records created by this updater
            }).sort("request_date", -1)

            # Combine cursors - include old records for historical data
            # This ensures Direct Award category records are shown including old ones
            combined_cursor = list(history_cursor) + list(old_history_cursor)
            
            for req_data in combined_cursor:
                request_id = str(req_data.get("_id", ""))

                # Skip if we've already seen this request
                if request_id in seen_request_ids:
                    continue

                seen_request_ids.add(request_id)

                employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
                
                # Support both old and new validator field names
                validator_id = req_data.get("assigned_validator_id") or req_data.get("pending_validator_id") or req_data.get("processed_by") or req_data.get("ta_validator_id") or req_data.get("validator_id")
                validator = mongo.db.users.find_one({"_id": validator_id}) if validator_id else None
                
                # Try to get category from hr_categories first, then fall back to old categories collection
                category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
                if not category:
                    category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
                
                if employee and category:
                    # Determine validator name
                    validator_name = "Unknown"
                    if validator:
                        validator_name = validator.get("name", "Unknown")
                    elif req_data.get("status") == "Approved":
                        validator_name = "Approved"
                    elif req_data.get("status") == "Rejected":
                        validator_name = "Rejected"
                    
                    history.append({
                        'request_id': str(req_data["_id"]),
                        'request_date': req_data["request_date"],
                        'event_date': req_data.get("event_date", req_data["request_date"]),
                        'employee_name': employee.get("name", "Unknown"),
                        'employee_id': employee.get("employee_id", "N/A"),
                        'employee_grade': employee.get("grade", "Unknown"),
                        'category_name': category.get("name", "Unknown"),
                        'quantity': req_data.get("quantity", 1),
                        'points': req_data.get("points", 0),
                        'validator_name': validator_name,
                        'status': req_data.get("status", "Unknown"),
                        'submission_notes': req_data.get("submission_notes", ""),
                        'response_notes': req_data.get("response_notes", ""),
                        'hr_modified': req_data.get('hr_modified', False)
                    })
                    
                    history_data.append({
                        'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                        'event_date': req_data.get("event_date", req_data["request_date"]).strftime('%d-%m-%Y'),
                        'employee_name': employee.get("name", "Unknown"),
                        'grade': employee.get("grade", "Unknown"),
                        'category_name': category.get("name", "Unknown"),
                        'quantity': req_data.get("quantity", 1),
                        'points': req_data.get("points", 0),
                        'notes': req_data.get("submission_notes", ""),
                        'status': req_data.get("status", "Unknown"),
                        'submitted_to': validator_name,
                        'hr_modified': req_data.get('hr_modified', False)
                    })
            
            # Also check points collection for old approved records
            # ✅ FIXED: Only show records created by this TA updater
            old_points_cursor = mongo.db.points.find({
                "created_by_ta_id": ObjectId(user['_id'])
            }).sort("created_at", -1)
            
            for point in old_points_cursor:
                # Skip if we already have this from points_request
                point_request_id = str(point.get("request_id", ""))
                if point_request_id and point_request_id in seen_request_ids:
                    continue
                
                employee = mongo.db.users.find_one({"_id": point["user_id"]})
                
                # Try to get category from hr_categories first, then fall back to old categories collection
                category = mongo.db.hr_categories.find_one({"_id": point.get("category_id")})
                if not category:
                    category = mongo.db.categories.find_one({"_id": point.get("category_id")})
                
                if employee and category:
                    # Use award_date (which is the event_date) for history display
                    event_date = point.get("award_date") or point.get("event_date") or point.get("created_at")
                    
                    history.append({
                        'request_id': point_request_id if point_request_id else str(point.get("_id")),
                        'request_date': event_date,
                        'event_date': event_date,
                        'employee_name': employee.get("name", "Unknown"),
                        'employee_id': employee.get("employee_id", "N/A"),
                        'employee_grade': employee.get("grade", "Unknown"),
                        'category_name': category.get("name", "Unknown"),
                        'quantity': point.get("quantity", 1),
                        'points': point.get("points", 0),
                        'validator_name': "Approved",
                        'status': 'Approved',
                        'submission_notes': point.get("submission_notes", ""),
                        'response_notes': point.get("notes", "") or point.get("response_notes", ""),
                        'hr_modified': point.get('hr_modified', False)
                    })
                    
                    history_data.append({
                        'request_date': event_date.strftime('%d-%m-%Y'),
                        'event_date': event_date.strftime('%d-%m-%Y'),
                        'employee_name': employee.get("name", "Unknown"),
                        'grade': employee.get("grade", "Unknown"),
                        'category_name': category.get("name", "Unknown"),
                        'quantity': point.get("quantity", 1),
                        'points': point.get("points", 0),
                        'notes': point.get("notes", ""),
                        'status': 'Approved',
                        'submitted_to': "Approved",
                        'hr_modified': point.get('hr_modified', False)
                    })
        
        # Get unique years and quarters for filters
        year_options = sorted(list(set([h['request_date'].strftime('%Y') for h in history])), reverse=True) if history else []
        
        # Dynamically generate quarter options based on actual data
        quarters_set = set()
        for h in history:
            month = h['request_date'].month
            # Determine fiscal quarter based on month
            if month in [4, 5, 6]:
                quarters_set.add('Q1')
            elif month in [7, 8, 9]:
                quarters_set.add('Q2')
            elif month in [10, 11, 12]:
                quarters_set.add('Q3')
            elif month in [1, 2, 3]:
                quarters_set.add('Q4')
        
        # Sort quarters in order Q1, Q2, Q3, Q4
        quarter_order = ['Q1', 'Q2', 'Q3', 'Q4']
        quarter_options = [q for q in quarter_order if q in quarters_set]
        
        grades = sorted(list(set([h['employee_grade'] for h in history]))) if history else []
        
        return render_template(
            'updater_dashboard.html',
            user=user,
            employees=employees,
            departments=departments,
            department_grades_map=department_grades_map,
            ta_categories=ta_categories,
            ta_validators=ta_validators,
            month_year_options=month_year_options,
            current_quarter=current_quarter,
            current_month=current_month,
            history=history,
            history_data=history_data,
            year_options=year_options,
            quarter_options=quarter_options,
            grades=grades,
            tab=tab,
            today=today
        )
    
    except Exception as e:
        error_print("Error in TA updater dashboard", e)
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))


def handle_single_assignment(user, current_tab='single-request'):
    """Handle single points assignment"""
    # ✅ FIXED: Changed default parameter from 'single_request' to 'single-request'
    mongo = get_mongo()
    
    employee_id = request.form.get('employee_id')
    category_id = request.form.get('category_id')
    validator_id = request.form.get('validator_id')
    notes = request.form.get('notes', '')
    event_date_str = request.form.get('event_date')
    award_month_year = request.form.get('award_month_year')
    
    try:
        quantity = int(request.form.get('quantity', 1))
    except (ValueError, TypeError):
        flash('Quantity must be a valid number.', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    # Validate inputs
    if not employee_id or not category_id or not validator_id or not notes or quantity <= 0:
        flash('All fields are required and quantity must be greater than 0.', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    # Check if validator is not the same as current user
    if str(validator_id) == str(user['_id']):
        flash('You cannot assign yourself as a validator. Please select another validator.', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    # Validate event_date
    event_date = None
    if event_date_str:
        event_date, error = validate_event_date(event_date_str, allow_future=True)
        if error:
            flash(error, 'danger')
            return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    else:
        event_date = datetime.utcnow()
    
    # If award_month_year is provided, use that month's first day as event_date
    if award_month_year:
        try:
            year, month = award_month_year.split('-')
            event_date = datetime(int(year), int(month), 1)
        except:
            flash('Invalid month/year selection', 'danger')
            return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    # Get employee
    employee = mongo.db.users.find_one({"employee_id": employee_id})
    if not employee:
        flash('Employee not found. Please enter a valid Employee ID.', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    # Get category
    category = mongo.db.hr_categories.find_one({"_id": ObjectId(category_id)})
    if not category:
        flash('Category not found in database.', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    # Get validator
    validator = mongo.db.users.find_one({"_id": ObjectId(validator_id)})
    if not validator:
        flash('Validator not found.', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    # Calculate points
    points_per_unit = category.get('points_per_unit', {})
    employee_grade = employee.get('grade', 'base')
    employee_name = employee.get('name', employee_id)
    
    if isinstance(points_per_unit, dict):
        # Check if the employee's grade is explicitly configured
        if employee_grade not in points_per_unit:
            # Grade not configured = not eligible (don't use 'base' as fallback)
            flash(f'Employee "{employee_name}" (Grade: {employee_grade}) is not eligible for category "{category.get("name")}". Please select a different category or employee.', 'danger')
            return redirect(url_for('ta.updater_dashboard', tab=current_tab))
        else:
            # Grade is explicitly configured
            points = points_per_unit.get(employee_grade, 0)
    else:
        points = points_per_unit
    
    # Check if employee grade is eligible for this category
    if points == 0:
        flash(f'Employee "{employee_name}" (Grade: {employee_grade}) is not eligible for category "{category.get("name")}". Please select a different category or employee.', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    total_points = points * quantity
    
    if total_points <= 0:
        flash('Category has invalid points configuration.', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    # Create request
    request_data = {
        "user_id": ObjectId(employee["_id"]),
        "category_id": ObjectId(category["_id"]),
        "points": total_points,
        "quantity": quantity,
        "submission_notes": notes,
        "updated_by": "TA",
        "status": "Pending",
        "request_date": datetime.utcnow(),
        "event_date": event_date,
        "assigned_validator_id": ObjectId(validator_id),
        "created_by_ta_id": ObjectId(user['_id'])
    }
    
    result = mongo.db.points_request.insert_one(request_data)
    
    # Publish real-time event
    try:
        from services.realtime_events import publish_request_raised
        request_data['_id'] = result.inserted_id
        publish_request_raised(request_data, employee, validator, category)
    except Exception as e:
        error_print("Error publishing real-time event", e)
    
    # ✅ Send email notification to validator (matches PMO pattern)
    if validator.get('email'):
        try:
            send_new_request_email(
                validator_email=validator.get('email'),
                validator_name=validator.get('name', 'Validator'),
                employee_name=employee.get('name', 'Employee'),
                category_name=category.get('name', 'Category'),
                points=total_points,
                event_date=event_date.strftime('%d-%m-%Y'),
                notes=notes
            )
        except Exception as e:
            error_print("Error sending TA email notification", e)
            # Don't fail the request submission if email fails
    
    flash(f'Request submitted successfully! {total_points} points pending approval for {employee.get("name")}', 'success')
    
    try:
        emit_pending_request_update()
    except:
        pass
    
    return redirect(url_for('ta.updater_dashboard', tab=current_tab))


@ta_bp.route('/updater/validate-bulk-upload', methods=['POST'])
def validate_bulk_upload():
    """Validate bulk CSV upload and return valid/invalid rows"""
    has_access, user = check_ta_updater_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        file = request.files.get('csv_file')
        
        if not file or file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        # Parse CSV
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        # Validate headers
        expected_headers = ['employee_id', 'validator_employee_id', 'event_date', 'category_code', 'quantity', 'notes']
        if csv_reader.fieldnames != expected_headers:
            return jsonify({
                'success': False, 
                'error': f"Invalid CSV headers. Expected: {', '.join(expected_headers)}"
            })
        
        # Dynamically fetch valid TA categories
        # Use regex to match any category_department starting with 'ta' (case-insensitive)
        ta_categories = list(mongo.db.hr_categories.find({
            'category_department': {'$regex': '^ta', '$options': 'i'},
            'category_status': 'active',
            'category_type': {'$not': {'$regex': 'employee.*raised', '$options': 'i'}}
        }, {'name': 1}))
        
        # Create list of valid category codes (normalized: lowercase with underscores)
        valid_categories_for_bulk = []
        category_name_map = {}  # Map normalized code to actual category name
        for cat in ta_categories:
            cat_name = cat.get('name', '')
            # Normalize: lowercase and replace spaces with underscores
            normalized_code = cat_name.lower().replace(' ', '_').replace('&', 'and')
            valid_categories_for_bulk.append(normalized_code)
            category_name_map[normalized_code] = cat_name
        
        valid_rows = []
        invalid_rows = []
        
        for row_num, row in enumerate(csv_reader, start=2):
            try:
                employee_id = row.get('employee_id', '').strip()
                validator_employee_id = row.get('validator_employee_id', '').strip()
                event_date_str = row.get('event_date', '').strip()
                category_code = row.get('category_code', '').strip()
                quantity_str = row.get('quantity', '').strip()
                notes = row.get('notes', '').strip()
                
                # Skip completely empty rows
                if not any([employee_id, validator_employee_id, event_date_str, category_code, quantity_str, notes]):
                    continue
                
                # Validate required fields
                missing_fields = []
                if not employee_id:
                    missing_fields.append('employee_id')
                if not validator_employee_id:
                    missing_fields.append('validator_employee_id')
                if not event_date_str:
                    missing_fields.append('event_date')
                if not category_code:
                    missing_fields.append('category_code')
                if not quantity_str:
                    missing_fields.append('quantity')
                if not notes:
                    missing_fields.append('notes')
                
                if missing_fields:
                    raise ValueError(f"Required field(s) missing: {', '.join(missing_fields)}")
                
                # Validate quantity
                try:
                    quantity = int(quantity_str)
                    if quantity <= 0:
                        raise ValueError("Quantity must be positive")
                except ValueError:
                    raise ValueError(f"Invalid quantity '{quantity_str}'")
                
                # Get validator by employee_id
                validator = mongo.db.users.find_one({"employee_id": validator_employee_id})
                if not validator:
                    raise ValueError(f"Validator with employee ID '{validator_employee_id}' not found")
                
                # Check if validator has TA validator access
                validator_dashboard_access = validator.get('dashboard_access', [])
                if 'ta_va' not in validator_dashboard_access:
                    raise ValueError(f"User '{validator_employee_id}' does not have TA Validator access")
                
                # Check if validator is not the same as current user
                if str(validator['_id']) == str(user['_id']):
                    raise ValueError("You cannot assign yourself as validator")
                
                # Parse event date
                try:
                    event_date = datetime.strptime(event_date_str, '%d-%m-%Y')
                except ValueError as ve:
                    if "does not match format" in str(ve):
                        raise ValueError(f"Invalid event_date format '{event_date_str}'. Use DD-MM-YYYY")
                    raise
                
                # Normalize the category code from CSV
                normalized_category_code = category_code.lower().replace(' ', '_').replace('&', 'and')
                
                # Validate category code
                if normalized_category_code not in valid_categories_for_bulk:
                    raise ValueError(f"Invalid category_code '{category_code}'. Must be one of: {', '.join(valid_categories_for_bulk)}")
                
                # Get employee
                employee = mongo.db.users.find_one({"employee_id": employee_id})
                if not employee:
                    raise ValueError(f"Employee ID '{employee_id}' not found")
                
                # Find category using the actual category name from our map
                actual_category_name = category_name_map.get(normalized_category_code)
                if not actual_category_name:
                    raise ValueError(f"Category code '{category_code}' not found in mapping")
                
                # Find category in database
                # Use regex to match any category_department starting with 'ta' (case-insensitive)
                category = mongo.db.hr_categories.find_one({
                    "name": actual_category_name,
                    "category_department": {"$regex": "^ta", "$options": "i"},
                    "category_status": "active"
                })
                
                if not category:
                    raise ValueError(f"Category '{actual_category_name}' not found in database")
                
                # Get employee grade
                employee_grade = employee.get('grade')
                employee_name = employee.get('name', employee_id)
                
                if not employee_grade:
                    raise ValueError(f"Employee '{employee_name}' ({employee_id}) has no grade assigned")
                
                # Get points based on grade
                points_per_unit_config = category.get('points_per_unit', 0)
                if isinstance(points_per_unit_config, dict):
                    # Check if the employee's grade is explicitly configured
                    if employee_grade not in points_per_unit_config:
                        # Grade not configured = not eligible (don't use 'base' as fallback)
                        raise ValueError(f"Employee '{employee_name}' (Grade: {employee_grade}) is not eligible for category '{actual_category_name}'")
                    else:
                        # Grade is explicitly configured
                        points_per_unit = points_per_unit_config.get(employee_grade, 0)
                else:
                    points_per_unit = points_per_unit_config
                
                if points_per_unit <= 0:
                    raise ValueError(f"Employee '{employee_name}' (Grade: {employee_grade}) is not eligible for category '{actual_category_name}'")
                
                total_points = points_per_unit * quantity
                
                # Add to valid rows
                valid_rows.append({
                    'row_number': row_num,
                    'employee_id': employee_id,
                    'employee_name': employee.get('name', 'Unknown'),
                    'employee_object_id': str(employee['_id']),
                    'validator_employee_id': validator_employee_id,
                    'validator_name': validator.get('name', 'Unknown'),
                    'validator_object_id': str(validator['_id']),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'event_date_obj': event_date.isoformat(),
                    'category_code': category_code,
                    'category_name': category.get('name', 'Unknown'),
                    'category_id': str(category['_id']),
                    'quantity': quantity,
                    'points': total_points,
                    'notes': notes
                })
            
            except Exception as e:
                # Get employee info if available for better error display
                employee_info = ''
                employee_grade_info = ''
                if 'employee' in locals() and employee:
                    employee_info = employee.get('name', '')
                    employee_grade_info = employee.get('grade', '')
                
                invalid_rows.append({
                    'row_number': row_num,
                    'employee_id': employee_id if 'employee_id' in locals() else '',
                    'employee_name': employee_info,
                    'employee_grade': employee_grade_info,
                    'validator_employee_id': validator_employee_id if 'validator_employee_id' in locals() else '',
                    'category_code': category_code if 'category_code' in locals() else '',
                    'quantity': quantity_str if 'quantity_str' in locals() else '',
                    'error': str(e)
                })
        
        # Get category info from first valid row if available
        category_name = 'Unknown'
        category_id = None
        
        if valid_rows:
            category_name = valid_rows[0].get('category_name', 'Unknown')
            category_id = valid_rows[0].get('category_id')
        
        return jsonify({
            'success': True,
            'valid_rows': valid_rows,
            'invalid_rows': invalid_rows,
            'category_name': category_name,
            'category_id': category_id
        })
    
    except Exception as e:
        error_print("Error validating bulk upload", e)
        return jsonify({'success': False, 'error': str(e)}), 500


def handle_bulk_upload_confirmed(user, current_tab='bulk-upload'):
    """Handle confirmed bulk upload with pre-validated data"""
    # ✅ FIXED: Changed default parameter from 'bulk_upload' to 'bulk-upload'
    mongo = get_mongo()
    
    try:
        # Get validated data from form
        validated_data_json = request.form.get('validated_data')
        if not validated_data_json:
            flash('No validated data received', 'danger')
            return redirect(url_for('ta.updater_dashboard', tab=current_tab))
        
        validated_rows = json.loads(validated_data_json)
        
        if not validated_rows:
            flash('No valid rows to process', 'warning')
            return redirect(url_for('ta.updater_dashboard', tab=current_tab))
        
        # Pre-fetch all unique categories to avoid repeated DB queries
        unique_category_ids = list(set(row.get('category_id') for row in validated_rows if row.get('category_id')))
        categories_cache = {str(cat['_id']): cat for cat in mongo.db.hr_categories.find({'_id': {'$in': [ObjectId(cid) for cid in unique_category_ids]}})}
        
        if not categories_cache:
            flash('No valid categories found', 'danger')
            return redirect(url_for('ta.updater_dashboard', tab=current_tab))
        
        success_count = 0
        error_count = 0
        realtime_success_count = 0
        validators_notified = {}  # Track validators for bulk email notification
        
        # Pre-fetch all unique employees and validators to avoid repeated DB queries
        unique_employee_ids = list(set(row['employee_object_id'] for row in validated_rows))
        unique_validator_ids = list(set(row['validator_object_id'] for row in validated_rows))
        
        employees_cache = {str(emp['_id']): emp for emp in mongo.db.users.find({'_id': {'$in': [ObjectId(eid) for eid in unique_employee_ids]}})}
        validators_cache = {str(val['_id']): val for val in mongo.db.users.find({'_id': {'$in': [ObjectId(vid) for vid in unique_validator_ids]}})}
        
        for row in validated_rows:
            try:
                # Get category for this row
                row_category_id = row.get('category_id')
                category = categories_cache.get(row_category_id)
                
                if not category:
                    error_count += 1
                    continue
                
                # Parse event date from ISO format
                event_date = datetime.fromisoformat(row['event_date_obj'])
                
                request_data = {
                    "user_id": ObjectId(row['employee_object_id']),
                    "category_id": ObjectId(row_category_id),
                    "points": row['points'],
                    "quantity": row['quantity'],
                    "submission_notes": row['notes'],
                    "updated_by": "TA",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date,
                    "assigned_validator_id": ObjectId(row['validator_object_id']),
                    "created_by_ta_id": ObjectId(user['_id'])
                }
                
                result = mongo.db.points_request.insert_one(request_data)
                request_data['_id'] = result.inserted_id
                
                # Publish real-time event using cached data
                try:
                    from services.realtime_events import publish_request_raised
                    
                    employee = employees_cache.get(row['employee_object_id'])
                    validator = validators_cache.get(row['validator_object_id'])
                    
                    if employee and validator:
                        # Ensure category_department is lowercase for real-time routing
                        if 'category_department' in category:
                            category['category_department'] = category['category_department'].lower()
                        else:
                            category['category_department'] = 'ta_up'
                        
                        rt_result = publish_request_raised(request_data, employee, validator, category)
                        if rt_result:
                            realtime_success_count += 1
                except Exception as e:
                    # Don't fail the bulk upload if real-time fails
                    error_print("Error publishing real-time event", e)
                
                # Track validator for bulk email notification using cached data
                validator_id_str = row['validator_object_id']
                if validator_id_str not in validators_notified:
                    validator_data = validators_cache.get(validator_id_str)
                    if validator_data:
                        validators_notified[validator_id_str] = {
                            'validator': validator_data,
                            'count': 0
                        }
                if validator_id_str in validators_notified:
                    validators_notified[validator_id_str]['count'] += 1
                
                success_count += 1
            
            except Exception as e:
                error_print(f"Error processing row {row.get('row_number')}", e)
                error_count += 1
                continue
        
        # Send bulk email notification to each validator (non-blocking)
        try:
            from ta.ta_email_service import send_bulk_request_email
            for validator_id, data in validators_notified.items():
                validator = data['validator']
                count = data['count']
                if validator.get('email'):
                    try:
                        send_bulk_request_email(
                            validator_email=validator.get('email'),
                            validator_name=validator.get('name', 'Validator'),
                            request_count=count,
                            updater_name=user.get('name', 'TA Updater')
                        )
                    except Exception as email_error:
                        error_print(f"Error sending email to validator {validator_id}", email_error)
        except Exception as e:
            error_print("Error sending bulk email notifications", e)
        
        if success_count > 0:
            flash(f'Successfully submitted {success_count} request(s) for validation.', 'success')
        if error_count > 0:
            flash(f'{error_count} row(s) failed to process.', 'warning')
        
        try:
            emit_pending_request_update()
        except Exception as e:
            error_print("Error emitting pending request update", e)
        
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))
    
    except Exception as e:
        error_print("Error processing bulk upload", e)
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('ta.updater_dashboard', tab=current_tab))


@ta_bp.route('/updater/get-valid-category-codes', methods=['GET'])
def get_valid_category_codes():
    """Get list of valid category codes for bulk upload (Direct Award only, excludes Employee Raised)"""
    has_access, user = check_ta_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        # Dynamically fetch valid TA categories - exclude employee_raised categories
        # Only show Direct Award categories (same logic as PMO)
        # Use regex to match any category_department starting with 'ta' (case-insensitive)
        ta_categories = list(mongo.db.hr_categories.find({
            'category_department': {'$regex': '^ta', '$options': 'i'},
            'category_status': 'active',
            'category_type': {'$not': {'$regex': 'employee.*raised', '$options': 'i'}}
        }, {'name': 1}).sort('name', 1))
        
        # Create list with both code and name
        category_list = []
        for cat in ta_categories:
            cat_name = cat.get('name', '')
            normalized_code = cat_name.lower().replace(' ', '_').replace('&', 'and')
            category_list.append({
                'code': normalized_code,
                'name': cat_name
            })
        
        return jsonify({
            'success': True,
            'categories': category_list
        })
    
    except Exception as e:
        error_print("Error fetching category codes", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@ta_bp.route('/updater/download-bulk-template')
def download_bulk_template():
    """Download CSV template for bulk upload with dynamic categories"""
    has_access, user = check_ta_updater_access()
    if not has_access:
        flash('Access denied', 'danger')
        return redirect(url_for('auth.login'))
    
    from flask import make_response
    
    try:
        mongo = get_mongo()
        
        # Use current date as default
        current_date = datetime.now().strftime('%d-%m-%Y')
        
        # Dynamically fetch valid TA categories
        # Use regex to match any category_department starting with 'ta' (case-insensitive)
        ta_categories = list(mongo.db.hr_categories.find({
            'category_department': {'$regex': '^ta', '$options': 'i'},
            'category_status': 'active',
            'category_type': {'$not': {'$regex': 'employee.*raised', '$options': 'i'}}
        }, {'name': 1}).sort('name', 1))
        
        csv_content = "employee_id,validator_employee_id,event_date,category_code,quantity,notes\n"
        
        # Add one sample row for EACH category so users can see all available codes
        if ta_categories:
            for idx, cat in enumerate(ta_categories, start=1):
                cat_code = cat.get('name', '').lower().replace(' ', '_').replace('&', 'and')
                cat_name = cat.get('name', 'Category')
                csv_content += f"EMP{idx:03d},VAL001,{current_date},{cat_code},1,Sample notes for {cat_name}\n"
        else:
            # Fallback if no categories found
            csv_content += f"EMP001,VAL001,{current_date},interviews,1,Sample notes\n"
        
        filename = "ta_bulk_upload_template.csv"
        
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        error_print("Error generating bulk template", e)
        flash('Error generating template', 'danger')
        return redirect(url_for('ta.updater_dashboard'))


@ta_bp.route('/updater/get-employees', methods=['POST'])
def get_employees():
    """Get employees based on filters"""
    has_access, user = check_ta_updater_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        department = request.form.get('department')
        grade = request.form.get('grade')
        
        query = SELECTABLE_EMPLOYEE_FILTER_FOR_TA.copy()
        
        if department and department != 'all':
            query['department'] = department
        
        if grade and grade != 'all':
            query['grade'] = grade
        
        employees = list(mongo.db.users.find(query).sort("name", 1))
        
        result = []
        for emp in employees:
            result.append({
                'id': str(emp['_id']),
                'name': emp.get('name', 'Unknown'),
                'employee_id': emp.get('employee_id', ''),
                'grade': emp.get('grade', ''),
                'department': emp.get('department', '')
            })
        
        return jsonify({'success': True, 'employees': result})
    
    except Exception as e:
        error_print("Error getting employees", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@ta_bp.route('/updater/get-employee-details', methods=['POST'])
def get_employee_details():
    """Get employee details"""
    has_access, user = check_ta_updater_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        employee_id = request.form.get('employee_id')
        
        employee = mongo.db.users.find_one({"_id": ObjectId(employee_id)})
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
        
        return jsonify({
            'success': True,
            'employee': {
                'name': employee.get('name', 'Unknown'),
                'employee_id': employee.get('employee_id', ''),
                'grade': employee.get('grade', ''),
                'department': employee.get('department', '')
            }
        })
    
    except Exception as e:
        error_print("Error getting employee details", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@ta_bp.route('/updater/get-history', methods=['POST'])
def get_updater_history():
    """Get assignment history for updater"""
    has_access, user = check_ta_updater_access()
    
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        ta_categories = get_ta_categories()
        if not ta_categories:
            return jsonify({'success': True, 'entries': []})
        
        category_ids = [cat["_id"] for cat in ta_categories]
        
        # Include ALL statuses
        history_query = {
            "created_by_ta_id": ObjectId(user['_id']),
            "category_id": {"$in": category_ids}
        }
        
        history_cursor = mongo.db.points_request.find(history_query).sort("request_date", -1)
        
        history_data = []
        for req_data in history_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            
            # Try to get category from hr_categories first, then fall back to old categories collection
            category = mongo.db.hr_categories.find_one({"_id": req_data.get("category_id")})
            if not category:
                category = mongo.db.categories.find_one({"_id": req_data.get("category_id")})
            
            if employee and category:
                history_data.append({
                    'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                    'event_date': req_data.get("event_date", req_data["request_date"]).strftime('%d-%m-%Y'),
                    'employee_name': employee.get("name", "Unknown"),
                    'grade': employee.get("grade", "Unknown"),
                    'category_name': category.get("name", "Unknown"),
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': req_data.get("submission_notes", ""),
                    'status': req_data.get("status", "Unknown"),
                    'hr_modified': req_data.get('hr_modified', False)
                })
        
        return jsonify({'success': True, 'entries': history_data})
    
    except Exception as e:
        error_print("Error getting updater history", e)
        return jsonify({'success': False, 'error': str(e)}), 500



@ta_bp.route('/updater/get-employees-by-department-grade', methods=['POST'])
def get_employees_by_department_grade():
    """API to get employees filtered by department and grade (like PMO)"""
    has_access, user = check_ta_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        mongo = get_mongo()
        department = request.form.get('department')
        grade = request.form.get('grade')
        
        if not department or not grade:
            return jsonify({'success': False, 'error': 'Department and grade are required'}), 400
        
        # Build query for employees
        query = {
            **SELECTABLE_EMPLOYEE_FILTER_FOR_TA,
            "department": {"$exists": True, "$ne": None},
            "grade": {"$exists": True, "$ne": None}
        }
        
        if department != "all":
            query["department"] = department
        
        if grade != "all":
            query["grade"] = grade
        
        # Allow current user to appear in selection (updaters/validators can assign to themselves)
        # query["_id"] = {"$ne": ObjectId(user['_id'])}
        
        employees = list(mongo.db.users.find(query, {"name": 1, "employee_id": 1, "_id": 1}).sort("name", 1))
        
        # Format for response
        employee_list = []
        for emp in employees:
            employee_list.append({
                'id': str(emp['_id']),
                'name': emp.get('name', 'Unknown'),
                'employee_id': emp.get('employee_id', 'N/A')
            })
        
        return jsonify({
            'success': True,
            'employees': employee_list
        })
    
    except Exception as e:
        error_print("Error fetching employees by department/grade", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@ta_bp.route('/updater/delete-record', methods=['POST'])
def updater_delete_record():
    """Delete a record (updater can delete their own records)"""
    has_access, user = check_ta_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        request_id = request.form.get('request_id', '').strip()
        
        if not request_id:
            flash('No record ID provided.', 'danger')
            return redirect(url_for('ta.updater_dashboard'))
        
        # Find the record - check if it belongs to this updater
        record = mongo.db.points_request.find_one({
            '_id': ObjectId(request_id),
            'created_by_ta_id': ObjectId(user['_id'])
        })
        
        if not record:
            flash('Record not found or you do not have permission to delete it.', 'danger')
            return redirect(url_for('ta.updater_dashboard'))
        
        # Delete from points_request collection
        mongo.db.points_request.delete_one({'_id': ObjectId(request_id)})
        
        # Also delete from points collection (approved records are copied there)
        mongo.db.points.delete_one({'request_id': ObjectId(request_id)})
        
        flash('Record deleted successfully.', 'success')
        return redirect(url_for('ta.updater_dashboard'))
        
    except Exception as e:
        error_print("Error deleting record", e)
        flash(f'Error deleting record: {str(e)}', 'danger')
        return redirect(url_for('ta.updater_dashboard'))


@ta_bp.route('/updater/modify-record', methods=['POST'])
def updater_modify_record():
    """Modify a record (updater can modify their own records)"""
    has_access, user = check_ta_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        request_id = request.form.get('request_id', '').strip()
        new_points = request.form.get('points', '').strip()
        new_notes = request.form.get('notes', '').strip()
        
        if not request_id:
            flash('No record ID provided.', 'danger')
            return redirect(url_for('ta.updater_dashboard'))
        
        # Find the record - check if it belongs to this updater
        record = mongo.db.points_request.find_one({
            '_id': ObjectId(request_id),
            'created_by_ta_id': ObjectId(user['_id'])
        })
        
        if not record:
            flash('Record not found or you do not have permission to modify it.', 'danger')
            return redirect(url_for('ta.updater_dashboard'))
        
        update_data = {
            'last_updated_by': ObjectId(user['_id']),
            'last_updated_at': datetime.utcnow()
        }
        
        if new_points:
            try:
                update_data['points'] = int(new_points)
            except ValueError:
                flash('Invalid points value.', 'danger')
                return redirect(url_for('ta.updater_dashboard'))
        
        if new_notes:
            update_data['submission_notes'] = new_notes
        
        # Update in points_request collection
        mongo.db.points_request.update_one(
            {'_id': ObjectId(request_id)},
            {'$set': update_data}
        )
        
        # Also update in points collection if approved
        if record.get('status') == 'Approved':
            points_update = {'last_updated_at': datetime.utcnow()}
            if new_points:
                points_update['points'] = int(new_points)
            if new_notes:
                points_update['notes'] = new_notes
            mongo.db.points.update_one(
                {'request_id': ObjectId(request_id)},
                {'$set': points_update}
            )
        
        flash('Record updated successfully.', 'success')
        return redirect(url_for('ta.updater_dashboard'))
        
    except Exception as e:
        error_print("Error modifying record", e)
        flash(f'Error modifying record: {str(e)}', 'danger')
        return redirect(url_for('ta.updater_dashboard'))
