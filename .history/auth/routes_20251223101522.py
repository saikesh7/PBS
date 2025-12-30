from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from extensions import mongo, mail, bcrypt
from datetime import datetime, timedelta
import random
import re
import secrets
import string
from flask_mail import Message
from bson.objectid import ObjectId
from functools import wraps
import hashlib
import uuid
import hmac
 
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
# SECURITY CONFIGURATION
# ============================================================================
OTP_EXPIRY_MINUTES = 10
PASSWORD_MIN_LENGTH = 8
SESSION_TIMEOUT_MINUTES = 525600  # 365 days (1 year)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def validate_email_format(email):
    """Validate email format using regex"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password_strength(password):
    """
    Validate password strength:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit"
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    
    # Check for common weak passwords
    weak_passwords = ['12345678', 'password', 'Password1!', 'Admin123!']
    if password in weak_passwords:
        return False, "This password is too common. Please choose a stronger password"
    
    return True, "Password is strong"

def sanitize_input(input_string):
    """Sanitize input to prevent SQL/Script injection"""
    if not input_string:
        return input_string
    
    # Remove script tags and SQL injection patterns
    dangerous_patterns = [
        r'<script[^>]*>.*?</script>',
        r'javascript:',
        r'on\w+\s*=',
        r"'\s*OR\s*'1'\s*=\s*'1",
        r'--',
        r';DROP',
        r'UNION\s+SELECT'
    ]
    
    cleaned = input_string
    for pattern in dangerous_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    return cleaned.strip()

def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))

def generate_reset_token():
    """Generate a secure reset token"""
    return secrets.token_urlsafe(32)

def generate_session_token():
    """Generate a unique session token for tracking"""
    return str(uuid.uuid4())

def get_client_fingerprint():
    """Generate a unique fingerprint for the client"""
    user_agent = request.headers.get('User-Agent', '')
    accept_language = request.headers.get('Accept-Language', '')
    accept_encoding = request.headers.get('Accept-Encoding', '')
    
    # Create a fingerprint from browser characteristics
    fingerprint_data = f"{user_agent}|{accept_language}|{accept_encoding}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()

def create_user_session(user_id, user_data):
    """Create a new session with proper tracking"""
    session_token = generate_session_token()
    client_fingerprint = get_client_fingerprint()
    
    # Store session in database for tracking
    session_data = {
        'session_token': session_token,
        'user_id': str(user_id),
        'client_fingerprint': client_fingerprint,
        'ip_address': request.remote_addr,
        'user_agent': request.headers.get('User-Agent', ''),
        'created_at': datetime.utcnow(),
        'last_activity': datetime.utcnow(),
        'is_active': True
    }
    
    # Insert new session (no limit on concurrent sessions)
    mongo.db.user_sessions.insert_one(session_data)
    
    # Set session data
    session.clear()
    session['user_id'] = str(user_id)
    session['session_token'] = session_token
    session['client_fingerprint'] = client_fingerprint
    session['user_role'] = user_data.get('role', 'Employee')
    session['user_name'] = user_data.get('name', '')
    session['user_email'] = user_data.get('email', '')
    session['last_activity'] = datetime.utcnow().isoformat()
    
    # Make session permanent with custom lifetime
    session.permanent = True
    
    return session_token

def validate_session():
    """Validate current session against database"""
    session_token = session.get('session_token')
    user_id = session.get('user_id')
    client_fingerprint = session.get('client_fingerprint')
    
    if not session_token or not user_id:
        return False
    
    # Check if session exists in database
    db_session = mongo.db.user_sessions.find_one({
        'session_token': session_token,
        'user_id': user_id,
        'is_active': True
    })
    
    if not db_session:
        return False
    
    # Verify client fingerprint to prevent session hijacking
    current_fingerprint = get_client_fingerprint()
    if db_session['client_fingerprint'] != current_fingerprint:
        # Potential session hijacking - invalidate session
        invalidate_session(session_token)
        return False
    
    # Update last activity
    mongo.db.user_sessions.update_one(
        {'session_token': session_token},
        {'$set': {'last_activity': datetime.utcnow()}}
    )
    
    return True

def invalidate_session(session_token=None):
    """Invalidate a specific session or current session"""
    if not session_token:
        session_token = session.get('session_token')
    
    if session_token:
        mongo.db.user_sessions.update_one(
            {'session_token': session_token},
            {'$set': {'is_active': False, 'ended_at': datetime.utcnow()}}
        )

