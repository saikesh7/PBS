from flask import render_template, request, redirect, url_for, flash, jsonify, make_response
from datetime import datetime
from bson import ObjectId
import csv, io, json

from .hr_main import hr_bp
from .hr_helpers import (
    check_hr_updater_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, parse_date_flexibly,
    validate_event_date, SELECTABLE_EMPLOYEE_FILTER,
    get_hr_categories, get_hr_validators
)
from utils.error_handling import error_print

@hr_bp.route('/updater/dashboard', methods=['GET', 'POST'])
def updater_dashboard():
    """HR Updater Dashboard"""
    has_access, user = check_hr_updater_access()
    
    if not has_access:
        if not user:
            flash('You need to log in first', 'warning')
        else:
            flash('You do not have permission to access this page', 'danger')
            return redirect(get_user_redirect(user))
        return redirect(url_for('auth.login'))
    managers = list(mongo.db.users.find({'role': 'Manager'}))
    # Fetch only users who have employee_level = 'dp' (case-insensitive)
    dps = list(mongo.db.users.find({
        'employee_level': {'$regex': '^dp$', '$options': 'i'}
    }))
    
    current_quarter, current_month = get_financial_quarter_and_month()
    
    try:
        mongo = get_mongo()
        
        if request.method == 'POST':
            action_type = request.form.get('action_type')
            if action_type == 'assign_reward':
                return handle_single_assignment(user)
            elif action_type == 'bulk_upload_confirmed':
                return handle_bulk_upload_confirmed(user)
        
        employees = list(mongo.db.users.find(SELECTABLE_EMPLOYEE_FILTER).sort("name", 1))
        hr_categories = get_hr_categories()
        hr_validators = [v for v in get_hr_validators() if str(v['_id']) != str(user['_id'])]
        
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
            category_ids = [cat["_id"] for cat in hr_categories] if hr_categories else []
            seen_request_ids = set()
            
            if category_ids:
                history_cursor = mongo.db.points_request.find({
                    "category_id": {"$in": category_ids},
                    "status": {"$in": ["Pending", "Approved", "Rejected"]},
                    "$or": [
                        {"created_by_hr_id": ObjectId(user['_id'])},
                        {"processed_by": ObjectId(user['_id'])}
                    ]
                }).sort("request_date", -1)
            else:
                history_cursor = []
            
            for req in list(history_cursor):
                request_id = str(req.get("_id", ""))
                if request_id in seen_request_ids:
                    continue
                seen_request_ids.add(request_id)
                
                emp = mongo.db.users.find_one({"_id": req["user_id"]})
                cat = mongo.db.hr_categories.find_one({"_id": req["category_id"]})
                
                if emp and cat:
                    event_date = req.get("event_date", req["request_date"])
                    history.append({
                        'request_date': event_date,
                        'event_date': event_date,
                        'employee_name': emp.get("name", "Unknown"),
                        'employee_id': emp.get("employee_id", "N/A"),
                        'employee_department': emp.get("department", ""),
                        'category_name': cat.get("name", "Unknown"),
                        'points': req.get("points", 0),
                        'submission_notes': req.get("submission_notes", ""),
                        'response_notes': req.get("response_notes", ""),
                        'status': req.get("status", "Unknown"),
                        'request_id': request_id
                    })
            
            if category_ids:
                points_cursor = mongo.db.points.find({
                    "awarded_by": ObjectId(user['_id']),
                    "category_id": {"$in": category_ids}
                }).sort("created_at", -1)
                
                for point in points_cursor:
                    emp = mongo.db.users.find_one({"_id": point["user_id"]})
                    cat = mongo.db.hr_categories.find_one({"_id": point["category_id"]})
                    
                    if emp and cat:
                        event_date = point.get("award_date") or point.get("created_at")
                        history.append({
                            'request_date': event_date,
                            'event_date': event_date,
                            'employee_name': emp.get("name", "Unknown"),
                            'employee_id': emp.get("employee_id", "N/A"),
                            'employee_department': emp.get("department", ""),
                            'category_name': cat.get("name", "Unknown"),
                            'points': point.get("points", 0),
                            'submission_notes': point.get("submission_notes", ""),
                            'response_notes': point.get("response_notes", ""),
                            'status': 'Approved',
                            'request_id': str(point.get("request_id", ""))
                        })
            
            history.sort(key=lambda x: x['request_date'], reverse=True)
        except Exception as hist_error:
            error_print("Error loading history", hist_error)
        
        return render_template(
            'hr_updater_dashboard.html',
            user=user,
            employees=employees,
            departments=departments,
            department_grades_map=department_grades_map,
            hr_categories=hr_categories,
            hr_validators=hr_validators,
            current_quarter=current_quarter,
            current_month=current_month,
            history=history
        )
    
    except Exception as e:
        error_print("Error in HR updater dashboard", e)
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))


