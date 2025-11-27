from flask import Blueprint, render_template, request, redirect, session, url_for, flash, send_file, jsonify
from extensions import mongo, bcrypt
from datetime import datetime
from bson.objectid import ObjectId
import csv
import io
import os
from .hr_utils import check_hr_access  # Changed to relative import
from .hr_analytics import get_financial_quarter_and_label

# Get the current directory path
current_dir = os.path.dirname(os.path.abspath(__file__))

# Define Blueprint for HR Registration
hr_registration_bp = Blueprint('hr_registration', __name__, url_prefix='/hr',
                               template_folder=os.path.join(current_dir, 'templates'),
                               static_folder=os.path.join(current_dir, 'static'),
                               static_url_path='/hr/static')


# HR Dashboard - Registration Forms
@hr_registration_bp.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access the HR dashboard', 'danger')
        return redirect(url_for('auth.login'))

    # Fetch dynamic data from database
    # Fetch users who have 'pm' in their dashboard_access
    managers = list(mongo.db.users.find({
        'dashboard_access': 'pm'
    }))
    # Fetch users who have 'dp' in their dashboard_access
    dps = list(mongo.db.users.find({
        'dashboard_access': 'dp'
    }))
    
    # Fetch dynamic configurations
    config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
    if not config_data:
        # Create default configuration if doesn't exist
        config_data = {
            'config_type': 'registration',
            'grades': ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2'],
            'departments': ['Management', 'IT', 'Admin', 'Marketing', 'Sales', 'HR', 'Finance'],
            'locations': ['US', 'Non-US', 'India', 'UK', 'Canada', 'Australia'],
            'employee_levels': ['Junior', 'Mid-Level', 'Senior', 'Lead', 'Principal'],
            'dashboard_access': ['employee_db', 'analytics_db', 'reports_db', 'pmo_db', 'finance_db']
        }
        mongo.db.hr_config.insert_one(config_data)
    
    grades = config_data.get('grades', [])
    departments = config_data.get('departments', [])
    locations = config_data.get('locations', [])
    employee_levels = config_data.get('employee_levels', [])
    dashboard_access_options = config_data.get('dashboard_access', [])
    
    # Define manager levels/roles for dropdown
    manager_levels = ['PMO', 'PM/Arch', 'PM', 'Marketing', 'TA', 'L & D', 'CoE/DH', 'Pre-sales']

    # Register Employee (Single Registration)
    if 'register_single' in request.form:
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        emp_id = request.form['employee_id']
        password = request.form['password']
        grade = request.form['grade']
        department = request.form['department']
        location = request.form['location']
        employee_level = request.form['employee_level']
        manager_id = request.form.get('manager_id')
        dp_id = request.form.get('dp_id')
        is_active = request.form.get('is_active') == 'on'
        dashboard_access = request.form.getlist('dashboard_access[]')
        # Convert to lowercase to match TA format (ta_up, ta_va, pmo_up, pmo_va)
        dashboard_access = [x.lower() for x in dashboard_access]
        joining_date = request.form['joining_date']
        exit_date = request.form.get('exit_date') or None
        
        # Ensure employee_db is always included
        if 'employee_db' not in dashboard_access:
            dashboard_access.append('employee_db')
        
        # Validate required fields
        if not all([name, email, phone, emp_id, password, grade, department, location, employee_level, joining_date]):
            flash("All required fields must be filled", 'danger')
            return redirect(url_for('hr_registration.dashboard'))

        # Check if email or employee ID already exists
        if mongo.db.users.find_one({'email': email}):
            flash('Email already exists', 'danger')
            return redirect(url_for('hr_registration.dashboard'))

        if mongo.db.users.find_one({'employee_id': emp_id}):
            flash('Employee ID already exists', 'danger')
            return redirect(url_for('hr_registration.dashboard'))

        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        
        # Convert manager_id to ObjectId if it's not empty and validate
        if manager_id:
            try:
                if manager_id.strip():
                    manager_obj_id = ObjectId(manager_id)
                    # Validate manager exists and has pm dashboard access
                    manager_check = mongo.db.users.find_one({
                        '_id': manager_obj_id,
                        'dashboard_access': 'pm'
                    })
                    if not manager_check:
                        flash('Invalid Manager ID or Manager does not have PM dashboard access', 'danger')
                        return redirect(url_for('hr_registration.dashboard'))
                    manager_id = manager_obj_id
                else:
                    manager_id = None
            except Exception as e:
                flash(f'Invalid manager ID: {str(e)}', 'danger')
                return redirect(url_for('hr_registration.dashboard'))
        else:
            manager_id = None
        
        # Convert dp_id to ObjectId if it's not empty and validate
        if dp_id:
            try:
                if dp_id.strip():
                    dp_obj_id = ObjectId(dp_id)
                    # Validate DP exists and has dp dashboard access
                    dp_check = mongo.db.users.find_one({
                        '_id': dp_obj_id,
                        'dashboard_access': 'dp'
                    })
                    if not dp_check:
                        flash('Invalid DP ID or DP does not have DP dashboard access', 'danger')
                        return redirect(url_for('hr_registration.dashboard'))
                    dp_id = dp_obj_id
                else:
                    dp_id = None
            except Exception as e:
                flash(f'Invalid DP ID: {str(e)}', 'danger')
                return redirect(url_for('hr_registration.dashboard'))
        else:
            dp_id = None
        
        # Convert dates to datetime objects
        if joining_date:
            joining_date = datetime.strptime(joining_date, '%Y-%m-%d')
        if exit_date:
            exit_date = datetime.strptime(exit_date, '%Y-%m-%d')
        
        user = {
            'name': name,
            'email': email,
            'phone': phone,
            'employee_id': emp_id,
            'password_hash': hashed,
            'role': 'Employee',
            'is_first_login': True,
            'grade': grade,
            'department': department,
            'location': location,
            'employee_level': employee_level,
            'manager_id': manager_id,
            'dp_id': dp_id,
            'is_active': is_active,
            'dashboard_access': dashboard_access,
            'joining_date': joining_date,
            'exit_date': exit_date,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        mongo.db.users.insert_one(user)
        flash('Employee registered successfully!', 'success')
        return redirect(url_for('hr_registration.dashboard'))

    # Bulk Registration via CSV
    if 'register_bulk' in request.form:
        file = request.files.get('csv_file')
        if not file or not file.filename.endswith('.csv'):
            flash('Please upload a valid CSV file.', 'danger')
            return redirect(url_for('hr_registration.dashboard'))

        try:
            file.stream.seek(0)
            csv_reader = csv.DictReader(file.read().decode('utf-8').splitlines())

            added, skipped = 0, 0
            row_num = 1
            error_messages = []

            for row in csv_reader:
                row_num += 1
                try:
                    email = row['email']
                    emp_id = row['employee_id']

                    if mongo.db.users.find_one({'$or': [{'email': email}, {'employee_id': emp_id}]}):
                        skipped += 1
                        error_messages.append(f"Row {row_num}: Skipped (duplicate email or employee ID)")
                        continue

                    # Find manager by name or email (must have 'pm' in dashboard_access)
                    manager_id = None
                    manager_name = row.get('manager_name', '').strip()
                    
                    if manager_name:
                        manager = mongo.db.users.find_one({
                            '$or': [
                                {'name': manager_name},
                                {'email': manager_name}
                            ],
                            'dashboard_access': 'pm'
                        })
                        if manager:
                            manager_id = manager['_id']
                        else:
                            error_messages.append(f"Row {row_num}: Warning - Manager '{manager_name}' not found with PM dashboard access")

                    # Find DP by name or email (must have 'dp' in dashboard_access)
                    dp_id = None
                    dp_name = row.get('dp_name', '').strip()
                    
                    if dp_name:
                        dp = mongo.db.users.find_one({
                            '$or': [
                                {'name': dp_name},
                                {'email': dp_name}
                            ],
                            'dashboard_access': 'dp'
                        })
                        if dp:
                            dp_id = dp['_id']
                        else:
                            error_messages.append(f"Row {row_num}: Warning - DP '{dp_name}' not found with DP dashboard access")

                    password_hash = bcrypt.generate_password_hash(row['password']).decode('utf-8')
                    
                    joining_date = None
                    if row.get('joining_date'):
                        try:
                            joining_date = datetime.strptime(row['joining_date'], '%Y-%m-%d')
                        except ValueError as e:
                            error_messages.append(f"Row {row_num}: Warning - Invalid joining date format ({str(e)})")
                    
                    exit_date = None
                    if row.get('exit_date'):
                        try:
                            exit_date = datetime.strptime(row['exit_date'], '%Y-%m-%d')
                        except ValueError as e:
                            error_messages.append(f"Row {row_num}: Warning - Invalid exit date format ({str(e)})")

                    # Parse dashboard access (comma-separated in CSV)
                    dashboard_access = []
                    if row.get('dashboard_access'):
                        dashboard_access = [x.strip() for x in row['dashboard_access'].split(',')]
                    
                    # Ensure employee_db is always included
                    if 'employee_db' not in dashboard_access:
                        dashboard_access.append('employee_db')
                    
                    # Parse is_active field
                    is_active_str = row.get('is_active', 'true').lower()
                    is_active = is_active_str in ['true', 'yes', '1', 'on', 'active']

                    new_emp = {
                        'name': row['name'],
                        'email': row['email'],
                        'phone': row.get('phone'),
                        'employee_id': emp_id,
                        'password_hash': password_hash,
                        'role': 'Employee',
                        'is_first_login': True,
                        'grade': row.get('grade'),
                        'department': row.get('department'),
                        'location': row.get('location'),
                        'employee_level': row.get('employee_level'),
                        'manager_id': manager_id,
                        'dp_id': dp_id,
                        'is_active': is_active,
                        'dashboard_access': dashboard_access,
                        'joining_date': joining_date,
                        'exit_date': exit_date,
                        'created_at': datetime.now(),
                        'updated_at': datetime.now()
                    }
                    
                    mongo.db.users.insert_one(new_emp)
                    added += 1

                except Exception as row_err:
                    skipped += 1
                    error_messages.append(f"Row {row_num}: Error - {str(row_err)}")
                    continue

            flash(f'{added} employees added, {skipped} skipped.', 'success')
            for msg in error_messages:
                flash(msg, 'warning')

        except Exception as e:
            flash(f'Critical error processing CSV: {str(e)}', 'danger')

        return redirect(url_for('hr_registration.dashboard'))

    # Get current quarter and month for header display
    now = datetime.utcnow()
    _, quarter_label, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
    display_quarter = f"{quarter_label} {fiscal_year_label}"
    display_month = now.strftime("%b %Y").upper()
    
    return render_template('dashboard.html', 
                          managers=managers,
                          dps=dps,
                          grades=grades, 
                          departments=departments,
                          locations=locations,
                          employee_levels=employee_levels,
                          dashboard_access_options=dashboard_access_options,
                          manager_levels=manager_levels,
                          display_quarter=display_quarter,
                          display_month=display_month)


# Register Manager
@hr_registration_bp.route('/register-manager', methods=['GET', 'POST'])
def register_manager():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))

    # Fetch users who have 'pm' in their dashboard_access
    managers = list(mongo.db.users.find({
        'dashboard_access': 'pm'
    }))
    # Fetch users who have 'dp' in their dashboard_access
    dps = list(mongo.db.users.find({
        'dashboard_access': 'dp'
    }))
    
    # Fetch dynamic configurations
    config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
    if not config_data:
        config_data = {
            'config_type': 'registration',
            'grades': ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2', 'E1', 'E2', 'EL1', 'EL2', 'EL3'],
            'departments': ['Management', 'IT', 'Admin', 'Marketing', 'Sales', 'HR', 'Finance'],
            'locations': ['US', 'Non-US', 'India', 'UK', 'Canada', 'Australia'],
            'employee_levels': ['Junior', 'Mid-Level', 'Senior', 'Lead', 'Principal', 'Manager'],
            'dashboard_access': ['employee_db', 'analytics_db', 'reports_db', 'pmo_db', 'finance_db', 'management_db']
        }
        mongo.db.hr_config.insert_one(config_data)
    
    grades = config_data.get('grades', [])
    departments = config_data.get('departments', [])
    locations = config_data.get('locations', [])
    employee_levels = config_data.get('employee_levels', [])
    dashboard_access_options = config_data.get('dashboard_access', [])
    
    manager_levels = ['PMO', 'PM/Arch', 'PM', 'Marketing', 'TA', 'L & D', 'Pre-sales']

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        emp_id = request.form['employee_id']
        password = request.form['password']
        grade = request.form.get('grade')
        department = request.form.get('department')
        location = request.form.get('location')
        employee_level = request.form.get('employee_level')
        manager_level = request.form.get('manager_level')
        manager_id = request.form.get('manager_id')
        dp_id = request.form.get('dp_id')
        is_active = request.form.get('is_active') == 'on'
        dashboard_access = request.form.getlist('dashboard_access[]')
        # Convert to lowercase to match TA format (ta_up, ta_va, pmo_up, pmo_va)
        dashboard_access = [x.lower() for x in dashboard_access]
        joining_date = request.form['joining_date']
        exit_date = request.form.get('exit_date') or None
        
        # Ensure employee_db is always included
        if 'employee_db' not in dashboard_access:
            dashboard_access.append('employee_db')

        if mongo.db.users.find_one({'email': email}):
            flash('Email already exists', 'danger')
            return redirect(url_for('hr_registration.register_manager'))

        if mongo.db.users.find_one({'employee_id': emp_id}):
            flash('Employee ID already exists', 'danger')
            return redirect(url_for('hr_registration.register_manager'))

        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        
        if manager_id:
            try:
                if manager_id.strip():
                    manager_obj_id = ObjectId(manager_id)
                    # Validate manager exists and has pm dashboard access
                    manager_check = mongo.db.users.find_one({
                        '_id': manager_obj_id,
                        'dashboard_access': 'pm'
                    })
                    if not manager_check:
                        flash('Invalid Manager ID or Manager does not have PM dashboard access', 'danger')
                        return redirect(url_for('hr_registration.register_manager'))
                    manager_id = manager_obj_id
                else:
                    manager_id = None
            except Exception as e:
                flash(f'Invalid manager ID: {str(e)}', 'danger')
                return redirect(url_for('hr_registration.register_manager'))
        else:
            manager_id = None
        
        if dp_id:
            try:
                if dp_id.strip():
                    dp_obj_id = ObjectId(dp_id)
                    # Validate DP exists and has dp dashboard access
                    dp_check = mongo.db.users.find_one({
                        '_id': dp_obj_id,
                        'dashboard_access': 'dp'
                    })
                    if not dp_check:
                        flash('Invalid DP ID or DP does not have DP dashboard access', 'danger')
                        return redirect(url_for('hr_registration.register_manager'))
                    dp_id = dp_obj_id
                else:
                    dp_id = None
            except Exception as e:
                flash(f'Invalid DP ID: {str(e)}', 'danger')
                return redirect(url_for('hr_registration.register_manager'))
        else:
            dp_id = None
        
        try:
            if joining_date:
                joining_date = datetime.strptime(joining_date, '%Y-%m-%d')
        except ValueError as e:
            flash(f'Invalid joining date format: {str(e)}', 'danger')
            return redirect(url_for('hr_registration.register_manager'))
            
        try:
            if exit_date:
                exit_date = datetime.strptime(exit_date, '%Y-%m-%d')
        except ValueError as e:
            flash(f'Invalid exit date format: {str(e)}', 'danger')
            return redirect(url_for('hr_registration.register_manager'))

        new_manager = {
            'name': name,
            'email': email,
            'phone': phone,
            'employee_id': emp_id,
            'password_hash': hashed,
            'role': 'Manager',
            'is_first_login': True,
            'grade': grade,
            'department': department,
            'location': location,
            'employee_level': employee_level,
            'manager_level': manager_level,
            'manager_id': manager_id,
            'dp_id': dp_id,
            'is_active': is_active,
            'dashboard_access': dashboard_access,
            'joining_date': joining_date,
            'exit_date': exit_date,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        mongo.db.users.insert_one(new_manager)
        flash('Manager registered successfully!', 'success')
        return redirect(url_for('hr_registration.register_manager'))

    return render_template('register_manager.html', 
                          managers=managers,
                          dps=dps, 
                          manager_levels=manager_levels, 
                          departments=departments,
                          grades=grades,
                          locations=locations,
                          employee_levels=employee_levels,
                          dashboard_access_options=dashboard_access_options)


# Register DP
@hr_registration_bp.route('/register-dp', methods=['GET', 'POST'])
def register_dp():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))

    # Fetch users who have 'pm' in their dashboard_access
    managers = list(mongo.db.users.find({
        'dashboard_access': 'pm'
    }))
    # Fetch users who have 'dp' in their dashboard_access
    dps = list(mongo.db.users.find({
        'dashboard_access': 'dp'
    }))
    
    # Fetch dynamic configurations
    config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
    if not config_data:
        config_data = {
            'config_type': 'registration',
            'grades': ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2', 'E1', 'E2', 'EL1', 'EL2', 'EL3'],
            'departments': ['Management', 'IT', 'Admin', 'Marketing', 'Sales', 'HR', 'Finance'],
            'locations': ['US', 'Non-US', 'India', 'UK', 'Canada', 'Australia'],
            'employee_levels': ['Junior', 'Mid-Level', 'Senior', 'Lead', 'Principal', 'DP'],
            'dashboard_access': ['employee_db', 'analytics_db', 'reports_db', 'pmo_db', 'finance_db', 'dp_dashboard']
        }
        mongo.db.hr_config.insert_one(config_data)
    
    grades = config_data.get('grades', [])
    departments = config_data.get('departments', [])
    locations = config_data.get('locations', [])
    employee_levels = config_data.get('employee_levels', [])
    dashboard_access_options = config_data.get('dashboard_access', [])

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        emp_id = request.form['employee_id']
        password = request.form['password']
        grade = request.form.get('grade')
        department = request.form.get('department')
        location = request.form.get('location')
        employee_level = request.form.get('employee_level')
        manager_id = request.form.get('manager_id')
        is_active = request.form.get('is_active') == 'on'
        dashboard_access = request.form.getlist('dashboard_access[]')
        # Convert to lowercase to match TA format (ta_up, ta_va, pmo_up, pmo_va)
        dashboard_access = [x.lower() for x in dashboard_access]
        joining_date = request.form['joining_date']
        exit_date = request.form.get('exit_date') or None
        
        # Ensure employee_db is always included
        if 'employee_db' not in dashboard_access:
            dashboard_access.append('employee_db')
        
        # Validate that DP must have 'dp' in dashboard_access
        if 'dp' not in dashboard_access:
            flash('DP registration requires "dp" dashboard access', 'danger')
            return redirect(url_for('hr_registration.register_dp'))

        if mongo.db.users.find_one({'email': email}):
            flash('Email already exists', 'danger')
            return redirect(url_for('hr_registration.register_dp'))

        if mongo.db.users.find_one({'employee_id': emp_id}):
            flash('Employee ID already exists', 'danger')
            return redirect(url_for('hr_registration.register_dp'))

        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        
        if manager_id:
            try:
                if manager_id.strip():
                    manager_obj_id = ObjectId(manager_id)
                    # Validate manager exists and has pm dashboard access
                    manager_check = mongo.db.users.find_one({
                        '_id': manager_obj_id,
                        'dashboard_access': 'pm'
                    })
                    if not manager_check:
                        flash('Invalid Manager ID or Manager does not have PM dashboard access', 'danger')
                        return redirect(url_for('hr_registration.register_dp'))
                    manager_id = manager_obj_id
                else:
                    manager_id = None
            except Exception as e:
                flash(f'Invalid manager ID: {str(e)}', 'danger')
                return redirect(url_for('hr_registration.register_dp'))
        else:
            manager_id = None
        
        try:
            if joining_date:
                joining_date = datetime.strptime(joining_date, '%Y-%m-%d')
        except ValueError as e:
            flash(f'Invalid joining date format: {str(e)}', 'danger')
            return redirect(url_for('hr_registration.register_dp'))
            
        try:
            if exit_date:
                exit_date = datetime.strptime(exit_date, '%Y-%m-%d')
        except ValueError as e:
            flash(f'Invalid exit date format: {str(e)}', 'danger')
            return redirect(url_for('hr_registration.register_dp'))

        new_dp = {
            'name': name,
            'email': email,
            'phone': phone,
            'employee_id': emp_id,
            'password_hash': hashed,
            'role': 'DP',
            'is_first_login': True,
            'grade': grade,
            'department': department,
            'location': location,
            'employee_level': employee_level,
            'manager_id': manager_id,
            'is_active': is_active,
            'dashboard_access': dashboard_access,
            'joining_date': joining_date,
            'exit_date': exit_date,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        mongo.db.users.insert_one(new_dp)
        flash('DP registered successfully!', 'success')
        return redirect(url_for('hr_registration.register_dp'))

    return render_template('register_dp.html', 
                          managers=managers,
                          dps=dps,
                          departments=departments,
                          grades=grades,
                          locations=locations,
                          employee_levels=employee_levels,
                          dashboard_access_options=dashboard_access_options)


# Update User
@hr_registration_bp.route('/update-user', methods=['GET', 'POST'])
def update_user():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))

    user = None
    show_form = False
    
    # Fetch dynamic configurations
    config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
    if not config_data:
        config_data = {
            'config_type': 'registration',
            'grades': ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2', 'E1', 'E2', 'EL1', 'EL2', 'EL3'],
            'departments': ['Management', 'IT', 'Admin', 'Marketing', 'Sales', 'HR', 'Finance'],
            'locations': ['US', 'Non-US', 'India', 'UK', 'Canada', 'Australia'],
            'employee_levels': ['Junior', 'Mid-Level', 'Senior', 'Lead', 'Principal', 'Manager', 'DP'],
            'dashboard_access': ['employee_db', 'analytics_db', 'reports_db', 'pmo_db', 'finance_db', 'management_db', 'dp_dashboard']
        }
        mongo.db.hr_config.insert_one(config_data)
    
    grades = config_data.get('grades', [])
    departments = config_data.get('departments', [])
    locations = config_data.get('locations', [])
    employee_levels = config_data.get('employee_levels', [])
    dashboard_access_options = config_data.get('dashboard_access', [])
    
    manager_levels = ['PMO', 'PM/Arch', 'PM', 'Marketing', 'TA', 'L & D', 'Pre-sales']

    if request.method == 'POST':
        if 'search' in request.form:
            query = request.form.get('search_query').strip()
            user = mongo.db.users.find_one({
                '$or': [
                    {'email': query},
                    {'employee_id': query}
                ]
            })

            if not user:
                flash("No user found with the given Email or Employee ID.", "danger")
            else:
                show_form = True

        elif 'update_user' in request.form:
            user_id = request.form['user_id']
            
            try:
                user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            except:
                flash("Invalid user ID", "danger")
                return redirect(url_for('hr_registration.update_user'))

            if user:
                update_data = {
                    'name': request.form['name'],
                    'email': request.form['email'],
                    'phone': request.form['phone'],
                    'employee_id': request.form['employee_id'],
                    'grade': request.form.get('grade'),
                    'department': request.form.get('department'),
                    'location': request.form.get('location'),
                    'employee_level': request.form.get('employee_level'),
                    'role': request.form['role'],
                    'is_active': request.form.get('is_active') == 'on',
                    'dashboard_access': [x.lower() for x in request.form.getlist('dashboard_access[]')],
                    'updated_at': datetime.now()
                }
                
                # Ensure employee_db is always included
                if 'employee_db' not in update_data['dashboard_access']:
                    update_data['dashboard_access'].append('employee_db')
                
                if update_data['role'] == 'Manager':
                    update_data['manager_level'] = request.form.get('manager_level')
                
                joining_date = request.form.get('joining_date')
                if joining_date:
                    update_data['joining_date'] = datetime.strptime(joining_date, '%Y-%m-%d')
                
                exit_date = request.form.get('exit_date')
                if exit_date:
                    update_data['exit_date'] = datetime.strptime(exit_date, '%Y-%m-%d')
                else:
                    update_data['exit_date'] = None
                
                manager_id = request.form.get('manager_id')
                if manager_id:
                    try:
                        manager_obj_id = ObjectId(manager_id)
                        # Validate manager exists and has pm dashboard access
                        manager_check = mongo.db.users.find_one({
                            '_id': manager_obj_id,
                            'dashboard_access': 'pm'
                        })
                        if not manager_check:
                            flash("Invalid Manager ID or Manager does not have PM dashboard access", "danger")
                            return redirect(url_for('hr_registration.update_user'))
                        update_data['manager_id'] = manager_obj_id
                    except:
                        flash("Invalid manager ID", "danger")
                        return redirect(url_for('hr_registration.update_user'))
                else:
                    update_data['manager_id'] = None
                
                dp_id = request.form.get('dp_id')
                if dp_id:
                    try:
                        dp_obj_id = ObjectId(dp_id)
                        # Validate DP exists and has dp dashboard access
                        dp_check = mongo.db.users.find_one({
                            '_id': dp_obj_id,
                            'dashboard_access': 'dp'
                        })
                        if not dp_check:
                            flash("Invalid DP ID or DP does not have DP dashboard access", "danger")
                            return redirect(url_for('hr_registration.update_user'))
                        update_data['dp_id'] = dp_obj_id
                    except:
                        flash("Invalid DP ID", "danger")
                        return redirect(url_for('hr_registration.update_user'))
                else:
                    update_data['dp_id'] = None
                
                new_password = request.form.get('password')
                if new_password:
                    update_data['password_hash'] = bcrypt.generate_password_hash(new_password).decode('utf-8')
                    update_data['is_first_login'] = True

                mongo.db.users.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$set': update_data}
                )
                
                flash("User updated successfully!", "success")
                return redirect(url_for('hr_registration.update_user', updated='true'))

            else:
                flash("User not found.", "danger")

    elif request.method == 'GET' and request.args.get('updated') == 'true':
        show_form = False

    # Fetch users who have 'pm' in their dashboard_access
    managers = list(mongo.db.users.find({
        'dashboard_access': 'pm'
    }))
    # Fetch users who have 'dp' in their dashboard_access
    dps = list(mongo.db.users.find({
        'dashboard_access': 'dp'
    }))
    
    # Get current quarter and month for header display
    now = datetime.utcnow()
    _, quarter_label, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
    display_quarter = f"{quarter_label} {fiscal_year_label}"
    display_month = now.strftime("%b %Y").upper()
    
    return render_template("update_user.html", 
                          user=user, 
                          managers=managers,
                          dps=dps, 
                          grades=grades, 
                          show_form=show_form, 
                          manager_levels=manager_levels, 
                          departments=departments,
                          locations=locations,
                          employee_levels=employee_levels,
                          dashboard_access_options=dashboard_access_options,
                          display_quarter=display_quarter,
                          display_month=display_month)


