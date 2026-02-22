"""
Unit tests for csync.daemon module.

Covers: CsyncFileHandler, CsyncDaemon.should_exclude_file(),
        add_pending_change() / get_pending_changes(), should_sync_now(),
        and _check_ssh_connectivity().
"""

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from csync.daemon import CsyncDaemon, CsyncFileHandler
from csync.config import CsyncConfig


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_daemon(exclude_patterns=None, **config_kwargs):
    """Construct a minimal CsyncDaemon without touching the filesystem or OS."""
    defaults = dict(
        local_path="/tmp/test_local/",
        remote_host="host.example.com",
        remote_path="/remote/",
        ssh_user="user",
        rsync_options=["-a"],
        exclude_patterns=exclude_patterns or [],
        respect_gitignore=False,
    )
    defaults.update(config_kwargs)
    config = CsyncConfig(**defaults)
    with patch("csync.daemon.Observer"), patch("csync.daemon.ProcessManager"):
        daemon = CsyncDaemon(config)
    return daemon


# ===========================================================================
# CsyncFileHandler tests
# ===========================================================================

class TestCsyncFileHandler:
    """Tests for CsyncFileHandler.on_any_event()."""

    def _make_event(self, src_path, is_directory=False, event_type="modified"):
        event = MagicMock()
        event.src_path = src_path
        event.is_directory = is_directory
        event.event_type = event_type
        return event

    def test_on_any_event_adds_pending_change(self):
        """A file event for a non-excluded path should add to pending_changes."""
        daemon = make_daemon()
        handler = CsyncFileHandler(daemon)

        event = self._make_event("/tmp/test_local/src/main.py")
        handler.on_any_event(event)

        assert len(daemon.pending_changes) == 1
        assert Path("/tmp/test_local/src/main.py").resolve() in daemon.pending_changes

    def test_on_any_event_skips_directories(self):
        """A directory event should not add anything to pending_changes."""
        daemon = make_daemon()
        handler = CsyncFileHandler(daemon)

        event = self._make_event("/tmp/test_local/src/", is_directory=True)
        handler.on_any_event(event)

        assert len(daemon.pending_changes) == 0

    def test_on_any_event_skips_excluded_files(self):
        """A file matching an exclude pattern should not be added."""
        daemon = make_daemon(exclude_patterns=["*.pyc"])
        handler = CsyncFileHandler(daemon)

        event = self._make_event("/tmp/test_local/src/module.pyc")
        handler.on_any_event(event)

        assert len(daemon.pending_changes) == 0


# ===========================================================================
# CsyncDaemon.should_exclude_file() tests
# ===========================================================================

STANDARD_PATTERNS = [".git/", "__pycache__/", "*.pyc", ".DS_Store", "build/"]


class TestShouldExcludeFile:
    """Tests for the should_exclude_file() method."""

    def _daemon(self):
        return make_daemon(exclude_patterns=STANDARD_PATTERNS)

    # -- directory patterns --------------------------------------------------

    def test_excludes_dir_itself(self):
        """The directory name alone (without trailing slash) should be excluded."""
        daemon = self._daemon()
        assert daemon.should_exclude_file("/tmp/test_local/.git") is True

    def test_excludes_file_inside_dir(self):
        """A path nested inside an excluded directory should be excluded."""
        daemon = self._daemon()
        assert daemon.should_exclude_file("/tmp/test_local/.git/config") is True

    def test_does_not_exclude_sibling_path(self):
        """.gitignore must NOT be excluded by the .git/ pattern (boundary bug fix)."""
        daemon = self._daemon()
        assert daemon.should_exclude_file("/tmp/test_local/.gitignore") is False

    def test_does_not_exclude_similar_prefix(self):
        """.github/workflows/ci.yml must NOT be excluded by the .git/ pattern."""
        daemon = self._daemon()
        assert daemon.should_exclude_file("/tmp/test_local/.github/workflows/ci.yml") is False

    # -- wildcard patterns ---------------------------------------------------

    def test_excludes_wildcard_pyc(self):
        """A *.pyc file at the top level should be excluded."""
        daemon = self._daemon()
        assert daemon.should_exclude_file("/tmp/test_local/src/module.pyc") is True

    def test_excludes_wildcard_in_subdir(self):
        """A *.pyc file deep in nested subdirectories should be excluded."""
        daemon = self._daemon()
        assert daemon.should_exclude_file("/tmp/test_local/deep/nested/file.pyc") is True

    # -- exact match patterns ------------------------------------------------

    def test_exact_match_ds_store(self):
        """.DS_Store (exact name) should be excluded."""
        daemon = self._daemon()
        assert daemon.should_exclude_file("/tmp/test_local/.DS_Store") is True

    def test_exact_match_not_substring(self):
        """my.DS_Store.bak must NOT be excluded by the exact .DS_Store pattern."""
        daemon = self._daemon()
        assert daemon.should_exclude_file("/tmp/test_local/my.DS_Store.bak") is False

    # -- empty patterns list -------------------------------------------------

    def test_no_patterns_never_excludes(self):
        """With an empty exclude_patterns list, nothing should ever be excluded."""
        daemon = make_daemon(exclude_patterns=[])
        assert daemon.should_exclude_file("/tmp/test_local/.git/config") is False
        assert daemon.should_exclude_file("/tmp/test_local/module.pyc") is False
        assert daemon.should_exclude_file("/tmp/test_local/.DS_Store") is False


