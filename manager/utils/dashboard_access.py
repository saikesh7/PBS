"""Dashboard Access Control Utility"""

from functools import wraps
from flask import session, redirect, url_for, flash
from bson import ObjectId
from dashboard_config import get_redirect_for_unauthorized_user


def get_mongo():
    """Get mongo instance"""
    from app import mongo
    return mongo


def require_dashboard_access(required_dashboard_names):
    """
    Decorator to require specific dashboard access
    
    Usage:
        @require_dashboard_access('Marketing - Updater')
        @require_dashboard_access(['Marketing - Updater', 'Marketing - Validator'])
    """
    if isinstance(required_dashboard_names, str):
        required_dashboard_names = [required_dashboard_names]
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
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
                
                # Check if user has access
                user_dashboards = user.get('dashboard_access', [])
                has_access = any(dash in user_dashboards for dash in required_dashboard_names)
                
                if not has_access:
                    flash('You do not have permission to access this page', 'danger')
                    redirect_url = get_redirect_for_unauthorized_user(user)
                    return redirect(redirect_url)
                
                return f(*args, **kwargs)
                
            except Exception as e:
                print(f"Error in dashboard access check: {e}")
                flash('An error occurred. Please try again.', 'danger')
                return redirect(url_for('auth.login'))
        
        return decorated_function
    return decorator