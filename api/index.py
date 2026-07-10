"""Vercel Python entrypoint — re-exports the FastAPI app from server/app.py.

Vercel bundles the whole repo into the function (minus vercel.json
excludeFiles), so server/app.py finds data/ and scripts/ at their normal
relative locations. The only deployment-specific code is this import shim;
the API itself has exactly one definition.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from app import app  # noqa: E402,F401