# ===========================================================================
# CsyncDaemon.add_pending_change() / get_pending_changes() tests
# ===========================================================================

class TestPendingChanges:
    """Tests for add_pending_change() and get_pending_changes()."""

    def test_add_sets_first_change_at(self):
        """first_change_at should be 0 before the first add and non-zero after."""
        daemon = make_daemon()
        assert daemon.first_change_at == 0.0

        before = time.time()
        daemon.add_pending_change("/tmp/test_local/file.txt")
        after = time.time()

        assert daemon.first_change_at != 0.0
        assert before <= daemon.first_change_at <= after

    def test_add_preserves_first_change_at_on_subsequent_adds(self):
        """Subsequent adds must not reset first_change_at."""
        daemon = make_daemon()
        daemon.add_pending_change("/tmp/test_local/first.txt")
        original_first_change_at = daemon.first_change_at

        # Small sleep to ensure time advances
        time.sleep(0.01)
        daemon.add_pending_change("/tmp/test_local/second.txt")

        assert daemon.first_change_at == original_first_change_at

    def test_get_clears_pending_changes(self):
        """get_pending_changes() should return the changes and leave the set empty."""
        daemon = make_daemon()
        daemon.add_pending_change("/tmp/test_local/a.txt")
        daemon.add_pending_change("/tmp/test_local/b.txt")

        changes = daemon.get_pending_changes()

        assert len(changes) == 2
        assert len(daemon.pending_changes) == 0

    def test_get_resets_first_change_at(self):
        """get_pending_changes() should reset first_change_at back to 0.0."""
        daemon = make_daemon()
        daemon.add_pending_change("/tmp/test_local/file.txt")
        assert daemon.first_change_at != 0.0

        daemon.get_pending_changes()

        assert daemon.first_change_at == 0.0


# ===========================================================================
# CsyncDaemon.should_sync_now() tests
# ===========================================================================

