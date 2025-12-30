from flask import Blueprint
import os

current_dir = os.path.dirname(os.path.abspath(__file__))

pm_bp = Blueprint(
    'pm',
    __name__,
    url_prefix='/pm',
    template_folder=os.path.join(current_dir, 'templates'),
    static_folder=os.path.join(current_dir, 'static'),
    static_url_path='/pm/static'
)

# Register attachment routes
from .pm_attachments import register_attachment_routes
register_attachment_routes(pm_bp)

# Import other routes
from . import pm_dashboard
from . import pm_requests
from . import pm_awards
from . import pm_bulk
from . import pm_employees
from . import pm_api