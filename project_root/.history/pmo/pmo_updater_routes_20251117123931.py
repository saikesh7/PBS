from flask import render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
from bson import ObjectId
import csv, io, json

from .pmo_main import pmo_bp
from .pmo_helpers import (
    check_pmo_updater_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, parse_date_flexibly,
    validate_event_date, SELECTABLE_EMPLOYEE_FILTER,
    get_pmo_categories, get_pmo_validators
)
from .pmo_email_service import (
    send_new_request_email, send_bulk_request_email
)
from utils.error_handling import error_print

@pmo_bp.route('/updater/dashboard', methods=['GET', 'POST'])
def updater_dashboard():
    """PMO Updater Dashboard"""
    has_access, user = check_pmo_updater_access()
    
    # DEBUG: Print access check result
    if user:
        print(f"DEBUG PMO UPDATER: User={user.get('email')}, dashboard_access={user.get('dashboard_access')}, has_access={has_access}")
    else:
        print(f"DEBUG PMO UPDATER: No user found, has_access={has_access}")
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
            return redirect(get_user_redirect(user))
        return redirect(url_for('auth.login'))
    
    current_quarter, current_month = get_financial_quarter_and_month()
    
    try:
        mongo = get_mongo()
        
        if request.method == 'POST':
            action_type = request.form.get('action_type')
            if action_type == 'assign_reward':
                return handle_single_assignment(user)
            elif action_type == 'bulk_upload_confirmed':
                return handle_bulk_upload_confirmed(user)
            elif action_type == 'utilization_upload_confirmed':
                return handle_utilization_upload_confirmed(user)
        
        employees = list(mongo.db.users.find(SELECTABLE_EMPLOYEE_FILTER).sort("name", 1))
        pmo_categories = get_pmo_categories()
        pmo_validators = [v for v in get_pmo_validators() if str(v['_id']) != str(user['_id'])]
        
        # Build department and grade mapping for dynamic dropdowns
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
        
        history = []
        try:
            category_ids = [cat["_id"] for cat in pmo_categories] if pmo_categories else []
            
            # Track seen request IDs to avoid duplicates
            seen_request_ids = set()
            
            # Get from points_request (pending/approved/rejected)
            # For NEW records: filter by category_ids
            # For OLD records: don't filter by category (old categories may not exist)
            if category_ids:
                # NEW records with category filter
                history_cursor = mongo.db.points_request.find({
                    "category_id": {"$in": category_ids},
                    "status": {"$in": ["Pending", "Approved", "Rejected"]},
                    "$or": [
                        {"created_by_pmo_id": ObjectId(user['_id'])},
                        {"processed_by": ObjectId(user['_id'])}
                    ]
                }).sort("request_date", -1)
            else:
                history_cursor = []
            
            # OLD records without category filter (old categories may have been deleted)
            old_history_cursor = mongo.db.points_request.find({
                "status": {"$in": ["Pending", "Approved", "Rejected"]},
                "$or": [
                    {"created_by_pmo_id": ObjectId(user['_id'])},  # Old updater
                    {"pmo_id": ObjectId(user['_id'])},  # Old validator (very old)
                    {"pending_validator_id": ObjectId(user['_id'])}  # Old validator
                ]
            }).sort("request_date", -1)
            
            # Combine both cursors
            combined_cursor = list(history_cursor) + list(old_history_cursor)
            
            for req in combined_cursor:
                request_id = str(req.get("_id", ""))
                
                # Skip if we've already seen this request
                if request_id in seen_request_ids:
                    continue
                
                seen_request_ids.add(request_id)
                
                emp = mongo.db.users.find_one({"_id": req["user_id"]})
                # Check both hr_categories and old categories collection
                cat = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
                if not cat:
                    cat = mongo.db.categories.find_one({"_id": req["category_id"]})
                # Show record even if category doesn't exist (for old records with deleted categories)
                if emp:
                        # Always use event_date for history display
                        event_date = req.get("event_date", req["request_date"])
                        
                        # Handle different field names for utilization (old vs new records)
                        utilization_val = req.get("utilization_value") or req.get("utilization") or req.get("utilization_percentage")
                        
                        # Separate submission notes and response notes
                        submission_notes = req.get("submission_notes") or req.get("notes") or ""
                        response_notes = req.get("response_notes") or ""
                        
                        history.append({
                            'request_date': event_date,
                            'event_date': event_date,
                            'employee_name': emp.get("name", "Unknown"),
                            'employee_id': emp.get("employee_id", "N/A"),
                            'employee_department': emp.get("department", ""),
                            'category_name': cat.get("name", "Unknown"),
                            'points': req.get("points", 0),
                            'utilization_value': utilization_val,
                            'submission_notes': submission_notes,
                            'response_notes': response_notes,
                            'status': req.get("status", "Unknown"),
                            'request_id': str(req.get("_id", ""))
                        })
                
            # Also get from points collection (approved records that were moved)
            # Don't filter by category for old records (old categories may have been deleted)
            if category_ids:
                points_cursor = mongo.db.points.find({
                    "awarded_by": ObjectId(user['_id']),
                    "category_id": {"$in": category_ids}
                }).sort("created_at", -1)
            else:
                # No category filter for old records
                points_cursor = mongo.db.points.find({
                    "awarded_by": ObjectId(user['_id'])
                }).sort("created_at", -1)
            
            for point in points_cursor:
                    emp = mongo.db.users.find_one({"_id": point["user_id"]})
                    # Check both hr_categories and old categories collection
                    cat = mongo.db.hr_categories.find_one({"_id": point["category_id"]})
                    if not cat:
                        cat = mongo.db.categories.find_one({"_id": point["category_id"]})
                    # Show record even if category doesn't exist (for old records with deleted categories)
                    if emp:
                        # Always use award_date (which is the event_date) for history display
                        event_date = point.get("award_date") or point.get("event_date") or point.get("created_at")
                        
                        # Handle different field names for utilization (old vs new records)
                        utilization_val = point.get("utilization_value") or point.get("utilization") or point.get("utilization_percentage")
                        
                        # Separate submission notes and response notes for old records
                        submission_notes = point.get("submission_notes") or point.get("notes") or ""
                        response_notes = point.get("response_notes") or ""
                        
                        history.append({
                            'request_date': event_date,
                            'event_date': event_date,
                            'employee_name': emp.get("name", "Unknown"),
                            'employee_id': emp.get("employee_id", "N/A"),
                            'employee_department': emp.get("department", ""),
                            'category_name': cat.get("name", "Unknown"),
                            'points': point.get("points", 0),
                            'utilization_value': utilization_val,
                            'submission_notes': submission_notes,
                            'response_notes': response_notes,
                            'status': 'Approved',  # Points collection only has approved records
                            'request_id': str(point.get("request_id", ""))
                        })
            
            # Sort combined history by status priority (Approved/Rejected first, then Pending), then by date
            # Status priority: Approved=1, Rejected=2, Pending=3 (lower number = higher priority)
            def sort_key(x):
                status_priority = {'Approved': 1, 'Rejected': 2, 'Pending': 3}
                return (status_priority.get(x['status'], 4), -x['request_date'].timestamp() if x['request_date'] else 0)
            
            history.sort(key=sort_key)
        except Exception as hist_error:
            error_print("Error loading history", hist_error)
            # Continue without history
        
        return render_template(
            'pmo_updater_dashboard.html',
            user=user,
            employees=employees,
            departments=departments,
            department_grades_map=department_grades_map,
            pmo_categories=pmo_categories,
            pmo_validators=pmo_validators,
            current_quarter=current_quarter,
            current_month=current_month,
            history=history
        )
    
    except Exception as e:
        error_print("Error in PMO updater dashboard", e)
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))

