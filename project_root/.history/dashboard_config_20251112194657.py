# dashboard_config.py
"""
Configuration file for dashboard access mapping
Maps dashboard_access values to their corresponding routes and display names

Location: PROJECT_ROOT/dashboard_config.py
"""

# Standardized dashboard names (use these in dashboard_access field)
DASHBOARD_NAMES = [
    'Central',
    'HR',
    'HR - Updater',      # ✨ HR UPDATER
    'HR - Validator',    # ✨ HR VALIDATOR
    'DP',
    'Employee',
    'PM/Arch - Updater',
    'PM/Arch - Validator',
    'PM - Updater',
    'PM - Validator',
    'Marketing - Updater',
    'Marketing - Validator',
    'Presales - Updater',
    'Presales - Validator',
    'PMO - Updater',
    'PMO - Validator',
    'TA - Updater',
    'TA - Validator',
    'L&D - Updater',
    'L&D - Validator',
    'ld_va'
]

# Mapping of dashboard_access values to route information
DASHBOARD_ROUTES = {
    'Central': {
        'url': 'central.dashboard',
        'icon': 'fas fa-globe',
        'display_name': 'Central Dashboard',
        'short_name': 'Central',
        'params': {}
    },
    'HR': {
        'url': 'hr.pbs_analytics',
        'icon': 'fas fa-users-cog',
        'display_name': 'HR Dashboard',
        'short_name': 'HR',
        'params': {}
    },
    'DP': {
        'url': 'pm.dashboard',
        'icon': 'fas fa-project-diagram',
        'display_name': 'DP Dashboard',
        'short_name': 'DP',
        'params': {}
    },
    'Employee': {
        'url': 'employee.dashboard',
        'icon': 'fas fa-user',
        'display_name': 'Employee Dashboard',
        'short_name': 'Employee',
        'params': {}
    },
    'PM/Arch - Updater': {
        'url': 'pm_arch.dashboard',
        'icon': 'fas fa-user-shield',
        'display_name': 'PM/Arch Updater',
        'short_name': 'PM/Arch Updater',
        'params': {}
    },
    'PM/Arch - Validator': {
        'url': 'pm_arch.validator_dashboard',
        'icon': 'fas fa-user-check',
        'display_name': 'PM/Arch Validator',
        'short_name': 'PM/Arch Validator',
        'params': {}
    },
    'PM - Updater': {
        'url': 'pm.dashboard',
        'icon': 'fas fa-user-tie',
        'display_name': 'PM Updater',
        'short_name': 'PM Updater',
        'params': {}
    },
    'PM - Validator': {
        'url': 'pm.validator_dashboard',
        'icon': 'fas fa-user-check',
        'display_name': 'PM Validator',
        'short_name': 'PM Validator',
        'params': {}
    },
    'Marketing - Updater': {
        'url': 'market_manager.dashboard',
        'icon': 'fas fa-bullhorn',
        'display_name': 'Marketing Updater',
        'short_name': 'Marketing Updater',
        'params': {}
    },
    'Marketing - Validator': {
        'url': 'market_manager.validator_dashboard',
        'icon': 'fas fa-check-circle',
        'display_name': 'Marketing Validator',
        'short_name': 'Marketing Validator',
        'params': {}
    },
    'Presales - Updater': {
        'url': 'presales.dashboard',
        'icon': 'fas fa-handshake',
        'display_name': 'Pre-sales Updater',
        'short_name': 'Pre-sales Updater',
        'params': {}
    },
    'Presales - Validator': {
        'url': 'presales.validator_dashboard',
        'icon': 'fas fa-user-check',
        'display_name': 'Pre-sales Validator',
        'short_name': 'Pre-sales Validator',
        'params': {}
    },
    'PMO - Updater': {
        'url': 'pmo.updater_dashboard',
        'icon': 'fas fa-tasks',
        'display_name': 'PMO Updater',
        'short_name': 'PMO Updater',
        'params': {}
    },
    'PMO - Validator': {
        'url': 'pmo.validator_dashboard',
        'icon': 'fas fa-clipboard-check',
        'display_name': 'PMO Validator',
        'short_name': 'PMO Validator',
        'params': {}
    },
    'TA - Updater': {
        'url': 'ta.dashboard',
        'icon': 'fas fa-user-plus',
        'display_name': 'TA Updater',
        'short_name': 'TA Updater',
        'params': {}
    },
    'TA - Validator': {
        'url': 'ta.validator_dashboard',
        'icon': 'fas fa-user-check',
        'display_name': 'TA Validator',
        'short_name': 'TA Validator',
        'params': {}
    },
    'L&D - Updater': {
        'url': 'ld.dashboard',
        'icon': 'fas fa-graduation-cap',
        'display_name': 'L&D Updater',
        'short_name': 'L&D Updater',
        'params': {}
    },
    'L&D - Validator': {
        'url': 'ld.validator_dashboard',
        'icon': 'fas fa-book-reader',
        'display_name': 'L&D Validator',
        'short_name': 'L&D Validator',
        'params': {}
    },
    'HR - Updater': {
        'url': 'hr_roles.updater_dashboard',
        'icon': 'fas fa-user-edit',
        'display_name': 'HR Updater',
        'short_name': 'HR Updater',
        'params': {}
    },
    'HR - Validator': {
        'url': 'hr_roles.validator_dashboard',
        'icon': 'fas fa-user-check',
        'display_name': 'HR Validator',
        'short_name': 'HR Validator',
        'params': {}
    },
}

