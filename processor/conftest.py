"""Pytest configuration for processor tests."""
import os
import tempfile
from unittest.mock import patch

# Create temp directories for testing
_test_dir = tempfile.mkdtemp(prefix='track2stem_test_')
_upload_dir = os.path.join(_test_dir, 'uploads')
_output_dir = os.path.join(_test_dir, 'outputs')
os.makedirs(_upload_dir, exist_ok=True)
os.makedirs(_output_dir, exist_ok=True)

# Patch os.makedirs during app import because the module creates /app/uploads
# and /app/outputs at import time, which don't exist in the test environment.
with patch('os.makedirs'):
    import app as app_module
    app_module.UPLOAD_FOLDER = _upload_dir
    app_module.OUTPUT_FOLDER = _output_dir