def handle_single_assignment(user):
    """Handle single reward assignment"""
    mongo = get_mongo()
    
    employee_id = request.form.get('employee_id')
    category_id = request.form.get('category_id')
    validator_id = request.form.get('validator_id')
    notes = request.form.get('notes', '').strip() or request.form.get('notes_full', '').strip()
    event_date_str = request.form.get('event_date')
    utilization_str = request.form.get('utilization', '').strip()
    
    # Validate required fields with specific messages
    missing_fields = []
    if not employee_id:
        missing_fields.append('Employee')
    if not category_id:
        missing_fields.append('Award Category')
    if not validator_id:
        missing_fields.append('Validator')
    if not notes:
        missing_fields.append('Notes/Reason')
    
    if missing_fields:
        flash(f'Required field(s) missing: {", ".join(missing_fields)}. Please complete all required fields.', 'danger')
        return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
    
    if str(validator_id) == str(user['_id']):
        flash('Invalid validator selection. You cannot submit requests for your own validation. Please select a different validator.', 'danger')
        return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
    
    event_date, error = validate_event_date(event_date_str, allow_future=True) if event_date_str else (datetime.utcnow(), None)
    if error:
        flash(error, 'danger')
        return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
    
    employee = mongo.db.users.find_one({"employee_id": employee_id})
    category = mongo.db.hr_categories.find_one({"_id": ObjectId(category_id)})
    
    if not employee:
        flash('Employee not found. Please select a valid employee.', 'danger')
        return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
    
    if not category:
        flash('Award category not found. Please select a valid category.', 'danger')
        return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
    
    # Check if this is a utilization category (handle typo "utlization" too)
    category_name = category.get('name', '').lower()
    is_utilization = 'utilization' in category_name or 'utlization' in category_name or 'billable' in category_name or 'util' in category_name
    
    points_per_unit = category.get('points_per_unit', {})
    employee_grade = employee.get('grade', 'base')
    points = points_per_unit.get(employee_grade, points_per_unit.get('base', 0)) if isinstance(points_per_unit, dict) else points_per_unit
    
    utilization_value = None
    if is_utilization:
        # For utilization category, require utilization percentage
        if not utilization_str:
            flash('Required field missing: Utilization Percentage. Please enter the utilization value for this category.', 'danger')
            return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
        
        try:
            # Handle different formats: 88, 88%, 0.88
            utilization_cleaned = utilization_str.replace('%', '').strip()
            utilization_float = float(utilization_cleaned)
            
            # If value is greater than 1, assume it's a percentage (88 -> 0.88)
            if utilization_float > 1:
                utilization_value = utilization_float / 100.0
            else:
                utilization_value = utilization_float
            
            # Validate range
            if not (0 <= utilization_value <= 1):
                flash('Invalid utilization value. Utilization percentage must be between 0% and 100%. Please enter a valid value.', 'danger')
                return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
        except ValueError:
            flash('Invalid utilization format. Please enter a valid number (e.g., 88, 88%, or 0.88).', 'danger')
            return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
        
        # For utilization, points are 0 (stored as percentage only)
        points = 0
        
        # Check for existing utilization record in the same month
        start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 
                     else start_of_month.replace(year=start_of_month.year + 1, month=1))
        
        # Check in points_request collection for Pending or Approved records
        existing_request = mongo.db.points_request.find_one({
            "user_id": ObjectId(employee["_id"]),
            "category_id": ObjectId(category["_id"]),
            "event_date": {"$gte": start_of_month, "$lt": next_month},
            "status": {"$in": ["Approved", "Pending"]}
        })
        
        # Also check in points collection (approved records that were moved)
        existing_point = mongo.db.points.find_one({
            "user_id": ObjectId(employee["_id"]),
            "category_id": ObjectId(category["_id"]),
            "award_date": {"$gte": start_of_month, "$lt": next_month}
        })
        
        if existing_request or existing_point:
            month_year = event_date.strftime('%B %Y')
            flash(f'⚠️ Already available in processing for {month_year}. Only one utilization request per employee per month is allowed.', 'warning')
            return redirect(url_for('pmo.updater_dashboard', tab='single-request'))
    
    request_data = {
        "user_id": ObjectId(employee["_id"]),
        "category_id": ObjectId(category["_id"]),
        "points": points,
        "submission_notes": notes,
        "updated_by": "PMO",
        "status": "Pending",
        "request_date": datetime.utcnow(),
        "event_date": event_date,
        "assigned_validator_id": ObjectId(validator_id),
        "created_by_pmo_id": ObjectId(user['_id'])
    }
    
    if utilization_value is not None:
        request_data['utilization_value'] = utilization_value
    
    result = mongo.db.points_request.insert_one(request_data)
    
    from services.realtime_events import publish_request_raised
    request_data['_id'] = result.inserted_id
    validator = mongo.db.users.find_one({'_id': ObjectId(validator_id)})
    if validator:
        # Ensure category_department is lowercase for real-time routing
        if 'category_department' in category:
            category['category_department'] = category['category_department'].lower()
        else:
            category['category_department'] = 'pmo_up'
        
        publish_request_raised(request_data, employee, validator, category)
        
        # Send email notification to validator
        if validator.get('email'):
            send_new_request_email(
                validator_email=validator.get('email'),
                validator_name=validator.get('name', 'Validator'),
                employee_name=employee.get('name', 'Unknown'),
                category_name=category.get('name', 'Unknown'),
                points=points,
                event_date=event_date.strftime('%d-%m-%Y'),
                notes=notes
            )
    
    flash('Reward assigned successfully!', 'success')
    return redirect(url_for('pmo.updater_dashboard', tab='single-request'))

