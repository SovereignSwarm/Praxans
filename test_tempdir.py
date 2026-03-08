import os
import shutil
import uuid
from contextlib import contextmanager


_WORKSPACE_TEMP_ROOT = os.path.join(os.path.dirname(__file__), "test-scratch", "test-temp")


@contextmanager
def workspace_tempdir(prefix: str = "tmp"):
    """Create a temp directory under the writable workspace without tempfile ACL quirks."""
    os.makedirs(_WORKSPACE_TEMP_ROOT, exist_ok=True)
    temp_dir = os.path.join(_WORKSPACE_TEMP_ROOT, f"{prefix}-{uuid.uuid4().hex}")
    os.makedirs(temp_dir, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
