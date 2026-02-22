"""
Comprehensive unit tests for csync.rsync.RsyncWrapper.

All tests use only stdlib unittest.mock — no pytest-mock.
subprocess.run is patched so no real rsync process is ever spawned.
"""

import subprocess
from unittest.mock import MagicMock, patch, call

import pytest

from csync.config import CsyncConfig
from csync.rsync import RsyncWrapper


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_config(**kwargs):
    """Build a minimal CsyncConfig for testing."""
    defaults = dict(
        local_path="/tmp/local/",
        remote_host="host.example.com",
        remote_path="/remote/path/",
        ssh_user="user",
        rsync_options=["-a"],
        exclude_patterns=[],
        respect_gitignore=False,
    )
    defaults.update(kwargs)
    return CsyncConfig(**defaults)


# ---------------------------------------------------------------------------
# _build_rsync_command
# ---------------------------------------------------------------------------

class TestBuildRsyncCommand:
    """Tests for RsyncWrapper._build_rsync_command()."""

    def test_basic_push_command(self):
        """Source and destination appear in correct positions; rsync_options included."""
        config = make_config(rsync_options=["-a", "-v"])
        wrapper = RsyncWrapper(config)
        source = config.local_path
        destination = config.remote_target

        cmd = wrapper._build_rsync_command(source, destination)

        assert cmd[0] == "rsync"
        # rsync_options come right after "rsync"
        assert "-a" in cmd
        assert "-v" in cmd
        # source and destination are last two elements
        assert cmd[-2] == source
        assert cmd[-1] == destination

    def test_dry_run_adds_flag(self):
        """--dry-run is appended when dry_run=True."""
        config = make_config()
        wrapper = RsyncWrapper(config)
        cmd = wrapper._build_rsync_command("/src/", "/dst/", dry_run=True)
        assert "--dry-run" in cmd

    def test_dry_run_not_added_by_default(self):
        """--dry-run is absent when dry_run=False (the default)."""
        config = make_config()
        wrapper = RsyncWrapper(config)
        cmd = wrapper._build_rsync_command("/src/", "/dst/")
        assert "--dry-run" not in cmd

    def test_exclude_patterns_added(self):
        """Each exclude pattern gets its own --exclude flag."""
        patterns = ["*.log", ".git/", "__pycache__/"]
        config = make_config(exclude_patterns=patterns)
        wrapper = RsyncWrapper(config)
        cmd = wrapper._build_rsync_command("/src/", "/dst/")

        for pattern in patterns:
            idx = cmd.index("--exclude")
            # Walk through all --exclude occurrences
            exclude_values = [
                cmd[i + 1] for i, token in enumerate(cmd) if token == "--exclude"
            ]
            assert pattern in exclude_values

    def test_ssh_port_adds_e_flag(self):
        """-e ssh includes ControlMaster options and -p <port> when ssh_port is set."""
        config = make_config(ssh_port=2222)
        wrapper = RsyncWrapper(config)
        cmd = wrapper._build_rsync_command("/src/", "/dst/")

        assert "-e" in cmd
        e_index = cmd.index("-e")
        ssh_arg = cmd[e_index + 1]
        assert "ControlMaster=auto" in ssh_arg
        assert "-p 2222" in ssh_arg

    def test_no_ssh_port_no_e_flag(self):
        """ControlMaster -e flag is present for any remote host; no -p when ssh_port is None."""
        config = make_config(ssh_port=None)
        wrapper = RsyncWrapper(config)
        cmd = wrapper._build_rsync_command("/src/", "/dst/")

        assert "-e" in cmd
        e_index = cmd.index("-e")
        ssh_arg = cmd[e_index + 1]
        assert "ControlMaster=auto" in ssh_arg
        assert "-p " not in ssh_arg

    def test_source_before_destination(self):
        """Source always comes directly before destination at the end of cmd."""
        config = make_config()
        wrapper = RsyncWrapper(config)
        source, destination = "/my/source/", "/my/dest/"
        cmd = wrapper._build_rsync_command(source, destination)
        assert cmd.index(source) == len(cmd) - 2
        assert cmd.index(destination) == len(cmd) - 1

    def test_empty_rsync_options(self):
        """Command is still valid when rsync_options is an empty list."""
        config = make_config(rsync_options=[])
        wrapper = RsyncWrapper(config)
        cmd = wrapper._build_rsync_command("/src/", "/dst/")
        assert cmd[0] == "rsync"
        assert cmd[-2] == "/src/"
        assert cmd[-1] == "/dst/"


