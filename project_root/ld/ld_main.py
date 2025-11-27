from flask import Blueprint, session, redirect, url_for, flash
from bson import ObjectId
import os

# Define Blueprint
current_dir = os.path.dirname(os.path.abspath(__file__))

ld_bp = Blueprint(
    'ld', __name__,
    url_prefix='/learning-development',
    template_folder=os.path.join(current_dir, 'templates'),
    static_folder=os.path.join(current_dir, 'static'),
    static_url_path='/ld/static'
)


# Main Dashboard Router
@ld_bp.route('/dashboard')
def dashboard():
    """
    Main L&D Dashboard Router
    Redirects users based on their dashboard_access:
    - 'ld_up' -> updater_dashboard
    - 'ld_va' -> validator_dashboard
    """
    from .helpers import get_mongo, get_user_redirect
    
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
        
        # Check for L&D Updater access
        if 'ld_up' in dashboard_access or 'ld_updater' in dashboard_access:
            return redirect(url_for('ld.updater_dashboard'))
        
        # Check for L&D Validator access
        elif 'ld_va' in dashboard_access or 'ld_validator' in dashboard_access:
            return redirect(url_for('ld.validator_dashboard'))
        
        # No L&D access
        else:
            flash('You do not have permission to access L&D dashboards', 'danger')
            redirect_url = get_user_redirect(user)
            return redirect(redirect_url)
    
    except Exception:
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
