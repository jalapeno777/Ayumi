"""Structured logging configuration for Ayumi modules."""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler


def setup_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    """Configure structured logging for all Ayumi modules.

    Sets up:
    - Console handler with formatted output
    - Rotating file handler (10MB, keep 5) at logs/ayumi_{date}.log
    - Logger hierarchy under 'ayumi'
    """
    os.makedirs(log_dir, exist_ok=True)
    log_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Root ayumi logger
    root = logging.getLogger("ayumi")
    root.setLevel(log_level)
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler
    today = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(log_dir, f"ayumi_{today}.log")
    file_handler = RotatingFileHandler(
        file_path, maxBytes=10 * 1024 * 1024, backupCount=5,
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Prevent double-propagation
    root.propagate = False
