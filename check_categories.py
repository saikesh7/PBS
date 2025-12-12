"""
Standalone Category Checker
Run this on any system to check category status without starting the full app

Usage:
    python check_categories.py              # Quick check
    python check_categories.py --detailed   # Detailed analysis
    python check_categories.py --fix        # Check and fix issues
"""

import sys
import os
import argparse

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from extensions import mongo
from utils.category_validator import validate_and_fix_categories, run_detailed_analysis
from bson.objectid import ObjectId
from collections import defaultdict

# Initialize Flask app
app, socketio = create_app()

def quick_check():
    """Quick category check"""
    with app.app_context():
        print("\n" + "=" * 80)
        print("QUICK CATEGORY CHECK")
        print("=" * 80)
        
        # Get all requests
        all_requests = list(mongo.db.points_request.find({}, {'category_id': 1}))
        
        print(f"\nTotal Requests: {len(all_requests)}")
        
        # Check categories
        valid_count = 0
        missing_count = 0
        
        for req in all_requests:
            cat_id = req.get('category_id')
            if not cat_id:
                missing_count += 1
                continue
            
            try:
                if isinstance(cat_id, str):
                    cat_id = ObjectId(cat_id)
                
                hr_cat = mongo.db.hr_categories.find_one({"_id": cat_id})
                old_cat = mongo.db.categories.find_one({"_id": cat_id})
                
                if hr_cat or old_cat:
                    valid_count += 1
                else:
                    missing_count += 1
            except:
                missing_count += 1
        
        print(f"Valid Categories: {valid_count}")
        print(f"Missing Categories: {missing_count}")
        
        if missing_count == 0:
            print("\n✅ SUCCESS: All categories are valid!")
        else:
            print(f"\n⚠️  WARNING: {missing_count} requests have missing categories")
            print("Run with --fix to automatically fix these issues")
        
        print("=" * 80)

def detailed_check():
    """Detailed category analysis"""
    with app.app_context():
        run_detailed_analysis()

def fix_categories():
    """Fix missing categories"""
    with app.app_context():
        print("\n" + "=" * 80)
        print("FIXING MISSING CATEGORIES")
        print("=" * 80)
        
        validate_and_fix_categories(show_analysis=True)
        
        print("\n" + "=" * 80)
        print("FIX COMPLETE")
        print("=" * 80)

def main():
    parser = argparse.ArgumentParser(
        description='Check and fix category issues in the PBS system'
    )
    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Show detailed analysis of missing categories'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Automatically fix missing categories'
    )
    
    args = parser.parse_args()
    
    if args.fix:
        fix_categories()
    elif args.detailed:
        detailed_check()
    else:
        quick_check()

if __name__ == '__main__':
    main()
