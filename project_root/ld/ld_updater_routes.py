from flask import render_template, request, session, redirect, url_for, flash, jsonify
from datetime import datetime, timedelta
from bson import ObjectId
import csv
import io
import json

from .ld_main import ld_bp
from .ld_helpers import (
    check_ld_updater_access, get_user_redirect, get_mongo,
    get_financial_quarter_and_month, parse_date_flexibly,
    validate_event_date, SELECTABLE_EMPLOYEE_FILTER_FOR_LD,
    emit_pending_request_update, get_financial_quarter_dates,
    get_ld_categories, get_ld_updater_categories, get_ld_validators, get_month_year_options,
    get_category_by_id, emit_updater_own_request_created, get_quarter_label_from_date
)
from utils.error_handling import error_print


@ld_bp.route('/updater/dashboard', methods=['GET', 'POST'])
def updater_dashboard():
    """L&D Updater Dashboard"""
    tab = request.args.get('tab', 'single_request')

    has_access, user = check_ld_updater_access()

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

            if action_type == 'assign_points':
                return handle_single_assignment(user)
            elif action_type == 'bulk_upload_confirmed':
                return handle_bulk_upload_confirmed(user)

        # GET request - render dashboard
        # ✅ L&D Updaters can assign points to ALL employees (no department restriction)
        employees_query = SELECTABLE_EMPLOYEE_FILTER_FOR_LD.copy()

        employees = list(mongo.db.users.find(employees_query).sort("name", 1))

        # Get L&D categories - Only Direct Award type for updaters
        ld_categories = get_ld_updater_categories()

        # Get L&D validators (exclude self if user has both updater and validator access)
        ld_validators = get_ld_validators()
        ld_validators = [v for v in ld_validators if str(v['_id']) != str(user['_id'])]

        if not ld_validators:
            flash('No other validators found. You cannot submit requests to yourself.', 'warning')

        # Get month/year options for backdating
        month_year_options = get_month_year_options()

        # Get today's date for max date validation
        today = datetime.utcnow().strftime('%Y-%m-%d')

        # Get departments data
        departments = {}
        for emp in employees:
            dept = emp.get('department', 'Unknown')
            if dept not in departments:
                departments[dept] = []
            departments[dept].append(emp)

        # Fetch assignment history
        history = []
        history_data = []
        seen_request_ids = set()

        if ld_categories:
            category_ids = [cat["_id"] for cat in ld_categories]

            # NEW records with category filter
            history_cursor = mongo.db.points_request.find({
                "category_id": {"$in": category_ids},
                "status": {"$in": ["Pending", "Approved", "Rejected"]},
                "created_by_ld_id": ObjectId(user['_id'])
            }).sort("request_date", -1)

            # OLD records without category filter (old categories may have been deleted)
            old_history_cursor = mongo.db.points_request.find({
                "status": {"$in": ["Pending", "Approved", "Rejected"]},
                "$or": [
                    {"created_by_ld_id": ObjectId(user['_id'])},  # Old updater field
                    {"pending_validator_id": ObjectId(user['_id'])}  # Very old validator field (for old LD users)
                ]
            }).sort("request_date", -1)

            # Combine both cursors
            combined_cursor = list(history_cursor) + list(old_history_cursor)

            for req_data in combined_cursor:
                request_id = str(req_data.get("_id", ""))

                # Skip if we've already seen this request
                if request_id in seen_request_ids:
                    continue

                seen_request_ids.add(request_id)

                employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
                # Support both old and new validator field names
                validator_id = req_data.get("assigned_validator_id") or req_data.get("pending_validator_id")
                validator = mongo.db.users.find_one({"_id": validator_id}) if validator_id else None
                category = get_category_by_id(req_data["category_id"])

                if employee and category:
                    history.append({
                        'request_date': req_data["request_date"],
                        'event_date': req_data.get("event_date", req_data["request_date"]),
                        'employee_name': employee.get("name", "Unknown"),
                        'employee_id': employee.get("employee_id", "N/A"),
                        'category_name': category.get("name", "Unknown"),
                        'quantity': req_data.get("quantity", 1),
                        'points': req_data.get("points", 0),
                        'validator_name': validator.get("name", "Unknown") if validator else "Unknown",
                        'status': req_data.get("status", "Unknown"),
                        'response_notes': req_data.get("response_notes", "")
                    })

                    # Calculate quarter from event_date (Financial Year: Apr-Mar)
                    event_date = req_data.get("event_date", req_data.get("request_date"))
                    quarter = get_quarter_label_from_date(event_date)

                    # Support both old (request_notes) and new (submission_notes) field names
                    submission_notes = req_data.get("submission_notes") or req_data.get("request_notes", "")

                    # Determine the most recent activity date for sorting
                    activity_date = req_data.get("response_date") if req_data.get("status") in ["Approved", "Rejected"] else req_data["request_date"]

                    history_data.append({
                        'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                        'event_date': event_date.strftime('%d-%m-%Y'),
                        'employee_name': employee.get("name", "Unknown"),
                        'employee_id': employee.get("employee_id", "N/A"),
                        'department': employee.get("department", "N/A"),
                        'grade': employee.get("grade", "Unknown"),
                        'quarter': quarter,
                        'category_name': category.get("name", "Unknown"),
                        'quantity': req_data.get("quantity", 1),
                        'points': req_data.get("points", 0),
                        'notes': submission_notes,
                        'response_notes': req_data.get("response_notes", ""),
                        'status': req_data.get("status", "Unknown"),
                        '_activity_date': activity_date  # Hidden field for sorting
                    })

        # Sort history_data by most recent activity (newest first)
        history_data.sort(key=lambda x: x['_activity_date'], reverse=True)

        # Get unique years and quarters for filters with crash protection
        year_options = []
        if history:
            try:
                years = set()
                for h in history:
                    if h.get('request_date'):
                        try:
                            years.add(h['request_date'].strftime('%Y'))
                        except (AttributeError, ValueError):
                            continue
                year_options = sorted(list(years), reverse=True)
            except Exception:
                year_options = []
        
        quarter_options = ['Q1', 'Q2', 'Q3', 'Q4']

        # Get grades - handle deleted employees with crash protection
        grades_set = set()
        try:
            for req in mongo.db.points_request.find({"created_by_ld_id": ObjectId(user['_id'])}):
                emp = mongo.db.users.find_one({"_id": req["user_id"]})
                if emp and emp.get("grade"):
                    grades_set.add(emp.get("grade"))
        except Exception:
            pass
        grades = sorted(list(grades_set)) if grades_set else []

        return render_template(
            'ld_updater_dashboard.html',
            user=user,
            employees=employees,
            departments=departments,
            ld_categories=ld_categories,
            ld_validators=ld_validators,
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

    except Exception:
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))


