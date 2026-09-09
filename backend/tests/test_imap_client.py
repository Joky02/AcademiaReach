from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.services import imap_client, reply_tracker


class IMAPClientTests(unittest.TestCase):
    def test_creates_ssl_client_through_http_proxy(self):
        client = MagicMock()
        with patch.object(imap_client, "HTTPConnectIMAP4SSL", return_value=client) as factory:
            result = imap_client.create_imap_client({
                "host": "imap.example.com",
                "port": 993,
                "use_ssl": True,
                "proxy_enabled": True,
                "proxy_host": "host.docker.internal",
                "proxy_port": 10809,
            }, timeout=12)

        self.assertIs(result, client)
        factory.assert_called_once_with(
            "imap.example.com",
            993,
            timeout=12,
            proxy_host="host.docker.internal",
            proxy_port=10809,
        )

    def test_reply_tracker_inherits_smtp_proxy_for_legacy_config(self):
        with patch.object(reply_tracker, "load_yaml_config", return_value={
            "smtp": {
                "proxy_enabled": True,
                "proxy_host": "host.docker.internal",
                "proxy_port": 10809,
            },
            "imap": {"host": "imap.example.com"},
        }):
            config = reply_tracker._get_imap_config()

        self.assertTrue(config["proxy_enabled"])
        self.assertEqual(config["proxy_port"], 10809)


if __name__ == "__main__":
    unittest.main()