# ---------------------------------------------------------------------------
# push()
# ---------------------------------------------------------------------------

class TestPush:
    """Tests for RsyncWrapper.push()."""

    @patch("csync.rsync.subprocess.run")
    def test_push_calls_subprocess_run_with_correct_command(self, mock_run):
        """subprocess.run is called with the command built for push."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.push(verbose=False)

        mock_run.assert_called_once()
        cmd_arg = mock_run.call_args[0][0]
        assert cmd_arg[0] == "rsync"
        # source is local_path, destination is remote_target
        assert cmd_arg[-2] == config.local_path
        assert cmd_arg[-1] == config.remote_target

    @patch("csync.rsync.subprocess.run")
    def test_push_returns_true_on_success(self, mock_run):
        """push() returns True when subprocess.run succeeds."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        result = wrapper.push(verbose=False)

        assert result is True

    @patch("csync.rsync.subprocess.run")
    def test_push_returns_false_on_called_process_error(self, mock_run):
        """push() returns False when subprocess.run raises CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=23, cmd=["rsync"]
        )
        config = make_config()
        wrapper = RsyncWrapper(config)

        result = wrapper.push(verbose=False)

        assert result is False

    @patch("csync.rsync.subprocess.run")
    def test_push_returns_false_on_file_not_found(self, mock_run):
        """push() returns False when rsync binary is missing (FileNotFoundError)."""
        mock_run.side_effect = FileNotFoundError
        config = make_config()
        wrapper = RsyncWrapper(config)

        result = wrapper.push(verbose=False)

        assert result is False

    @patch("csync.rsync.subprocess.run")
    def test_push_verbose_prints_command(self, mock_run, capsys):
        """With verbose=True, push() prints 'Executing: ...' before running."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.push(verbose=True)

        captured = capsys.readouterr()
        assert "Executing:" in captured.out

    @patch("csync.rsync.subprocess.run")
    def test_push_no_output_when_not_verbose(self, mock_run, capsys):
        """With verbose=False, push() does not print the command."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.push(verbose=False)

        captured = capsys.readouterr()
        assert "Executing:" not in captured.out

    @patch("csync.rsync.subprocess.run")
    def test_push_dry_run_includes_flag(self, mock_run):
        """push(dry_run=True) passes --dry-run in the subprocess command."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.push(dry_run=True, verbose=False)

        cmd_arg = mock_run.call_args[0][0]
        assert "--dry-run" in cmd_arg

    @patch("csync.rsync.subprocess.run")
    def test_push_subprocess_called_with_check_true(self, mock_run):
        """subprocess.run is always called with check=True."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.push(verbose=False)

        _, kwargs = mock_run.call_args
        assert kwargs.get("check") is True


# ---------------------------------------------------------------------------
# pull()
# ---------------------------------------------------------------------------

class TestPull:
    """Tests for RsyncWrapper.pull()."""

    @patch("csync.rsync.os.makedirs")
    @patch("csync.rsync.subprocess.run")
    def test_pull_creates_destination_dir(self, mock_run, mock_makedirs):
        """pull() calls os.makedirs for the local destination directory."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.pull(verbose=False)

        mock_makedirs.assert_called_once_with(config.local_path, exist_ok=True)

    @patch("csync.rsync.subprocess.run")
    def test_pull_creates_destination_dir_with_tmp_path(self, mock_run, tmp_path):
        """pull() ensures destination directory is created on disk."""
        mock_run.return_value = MagicMock(returncode=0)
        dest = str(tmp_path / "new_subdir") + "/"
        config = make_config(local_path=dest)
        wrapper = RsyncWrapper(config)

        wrapper.pull(verbose=False)

        import os
        assert os.path.isdir(config.local_path)

    @patch("csync.rsync.subprocess.run")
    def test_pull_source_is_remote_target(self, mock_run):
        """In pull(), the source passed to rsync is the remote_target."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.pull(verbose=False)

        cmd_arg = mock_run.call_args[0][0]
        assert cmd_arg[-2] == config.remote_target
        assert cmd_arg[-1] == config.local_path

    @patch("csync.rsync.subprocess.run")
    def test_pull_returns_true_on_success(self, mock_run):
        """pull() returns True when subprocess.run succeeds."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        result = wrapper.pull(verbose=False)

        assert result is True

    @patch("csync.rsync.subprocess.run")
    def test_pull_returns_false_on_called_process_error(self, mock_run):
        """pull() returns False when subprocess.run raises CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=11, cmd=["rsync"]
        )
        config = make_config()
        wrapper = RsyncWrapper(config)

        result = wrapper.pull(verbose=False)

        assert result is False

    @patch("csync.rsync.subprocess.run")
    def test_pull_returns_false_on_file_not_found(self, mock_run):
        """pull() returns False when rsync binary is missing."""
        mock_run.side_effect = FileNotFoundError
        config = make_config()
        wrapper = RsyncWrapper(config)

        result = wrapper.pull(verbose=False)

        assert result is False

    @patch("csync.rsync.subprocess.run")
    def test_pull_verbose_prints_command(self, mock_run, capsys):
        """With verbose=True, pull() prints 'Executing: ...'."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.pull(verbose=True)

        captured = capsys.readouterr()
        assert "Executing:" in captured.out

    @patch("csync.rsync.subprocess.run")
    def test_pull_dry_run_includes_flag(self, mock_run):
        """pull(dry_run=True) passes --dry-run in the subprocess command."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.pull(dry_run=True, verbose=False)

        cmd_arg = mock_run.call_args[0][0]
        assert "--dry-run" in cmd_arg

    @patch("csync.rsync.subprocess.run")
    def test_pull_subprocess_called_with_check_true(self, mock_run):
        """subprocess.run is always called with check=True in pull()."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config()
        wrapper = RsyncWrapper(config)

        wrapper.pull(verbose=False)

        _, kwargs = mock_run.call_args
        assert kwargs.get("check") is True


