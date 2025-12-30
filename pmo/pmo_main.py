from flask import Blueprint, session, redirect, url_for, flash
from bson import ObjectId
import os

current_dir = os.path.dirname(os.path.abspath(__file__))

pmo_bp = Blueprint(
    'pmo', __name__,
    url_prefix='/pmo',
    template_folder=os.path.join(current_dir, 'templates'),
    static_folder=os.path.join(current_dir, 'static'),
    static_url_path='/pmo/static'
)

@pmo_bp.route('/dashboard')
def dashboard():
    """Main PMO Dashboard Router"""
    from .pmo_helpers import get_mongo, get_user_redirect
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
        if isinstance(dashboard_access, str):
            dashboard_access = [x.strip() for x in dashboard_access.split(',')]
        
        # Normalize to lowercase like TA does
        dashboard_access = [x.lower() for x in dashboard_access]
        
        # Check for pmo_up (lowercase like TA uses ta_up)
        if 'pmo_up' in dashboard_access:
            return redirect(url_for('pmo.updater_dashboard'))
        # Check for pmo_va (lowercase like TA uses ta_va)
        elif 'pmo_va' in dashboard_access:
            return redirect(url_for('pmo.validator_dashboard'))
        else:
            flash('You do not have permission to access PMO dashboards', 'danger')
            return redirect(get_user_redirect(user))
    
    except Exception as e:
        error_print("Error in PMO dashboard router", e)
        flash('An error occurred while loading the dashboard.', 'danger')
        return redirect(url_for('auth.login'))
