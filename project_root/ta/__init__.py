from .ta_main import ta_bp

# Import routes to register them with the blueprint
from . import updater_routes
from . import validator_routes

__all__ = ['ta_bp']