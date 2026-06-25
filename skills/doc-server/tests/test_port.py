import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docserver import server


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestPort(unittest.TestCase):
    def test_free_port_is_free(self):
        p = _free_port()
        self.assertTrue(server.is_port_free(p))

    def test_occupied_port_not_free(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertFalse(server.is_port_free(port))
        finally:
            s.close()

    def test_resolve_port_binds_when_free(self):
        p = _free_port()
        port, action = server.resolve_port(p)
        self.assertEqual(port, p)
        self.assertEqual(action, "bind")

    def test_resolve_port_scans_past_stranger(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            chosen, action = server.resolve_port(port)
            self.assertNotEqual(chosen, port)
            self.assertEqual(action, "bind")
        finally:
            s.close()

    def test_probe_health_false_when_nothing_listening(self):
        self.assertFalse(server.probe_health(_free_port()))


if __name__ == "__main__":
    unittest.main()