@pmo_bp.route('/updater/validate-bulk-upload', methods=['POST'])
def validate_bulk_upload():
    """Validate bulk CSV upload"""
    has_access, user = check_pmo_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        file = request.files.get('csv_file')
        
        if not file:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        expected_headers = ['employee_id', 'validator_employee_id', 'event_date', 'category_code', 'department', 'notes']
        if csv_reader.fieldnames != expected_headers:
            return jsonify({'success': False, 'error': f'Invalid CSV headers. Expected: {", ".join(expected_headers)}'})
        
        # Dynamically fetch valid PMO categories (excluding utilization and employee_raised)
        pmo_categories = list(mongo.db.hr_categories.find({
            'category_department': {'$regex': '^pmo', '$options': 'i'},
            'category_status': 'active',
            'name': {'$not': {'$regex': 'utilization|billable', '$options': 'i'}},
            'category_type': {'$not': {'$regex': 'employee.*raised', '$options': 'i'}}
        }, {'name': 1}))
        
        # Create list of valid category codes (normalized: lowercase with underscores)
        valid_categories_for_bulk = []
        category_name_map = {}  # Map normalized code to actual category name
        for cat in pmo_categories:
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
                department = row.get('department', '').strip()
                notes = row.get('notes', '').strip()
                
                # Skip completely empty rows (all fields are empty)
                if not any([employee_id, validator_employee_id, event_date_str, category_code, department, notes]):
                    continue
                
                # Validate required fields with specific messages
                missing_fields = []
                if not employee_id:
                    missing_fields.append('employee_id')
                if not validator_employee_id:
                    missing_fields.append('validator_employee_id')
                if not event_date_str:
                    missing_fields.append('event_date')
                if not category_code:
                    missing_fields.append('category_code')
                if not notes:
                    missing_fields.append('notes')
                
                if missing_fields:
                    raise ValueError(f"Required field(s) missing: {', '.join(missing_fields)}. Please complete all required fields.")
                
                # Find validator by employee_id
                row_validator = mongo.db.users.find_one({"employee_id": validator_employee_id})
                if not row_validator:
                    raise ValueError(f"Validator with employee ID '{validator_employee_id}' not found")
                
                # Check if validator has PMO validator access
                validator_dashboard_access = row_validator.get('dashboard_access', [])
                if 'pmo_va' not in validator_dashboard_access:
                    raise ValueError(f"User '{validator_employee_id}' does not have PMO Validator access")
                
                # Check if validator is not the same as current user
                if str(row_validator['_id']) == str(user['_id']):
                    raise ValueError("Invalid validator selection. You cannot submit requests for your own validation. Please select a different validator.")
                
                # Validate event date
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
                
                # Find employee
                employee_query = {"employee_id": employee_id}
                employee_query.update(SELECTABLE_EMPLOYEE_FILTER)
                employee = mongo.db.users.find_one(employee_query)
                if not employee:
                    raise ValueError(f"Employee ID '{employee_id}' not found in database")
                
                # Validate department matches employee's actual department
                employee_department = employee.get('department', '')
                if department and employee_department:
                    # Normalize both for comparison (case-insensitive)
                    if department.strip().lower() != employee_department.strip().lower():
                        raise ValueError(f"Wrong department '{department}'. Employee '{employee_id}' belongs to '{employee_department}'")
                
                # Find category using the actual category name from our map
                actual_category_name = category_name_map.get(normalized_category_code)
                if not actual_category_name:
                    raise ValueError(f"Category code '{category_code}' not found in mapping")
                
                # Find category in database
                category = mongo.db.hr_categories.find_one({
                    "name": actual_category_name,
                    "category_department": {"$regex": "^pmo", "$options": "i"},
                    "category_status": "active"
                })
                
                if not category:
                    raise ValueError(f"Category '{actual_category_name}' not found in database. Available: {', '.join(category_name_map.values())}")
                
                # Check employee grade
                employee_grade = employee.get('grade')
                if not employee_grade:
                    raise ValueError(f"Employee '{employee_id}' has no grade assigned")
                
                # Get points based on grade
                points_per_unit_config = category.get('points_per_unit', 0)
                if isinstance(points_per_unit_config, dict):
                    # Get points for employee's grade, fallback to base
                    points_per_unit = points_per_unit_config.get(employee_grade, points_per_unit_config.get('base', 0))
                else:
                    points_per_unit = points_per_unit_config
                
                if points_per_unit <= 0:
                    raise ValueError(f"Category '{category_code}' has invalid or zero points for grade '{employee_grade}'")
                
                valid_rows.append({
                    'row_number': row_num,
                    'employee_id': employee_id,
                    'employee_name': employee.get('name', 'Unknown'),
                    'employee_object_id': str(employee['_id']),
                    'validator_employee_id': validator_employee_id,
                    'validator_name': row_validator.get('name', 'Unknown'),
                    'validator_object_id': str(row_validator['_id']),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'event_date_obj': event_date.isoformat(),
                    'category_code': category_code,
                    'category_name': category.get('name', 'Unknown'),
                    'category_id': str(category['_id']),
                    'points': points_per_unit,
                    'notes': notes
                })
            
            except Exception as e:
                invalid_rows.append({
                    'row_number': row_num,
                    'employee_id': employee_id if 'employee_id' in locals() else '',
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'valid_rows': valid_rows,
            'invalid_rows': invalid_rows
        })
    
    except Exception as e:
        error_print("Error validating bulk upload", e)
        return jsonify({'success': False, 'error': str(e)}), 500

