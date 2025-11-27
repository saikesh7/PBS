from flask import Blueprint, render_template, request, redirect, session, url_for, flash, send_file, jsonify
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import csv
import io
import os
from .hr_utils import check_hr_access  # Changed to relative import

current_dir = os.path.dirname(os.path.abspath(__file__))

hr_employee_mgmt_bp = Blueprint('hr_employee_mgmt', __name__, url_prefix='/hr',
                                template_folder=os.path.join(current_dir, 'templates'),
                                static_folder=os.path.join(current_dir, 'static'),
                                static_url_path='/hr/static')


@hr_employee_mgmt_bp.route('/employee-list', methods=['GET'])
def employee_list():
    """Get detailed list of all employees with all fields for HR viewing"""
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    department = request.args.get('department')
    grade = request.args.get('grade')
    location = request.args.get('us_non_us')
    
    query = {'role': {'$in': ['Employee', 'DP']}}
    
    if department:
        query['department'] = department
    
    if grade:
        query['grade'] = grade
    
    if location:
        # Support both field names for backward compatibility
        if '$or' not in query:
            query = {'$and': [query, {'$or': [{'us_non_us': location}, {'location': location}]}]}
        else:
            query['$or'].append({'us_non_us': location})
            query['$or'].append({'location': location})
    
    employees = list(mongo.db.users.find(query).sort('name', 1))
    
    managers = list(mongo.db.users.find({'role': 'Manager'}, {'_id': 1, 'name': 1}))
    manager_dict = {str(manager['_id']): manager['name'] for manager in managers}
    
    for employee in employees:
        if employee.get('manager_id'):
            manager_id = str(employee['manager_id'])
            employee['manager_name'] = manager_dict.get(manager_id, 'Unknown')
        else:
            employee['manager_name'] = 'Not Assigned'
    
    departments = ['Management', 'IT', 'Admin']
    grades = ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']
    locations = ['US', 'Non-US']
    
    return render_template(
        'employee_list.html',
        employees=employees,
        departments=departments,
        grades=grades,
        locations=locations,
        selected_department=department,
        selected_grade=grade,
        selected_location=location
    )


@hr_employee_mgmt_bp.route('/api/employees', methods=['GET'])
def api_employees():
    """API endpoint to get all employee details in JSON format"""
    has_access, user = check_hr_access()
    
    if not has_access:
        return {"error": "Unauthorized"}, 401
    
    department = request.args.get('department')
    grade = request.args.get('grade')
    location = request.args.get('us_non_us')
    
    query = {'role': {'$in': ['Employee', 'DP']}}
    
    if department:
        query['department'] = department
    
    if grade:
        query['grade'] = grade
    
    if location:
        # Support both field names for backward compatibility
        if '$or' not in query:
            query = {'$and': [query, {'$or': [{'us_non_us': location}, {'location': location}]}]}
        else:
            query['$or'].append({'us_non_us': location})
            query['$or'].append({'location': location})
    
    projection = {'password_hash': 0}
    
    employees = list(mongo.db.users.find(query, projection).sort('name', 1))
    
    for employee in employees:
        employee['_id'] = str(employee['_id'])
        if employee.get('manager_id'):
            employee['manager_id'] = str(employee['manager_id'])
        
        if employee.get('joining_date'):
            employee['joining_date'] = employee['joining_date'].strftime('%Y-%m-%d')
        
        if employee.get('exit_date'):
            employee['exit_date'] = employee['exit_date'].strftime('%Y-%m-%d')
    
    return {"employees": employees, "count": len(employees)}


