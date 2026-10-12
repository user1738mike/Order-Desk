"""Real loopback port ownership must fail before isolated gate provisioning."""

import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quality_gates import require_available_ports  # noqa: E402


class QualityPortTests(unittest.TestCase):
    def test_existing_listener_is_refused_without_modifying_it(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as owner:
            owner.bind(("127.0.0.1", 0))
            owner.listen()
            port = owner.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, f"port {port} is unavailable"):
                require_available_ports((port,))
            self.assertEqual(owner.getsockname()[1], port)

    def test_released_loopback_port_is_available(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as owner:
            owner.bind(("127.0.0.1", 0))
            port = owner.getsockname()[1]
        require_available_ports((port,))
