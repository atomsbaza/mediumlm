import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from mediumlm import browser


class _EchoCookieHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        cookie_header = self.headers.get("Cookie", "no-cookie")
        body = (
            f"<html><head><title>echo</title></head>"
            f"<body>{cookie_header}</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # silence default per-request stderr logging


def test_fetch_page_injects_cookies_into_the_request():
    server = HTTPServer(("127.0.0.1", 0), _EchoCookieHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser.fetch_page(
            f"http://127.0.0.1:{port}/",
            cookies=[
                {
                    "name": "probe",
                    "value": "hello123",
                    "domain": "127.0.0.1",
                    "path": "/",
                    "secure": False,
                }
            ],
        )
        assert result.status == 200
        assert "hello123" in result.html
        assert result.title == "echo"
    finally:
        server.shutdown()
        thread.join()


def test_browser_session_fetches_multiple_pages_in_one_session():
    server = HTTPServer(("127.0.0.1", 0), _EchoCookieHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with browser.BrowserSession(
            cookies=[
                {
                    "name": "probe",
                    "value": "hello123",
                    "domain": "127.0.0.1",
                    "path": "/",
                    "secure": False,
                }
            ],
            settle_ms=100,
        ) as session:
            first = session.fetch(f"http://127.0.0.1:{port}/first")
            second = session.fetch(f"http://127.0.0.1:{port}/second")
        assert first.status == 200
        assert second.status == 200
        assert "hello123" in first.html
        assert "hello123" in second.html
        assert first.title == "echo"
        assert second.title == "echo"
    finally:
        server.shutdown()
        thread.join()
