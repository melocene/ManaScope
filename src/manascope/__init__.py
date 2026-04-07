"""manascope: MTG deck analysis toolkit.

Configures UTF-8 stdout encoding at import time and exports the package
version (``__version__``), the default SQLite cache path (``DB_PATH``),
and a safety cap for HTTP response bodies (``MAX_RESPONSE_BYTES``).
"""

import io
import sys
from pathlib import Path

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

__version__ = "0.1.0"

DB_PATH = Path(".cache/cache.db")

# Safety cap for HTTP response bodies before JSON parsing (2 MB).
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
