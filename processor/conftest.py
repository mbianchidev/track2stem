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

# Patch module-level directory creation and folder constants before app import
with patch('os.makedirs'):
    import app as app_module
    app_module.UPLOAD_FOLDER = _upload_dir
    app_module.OUTPUT_FOLDER = _output_dir
