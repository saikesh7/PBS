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
        
        # Test connection
        try:
            self.redis.ping()
            print("✅ Redis connection successful (127.0.0.1:6379)")
        except Exception as e:
            print(f"❌ Redis connection failed: {e}", file=sys.stderr)
    
    def publish_event(self, event_type: str, data: Dict[str, Any], 
                     target_user_id: Optional[str] = None,
                     target_role: Optional[str] = None):
        """
        Universal publish method for all events
        
        Args:
            event_type: 'employee_request_raised', 'new_request', 'points_awarded', etc.
            data: Event payload
            target_user_id: Specific user to notify (e.g., manager_id)
            target_role: Role to notify (e.g., 'employee', 'ta_updater', 'ta_validator', 'pm', 'manager')
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
                    print(f"✅ Published '{event_type}' to {channel}")
                
                # Also notify all validators of this role
                if target_role:
                    self.redis.publish(f'role:{target_role}:updates', json.dumps(message))
                    print(f"✅ Published '{event_type}' to role:{target_role}:updates")
            
            elif event_type == 'points_awarded':
                # Notify specific user (could be employee or anyone receiving points)
                if target_user_id:
                    # ✅ Use target_role to determine the correct room prefix
                    role_prefix = target_role if target_role else 'employee'
                    channel = f'user:{role_prefix}:{target_user_id}'
                    self.redis.publish(channel, json.dumps(message))
                    print(f"✅ Published points_awarded to {channel}")
                
                # Broadcast leaderboard update
                self.redis.publish('all:leaderboard_update', json.dumps(message))
                print(f"✅ Broadcasted leaderboard update")
            
            elif event_type == 'request_status_changed':
                # Notify user about their request status
                if target_user_id:
                    # ✅ Use target_role to determine the correct room prefix
                    role_prefix = target_role if target_role else 'employee'
                    channel = f'user:{role_prefix}:{target_user_id}'
                    self.redis.publish(channel, json.dumps(message))
                    print(f"✅ Published status change to {channel}")
            
            elif event_type == 'leaderboard_update':
                # Broadcast to everyone
                self.redis.publish('all:leaderboard_update', json.dumps(message))
                print(f"✅ Broadcasted leaderboard update")
            
            else:
                # Generic fallback for unknown event types
                if target_user_id:
                    role_prefix = target_role if target_role else 'user'
                    channel = f'user:{role_prefix}:{target_user_id}'
                    self.redis.publish(channel, json.dumps(message))
                    print(f"✅ Published {event_type} to {channel}")
                elif target_role:
                    self.redis.publish(f'role:{target_role}:updates', json.dumps(message))
                    print(f"✅ Published {event_type} to role:{target_role}:updates")
                else:
                    self.redis.publish('all:global_event', json.dumps(message))
                    print(f"✅ Broadcasted {event_type} globally")
            
            return True
        
        except Exception as e:
            print(f"❌ Error publishing event: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False


# Global instance
redis_service = RedisRealtimeService()