@hr_employee_mgmt_bp.route('/download-employee-list', methods=['GET'])
def download_employee_list():
    """Generate and download employee list as CSV"""
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    department = request.args.get('department')
    grade = request.args.get('grade')
    location = request.args.get('us_non_us')
    
    query = {'role': {'$in': ['Employee', 'DP']}}
    
    if department:
        query['department'] = department
    
    if grade:
        query['grade'] = grade
    
    if location:
        # Support both field names for backward compatibility
        if '$or' not in query:
            query = {'$and': [query, {'$or': [{'us_non_us': location}, {'location': location}]}]}
        else:
            query['$or'].append({'us_non_us': location})
            query['$or'].append({'location': location})
    
    employees = list(mongo.db.users.find(query).sort('name', 1))
    
    managers = list(mongo.db.users.find({'role': 'Manager'}, {'_id': 1, 'name': 1}))
    manager_dict = {str(manager['_id']): manager['name'] for manager in managers}
    
    csv_buffer = io.StringIO()
    
    fieldnames = ['name', 'email', 'phone', 'employee_id', 'grade', 'department', 
                  'us_non_us', 'manager_name', 'joining_date', 'exit_date']
    
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
    writer.writeheader()
    
    for employee in employees:
        manager_name = "Not Assigned"
        if employee.get('manager_id'):
            manager_id = str(employee['manager_id'])
            manager_name = manager_dict.get(manager_id, 'Unknown')
        
        joining_date = ""
        if employee.get('joining_date'):
            joining_date = employee['joining_date'].strftime('%Y-%m-%d')
        
        exit_date = ""
        if employee.get('exit_date'):
            exit_date = employee['exit_date'].strftime('%Y-%m-%d')
        
        writer.writerow({
            'name': employee.get('name', ''),
            'email': employee.get('email', ''),
            'phone': employee.get('phone', ''),
            'employee_id': employee.get('employee_id', ''),
            'grade': employee.get('grade', ''),
            'department': employee.get('department', ''),
            'us_non_us': employee.get('us_non_us', ''),
            'manager_name': manager_name,
            'joining_date': joining_date,
            'exit_date': exit_date
        })
    
    csv_buffer.seek(0)
    
    filter_desc = ""
    if department:
        filter_desc += f"_{department}"
    if grade:
        filter_desc += f"_{grade}"
    if location:
        filter_desc += f"_{location}"
    
    current_date = datetime.utcnow().strftime('%Y%m%d')
    filename = f"employee_list{filter_desc}_{current_date}.csv"
    
    return send_file(
        io.BytesIO(csv_buffer.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


@hr_employee_mgmt_bp.route('/deactivate-user/<user_id>', methods=['POST'])
def deactivate_user(user_id):
    """Deactivate a user (soft delete) by setting active status to False"""
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        user_to_deactivate = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        if not user_to_deactivate:
            flash('User not found.', 'danger')
            return redirect(url_for('hr_employee_mgmt.employee_list'))
        
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {'active': False, 'deactivated_date': datetime.utcnow()}}
        )
        
        flash(f"{user_to_deactivate['role']} '{user_to_deactivate['name']}' has been deactivated.", 'success')
        
    except Exception as e:
        flash(f'Error deactivating user: {str(e)}', 'danger')
    
    if request.form.get('redirect_url'):
        return redirect(request.form.get('redirect_url'))
    else:
        return redirect(url_for('hr_employee_mgmt.employee_list'))


@hr_employee_mgmt_bp.route('/delete-user/<user_id>', methods=['POST'])
def delete_user(user_id):
    """Permanently delete a user (employee or manager)"""
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        user_to_delete = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        
        if not user_to_delete:
            flash('User not found.', 'danger')
            return redirect(url_for('hr_employee_mgmt.employee_list'))
        
        user_role = user_to_delete['role']
        user_name = user_to_delete['name']
        
        if user_role == 'Manager':
            dependent_count = mongo.db.users.count_documents({'manager_id': ObjectId(user_id)})
            if dependent_count > 0:
                flash(f"Cannot delete manager '{user_name}' as they have {dependent_count} employees assigned to them. Please reassign these employees first.", 'warning')
                return redirect(url_for('hr_employee_mgmt.manager_employees', manager_id=user_id))
        
        mongo.db.points.delete_many({'user_id': ObjectId(user_id)})
        mongo.db.points_request.delete_many({'user_id': ObjectId(user_id)})
        
        mongo.db.users.delete_one({'_id': ObjectId(user_id)})
        
        flash(f"{user_role} '{user_name}' has been permanently deleted.", 'success')
        
    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'danger')
    
    if request.form.get('redirect_url'):
        return redirect(request.form.get('redirect_url'))
    else:
        return redirect(url_for('hr_employee_mgmt.employee_list'))


@hr_employee_mgmt_bp.route('/manager-employees/<manager_id>')
def manager_employees(manager_id):
    """List all employees assigned to a specific manager"""
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        manager = mongo.db.users.find_one({'_id': ObjectId(manager_id)})
        
        if not manager:
            flash('Manager not found.', 'danger')
            return redirect(url_for('hr_employee_mgmt.employee_list'))
        
        employees = list(mongo.db.users.find(
            {'manager_id': ObjectId(manager_id), 'role': 'Employee'}
        ).sort('name', 1))
        
        other_managers = list(mongo.db.users.find(
            {'role': 'Manager', '_id': {'$ne': ObjectId(manager_id)}}
        ).sort('name', 1))
        
        return render_template(
            'manager_employees.html',
            manager=manager,
            employees=employees,
            other_managers=other_managers
        )
        
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('hr_employee_mgmt.employee_list'))


