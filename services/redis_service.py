"""
Centralized Redis Service for Real-Time Updates
"""

import redis
import json
from datetime import datetime
from typing import Dict, Any, Optional
import sys


class RedisRealtimeService:
    """Centralized Redis Pub/Sub for all PBS dashboards"""
    
    def __init__(self):
        # ✅ USE 127.0.0.1 INSTEAD OF 'localhost' to avoid eventlet DNS issues
        self.redis = redis.Redis(
            host='127.0.0.1',  # ✅ CHANGED FROM 'localhost'
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True
        )
        
        try:
            self.redis.ping()
        except Exception:
            pass
    
    def publish_event(self, event_type: str, data: Dict[str, Any], 
                     target_user_id: Optional[str] = None,
                     target_role: Optional[str] = None,
                     notify_only_assigned: bool = False):
        """
        Universal publish method for all events
        
        Args:
            event_type: 'employee_request_raised', 'new_request', 'points_awarded', etc.
            data: Event payload
            target_user_id: Specific user to notify (e.g., manager_id)
            target_role: Role to notify (e.g., 'employee', 'ta_updater', 'ta_validator', 'pm', 'manager')
            notify_only_assigned: If True, only notify the specific assigned user, not all users with that role
        """
        try:
            message = {
                'event_type': event_type,
                'data': data,
                'timestamp': datetime.utcnow().isoformat(),
                'target_user_id': target_user_id,
                'target_role': target_role
            }
            
            # ✅ ROUTE BASED ON EVENT TYPE
            if event_type in ['employee_request_raised', 'new_request']:
                # Notify specific manager/validator
                if target_user_id:
                    # Use target_role to determine the correct room prefix
                    role_prefix = target_role if target_role else 'manager'
                    channel = f'user:{role_prefix}:{target_user_id}'
                    
                    self.redis.publish(channel, json.dumps(message))
                
                # ✅ FIXED: Only notify all validators of this role if NOT notify_only_assigned
                # This prevents unassigned managers from getting notifications
                if target_role and not notify_only_assigned:
                    role_channel = f'role:{target_role}:updates'
                    self.redis.publish(role_channel, json.dumps(message))
            
            elif event_type == 'points_awarded':
                # Notify specific user (could be employee or anyone receiving points)
                if target_user_id:
                    # ✅ Use target_role to determine the correct room prefix
                    role_prefix = target_role if target_role else 'employee'
                    channel = f'user:{role_prefix}:{target_user_id}'
                    self.redis.publish(channel, json.dumps(message))
                
                # Broadcast leaderboard update
                self.redis.publish('all:leaderboard_update', json.dumps(message))
            
            elif event_type == 'bonus_points_awarded':
                # ✅ Notify specific user about bonus points (employee or manager)
                if target_user_id:
                    role_prefix = target_role if target_role else 'employee'
                    channel = f'user:{role_prefix}:{target_user_id}'
                    self.redis.publish(channel, json.dumps(message))
                
                # Also broadcast leaderboard update
                self.redis.publish('all:leaderboard_update', json.dumps(message))
            
            elif event_type == 'request_status_changed':
                # Notify user about their request status
                if target_user_id:
                    # ✅ Use target_role to determine the correct room prefix
                    role_prefix = target_role if target_role else 'employee'
                    channel = f'user:{role_prefix}:{target_user_id}'
                    self.redis.publish(channel, json.dumps(message))
            
            elif event_type == 'leaderboard_update':
                # Broadcast to everyone
                self.redis.publish('all:leaderboard_update', json.dumps(message))
            
            else:
                # Generic fallback for unknown event types
                if target_user_id:
                    role_prefix = target_role if target_role else 'user'
                    channel = f'user:{role_prefix}:{target_user_id}'
                    self.redis.publish(channel, json.dumps(message))
                elif target_role:
                    self.redis.publish(f'role:{target_role}:updates', json.dumps(message))
                else:
                    self.redis.publish('all:global_event', json.dumps(message))
            
            return True
        
        except Exception:
            return False


# Global instance
redis_service = RedisRealtimeService()