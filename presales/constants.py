"""
Presales Constants
Centralized constants and configuration values
"""

# Error Messages
ERROR_MESSAGES = {
    'NOT_LOGGED_IN': 'You need to log in first',
    'ACCESS_DENIED': 'You do not have permission to perform this action',
    'REQUEST_NOT_FOUND': 'Request not found',
    'EMPLOYEE_NOT_FOUND': 'Employee not found',
    'CATEGORY_NOT_FOUND': 'Category not found',
    'INVALID_ACTION': 'Invalid action specified',
    'UNAUTHORIZED_REQUEST': 'You are not authorized to process this request',
    'CATEGORIES_NOT_FOUND': 'Presales categories not found. Please contact HR.',
    'PROCESSING_ERROR': 'An error occurred while processing the request',
    'LOADING_ERROR': 'An error occurred while loading the page',
}

# Success Messages
SUCCESS_MESSAGES = {
    'REQUEST_APPROVED': 'Request approved! {points} points awarded to {employee_name}',
    'REQUEST_REJECTED': 'Request rejected',
}

# Flash Message Categories
FLASH_CATEGORIES = {
    'SUCCESS': 'success',
    'ERROR': 'danger',
    'WARNING': 'warning',
    'INFO': 'info',
}

# Request Status
REQUEST_STATUS = {
    'PENDING': 'Pending',
    'APPROVED': 'Approved',
    'REJECTED': 'Rejected',
}

# Presales Category Codes
PRESALES_CATEGORY_CODES = [
    'presales_partial',  # Pre-Sales contribution (Partly)
    'presales_adhoc',    # Pre-Sales contribution (ad-hoc support)
    'presales_rfp'       # Pre-Sales/RFP
]

# Points Configuration
PRESALES_POINTS_CONFIG = {
    'presales_partial': 150,
    'presales_adhoc': 50,
    'presales_rfp': 500
}
# Request limits are unlimited (no hardcoded limits)

# List of all grades in the system
ALL_GRADES = ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']

# Grade Minimum Expectations (for quarterly points)
GRADE_MINIMUM_EXPECTATIONS = {
    'A1': 0, 'B1': 0, 'B2': 0, 'C1': 1000, 
    'C2': 1500, 'D1': 1500, 'D2': 1500
}

# File Upload Configuration
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
VIEWABLE_CONTENT_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf']

# Pagination
DEFAULT_PAGE_SIZE = 25
PROCESSED_REQUESTS_LIMIT = 200

# Real-time Events
REALTIME_EVENTS = {
    'REQUEST_APPROVED': 'employee_request_approved',
    'REQUEST_REJECTED': 'employee_request_rejected',
    'NEW_REQUEST': 'employee_request_raised',
    'LEADERBOARD_UPDATE': 'leaderboard_update',
}
