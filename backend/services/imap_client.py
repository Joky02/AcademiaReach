"""IMAP client construction with optional HTTP CONNECT proxying."""

from __future__ import annotations

import imaplib
import socket

from backend.services.smtp_client import open_http_tunnel


class HTTPConnectIMAP4(imaplib.IMAP4):
    def __init__(self, *args, proxy_host: str, proxy_port: int, **kwargs):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        super().__init__(*args, **kwargs)

    def _create_socket(self, timeout: float | None) -> socket.socket:
        return open_http_tunnel(
            self.host,
            self.port,
            self.proxy_host,
            self.proxy_port,
            timeout or socket.getdefaulttimeout() or 30,
        )


class HTTPConnectIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, *args, proxy_host: str, proxy_port: int, **kwargs):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        super().__init__(*args, **kwargs)

    def _create_socket(self, timeout: float | None) -> socket.socket:
        raw_socket = open_http_tunnel(
            self.host,
            self.port,
            self.proxy_host,
            self.proxy_port,
            timeout or socket.getdefaulttimeout() or 30,
        )
        return self.ssl_context.wrap_socket(raw_socket, server_hostname=self.host)


def create_imap_client(imap_cfg: dict, timeout: float = 30) -> imaplib.IMAP4:
    """Create an IMAP connection using the supplied app config."""
    host = imap_cfg["host"]
    use_ssl = imap_cfg.get("use_ssl", True)
    port = imap_cfg.get("port", 993 if use_ssl else 143)
    proxy_enabled = imap_cfg.get("proxy_enabled", False)
    proxy_kwargs = {}
    if proxy_enabled:
        proxy_kwargs = {
            "proxy_host": imap_cfg.get("proxy_host", "host.docker.internal"),
            "proxy_port": imap_cfg.get("proxy_port", 10809),
        }
    if use_ssl:
        imap_class = HTTPConnectIMAP4SSL if proxy_enabled else imaplib.IMAP4_SSL
    else:
        imap_class = HTTPConnectIMAP4 if proxy_enabled else imaplib.IMAP4
    return imap_class(host, port, timeout=timeout, **proxy_kwargs)