# Manage Dynamic Fields (Grades, Departments, Locations, etc.)
@hr_registration_bp.route('/manage-fields', methods=['GET', 'POST'])
def manage_fields():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
    if not config_data:
        config_data = {
            'config_type': 'registration',
            'grades': ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2'],
            'departments': ['Management', 'IT', 'Admin', 'Marketing', 'Sales', 'HR', 'Finance'],
            'locations': ['US', 'Non-US', 'India', 'UK', 'Canada', 'Australia'],
            'employee_levels': ['Junior', 'Mid-Level', 'Senior', 'Lead', 'Principal'],
            'dashboard_access': ['employee_db', 'analytics_db', 'reports_db', 'pmo_db', 'finance_db']
        }
        mongo.db.hr_config.insert_one(config_data)
    
    if request.method == 'POST':
        field_type = request.form.get('field_type')
        action = request.form.get('action')
        value = request.form.get('value', '').strip()
        
        if field_type and action and value:
            if action == 'add':
                if value not in config_data.get(field_type, []):
                    mongo.db.hr_config.update_one(
                        {'config_type': 'registration'},
                        {'$push': {field_type: value}}
                    )
                    flash(f'{value} added to {field_type} successfully!', 'success')
                else:
                    flash(f'{value} already exists in {field_type}!', 'warning')
            
            elif action == 'remove':
                if value in config_data.get(field_type, []):
                    # Don't allow removing employee_db from dashboard_access
                    if not (field_type == 'dashboard_access' and value == 'employee_db'):
                        mongo.db.hr_config.update_one(
                            {'config_type': 'registration'},
                            {'$pull': {field_type: value}}
                        )
                        flash(f'{value} removed from {field_type} successfully!', 'success')
                    else:
                        flash('employee_db cannot be removed from dashboard access!', 'danger')
                else:
                    flash(f'{value} not found in {field_type}!', 'warning')
        
        return redirect(url_for('hr_registration.manage_fields'))
    
    # Get current quarter and month for header display
    now = datetime.utcnow()
    _, quarter_label, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
    display_quarter = f"{quarter_label} {fiscal_year_label}"
    display_month = now.strftime("%b %Y").upper()
    
    return render_template('manage_fields.html', 
                          config_data=config_data,
                          display_quarter=display_quarter,
                          display_month=display_month)


