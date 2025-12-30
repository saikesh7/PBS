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
    except Exception:
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
        return False
    
    try:
        # Check if this is a TA-created request
        is_ta_created = bool(request_data.get('created_by_ta_id'))
        ta_updater_name = None
        
        if is_ta_created:
            from extensions import mongo
            ta_updater = mongo.db.users.find_one({'_id': request_data.get('created_by_ta_id')})
            ta_updater_name = ta_updater.get('name', 'TA Updater') if ta_updater else 'TA Updater'
        
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
            'is_ta_created': is_ta_created,
            'ta_updater_name': ta_updater_name,
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

        # ✅ SPECIAL HANDLING: Detect which updater created the request
        is_pmo_created = bool(request_data.get('created_by_pmo_id'))
        is_hr_created = bool(request_data.get('created_by_hr_id'))
        is_ld_created = bool(request_data.get('created_by_ld_id'))
        is_ta_created = bool(request_data.get('created_by_ta_id'))
        

        
        # ✅ USE CORRECT EVENT TYPE AND TARGET ROLE BASED ON DASHBOARD TYPE
        # ⚠️ PRIORITY: Check created_by flags FIRST (they have highest priority)

        if is_hr_created:
            # HR Updater created - route to HR Validator
            event_type = 'new_request'
            target_role = 'hr_validator'
        
        elif is_ld_created:
            # L&D Updater created - route to L&D Validator
            event_type = 'new_request'
            target_role = 'ld_validator'
        
        elif is_pmo_created:
            # PMO Updater created - route to PMO Validator
            event_type = 'new_request'
            target_role = 'pmo_validator'
        
        elif is_ta_created:
            # TA Updater created - route to TA Validator
            event_type = 'new_request'
            target_role = 'ta_validator'
        
        # If no created_by flag, use category_department and validator access
        elif dashboard_type.startswith('hr') or dashboard_type == 'hr_up' or ('hr_va' in validator_access and 'hr' in dashboard_type):
            event_type = 'new_request'
            target_role = 'hr_validator'
        
        elif dashboard_type in ['ld_up', 'ld_va'] or dashboard_type.startswith('ld') or ('ld_va' in validator_access and ('ld' in dashboard_type or 'l&d' in dashboard_type or 'learning' in dashboard_type)):
            event_type = 'new_request'
            target_role = 'ld_validator'
        
        elif dashboard_type == 'pmo_up' or dashboard_type.startswith('pmo') or ('pmo_va' in validator_access and 'pmo' in dashboard_type):
            event_type = 'new_request'
            target_role = 'pmo_validator'
        
        elif dashboard_type in ['ta_up', 'ta_va'] or dashboard_type.startswith('ta') or ('ta_va' in validator_access and 'ta' in dashboard_type):
            event_type = 'new_request'
            target_role = 'ta_validator'
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
        
        # ✅ FIXED: Publish ONLY to the assigned validator's specific room
        # Do NOT broadcast to all validators of that role
        result = redis_service.publish_event(
            event_type=event_type,
            data=event_payload,
            target_user_id=str(validator_data.get('_id')),
            target_role=target_role,
            notify_only_assigned=True  # New flag to prevent role-wide broadcast
        )
        
        return True
    
    except Exception:
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
        return False
    
    try:
        from extensions import mongo
        
        # Get category data
        category_id = request_data.get('category_id')
        category = mongo.db.categories.find_one({'_id': category_id})
        if not category:
            category = mongo.db.hr_categories.find_one({'_id': category_id})
        
        category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
        
        # Get utilization value if it exists
        utilization_value = request_data.get('utilization_value')
        utilization_percentage = None
        
        # Convert utilization to percentage for display
        if utilization_value is not None:
            if utilization_value <= 1:
                # It's a decimal (0.85 = 85%)
                utilization_percentage = round(utilization_value * 100, 1)
            else:
                # It's already a percentage (85 = 85%)
                utilization_percentage = round(utilization_value, 1)
        
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
            'utilization_value': utilization_value,
            'utilization_percentage': utilization_percentage,
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
        
        # ✅ 2. Notify TA Updater who raised the request (always notify, even if same as employee)
        if 'created_by_ta_id' in request_data and request_data.get('created_by_ta_id'):
            ta_updater_id = str(request_data.get('created_by_ta_id'))
            
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=ta_updater_id,
                target_role='ta_updater'
            )
        # ✅ 3. Notify PMO Updater who raised the request (always notify, even if same as employee)
        if 'created_by_pmo_id' in request_data and request_data.get('created_by_pmo_id'):
            pmo_updater_id = str(request_data.get('created_by_pmo_id'))
            
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=pmo_updater_id,
                target_role='pmo_updater'
            )

        
        # ✅ Notify HR Updater who raised the request (always notify, even if same as employee)
        if 'created_by_hr_id' in request_data and request_data.get('created_by_hr_id'):
            hr_updater_id = str(request_data.get('created_by_hr_id'))
            
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=hr_updater_id,
                target_role='hr_updater'
            )

        
        
        
        # ✅ 4. Notify L&D Updater who raised the request (always notify, even if same as employee)
        if 'created_by_ld_id' in request_data and request_data.get('created_by_ld_id'):
            ld_updater_id = str(request_data.get('created_by_ld_id'))
            
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=ld_updater_id,
                target_role='ld_updater'
            )

        
    
        # Also trigger leaderboard update
        publish_leaderboard_update()
        
        # ✅ 5. Notify DP if employee is assigned to a DP
        if employee_data.get('dp_id'):
            dp_id = str(employee_data.get('dp_id'))
            publish_dp_points_update(
                employee_id=str(employee_data.get('_id')),
                dp_id=dp_id,
                points_data={
                    'points': request_data.get('points', 0),
                    'category_name': category_name
                }
            )
        
        return True
    
    except Exception:
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
        return False
    
    try:
        from extensions import mongo
        
        # Get category data
        category_id = request_data.get('category_id')
        category = mongo.db.categories.find_one({'_id': category_id})
        if not category:
            category = mongo.db.hr_categories.find_one({'_id': category_id})
        
        category_name = category.get('name', 'Unknown Category') if category else 'Unknown Category'
        
        # Get utilization value if it exists
        utilization_value = request_data.get('utilization_value')
        utilization_percentage = None
        
        # Convert utilization to percentage for display
        if utilization_value is not None:
            if utilization_value <= 1:
                # It's a decimal (0.85 = 85%)
                utilization_percentage = round(utilization_value * 100, 1)
            else:
                # It's already a percentage (85 = 85%)
                utilization_percentage = round(utilization_value, 1)
        
        event_payload = {
            'request_id': str(request_data.get('_id')),
            'employee_id': str(employee_data.get('_id')),
            'employee_name': employee_data.get('name', 'Unknown Employee'),
            'rejector_id': str(rejector_data.get('_id')),
            'rejector_name': rejector_data.get('name', 'Unknown Rejector'),
            'category_name': category_name,
            'points': request_data.get('points', 0),
            'utilization_value': utilization_value,
            'utilization_percentage': utilization_percentage,
            'response_notes': request_data.get('response_notes', ''),
            'new_status': 'Rejected',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # ✅ 1. Notify employee ONLY if it's an employee-raised request (not a direct award)
        # Direct awards have created_by_X_id fields (ta/pmo/hr/ld)
        is_direct_award = (
            request_data.get('created_by_ta_id') or 
            request_data.get('created_by_pmo_id') or 
            request_data.get('created_by_hr_id') or 
            request_data.get('created_by_ld_id')
        )
        
        # Only notify employee if it's NOT a direct award
        if not is_direct_award:
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=str(employee_data.get('_id')),
                target_role='employee'
            )
        
        # ✅ 2. Notify TA Updater who raised the request (if different from employee)
        if 'created_by_ta_id' in request_data and request_data.get('created_by_ta_id'):
            ta_updater_id = str(request_data.get('created_by_ta_id'))
            
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=ta_updater_id,
                target_role='ta_updater'
            )

        # ✅ 3. Notify L&D Updater who raised the request (always notify, even if same as employee)
        if 'created_by_ld_id' in request_data and request_data.get('created_by_ld_id'):
            ld_updater_id = str(request_data.get('created_by_ld_id'))
            
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=ld_updater_id,
                target_role='ld_updater'
            )
        
        
        # ✅ Notify HR Updater who raised the request (always notify, even if same as employee)
        if 'created_by_hr_id' in request_data and request_data.get('created_by_hr_id'):
            hr_updater_id = str(request_data.get('created_by_hr_id'))
            
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=hr_updater_id,
                target_role='hr_updater'
            )
                
                
        
        #✅ 3. Notify PMO Updater who raised the request (always notify, even if same as employee)
        if 'created_by_pmo_id' in request_data and request_data.get('created_by_pmo_id'):
            pmo_updater_id = str(request_data.get('created_by_pmo_id'))
            
            redis_service.publish_event(
                event_type='request_status_changed',
                data=event_payload,
                target_user_id=pmo_updater_id,
                target_role='pmo_updater'
            )
        
        # ✅ 4. Notify DP if employee is assigned to a DP (for rejection tracking)
        if employee_data.get('dp_id'):
            dp_id = str(employee_data.get('dp_id'))
            # DP might want to know about rejections too
            redis_service.publish_event(
                event_type='dp_employee_points_update',
                data={
                    'employee_id': str(employee_data.get('_id')),
                    'dp_id': dp_id,
                    'action': 'refresh_points',
                    'status': 'rejected',
                    'timestamp': datetime.utcnow().isoformat()
                },
                target_user_id=dp_id,
                target_role='dp'
            )
        
        return True
        
    
    except Exception:
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
        
        # Also trigger leaderboard update
        publish_leaderboard_update()
        
        # ✅ Notify DP if employee is assigned to a DP
        if employee_data.get('dp_id'):
            dp_id = str(employee_data.get('dp_id'))
            publish_dp_points_update(
                employee_id=str(employee_data.get('_id')),
                dp_id=dp_id,
                points_data={
                    'points': points_award_data.get('points', 0),
                    'category_name': category_data.get('name', 'Unknown')
                }
            )
        
        return True
    
    except Exception:
        return False


