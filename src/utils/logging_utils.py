"""
Logging utilities for consistent, readable terminal output
"""
import logging
from typing import Optional

MAX_LOG_LINE_LENGTH = 60

def truncate_log_message(message: str, max_length: int = MAX_LOG_LINE_LENGTH) -> str:
    """
    Truncate log messages to max_length, adding '...' if truncated.
    
    Args:
        message: The log message to truncate
        max_length: Maximum line length (default: 60)
    
    Returns:
        Truncated message
    """
    if len(message) <= max_length:
        return message
    
    # Truncate and add ellipsis
    return message[:max_length - 3] + '...'

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with consistent formatting and truncation.
    
    Usage:
        logger = get_logger(__name__)
        logger.info(truncate_log_message("Very long message here..."))
    """
    return logging.getLogger(name)

