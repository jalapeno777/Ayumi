"""Centralized project root for path construction in tests."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # tests/ → project root