# Alternative naming conventions (for backward compatibility)
DASHBOARD_ALIASES = {
    'PM/Arch awardee': 'PM/Arch - Updater',
    'PM/Arch Awardee': 'PM/Arch - Updater',
    'Marketing Awardee': 'Marketing - Updater',
    'Marketing awardee': 'Marketing - Updater',
    'PMO updator': 'PMO - Updater',
    'PMO Updator': 'PMO - Updater',
    'TA validator': 'TA - Validator',
    'TA Validator': 'TA - Validator',
    'L&D updator': 'L&D - Updater',
    'L&D Updator': 'L&D - Updater',
    'ld_va':'ld_validator',
    'Presales updator': 'Presales - Updater',
    'Presales Updator': 'Presales - Updater',
    'PM updator': 'PM - Updater',
    'PM Updator': 'PM - Updater',
    'PM validator': 'PM - Validator',
    'PM Validator': 'PM - Validator',
    'TA updator': 'TA - Updater',
    'TA Updator': 'TA - Updater',
    'PMO validator': 'PMO - Validator',
    'PMO Validator': 'PMO - Validator',
    'Presales validator': 'Presales - Validator',
    'Presales Validator': 'Presales - Validator',
    'Marketing validator': 'Marketing - Validator',
    'Marketing Validator': 'Marketing - Validator',
    'L&D validator': 'L&D - Validator',
    'L&D Validator': 'L&D - Validator',
    'PM/Arch validator': 'PM/Arch - Validator',
    'PM/Arch Validator': 'PM/Arch - Validator',
    # Database shorthand codes (lowercase)
    'pmo_up': 'PMO - Updater',
    'pmo_va': 'PMO - Validator',
    'ta_up': 'TA - Updater',
    'ta_va': 'TA - Validator',
    'employee_db': 'Employee',
    'pm_up': 'PM - Updater',
    'pm_va': 'PM - Validator',
    'HR updator': 'HR - Updater',      # ✨ Backward compatibility
    'HR Updator': 'HR - Updater',      # ✨ Backward compatibility
    'HR validator': 'HR - Validator',  # ✨ Backward compatibility
    'HR Validator': 'HR - Validator',  # ✨ Backward compatibility
}


# ============================================================================
# CORE HELPER FUNCTIONS
# ============================================================================

def normalize_dashboard_name(dashboard_name):
    """
    Normalize dashboard names for consistency
    Handles backward compatibility with old naming conventions
    
    Args:
        dashboard_name: The dashboard name from user's dashboard_access array
        
    Returns:
        Normalized dashboard name
    """
    # First check if it's already a valid name
    if dashboard_name in DASHBOARD_ROUTES:
        return dashboard_name
    
    # Check aliases
    if dashboard_name in DASHBOARD_ALIASES:
        return DASHBOARD_ALIASES[dashboard_name]
    
    # Return as-is if no mapping found
    return dashboard_name


def get_dashboard_config(dashboard_name):
    """
    Get the configuration for a dashboard
    
    Args:
        dashboard_name: The dashboard name from user's dashboard_access array
        
    Returns:
        Dictionary with dashboard configuration or None if not found
    """
    normalized_name = normalize_dashboard_name(dashboard_name)
    return DASHBOARD_ROUTES.get(normalized_name)


def get_user_dashboard_configs(dashboard_access_list):
    """
    Get all dashboard configurations for a user's dashboard_access list
    
    Args:
        dashboard_access_list: List of dashboard names from user document
        
    Returns:
        List of valid dashboard configurations
    """
    configs = []
    for dashboard_name in dashboard_access_list:
        config = get_dashboard_config(dashboard_name)
        if config:
            # Add the original name for reference
            config_with_name = config.copy()
            config_with_name['access_name'] = dashboard_name
            config_with_name['normalized_name'] = normalize_dashboard_name(dashboard_name)
            configs.append(config_with_name)
    return configs


