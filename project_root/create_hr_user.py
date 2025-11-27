from app import create_app
from extensions import mongo, bcrypt
from datetime import datetime

app = create_app()

with app.app_context():
    # Check if user already exists
    existing_user = mongo.db.users.find_one({"email": "shaikafridi557@gmail.com"})
    
    if not existing_user:
        hr_user = {
            "name": "Subbarao 67",
            "email": "emp@gmail.com",
            "phone": "9849181039",
            "employee_id": "E2222",
            "password_hash": bcrypt.generate_password_hash("123").decode("utf-8"),
            "role": "Employee",
            "is_first_login": True,
            "joining_date": datetime.now(),
            "exit_date": None
        }
        
        result = mongo.db.users.insert_one(hr_user)
    else:
        pass