def check_rate_limit(email, action_type, max_attempts, time_window_minutes):
    """
    Check if user has exceeded rate limit for a specific action
    action_type: 'login', 'otp_request', 'otp_verify'
    """
    now = datetime.utcnow()
    time_threshold = now - timedelta(minutes=time_window_minutes)
    
    # Count attempts in the time window
    attempts = mongo.db.rate_limits.count_documents({
        'email': email,
        'action_type': action_type,
        'timestamp': {'$gte': time_threshold}
    })
    
    return attempts < max_attempts

def log_rate_limit_attempt(email, action_type):
    """Log an attempt for rate limiting"""
    mongo.db.rate_limits.insert_one({
        'email': email,
        'action_type': action_type,
        'timestamp': datetime.utcnow()
    })

def is_account_locked(email):
    """Check if account is locked due to failed login attempts"""
    user = mongo.db.users.find_one({'email': email})
    if not user:
        return False
    
    locked_until = user.get('locked_until')
    if locked_until and locked_until > datetime.utcnow():
        return True
    
    # If lock has expired, clear it
    if locked_until and locked_until <= datetime.utcnow():
        mongo.db.users.update_one(
            {'email': email},
            {'$unset': {'locked_until': '', 'failed_login_attempts': ''}}
        )
    
    return False

def increment_failed_login(email):
    """Increment failed login attempts (tracking only, no locking)"""
    user = mongo.db.users.find_one({'email': email})
    if not user:
        return
    
    failed_attempts = user.get('failed_login_attempts', 0) + 1
    
    mongo.db.users.update_one(
        {'email': email},
        {'$set': {'failed_login_attempts': failed_attempts}}
    )

def reset_failed_login(email):
    """Reset failed login attempts on successful login"""
    mongo.db.users.update_one(
        {'email': email},
        {'$unset': {'failed_login_attempts': '', 'locked_until': ''}}
    )

def check_session_timeout():
    """Check if session has timed out"""
    last_activity = session.get('last_activity')
    if last_activity:
        last_activity_time = datetime.fromisoformat(last_activity)
        if datetime.utcnow() - last_activity_time > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
            return True
    return False

def update_session_activity():
    """Update last activity timestamp in session"""
    session['last_activity'] = datetime.utcnow().isoformat()