def handle_single_assignment(user):
    """Handle single points assignment"""
    mongo = get_mongo()

    employee_id = request.form.get('employee_id')
    category_id = request.form.get('category_id')
    validator_id = request.form.get('validator_id')
    notes = request.form.get('notes', '')
    event_date_str = request.form.get('event_date')
    award_month_year = request.form.get('award_month_year')  # For backdating

    try:
        quantity = int(request.form.get('quantity', 1))
    except (ValueError, TypeError):
        flash('Quantity must be a valid number.', 'danger')
        return redirect(url_for('ld.updater_dashboard'))

    # Validate inputs
    if not employee_id or not category_id or not validator_id or not notes or quantity <= 0:
        flash('All fields are required and quantity must be greater than 0.', 'danger')
        return redirect(url_for('ld.updater_dashboard'))

    # Check if validator is not the same as current user
    if str(validator_id) == str(user['_id']):
        flash('You cannot assign yourself as a validator. Please select another validator.', 'danger')
        return redirect(url_for('ld.updater_dashboard'))

    # Validate event_date or use award_month_year for backdating
    event_date = None

    if award_month_year:
        # Parse award_month_year (format: "YYYY-MM" e.g., "2025-02")
        try:
            year, month = award_month_year.split('-')
            # Set to first day of the selected month
            event_date = datetime(int(year), int(month), 1)
        except (ValueError, AttributeError) as e:
            flash('Invalid award month format.', 'danger')
            return redirect(url_for('ld.updater_dashboard'))
    elif event_date_str:
        event_date, error = validate_event_date(event_date_str, allow_future=True)
        if error:
            flash(error, 'danger')
            return redirect(url_for('ld.updater_dashboard'))
    else:
        event_date = datetime.utcnow()

    # Get employee
    employee = mongo.db.users.find_one({"employee_id": employee_id})
    if not employee:
        flash('Employee not found. Please enter a valid Employee ID.', 'danger')
        return redirect(url_for('ld.updater_dashboard'))

    # Get category
    category = get_category_by_id(ObjectId(category_id))
    if not category:
        flash('Category not found in database.', 'danger')
        return redirect(url_for('ld.updater_dashboard'))

    # Get validator
    validator = mongo.db.users.find_one({"_id": ObjectId(validator_id)})
    if not validator:
        flash('Validator not found.', 'danger')
        return redirect(url_for('ld.updater_dashboard'))

    # Calculate points
    points_per_unit = category.get('points_per_unit', {})
    if isinstance(points_per_unit, dict):
        employee_grade = employee.get('grade', 'base')
        points = points_per_unit.get(employee_grade, points_per_unit.get('base', 0))
    else:
        points = points_per_unit

    total_points = points * quantity

    if total_points <= 0:
        flash('Category has invalid points configuration.', 'danger')
        return redirect(url_for('ld.updater_dashboard'))

    # Create request
    request_data = {
        "user_id": ObjectId(employee["_id"]),
        "category_id": ObjectId(category["_id"]),
        "points": total_points,
        "quantity": quantity,
        "submission_notes": notes,
        "updated_by": "LD",
        "status": "Pending",
        "request_date": datetime.utcnow(),
        "event_date": event_date,
        "assigned_validator_id": ObjectId(validator_id),
        "created_by_ld_id": ObjectId(user['_id'])
    }

    # Add award_month_year if backdating was used
    if award_month_year:
        request_data["award_month_year"] = award_month_year


    result = mongo.db.points_request.insert_one(request_data)
    request_data['_id'] = result.inserted_id

    from services.realtime_events import publish_request_raised
    
    # Ensure category_department is set correctly for L&D
    if 'category_department' in category:
        category['category_department'] = category['category_department'].lower()
    else:
        category['category_department'] = 'ld_up'
    
    # Ensure created_by_ld_id is set for proper routing
    request_data['created_by_ld_id'] = ObjectId(user['_id'])
    
    publish_request_raised(request_data, employee, validator, category)

    # Send email notification to validator
    from flask import current_app
    from ld.ld_email_service import send_single_request_to_validator
    send_single_request_to_validator(current_app._get_current_object(), mongo, request_data, employee, validator, category, user)

    # Success message
    flash(f'Successfully submitted request for {employee.get("name", employee_id)} - {category.get("name")} ({total_points} points) to {validator.get("name", "validator")} for validation.', 'success')

    try:
        emit_pending_request_update()
    except:
        pass

    # ✅ Emit event to updater to refresh their own Recent Activity
    try:
        emit_updater_own_request_created(user['_id'])
    except:
        pass

    return redirect(url_for('ld.updater_dashboard', tab='single-request'))


