import os
import tempfile
from pathlib import Path
from uuid import uuid4

TEST_ROOT = Path(tempfile.gettempdir()) / f"mystery-atlas-tests-{uuid4()}"
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["MYSTERY_ATLAS_DATABASE_URL"] = f"sqlite:///{(TEST_ROOT / 'test.db').as_posix()}"
os.environ["MYSTERY_ATLAS_UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["MYSTERY_ATLAS_SESSION_SECRET"] = "test-session-secret-with-at-least-32-bytes"