def handle_bulk_upload_confirmed(user):
    """Handle confirmed bulk upload"""
    mongo = get_mongo()
    
    try:
        validated_data_json = request.form.get('validated_data')
        
        if not validated_data_json:
            flash('No validated data received', 'danger')
            return redirect(url_for('pmo.updater_dashboard', tab='bulk-upload'))
        
        validated_rows = json.loads(validated_data_json)
        
        if not validated_rows:
            flash('No valid rows to process', 'warning')
            return redirect(url_for('pmo.updater_dashboard', tab='bulk-upload'))
        
        success_count = 0
        error_count = 0
        validators_notified = {}  # Track validators to send single email per validator
        
        for row in validated_rows:
            try:
                event_date = datetime.fromisoformat(row['event_date_obj'])
                category = mongo.db.hr_categories.find_one({"_id": ObjectId(row['category_id'])})
                validator = mongo.db.users.find_one({"_id": ObjectId(row['validator_object_id'])})
                
                if not category or not validator:
                    error_count += 1
                    continue
                
                request_data = {
                    "user_id": ObjectId(row['employee_object_id']),
                    "category_id": ObjectId(row['category_id']),
                    "points": row['points'],
                    "submission_notes": row['notes'],
                    "updated_by": "PMO",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date,
                    "assigned_validator_id": ObjectId(row['validator_object_id']),
                    "created_by_pmo_id": ObjectId(user['_id'])
                }
                
                result = mongo.db.points_request.insert_one(request_data)
                request_data['_id'] = result.inserted_id
                
                # Send real-time notification
                from services.realtime_events import publish_request_raised
                employee = mongo.db.users.find_one({'_id': ObjectId(row['employee_object_id'])})
                if employee and validator:
                    # Ensure category_department is lowercase for real-time routing
                    if 'category_department' in category:
                        category['category_department'] = category['category_department'].lower()
                    else:
                        category['category_department'] = 'pmo_up'
                    
                    # Add source indicator for PMO
                    request_data['created_by_pmo_id'] = ObjectId(user['_id'])
                    
                    publish_request_raised(request_data, employee, validator, category)
                
                # Track validator for bulk email
                validator_id_str = str(validator['_id'])
                if validator_id_str not in validators_notified:
                    validators_notified[validator_id_str] = {
                        'validator': validator,
                        'count': 0
                    }
                validators_notified[validator_id_str]['count'] += 1
                
                success_count += 1
            except Exception as e:
                error_print(f"Error processing row {row.get('row_number')}", e)
                error_count += 1
                continue
        
        # Send single bulk email to each validator
        for validator_id, data in validators_notified.items():
            validator = data['validator']
            count = data['count']
            if validator.get('email'):
                send_bulk_request_email(
                    validator_email=validator.get('email'),
                    validator_name=validator.get('name', 'Validator'),
                    request_count=count,
                    updater_name=user.get('name', 'PMO Updater')
                )
        
        if success_count > 0:
            flash(f'Successfully submitted {success_count} reward request(s) for validation.', 'success')
        if error_count > 0:
            flash(f'{error_count} row(s) failed to process.', 'warning')
        
        return redirect(url_for('pmo.updater_dashboard', tab='bulk-upload'))
    
    except Exception as e:
        error_print("Error processing bulk upload", e)
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('pmo.updater_dashboard', tab='bulk-upload'))

