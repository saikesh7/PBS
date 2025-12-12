"""
Presales Main Blueprint
Initializes the presales blueprint and registers all sub-modules
"""
from flask import Blueprint
import os

current_dir = os.path.dirname(os.path.abspath(__file__))

presales_bp = Blueprint(
    'presales',
    __name__,
    url_prefix='/presales',
    template_folder=os.path.join(current_dir, 'templates'),
    static_folder=os.path.join(current_dir, 'static'),
    static_url_path='/presales/static'
)

# ✅ Register attachment routes
from .presales_attachments import register_attachment_routes
register_attachment_routes(presales_bp)

# ✅ Register validator routes
from .presales_validators import register_validator_routes
register_validator_routes(presales_bp)

# Routes registered successfully

# Import other route modules
from . import presales_dashboard
from . import presales_requests
from . import presales_api
from . import presales_notifications
from . import presales_employees
from . import presales_realtime_stats
