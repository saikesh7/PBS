from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from extensions import mongo, mail, bcrypt
from datetime import datetime, timedelta
import random
from flask_mail import Message
from bson.objectid import ObjectId

auth_bp = Blueprint(
    'auth',
    __name__,
    url_prefix='/auth',
    template_folder='templates',
    static_folder='static',
    static_url_path='/auth/static'
)

# ============================================================================
# VALID DASHBOARD CODES
# ============================================================================
VALID_DASHBOARDS = ['pm', 'pmo', 'pmo_up', 'pmo_va', 'pm_arch', 'ta_va', 'ta_up', 'ld_up','ld_va', 'marketing', 'presales', 'central', 'hr','dp', 'dp_dashboard']


# ============================================================================
# LOGIN ROUTE - SIMPLIFIED TO ALWAYS GO TO EMPLOYEE DASHBOARD
# ============================================================================

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = mongo.db.users.find_one({'email': email})

        if user and bcrypt.check_password_hash(user['password_hash'], password):
            # ------------------------------------------------------------
            # ✅ Reset session and store normalized values
            # ------------------------------------------------------------
            session.clear()
            session['user_id'] = str(user['_id'])
            session['user_role'] = user.get('role', 'Employee')
            session['user_name'] = user.get('name', '')
            session['user_email'] = user.get('email', '')

            # Normalize dashboard access list (handle string or list)
            dashboard_access = user.get('dashboard_access', [])
            
            # Convert to list and normalize
            if isinstance(dashboard_access, str):
                dashboard_access = [x.strip().lower() for x in dashboard_access.split(',') if x.strip()]
            elif isinstance(dashboard_access, list):
                dashboard_access = [x.strip().lower() for x in dashboard_access if isinstance(x, str) and x.strip()]
            else:
                dashboard_access = []
            
            # ✅ IMPORTANT: Filter to only valid dashboard codes
            dashboard_access = [d for d in dashboard_access if d in VALID_DASHBOARDS]
            
            session['dashboard_access'] = dashboard_access

            print("DEBUG: User email =", user.get('email'))
            print("DEBUG: Raw dashboard_access from DB =", user.get('dashboard_access'))
            print("DEBUG: Normalized dashboard_access =", dashboard_access)
            print("DEBUG: Session dashboard_access =", session['dashboard_access'])

            # ------------------------------------------------------------
            # ✅ Handle first login reset
            # ------------------------------------------------------------
            if user.get('is_first_login', True):
                return redirect(url_for('auth.reset_password'))

            # ------------------------------------------------------------
            # ✅ Redirect to Employee Dashboard always
            # (The Employee dashboard will show available dashboards)
            # ------------------------------------------------------------
            session['justLoggedIn'] = True
            flash('Login successful. Welcome back!', 'success')
            return redirect(url_for('employee_dashboard.dashboard'))

        # Invalid credentials
        flash('Invalid credentials. Please check your email or password.', 'danger')

    return render_template('login.html')


# ============================================================================
# RESET PASSWORD FOR FIRST-TIME LOGIN
# ============================================================================

@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if new_password == confirm_password:
            password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
            
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {'password_hash': password_hash, 'is_first_login': False}}
            )
            
            flash('Password reset successful. Please log in again.', 'success')
            session.clear()
            return redirect(url_for('auth.login'))
        else:
            flash('Passwords do not match', 'danger')

    return render_template('reset_password.html')

# ============================================================================
# FORGOT PASSWORD
# ============================================================================

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = mongo.db.users.find_one({'email': email})
        if user:
            flash('If your email is registered, instructions will be sent.', 'info')
            return redirect(url_for('auth.login'))
        flash('Email not found. Please check your email address.', 'danger')
    return render_template('forgot_password.html')

@auth_bp.route('/forgot-reset-password', methods=['GET', 'POST'])
def forgot_reset_password():
    user_id = session.get('reset_user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if new_password == confirm_password:
            password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
            
            mongo.db.users.update_one(
                {'_id': ObjectId(user_id)},
                {'$set': {'password_hash': password_hash}}
            )
            
            session.clear()
            flash('Password reset successful.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('Passwords do not match', 'danger')

    return render_template('reset_password.html')

# ============================================================================
# LOGOUT
# ============================================================================

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))