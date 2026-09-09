from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.services.smtp_client import (
    SMTPProxyError,
    describe_smtp_connection_error,
    open_http_tunnel,
)


class FakeSocket:
    def __init__(self, response: bytes):
        self.response = bytearray(response)
        self.sent = b""
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, size: int) -> bytes:
        if not self.response:
            return b""
        data = bytes(self.response[:size])
        del self.response[:size]
        return data

    def close(self) -> None:
        self.closed = True


class HTTPConnectTests(unittest.TestCase):
    def test_gmail_address_error_recommends_proxy(self):
        error = OSError(99, "Cannot assign requested address")

        message = describe_smtp_connection_error(error, {
            "host": "smtp.gmail.com",
            "proxy_enabled": False,
        })

        self.assertIn("开启 SMTP 代理", message)

    def test_opens_connect_tunnel(self):
        sock = FakeSocket(b"HTTP/1.1 200 Connection established\r\nX-Test: yes\r\n\r\n")
        with patch("backend.services.smtp_client.socket.create_connection", return_value=sock):
            result = open_http_tunnel(
                "smtp.gmail.com", 465, "host.docker.internal", 10809, 10
            )

        self.assertIs(result, sock)
        self.assertIn(b"CONNECT smtp.gmail.com:465 HTTP/1.1", sock.sent)
        self.assertIn(b"Host: smtp.gmail.com:465", sock.sent)
        self.assertFalse(sock.closed)

    def test_rejects_failed_connect_tunnel(self):
        sock = FakeSocket(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        with (
            patch("backend.services.smtp_client.socket.create_connection", return_value=sock),
            self.assertRaises(SMTPProxyError),
        ):
            open_http_tunnel("smtp.gmail.com", 465, "proxy", 10809, 10)

        self.assertTrue(sock.closed)


if __name__ == "__main__":
    unittest.main()
