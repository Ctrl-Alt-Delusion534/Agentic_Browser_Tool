import threading
import time
import pytest
import uvicorn
from company_portal.server import app


@pytest.fixture(scope="session", autouse=True)
def live_server():
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/api/invoices", timeout=0.5)
        # server already active on port 8000
        yield
        return
    except Exception:
        pass

    # start live server
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # poll server ready
    for _ in range(30):
        time.sleep(0.1)
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/invoices", timeout=0.2)
            break
        except Exception:
            pass

    yield
    # stop live server
    server.should_exit = True
