import pymongo
from datetime import datetime

# Keep your connection logic
MONGO_URI = "mongodb://prod_db:Msdhoni7@127.0.0.1:27017/pbs_db?authSource=admin"
client = pymongo.MongoClient(MONGO_URI)
db = client['test_db']

# Your data with ONLY syntax fixes (None, True, False)
user_data = {
  "name": "Akhil V2 PM3",
  "email": "akhilv2pm3@gmail.com",
  "phone": "7793920128",
  "employee_id": "V2PM3",
  "password_hash": "$2b$12$lUFy8KxfZ102KqUVZITsqOAJBPgrgfJ/.jiNBWosIE7Pn6HGyw9tO",
  "role": "Employee",
  "is_first_login": False,        # Changed false to False
  "grade": "C2",
  "department": "Management",
  "location": "India",
  "employee_level": "Mid-Level",
  "manager_id": None,             # Changed null to None
  "dp_id": None,                  # Changed null to None
  "is_active": True,              # Changed true to True
  "dashboard_access": [
 "pm",
    "hr",
    "ta_up",
    "ta_va",
    "employee_db"
  ],
  "joining_date": datetime(2020, 5, 29), # Converted to Python Date
  "exit_date": None,              # Changed null to None
  "created_at": datetime.utcnow(), # Converted to Python Date
  "updated_at": datetime.utcnow()  # Converted to Python Date
}

# The execution step (Required for the code to run)
db.users.update_one({"email": user_data["email"]}, {"$set": user_data}, upsert=True)
print("✅ User created successfully.")