def get_user_default_dashboard(user):
    """
    Get the default dashboard for a user based on their dashboard_access
    Returns the URL for url_for() function
    
    Args:
        user: User document from MongoDB
        
    Returns:
        String: URL endpoint (e.g., 'employee.dashboard')
    """
    from flask import url_for
    
    dashboard_access = user.get('dashboard_access', [])
    
    if not dashboard_access:
        return 'employee.dashboard'
    
    # Priority order - highest priority dashboards first
    priority_order = [
        'Employee',
        'Central',
        'HR',
        'DP',
        'PM/Arch - Validator',
        'PM - Validator',
        'Marketing - Validator',
        'Presales - Validator',
        'PMO - Validator',
        'TA - Validator',
        'L&D - Validator',
        'PM/Arch - Updater',
        'PM - Updater',
        'Marketing - Updater',
        'Presales - Updater',
        'PMO - Updater',
        'TA - Updater',
        'ld_updater',
        'ld_va'
        
    ]
    
    for dashboard_name in priority_order:
        if dashboard_name in dashboard_access:
            config = get_dashboard_config(dashboard_name)
            if config:
                return config['url']
    
    return 'employee.dashboard'


def get_redirect_for_unauthorized_user(user):
    """
    Get appropriate redirect URL for unauthorized access
    
    Args:
        user: User document from MongoDB
        
    Returns:
        String: Full URL path for redirect
    """
    from flask import url_for
    
    dashboard_access = user.get('dashboard_access', [])
    
    if not dashboard_access:
        try:
            return url_for('employee.dashboard')
        except:
            return '/employee/dashboard'
    
    # Priority order for redirect - highest priority dashboards first
    priority_order = [
        'Employee',
        'Central',
        'HR',
        'DP',
        'PM/Arch - Validator',
        'PM - Validator',
        'Marketing - Validator',
        'Presales - Validator',
        'PMO - Validator',
        'TA - Validator',
        'L&D - Validator',
        'PM/Arch - Updater',
        'PM - Updater',
        'Marketing - Updater',
        'Presales - Updater',
        'PMO - Updater',
        'TA - Updater',
        'L&D - Updater'
        
    ]
    
    for dashboard_name in priority_order:
        if dashboard_name in dashboard_access:
            config = get_dashboard_config(dashboard_name)
            if config:
                url_endpoint = config['url']
                try:
                    return url_for(url_endpoint)
                except Exception as e:
                    # If url_for fails, continue to next dashboard
                    continue
    
    # Fallback to employee dashboard
    try:
        return url_for('employee.dashboard')
    except:
        return '/employee/dashboard'


def check_user_dashboard_access(user, required_dashboard):
    """
    Check if a user has access to a specific dashboard
    
    Args:
        user: User document from MongoDB
        required_dashboard: Dashboard name to check (e.g., 'TA - Validator')
        
    Returns:
        Boolean: True if user has access, False otherwise
    """
    dashboard_access = user.get('dashboard_access', [])
    
    if not dashboard_access:
        return False
    
    # Normalize the required dashboard name
    normalized_required = normalize_dashboard_name(required_dashboard)
    
    # Check if user has this dashboard in their access list
    for user_dashboard in dashboard_access:
        normalized_user = normalize_dashboard_name(user_dashboard)
        if normalized_user == normalized_required:
            return True
    
    return False


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_all_user_dashboards(user):
    """
    Get all dashboard URLs that a user has access to
    
    Args:
        user: User document from MongoDB
        
    Returns:
        List of dictionaries with dashboard info
    """
    dashboard_access = user.get('dashboard_access', [])
    dashboards = []
    
    for dashboard_name in dashboard_access:
        config = get_dashboard_config(dashboard_name)
        if config:
            dashboards.append({
                'name': dashboard_name,
                'url': config['url'],
                'display_name': config['display_name'],
                'icon': config['icon']
            })
    
    return dashboards


def validate_dashboard_access_field(dashboard_access_list):
    """
    Validate a dashboard_access list and return warnings for invalid entries
    
    Args:
        dashboard_access_list: List of dashboard names
        
    Returns:
        Tuple: (valid_dashboards, invalid_dashboards)
    """
    valid = []
    invalid = []
    
    for dashboard_name in dashboard_access_list:
        config = get_dashboard_config(dashboard_name)
        if config:
            valid.append(dashboard_name)
        else:
            invalid.append(dashboard_name)
    
    return (valid, invalid)


# ============================================================================
# DEBUG FUNCTIONS
# ============================================================================

def debug_user_access(user):
    """
    Debug function to print user's dashboard access information
    
    Args:
        user: User document from MongoDB
    """
    print("="*60)
    print("USER DASHBOARD ACCESS DEBUG")
    print("="*60)
    print(f"User: {user.get('name')} ({user.get('email')})")
    print(f"Role: {user.get('role')}")
    print(f"Dashboard Access: {user.get('dashboard_access')}")
    print("\nDashboard Configurations:")
    
    dashboard_access = user.get('dashboard_access', [])
    for dashboard_name in dashboard_access:
        config = get_dashboard_config(dashboard_name)
        if config:
            print(f"  ✓ {dashboard_name} -> {config['url']}")
        else:
            print(f"  ✗ {dashboard_name} -> NOT FOUND")
    
    print(f"\nDefault Dashboard: {get_user_default_dashboard(user)}")
    print(f"Redirect URL: {get_redirect_for_unauthorized_user(user)}")
    print("="*60)