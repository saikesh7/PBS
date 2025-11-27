# ✅ CRITICAL: Monkey patch MUST be FIRST
import eventlet
eventlet.monkey_patch()

from flask import Flask, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
from config import Config
from extensions import mongo, mail, bcrypt
from auth.routes import auth_bp
from central.routes import central_bp
from manager.pmarch import pm_arch_bp
from manager.market_manager import market_manager_bp

from employee.employee_dashboard import employee_dashboard_bp
from employee.employee_leaderboard import employee_leaderboard_bp
from employee.employee_history import employee_history_bp
from employee.employee_attachments import employee_attachments_bp
from employee.employee_filters import employee_filters_bp
from employee.employee_api import employee_api_bp
from employee.employee_notifications import employee_notifications_bp
from employee.employee_raise_request import employee_raise_request_bp
from employee.employee_points_total import employee_points_total_bp

from hr.hr_registration import hr_registration_bp
from hr.hr_analytics import hr_analytics_bp
from hr.hr_employee_management import hr_employee_mgmt_bp
from hr.hr_points_management import hr_points_mgmt_bp
from hr.hr_rr_review import hr_rr_review_bp
from hr.hr_categories import hr_categories_bp

from pm.pm_main import pm_bp
from ta import ta_bp
from pmo import pmo_bp
from presales.presales_main import presales_bp
from pmarch.pmarch_main import pmarch_bp as pm_arch_bp
# ✅ IMPORT REDIS SERVICES
from services.redis_service import redis_service
from services.socketio_service import SocketIORealtimeService


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

    app.register_blueprint(employee_dashboard_bp)
    app.register_blueprint(employee_leaderboard_bp)
    app.register_blueprint(employee_history_bp)
    app.register_blueprint(employee_attachments_bp)
    app.register_blueprint(employee_filters_bp)
    app.register_blueprint(employee_api_bp)
    app.register_blueprint(employee_notifications_bp)
    app.register_blueprint(employee_raise_request_bp)
    app.register_blueprint(employee_points_total_bp)

    app.register_blueprint(pm_bp)
    app.register_blueprint(ta_bp)


    app.register_blueprint(presales_bp)

    app.register_blueprint(pmo_bp)

    # ✅ INITIALIZE SOCKETIO SERVICE
    socketio_service = SocketIORealtimeService(socketio, redis_service)
    
    # ✅ SOCKETIO EVENT HANDLERS
    @socketio.on('connect')
    def handle_connect():
        print("🔌 Client connected")
    
    @socketio.on('register_user')
    def handle_register_user(data):
        user_id = data.get('user_id')
        user_type = data.get('user_type')
        role = data.get('role')
        
        print(f"👤 Registering: ID={user_id}, Type={user_type}, Role={role}")
        
        if user_id and user_type:
            socketio_service.handle_user_connect(user_id, user_type, role)
    
    @socketio.on('disconnect')
    def handle_disconnect():
        print("❌ Client disconnected")
    
    @socketio.on('ping')
    def handle_ping():
        emit('pong', {'status': 'ok'})
    
    # ✅ START REDIS LISTENER
    try:
        socketio_service.start_listener()
        print("✅ Redis listener started successfully")
    except Exception as e:
        print(f"❌ Failed to start Redis listener: {e}")
        import traceback
        traceback.print_exc()

    return app, socketio


# CREATE APP
app, socketio = create_app()


if __name__ == '__main__':
    print("=" * 60)
    print("=== PBS APPLICATION WITH REAL-TIME UPDATES ===")
    print("=" * 60)
    print("📡 Real-time Updates: ENABLED")
    print("🔴 Redis Pub/Sub: ACTIVE")
    print("🔌 SocketIO: LISTENING")
    print("🌐 Server: http://0.0.0.0:3500")
    print("=" * 60)
    
    # ✅ DISABLE RELOADER TO PREVENT DOUBLE STARTUP
    socketio.run(
        app,
        host='0.0.0.0',
        port=3500,
        debug=True,
        use_reloader=False  # ✅ ADD THIS LINE
    )