@pmo_bp.route('/updater/validate-utilization-upload', methods=['POST'])
def validate_utilization_upload():
    """Validate utilization CSV upload"""
    has_access, user = check_pmo_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        file = request.files.get('csv_file')
        
        if not file:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        # Find utilization category for PMO
        category = mongo.db.hr_categories.find_one({
            "name": {"$regex": "utilization", "$options": "i"},
            "category_department": {"$regex": "^pmo", "$options": "i"},
            "category_status": "active"
        })
        if not category:
            return jsonify({'success': False, 'error': 'Utilization category not found in PMO categories'})
        
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        expected_headers = ['employee_id', 'validator_employee_id', 'event_date', 'category_code', 'department', 'utilization', 'notes']
        if csv_reader.fieldnames != expected_headers:
            return jsonify({'success': False, 'error': f'Invalid headers. Expected: {", ".join(expected_headers)}'})
        
        valid_rows = []
        invalid_rows = []
        
        for row_num, row in enumerate(csv_reader, start=2):
            try:
                employee_id = row.get('employee_id', '').strip()
                validator_employee_id = row.get('validator_employee_id', '').strip()
                event_date_str = row.get('event_date', '').strip()
                category_code = row.get('category_code', '').strip()
                utilization_str = row.get('utilization', '').strip()
                notes = row.get('notes', '').strip()
                department = row.get('department', '').strip()
                
                # Skip completely empty rows (all fields are empty)
                if not any([employee_id, validator_employee_id, event_date_str, category_code, utilization_str, notes, department]):
                    continue
                
                # Validate required fields with specific messages
                missing_fields = []
                if not employee_id:
                    missing_fields.append('employee_id')
                if not validator_employee_id:
                    missing_fields.append('validator_employee_id')
                if not event_date_str:
                    missing_fields.append('event_date')
                if not utilization_str:
                    missing_fields.append('utilization')
                if not notes:
                    missing_fields.append('notes')
                
                if missing_fields:
                    raise ValueError(f"Required field(s) missing: {', '.join(missing_fields)}. Please complete all required fields.")
                
                # Find validator by employee_id
                row_validator = mongo.db.users.find_one({"employee_id": validator_employee_id})
                if not row_validator:
                    raise ValueError(f"Validator with employee ID '{validator_employee_id}' not found")
                
                # Check if validator has PMO validator access
                validator_dashboard_access = row_validator.get('dashboard_access', [])
                if 'pmo_va' not in validator_dashboard_access:
                    raise ValueError(f"User '{validator_employee_id}' does not have PMO Validator access")
                
                # Check if validator is not the same as current user
                if str(row_validator['_id']) == str(user['_id']):
                    raise ValueError("Invalid validator selection. You cannot submit requests for your own validation. Please select a different validator.")
                
                # Accept both 'utilization' and 'utilization_billable'
                if category_code.lower() not in ['utilization', 'utilization_billable', 'utilization billable']:
                    raise ValueError("Invalid category_code. Must be 'utilization' or 'utilization_billable'.")
                
                employee = mongo.db.users.find_one({"employee_id": employee_id})
                if not employee:
                    raise ValueError(f"Employee '{employee_id}' not found")
                
                event_date = parse_date_flexibly(event_date_str)
                if not event_date:
                    raise ValueError(f"Invalid date format for '{event_date_str}'. Please use DD-MM-YYYY format.")

                
                # Check for existing utilization record in the same month
                start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 
                             else start_of_month.replace(year=start_of_month.year + 1, month=1))
                
                existing_record = mongo.db.points_request.find_one({
                    "user_id": ObjectId(employee["_id"]),
                    "category_id": ObjectId(category["_id"]),
                    "event_date": {"$gte": start_of_month, "$lt": next_month},
                    "status": {"$in": ["Approved", "Pending"]}
                })
                
                if existing_record:
                    raise ValueError(f"⚠️ Already available in processing for {event_date.strftime('%B %Y')}. Only one utilization request per employee per month is allowed.")
                
                # Parse utilization value
                try:
                    utilization_cleaned = utilization_str.replace('%', '').strip()
                    utilization_value = float(utilization_cleaned)
                    if utilization_value > 1:
                        utilization_value /= 100.0
                    
                    if not (0 <= utilization_value <= 1):
                        raise ValueError(f"Invalid utilization value '{utilization_str}'. Utilization percentage must be between 0% and 100%. Please enter a valid value.")
                except ValueError as ve:
                    if "could not convert" in str(ve):
                        raise ValueError(f"Invalid utilization format '{utilization_str}'. Please enter a valid number (e.g., 88, 88%, or 0.88).")
                    raise
                
                valid_rows.append({
                    'row_number': row_num,
                    'employee_id': employee_id,
                    'employee_name': employee.get('name', 'Unknown'),
                    'employee_object_id': str(employee['_id']),
                    'validator_employee_id': validator_employee_id,
                    'validator_name': row_validator.get('name', 'Unknown'),
                    'validator_object_id': str(row_validator['_id']),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'event_date_obj': event_date.isoformat(),
                    'utilization_value': utilization_value,
                    'notes': notes
                })
            
            except Exception as e:
                invalid_rows.append({
                    'row_number': row_num,
                    'employee_id': employee_id if 'employee_id' in locals() else '',
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'valid_rows': valid_rows,
            'invalid_rows': invalid_rows,
            'category_name': category.get('name', 'Utilization'),
            'category_id': str(category['_id'])
        })
    
    except Exception as e:
        error_print("Error validating utilization upload", e)
        return jsonify({'success': False, 'error': str(e)}), 500

