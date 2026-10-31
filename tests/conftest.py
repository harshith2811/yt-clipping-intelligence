"""
Pytest configuration and environment fixtures for YT Clipping Intelligence.
"""

import os
import pytest

# Ensure testing execution mode for synthetic test harnesses
os.environ.setdefault("YT_EXECUTION_MODE", "test")
os.environ.setdefault("YT_ALLOW_SYNTHETIC", "1")
