"""
PM Constants
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
    'CATEGORIES_NOT_FOUND': 'PM categories not found. Please contact HR.',
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

# PM Category Codes - REMOVED: Now fetched dynamically from hr_categories
# Categories are fetched using get_pm_categories() helper function

# Points Configuration - REMOVED: Points are now defined in hr_categories collection
# Each category in hr_categories has its own points configuration

# Grade Configuration - Simplified to remove hardcoded category references
# Points per request are now fetched from hr_categories collection
GRADE_CONFIG = {
    'A1': {'quarterly_points_limit': 999999, 'request_limit': 9999},
    'B1': {'quarterly_points_limit': 999999, 'request_limit': 9999},
    'B2': {'quarterly_points_limit': 999999, 'request_limit': 9999},
    'C1': {'quarterly_points_limit': 999999, 'request_limit': 9999},
    'C2': {'quarterly_points_limit': 999999, 'request_limit': 9999},
    'D1': {'quarterly_points_limit': 999999, 'request_limit': 9999},
    'D2': {'quarterly_points_limit': 999999, 'request_limit': 9999}
}

# List of all grades in the system
ALL_GRADES = ['A1', 'B1', 'B2', 'C1', 'C2', 'D1', 'D2']

# Grade Minimum Expectations (for quarterly points)
GRADE_MINIMUM_EXPECTATIONS = {
    'A1': 500, 'B1': 500, 'B2': 500, 'C1': 1000, 
    'C2': 1000, 'D1': 1000, 'D2': 500
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
