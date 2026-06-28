import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docserver import server, state


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


class TestStopDaemon(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("DOC_SERVER_HOME", None)

    def _spawn_holder(self, port):
        # A child process that binds the port and blocks, standing in for the daemon.
        code = (
            "import socket,time;"
            f"s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
            f"s.bind(('127.0.0.1',{port}));s.listen(1);time.sleep(60)"
        )
        proc = subprocess.Popen([sys.executable, "-c", code])
        for _ in range(40):
            if not server.is_port_free(port):
                break
            time.sleep(0.05)
        return proc

    def test_stop_daemon_kills_pid_and_frees_port(self):
        port = _free_port()
        proc = self._spawn_holder(port)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        state.set_daemon_pid(proc.pid)

        self.assertTrue(server.is_port_free(port) is False)
        freed = server.stop_daemon(self._tmp_home(), port)
        self.assertTrue(freed)
        self.assertTrue(server.is_port_free(port))

    def test_stop_daemon_noop_when_no_pid(self):
        # No daemon recorded, nothing listening: returns True (port already free).
        self.assertTrue(server.stop_daemon(self._tmp_home(), _free_port()))

    def _tmp_home(self):
        from pathlib import Path
        return Path(self._tmp.name)


if __name__ == "__main__":
    unittest.main()
