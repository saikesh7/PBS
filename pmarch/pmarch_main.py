"""
PM/Arch Main Blueprint
Initializes the PM/Arch blueprint and registers all sub-modules
"""
from flask import Blueprint
import os

current_dir = os.path.dirname(os.path.abspath(__file__))

pmarch_bp = Blueprint(
    'pm_arch',
    __name__,
    url_prefix='/pm-arch',
    template_folder=os.path.join(current_dir, 'templates'),
    static_folder=os.path.join(current_dir, 'static'),
    static_url_path='/pm-arch/static'
)

# Register attachment and validator routes
from .pmarch_attachments import register_attachment_routes
from .pmarch_validators import register_validator_routes

register_attachment_routes(pmarch_bp)
register_validator_routes(pmarch_bp)

# Import route modules
from . import pmarch_dashboard
from . import pmarch_requests
from . import pmarch_api
from . import pmarch_employees
