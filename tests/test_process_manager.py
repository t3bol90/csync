"""
Unit tests for csync.process_manager.ProcessManager.
Uses only stdlib unittest.mock — no pytest-mock.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import psutil
import pytest

from csync.process_manager import ProcessManager, DaemonInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_manager(tmp_path):
    """Return a ProcessManager whose daemon_dir is redirected to tmp_path."""
    pm = ProcessManager()
    pm.daemon_dir = tmp_path
    return pm


def make_info(pid=12345, local_path="/tmp/proj/", signature="csync-abc123def456"):
    return DaemonInfo(
        pid=pid,
        local_path=local_path,
        remote_target="user@host:/remote/",
        config_file=".csync.cfg",
        signature=signature,
        started_at=1700000000.0,
        sync_count=0,
    )


# ---------------------------------------------------------------------------
# ProcessManager.generate_signature()
# ---------------------------------------------------------------------------

class TestGenerateSignature:
    def test_signature_has_csync_prefix(self):
        pm = ProcessManager()
        sig = pm.generate_signature("/some/path")
        assert sig.startswith("csync-")

    def test_signature_consistent_for_same_path(self):
        pm = ProcessManager()
        sig1 = pm.generate_signature("/some/path")
        sig2 = pm.generate_signature("/some/path")
        assert sig1 == sig2

    def test_signature_different_for_different_paths(self):
        pm = ProcessManager()
        sig1 = pm.generate_signature("/path/one")
        sig2 = pm.generate_signature("/path/two")
        assert sig1 != sig2

    def test_signature_length(self):
        pm = ProcessManager()
        sig = pm.generate_signature("/any/path")
        # "csync-" (6 chars) + 12 hex chars = 18 total
        assert len(sig) == 18
        hex_part = sig[len("csync-"):]
        assert all(c in "0123456789abcdef" for c in hex_part)


# ---------------------------------------------------------------------------
# ProcessManager.is_process_running()
# ---------------------------------------------------------------------------

class TestIsProcessRunning:
    def test_returns_false_for_nonexistent_pid(self):
        pm = ProcessManager()
        # PID 9999999 cannot exist on any normal system
        assert pm.is_process_running(9999999) is False

    def test_returns_true_for_current_process(self):
        """Mock psutil.Process for the current PID so cmdline contains 'csync'."""
        pm = ProcessManager()
        current_pid = os.getpid()

        mock_proc = MagicMock()
        mock_proc.cmdline.return_value = ["python", "-m", "csync", "daemon"]
        mock_proc.is_running.return_value = True

        with patch("psutil.Process", return_value=mock_proc) as mock_cls:
            result = pm.is_process_running(current_pid)
            mock_cls.assert_called_once_with(current_pid)

        assert result is True

    def test_returns_false_when_psutil_raises_no_such_process(self):
        pm = ProcessManager()

        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(pid=42)):
            result = pm.is_process_running(42)

        assert result is False

    def test_returns_false_for_zombie(self):
        """A zombie process has status STATUS_ZOMBIE; cmdline is typically empty."""
        pm = ProcessManager()

        mock_proc = MagicMock()
        # Zombie processes usually return an empty cmdline
        mock_proc.cmdline.return_value = []
        mock_proc.is_running.return_value = True
        mock_proc.status.return_value = psutil.STATUS_ZOMBIE

        with patch("psutil.Process", return_value=mock_proc):
            result = pm.is_process_running(99)

        # "csync" is not in an empty cmdline string, so result is False
        assert result is False


# ---------------------------------------------------------------------------
# ProcessManager.write_daemon_info() / read_daemon_info()
# ---------------------------------------------------------------------------

class TestWriteAndReadDaemonInfo:
    def test_write_creates_pid_file(self, tmp_path):
        pm = make_manager(tmp_path)
        info = make_info()
        pm.write_daemon_info(info)

        pid_file = tmp_path / f"{info.signature}.pid"
        assert pid_file.exists()
        assert pid_file.read_text() == str(info.pid)

    def test_write_creates_json_info_file(self, tmp_path):
        pm = make_manager(tmp_path)
        info = make_info()
        pm.write_daemon_info(info)

        info_file = tmp_path / f"{info.signature}.json"
        assert info_file.exists()
        data = json.loads(info_file.read_text())
        assert data["pid"] == info.pid
        assert data["local_path"] == info.local_path
        assert data["remote_target"] == info.remote_target
        assert data["config_file"] == info.config_file
        assert data["signature"] == info.signature
        assert data["started_at"] == info.started_at
        assert data["sync_count"] == info.sync_count

    def test_read_returns_daemon_info(self, tmp_path):
        pm = make_manager(tmp_path)
        info = make_info()
        pm.write_daemon_info(info)

        result = pm.read_daemon_info(info.signature)
        assert result is not None
        assert result.pid == info.pid
        assert result.local_path == info.local_path
        assert result.remote_target == info.remote_target
        assert result.config_file == info.config_file
        assert result.signature == info.signature
        assert result.started_at == info.started_at
        assert result.sync_count == info.sync_count

    def test_read_returns_none_for_missing_file(self, tmp_path):
        pm = make_manager(tmp_path)
        result = pm.read_daemon_info("csync-nonexistent0")
        assert result is None

    def test_read_returns_none_for_corrupt_json(self, tmp_path):
        pm = make_manager(tmp_path)
        signature = "csync-corruptfile1"
        info_file = tmp_path / f"{signature}.json"
        info_file.write_text("{this is not valid json}")

        result = pm.read_daemon_info(signature)
        assert result is None


# ---------------------------------------------------------------------------
# ProcessManager.get_daemon_by_path()
# ---------------------------------------------------------------------------

class TestGetDaemonByPath:
    LOCAL_PATH = "/tmp/proj/"

    def _make_info_for_path(self, pm, local_path, pid=12345):
        """Build a DaemonInfo whose signature matches what the manager would compute."""
        signature = pm.generate_signature(local_path)
        return DaemonInfo(
            pid=pid,
            local_path=local_path,
            remote_target="user@host:/remote/",
            config_file=".csync.cfg",
            signature=signature,
            started_at=1700000000.0,
            sync_count=0,
        )

    def test_returns_none_when_no_info_file(self, tmp_path):
        pm = make_manager(tmp_path)
        result = pm.get_daemon_by_path(self.LOCAL_PATH)
        assert result is None

    def test_returns_none_when_process_not_running(self, tmp_path):
        pm = make_manager(tmp_path)
        info = self._make_info_for_path(pm, self.LOCAL_PATH)
        pm.write_daemon_info(info)

        with patch.object(pm, "is_process_running", return_value=False):
            result = pm.get_daemon_by_path(self.LOCAL_PATH)

        assert result is None

    def test_returns_daemon_info_when_running(self, tmp_path):
        pm = make_manager(tmp_path)
        info = self._make_info_for_path(pm, self.LOCAL_PATH)
        pm.write_daemon_info(info)

        with patch.object(pm, "is_process_running", return_value=True):
            result = pm.get_daemon_by_path(self.LOCAL_PATH)

        assert result is not None
        assert result.pid == info.pid
        assert result.local_path == info.local_path

    def test_cleans_up_stale_files(self, tmp_path):
        pm = make_manager(tmp_path)
        info = self._make_info_for_path(pm, self.LOCAL_PATH)
        pm.write_daemon_info(info)

        pid_file = tmp_path / f"{info.signature}.pid"
        json_file = tmp_path / f"{info.signature}.json"
        assert pid_file.exists()
        assert json_file.exists()

        with patch.object(pm, "is_process_running", return_value=False):
            pm.get_daemon_by_path(self.LOCAL_PATH)

        assert not pid_file.exists()
        assert not json_file.exists()


# ---------------------------------------------------------------------------
# ProcessManager.cleanup_daemon_files()
# ---------------------------------------------------------------------------

class TestCleanupDaemonFiles:
    def test_deletes_pid_and_json_files(self, tmp_path):
        pm = make_manager(tmp_path)
        info = make_info()
        pm.write_daemon_info(info)

        pid_file = tmp_path / f"{info.signature}.pid"
        json_file = tmp_path / f"{info.signature}.json"
        assert pid_file.exists()
        assert json_file.exists()

        pm.cleanup_daemon_files(info.signature)

        assert not pid_file.exists()
        assert not json_file.exists()

    def test_does_not_raise_when_files_absent(self, tmp_path):
        pm = make_manager(tmp_path)
        # Should complete without raising any exception
        pm.cleanup_daemon_files("csync-doesnotexist")


# ---------------------------------------------------------------------------
# ProcessManager.update_daemon_stats()
# ---------------------------------------------------------------------------

class TestUpdateDaemonStats:
    LOCAL_PATH = "/tmp/proj/"

    def _make_info_for_path(self, pm, local_path, pid=12345):
        """Build a DaemonInfo whose signature matches what the manager would compute."""
        signature = pm.generate_signature(local_path)
        return DaemonInfo(
            pid=pid,
            local_path=local_path,
            remote_target="user@host:/remote/",
            config_file=".csync.cfg",
            signature=signature,
            started_at=1700000000.0,
            sync_count=0,
        )

    def test_updates_last_sync_and_count(self, tmp_path):
        pm = make_manager(tmp_path)
        info = self._make_info_for_path(pm, self.LOCAL_PATH)
        pm.write_daemon_info(info)

        new_last_sync = 1700001234.5
        new_sync_count = 7
        pm.update_daemon_stats(self.LOCAL_PATH, new_last_sync, new_sync_count)

        updated = pm.read_daemon_info(info.signature)
        assert updated is not None
        assert updated.last_sync == new_last_sync
        assert updated.sync_count == new_sync_count
        # Other fields should be unchanged
        assert updated.pid == info.pid
        assert updated.local_path == info.local_path
