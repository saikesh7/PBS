"""
Duplicate Detection API
Provides endpoints for checking duplicate requests across all modules (PMO, TA, HR)
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from bson import ObjectId
from extensions import mongo
from utils.error_handling import error_print

duplicate_api_bp = Blueprint('duplicate_api', __name__, url_prefix='/api/duplicate')


def parse_date_flexibly(date_str):
    """Parse date string in multiple formats"""
    if not date_str:
        return None
    
    # Handle ISO format with time (e.g., "2025-12-05T00:00:00")
    if 'T' in str(date_str):
        try:
            # Try parsing ISO format
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            pass
    
    formats = [
        '%Y-%m-%d',
        '%d-%m-%Y',
        '%m/%d/%Y',
        '%d/%m/%Y',
        '%Y/%m/%d',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f'
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(str(date_str), fmt)
        except ValueError:
            continue
    
    return None


def _get_assigning_name(request_doc):
    """Get the name of the person who assigned/created the request"""
    try:
        # Try different fields that might contain the assigning user
        assigning_id = request_doc.get('assigned_by') or request_doc.get('created_by') or request_doc.get('updater_id')
        if assigning_id:
            assigning_user = mongo.db.users.find_one({"_id": ObjectId(assigning_id)})
            if assigning_user:
                return assigning_user.get('name', 'Unknown')
        return 'Unknown'
    except:
        return 'Unknown'


def _check_duplicate_for_record(employee_id, category_id, event_date_str):
    """
    Internal function to check if a duplicate exists
    Returns: (isDuplicate, duplicateInfo)
    """
    try:
        # Parse event date
        event_date = parse_date_flexibly(event_date_str)
        if not event_date:
            return False, None
        
        # Get employee by employee_id
        employee = mongo.db.users.find_one({"employee_id": employee_id})
        if not employee:
            return False, None
        
        # Get category - check both hr_categories and categories collections
        category = None
        try:
            category = mongo.db.hr_categories.find_one({"_id": ObjectId(category_id)})
            if not category:
                category = mongo.db.categories.find_one({"_id": ObjectId(category_id)})
        except:
            return False, None
        
        if not category:
            return False, None
        
        # Check for utilization category
        category_name = category.get('name', '').lower()
        # ✅ Check both category_code (hr_categories) and code (categories) fields
        category_code = category.get('category_code', category.get('code', '')).lower()
        is_utilization = ('utilization' in category_name or 'utlization' in category_name or 'billable' in category_name or
                         'utilization' in category_code or 'billable' in category_code)
        
        if is_utilization:
            # For utilization, check for same month
            start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 
                         else start_of_month.replace(year=start_of_month.year + 1, month=1))
            
            # ✅ FIXED: Only check points_request collection (points collection is duplicate data)
            existing_requests = list(mongo.db.points_request.find({
                "user_id": ObjectId(employee["_id"]),
                "category_id": ObjectId(category["_id"]),
                "event_date": {"$gte": start_of_month, "$lt": next_month},
                "status": {"$in": ["Approved", "Pending"]}
            }))
            
            if existing_requests:
                # ✅ Count approved and pending records (only from points_request)
                approved_count = sum(1 for req in existing_requests if req.get('status') == 'Approved')
                pending_count = sum(1 for req in existing_requests if req.get('status') == 'Pending')
                
                # ✅ Build pending details with assigning info
                pending_details = []
                for req in existing_requests:
                    if req.get('status') == 'Pending':
                        req_date = req.get('event_date')
                        pending_details.append({
                            'assignedBy': _get_assigning_name(req),
                            'eventDate': req_date.strftime('%d-%m-%Y') if req_date else 'Unknown',
                            'createdAt': req.get('created_at').strftime('%d-%m-%Y %H:%M') if req.get('created_at') else 'Unknown'
                        })
                
                # ✅ Build clear status message - show both counts for transparency
                status_parts = []
                if approved_count > 0:
                    status_parts.append(f"{approved_count} Approved")
                if pending_count > 0:
                    status_parts.append(f"{pending_count} Pending")
                status_display = " + ".join(status_parts) if status_parts else "Approved"
                
                return True, {
                    'employeeName': employee.get('name', 'Unknown'),
                    'categoryName': category.get('name', 'Unknown'),
                    'eventDate': event_date.strftime('%d-%m-%Y'),
                    'status': status_display,
                    'approvedCount': approved_count,
                    'pendingCount': pending_count,
                    'pendingDetails': pending_details,  # ✅ Add pending details with assigning info
                    'message': f'Utilization already exists for {event_date.strftime("%B %Y")} ({status_display})'
                }
        else:
            # For non-utilization, check exact date
            start_of_day = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = event_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            # ✅ FIXED: Only check points_request collection (points collection is duplicate data)
            existing_requests = list(mongo.db.points_request.find({
                "user_id": ObjectId(employee["_id"]),
                "category_id": ObjectId(category["_id"]),
                "event_date": {"$gte": start_of_day, "$lte": end_of_day},
                "status": {"$in": ["Approved", "Pending"]}
            }))
            
            if existing_requests:
                # ✅ Count approved and pending records (only from points_request)
                approved_count = sum(1 for req in existing_requests if req.get('status') == 'Approved')
                pending_count = sum(1 for req in existing_requests if req.get('status') == 'Pending')
                
                # ✅ Build pending details with assigning info
                pending_details = []
                for req in existing_requests:
                    if req.get('status') == 'Pending':
                        req_date = req.get('event_date')
                        pending_details.append({
                            'assignedBy': _get_assigning_name(req),
                            'eventDate': req_date.strftime('%d-%m-%Y') if req_date else 'Unknown',
                            'createdAt': req.get('created_at').strftime('%d-%m-%Y %H:%M') if req.get('created_at') else 'Unknown'
                        })
                
                # ✅ Build clear status message - show both counts for transparency
                status_parts = []
                if approved_count > 0:
                    status_parts.append(f"{approved_count} Approved")
                if pending_count > 0:
                    status_parts.append(f"{pending_count} Pending")
                status_display = " + ".join(status_parts) if status_parts else "Approved"
                
                return True, {
                    'employeeName': employee.get('name', 'Unknown'),
                    'categoryName': category.get('name', 'Unknown'),
                    'eventDate': event_date.strftime('%d-%m-%Y'),
                    'status': status_display,
                    'approvedCount': approved_count,
                    'pendingCount': pending_count,
                    'pendingDetails': pending_details  # ✅ Add pending details with assigning info
                }
        
        return False, None
        
    except Exception as e:
        error_print(f"Error checking duplicate: {str(e)}")
        return False, None


@duplicate_api_bp.route('/check-single', methods=['POST'])
def check_single_duplicate():
    """
    Check if a duplicate request exists for the given employee, category, and event date
    
    Request JSON:
    {
        "employee_id": "EMP123",
        "category_id": "507f1f77bcf86cd799439011",
        "event_date": "2025-12-17" or "17-12-2025"
    }
    
    Response JSON:
    {
        "isDuplicate": true/false,
        "duplicateInfo": {
            "employeeName": "John Doe",
            "categoryName": "Sports Award",
            "eventDate": "17-12-2025",
            "status": "Pending"
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'isDuplicate': False,
                'error': 'No data provided'
            }), 400
        
        employee_id = data.get('employee_id')
        category_id = data.get('category_id')
        event_date_str = data.get('event_date')
        
        # Validate required fields
        if not all([employee_id, category_id, event_date_str]):
            return jsonify({
                'isDuplicate': False,
                'error': 'Missing required fields'
            }), 400
        
        # Use internal function
        is_duplicate, duplicate_info = _check_duplicate_for_record(employee_id, category_id, event_date_str)
        
        if is_duplicate:
            return jsonify({
                'isDuplicate': True,
                'duplicateInfo': duplicate_info
            })
        else:
            return jsonify({
                'isDuplicate': False
            })
        
    except Exception as e:
        error_print(f"Error in duplicate check: {str(e)}")
        return jsonify({
            'isDuplicate': False,
            'error': 'Internal server error'
        }), 500


