"""
Universal Real-Time Event Publisher for PBS Application
Handles all real-time notifications across all dashboards
"""

from flask import current_app
from datetime import datetime
from typing import Dict, Any, Optional
import sys
from bson import ObjectId


def get_services():
    """Get Redis and SocketIO services from app config"""
    try:
        redis_service = current_app.config.get('redis_service')
        socketio = current_app.config.get('socketio')
        return redis_service, socketio
    except Exception as e:
        print(f"⚠️ Services not available: {e}", file=sys.stderr)
        return None, None


def publish_request_raised(request_data: Dict, employee_data: Dict, validator_data: Dict, category_data: Dict):
    """
    Published when: Employee or TA Updater raises a request
    Notifies: Assigned validator (PM/Presales/Marketing/TA Validator)
    
    Usage Example:
        # After inserting request
        publish_request_raised(new_request, employee, validator, category)
    """
    redis_service, _ = get_services()
    if not redis_service:
        print("⚠️ Redis service not available for publish_request_raised")
        return False
    
    try:
        event_payload = {
            'request_id': str(request_data.get('_id')),
            'employee_id': str(employee_data.get('_id')),
            'employee_name': employee_data.get('name', 'Unknown Employee'),
            'employee_email': employee_data.get('email', ''),
            'employee_grade': employee_data.get('grade', 'N/A'),
            'employee_department': employee_data.get('department', 'N/A'),
            'validator_id': str(validator_data.get('_id')),
            'validator_name': validator_data.get('name', 'Unknown Validator'),
            'category_id': str(category_data.get('_id')),
            'category_name': category_data.get('name', 'Unknown Category'),
            'category_department': category_data.get('category_department', 'N/A'),
            'category_type': category_data.get('category_type', 'N/A'),
            'points': request_data.get('points', 0),
            'quantity': request_data.get('quantity', 1),
            'submission_notes': request_data.get('submission_notes', ''),
            'event_date': request_data.get('event_date').isoformat() if request_data.get('event_date') else None,
            'updated_by': request_data.get('updated_by', 'Employee'),
            'source': 'ta_updater' if request_data.get('created_by_ta_id') else ('pmo_updater' if request_data.get('created_by_pmo_id') else 'employee'),
 
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Determine dashboard type and event type based on category_department
        dashboard_type_raw = category_data.get('category_department', 'pm')
        
        # ✅ NORMALIZE: Convert to lowercase and replace spaces/slashes with underscores
        dashboard_type = str(dashboard_type_raw).lower().replace(' ', '_').replace('/', '_').replace('-', '_')
        
        # Also check validator's dashboard_access to determine correct role
        validator_access = validator_data.get('dashboard_access', [])
        if isinstance(validator_access, str):
            validator_access = [x.strip().lower() for x in validator_access.split(',')]
        validator_access = [x.lower() for x in validator_access]

        # ✅ USE CORRECT EVENT TYPE AND TARGET ROLE BASED ON DASHBOARD TYPE

        if dashboard_type.startswith('hr') or dashboard_type == 'hr_up':
            event_type = 'new_request'
            target_role = 'hr_validator'
        elif dashboard_type == 'ta_up':
            # For TA Validator, use 'new_request' event
            event_type = 'new_request'
            target_role = 'ta_validator'
        

        elif dashboard_type == 'pmo_up' or 'pmo_va' in validator_access or dashboard_type.startswith('pmo'):
            # For PMO Validator, use 'new_request' event (same as TA)
            event_type = 'new_request'
            target_role = 'pmo_validator'

        elif dashboard_type in ['ld_up', 'ld_va']:
            # For L&D Validator, use 'new_request' event
            event_type = 'new_request'
            target_role = 'ld_validator'
        elif dashboard_type == 'pm':
            # For PM, use 'employee_request_raised'
            event_type = 'employee_request_raised'
            target_role = 'pm'
        elif dashboard_type == 'presales':
            event_type = 'employee_request_raised'
            target_role = 'presales'
        elif dashboard_type == 'marketing':
            event_type = 'employee_request_raised'
            target_role = 'marketing'
        elif 'pmarch' in dashboard_type or 'pm_arch' in dashboard_type:
            # For PM/Arch, use 'employee_request_raised'
            # Handles: pmarch, pm_arch, PM_ARCH, PM/Arch, etc.
            event_type = 'employee_request_raised'
            target_role = 'pm_arch'
        else:
            # Default
            event_type = 'employee_request_raised'
            target_role = dashboard_type
        
        # Publish to validator's specific room
        redis_service.publish_event(
            event_type=event_type,
            data=event_payload,
            target_user_id=str(validator_data.get('_id')),
            target_role=target_role
        )
        
        source = "TA Updater" if request_data.get('created_by_ta_id') else ("PMO Updater" if request_data.get('created_by_pmo_id') else "Employee")
        print(f"✅ Real-Time: Request raised by {source} ({employee_data.get('name')}) → Validator: {validator_data.get('name')} [{dashboard_type}] as event '{event_type}'")
        return True
    
    except Exception as e:
        print(f"❌ Error in publish_request_raised: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def publish_request_approved(request_data: Dict, employee_data: Dict, approver_data: Dict, points_award_data: Optional[Dict] = None):
    """
    Published when: PM/TA Validator/Manager approves a request and awards points
    Notifies: 
        1. Employee who receives the points
        2. TA Updater who raised the request (if different from employee)
    
    Usage Example:
        # After approving request and creating points record
        publish_request_approved(request_doc, employee, approver, points_doc)
    """
    redis_service, _ = get_services()
    if not redis_service:
        print("⚠️ Redis service not available for publish_request_approved")
        return False
    
    try:
        from extensions import mongo
        
        # Get category data
        category_id = request_data.get('category_id')
        category = mongo.db.categories.find_one({'_id': category_id})
        if not category:
            category = mongo.db.hr_categories.find_one({'_id': category_id})
        
        category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
        
        event_payload = {
            'request_id': str(request_data.get('_id')),
            'award_id': str(points_award_data.get('_id')) if points_award_data else None,
            'employee_id': str(employee_data.get('_id')),
            'employee_name': employee_data.get('name', 'Unknown Employee'),
            'employee_email': employee_data.get('email', ''),
            'approver_id': str(approver_data.get('_id')),
            'approver_name': approver_data.get('name', 'Unknown Approver'),
            'category_id': str(category_id) if category_id else None,
            'category_name': category_name,
            'points': request_data.get('points', 0),
            'response_notes': request_data.get('response_notes', ''),
            'old_status':'Pending',
            'award_date': points_award_data.get('award_date').isoformat() if points_award_data and points_award_data.get('award_date') else None,
            'new_status': 'Approved',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # ✅ 1. Notify employee who receives points
        redis_service.publish_event(
            event_type='points_awarded',
            data=event_payload,
            target_user_id=str(employee_data.get('_id')),
            target_role='employee'
        )
        
        print(f"✅ Real-Time: Points approved ({request_data.get('points')} pts) for {employee_data.get('name')} by {approver_data.get('name')}")
        
        # ✅ 2. Notify TA Updater who raised the request (if different from employee)
        if 'created_by_ta_id' in request_data and request_data.get('created_by_ta_id'):
            ta_updater_id = str(request_data.get('created_by_ta_id'))
            employee_id = str(employee_data.get('_id'))
            
            # Only notify if TA Updater is different from employee
            if ta_updater_id != employee_id:
                redis_service.publish_event(
                    event_type='request_status_changed',
                    data=event_payload,
                    target_user_id=ta_updater_id,
                    target_role='ta_updater'
                )
                print(f"✅ Real-Time: Approval notification sent to TA Updater (ID: {ta_updater_id}) in room: ta_updater_{ta_updater_id}")
        # ✅ 3. Notify PMO Updater who raised the request (if different from employee)
        if 'created_by_pmo_id' in request_data and request_data.get('created_by_pmo_id'):
            pmo_updater_id = str(request_data.get('created_by_pmo_id'))
            employee_id = str(employee_data.get('_id'))
           
            # Only notify if PMO Updater is different from employee
            if pmo_updater_id != employee_id:
                redis_service.publish_event(
                    event_type='request_status_changed',
                    data=event_payload,
                    target_user_id=pmo_updater_id,
                    target_role='pmo_updater'
                )
                print(f"✅ Real-Time: Approval notification sent to PMO Updater (ID: {pmo_updater_id}) in room: pmo_updater_{pmo_updater_id}")
        if 'created_by_ld_id' in request_data and request_data.get('created_by_ld_id'):
            ld_updater_id = str(request_data.get('created_by_ld_id'))
            employee_id = str(employee_data.get('_id'))
           
            # Only notify if L&D Updater is different from employee
            if ld_updater_id != employee_id:
                redis_service.publish_event(
                    event_type='request_status_changed',
                    data=event_payload,
                    target_user_id=ld_updater_id,
                    target_role='ld_updater'
                )
                print(f"✅ Real-Time: Approval notification sent to L&D Updater (ID: {ld_updater_id}) in room: ld_updater_{ld_updater_id}")
    
        # Also trigger leaderboard update
        publish_leaderboard_update()
        
        return True
    
    except Exception as e:
        print(f"❌ Error in publish_request_approved: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def publish_request_rejected(request_data: Dict, employee_data: Dict, rejector_data: Dict):
    """
    Published when: PM/TA Validator/Manager rejects a request
    Notifies: 
        1. Employee who would have received points
        2. TA Updater who raised the request (if different from employee)
    
    Usage Example:
        # After rejecting request
        publish_request_rejected(request_doc, employee, rejector)
    """
    redis_service, _ = get_services()
    if not redis_service:
        print("⚠️ Redis service not available for publish_request_rejected")
        return False
    
    try:
        from extensions import mongo
        
        # Get category data
        category_id = request_data.get('category_id')
        category = mongo.db.categories.find_one({'_id': category_id})
        if not category:
            category = mongo.db.hr_categories.find_one({'_id': category_id})
        
        category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
        
        event_payload = {
            'request_id': str(request_data.get('_id')),
            'employee_id': str(employee_data.get('_id')),
            'employee_name': employee_data.get('name', 'Unknown Employee'),
            'rejector_id': str(rejector_data.get('_id')),
            'rejector_name': rejector_data.get('name', 'Unknown Rejector'),
            'category_name': category_name,
            'points': request_data.get('points', 0),
            'response_notes': request_data.get('response_notes', ''),
            'new_status': 'Rejected',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # ✅ 1. Notify employee
        redis_service.publish_event(
            event_type='request_status_changed',
            data=event_payload,
            target_user_id=str(employee_data.get('_id')),
            target_role='employee'
        )
        
        print(f"✅ Real-Time: Request rejected for {employee_data.get('name')} by {rejector_data.get('name')}")
        
        # ✅ 2. Notify TA Updater who raised the request (if different from employee)
        if 'created_by_ta_id' in request_data and request_data.get('created_by_ta_id'):
            ta_updater_id = str(request_data.get('created_by_ta_id'))
            employee_id = str(employee_data.get('_id'))
            
            # Only notify if TA Updater is different from employee
            if ta_updater_id != employee_id:
                redis_service.publish_event(
                    event_type='request_status_changed',
                    data=event_payload,
                    target_user_id=ta_updater_id,
                    target_role='ta_updater'
                )
                print(f"✅ Real-Time: Rejection notification sent to TA Updater (ID: {ta_updater_id}) in room: ta_updater_{ta_updater_id}")

        # ✅ 3. Notify L&D Updater who raised the request (if different from employee)
        if 'created_by_ld_id' in request_data and request_data.get('created_by_ld_id'):
            ld_updater_id = str(request_data.get('created_by_ld_id'))
            employee_id = str(employee_data.get('_id'))
           
            # Only notify if L&D Updater is different from employee
            if ld_updater_id != employee_id:
                redis_service.publish_event(
                    event_type='request_status_changed',
                    data=event_payload,
                    target_user_id=ld_updater_id,
                    target_role='ld_updater'
                )
                print(f"✅ Real-Time: Rejection notification sent to L&D Updater (ID: {ld_updater_id}) in room: ld_updater_{ld_updater_id}")
        #✅ 3. Notify PMO Updater who raised the request (if different from employee)
        if 'created_by_pmo_id' in request_data and request_data.get('created_by_pmo_id'):
            pmo_updater_id = str(request_data.get('created_by_pmo_id'))
            employee_id = str(employee_data.get('_id'))
           
            # Only notify if PMO Updater is different from employee
            if pmo_updater_id != employee_id:
                redis_service.publish_event(
                    event_type='request_status_changed',
                    data=event_payload,
                    target_user_id=pmo_updater_id,
                    target_role='pmo_updater'
                )
                print(f"✅ Real-Time: Rejection notification sent to PMO Updater (ID: {pmo_updater_id}) in room: pmo_updater_{pmo_updater_id}")
        return True
        
    
    except Exception as e:
        print(f"❌ Error in publish_request_rejected: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def publish_points_awarded_direct(points_award_data: Dict, employee_data: Dict, awarder_data: Dict, category_data: Dict):
    """
    Published when: Manager/PMO/TA/HR directly awards points (no request involved)
    Notifies: Employee who receives points
    
    Usage Example:
        # After creating points record directly
        publish_points_awarded_direct(points_doc, employee, awarder, category)
    """
    redis_service, _ = get_services()
    if not redis_service:
        print("⚠️ Redis service not available for publish_points_awarded_direct")
        return False
    
    try:
        event_payload = {
            'award_id': str(points_award_data.get('_id')),
            'employee_id': str(employee_data.get('_id')),
            'employee_name': employee_data.get('name', 'Unknown Employee'),
            'employee_email': employee_data.get('email', ''),
            'awarder_id': str(awarder_data.get('_id')),
            'awarder_name': awarder_data.get('name', 'Unknown Awarder'),
            'category_id': str(category_data.get('_id')),
            'category_name': category_data.get('name', 'Unknown Category'),
            'category_department': category_data.get('category_department', 'N/A'),
            'points': points_award_data.get('points', 0),
            'award_date': points_award_data.get('award_date').isoformat() if points_award_data.get('award_date') else None,
            'old_status':'Pending',
            'notes': points_award_data.get('notes', ''),
            'request_id': str(points_award_data.get('request_id')) if points_award_data.get('request_id') else None,
            'source': 'direct_award',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Notify employee
        redis_service.publish_event(
            event_type='points_awarded',
            data=event_payload,
            target_user_id=str(employee_data.get('_id')),
            target_role='employee'
        )
        
        print(f"✅ Real-Time: Direct award ({points_award_data.get('points')} pts) to {employee_data.get('name')} by {awarder_data.get('name')}")
        
        # Also trigger leaderboard update
        publish_leaderboard_update()
        
        return True
    
    except Exception as e:
        print(f"❌ Error in publish_points_awarded_direct: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def publish_leaderboard_update():
    """
    Published when: Any points are awarded (triggers leaderboard refresh for all users)
    Notifies: All connected users
    
    Usage Example:
        # After any points award
        publish_leaderboard_update()
    """
    redis_service, _ = get_services()
    if not redis_service:
        return False
    
    try:
        event_payload = {
            'update_type': 'leaderboard_refresh',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Broadcast to all users
        redis_service.publish_event(
            event_type='leaderboard_update',
            data=event_payload
        )
        
        print(f"✅ Real-Time: Leaderboard update broadcasted")
        return True
    
    except Exception as e:
        print(f"❌ Error in publish_leaderboard_update: {e}", file=sys.stderr)
        return False