def handle_utilization_upload_confirmed(user):
    """Handle confirmed utilization upload"""
    mongo = get_mongo()
    
    try:
        validated_data_json = request.form.get('validated_data')
        if not validated_data_json:
            flash('No validated data received', 'danger')
            return redirect(url_for('pmo.updater_dashboard', tab='utilization-upload'))
        
        validated_rows = json.loads(validated_data_json)
        category_id = request.form.get('category_id')
        
        print(f"DEBUG: category_id from form: {category_id}")
        print(f"DEBUG: validated_rows count: {len(validated_rows)}")
        
        if not category_id:
            flash('Category not specified', 'danger')
            return redirect(url_for('pmo.updater_dashboard', tab='utilization-upload'))
        
        category = mongo.db.hr_categories.find_one({"_id": ObjectId(category_id)})
        
        print(f"DEBUG: category found: {category.get('name') if category else 'None'}")
        
        if not category:
            flash('Category not found', 'danger')
            return redirect(url_for('pmo.updater_dashboard', tab='utilization-upload'))
        
        success_count = 0
        validators_notified = {}  # Track validators for bulk email
        
        for row in validated_rows:
            try:
                event_date = datetime.fromisoformat(row['event_date_obj'])
                row_validator = mongo.db.users.find_one({"_id": ObjectId(row['validator_object_id'])})
                
                if not row_validator:
                    continue
                
                request_data = {
                    "user_id": ObjectId(row['employee_object_id']),
                    "category_id": ObjectId(category['_id']),
                    "points": 0,
                    "utilization_value": row['utilization_value'],
                    "submission_notes": row['notes'],
                    "updated_by": "PMO",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date,
                    "assigned_validator_id": ObjectId(row['validator_object_id']),
                    "created_by_pmo_id": ObjectId(user['_id'])
                }
                
                result = mongo.db.points_request.insert_one(request_data)
                request_data['_id'] = result.inserted_id
                
                from services.realtime_events import publish_request_raised
                employee = mongo.db.users.find_one({'_id': ObjectId(row['employee_object_id'])})
                if employee and row_validator:
                    # Ensure category_department is lowercase for real-time routing
                    if 'category_department' in category:
                        category['category_department'] = category['category_department'].lower()
                    else:
                        category['category_department'] = 'pmo_up'
                    
                    publish_request_raised(request_data, employee, row_validator, category)
                
                # Track validator for bulk email
                validator_id_str = str(row_validator['_id'])
                if validator_id_str not in validators_notified:
                    validators_notified[validator_id_str] = {
                        'validator': row_validator,
                        'count': 0
                    }
                validators_notified[validator_id_str]['count'] += 1
                
                success_count += 1
            except Exception as e:
                error_print(f"Error processing utilization row {row.get('row_number')}", e)
                continue
        
        # Send single bulk email to each validator
        for validator_id, data in validators_notified.items():
            validator = data['validator']
            count = data['count']
            if validator.get('email'):
                send_bulk_request_email(
                    validator_email=validator.get('email'),
                    validator_name=validator.get('name', 'Validator'),
                    request_count=count,
                    updater_name=user.get('name', 'PMO Updater')
                )
        
        if success_count > 0:
            flash(f'Successfully submitted {success_count} utilization record(s) for validation.', 'success')
        
        return redirect(url_for('pmo.updater_dashboard', tab='utilization-upload'))
    
    except Exception as e:
        error_print("Error processing utilization upload", e)
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('pmo.updater_dashboard', tab='utilization-upload'))