@duplicate_api_bp.route('/check-bulk', methods=['POST'])
def check_bulk_duplicates():
    """
    Check for duplicates in bulk upload
    
    Request JSON:
    {
        "rows": [
            {"employee_id": "EMP001", "category_id": "...", "event_date": "2025-12-17"},
            {"employee_id": "EMP002", "category_id": "...", "event_date": "2025-12-18"}
        ]
    }
    
    Response JSON:
    {
        "duplicates": [
            {
                "rowNumber": 1,
                "employeeName": "John Doe",
                "categoryName": "Sports Award",
                "eventDate": "17-12-2025",
                "status": "Pending"
            }
        ]
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'rows' not in data:
            return jsonify({
                'duplicates': [],
                'error': 'No rows provided'
            }), 400
        
        rows = data.get('rows', [])
        duplicates = []
        
        # ✅ Track unique combinations to avoid duplicate warnings for same employee+category+date
        checked_combinations = {}
        
        for idx, row in enumerate(rows):
            employee_id = row.get('employee_id')
            category_id = row.get('category_id')
            event_date = row.get('event_date')
            
            if not all([employee_id, category_id, event_date]):
                continue
            
            # ✅ Create unique key for this combination
            combo_key = f"{employee_id}_{category_id}_{event_date}"
            
            # ✅ Skip if we already checked this combination (avoid duplicate warnings)
            if combo_key in checked_combinations:
                continue
            
            is_duplicate, duplicate_info = _check_duplicate_for_record(employee_id, category_id, event_date)
            
            if is_duplicate:
                # ✅ Use row number from frontend if provided, otherwise calculate it
                duplicate_info['rowNumber'] = row.get('rowNumber', idx + 2)  # +2 for Excel header row
                # ✅ Use formatted date from frontend if provided (for display in modal)
                if row.get('eventDateFormatted'):
                    duplicate_info['eventDate'] = row.get('eventDateFormatted')
                duplicates.append(duplicate_info)
                # ✅ Mark this combination as checked
                checked_combinations[combo_key] = True
        
        return jsonify({
            'duplicates': duplicates
        })
        
    except Exception as e:
        error_print(f"Error in bulk duplicate check: {str(e)}")
        return jsonify({
            'duplicates': [],
            'error': 'Internal server error'
        }), 500


@duplicate_api_bp.route('/check-validator-action', methods=['POST'])
def check_validator_action():
    """
    Check if validator is approving/rejecting a duplicate
    
    Request JSON:
    {
        "request_id": "507f1f77bcf86cd799439011",
        "action": "approve" or "reject"
    }
    
    Response JSON:
    {
        "isDuplicate": true/false,
        "duplicateInfo": {
            "employeeName": "John Doe",
            "categoryName": "Sports Award",
            "eventDate": "17-12-2025",
            "status": "1 Approved + 3 Pending",
            "message": "This request already has an approved record"
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'isDuplicate': False,
                'error': 'No data provided'
            }), 400
        
        request_id = data.get('request_id')
        action = data.get('action', 'approve')
        
        if not request_id:
            return jsonify({
                'isDuplicate': False,
                'error': 'Missing request ID'
            }), 400
        
        # Get the request being approved/rejected
        try:
            current_request = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
        except:
            return jsonify({
                'isDuplicate': False,
                'error': 'Invalid request ID'
            }), 400
        
        if not current_request:
            return jsonify({
                'isDuplicate': False,
                'error': 'Request not found'
            }), 404
        
        # Get employee and category info
        employee = mongo.db.users.find_one({"_id": current_request.get('user_id')})
        # ✅ Check both hr_categories and categories collections
        category = mongo.db.hr_categories.find_one({"_id": current_request.get('category_id')})
        if not category:
            category = mongo.db.categories.find_one({"_id": current_request.get('category_id')})
        
        if not employee or not category:
            return jsonify({
                'isDuplicate': False
            })
        
        event_date = current_request.get('event_date')
        if not event_date:
            return jsonify({
                'isDuplicate': False
            })
        
        # Check for utilization category
        category_name = category.get('name', '').lower()
        # ✅ Check both category_code (hr_categories) and code (categories) fields
        category_code = category.get('category_code', category.get('code', '')).lower()
        is_utilization = ('utilization' in category_name or 'utlization' in category_name or 'billable' in category_name or
                         'utilization' in category_code or 'billable' in category_code)
        
        if is_utilization:
            # For utilization, check same month
            start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 
                         else start_of_month.replace(year=start_of_month.year + 1, month=1))
            
            # ✅ FIXED: Only check points_request collection (points collection is duplicate data)
            other_approved_requests = list(mongo.db.points_request.find({
                "_id": {"$ne": ObjectId(request_id)},
                "user_id": current_request.get('user_id'),
                "category_id": current_request.get('category_id'),
                "event_date": {"$gte": start_of_month, "$lt": next_month},
                "status": "Approved"  # ✅ Only check approved records
            }))
            
            # ✅ Count only from points_request (avoid double counting with points collection)
            approved_count = len(other_approved_requests)
            
            # ✅ Only show duplicate warning if there are APPROVED records (ignore pending-only)
            if approved_count > 0:
                # ✅ Show ONLY approved count (remove pending from display)
                status_display = f"{approved_count} Already Approved"
                
                # ✅ Build validator-specific message showing only approved records
                validator_message = f'This employee, category, and {event_date.strftime("%B %Y")} is already approved ({approved_count} record(s))'
                
                return jsonify({
                    'isDuplicate': True,
                    'duplicateInfo': {
                        'employeeName': employee.get('name', 'Unknown'),
                        'categoryName': category.get('name', 'Unknown'),
                        'eventDate': event_date.strftime('%d-%m-%Y'),
                        'status': status_display,
                        'approvedCount': approved_count,  # ✅ Add approved count separately
                        'pendingCount': 0,                # ✅ Hide pending count
                        'message': validator_message
                    }
                })
        else:
            # For non-utilization, check exact date
            start_of_day = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = event_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            # ✅ FIXED: Only check points_request collection (points collection is duplicate data)
            other_approved_requests = list(mongo.db.points_request.find({
                "_id": {"$ne": ObjectId(request_id)},
                "user_id": current_request.get('user_id'),
                "category_id": current_request.get('category_id'),
                "event_date": {"$gte": start_of_day, "$lte": end_of_day},
                "status": "Approved"  # ✅ Only check approved records
            }))
            
            # ✅ Count only from points_request (avoid double counting with points collection)
            approved_count = len(other_approved_requests)
            
            # ✅ Only show duplicate warning if there are APPROVED records (ignore pending-only)
            if approved_count > 0:
                # ✅ Show ONLY approved count (remove pending from display)
                status_display = f"{approved_count} Already Approved"
                
                # ✅ Build validator-specific message showing only approved records
                validator_message = f'This employee, category, and event date is already approved ({approved_count} record(s))'
                
                return jsonify({
                    'isDuplicate': True,
                    'duplicateInfo': {
                        'employeeName': employee.get('name', 'Unknown'),
                        'categoryName': category.get('name', 'Unknown'),
                        'eventDate': event_date.strftime('%d-%m-%Y'),
                        'status': status_display,
                        'approvedCount': approved_count,  # ✅ Add approved count separately
                        'pendingCount': 0,                # ✅ Hide pending count
                        'message': validator_message
                    }
                })
        
        # No duplicate found
        return jsonify({
            'isDuplicate': False
        })
        
    except Exception as e:
        error_print(f"Error in validator action check: {str(e)}")
        return jsonify({
            'isDuplicate': False,
            'error': 'Internal server error'
        }), 500


