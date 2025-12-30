# ✅ CRITICAL: Monkey patch MUST be FIRST
import eventlet
eventlet.monkey_patch()

import logging

# Configure logging to suppress debug messages from pymongo and other libraries
logging.basicConfig(level=logging.INFO)
logging.getLogger('pymongo').setLevel(logging.WARNING)
logging.getLogger('pymongo.command').setLevel(logging.WARNING)
logging.getLogger('pymongo.connection').setLevel(logging.WARNING)
logging.getLogger('pymongo.serverSelection').setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

from flask import Flask, redirect, url_for
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from config import Config
from extensions import mongo, mail, bcrypt
from auth.routes import auth_bp
from central import central_bp
from manager.pmarch import pm_arch_bp
from manager.market_manager import market_manager_bp

from employee.employee_dashboard import employee_dashboard_bp
from employee.employee_leaderboard import employee_leaderboard_bp
from employee.employee_history import employee_history_bp
from employee.employee_attachments import employee_attachments_bp
from employee.employee_filters import employee_filters_bp
from employee.employee_api import employee_api_bp
from employee.employee_raise_request import employee_raise_request_bp
from employee.employee_points_total import employee_points_total_bp

from hr.hr_registration import hr_registration_bp
from hr.hr_analytics import hr_analytics_bp
from hr.hr_employee_management import hr_employee_mgmt_bp
from hr.hr_points_management import hr_points_mgmt_bp
from hr.hr_rr_review import hr_rr_review_bp
from hr.hr_categories import hr_categories_bp
from hr.pending_points_tracker import pending_tracker_bp

from pm.pm_main import pm_bp
from ta import ta_bp
from pmo import pmo_bp
from presales.presales_main import presales_bp
from pmarch.pmarch_main import pmarch_bp as pm_arch_bp
from services.redis_service import redis_service
from services.socketio_service import SocketIORealtimeService

from dp.dp_dashboard import dp_bp
from marketing.marketing_dashboard import marketing_dashboard_bp
from hr.hr_main import hr_bp
from ld import ld_bp
from utils.duplicate_api import duplicate_api_bp

def create_app():
    
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app)

    # Initialize extensions
    mongo.init_app(app)
    mail.init_app(app)
    bcrypt.init_app(app)
    
    # ✅ INITIALIZE SOCKETIO WITH EVENTLET
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode='eventlet',
        logger=False,
        engineio_logger=False,
        ping_timeout=60,
        ping_interval=25
    )
    
    # ✅ MAKE REDIS SERVICE AVAILABLE
    app.config['redis_service'] = redis_service
    app.config['socketio'] = socketio

    # Add root URL redirect
    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(pm_arch_bp)
   
    app.register_blueprint(market_manager_bp)
    app.register_blueprint(central_bp)

    app.register_blueprint(hr_registration_bp)
    app.register_blueprint(hr_analytics_bp)
    app.register_blueprint(hr_employee_mgmt_bp)
    app.register_blueprint(hr_points_mgmt_bp)
    app.register_blueprint(hr_rr_review_bp)
    app.register_blueprint(hr_categories_bp)
    app.register_blueprint(pending_tracker_bp)

    app.register_blueprint(employee_dashboard_bp)
    app.register_blueprint(employee_leaderboard_bp)
    app.register_blueprint(employee_history_bp)
    app.register_blueprint(employee_attachments_bp)
    app.register_blueprint(employee_filters_bp)
    app.register_blueprint(employee_api_bp)
    app.register_blueprint(employee_raise_request_bp)
    app.register_blueprint(employee_points_total_bp)

    app.register_blueprint(pm_bp)
    app.register_blueprint(ta_bp)


    app.register_blueprint(ld_bp)
    app.register_blueprint(hr_bp)


    app.register_blueprint(presales_bp)

    app.register_blueprint(pmo_bp)

    app.register_blueprint(dp_bp)
    
    app.register_blueprint(marketing_dashboard_bp)
    
    app.register_blueprint(duplicate_api_bp)

    # ✅ INITIALIZE SOCKETIO SERVICE
    socketio_service = SocketIORealtimeService(socketio, redis_service)
    
    # ✅ SOCKETIO EVENT HANDLERS
    @socketio.on('connect')
    def handle_connect():
        pass
    
    @socketio.on('register_user')
    def handle_register_user(data):
        user_id = data.get('user_id')
        user_type = data.get('user_type')
        role = data.get('role')
        
        if user_id and user_type:
            socketio_service.handle_user_connect(user_id, user_type, role)
    
    @socketio.on('disconnect')
    def handle_disconnect():
        pass
    
    @socketio.on('ping')
    def handle_ping():
        emit('pong', {'status': 'ok'})
    
    # ✅ START REDIS LISTENER
    try:
        socketio_service.start_listener()
    except Exception as e:
        import traceback
        traceback.print_exc()
    
    # ✅ VALIDATE AND FIX CATEGORIES ON STARTUP
    # This runs on EVERY system where the app is deployed
    # Shows analysis and fixes missing categories automatically
    try:
        from utils.category_validator import validate_and_fix_categories
        with app.app_context():
            # show_analysis=False to disable verbose category distribution logs
            validate_and_fix_categories(show_analysis=False)
    except Exception as e:
        import traceback
        print("⚠️  Category validation failed (non-critical):")
        traceback.print_exc()

    return app, socketio


# CREATE APP
app, socketio = create_app()


if __name__ == '__main__':
    print("=" * 60)
    print("PBS APPLICATION WITH REAL-TIME UPDATES")
    print("=" * 60)
    print("Server: http://0.0.0.0:3500")
    print("=" * 60)
    
    # ✅ DISABLE RELOADER TO PREVENT DOUBLE STARTUP
    socketio.run(
        app,
        host='0.0.0.0',
        port=3500,
        debug=False,  # Set to False to reduce verbose logging
        use_reloader=False
    )