def publish_ta_working_notification(request_data: Dict, employee_data: Dict, validator_data: Dict, category_data: Dict, action: str = 'reviewing'):
    """
    Published when: TA Validator is working on (reviewing/approving/rejecting) a request
    Notifies: PM/PMArch/Presales validators who originally received the request
    
    Usage Example:
        # When TA validator opens/reviews a request
        publish_ta_working_notification(request_doc, employee, ta_validator, category, action='reviewing')
    
    Args:
        action: 'reviewing', 'approving', 'rejecting'
    """
    redis_service, _ = get_services()
    if not redis_service:
        return False
    
    try:
        from extensions import mongo
        
        # Get the original validator (PM/PMArch/Presales) from the request
        original_validator_id = request_data.get('assigned_validator_id')
        if not original_validator_id:
            return False
        
        original_validator = mongo.db.users.find_one({'_id': original_validator_id})
        if not original_validator:
            return False
        
        # Check if original validator is PM/PMArch/Presales (not TA)
        validator_access = original_validator.get('dashboard_access', [])
        if isinstance(validator_access, str):
            validator_access = [x.strip().lower() for x in validator_access.split(',')]
        validator_access = [x.lower() for x in validator_access]
        
        # Only notify if original validator is PM/PMArch/Presales
        is_pm_presales_pmarch = any(role in validator_access for role in ['pm', 'presales', 'marketing', 'pm_arch'])
        
        if not is_pm_presales_pmarch:
            return False
        
        event_payload = {
            'request_id': str(request_data.get('_id')),
            'employee_id': str(employee_data.get('_id')),
            'employee_name': employee_data.get('name', 'Unknown Employee'),
            'ta_validator_id': str(validator_data.get('_id')),
            'ta_validator_name': validator_data.get('name', 'TA Validator'),
            'category_name': category_data.get('name', 'Unknown Category'),
            'points': request_data.get('points', 0),
            'action': action,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Determine target role
        if 'pm' in validator_access and 'pm_arch' not in validator_access:
            target_role = 'pm'
        elif 'pm_arch' in validator_access:
            target_role = 'pm_arch'
        elif 'presales' in validator_access:
            target_role = 'presales'
        elif 'marketing' in validator_access:
            target_role = 'marketing'
        else:
            return False
        
        # Notify the original validator
        redis_service.publish_event(
            event_type='ta_working_on_request',
            data=event_payload,
            target_user_id=str(original_validator_id),
            target_role=target_role
        )
        
        return True
    
    except Exception:
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
        
        return True
    
    except Exception:
        return False
def publish_dp_employee_list_update(dp_id: str):
    """
    Published when: An employee is assigned or unassigned from a DP
    Notifies: The DP to refresh their employee list
    
    Usage Example:
        # After assigning/unassigning employee to/from DP
        publish_dp_employee_list_update(str(dp_id))
    """
    redis_service, _ = get_services()
    if not redis_service:
        return False
    
    try:
        event_payload = {
            'dp_id': dp_id,
            'timestamp': datetime.utcnow().isoformat(),
            'action': 'refresh_employee_list'
        }
        
        # Notify DP to refresh their employee list
        redis_service.publish_event(
            event_type='dp_employee_list_update',
            data=event_payload,
            target_user_id=dp_id,
            target_role='dp'
        )
        
        return True
    
    except Exception:
        return False


def publish_dp_points_update(employee_id: str, dp_id: str, points_data: Dict):
    """
    Published when: An employee assigned to a DP gets points approved
    Notifies: The DP to refresh their dashboard with updated points
    
    Usage Example:
        # After approving points for an employee assigned to a DP
        publish_dp_points_update(str(employee_id), str(dp_id), points_data)
    """
    redis_service, _ = get_services()
    if not redis_service:
        return False
    
    try:
        event_payload = {
            'employee_id': employee_id,
            'dp_id': dp_id,
            'points': points_data.get('points', 0),
            'category_name': points_data.get('category_name', 'Unknown'),
            'timestamp': datetime.utcnow().isoformat(),
            'action': 'refresh_points'
        }
        
        # Notify DP to refresh their dashboard
        redis_service.publish_event(
            event_type='dp_employee_points_update',
            data=event_payload,
            target_user_id=dp_id,
            target_role='dp'
        )
        
        return True
    
    except Exception:
        return False


def publish_validator_dashboard_refresh(validator_id: str, validator_role: str, action: str = 'refresh'):
    """
    Published when: A validator processes a request (approve/reject)
    Notifies: The validator to refresh their dashboard
    
    Usage Example:
        # After validator approves/rejects a request
        publish_validator_dashboard_refresh(str(validator_id), 'pmo_validator', 'approved')
    
    Args:
        validator_id: The validator's user ID
        validator_role: The validator's role (pmo_validator, ld_validator, hr_validator, ta_validator)
        action: The action performed ('approved', 'rejected', 'refresh')
    """
    redis_service, _ = get_services()
    if not redis_service:
        return False
    
    try:
        event_payload = {
            'validator_id': validator_id,
            'action': action,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Notify validator to refresh their dashboard
        redis_service.publish_event(
            event_type='validator_dashboard_refresh',
            data=event_payload,
            target_user_id=validator_id,
            target_role=validator_role
        )
        
        return True
    
    except Exception:
        return False