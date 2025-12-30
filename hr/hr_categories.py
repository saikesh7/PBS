from flask import Blueprint, render_template, request, redirect, session, url_for, flash, jsonify
from extensions import mongo
from datetime import datetime
from bson.objectid import ObjectId
import os
from .hr_utils import check_hr_access  # Import from hr_utils like other HR modules
from .hr_analytics import get_financial_quarter_and_label

# Get the current directory path
current_dir = os.path.dirname(os.path.abspath(__file__))

# Define Blueprint for HR Categories
hr_categories_bp = Blueprint('hr_categories', __name__, url_prefix='/hr/categories',
                             template_folder=os.path.join(current_dir, 'templates'),
                             static_folder=os.path.join(current_dir, 'static'),
                             static_url_path='/hr/categories/static')


# Main Dashboard Route - Serves the single-page template
@hr_categories_bp.route('/', methods=['GET'])
def categories_dashboard():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access the category management', 'danger')
        return redirect(url_for('auth.login'))
    
    # Fetch all categories
    categories = list(mongo.db.hr_categories.find())
    
    # Convert ObjectId to string for JSON serialization
    for category in categories:
        category['_id'] = str(category['_id'])
    
    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    department_filter = request.args.get('department', 'all')
    category_type_filter = request.args.get('category_type', 'all')
    
    # Apply filters
    if status_filter != 'all':
        categories = [cat for cat in categories if cat.get('category_status') == status_filter]
    
    if department_filter != 'all':
        categories = [cat for cat in categories if cat.get('category_department') == department_filter]
    
    if category_type_filter != 'all':
        categories = [cat for cat in categories if cat.get('category_type') == category_type_filter]
    
    # Fetch dynamic configurations
    config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
    if config_data:
        grades = config_data.get('grades', [])
        departments = [dept for dept in config_data.get('dashboard_access', []) if dept != 'employee_db']
    else:
        grades = ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']
        departments = []
    
    # Get current quarter and month for header display
    now = datetime.utcnow()
    _, quarter_label, _, _, fiscal_year_label = get_financial_quarter_and_label(now)
    display_quarter = f"{quarter_label} {fiscal_year_label}"
    display_month = now.strftime("%b %Y").upper()
    
    return render_template('categories.html', 
                          categories=categories,
                          departments=departments,
                          grades=grades,
                          status_filter=status_filter,
                          department_filter=department_filter,
                          category_type_filter=category_type_filter,
                          display_quarter=display_quarter,
                          display_month=display_month)


# Create Category
@hr_categories_bp.route('/create', methods=['POST'])
def create_category():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    # Fetch grades from config
    config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
    grades = config_data.get('grades', []) if config_data else ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']
    
    try:
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        frequency = request.form.get('frequency')
        category_status = request.form.get('category_status', 'active')
        category_department = request.form.get('category_department')
        category_type = request.form.get('category_type')
        
        if not all([name, description, frequency, category_status, category_department, category_type]):
            flash('All required fields must be filled', 'danger')
            return redirect(url_for('hr_categories.categories_dashboard'))
        
        if mongo.db.hr_categories.find_one({'name': name}):
            flash('Category name already exists', 'danger')
            return redirect(url_for('hr_categories.categories_dashboard'))
        
        # Build points_per_unit dictionary with base and grade-wise values
        points_per_unit = {}
        base_points = request.form.get('base_points_per_unit', 0)
        points_per_unit['base'] = int(base_points) if base_points else 0
        
        for grade in grades:
            grade_points = request.form.get(f'points_per_unit_{grade}', 0)
            points_per_unit[grade] = int(grade_points) if grade_points else 0
        
        # Build min_points_per_frequency dictionary with grade-wise values
        min_points_per_frequency = {}
        for grade in grades:
            min_points = request.form.get(f'min_points_{grade}', 0)
            min_points_per_frequency[grade] = int(min_points) if min_points else 0
        
        new_category = {
            'name': name,
            'description': description,
            'points_per_unit': points_per_unit,
            'min_points_per_frequency': min_points_per_frequency,
            'frequency': frequency,
            'category_status': category_status,
            'category_department': category_department,
            'category_type': category_type,
            'created_at': datetime.now(),
            'updated_at': datetime.now(),
            'created_by': current_user.get('email', 'Unknown')
        }
        
        mongo.db.hr_categories.insert_one(new_category)
        flash('Category created successfully!', 'success')
        
    except Exception as e:
        flash(f'Error creating category: {str(e)}', 'danger')
    
    return redirect(url_for('hr_categories.categories_dashboard'))