@pmo_bp.route('/updater/download-bulk-template')
def download_bulk_template():
    """Download CSV template for bulk upload"""
    has_access, user = check_pmo_updater_access()
    if not has_access:
        flash('Access denied', 'danger')
        return redirect(url_for('auth.login'))
    
    from flask import make_response
    
    try:
        mongo = get_mongo()
        
        # Use current date as default
        current_date = datetime.now().strftime('%d-%m-%Y')
        
        # Dynamically fetch valid PMO categories (excluding utilization and employee_raised)
        pmo_categories = list(mongo.db.hr_categories.find({
            'category_department': {'$regex': '^pmo', '$options': 'i'},
            'category_status': 'active',
            'name': {'$not': {'$regex': 'utilization|billable', '$options': 'i'}},
            'category_type': {'$not': {'$regex': 'employee.*raised', '$options': 'i'}}
        }, {'name': 1}).sort('name', 1))
        
        csv_content = "employee_id,validator_employee_id,event_date,category_code,department,notes\n"
        
        # Add one sample row for EACH category so users can see all available codes
        if pmo_categories:
            for idx, cat in enumerate(pmo_categories, start=1):
                cat_code = cat.get('name', '').lower().replace(' ', '_').replace('&', 'and')
                cat_name = cat.get('name', 'Category')
                # Alternate between departments for variety
                dept = 'Engineering' if idx % 2 == 1 else 'Sales'
                csv_content += f"EMP{idx:03d},VAL001,{current_date},{cat_code},{dept},Sample notes for {cat_name}\n"
        else:
            # Fallback if no categories found
            csv_content += f"EMP001,VAL001,{current_date},category_code,Engineering,Sample notes\n"
        
        filename = "pmo_bulk_upload_template.csv"
        
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
        return redirect(url_for('pmo.updater_dashboard'))

@pmo_bp.route('/updater/download-utilization-template')
def download_utilization_template():
    """Download CSV template for utilization upload"""
    has_access, user = check_pmo_updater_access()
    if not has_access:
        flash('Access denied', 'danger')
        return redirect(url_for('auth.login'))
    
    from flask import make_response
    
    # Use current date as default
    current_date = datetime.now().strftime('%d-%m-%Y')
    
    csv_content = "employee_id,validator_employee_id,event_date,category_code,department,utilization,notes\n"
    csv_content += f"EMP001,VAL001,{current_date},utilization,Engineering,88%,Sample utilization notes\n"
    filename = "pmo_utilization_upload_template.csv"
    
    response = make_response(csv_content)
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@pmo_bp.route('/updater/get-employees-by-department-grade', methods=['POST'])
def get_employees_by_department_grade():
    """API to get employees filtered by department and grade"""
    has_access, user = check_pmo_updater_access()
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
            **SELECTABLE_EMPLOYEE_FILTER,
            "employee_id": {"$exists": True, "$ne": None},
            "department": {"$exists": True, "$ne": None},
            "grade": {"$exists": True, "$ne": None}
        }
        
        if department != "all":
            query["department"] = department
        
        if grade != "all":
            query["grade"] = grade
        
        # Exclude current user from selection
        query["_id"] = {"$ne": ObjectId(user['_id'])}
        
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