def handle_single_assignment(user):
    """Handle single reward assignment"""
    mongo = get_mongo()
    
    employee_id = request.form.get('employee_id')
    category_id = request.form.get('category_id')
    validator_id = request.form.get('validator_id')
    notes = request.form.get('notes', '').strip()
    event_date_str = request.form.get('event_date')
    
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
        flash(f'Required field(s) missing: {", ".join(missing_fields)}', 'danger')
        return redirect(url_for('hr_roles.updater_dashboard'))
    
    if str(validator_id) == str(user['_id']):
        flash('You cannot submit requests for your own validation', 'danger')
        return redirect(url_for('hr_roles.updater_dashboard'))
    
    event_date, error = validate_event_date(event_date_str, allow_future=True) if event_date_str else (datetime.utcnow(), None)
    if error:
        flash(error, 'danger')
        return redirect(url_for('hr_roles.updater_dashboard'))
    
    employee = mongo.db.users.find_one({"employee_id": employee_id})
    category = mongo.db.hr_categories.find_one({"_id": ObjectId(category_id)})
    
    if not employee:
        flash('Employee not found', 'danger')
        return redirect(url_for('hr_roles.updater_dashboard'))
    
    if not category:
        flash('Category not found', 'danger')
        return redirect(url_for('hr_roles.updater_dashboard'))
    
    points_per_unit = category.get('points_per_unit', {})
    employee_grade = employee.get('grade', 'base')
    points = points_per_unit.get(employee_grade, points_per_unit.get('base', 0)) if isinstance(points_per_unit, dict) else points_per_unit
    
    request_data = {
        "user_id": ObjectId(employee["_id"]),
        "category_id": ObjectId(category["_id"]),
        "points": points,
        "submission_notes": notes,
        "updated_by": "HR",
        "status": "Pending",
        "request_date": datetime.utcnow(),
        "event_date": event_date,
        "assigned_validator_id": ObjectId(validator_id),
        "created_by_hr_id": ObjectId(user['_id'])
    }
    
    result = mongo.db.points_request.insert_one(request_data)
    
    from services.realtime_events import publish_request_raised
    request_data['_id'] = result.inserted_id
    validator = mongo.db.users.find_one({'_id': ObjectId(validator_id)})
    if validator:
        # Ensure category_department is set correctly for HR
        if not category.get('category_department'):
            category['category_department'] = 'hr'
        publish_request_raised(request_data, employee, validator, category)
    
    flash('Reward assigned successfully!', 'success')
    return redirect(url_for('hr_roles.updater_dashboard'))


