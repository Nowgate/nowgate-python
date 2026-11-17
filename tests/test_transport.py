"""The default transport, urllib, against a local server: every answer returned as it is,
redirects not followed, and no answer raised as an OSError, which the client retries."""

from __future__ import annotations

import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

from nowgate import APIConnectionError, Nowgate, Request, UrllibTransport

from .fake import KEY

SEEN: List[Dict[str, Any]] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.answer()

    def do_POST(self) -> None:
        self.answer()

    def answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        SEEN.append({"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(length)})
        if self.path == "/v1/slow":
            time.sleep(0.5)
        if self.path == "/v1/moved":
            self.send_response(302)
            self.send_header("Location", "/v1/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        status = 404 if self.path == "/v1/missing" else 200
        body = b'{"ok":true}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Request-Id", "req_local")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


class Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # the slow answer's client has gone: that's the test


class Transport(unittest.TestCase):
    server: ThreadingHTTPServer
    base: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        SEEN.clear()

    def send(self, method: str, path: str, body: Any = None, timeout: float = 5) -> Any:
        headers = {"Authorization": "Bearer x", "User-Agent": "nowgate-python/test", "Content-Type": "application/json"}
        return UrllibTransport()(Request(method=method, url=self.base + path, headers=headers, body=body, timeout=timeout))

    def test_an_answer_is_returned_as_it_is_with_lowercase_headers(self) -> None:
        answer = self.send("POST", "/payments", b'{"a":1}')
        self.assertEqual(answer.status, 200)
        self.assertEqual(answer.body, b'{"ok":true}')
        self.assertEqual(answer.headers["x-request-id"], "req_local")
        self.assertEqual(answer.reason, "OK")
        self.assertEqual(SEEN[0]["body"], b'{"a":1}')
        self.assertEqual(SEEN[0]["headers"]["User-Agent"], "nowgate-python/test")
        self.assertEqual(SEEN[0]["headers"]["Authorization"], "Bearer x")

    def test_a_failure_status_is_an_answer_not_an_exception(self) -> None:
        answer = self.send("GET", "/missing")
        self.assertEqual(answer.status, 404)
        self.assertEqual(answer.body, b'{"ok":true}')

    def test_a_redirect_isnt_followed(self) -> None:
        answer = self.send("GET", "/moved")
        self.assertEqual(answer.status, 302)
        self.assertEqual(answer.headers["location"], "/v1/elsewhere")
        self.assertEqual([s["path"] for s in SEEN], ["/v1/moved"])

    def test_no_answer_is_an_os_error(self) -> None:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with self.assertRaises(OSError):
            UrllibTransport()(Request(method="GET", url=f"http://127.0.0.1:{port}/v1", headers={}, body=None, timeout=5))
        with self.assertRaises(OSError):
            self.send("GET", "/slow", timeout=0.1)

    def test_the_client_retries_over_it_then_reports_the_timeout(self) -> None:
        client = Nowgate(f"ngk_test_{KEY[12:]}", base_url=self.base, timeout=0.1, max_retries=1)
        client._requester._sleep = lambda seconds: None
        with self.assertRaisesRegex(APIConnectionError, "didn't answer within 0.1 s"):
            client._requester.request("GET", "/slow")
        self.assertEqual(len(SEEN), 2)
        self.assertEqual(client.status.retrieve(), {"ok": True})


if __name__ == "__main__":
    unittest.main()