@pmo_bp.route('/updater/get-valid-category-codes', methods=['GET'])
def get_valid_category_codes():
    """Get list of valid category codes for bulk upload"""
    has_access, user = check_pmo_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        
        # Dynamically fetch valid PMO categories (excluding utilization and employee_raised)
        pmo_categories = list(mongo.db.hr_categories.find({
            'category_department': {'$regex': '^pmo', '$options': 'i'},
            'category_status': 'active',
            'name': {'$not': {'$regex': 'utilization|billable', '$options': 'i'}},
            'category_type': {'$not': {'$regex': 'employee.*raised', '$options': 'i'}}
        }, {'name': 1}).sort('name', 1))
        
        # Create list with both code and name
        category_list = []
        for cat in pmo_categories:
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


@pmo_bp.route('/updater/check-utilization-duplicate', methods=['POST'])
def check_utilization_duplicate():
    """Check if utilization already exists for employee in given month"""
    has_access, user = check_pmo_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        mongo = get_mongo()
        data = request.get_json()
        
        employee_id = data.get('employee_id')
        category_id = data.get('category_id')
        event_date_str = data.get('event_date')
        
        if not all([employee_id, category_id, event_date_str]):
            return jsonify({'success': True, 'duplicate': False})
        
        # Find employee
        employee = mongo.db.users.find_one({"employee_id": employee_id})
        if not employee:
            return jsonify({'success': True, 'duplicate': False})
        
        # Parse date
        event_date = parse_date_flexibly(event_date_str)
        if not event_date:
            return jsonify({'success': True, 'duplicate': False})
        
        # Check for existing utilization in the same month
        start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 
                     else start_of_month.replace(year=start_of_month.year + 1, month=1))
        
        # Check in points_request collection
        existing_request = mongo.db.points_request.find_one({
            "user_id": ObjectId(employee["_id"]),
            "category_id": ObjectId(category_id),
            "event_date": {"$gte": start_of_month, "$lt": next_month},
            "status": {"$in": ["Approved", "Pending"]}
        })
        
        # Check in points collection
        existing_point = mongo.db.points.find_one({
            "user_id": ObjectId(employee["_id"]),
            "category_id": ObjectId(category_id),
            "award_date": {"$gte": start_of_month, "$lt": next_month}
        })
        
        if existing_request or existing_point:
            month_year = event_date.strftime('%B %Y')
            return jsonify({
                'success': True,
                'duplicate': True,
                'message': f'⚠️ Already available in processing for {month_year}. Only one utilization request per employee per month is allowed.'
            })
        
        return jsonify({'success': True, 'duplicate': False})
    
    except Exception as e:
        error_print("Error checking utilization duplicate", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@pmo_bp.route('/test-email', methods=['GET'])
def test_email():
    """Test email functionality"""
    has_access, user = check_pmo_updater_access()
    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from flask import current_app
        
        user_email = user.get('email')
        if not user_email:
            return jsonify({'success': False, 'error': f'Your account has no email address. User data: {user.get("name")}, {user.get("employee_id")}'}), 400
        
        print(f"\n{'='*60}")
        print(f"🧪 EMAIL TEST STARTED")
        print(f"{'='*60}")
        print(f"To: {user_email}")
        print(f"From: {current_app.config['MAIL_USERNAME']}")
        print(f"Server: {current_app.config['MAIL_SERVER']}:{current_app.config['MAIL_PORT']}")
        
        # Create simple test email
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "PMO Email Test"
        msg['From'] = current_app.config['MAIL_USERNAME']
        msg['To'] = user_email
        
        html = f"""
        <html>
        <body>
            <h2>Test Email from PMO System</h2>
            <p>Hello {user.get('name', 'User')},</p>
            <p>This is a test email. If you receive this, the email system is working!</p>
            <p>Sent at: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        # Send synchronously for testing
        print(f"Connecting to SMTP server...")
        server = smtplib.SMTP(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT'])
        server.set_debuglevel(1)
        
        print(f"Starting TLS...")
        server.starttls()
        
        print(f"Logging in...")
        server.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
        
        print(f"Sending message...")
        server.send_message(msg)
        
        print(f"Closing connection...")
        server.quit()
        
        print(f"✅ Email sent successfully!")
        print(f"{'='*60}\n")
        
        return jsonify({
            'success': True, 
            'message': f'Test email sent to {user_email}. Check your inbox!'
        })
        
    except Exception as e:
        print(f"❌ Email test failed: {str(e)}")
        print(f"{'='*60}\n")
        error_print("Error sending test email", e)
        return jsonify({'success': False, 'error': str(e)}), 500
