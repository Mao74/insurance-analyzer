"""
Security audit logging utility  
Logs security-relevant events for monitoring and compliance
"""
import logging
from datetime import datetime
from typing import Optional

# Configure security audit logger
security_logger = logging.getLogger("security.audit")
security_logger.setLevel(logging.INFO)

# Create formatters
formatter = logging.Formatter(
    '%(asctime)s - SECURITY_AUDIT - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# File handler for audit trail
try:
    file_handler = logging.FileHandler('logs/security_audit.log')
    file_handler.setFormatter(formatter)
    security_logger.addHandler(file_handler)
except:
    # If logs directory doesn't exist, log to console only
    pass

# Console handler (always)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
security_logger.addHandler(console_handler)


def log_login_attempt(username: str, ip_address: str, success: bool, reason: Optional[str] = None):
    """Log login attempt"""
    status = "SUCCESS" if success else "FAILED"
    message = f"Login {status} - Username: {username} - IP: {ip_address}"
    if reason:
        message += f" - Reason: {reason}"
    
    if success:
        security_logger.info(message)
    else:
        security_logger.warning(message)


def log_password_change(user_id: int, username: str, ip_address: str, success: bool):
    """Log password change"""
    status = "SUCCESS" if success else "FAILED"
    message = f"Password Change {status} - User ID: {user_id} - Username: {username} - IP: {ip_address}"
    security_logger.info(message)


def log_password_reset_request(email: str, ip_address: str):
    """Log password reset request"""
    security_logger.info(f"Password Reset Requested - Email: {email} - IP: {ip_address}")


def log_password_reset_complete(user_id: int, ip_address: str):
    """Log completed password reset"""
    security_logger.info(f"Password Reset Completed - User ID: {user_id} - IP: {ip_address}")


def log_file_upload(user_id: int, filename: str, file_size: int, mime_type: str, ip_address: str):
    """Log file upload"""
    security_logger.info(
        f"File Upload - User ID: {user_id} - File: {filename} - "
        f"Size: {file_size} bytes - MIME: {mime_type} - IP: {ip_address}"
    )


def log_analysis_create(user_id: int, analysis_id: int, policy_type: str, ip_address: str):
    """Log analysis creation"""
    security_logger.info(
        f"Analysis Created - User ID: {user_id} - Analysis ID: {analysis_id} - "
        f"Policy Type: {policy_type} - IP: {ip_address}"
    )


def log_analysis_delete(user_id: int, analysis_id: int, ip_address: str):
    """Log analysis deletion"""
    security_logger.warning(
        f"Analysis Deleted - User ID: {user_id} - Analysis ID: {analysis_id} - IP: {ip_address}"
    )


def log_admin_action(admin_id: int, action: str, target: str, ip_address: str):
    """Log administrative action"""
    security_logger.warning(
        f"ADMIN ACTION - Admin ID: {admin_id} - Action: {action} - "
        f"Target: {target} - IP: {ip_address}"
    )


def log_security_event(event_type: str, details: str, severity: str = "INFO"):
    """Log generic security event"""
    if severity.upper() == "WARNING":
        security_logger.warning(f"{event_type} - {details}")
    elif severity.upper() == "ERROR":
        security_logger.error(f"{event_type} - {details}")
    else:
        security_logger.info(f"{event_type} - {details}")
