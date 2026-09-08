import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from enroll_helper.config import DEFAULT_KEYWORDS
from enroll_helper.mockserver import MockTisState, make_handler
from enroll_helper.session import build_client
from enroll_helper.tis.client import TisClient
from enroll_helper.tis.endpoints import Endpoints


@pytest.fixture()
def mock():
    state = MockTisState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    handle = SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", state=state)
    try:
        yield handle
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def tis(mock):
    client = build_client(mock.url, {"MOCKSESSION": "ok"}, timeout_s=5)
    return TisClient(client, Endpoints(), DEFAULT_KEYWORDS)


@pytest.fixture()
def make_settings():
    from enroll_helper.config import Settings

    def _mk(**kw):
        defaults = dict(
            base_url="http://127.0.0.1:1",
            interval_ms=5,
            discovery_interval_ms=1,
            auto_skip_conflict=True,
            retry_full=False,
            non_interactive=True,
            submit_target="rwtjzyx",
        )
        defaults.update(kw)
        return Settings(**defaults)

    return _mk