@hr_bp.route('/updater/validate-bulk-upload', methods=['POST'])
def validate_bulk_upload():
    """Validate bulk CSV upload"""
    has_access, user = check_hr_updater_access()
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
        
        hr_categories = list(mongo.db.hr_categories.find({
            'category_department': {'$regex': '^hr', '$options': 'i'},
            'category_status': 'active'
        }, {'name': 1}))
        
        valid_categories_map = {}
        for cat in hr_categories:
            cat_name = cat.get('name', '')
            normalized_code = cat_name.lower().replace(' ', '_').replace('&', 'and')
            valid_categories_map[normalized_code] = cat_name
        
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
                
                if not any([employee_id, validator_employee_id, event_date_str, category_code, department, notes]):
                    continue
                
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
                    raise ValueError(f"Required field(s) missing: {', '.join(missing_fields)}")
                
                row_validator = mongo.db.users.find_one({"employee_id": validator_employee_id})
                if not row_validator:
                    raise ValueError(f"Validator '{validator_employee_id}' not found")
                
                validator_dashboard_access = row_validator.get('dashboard_access', [])
                if 'hr_va' not in validator_dashboard_access:
                    raise ValueError(f"User '{validator_employee_id}' does not have HR Validator access")
                
                if str(row_validator['_id']) == str(user['_id']):
                    raise ValueError("Cannot submit requests for your own validation")
                
                try:
                    event_date = datetime.strptime(event_date_str, '%d-%m-%Y')
                except ValueError:
                    raise ValueError(f"Invalid date format '{event_date_str}'. Use DD-MM-YYYY")
                
                normalized_category_code = category_code.lower().replace(' ', '_').replace('&', 'and')
                
                if normalized_category_code not in valid_categories_map:
                    raise ValueError(f"Invalid category_code '{category_code}'")
                
                actual_category_name = valid_categories_map.get(normalized_category_code)
                
                employee_query = {"employee_id": employee_id}
                employee_query.update(SELECTABLE_EMPLOYEE_FILTER)
                employee = mongo.db.users.find_one(employee_query)
                if not employee:
                    raise ValueError(f"Employee '{employee_id}' not found")
                
                category = mongo.db.hr_categories.find_one({
                    "name": actual_category_name,
                    "category_department": {"$regex": "^hr", "$options": "i"},
                    "category_status": "active"
                })
                
                if not category:
                    raise ValueError(f"Category '{actual_category_name}' not found")
                
                employee_grade = employee.get('grade')
                if not employee_grade:
                    raise ValueError(f"Employee '{employee_id}' has no grade assigned")
                
                points_per_unit_config = category.get('points_per_unit', 0)
                if isinstance(points_per_unit_config, dict):
                    points_per_unit = points_per_unit_config.get(employee_grade, points_per_unit_config.get('base', 0))
                else:
                    points_per_unit = points_per_unit_config
                
                if points_per_unit <= 0:
                    raise ValueError(f"Category '{category_code}' has invalid points for grade '{employee_grade}'")
                
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
            return redirect(url_for('hr_roles.updater_dashboard'))
        
        validated_rows = json.loads(validated_data_json)
        
        if not validated_rows:
            flash('No valid rows to process', 'warning')
            return redirect(url_for('hr_roles.updater_dashboard'))
        
        success_count = 0
        
        for row in validated_rows:
            try:
                event_date = datetime.fromisoformat(row['event_date_obj'])
                category = mongo.db.hr_categories.find_one({"_id": ObjectId(row['category_id'])})
                validator = mongo.db.users.find_one({"_id": ObjectId(row['validator_object_id'])})
                
                if not category or not validator:
                    continue
                
                request_data = {
                    "user_id": ObjectId(row['employee_object_id']),
                    "category_id": ObjectId(row['category_id']),
                    "points": row['points'],
                    "submission_notes": row['notes'],
                    "updated_by": "HR",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date,
                    "assigned_validator_id": ObjectId(row['validator_object_id']),
                    "created_by_hr_id": ObjectId(user['_id'])
                }
                
                result = mongo.db.points_request.insert_one(request_data)
                request_data['_id'] = result.inserted_id
                
                from services.realtime_events import publish_request_raised
                employee = mongo.db.users.find_one({'_id': ObjectId(row['employee_object_id'])})
                if employee and validator:
                    # Ensure category_department is set correctly for HR
                    if not category.get('category_department'):
                        category['category_department'] = 'hr'
                    publish_request_raised(request_data, employee, validator, category)
                
                success_count += 1
            except Exception as e:
                error_print(f"Error processing row {row.get('row_number')}", e)
                continue
        
        if success_count > 0:
            flash(f'Successfully submitted {success_count} reward request(s)', 'success')
        
        return redirect(url_for('hr_roles.updater_dashboard'))
    
    except Exception as e:
        error_print("Error processing bulk upload", e)
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('hr_roles.updater_dashboard'))


@hr_bp.route('/updater/download-bulk-template')
def download_bulk_template():
    """Download CSV template for bulk upload"""
    has_access, user = check_hr_updater_access()
    if not has_access:
        flash('Access denied', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        mongo = get_mongo()
        current_date = datetime.now().strftime('%d-%m-%Y')
        
        hr_categories = list(mongo.db.hr_categories.find({
            'category_department': {'$regex': '^hr', '$options': 'i'},
            'category_status': 'active'
        }, {'name': 1}).sort('name', 1))
        
        csv_content = "employee_id,validator_employee_id,event_date,category_code,department,notes\n"
        
        if hr_categories:
            for idx, cat in enumerate(hr_categories, start=1):
                cat_code = cat.get('name', '').lower().replace(' ', '_').replace('&', 'and')
                cat_name = cat.get('name', 'Category')
                csv_content += f"EMP{idx:03d},VAL001,{current_date},{cat_code},Engineering,Sample notes for {cat_name}\n"
        else:
            csv_content += f"EMP001,VAL001,{current_date},category_code,Engineering,Sample notes\n"
        
        filename = "hr_bulk_upload_template.csv"
        
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response
    except Exception as e:
        error_print("Error generating bulk template", e)
        flash('Error generating template', 'danger')
        return redirect(url_for('hr_roles.updater_dashboard'))
