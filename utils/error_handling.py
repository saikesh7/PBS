import logging
import traceback
import sys
from datetime import datetime
from flask import request, render_template, flash, redirect, url_for  # Add request import here

# Configure logging
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app_errors.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Create logger
error_logger = logging.getLogger('app.errors')

def error_print(context, exception=None):
    """
    Logs errors with context information and optional exception details.
    
    Args:
        context (str): Description of where/what caused the error
        exception (Exception, optional): The exception object if available
    """
    try:
        # Get timestamp
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        
        # Log to error logger
        if exception:
            error_message = f"{context}: {str(exception)}"
            error_logger.error(error_message)
            error_logger.error(traceback.format_exc())
            
            # Also print to console during development
            print(f"[{timestamp}] ERROR: {error_message}")
            print(traceback.format_exc())
        else:
            error_message = f"{context}"
            error_logger.error(error_message)
            
            # Also print to console during development
            print(f"[{timestamp}] ERROR: {error_message}")
            
        # Return the error message in case it needs to be used
        return error_message
    except Exception as e:
        # Failsafe for errors in the error handler
        print(f"Error in error_print function: {str(e)}")
        print(f"Original context: {context}")
        if exception:
            print(f"Original exception: {str(exception)}")
        return f"Error logging failed: {str(e)}"

def capture_route_exceptions(func):
    """
    Decorator to capture exceptions in route functions.
    Logs the error and returns a 500 error response.
    
    Args:
        func: The route function to wrap
    
    Returns:
        The wrapped function with exception handling
    """
    from functools import wraps
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Log the error
            error_print(f"Exception in {func.__name__}", e)
            
            # Flash message to user
            flash(f"An unexpected error occurred. Please try again or contact support.", "danger")
            
            # Redirect to a safe page
            return redirect(url_for('main.index'))
    
    return wrapper

def init_error_handlers(app):
    """
    Initialize global error handlers for a Flask application.
    
    Args:
        app: Flask application instance
    """
    @app.errorhandler(404)
    def page_not_found(e):
        error_print(f"404 error: {request.path}")
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(403)
    def forbidden(e):
        error_print(f"403 error: {request.path}")
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(500)
    def internal_server_error(e):
        error_print(f"500 error: {str(e)}")
        return render_template('errors/500.html'), 500

# Additional utility functions can be added below
def log_activity(user_id, action, details=None):
    """
    Logs user activity for audit purposes.
    
    Args:
        user_id (str): The ID of the user performing the action
        action (str): The action being performed (e.g., "assign_points")
        details (dict, optional): Additional details about the action
    """
    try:
        # Create activity log
        timestamp = datetime.utcnow()
        activity_log = {
            "timestamp": timestamp,
            "user_id": user_id,
            "action": action,
            "details": details or {}
        }
        
        # In a real application, you might save this to a database
        # For now, just log it
        activity_logger = logging.getLogger('app.activity')
        activity_logger.info(f"User {user_id} performed {action}: {details}")
        
        return True
    except Exception as e:
        error_print(f"Error logging activity for user {user_id}", e)
        return False