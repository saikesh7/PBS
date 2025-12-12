import json
import eventlet
from flask_socketio import emit, join_room
import sys

class SocketIORealtimeService:
    """Eventlet-compatible SocketIO handler for all dashboards"""
    
    def __init__(self, socketio, redis_service):
        self.socketio = socketio
        self.redis_service = redis_service
        self.pubsub = None
        self.listening = False
        self.listener_greenlet = None
    
    def start_listener(self):
        """Start Redis subscriber in eventlet greenlet"""
        if not self.listening:
            self.listening = True
            self._subscribe_to_all_channels()
            
            # Use eventlet spawn instead of threading
            self.listener_greenlet = eventlet.spawn(self._listen_for_redis_messages)
    
    def _subscribe_to_all_channels(self):
        """Subscribe to all Redis channels"""
        try:
            self.pubsub = self.redis_service.redis.pubsub(ignore_subscribe_messages=True)
            self.pubsub.psubscribe('user:*', 'role:*', 'all:*')
        except Exception:
            pass
    
    def _listen_for_redis_messages(self):
        """Listen for Redis messages with timeout handling"""
        while self.listening:
            try:
                # Get message with timeout to prevent blocking
                message = self.pubsub.get_message(timeout=1.0)
                
                if message and message['type'] == 'pmessage':
                    channel = message['channel']
                    try:
                        data = json.loads(message['data'])
                        self._route_message(channel, data)
                    except json.JSONDecodeError:
                        pass
                    except Exception:
                        pass
                
                # Yield to other greenlets to prevent blocking
                eventlet.sleep(0.01)
            
            except Exception:
                eventlet.sleep(1)
    
    def _route_message(self, channel: str, data: dict):
        """Route messages to appropriate SocketIO rooms"""
        event_type = data.get('event_type')
        
        try:
            # User-specific channels (user:employee:123, user:manager:456)
            if channel.startswith('user:'):
                parts = channel.split(':')
                if len(parts) >= 3:
                    user_type = parts[1]  # employee, manager, validator
                    user_id = parts[2]
                    room = f'{user_type}_{user_id}'
                    
                    # ✅ Emit the event to the user's room
                    self.socketio.emit(
                        event_type,
                        data['data'],
                        room=room,
                        namespace='/'
                    )
            
            # Role-based channels (role:pm:updates, role:hr:updates)
            elif channel.startswith('role:'):
                role = channel.split(':')[1] if len(channel.split(':')) > 1 else None
                if role:
                    self.socketio.emit(
                        event_type,
                        data['data'],
                        room=f'role_{role}',
                        namespace='/'
                    )
            
            # Broadcast channels (all:leaderboard_update, all:notification)
            elif channel.startswith('all:'):
                if channel == 'all:leaderboard_update':
                    self.socketio.emit(
                        'leaderboard_update',
                        data['data'],
                        broadcast=True,
                        namespace='/'
                    )
                elif channel == 'all:notification':
                    self.socketio.emit(
                        'global_notification',
                        data['data'],
                        broadcast=True,
                        namespace='/'
                    )
        
        except Exception:
            pass
    
    def handle_user_connect(self, user_id: str, user_type: str, role: str = None):
        """Handle user connection to SocketIO"""
        try:
            # Join user-specific room
            room = f'{user_type}_{user_id}'
            join_room(room)
            
            # Join role-based room if applicable
            if role:
                join_room(f'role_{role}')
            
            emit('connected', {
                'message': 'Connected to real-time updates',
                'user_room': room,
                'role_room': f'role_{role}' if role else None
            })
        
        except Exception:
            pass
    
    def stop_listener(self):
        """Stop the Redis listener gracefully"""
        self.listening = False
        if self.pubsub:
            try:
                self.pubsub.punsubscribe()
                self.pubsub.close()
            except Exception:
                pass