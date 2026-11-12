"""Production logging configuration."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

def setup_logging(app):
    """Configure production-grade logging for the Flask application.
    
    Args:
        app: Flask application instance
    """
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler - rotating by size
    app_log_handler = RotatingFileHandler(
        log_dir / 'app.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    app_log_handler.setLevel(log_level)
    app_log_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    app_log_handler.setFormatter(app_log_formatter)
    root_logger.addHandler(app_log_handler)
    
    # Error log handler - rotating daily
    error_log_handler = TimedRotatingFileHandler(
        log_dir / 'error.log',
        when='midnight',
        interval=1,
        backupCount=30
    )
    error_log_handler.setLevel(logging.ERROR)
    error_log_handler.setFormatter(app_log_formatter)
    root_logger.addHandler(error_log_handler)
    
    # Access log handler for API requests
    access_log_handler = RotatingFileHandler(
        log_dir / 'access.log',
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    access_log_handler.setLevel(logging.INFO)
    access_formatter = logging.Formatter(
        '%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    access_log_handler.setFormatter(access_formatter)
    
    # Create access logger
    access_logger = logging.getLogger('access')
    access_logger.setLevel(logging.INFO)
    access_logger.addHandler(access_log_handler)
    access_logger.propagate = False
    
    # Suppress noisy third-party loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    app.logger.info(f"Logging configured - Level: {log_level}")
    
    return root_logger
