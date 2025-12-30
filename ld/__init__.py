from .ld_main import ld_bp

# Import routes to register them with the blueprint
from . import ld_updater_routes
from . import ld_validator_routes

__all__ = ['ld_bp']
