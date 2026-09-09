"""SMTP client construction with optional HTTP CONNECT proxying."""

from __future__ import annotations

import errno
import smtplib
import socket


class SMTPProxyError(OSError):
    """Raised when the configured proxy cannot establish a tunnel."""


def describe_smtp_connection_error(error: OSError, smtp_cfg: dict) -> str:
    """Turn low-level socket errors into actionable SMTP guidance."""
    if error.errno == errno.EADDRNOTAVAIL:
        if str(smtp_cfg.get("host", "")).lower() == "smtp.gmail.com" and not smtp_cfg.get("proxy_enabled"):
            return "Gmail SMTP 直连不可用，请在设置中开启 SMTP 代理后重试"
        return "SMTP 出站连接不可用，请检查 Docker 网络和 SMTP 代理设置"
    return f"SMTP 网络连接失败: {error}"


def _proxy_authority(host: str, port: int) -> str:
    if not host or "\r" in host or "\n" in host:
        raise ValueError("SMTP proxy host is invalid")
    if not 1 <= port <= 65535:
        raise ValueError("SMTP proxy port is invalid")
    return f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"


def open_http_tunnel(
    target_host: str,
    target_port: int,
    proxy_host: str,
    proxy_port: int,
    timeout: float,
) -> socket.socket:
    """Open a TCP tunnel through an unauthenticated HTTP CONNECT proxy."""
    target = _proxy_authority(target_host, target_port)
    proxy = _proxy_authority(proxy_host, proxy_port)
    sock = socket.create_connection((proxy_host, proxy_port), timeout)
    try:
        request = (
            f"CONNECT {target} HTTP/1.1\r\n"
            f"Host: {target}\r\n"
            "Proxy-Connection: keep-alive\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))

        response = bytearray()
        while not response.endswith(b"\r\n\r\n"):
            chunk = sock.recv(1)
            if not chunk:
                raise SMTPProxyError(f"SMTP proxy {proxy} closed the connection")
            response.extend(chunk)
            if len(response) > 65536:
                raise SMTPProxyError(f"SMTP proxy {proxy} returned an oversized response")

        status_line = bytes(response).split(b"\r\n", 1)[0]
        parts = status_line.split(b" ", 2)
        if len(parts) < 2 or not parts[1].isdigit() or not 200 <= int(parts[1]) < 300:
            detail = status_line.decode("ascii", "replace")
            raise SMTPProxyError(f"SMTP proxy tunnel failed: {detail}")
        return sock
    except Exception:
        sock.close()
        raise


class HTTPConnectSMTP(smtplib.SMTP):
    def __init__(self, *args, proxy_host: str, proxy_port: int, **kwargs):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        super().__init__(*args, **kwargs)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        return open_http_tunnel(host, port, self.proxy_host, self.proxy_port, timeout)


class HTTPConnectSMTPSSL(smtplib.SMTP_SSL):
    def __init__(self, *args, proxy_host: str, proxy_port: int, **kwargs):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        super().__init__(*args, **kwargs)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        raw_socket = open_http_tunnel(host, port, self.proxy_host, self.proxy_port, timeout)
        return self.context.wrap_socket(raw_socket, server_hostname=host)


def create_smtp_client(smtp_cfg: dict, timeout: float = 30) -> smtplib.SMTP:
    """Create and secure an SMTP connection using the supplied app config."""
    host = smtp_cfg["host"]
    port = smtp_cfg.get("port", 587)
    proxy_enabled = smtp_cfg.get("proxy_enabled", False)
    proxy_kwargs = {}
    if proxy_enabled:
        proxy_kwargs = {
            "proxy_host": smtp_cfg.get("proxy_host", "host.docker.internal"),
            "proxy_port": smtp_cfg.get("proxy_port", 10809),
        }

    if smtp_cfg.get("use_tls", True):
        smtp_class = HTTPConnectSMTP if proxy_enabled else smtplib.SMTP
        server = smtp_class(host, port, timeout=timeout, **proxy_kwargs)
        server.starttls()
        return server

    smtp_class = HTTPConnectSMTPSSL if proxy_enabled else smtplib.SMTP_SSL
    return smtp_class(host, port, timeout=timeout, **proxy_kwargs)
