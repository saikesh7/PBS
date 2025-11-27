from datetime import datetime
from pymongo import MongoClient

# --- DB Connection ---
MONGO_URI = "mongodb://localhost:27017/your_database_name"  # Change DB name
client = MongoClient(MONGO_URI)
db = client.get_database()

def debug_print(msg):
    pass  # Debug function disabled for production

def error_print(msg, error):
    print(f"[ERROR] {msg}: {error}")

def force_initialize_categories():
    try:
        # 1) Existing categories
        existing_categories = list(db.categories.find({}, {"name": 1, "code": 1}))
        debug_print(f"Found {len(existing_categories)} existing categories")
        for cat in existing_categories:
            debug_print(f"Existing: {cat.get('name')} (code: {cat.get('code')})")

        # 2) Non-Presales categories
        base_categories = [
            {
                "name": "Value Add (Accelerator Solutions)",
                "code": "value_add",
                "description": "Rewards for innovative solutions that accelerate business value",
                "frequency": "Quarterly",
                "updated_by": "Employee",
                "validator": "PMO",
                "grade_limits": {"A1": 1, "B1": 1, "B2": 1, "C1": 2, "C2": 2, "D1": 2, "D2": 1},
                "grade_points": {"A1": 500, "B1": 500, "B2": 500, "C1": 1000, "C2": 1000, "D1": 1000, "D2": 500},
                "points_per_unit": 500
            },
            {
                "name": "Initiative (AI Adoption)",
                "code": "initiative_ai",
                "description": "Rewards for adopting and implementing AI solutions",
                "frequency": "Monthly",
                "updated_by": "Employee",
                "validator": "PMO",
                "grade_limits": {"A1": 1, "B1": 1, "B2": 1, "C1": 2, "C2": 2, "D1": 1, "D2": 1},
                "grade_points": {"A1": 750, "B1": 750, "B2": 750, "C1": 1500, "C2": 1500, "D1": 750, "D2": 750},
                "points_per_unit": 250
            },
            {
                "name": "Mentoring",
                "code": "mentoring",
                "description": "Rewards for mentoring other employees",
                "frequency": "Quarterly",
                "updated_by": "Employee",
                "validator": "PMO",
                "grade_limits": {"A1": 0, "B1": 2, "B2": 2, "C1": 4, "C2": 6, "D1": 5, "D2": 5},
                "grade_points": {"A1": 0, "B1": 500, "B2": 500, "C1": 1000, "C2": 1500, "D1": 1250, "D2": 1250},
                "points_per_unit": 250
            },
            {
                "name": "Mindshare Content (Blogs, White Papers & Community activities)",
                "code": "mindshare",
                "description": "Rewards for creating and sharing content",
                "frequency": "Quarterly",
                "updated_by": "Employee",
                "validator": "PMO",
                "grade_limits": {"A1": 1, "B1": 2, "B2": 2, "C1": 2, "C2": 2, "D1": 2, "D2": 2},
                "grade_points": {"A1": 200, "B1": 400, "B2": 400, "C1": 400, "C2": 400, "D1": 400, "D2": 400},
                "points_per_unit": 200
            }
        ]

        # 3) Updated Presales category
        presales_updated = {
            "name": "Presales/RFP",
            "code": "presales_rfp",
            "description": "Rewards for presales and RFP support activities",
            "frequency": "Quarterly",
            "updated_by": "Employee",
            "validator": "PMO",
            "grade_limits": {"A1": 1, "B1": 1, "B2": 1, "C1": 2, "C2": 2, "D1": 2, "D2": 2},
            "grade_points": {"A1": 300, "B1": 300, "B2": 300, "C1": 600, "C2": 600, "D1": 600, "D2": 600},
            "points_per_unit": 300,
            "contribution_types": [
                {"key": "end_to_end", "label": "Pre-Sales contribution (End to end with ownership)", "points_per_unit": 500},
                {"key": "partly", "label": "Pre-Sales contribution (Partly)", "points_per_unit": 150},
                {"key": "adhoc", "label": "Pre-Sales contribution (ad-hoc support)", "points_per_unit": 50}
            ]
        }

        # 4) Add missing non-Presales categories
        existing_codes = [cat.get('code', '') for cat in existing_categories]
        categories_to_add = [cat for cat in base_categories if cat['code'] not in existing_codes]

        if categories_to_add:
            db.categories.insert_many(categories_to_add)
            debug_print(f"Added {len(categories_to_add)} new base categories")

        # 5) Upsert Presales category
        presales_result = db.categories.update_one(
            {"code": "presales_rfp"},
            {
                "$set": {
                    "name": presales_updated["name"],
                    "description": presales_updated["description"],
                    "frequency": presales_updated["frequency"],
                    "updated_by": presales_updated["updated_by"],
                    "validator": presales_updated["validator"],
                    "grade_limits": presales_updated["grade_limits"],
                    "grade_points": presales_updated["grade_points"],
                    "points_per_unit": presales_updated["points_per_unit"],
                    "contribution_types": presales_updated["contribution_types"],
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )

        if presales_result.upserted_id:
            debug_print("Inserted Presales/RFP category")
        elif presales_result.modified_count:
            debug_print("Updated Presales/RFP category")
        else:
            debug_print("Presales/RFP already up-to-date")

    except Exception as e:
        error_print("Failed to initialize categories", e)

if __name__ == "__main__":
    force_initialize_categories()
    print("Category initialization completed.")
