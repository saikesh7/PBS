from flask import Blueprint
import os

# Get the current directory path
current_dir = os.path.dirname(os.path.abspath(__file__))

# Create main blueprint
central_bp = Blueprint('central', __name__, url_prefix='/central',
                      template_folder=os.path.join(current_dir, 'templates'),
                      static_folder=os.path.join(current_dir, 'static'),
                      static_url_path='/central/static')

# Import routes after blueprint creation to avoid circular imports
from . import central_routes
from . import central_config
from . import central_bonus
from . import central_export
from . import central_leaderboard  # Optimized leaderboard with batch queries

__all__ = ['central_bp']