# Edit Category
@hr_categories_bp.route('/edit/<category_id>', methods=['POST'])
def edit_category(category_id):
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to access this page', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        if not category:
            flash('Category not found', 'danger')
            return redirect(url_for('hr_categories.categories_dashboard'))
        
        # Fetch grades from config
        config_data = mongo.db.hr_config.find_one({'config_type': 'registration'})
        grades = config_data.get('grades', []) if config_data else ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']
        
        name = request.form.get('name', '').strip()
        
        # Check duplicate name
        existing = mongo.db.hr_categories.find_one({'name': name, '_id': {'$ne': ObjectId(category_id)}})
        if existing:
            flash('Category name already exists', 'danger')
            return redirect(url_for('hr_categories.categories_dashboard'))
        
        # Build points_per_unit dictionary with base and grade-wise values
        points_per_unit = {}
        base_points = request.form.get('base_points_per_unit', 0)
        points_per_unit['base'] = int(base_points) if base_points else 0
        
        for grade in grades:
            grade_points = request.form.get(f'points_per_unit_{grade}', 0)
            points_per_unit[grade] = int(grade_points) if grade_points else 0
        
        # Build min_points_per_frequency dictionary with grade-wise values
        min_points_per_frequency = {}
        for grade in grades:
            min_points = request.form.get(f'min_points_{grade}', 0)
            min_points_per_frequency[grade] = int(min_points) if min_points else 0
        
        update_data = {
            'name': name,
            'description': request.form.get('description', '').strip(),
            'points_per_unit': points_per_unit,
            'min_points_per_frequency': min_points_per_frequency,
            'frequency': request.form.get('frequency'),
            'category_status': request.form.get('category_status', 'active'),
            'category_department': request.form.get('category_department'),
            'category_type': request.form.get('category_type'),
            'updated_at': datetime.now(),
            'updated_by': current_user.get('email', 'Unknown')
        }
        
        mongo.db.hr_categories.update_one({'_id': ObjectId(category_id)}, {'$set': update_data})
        flash('Category updated successfully!', 'success')
        
    except Exception as e:
        flash(f'Error updating category: {str(e)}', 'danger')
    
    return redirect(url_for('hr_categories.categories_dashboard'))


# Delete Category
@hr_categories_bp.route('/delete/<category_id>', methods=['POST'])
def delete_category(category_id):
    has_access, current_user = check_hr_access()
    
    if not has_access:
        flash('You do not have permission to perform this action', 'danger')
        return redirect(url_for('auth.login'))
    
    try:
        result = mongo.db.hr_categories.delete_one({'_id': ObjectId(category_id)})
        if result.deleted_count > 0:
            flash('Category deleted successfully!', 'success')
        else:
            flash('Category not found', 'danger')
    except Exception as e:
        flash(f'Error deleting category: {str(e)}', 'danger')
    
    return redirect(url_for('hr_categories.categories_dashboard'))


# Toggle Category Status
@hr_categories_bp.route('/toggle-status/<category_id>', methods=['POST'])
def toggle_category_status(category_id):
    has_access, current_user = check_hr_access()
    
    if not has_access:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        category = mongo.db.hr_categories.find_one({'_id': ObjectId(category_id)})
        if not category:
            return jsonify({'success': False, 'message': 'Category not found'}), 404
        
        new_status = 'inactive' if category.get('category_status') == 'active' else 'active'
        
        mongo.db.hr_categories.update_one(
            {'_id': ObjectId(category_id)},
            {'$set': {
                'category_status': new_status,
                'updated_at': datetime.now(),
                'updated_by': current_user.get('email', 'Unknown')
            }}
        )
        
        return jsonify({'success': True, 'new_status': new_status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# API: Get categories by department
@hr_categories_bp.route('/api/get-categories-by-department/<department>')
def get_categories_by_department(department):
    has_access, current_user = check_hr_access()
    
    if not has_access:
        return jsonify({'error': 'Unauthorized'}), 403
    
    categories = list(mongo.db.hr_categories.find({
        'category_department': department,
        'category_status': 'active'
    }))
    
    for cat in categories:
        cat['_id'] = str(cat['_id'])
    
    return jsonify({'categories': categories})


# API: Get all active categories
@hr_categories_bp.route('/api/get-active-categories')
def get_active_categories():
    has_access, current_user = check_hr_access()
    
    if not has_access:
        return jsonify({'error': 'Unauthorized'}), 403
    
    categories = list(mongo.db.hr_categories.find({'category_status': 'active'}))
    
    for cat in categories:
        cat['_id'] = str(cat['_id'])
    
    return jsonify({'categories': categories})