@hr_employee_mgmt_bp.route('/reassign-employees', methods=['POST'])
def reassign_employees():
    """Reassign employees from one manager to another"""
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        old_manager_id = request.form.get('old_manager_id')
        new_manager_id = request.form.get('new_manager_id')
        
        if not old_manager_id or not new_manager_id:
            flash('Both original and new manager must be specified.', 'danger')
            return redirect(url_for('hr_employee_mgmt.employee_list'))
        
        old_manager_id = ObjectId(old_manager_id)
        new_manager_id = ObjectId(new_manager_id)
        
        old_manager = mongo.db.users.find_one({'_id': old_manager_id})
        new_manager = mongo.db.users.find_one({'_id': new_manager_id})
        
        if not old_manager or not new_manager:
            flash('One or both managers not found.', 'danger')
            return redirect(url_for('hr_employee_mgmt.employee_list'))
        
        result = mongo.db.users.update_many(
            {'manager_id': old_manager_id},
            {'$set': {'manager_id': new_manager_id}}
        )
        
        if result.modified_count > 0:
            flash(f'Successfully reassigned {result.modified_count} employees from {old_manager["name"]} to {new_manager["name"]}.', 'success')
        else:
            flash('No employees were reassigned.', 'warning')
        
        return redirect(url_for('hr_employee_mgmt.manager_employees', manager_id=old_manager_id))
        
    except Exception as e:
        flash(f'Error reassigning employees: {str(e)}', 'danger')
        return redirect(url_for('hr_employee_mgmt.employee_list'))


@hr_employee_mgmt_bp.route('/bulk-delete-users', methods=['POST'])
def bulk_delete_users():
    """Delete multiple users at once"""
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        user_ids = request.form.getlist('user_ids')
        deletion_type = request.form.get('deletion_type', 'deactivate')
        
        if not user_ids:
            flash('No users selected for deletion.', 'warning')
            return redirect(url_for('hr_employee_mgmt.employee_list'))
        
        deleted_count = 0
        failed_count = 0
        failed_users = []
        
        for user_id in user_ids:
            try:
                user_to_process = mongo.db.users.find_one({'_id': ObjectId(user_id)})
                
                if not user_to_process:
                    failed_count += 1
                    continue
                
                if user_to_process['role'] == 'Manager':
                    dependent_count = mongo.db.users.count_documents({'manager_id': ObjectId(user_id)})
                    if dependent_count > 0:
                        failed_count += 1
                        failed_users.append(f"{user_to_process['name']} (has {dependent_count} assigned employees)")
                        continue
                
                if deletion_type == 'deactivate':
                    mongo.db.users.update_one(
                        {'_id': ObjectId(user_id)},
                        {'$set': {'active': False, 'deactivated_date': datetime.utcnow()}}
                    )
                else:
                    mongo.db.points.delete_many({'user_id': ObjectId(user_id)})
                    mongo.db.points_request.delete_many({'user_id': ObjectId(user_id)})
                    
                    mongo.db.users.delete_one({'_id': ObjectId(user_id)})
                
                deleted_count += 1
                
            except Exception as e:
                failed_count += 1
        
        action_verb = "deactivated" if deletion_type == "deactivate" else "permanently deleted"
        
        if deleted_count > 0:
            flash(f'Successfully {action_verb} {deleted_count} users.', 'success')
        
        if failed_count > 0:
            if failed_users:
                flash(f'Failed to process {failed_count} users: {", ".join(failed_users)}', 'warning')
            else:
                flash(f'Failed to process {failed_count} users.', 'warning')
        
    except Exception as e:
        flash(f'Error during bulk deletion: {str(e)}', 'danger')
    
    return redirect(url_for('hr_employee_mgmt.employee_list'))


@hr_employee_mgmt_bp.route('/update-employee-points', methods=['POST'])
def update_employee_points():
    has_access, user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))

    try:
        user_id = request.form.get('user_id')
        points = request.form.get('points')

        if not user_id or not points:
            flash('User ID and points are required.', 'warning')
            return redirect(url_for('hr_employee_mgmt.employee_list'))

        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {'points': points}}
        )

        flash('Employee points updated successfully.', 'success')
    except Exception as e:
        flash(f'Error updating employee points: {str(e)}', 'danger')

    return redirect(url_for('hr_employee_mgmt.employee_list'))