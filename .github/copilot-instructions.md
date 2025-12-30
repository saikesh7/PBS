<!-- Copied/created for AI coding agents. Keep concise and specific to this repo. -->
# Quick guidance for AI coding agents

This file gives targeted, actionable guidance for making safe, correct edits in this Flask + SocketIO codebase.

**Big Picture**
- **App entry:** `app.py` is the canonical startup file. It monkey-patches with `eventlet` (must be first) and creates a `SocketIO` instance using `async_mode='eventlet'`.
- **Architecture:** Modular Flask app built from many blueprints under folders like `employee/`, `hr/`, `pm/`, `pmarch/`, `manager/`. Blueprints are imported in `app.py` and registered on the Flask app.
- **Realtime:** Real-time notifications use Redis Pub/Sub (`services/redis_service.py`) and a Socket.IO listener (`services/socketio_service.py`). Channels follow these conventions:
  - `user:<role>:<id>` — direct message to a specific user (e.g. `user:employee:123`).
  - `role:<role>:updates` — messages for all users of a role.
  - `all:<event>` — broadcasts to everyone (e.g. `all:leaderboard_update`).

**Critical patterns & conventions**
- **Monkey patch early:** `eventlet.monkey_patch()` must appear before other network/event imports (see top of `app.py`).
- **Blueprint naming:** Blueprints are named with a `_bp` suffix in modules (example: `employee_dashboard_bp` in `employee/employee_dashboard.py`). When adding a new module, export the blueprint with that pattern and register it in `app.py`.
- **Redis routing:** Use `RedisRealtimeService.publish_event(...)` to publish events. Match the event_type handling in `redis_service.py` so events land on the expected channel.
- **Socket routing:** `SocketIORealtimeService` expects JSON messages with `event_type` and `data` and routes based on channel prefixes. Use the same keys and room naming (e.g. `role_{role}`, `{user_type}_{user_id}`) when emitting.
- **Extensions:** `extensions.py` exposes `mongo`, `db` (legacy), `mail`, `bcrypt`. Initialize with `init_app(app)` in `create_app()`.

**How to run locally**
- Install dependencies from `requirements.txt` (the repo uses eventlet + Flask-SocketIO + Flask-PyMongo). `redis` Python package is required but not listed explicitly — confirm and install if missing.

  Example (PowerShell):
  ```powershell
  python -m pip install -r requirements.txt
  python app.py
  ```

- The server binds to `0.0.0.0:3500` by default (see `socketio.run(...)` in `app.py`). `use_reloader=False` is intentionally set to avoid double-start with Socket.IO/eventlet.

**Common change tasks & examples**
- Add a new blueprint:
  - Create module `foo/foo_routes.py` exporting `foo_bp`.
  - Import and register `foo_bp` in `app.py` (follow existing imports ordering).
- Emit a real-time event from code:
  - Use the global `redis_service` from `services/redis_service.py` and call `publish_event(event_type, data, target_user_id=..., target_role=...)`.
  - Example channel outcome: `publish_event('points_awarded', payload, target_user_id='123', target_role='employee')` will publish to `user:employee:123` and broadcast leaderboard update.

**Files to inspect for patterns**
- `app.py` — startup, blueprint registration, Socket.IO handlers
- `services/redis_service.py` — how events are published and channel naming
- `services/socketio_service.py` — how messages are consumed and routed
- `extensions.py`, `config.py` — app-level extensions and configuration
- Example module: `pmarch/README.md` and `pmarch/` code show service-layer separation and conventions for request handling.

**Safety notes for edits**
- Avoid changing the order of `eventlet.monkey_patch()` or the `socketio` initialization; doing so can break real-time behavior.
- Do not enable Flask reloader (`use_reloader=True`) — it causes duplicate SocketIO listeners.
- Prefer using `redis_service.publish_event(...)` over direct `redis.publish(...)` to keep message format consistent.

If anything here is unclear or you'd like the instructions to cover other developer tasks (tests, CI, deployment), tell me which area to expand and I will iterate.