def send_otp_email(email, otp):
    """Send OTP via email"""
    try:
        msg = Message(
            subject='PBS - Password Reset OTP',
            sender='pbs@prowesssoft.com',
            recipients=[email]
        )
        msg.html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background: #f8f9fa; padding: 30px; border-radius: 10px;">
                    <h2 style="color: #667eea;">Password Reset Request</h2>
                    <p>You have requested to reset your password for PBS System.</p>
                    <div style="background: white; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <p style="font-size: 14px; color: #666;">Your OTP is:</p>
                        <h1 style="color: #667eea; letter-spacing: 5px; font-size: 36px; margin: 10px 0;">{otp}</h1>
                    </div>
                    <p style="color: #666; font-size: 14px;">This OTP will expire in {OTP_EXPIRY_MINUTES} minutes.</p>
                    <p style="color: #666; font-size: 14px;">If you didn't request this, please ignore this email.</p>
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    <p style="color: #999; font-size: 12px;">© 2025 PROWESSSOFT - PBS System</p>
                </div>
            </body>
        </html>
        """
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def check_password_history(user_id, new_password):
    """Check if password was used before (last 3 passwords)"""
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return True
    
    password_history = user.get('password_history', [])
    
    # Check against last 3 passwords
    for old_hash in password_history[-3:]:
        if bcrypt.check_password_hash(old_hash, new_password):
            return False
    
    return True

def add_to_password_history(user_id, password_hash):
    """Add password to history (keep last 5)"""
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return
    
    password_history = user.get('password_history', [])
    password_history.append(password_hash)
    
    # Keep only last 5 passwords
    if len(password_history) > 5:
        password_history = password_history[-5:]
    
    mongo.db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$set': {'password_history': password_history}}
    )
 
 
# ============================================================================
# LOGIN ROUTE - SIMPLIFIED TO ALWAYS GO TO EMPLOYEE DASHBOARD
# ============================================================================
 
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # ============================================================
        # STEP 1: Input Validation & Sanitization
        # ============================================================
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember_me = request.form.get('remember', '') == 'on'
        
        # Sanitize inputs
        email = sanitize_input(email)
        
        # Validate email format
        if not validate_email_format(email):
            flash('Invalid email format. Please enter a valid email address.', 'danger')
            return render_template('login.html')
        
        # Check for empty password
        if not password:
            flash('Password is required.', 'danger')
            return render_template('login.html')
        
        # ============================================================
        # STEP 2: User Authentication
        # ============================================================
        user = mongo.db.users.find_one({'email': email})
        
        if not user:
            # Don't reveal if user exists or not (security best practice)
            flash('Invalid credentials. Please check your email or password.', 'danger')
            return render_template('login.html')
        
        # Check if user is deactivated/blocked
        if user.get('status') == 'deactivated' or user.get('is_blocked', False):
            flash('Your account has been deactivated. Please contact HR or support.', 'danger')
            return render_template('login.html')
        
        # Verify password
        if not bcrypt.check_password_hash(user['password_hash'], password):
            # Track failed attempt (for monitoring only)
            increment_failed_login(email)
            flash('Invalid credentials. Please check your email or password.', 'danger')
            return render_template('login.html')
        
        # ============================================================
        # STEP 3: Successful Login - Create Secure Session
        # ============================================================
        # Reset failed login attempts
        reset_failed_login(email)
        
        # Create secure session with tracking
        create_user_session(user['_id'], user)
        
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
        
        # Update last login timestamp
        mongo.db.users.update_one(
            {'_id': user['_id']},
            {'$set': {'last_login': datetime.utcnow()}}
        )
        
        # ============================================================
        # STEP 4: Handle First Login Reset
        # ============================================================
        if user.get('is_first_login', True):
            response = make_response(redirect(url_for('auth.reset_password')))
            # Set secure cookie flags
            response.set_cookie('session_secure', 'true', httponly=True, secure=True, samesite='Lax')
            return response
        
        # ============================================================
        # STEP 5: Redirect to Dashboard
        # ============================================================
        session['justLoggedIn'] = True
        flash('Login successful. Welcome back!', 'success')
        
        response = make_response(redirect(url_for('employee_dashboard.dashboard')))
        # Set secure cookie flags for production
        response.set_cookie('session_secure', 'true', httponly=True, secure=True, samesite='Lax')
        
        # ============================================================
        # STEP 6: Handle Remember Me
        # ============================================================
        if remember_me:
            # Store email and encrypted password in cookies (30 days)
            response.set_cookie('remembered_email', email, max_age=30*24*60*60, httponly=True, samesite='Lax')
            # Store a simple flag that password was remembered
            response.set_cookie('remembered_password', password, max_age=30*24*60*60, httponly=True, samesite='Lax')
        else:
            # Clear remember me cookies if unchecked
            response.delete_cookie('remembered_email')
            response.delete_cookie('remembered_password')
        
        return response
    
    # ============================================================
    # GET Request: Check for remembered credentials
    # ============================================================
    remembered_email = request.cookies.get('remembered_email', '')
    remembered_password = request.cookies.get('remembered_password', '')
    
    return render_template('login.html', 
                         remembered_email=remembered_email,
                         remembered_password=remembered_password)
 
 
# ============================================================================
# RESET PASSWORD FOR FIRST-TIME LOGIN
# ============================================================================
 
@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    user_id = session.get('user_id')
    if not user_id:
        flash('Session expired. Please login again.', 'danger')
        return redirect(url_for('auth.login'))
   
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found. Please login again.', 'danger')
        return redirect(url_for('auth.login'))
 
    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # ============================================================
        # STEP 1: Validate Password Match
        # ============================================================
        if new_password != confirm_password:
            flash('Passwords do not match. Please try again.', 'danger')
            return render_template('reset_password.html')
        
        # ============================================================
        # STEP 2: Validate Password Strength
        # ============================================================
        is_strong, message = validate_password_strength(new_password)
        if not is_strong:
            flash(message, 'danger')
            return render_template('reset_password.html')
        
        # ============================================================
        # STEP 3: Check Password History
        # ============================================================
        if not check_password_history(user_id, new_password):
            flash('You cannot reuse your previous passwords. Please choose a different password.', 'danger')
            return render_template('reset_password.html')
        
        # ============================================================
        # STEP 4: Update Password
        # ============================================================
        password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
        
        # Add old password to history
        if user.get('password_hash'):
            add_to_password_history(user_id, user['password_hash'])
        
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {
                'password_hash': password_hash,
                'is_first_login': False,
                'password_changed_at': datetime.utcnow()
            }}
        )
       
        flash('Password reset successful. Please log in with your new password.', 'success')
        session.clear()
        return redirect(url_for('auth.login'))
 
    return render_template('reset_password.html')
 
# ============================================================================
# FORGOT PASSWORD
# ============================================================================
 
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        # ============================================================
        # STEP 1: Validate Email Format
        # ============================================================
        email = sanitize_input(email)
        if not validate_email_format(email):
            flash('Invalid email format. Please enter a valid email address.', 'danger')
            return render_template('forgot_password.html')
        
        # ============================================================
        # STEP 2: Check if User Exists (Don't reveal if not)
        # ============================================================
        user = mongo.db.users.find_one({'email': email})
        
        # Always show same message for security (don't reveal if user exists)
        if user:
            # ============================================================
            # STEP 3: Generate and Store OTP
            # ============================================================
            otp = generate_otp()
            otp_expiry = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
            
            # Store OTP in database
            mongo.db.users.update_one(
                {'email': email},
                {'$set': {
                    'reset_otp': otp,
                    'reset_otp_expiry': otp_expiry,
                    'otp_attempts': 0
                }}
            )
            
            # ============================================================
            # STEP 4: Send OTP via Email
            # ============================================================
            if send_otp_email(email, otp):
                flash('A One-Time Password (OTP) has been sent to your registered email address.', 'success')
                # Store email in session for OTP verification
                session['reset_email'] = email
                return redirect(url_for('auth.verify_otp'))
            else:
                flash('Failed to send OTP. Please try again or contact support.', 'danger')
                return render_template('forgot_password.html')
        else:
            # Don't reveal that user doesn't exist
            flash('If your email is registered, a One-Time Password (OTP) has been sent to your email address. Please check your inbox.', 'info')
            return render_template('forgot_password.html')
    
    return render_template('forgot_password.html')
 
@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('reset_email')
    if not email:
        flash('Your session has expired. Please request a new OTP to continue with password reset.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()
        
        # ============================================================
        # STEP 1: Validate OTP Format
        # ============================================================
        if not entered_otp or len(entered_otp) != 6 or not entered_otp.isdigit():
            flash('Invalid OTP format. Please enter a 6-digit OTP.', 'danger')
            return render_template('verify_otp.html')
        
        # ============================================================
        # STEP 2: Verify OTP
        # ============================================================
        user = mongo.db.users.find_one({'email': email})
        
        if not user:
            flash('User not found. Please try again.', 'danger')
            return redirect(url_for('auth.forgot_password'))
        
        stored_otp = user.get('reset_otp')
        otp_expiry = user.get('reset_otp_expiry')
        otp_attempts = user.get('otp_attempts', 0)
        
        # Check if OTP exists
        if not stored_otp or not otp_expiry:
            flash('No OTP found. Please request a new OTP.', 'danger')
            return redirect(url_for('auth.forgot_password'))
        
        # Check if OTP has expired
        if datetime.utcnow() > otp_expiry:
            flash(f'OTP has expired. Please request a new OTP. (Valid for {OTP_EXPIRY_MINUTES} minutes)', 'danger')
            # Clear expired OTP
            mongo.db.users.update_one(
                {'email': email},
                {'$unset': {'reset_otp': '', 'reset_otp_expiry': '', 'otp_attempts': ''}}
            )
            return redirect(url_for('auth.forgot_password'))
        
        # Check OTP attempts (max 5 attempts)
        if otp_attempts >= 5:
            flash('Maximum OTP verification attempts reached. Please request a new OTP.', 'danger')
            mongo.db.users.update_one(
                {'email': email},
                {'$unset': {'reset_otp': '', 'reset_otp_expiry': '', 'otp_attempts': ''}}
            )
            session.pop('reset_email', None)
            return redirect(url_for('auth.forgot_password'))
        
        # Verify OTP
        if entered_otp == stored_otp:
            # OTP is correct - allow password reset
            session['reset_user_id'] = str(user['_id'])
            session['otp_verified'] = True
            
            # Clear OTP from database (single use)
            mongo.db.users.update_one(
                {'email': email},
                {'$unset': {'reset_otp': '', 'reset_otp_expiry': '', 'otp_attempts': ''}}
            )
            
            flash('OTP verified successfully. Please set your new password.', 'success')
            return redirect(url_for('auth.forgot_reset_password'))
        else:
            # Incorrect OTP - increment attempts
            mongo.db.users.update_one(
                {'email': email},
                {'$inc': {'otp_attempts': 1}}
            )
            
            attempts_left = 5 - (otp_attempts + 1)
            if attempts_left > 0:
                flash(f'Incorrect OTP. You have {attempts_left} attempt(s) remaining.', 'danger')
            else:
                flash('Maximum OTP verification attempts reached. Please request a new OTP.', 'danger')
                mongo.db.users.update_one(
                    {'email': email},
                    {'$unset': {'reset_otp': '', 'reset_otp_expiry': '', 'otp_attempts': ''}}
                )
                session.pop('reset_email', None)
                return redirect(url_for('auth.forgot_password'))
            
            return render_template('verify_otp.html')
    
    return render_template('verify_otp.html')

@auth_bp.route('/forgot-reset-password', methods=['GET', 'POST'])
def forgot_reset_password():
    user_id = session.get('reset_user_id')
    otp_verified = session.get('otp_verified')
    
    if not user_id or not otp_verified:
        flash('Your session has expired or OTP verification is required. Please start the password reset process again.', 'warning')
        return redirect(url_for('auth.forgot_password'))
   
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User account not found. Please contact support if this issue persists.', 'danger')
        return redirect(url_for('auth.login'))
 
    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # ============================================================
        # STEP 1: Validate Password Match
        # ============================================================
        if new_password != confirm_password:
            flash('Passwords do not match. Please try again.', 'danger')
            return render_template('forgot_reset_password.html')
        
        # ============================================================
        # STEP 2: Validate Password Strength
        # ============================================================
        is_strong, message = validate_password_strength(new_password)
        if not is_strong:
            flash(message, 'danger')
            return render_template('forgot_reset_password.html')
        
        # ============================================================
        # STEP 3: Check Password History
        # ============================================================
        if not check_password_history(user_id, new_password):
            flash('You cannot reuse your previous passwords. Please choose a different password.', 'danger')
            return render_template('forgot_reset_password.html')
        
        # ============================================================
        # STEP 4: Update Password
        # ============================================================
        password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
        
        # Add old password to history
        if user.get('password_hash'):
            add_to_password_history(user_id, user['password_hash'])
        
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {
                'password_hash': password_hash,
                'password_changed_at': datetime.utcnow()
            }}
        )
       
        session.clear()
        flash('Password reset successful. Please log in with your new password.', 'success')
        return redirect(url_for('auth.login'))
 
    return render_template('forgot_reset_password.html')
 
# ============================================================================
# LOGOUT
# ============================================================================
 
@auth_bp.route('/logout')
def logout():
    # ============================================================
    # STEP 1: Invalidate Session in Database
    # ============================================================
    session_token = session.get('session_token')
    user_email = session.get('user_email')
    
    # Invalidate session in database
    if session_token:
        invalidate_session(session_token)
    
    # ============================================================
    # STEP 2: Clear Session Data
    # ============================================================
    session.clear()
    
    flash('You have been logged out successfully.', 'info')
    
    # ============================================================
    # STEP 3: Redirect to Login with Cache Control
    # ============================================================
    response = make_response(redirect(url_for('auth.login')))
    
    # Prevent browser back button after logout
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Delete secure cookie
    response.delete_cookie('session_secure')
    
    # Note: We keep remember me cookies even after logout
    # so user can login again easily if they want
    
    return response

# ============================================================================
# SESSION TIMEOUT MIDDLEWARE (Add to before_request)
# ============================================================================
@auth_bp.before_app_request
def check_session_validity():
    """Check session timeout and validity before each request"""
    # Skip check for auth routes (login, logout, forgot password, etc.)
    if request.endpoint and request.endpoint.startswith('auth.'):
        return
    
    # Skip check for static files
    if request.endpoint and request.endpoint == 'static':
        return
    
    # Check if user is logged in
    if 'user_id' in session:
        # Initialize last_activity if not present (for existing sessions)
        if 'last_activity' not in session:
            update_session_activity()
            return
        
        # Validate session against database (prevents session hijacking)
        if not validate_session():
            session.clear()
            flash('Your session is invalid or has been terminated. Please login again.', 'warning')
            return redirect(url_for('auth.login'))
        
        # Check session timeout
        if check_session_timeout():
            invalidate_session()
            session.clear()
            flash('Your session has expired due to inactivity. Please login again.', 'warning')
            return redirect(url_for('auth.login'))
        
        # Update last activity
        update_session_activity()

# ============================================================================
# SECURITY HEADERS MIDDLEWARE
# ============================================================================
@auth_bp.after_app_request
def add_security_headers(response):
    """Add security headers to all responses"""
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'DENY'
    
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # Enable XSS protection
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Strict Transport Security (HTTPS only)
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Content Security Policy
    response.headers['Content-Security-Policy'] = "default-src 'self' https:; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://code.jquery.com https://cdn.datatables.net https://cdn.socket.io; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com https://cdn.datatables.net; font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; img-src 'self' data: https:;"
    
    # Referrer Policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Permissions Policy
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    
    return response