"""
Category Validator - Automatically fixes missing categories on app startup
This ensures all dashboards display correct categories
"""

from extensions import mongo
from bson.objectid import ObjectId
from datetime import datetime
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

def validate_and_fix_categories(show_analysis=True):
    """
    Validate all category references and fix missing ones
    Runs automatically on app startup
    
    Args:
        show_analysis: If True, shows detailed analysis of categories (default: True)
    """
    try:
        logger.info("=" * 60)
        logger.info("CATEGORY VALIDATION: Checking for missing categories...")
        logger.info("=" * 60)
        
        # Get all points requests
        all_requests = list(mongo.db.points_request.find({}, {'category_id': 1, 'points': 1, 'request_notes': 1, 'submission_notes': 1}))
        
        if not all_requests:
            logger.info("No requests found. Skipping category validation.")
            return
        
        # Show analysis if requested
        if show_analysis:
            _show_category_analysis(all_requests)
        
        # Group by category_id
        category_groups = defaultdict(list)
        
        for req in all_requests:
            cat_id = req.get('category_id')
            if cat_id:
                category_groups[str(cat_id)].append(req)
        
        # Check which categories are missing
        missing_categories = []
        
        for cat_id_str, requests in category_groups.items():
            try:
                cat_id = ObjectId(cat_id_str)
            except:
                missing_categories.append({'id': cat_id_str, 'requests': requests})
                continue
            
            # Check in hr_categories
            hr_cat = mongo.db.hr_categories.find_one({"_id": cat_id})
            if hr_cat:
                continue
            
            # Check in old categories
            old_cat = mongo.db.categories.find_one({"_id": cat_id})
            if old_cat:
                continue
            
            # Category not found
            missing_categories.append({'id': cat_id_str, 'requests': requests})
        
        if not missing_categories:
            logger.info("✅ All categories are valid. No fixes needed.")
            return
        
        # Fix missing categories
        total_fixed = 0
        logger.info(f"⚠️  Found {len(missing_categories)} missing categories. Auto-fixing...")
        
        # Get reference categories
        interviews_cat = mongo.db.hr_categories.find_one({'name': 'Interviews'})
        presales_cat = mongo.db.hr_categories.find_one({'name': {'$regex': 'Pre-Sales.*End to End', '$options': 'i'}})
        client_cat = mongo.db.hr_categories.find_one({'name': 'Client Appreciation'})
        
        # Create or get Uncategorized category
        uncategorized_cat = mongo.db.hr_categories.find_one({'name': 'Uncategorized'})
        if not uncategorized_cat:
            new_category = {
                'name': 'Uncategorized',
                'description': 'Requests that need manual categorization',
                'points_per_unit': {'base': 0},
                'min_points_per_frequency': {},
                'frequency': 'per_occurrence',
                'category_status': 'active',
                'category_department': 'HR',
                'category_type': 'standard',
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'created_by': 'System (Auto-validator)'
            }
            result = mongo.db.hr_categories.insert_one(new_category)
            uncategorized_id = result.inserted_id
            logger.info(f"Created 'Uncategorized' category")
        else:
            uncategorized_id = uncategorized_cat['_id']
        
        # Fix each missing category
        for missing in missing_categories:
            cat_id_str = missing['id']
            requests = missing['requests']
            
            try:
                cat_oid = ObjectId(cat_id_str)
            except:
                continue
            
            # Analyze requests to determine best category
            points_dist = defaultdict(int)
            has_interview_notes = False
            has_presales_notes = False
            has_client_notes = False
            
            for req in requests:
                points = req.get('points', 0)
                points_dist[points] += 1
                
                notes = (req.get('request_notes') or req.get('submission_notes') or '').lower()
                if 'interview' in notes:
                    has_interview_notes = True
                if 'presales' in notes or 'rfp' in notes or 'proposal' in notes:
                    has_presales_notes = True
                if 'client' in notes or 'blue yonder' in notes or 'appreciation' in notes:
                    has_client_notes = True
            
            # Determine target category
            target_id = uncategorized_id
            target_name = 'Uncategorized'
            
            # Interview-related (100 points or interview notes)
            if (100 in points_dist or has_interview_notes) and interviews_cat:
                target_id = interviews_cat['_id']
                target_name = 'Interviews'
            
            # Pre-Sales related (500 points or presales notes)
            elif (500 in points_dist or has_presales_notes) and presales_cat:
                target_id = presales_cat['_id']
                target_name = 'Pre-Sales Contribution'
            
            # Client Appreciation (400 points or client notes)
            elif (400 in points_dist or has_client_notes) and client_cat:
                target_id = client_cat['_id']
                target_name = 'Client Appreciation'
            
            # Update all requests with this missing category
            result = mongo.db.points_request.update_many(
                {'category_id': cat_oid},
                {'$set': {'category_id': target_id}}
            )
            
            if result.modified_count > 0:
                total_fixed += result.modified_count
                logger.info(f"✅ Fixed {result.modified_count} requests: {cat_id_str[:8]}... → {target_name}")
        
        if total_fixed > 0:
            logger.info("=" * 60)
            logger.info(f"✅ CATEGORY FIX COMPLETE: {total_fixed} requests updated")
            logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Error during category validation: {str(e)}")
        # Don't crash the app if validation fails
        pass