@duplicate_api_bp.route('/check-bulk-validator-action', methods=['POST'])
def check_bulk_validator_action():
    """
    Check if bulk validator actions contain duplicates
    
    Request JSON:
    {
        "request_ids": ["507f1f77bcf86cd799439011", "507f1f77bcf86cd799439012"],
        "action_type": "bulk_approve" or "bulk_reject"
    }
    
    Response JSON:
    {
        "duplicates": [
            {
                "rowNumber": 1,
                "employeeName": "John Doe",
                "categoryName": "Sports Award",
                "eventDate": "17-12-2025",
                "status": "1 Approved + 3 Pending",
                "message": "Already has an approved record"
            }
        ]
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'request_ids' not in data:
            return jsonify({
                'duplicates': [],
                'error': 'No request IDs provided'
            }), 400
        
        request_ids = data.get('request_ids', [])
        action_type = data.get('action_type', 'bulk_approve')
        
        # ✅ First, load all requests being processed
        selected_requests = []
        request_id_to_idx = {}  # Map request_id to index for row number
        for idx, request_id in enumerate(request_ids):
            try:
                req = mongo.db.points_request.find_one({"_id": ObjectId(request_id)})
                if req:
                    req['_original_idx'] = idx  # Store original index
                    selected_requests.append(req)
                    request_id_to_idx[str(req['_id'])] = idx
            except:
                continue
        
        # ✅ Track internal duplicates (duplicates within the selected requests)
        internal_duplicate_groups = {}  # key -> list of request indices
        duplicate_groups = {}
        duplicates = []
        
        # ✅ STEP 1: Find internal duplicates (same employee + category + date within selection)
        for req in selected_requests:
            employee = mongo.db.users.find_one({"_id": req.get('user_id')})
            category = mongo.db.hr_categories.find_one({"_id": req.get('category_id')})
            if not category:
                category = mongo.db.categories.find_one({"_id": req.get('category_id')})
            
            if not employee or not category:
                continue
            
            event_date = req.get('event_date')
            if not event_date:
                continue
            
            # Check for utilization category
            category_name_lower = category.get('name', '').lower()
            category_code = category.get('category_code', category.get('code', '')).lower()
            is_utilization = ('utilization' in category_name_lower or 'utlization' in category_name_lower or 
                             'billable' in category_name_lower or 'utilization' in category_code or 'billable' in category_code)
            
            if is_utilization:
                # For utilization, group by month
                start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                group_key = f"{req.get('user_id')}_{req.get('category_id')}_{start_of_month.strftime('%Y-%m')}"
            else:
                # For non-utilization, group by exact date
                start_of_day = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
                group_key = f"{req.get('user_id')}_{req.get('category_id')}_{start_of_day.strftime('%Y-%m-%d')}"
            
            if group_key not in internal_duplicate_groups:
                internal_duplicate_groups[group_key] = []
            internal_duplicate_groups[group_key].append({
                'request': req,
                'employee': employee,
                'category': category,
                'event_date': event_date,
                'idx': req['_original_idx']
            })
        
        # ✅ STEP 2: Report internal duplicates (more than 1 request with same key) AND check for existing approved
        for group_key, group_items in internal_duplicate_groups.items():
            if len(group_items) > 1:
                # Get the first item to check for existing approved records
                first_item = group_items[0]
                req = first_item['request']
                event_date = first_item['event_date']
                category = first_item['category']
                
                # Check for utilization category
                category_name_lower = category.get('name', '').lower()
                category_code = category.get('category_code', category.get('code', '')).lower()
                is_utilization = ('utilization' in category_name_lower or 'utlization' in category_name_lower or 
                                 'billable' in category_name_lower or 'utilization' in category_code or 'billable' in category_code)
                
                # Get list of selected request IDs to exclude them
                selected_ids = [ObjectId(rid) for rid in request_ids]
                
                # Check for existing approved records in database
                approved_count = 0
                if is_utilization:
                    start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 
                                 else start_of_month.replace(year=start_of_month.year + 1, month=1))
                    approved_count = mongo.db.points_request.count_documents({
                        "_id": {"$nin": selected_ids},
                        "user_id": req.get('user_id'),
                        "category_id": req.get('category_id'),
                        "event_date": {"$gte": start_of_month, "$lt": next_month},
                        "status": "Approved"
                    })
                else:
                    start_of_day = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_of_day = event_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                    approved_count = mongo.db.points_request.count_documents({
                        "_id": {"$nin": selected_ids},
                        "user_id": req.get('user_id'),
                        "category_id": req.get('category_id'),
                        "event_date": {"$gte": start_of_day, "$lte": end_of_day},
                        "status": "Approved"
                    })
                
                # Mark all items in the group as duplicates (including the first one if there are approved records)
                for i, item in enumerate(group_items):
                    duplicates.append({
                        'rowNumber': item['idx'] + 1,
                        'employeeName': item['employee'].get('name', 'Unknown'),
                        'categoryName': item['category'].get('name', 'Unknown'),
                        'eventDate': item['event_date'].strftime('%d-%m-%Y'),
                        'status': 'Duplicate in Selection',
                        'approvedCount': approved_count,
                        'pendingCount': len(group_items),
                        'message': f"Duplicate in selection" + (f" + {approved_count} already approved" if approved_count > 0 else "")
                    })
                # Mark the group as processed
                duplicate_groups[group_key] = True
        
        # ✅ STEP 3: Check for existing approved records in database
        for current_request in selected_requests:
            try:
                idx = current_request['_original_idx']
                
                # Get employee and category info
                employee = mongo.db.users.find_one({"_id": current_request.get('user_id')})
                # ✅ Check both hr_categories and categories collections
                category = mongo.db.hr_categories.find_one({"_id": current_request.get('category_id')})
                if not category:
                    category = mongo.db.categories.find_one({"_id": current_request.get('category_id')})
                
                if not employee or not category:
                    continue
                
                event_date = current_request.get('event_date')
                if not event_date:
                    continue
                
                # Check for utilization category
                category_name = category.get('name', '').lower()
                # ✅ Check both category_code (hr_categories) and code (categories) fields
                category_code = category.get('category_code', category.get('code', '')).lower()
                is_utilization = ('utilization' in category_name or 'utlization' in category_name or 'billable' in category_name or
                                 'utilization' in category_code or 'billable' in category_code)
                
                if is_utilization:
                    # For utilization, check same month
                    start_of_month = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    next_month = (start_of_month.replace(month=start_of_month.month % 12 + 1) if start_of_month.month < 12 
                                 else start_of_month.replace(year=start_of_month.year + 1, month=1))
                    
                    # ✅ Create a key for grouping (user + category + month)
                    group_key = f"{current_request.get('user_id')}_{current_request.get('category_id')}_{start_of_month.strftime('%Y-%m')}"
                    
                    # ✅ Check for EXISTING approved records (exclude the ones being selected)
                    # Get list of selected request IDs to exclude them
                    selected_ids = [ObjectId(rid) for rid in request_ids]
                    
                    # ✅ FIXED: Only check points_request collection (points collection is duplicate data)
                    existing_approved_requests = list(mongo.db.points_request.find({
                        "_id": {"$nin": selected_ids},  # ✅ Exclude selected requests
                        "user_id": current_request.get('user_id'),
                        "category_id": current_request.get('category_id'),
                        "event_date": {"$gte": start_of_month, "$lt": next_month},
                        "status": "Approved"  # ✅ Only check approved records
                    }))
                    
                    # ✅ Count only from points_request (avoid double counting with points collection)
                    approved_count = len(existing_approved_requests)
                    
                    # ✅ Only flag as duplicate if there are APPROVED records (ignore pending-only)
                    if approved_count > 0:
                        # Track this group to avoid duplicate warnings
                        if group_key not in duplicate_groups:
                            duplicate_groups[group_key] = True
                            
                            # ✅ Show ONLY approved count (remove pending from display)
                            status_display = f"{approved_count} Already Approved"
                            
                            # ✅ Build validator-specific message showing only approved records
                            validator_message = f'This employee, category, and {event_date.strftime("%B %Y")} is already approved ({approved_count} record(s))'
                            
                            duplicates.append({
                                'rowNumber': idx + 1,
                                'employeeName': employee.get('name', 'Unknown'),
                                'categoryName': category.get('name', 'Unknown'),
                                'eventDate': event_date.strftime('%d-%m-%Y'),
                                'status': status_display,
                                'approvedCount': approved_count,  # ✅ Add approved count separately
                                'pendingCount': 0,                # ✅ Hide pending count
                                'message': validator_message
                            })
                else:
                    # For non-utilization, check exact date
                    start_of_day = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_of_day = event_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                    
                    # ✅ Create a key for grouping (user + category + date)
                    group_key = f"{current_request.get('user_id')}_{current_request.get('category_id')}_{start_of_day.strftime('%Y-%m-%d')}"
                    
                    # ✅ Check for EXISTING approved records (exclude the ones being selected)
                    # Get list of selected request IDs to exclude them
                    selected_ids = [ObjectId(rid) for rid in request_ids]
                    
                    # ✅ FIXED: Only check points_request collection (points collection is duplicate data)
                    existing_approved_requests = list(mongo.db.points_request.find({
                        "_id": {"$nin": selected_ids},  # ✅ Exclude selected requests
                        "user_id": current_request.get('user_id'),
                        "category_id": current_request.get('category_id'),
                        "event_date": {"$gte": start_of_day, "$lte": end_of_day},
                        "status": "Approved"  # ✅ Only check approved records
                    }))
                    
                    # ✅ Count only from points_request (avoid double counting with points collection)
                    approved_count = len(existing_approved_requests)
                    
                    # ✅ Only flag as duplicate if there are APPROVED records (ignore pending-only)
                    if approved_count > 0:
                        # Track this group to avoid duplicate warnings
                        if group_key not in duplicate_groups:
                            duplicate_groups[group_key] = True
                            
                            # ✅ Show ONLY approved count (remove pending from display)
                            status_display = f"{approved_count} Already Approved"
                            
                            # ✅ Build validator-specific message showing only approved records
                            validator_message = f'This employee, category, and event date is already approved ({approved_count} record(s))'
                            
                            duplicates.append({
                                'rowNumber': idx + 1,
                                'employeeName': employee.get('name', 'Unknown'),
                                'categoryName': category.get('name', 'Unknown'),
                                'eventDate': event_date.strftime('%d-%m-%Y'),
                                'status': status_display,
                                'approvedCount': approved_count,  # ✅ Add approved count separately
                                'pendingCount': 0,                # ✅ Hide pending count
                                'message': validator_message
                            })
            
            except Exception as e:
                error_print(f"Error checking request {current_request.get('_id')}: {str(e)}")
                continue
        
        # ✅ Sort duplicates by row number before returning
        duplicates.sort(key=lambda x: x.get('rowNumber', 999999))
        
        return jsonify({
            'duplicates': duplicates
        })
        
    except Exception as e:
        error_print(f"Error in bulk validator action check: {str(e)}")
        return jsonify({
            'duplicates': [],
            'error': 'Internal server error'
        }), 500
