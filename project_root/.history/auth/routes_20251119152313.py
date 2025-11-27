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
VALID_DASHBOARDS = ['pm', 'pmo', 'pmo_up', 'pmo_va', 'pm_arch', 'ta_va', 'ta_up', 'ld_up','ld_va', 'marketing', 'presales', 'central', 'hr','dp', 'dp_dashboard','hr_va','hr_up']

# ============================================================================
# HELPER FUNCTION - GENERATE OTP
# ============================================================================
def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

# ============================================================================
# HELPER FUNCTION - SEND OTP EMAIL
# ============================================================================
def send_otp_email(email, otp, purpose="login"):
    """Send OTP via email"""
    try:
        subject = f"Your OTP for {purpose.title()}"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f4f4f4;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h2 style="color: #1e40af; text-align: center;">PBS System - OTP Verification</h2>
                <p style="font-size: 16px; color: #333;">Hello,</p>
                <p style="font-size: 16px; color: #333;">Your OTP for {purpose} is:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <span style="font-size: 32px; font-weight: bold; color: #1e40af; letter-spacing: 5px; padding: 15px 30px; background-color: #e0e7ff; border-radius: 8px; display: inline-block;">{otp}</span>
                </div>
                <p style="font-size: 14px; color: #666;">This OTP is valid for 5 minutes.</p>
                <p style="font-size: 14px; color: #666;">If you didn't request this, please ignore this email.</p>
                <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;">
                <p style="font-size: 12px; color: #999; text-align: center;">© 2025 PROWESSSOFT | PBS System</p>
            </div>
        </body>
        </html>
        """
        
        msg = Message(
            subject=subject, 
            sender='pbs@prowesssoft.com',  # Add sender email
            recipients=[email], 
            html=body
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending OTP email: {str(e)}")
        return False


# ============================================================================
# LOGIN ROUTE - WITH OTP VERIFICATION
# ============================================================================

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = mongo.db.users.find_one({'email': email})

        if user and bcrypt.check_password_hash(user['password_hash'], password):
            # Generate OTP and store in session
            otp = generate_otp()
            otp_expiry = datetime.now() + timedelta(minutes=5)
            
            # Store OTP details in session temporarily
            session['pending_login'] = {
                'user_id': str(user['_id']),
                'otp': otp,
                'otp_expiry': otp_expiry.isoformat(),
                'email': email
            }
            
            # Send OTP via email
            if send_otp_email(email, otp, purpose="login"):
                flash('OTP has been sent to your email. Please verify to continue.', 'info')
                return redirect(url_for('auth.verify_login_otp'))
            else:
                flash('Failed to send OTP. Please try again.', 'danger')
        else:
            # Invalid credentials
            flash('Invalid credentials. Please check your email or password.', 'danger')

    return render_template('login.html')

# ============================================================================
# VERIFY LOGIN OTP
# ============================================================================

@auth_bp.route('/verify-login-otp', methods=['GET', 'POST'])
def verify_login_otp():
    # Check if there's a pending login
    if 'pending_login' not in session:
        flash('No pending login. Please login first.', 'warning')
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()
        pending = session['pending_login']
        
        print(f"DEBUG: Entered OTP: {entered_otp}")
        print(f"DEBUG: Expected OTP: {pending['otp']}")
        
        # Check if OTP has expired
        otp_expiry = datetime.fromisoformat(pending['otp_expiry'])
        if datetime.now() > otp_expiry:
            session.pop('pending_login', None)
            flash('OTP has expired. Please login again.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Verify OTP
        if entered_otp == pending['otp']:
            # OTP is correct, complete the login
            user_id = pending['user_id']
            user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            
            if user:
                # Clear pending login
                session.pop('pending_login', None)
                
                # Set up user session
                session.clear()
                session['user_id'] = str(user['_id'])
                session['user_role'] = user.get('role', 'Employee')
                session['user_name'] = user.get('name', '')
                session['user_email'] = user.get('email', '')

                # Normalize dashboard access list
                dashboard_access = user.get('dashboard_access', [])
                
                if isinstance(dashboard_access, str):
                    dashboard_access = [x.strip().lower() for x in dashboard_access.split(',') if x.strip()]
                elif isinstance(dashboard_access, list):
                    dashboard_access = [x.strip().lower() for x in dashboard_access if isinstance(x, str) and x.strip()]
                else:
                    dashboard_access = []
                
                dashboard_access = [d for d in dashboard_access if d in VALID_DASHBOARDS]
                session['dashboard_access'] = dashboard_access

                print(f"DEBUG: Login successful for user: {user.get('email')}")
                print(f"DEBUG: Redirecting to employee dashboard")

                # Handle first login reset
                if user.get('is_first_login', True):
                    return redirect(url_for('auth.reset_password'))

                # Redirect to Employee Dashboard
                session['justLoggedIn'] = True
                flash('Login successful. Welcome back!', 'success')
                return redirect(url_for('employee_dashboard.dashboard'))
        else:
            print(f"DEBUG: OTP mismatch - entered: '{entered_otp}', expected: '{pending['otp']}'")
            flash('Invalid OTP. Please try again.', 'danger')
    
    return render_template('otp.html', 
                         email=session['pending_login']['email'],
                         resend_url=url_for('auth.resend_login_otp'))

# ============================================================================
# RESEND LOGIN OTP
# ============================================================================

@auth_bp.route('/resend-login-otp', methods=['POST'])
def resend_login_otp():
    if 'pending_login' not in session:
        flash('No pending login. Please login first.', 'warning')
        return redirect(url_for('auth.login'))
    
    # Generate new OTP
    otp = generate_otp()
    otp_expiry = datetime.now() + timedelta(minutes=5)
    
    # Update session
    session['pending_login']['otp'] = otp
    session['pending_login']['otp_expiry'] = otp_expiry.isoformat()
    
    # Send new OTP
    email = session['pending_login']['email']
    if send_otp_email(email, otp, purpose="login"):
        flash('New OTP has been sent to your email.', 'success')
    else:
        flash('Failed to send OTP. Please try again.', 'danger')
    
    return redirect(url_for('auth.verify_login_otp'))


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
# FORGOT PASSWORD - WITH OTP VERIFICATION
# ============================================================================

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = mongo.db.users.find_one({'email': email})
        
        if user:
            # Generate OTP
            otp = generate_otp()
            otp_expiry = datetime.now() + timedelta(minutes=5)
            
            # Store OTP details in session
            session['password_reset'] = {
                'user_id': str(user['_id']),
                'otp': otp,
                'otp_expiry': otp_expiry.isoformat(),
                'email': email
            }
            
            # Send OTP via email
            if send_otp_email(email, otp, purpose="password reset"):
                flash('OTP has been sent to your email. Please verify to reset your password.', 'info')
                return redirect(url_for('auth.verify_reset_otp'))
            else:
                flash('Failed to send OTP. Please try again.', 'danger')
        else:
            # For security, show same message even if email not found
            flash('If your email is registered, an OTP will be sent.', 'info')
    
    return render_template('forgot_password.html')

# ============================================================================
# VERIFY PASSWORD RESET OTP
# ============================================================================

@auth_bp.route('/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    # Check if there's a pending password reset
    if 'password_reset' not in session:
        flash('No pending password reset. Please try again.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()
        pending = session['password_reset']
        
        # Check if OTP has expired
        otp_expiry = datetime.fromisoformat(pending['otp_expiry'])
        if datetime.now() > otp_expiry:
            session.pop('password_reset', None)
            flash('OTP has expired. Please try again.', 'danger')
            return redirect(url_for('auth.forgot_password'))
        
        # Verify OTP
        if entered_otp == pending['otp']:
            # OTP is correct, allow password reset
            session['reset_user_id'] = pending['user_id']
            session.pop('password_reset', None)
            flash('OTP verified. Please enter your new password.', 'success')
            return redirect(url_for('auth.forgot_reset_password'))
        else:
            flash('Invalid OTP. Please try again.', 'danger')
    
    return render_template('otp.html', 
                         email=session['password_reset']['email'],
                         resend_url=url_for('auth.resend_reset_otp'))

# ============================================================================
# RESEND PASSWORD RESET OTP
# ============================================================================

@auth_bp.route('/resend-reset-otp', methods=['POST'])
def resend_reset_otp():
    if 'password_reset' not in session:
        flash('No pending password reset. Please try again.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    
    # Generate new OTP
    otp = generate_otp()
    otp_expiry = datetime.now() + timedelta(minutes=5)
    
    # Update session
    session['password_reset']['otp'] = otp
    session['password_reset']['otp_expiry'] = otp_expiry.isoformat()
    
    # Send new OTP
    email = session['password_reset']['email']
    if send_otp_email(email, otp, purpose="password reset"):
        flash('New OTP has been sent to your email.', 'success')
    else:
        flash('Failed to send OTP. Please try again.', 'danger')
    
    return redirect(url_for('auth.verify_reset_otp'))

# ============================================================================
# RESET PASSWORD AFTER OTP VERIFICATION
# ============================================================================

@auth_bp.route('/forgot-reset-password', methods=['GET', 'POST'])
def forgot_reset_password():
    user_id = session.get('reset_user_id')
    if not user_id:
        flash('Session expired. Please try again.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found. Please try again.', 'danger')
        return redirect(url_for('auth.forgot_password'))

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
            flash('Password reset successful. Please login with your new password.', 'success')
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