# ---------------------------------------------------------------------------
# Remote target construction (integration of config + wrapper)
# ---------------------------------------------------------------------------

class TestRemoteTarget:
    """Tests verifying the remote target string used in commands."""

    def test_remote_target_with_user(self):
        """remote_target includes ssh_user when configured."""
        config = make_config(ssh_user="alice", remote_host="box.example.com", remote_path="/data/")
        assert config.remote_target == "alice@box.example.com:/data/"

    def test_remote_target_without_user(self):
        """remote_target omits user prefix when ssh_user is None."""
        config = make_config(ssh_user=None, remote_host="box.example.com", remote_path="/data/")
        assert config.remote_target == "box.example.com:/data/"

    @patch("csync.rsync.subprocess.run")
    def test_push_uses_remote_target_as_destination(self, mock_run):
        """push() places remote_target as the destination (last) argument."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config(
            ssh_user="deploy",
            remote_host="prod.example.com",
            remote_path="/var/app/",
        )
        wrapper = RsyncWrapper(config)

        wrapper.push(verbose=False)

        cmd = mock_run.call_args[0][0]
        assert cmd[-1] == "deploy@prod.example.com:/var/app/"

    @patch("csync.rsync.subprocess.run")
    def test_pull_uses_remote_target_as_source(self, mock_run):
        """pull() places remote_target as the source (second-to-last) argument."""
        mock_run.return_value = MagicMock(returncode=0)
        config = make_config(
            ssh_user="deploy",
            remote_host="prod.example.com",
            remote_path="/var/app/",
        )
        wrapper = RsyncWrapper(config)

        wrapper.pull(verbose=False)

        cmd = mock_run.call_args[0][0]
        assert cmd[-2] == "deploy@prod.example.com:/var/app/"
