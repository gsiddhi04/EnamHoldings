"""Tests never touch the real database, the network or a model: a temp DB, and every outside call is faked per test."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="finn-test-")
os.environ["FINN_DB"] = str(Path(_tmp) / "test.db")       # must be set before backend.config is imported
os.environ["FINN_NO_DOTENV"] = "1"                         # never load the real .env (and so never a real API key)
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("FINN_AUTO_REFRESH_HOURS", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from backend import db  # noqa: E402


@pytest.fixture()
def conn():
    """A clean database per test."""
    from backend import config
    for ext in ("", "-wal", "-shm"):
        Path(str(config.DB_PATH) + ext).unlink(missing_ok=True)
    db.init_db()
    with db.session() as c:
        yield c


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any outbound HTTP in a test is a bug: fail it as a connection error instead of touching the internet."""
    import requests

    def blocked(*a, **k):
        raise requests.ConnectionError("network is disabled in tests")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