def get_category_name_safe(category_id):
    """
    Safely get category name with fallback
    Used by all dashboards to display category names
    """
    if not category_id:
        return 'No Category'
    
    try:
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
    except:
        return 'No Category'
    
    # Try hr_categories first
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return category.get('name', 'No Category')
    
    # Fallback to old categories
    category = mongo.db.categories.find_one({"_id": category_id})
    if category:
        return category.get('name', 'No Category')
    
    return 'No Category'


def get_category_info_safe(category_id):
    """
    Safely get category info with fallback
    Returns dict with name and code
    """
    if not category_id:
        return {'name': 'No Category', 'code': 'N/A'}
    
    try:
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
    except:
        return {'name': 'No Category', 'code': 'N/A'}
    
    # Try hr_categories first
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return {
            'name': category.get('name', 'No Category'),
            'code': category.get('category_code', 'N/A')
        }
    
    # Fallback to old categories
    category = mongo.db.categories.find_one({"_id": category_id})
    if category:
        return {
            'name': category.get('name', 'No Category'),
            'code': category.get('code', 'N/A')
        }
    
    return {'name': 'No Category', 'code': 'N/A'}


def get_category_full(category_id):
    """
    Get full category object with all fields
    Returns the complete category dict or None
    Used by dashboards that need full category details
    """
    if not category_id:
        return None
    
    try:
        if isinstance(category_id, str):
            category_id = ObjectId(category_id)
    except:
        return None
    
    # Try hr_categories first
    category = mongo.db.hr_categories.find_one({"_id": category_id})
    if category:
        return category
    
    # Fallback to old categories
    category = mongo.db.categories.find_one({"_id": category_id})
    if category:
        return category
    
    return None