@ld_bp.route('/updater/validate-bulk-upload', methods=['POST'])
def validate_bulk_upload():
    """Validate bulk CSV upload and return valid/invalid rows"""
    has_access, user = check_ld_updater_access()

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

        # Validate headers - normalize by stripping whitespace and converting to lowercase
        expected_headers = ['employee_id', 'validator_employee_id', 'category_name', 'event_date', 'quantity', 'notes']
        
        if not csv_reader.fieldnames:
            return jsonify({
                'success': False,
                'error': 'CSV file is empty or has no headers'
            })
        
        # Create mapping from normalized headers to original headers
        header_mapping = {}
        actual_headers_normalized = []
        for original_header in csv_reader.fieldnames:
            normalized = original_header.strip().lower() if original_header else ''
            actual_headers_normalized.append(normalized)
            header_mapping[normalized] = original_header
        
        expected_headers_lower = [h.lower() for h in expected_headers]
        
        # Check if all expected headers are present (order doesn't matter)
        missing_headers = set(expected_headers_lower) - set(actual_headers_normalized)
        if missing_headers:
            return jsonify({
                'success': False,
                'error': f"Invalid CSV headers. Missing: {', '.join(missing_headers)}. Expected: {', '.join(expected_headers)}"
            })

        # Get all L&D categories for lookup - Only Direct Award type for updaters
        ld_categories = get_ld_updater_categories()
        category_map = {cat['name'].lower(): cat for cat in ld_categories}

        valid_rows = []
        invalid_rows = []

        for row_num, row in enumerate(csv_reader, start=2):
            error = None
            employee_id = ''
            validator_employee_id = ''
            category_name = ''

            try:
                # Get values using original header names from the mapping
                employee_id = row.get(header_mapping.get('employee_id', 'employee_id'), '').strip()
                validator_employee_id = row.get(header_mapping.get('validator_employee_id', 'validator_employee_id'), '').strip()
                category_name = row.get(header_mapping.get('category_name', 'category_name'), '').strip()
                event_date_str = row.get(header_mapping.get('event_date', 'event_date'), '').strip()
                quantity_str = row.get(header_mapping.get('quantity', 'quantity'), '').strip()
                notes = row.get(header_mapping.get('notes', 'notes'), '').strip()

                # ✅ Skip completely empty rows (when user deletes with backspace)
                if not any([employee_id, validator_employee_id, category_name, event_date_str, quantity_str, notes]):
                    continue  # Skip this row entirely

                # Validate required fields - show only missing ones
                missing_fields = []
                if not employee_id:
                    missing_fields.append('employee_id')
                if not validator_employee_id:
                    missing_fields.append('validator_employee_id')
                if not category_name:
                    missing_fields.append('category_name')
                if not quantity_str:
                    missing_fields.append('quantity')
                if not notes:
                    missing_fields.append('notes')

                if missing_fields:
                    error = f"Missing required fields: {', '.join(missing_fields)}"
                    raise ValueError(error)

                # Get category by name
                category = category_map.get(category_name.lower())
                if not category:
                    error = f"Category '{category_name}' not found. Available categories: {', '.join([c['name'] for c in ld_categories])}"
                    raise ValueError(error)

                points_per_unit = category.get('points_per_unit', {})

                # Validate quantity
                try:
                    quantity = int(quantity_str)
                    if quantity <= 0:
                        raise ValueError("Quantity must be positive")
                except ValueError:
                    error = f"Invalid quantity '{quantity_str}'"
                    raise ValueError(error)

                # Get validator by employee_id
                validator = mongo.db.users.find_one({"employee_id": validator_employee_id})
                if not validator:
                    error = f"Validator with employee ID '{validator_employee_id}' not found"
                    raise ValueError(error)

                # Check if validator has L&D validator access
                validator_dashboard_access = validator.get('dashboard_access', [])
                if 'ld_va' not in validator_dashboard_access:
                    error = f"User '{validator_employee_id}' does not have L&D Validator access"
                    raise ValueError(error)

                # Check if validator is not the same as current user
                if str(validator['_id']) == str(user['_id']):
                    error = "You cannot assign yourself as validator"
                    raise ValueError(error)

                # Parse event date from CSV
                if event_date_str:
                    event_date = parse_date_flexibly(event_date_str)
                    if not event_date:
                        error = f"Invalid event date '{event_date_str}'"
                        raise ValueError(error)
                else:
                    error = "Event date is required"
                    raise ValueError(error)

                # Get employee
                employee = mongo.db.users.find_one({"employee_id": employee_id})
                if not employee:
                    error = f"Employee ID '{employee_id}' not found"
                    raise ValueError(error)

                # Calculate points
                employee_grade = employee.get('grade', 'N/A')
                if isinstance(points_per_unit, dict):
                    points = points_per_unit.get(employee_grade, points_per_unit.get('base', 0))
                else:
                    points = points_per_unit

                # Check if category is eligible for this grade (points should not be 0)
                if points == 0:
                    error = f"Category '{category_name}' is not eligible for grade {employee_grade}. This category awards 0 points for this grade."
                    raise ValueError(error)

                total_points = points * quantity

                # Add to valid rows
                valid_rows.append({
                    'row_number': row_num,
                    'employee_id': employee_id,
                    'employee_name': employee.get('name', 'Unknown'),
                    'employee_object_id': str(employee['_id']),
                    'validator_employee_id': validator_employee_id,
                    'validator_name': validator.get('name', 'Unknown'),
                    'validator_object_id': str(validator['_id']),
                    'category_id': str(category['_id']),
                    'category_name': category.get('name', 'Unknown'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'event_date_obj': event_date.isoformat(),
                    'quantity': quantity,
                    'points': total_points,
                    'notes': notes
                })

            except Exception as e:
                invalid_rows.append({
                    'row_number': row_num,
                    'employee_id': employee_id,
                    'validator_employee_id': validator_employee_id,
                    'category_name': category_name,
                    'error': error or str(e)
                })

        # Prepare response
        response = {
            'success': True,
            'valid_rows': valid_rows,
            'invalid_rows': invalid_rows
        }

        # Add category info if we have valid rows
        if valid_rows:
            # Get category from first valid row
            first_valid = valid_rows[0]
            response['category_name'] = first_valid.get('category_name', 'Unknown')
            response['category_id'] = first_valid.get('category_id', '')

        return jsonify(response)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def handle_bulk_upload_confirmed(user):
    """Handle confirmed bulk upload with pre-validated data"""
    mongo = get_mongo()

    try:
        # Get validated data from form
        validated_data_json = request.form.get('validated_data')
        if not validated_data_json:
            flash('No validated data received', 'danger')
            return redirect(url_for('ld.updater_dashboard', tab='bulk-upload'))

        validated_rows = json.loads(validated_data_json)

        if not validated_rows:
            flash('No valid rows to process', 'warning')
            return redirect(url_for('ld.updater_dashboard', tab='bulk-upload'))

        success_count = 0
        error_count = 0
        realtime_success_count = 0
        bulk_requests_by_validator = {}  # Group by validator for email and socket notification

        for row in validated_rows:
            try:
                # Parse event date from ISO format
                event_date = datetime.fromisoformat(row['event_date_obj'])

                # Get category for this row
                category = get_category_by_id(ObjectId(row['category_id']))
                if not category:
                    error_count += 1
                    continue

                request_data = {
                    "user_id": ObjectId(row['employee_object_id']),
                    "category_id": ObjectId(row['category_id']),
                    "points": row['points'],
                    "quantity": row['quantity'],
                    "submission_notes": row['notes'],
                    "updated_by": "LD",
                    "status": "Pending",
                    "request_date": datetime.utcnow(),
                    "event_date": event_date,
                    "assigned_validator_id": ObjectId(row['validator_object_id']),
                    "created_by_ld_id": ObjectId(user['_id'])
                }

                result = mongo.db.points_request.insert_one(request_data)
                request_data['_id'] = result.inserted_id

                employee = mongo.db.users.find_one({'_id': ObjectId(row['employee_object_id'])})
                validator = mongo.db.users.find_one({'_id': ObjectId(row['validator_object_id'])})

                if employee and validator:
                    # ✅ Send individual real-time notification for each request
                    from services.realtime_events import publish_request_raised
                    
                    # Ensure category_department is set correctly for L&D
                    if 'category_department' in category:
                        category['category_department'] = category['category_department'].lower()
                    else:
                        category['category_department'] = 'ld_up'
                    
                    # Ensure created_by_ld_id is set for proper routing
                    request_data['created_by_ld_id'] = ObjectId(user['_id'])
                    
                    # Publish real-time event
                    try:
                        rt_result = publish_request_raised(request_data, employee, validator, category)
                        if rt_result:
                            realtime_success_count += 1
                    except Exception:
                        # Don't fail the bulk upload if real-time fails
                        pass

                    # Group requests by validator for bulk email
                    validator_id_str = str(validator['_id'])
                    if validator_id_str not in bulk_requests_by_validator:
                        bulk_requests_by_validator[validator_id_str] = {
                            'validator': validator,
                            'requests': [],
                            'total_points': 0
                        }
                    bulk_requests_by_validator[validator_id_str]['requests'].append({
                        'employee_name': employee.get('name'),
                        'employee_id': employee.get('employee_id'),
                        'category_name': category.get('name'),
                        'quantity': row['quantity'],
                        'points': row['points']
                    })
                    bulk_requests_by_validator[validator_id_str]['total_points'] += row['points']

                success_count += 1

            except Exception:
                error_count += 1
                continue

        # Send bulk upload emails to validators (one email per validator)
        from flask import current_app
        from ld.ld_email_service import send_bulk_upload_to_validator
        for validator_data in bulk_requests_by_validator.values():
            send_bulk_upload_to_validator(
                current_app._get_current_object(),
                mongo,
                validator_data['requests'],
                validator_data['validator'],
                user
            )

        if success_count > 0:
            flash(f'Successfully submitted {success_count} requests for validation.', 'success')
        if error_count > 0:
            flash(f'{error_count} row(s) failed to process.', 'warning')

        # ✅ Emit event to updater to refresh their own Recent Activity
        try:
            emit_updater_own_request_created(user['_id'])
        except:
            pass

        return redirect(url_for('ld.updater_dashboard', tab='bulk-upload'))

    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('ld.updater_dashboard', tab='bulk-upload'))


