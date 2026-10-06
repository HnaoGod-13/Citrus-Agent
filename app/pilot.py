"""Authenticated enterprise pilot, separate from the public preview entry."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Runtime paths are read by agent modules at import time.
load_dotenv(ROOT / ".env", override=False)
os.environ["CITRUS_AUTH_REQUIRED"] = "true"

from app.main import main


if __name__ == "__main__":
    main(require_platform_login=True)
