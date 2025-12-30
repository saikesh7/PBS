from flask import Blueprint, session, redirect, url_for, flash
from bson import ObjectId
import os

# Define Blueprint
current_dir = os.path.dirname(os.path.abspath(__file__))

ta_bp = Blueprint(
    'ta', __name__,
    url_prefix='/talent-acquisition',
    template_folder=os.path.join(current_dir, 'templates'),
    static_folder=os.path.join(current_dir, 'static'),
    static_url_path='/ta/static'
)


# Main Dashboard Router - ADD THIS
@ta_bp.route('/dashboard')
def dashboard():
    """
    Main TA Dashboard Router
    Redirects users based on their dashboard_access:
    - 'ta_up' -> updater_dashboard
    - 'ta_va' -> validator_dashboard
    """
    from .helpers import get_mongo, get_user_redirect
    from utils.error_handling import error_print
    
    user_id = session.get('user_id')
    
    if not user_id:
        flash('You need to log in first', 'warning')
        return redirect(url_for('auth.login'))
    
    try:
        mongo = get_mongo()
        user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('auth.login'))
        
        dashboard_access = user.get('dashboard_access', [])
        
        # Normalize dashboard_access to list
        if isinstance(dashboard_access, str):
            dashboard_access = [x.strip().lower() for x in dashboard_access.split(',')]
        else:
            dashboard_access = [x.lower() for x in dashboard_access]
        
        # Check for TA Updater access
        if 'ta_up' in dashboard_access:
            return redirect(url_for('ta.updater_dashboard'))
        
        # Check for TA Validator access
        elif 'ta_va' in dashboard_access:
            return redirect(url_for('ta.validator_dashboard'))
        
        # No TA access
        else:
            flash('You do not have permission to access TA dashboards', 'danger')
            redirect_url = get_user_redirect(user)
            return redirect(redirect_url)
    
    except Exception as e:
        error_print("Error in TA dashboard router", e)
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))