def _show_category_analysis(all_requests):
    """
    Show detailed analysis of category distribution
    This helps identify any issues across different systems
    """
    from collections import defaultdict
    
    logger.info("-" * 60)
    logger.info("CATEGORY ANALYSIS:")
    logger.info("-" * 60)
    
    # Count categories
    category_counts = defaultdict(int)
    missing_count = 0
    total_count = len(all_requests)
    
    for req in all_requests:
        cat_id = req.get('category_id')
        if cat_id:
            try:
                if isinstance(cat_id, str):
                    cat_id = ObjectId(cat_id)
                
                # Check if category exists
                hr_cat = mongo.db.hr_categories.find_one({"_id": cat_id})
                old_cat = mongo.db.categories.find_one({"_id": cat_id})
                
                if hr_cat:
                    cat_name = hr_cat.get('name', 'Unknown')
                    category_counts[cat_name] += 1
                elif old_cat:
                    cat_name = old_cat.get('name', 'Unknown')
                    category_counts[cat_name] += 1
                else:
                    category_counts['[MISSING CATEGORY]'] += 1
                    missing_count += 1
            except:
                category_counts['[INVALID ID]'] += 1
                missing_count += 1
        else:
            category_counts['[NO CATEGORY ID]'] += 1
            missing_count += 1
    
    # Show top categories
    logger.info(f"Total Requests: {total_count}")
    logger.info(f"Valid Categories: {total_count - missing_count}")
    logger.info(f"Missing/Invalid: {missing_count}")
    
    if missing_count > 0:
        logger.warning(f"⚠️  {missing_count} requests need category fixing!")
    
    # Show category distribution (top 10)
    logger.info("\nTop Categories:")
    sorted_cats = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
    for cat_name, count in sorted_cats[:10]:
        percentage = (count / total_count) * 100
        logger.info(f"  - {cat_name}: {count} ({percentage:.1f}%)")
    
    if len(sorted_cats) > 10:
        logger.info(f"  ... and {len(sorted_cats) - 10} more categories")
    
    logger.info("-" * 60)


def run_detailed_analysis():
    """
    Run a detailed analysis of all categories
    Can be called manually for troubleshooting
    """
    logger.info("\n" + "=" * 60)
    logger.info("DETAILED CATEGORY ANALYSIS")
    logger.info("=" * 60)
    
    # Get all requests
    all_requests = list(mongo.db.points_request.find({}, {
        'category_id': 1, 
        'points': 1, 
        'request_notes': 1, 
        'submission_notes': 1,
        'status': 1,
        'request_date': 1
    }))
    
    logger.info(f"\nTotal Requests in Database: {len(all_requests)}")
    
    # Analyze missing categories
    missing_categories = defaultdict(list)
    
    for req in all_requests:
        cat_id = req.get('category_id')
        if not cat_id:
            missing_categories['NO_CATEGORY_ID'].append(req)
            continue
        
        try:
            if isinstance(cat_id, str):
                cat_id = ObjectId(cat_id)
        except:
            missing_categories['INVALID_OBJECTID'].append(req)
            continue
        
        # Check if exists
        hr_cat = mongo.db.hr_categories.find_one({"_id": cat_id})
        old_cat = mongo.db.categories.find_one({"_id": cat_id})
        
        if not hr_cat and not old_cat:
            missing_categories[str(cat_id)].append(req)
    
    if not missing_categories:
        logger.info("✅ All categories are valid!")
        return
    
    # Show missing categories
    logger.info(f"\n⚠️  Found {len(missing_categories)} missing category groups:")
    logger.info("-" * 60)
    
    for cat_id, requests in missing_categories.items():
        logger.info(f"\nCategory ID: {cat_id}")
        logger.info(f"Affected Requests: {len(requests)}")
        
        # Analyze points distribution
        points_dist = defaultdict(int)
        status_dist = defaultdict(int)
        
        for req in requests:
            points_dist[req.get('points', 0)] += 1
            status_dist[req.get('status', 'Unknown')] += 1
        
        logger.info("  Points Distribution:")
        for points, count in sorted(points_dist.items()):
            logger.info(f"    {points} points: {count} requests")
        
        logger.info("  Status Distribution:")
        for status, count in status_dist.items():
            logger.info(f"    {status}: {count} requests")
        
        # Show sample notes
        sample_notes = []
        for req in requests[:3]:
            notes = req.get('request_notes') or req.get('submission_notes')
            if notes:
                sample_notes.append(notes[:80])
        
        if sample_notes:
            logger.info("  Sample Notes:")
            for note in sample_notes:
                logger.info(f"    - {note}...")
    
    logger.info("\n" + "=" * 60)