@ld_bp.route('/updater/get-employees', methods=['GET'])
def get_employees():
    """Get all eligible employees for L&D points assignment"""
    has_access, user = check_ld_updater_access()

    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    try:
        mongo = get_mongo()

        # Build query for employees - NO department restriction
        # Updaters can raise requests for employees from any department
        query = SELECTABLE_EMPLOYEE_FILTER_FOR_LD.copy()

        # Fetch ALL eligible employees regardless of department
        employees = list(mongo.db.users.find(
            query,
            {
                '_id': 1,
                'name': 1,
                'employee_id': 1,
                'grade': 1,
                'department': 1,
                'email': 1
            }
        ).sort("name", 1))

        # Get ALL unique grades and departments from entire users collection
        all_grades = mongo.db.users.distinct('grade', {'grade': {'$exists': True, '$ne': None, '$ne': ''}})
        all_departments = mongo.db.users.distinct('department', {'department': {'$exists': True, '$ne': None, '$ne': ''}})

        # Format response
        result = []
        for emp in employees:
            grade = emp.get('grade', 'N/A')
            result.append({
                'id': str(emp['_id']),
                'employee_id': emp.get('employee_id', ''),
                'name': emp.get('name', 'Unknown'),
                'grade': grade,
                'department': emp.get('department', 'N/A'),
                'email': emp.get('email', ''),
                'display': f"{emp.get('name', 'Unknown')} ({emp.get('employee_id', 'N/A')}) - {grade}"
            })

        return jsonify({
            'success': True,
            'employees': result,
            'count': len(result),
            'all_grades': sorted([g for g in all_grades if g]),
            'all_departments': sorted([d for d in all_departments if d])
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ld_bp.route('/updater/search-employee', methods=['GET'])
def search_employee():
    """Search employees by name or employee ID"""
    has_access, user = check_ld_updater_access()

    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    try:
        mongo = get_mongo()
        search_term = request.args.get('q', '').strip()

        if not search_term or len(search_term) < 2:
            return jsonify({'success': True, 'employees': []})

        # ✅ L&D Updaters can search ALL employees (no department restriction)
        query = SELECTABLE_EMPLOYEE_FILTER_FOR_LD.copy()

        # Add search criteria
        query["$or"] = [
            {"name": {"$regex": search_term, "$options": "i"}},
            {"employee_id": {"$regex": search_term, "$options": "i"}},
            {"email": {"$regex": search_term, "$options": "i"}}
        ]

        # Fetch matching employees (limit to 20 results)
        employees = list(mongo.db.users.find(
            query,
            {
                '_id': 1,
                'name': 1,
                'employee_id': 1,
                'grade': 1,
                'department': 1
            }
        ).sort("name", 1).limit(20))

        # Format response
        result = []
        for emp in employees:
            result.append({
                'id': str(emp['_id']),
                'employee_id': emp.get('employee_id', ''),
                'name': emp.get('name', 'Unknown'),
                'grade': emp.get('grade', 'N/A'),
                'department': emp.get('department', 'N/A'),
                'display': f"{emp.get('name', 'Unknown')} ({emp.get('employee_id', 'N/A')}) - {emp.get('department', 'N/A')}"
            })

        return jsonify({'success': True, 'employees': result})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ld_bp.route('/updater/get-employee-details', methods=['POST'])
def get_employee_details():
    """Get employee details"""
    has_access, user = check_ld_updater_access()

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
        return jsonify({'success': False, 'error': str(e)}), 500


@ld_bp.route('/updater/get-history', methods=['GET'])
def get_updater_history():
    """Get assignment history for updater - Real-time compatible"""
    has_access, user = check_ld_updater_access()

    if not has_access:
        return jsonify({'success': False, 'error': 'Not authorized'}), 403

    try:
        mongo = get_mongo()

        ld_categories = get_ld_categories()
        if not ld_categories:
            return jsonify({'success': True, 'entries': []})

        category_ids = [cat["_id"] for cat in ld_categories]

        history_query = {
            "created_by_ld_id": ObjectId(user['_id']),
            "category_id": {"$in": category_ids},
            "status": {"$in": ["Approved", "Rejected", "Pending"]}
        }

        history_cursor = mongo.db.points_request.find(history_query).sort("request_date", -1).limit(100)

        history_data = []
        for req_data in history_cursor:
            employee = mongo.db.users.find_one({"_id": req_data["user_id"]})
            category = mongo.db.hr_categories.find_one({"_id": req_data["category_id"]})
            validator = mongo.db.users.find_one({"_id": req_data.get("assigned_validator_id")})

            if employee and category:
                # Calculate quarter from event_date (Financial Year: Apr-Mar)
                event_date = req_data.get("event_date", req_data.get("request_date"))
                quarter = get_quarter_label_from_date(event_date)

                history_data.append({
                    'request_id': str(req_data["_id"]),
                    'request_date': req_data["request_date"].strftime('%d-%m-%Y'),
                    'response_date': req_data.get("response_date", req_data["request_date"]).strftime('%d-%m-%Y'),
                    'event_date': event_date.strftime('%d-%m-%Y'),
                    'employee_name': employee.get("name", "Unknown"),
                    'employee_id': employee.get("employee_id", "N/A"),
                    'department': employee.get("department", "N/A"),
                    'grade': employee.get("grade", "Unknown"),
                    'quarter': quarter,
                    'category_name': category.get("name", "Unknown"),
                    'quantity': req_data.get("quantity", 1),
                    'points': req_data.get("points", 0),
                    'notes': req_data.get("submission_notes", ""),
                    'response_notes': req_data.get("response_notes", ""),
                    'validator_name': validator.get("name", "Unknown") if validator else "Unknown",
                    'status': req_data.get("status", "Unknown")
                })

        return jsonify({'success': True, 'entries': history_data})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
