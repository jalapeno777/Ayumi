"""Pytest configuration for Ayumi forex-bot tests."""
import os
import sys

# Add project paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src/forex-bot"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
