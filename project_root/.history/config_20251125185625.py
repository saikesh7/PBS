class Config:
    SECRET_KEY = 'prowess_points_application'
    
    # ✅ UPDATED: Use 127.0.0.1 instead of localhost (fixes eventlet DNS issue)
    MONGO_URI = 'mongodb://127.0.0.1:27017/prowess_points_application'
    
    # Keep your email settings the same
    MAIL_SERVER = 'smtp.outlook.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'pbs@prowesssoft.com'
    MAIL_PASSWORD = 'thffnrhmbjnjlsjd'