class TestShouldSyncNow:
    """Tests for the should_sync_now() method."""

    def test_returns_true_when_max_interval_exceeded(self):
        """Should return True when last_sync_time is far in the past."""
        daemon = make_daemon()
        # Push last_sync_time well beyond max_sync_interval (300 s)
        daemon.last_sync_time = time.time() - 400.0
        assert daemon.should_sync_now() is True

    def test_returns_false_with_no_pending_changes_and_recent_sync(self):
        """Should return False when there are no pending changes and sync is recent."""
        daemon = make_daemon()
        daemon.last_sync_time = time.time()  # just synced
        daemon.first_change_at = 0.0         # no pending changes
        assert daemon.should_sync_now() is False

    def test_returns_true_when_delay_elapsed_after_first_change(self):
        """Should return True when sync_delay has elapsed since first_change_at."""
        daemon = make_daemon()
        daemon.sync_delay = 5.0
        daemon.last_sync_time = time.time()   # recent sync (won't trigger max interval)
        daemon.first_change_at = time.time() - 10.0  # 10 s ago, delay is 5 s
        assert daemon.should_sync_now() is True

    def test_returns_false_when_delay_not_elapsed(self):
        """Should return False when sync_delay has NOT yet elapsed since first_change_at."""
        daemon = make_daemon()
        daemon.sync_delay = 5.0
        daemon.last_sync_time = time.time()   # recent sync
        daemon.first_change_at = time.time() - 1.0  # only 1 s ago, delay is 5 s
        assert daemon.should_sync_now() is False

    def test_returns_false_when_no_first_change_at(self):
        """Should return False when first_change_at is 0.0 and max interval not reached."""
        daemon = make_daemon()
        daemon.last_sync_time = time.time()   # recent sync
        daemon.first_change_at = 0.0          # no queued change
        assert daemon.should_sync_now() is False


# ===========================================================================
# CsyncDaemon._check_ssh_connectivity() tests
# ===========================================================================

class TestCheckSshConnectivity:
    """Tests for the _check_ssh_connectivity() method."""

    def _completed_process(self, returncode):
        mock = MagicMock(spec=subprocess.CompletedProcess)
        mock.returncode = returncode
        return mock

    def test_ssh_check_success(self):
        """Should return True when ssh exits with returncode 0."""
        daemon = make_daemon()
        with patch("subprocess.run", return_value=self._completed_process(0)):
            assert daemon._check_ssh_connectivity() is True

    def test_ssh_check_failure(self):
        """Should return False when ssh exits with a non-zero returncode."""
        daemon = make_daemon()
        with patch("subprocess.run", return_value=self._completed_process(1)):
            assert daemon._check_ssh_connectivity() is False

    def test_ssh_check_timeout(self):
        """Should return False when subprocess.run raises TimeoutExpired."""
        daemon = make_daemon()
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=10),
        ):
            assert daemon._check_ssh_connectivity() is False

    def test_ssh_check_includes_port(self):
        """When ssh_port is set, the command should include -p <port>."""
        daemon = make_daemon(ssh_port=2222)
        with patch("subprocess.run", return_value=self._completed_process(0)) as mock_run:
            daemon._check_ssh_connectivity()
        cmd = mock_run.call_args[0][0]
        assert "-p" in cmd
        assert "2222" in cmd

    def test_ssh_check_no_user(self):
        """When ssh_user is None, the target should be just the host (no @ sign)."""
        daemon = make_daemon(ssh_user=None)
        with patch("subprocess.run", return_value=self._completed_process(0)) as mock_run:
            daemon._check_ssh_connectivity()
        cmd = mock_run.call_args[0][0]
        target = cmd[-2]  # second-to-last arg before "exit"
        assert "@" not in target
        assert "host.example.com" in target


# ===========================================================================
# CsyncDaemon.perform_sync() tests
# ===========================================================================

class TestCsyncDaemon:
    """Tests for CsyncDaemon.perform_sync()."""

    def setup_method(self):
        self.daemon = make_daemon()

    def test_last_sync_duration_ms_set_after_success(self):
        """last_sync_duration_ms is updated after a successful sync."""
        self.daemon.last_sync_duration_ms = 0.0
        mock_wrapper = MagicMock()
        mock_wrapper.push.return_value = True
        self.daemon.rsync_wrapper = mock_wrapper
        self.daemon.add_pending_change("/tmp/test/file.txt")
        result = self.daemon.perform_sync()
        assert result is True
        assert self.daemon.last_sync_duration_ms >= 0.0

    def test_last_sync_duration_ms_unchanged_after_failure(self):
        """last_sync_duration_ms stays 0 after a failed sync."""
        self.daemon.last_sync_duration_ms = 0.0
        mock_wrapper = MagicMock()
        mock_wrapper.push.return_value = False
        self.daemon.rsync_wrapper = mock_wrapper
        self.daemon.add_pending_change("/tmp/test/file.txt")
        result = self.daemon.perform_sync()
        assert result is False
        assert self.daemon.last_sync_duration_ms == 0.0