# API endpoint to get dynamic fields (for AJAX requests)
@hr_registration_bp.route('/api/get-fields/<field_type>')
def get_fields(field_type):
    has_access, current_user = check_hr_access()
    
    if not has_access:
        return jsonify({'error': 'Unauthorized'}), 403
    
    config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
    if config_data and field_type in config_data:
        return jsonify({field_type: config_data[field_type]})
    
    return jsonify({field_type: []})


# Download CSV Template
@hr_registration_bp.route('/download-csv-template')
def download_csv_template():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    csv_buffer = io.StringIO()
    
    fieldnames = ['name', 'email', 'phone', 'employee_id', 'password', 'grade', 
                 'department', 'location', 'employee_level', 'manager_name', 'dp_name',
                 'is_active', 'dashboard_access', 'joining_date', 'exit_date']
    
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
    writer.writeheader()
    
    # Sample row with all fields
    sample_row = {
        'name': 'John Doe',
        'email': 'john.doe@example.com',
        'phone': '1234567890',
        'employee_id': 'EMP001',
        'password': 'SecurePassword123',
        'grade': 'B2',
        'department': 'IT',
        'location': 'US',
        'employee_level': 'Senior',
        'manager_name': 'Jane Manager',
        'dp_name': 'Bob DP',
        'is_active': 'true',
        'dashboard_access': 'employee_db,analytics_db,reports_db',
        'joining_date': datetime.now().strftime('%Y-%m-%d'),
        'exit_date': ''
    }
    
    writer.writerow(sample_row)
    
    # Minimal row example
    minimal_row = {
        'name': 'Jane Smith',
        'email': 'jane.smith@example.com',
        'phone': '0987654321',
        'employee_id': 'EMP002',
        'password': 'AnotherPassword456',
        'grade': 'C1',
        'department': 'Marketing',
        'location': 'Non-US',
        'employee_level': 'Mid-Level',
        'manager_name': 'John Manager',
        'dp_name': '',
        'is_active': 'true',
        'dashboard_access': 'employee_db',
        'joining_date': datetime.now().strftime('%Y-%m-%d'),
        'exit_date': ''
    }
    
    writer.writerow(minimal_row)
    
    # Empty row for users to fill
    empty_row = {field: '' for field in fieldnames}
    writer.writerow(empty_row)
    
    # Add comments row explaining the fields
    comments_row = {
        'name': 'Full Name (Required)',
        'email': 'Email Address (Required, Unique)',
        'phone': 'Phone Number (Required)',
        'employee_id': 'Employee ID (Required, Unique)',
        'password': 'Password (Required)',
        'grade': 'Grade (e.g., A1, B1, C1)',
        'department': 'Department (e.g., IT, Marketing)',
        'location': 'Location (e.g., US, Non-US)',
        'employee_level': 'Level (e.g., Junior, Senior)',
        'manager_name': 'Manager Name or Email (Optional)',
        'dp_name': 'DP Name or Email (Optional)',
        'is_active': 'true/false (Default: true)',
        'dashboard_access': 'Comma-separated (e.g., employee_db,analytics_db)',
        'joining_date': 'YYYY-MM-DD Format (Required)',
        'exit_date': 'YYYY-MM-DD Format (Optional)'
    }
    
    writer.writerow(comments_row)
    
    csv_buffer.seek(0)
    
    return send_file(
        io.BytesIO(csv_buffer.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='employee_registration_template.csv'
    )


# Bulk Update Users
@hr_registration_bp.route('/bulk-update', methods=['GET', 'POST'])
def bulk_update():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        file = request.files.get('csv_file')
        if not file or not file.filename.endswith('.csv'):
            flash('Please upload a valid CSV file.', 'danger')
            return redirect(url_for('hr_registration.bulk_update'))

        try:
            file.stream.seek(0)
            csv_reader = csv.DictReader(file.read().decode('utf-8').splitlines())

            updated, skipped = 0, 0
            row_num = 1
            error_messages = []

            for row in csv_reader:
                row_num += 1
                try:
                    # Find user by email or employee_id
                    identifier = row.get('email') or row.get('employee_id')
                    if not identifier:
                        skipped += 1
                        error_messages.append(f"Row {row_num}: Skipped (no email or employee_id)")
                        continue
                    
                    user = mongo.db.users.find_one({
                        '$or': [
                            {'email': identifier},
                            {'employee_id': identifier}
                        ]
                    })
                    
                    if not user:
                        skipped += 1
                        error_messages.append(f"Row {row_num}: User not found ({identifier})")
                        continue
                    
                    update_data = {'updated_at': datetime.now()}
                    
                    # Update only provided fields
                    if row.get('name'):
                        update_data['name'] = row['name']
                    if row.get('phone'):
                        update_data['phone'] = row['phone']
                    if row.get('grade'):
                        update_data['grade'] = row['grade']
                    if row.get('department'):
                        update_data['department'] = row['department']
                    if row.get('location'):
                        update_data['location'] = row['location']
                    if row.get('employee_level'):
                        update_data['employee_level'] = row['employee_level']
                    if row.get('is_active'):
                        is_active_str = row['is_active'].lower()
                        update_data['is_active'] = is_active_str in ['true', 'yes', '1', 'on', 'active']
                    if row.get('dashboard_access'):
                        dashboard_access = [x.strip() for x in row['dashboard_access'].split(',')]
                        if 'employee_db' not in dashboard_access:
                            dashboard_access.append('employee_db')
                        update_data['dashboard_access'] = dashboard_access
                    
                    # Handle manager update (must have 'pm' in dashboard_access)
                    if row.get('manager_name'):
                        manager = mongo.db.users.find_one({
                            '$or': [
                                {'name': row['manager_name']},
                                {'email': row['manager_name']}
                            ],
                            'dashboard_access': 'pm'
                        })
                        if manager:
                            update_data['manager_id'] = manager['_id']
                    
                    # Handle DP update (must have 'dp' in dashboard_access)
                    if row.get('dp_name'):
                        dp = mongo.db.users.find_one({
                            '$or': [
                                {'name': row['dp_name']},
                                {'email': row['dp_name']}
                            ],
                            'dashboard_access': 'dp'
                        })
                        if dp:
                            update_data['dp_id'] = dp['_id']
                    
                    # Handle dates
                    if row.get('joining_date'):
                        update_data['joining_date'] = datetime.strptime(row['joining_date'], '%Y-%m-%d')
                    if row.get('exit_date'):
                        update_data['exit_date'] = datetime.strptime(row['exit_date'], '%Y-%m-%d')
                    
                    # Handle password update
                    if row.get('password'):
                        update_data['password_hash'] = bcrypt.generate_password_hash(row['password']).decode('utf-8')
                        update_data['is_first_login'] = True
                    
                    mongo.db.users.update_one(
                        {'_id': user['_id']},
                        {'$set': update_data}
                    )
                    updated += 1

                except Exception as row_err:
                    skipped += 1
                    error_messages.append(f"Row {row_num}: Error - {str(row_err)}")
                    continue

            flash(f'{updated} users updated, {skipped} skipped.', 'success')
            for msg in error_messages:
                flash(msg, 'warning')

        except Exception as e:
            flash(f'Critical error processing CSV: {str(e)}', 'danger')

        return redirect(url_for('hr_registration.bulk_update'))

    return render_template('bulk_update.html')