from datetime import timedelta

class Config:
    SECRET_KEY = 'prowess_points_application'

    # ✅ UPDATED: Use 127.0.0.1 instead of localhost (fixes eventlet DNS issue)
    MONGO_URI = 'mongodb://main_db:12345678@10.0.2.42:27017/admin?authSource=admin'

    # Keep your email settings the same
    MAIL_SERVER = 'smtp.outlook.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'pbs@prowesssoft.com'
    MAIL_PASSWORD = 'thffnrhmbjnjlsjd'

    # Session configuration - 1 year session timeout for "Remember me"
    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
