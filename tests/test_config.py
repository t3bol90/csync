"""
Comprehensive unit tests for csync.config module.
"""

import configparser
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from csync.config import (
    CsyncConfig,
    find_config_file,
    load_global_defaults,
    save_global_defaults,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs):
    """Return a minimal CsyncConfig, merging caller's kwargs."""
    defaults = dict(
        local_path=".",
        remote_host="example.com",
        remote_path="/remote/",
    )
    defaults.update(kwargs)
    return CsyncConfig(**defaults)


# ---------------------------------------------------------------------------
# CsyncConfig dataclass
# ---------------------------------------------------------------------------

class TestCsyncConfigDataclass:

    def test_local_path_is_made_absolute(self):
        cfg = _make_config(local_path=".")
        assert Path(cfg.local_path).is_absolute()

    def test_local_path_ends_with_slash(self):
        cfg = _make_config(local_path=".")
        assert cfg.local_path.endswith("/")

    def test_remote_path_ends_with_slash(self):
        cfg = _make_config(remote_path="/some/path")
        assert cfg.remote_path.endswith("/")

    def test_remote_path_already_has_slash(self):
        cfg = _make_config(remote_path="/already/")
        assert cfg.remote_path == "/already/"

    def test_default_rsync_options(self):
        cfg = _make_config(rsync_options=None)
        assert cfg.rsync_options == ["-av", "--progress"]

    def test_explicit_rsync_options_preserved(self):
        cfg = _make_config(rsync_options=["-r"])
        assert cfg.rsync_options == ["-r"]

    def test_default_exclude_patterns(self):
        cfg = _make_config(exclude_patterns=None)
        assert ".git/" in cfg.exclude_patterns
        assert "__pycache__/" in cfg.exclude_patterns

    def test_explicit_exclude_patterns_preserved(self):
        cfg = _make_config(exclude_patterns=["*.log"])
        # Should still contain the explicit pattern
        assert "*.log" in cfg.exclude_patterns

    def test_remote_target_with_user(self):
        cfg = _make_config(ssh_user="alice", remote_host="host.example", remote_path="/data/")
        assert cfg.remote_target == "alice@host.example:/data/"

    def test_remote_target_without_user(self):
        cfg = _make_config(ssh_user=None, remote_host="host.example", remote_path="/data/")
        assert cfg.remote_target == "host.example:/data/"

    def test_respect_gitignore_false_skips_gitignore_load(self, tmp_path):
        # Create a .gitignore with a distinctive pattern
        (tmp_path / ".gitignore").write_text("should_not_appear\n")
        cfg = CsyncConfig(
            local_path=str(tmp_path),
            remote_host="host",
            remote_path="/r/",
            respect_gitignore=False,
            exclude_patterns=None,
        )
        # The pattern from .gitignore must NOT be present
        assert "should_not_appear" not in cfg.exclude_patterns


# ---------------------------------------------------------------------------
# CsyncConfig.from_file()
# ---------------------------------------------------------------------------

class TestCsyncConfigFromFile:

    def test_from_file_cfg_format(self, tmp_path):
        cfg_file = tmp_path / ".csync.cfg"
        cfg_file.write_text(
            "[csync]\n"
            "local_path = /tmp/project\n"
            "remote_host = server.example\n"
            "remote_path = /home/user/project\n"
            "ssh_user = bob\n"
            "ssh_port = 2222\n"
        )
        cfg = CsyncConfig.from_file(str(cfg_file))
        assert cfg.remote_host == "server.example"
        assert cfg.remote_path == "/home/user/project/"
        assert cfg.ssh_user == "bob"
        assert cfg.ssh_port == 2222

    def test_from_file_json_format(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        data = {
            "local_path": str(tmp_path),
            "remote_host": "json.host",
            "remote_path": "/json/path",
            "ssh_user": "jsonuser",
        }
        cfg_file.write_text(json.dumps(data))
        cfg = CsyncConfig.from_file(str(cfg_file))
        assert cfg.remote_host == "json.host"
        assert cfg.ssh_user == "jsonuser"
        assert cfg.remote_path.endswith("/")

    def test_from_file_yaml_format(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        data = {
            "local_path": str(tmp_path),
            "remote_host": "yaml.host",
            "remote_path": "/yaml/path",
        }
        cfg_file.write_text(yaml.dump(data))
        cfg = CsyncConfig.from_file(str(cfg_file))
        assert cfg.remote_host == "yaml.host"
        assert cfg.remote_path.endswith("/")

    def test_from_file_not_found(self, tmp_path):
        missing = str(tmp_path / "nonexistent.cfg")
        with pytest.raises(FileNotFoundError):
            CsyncConfig.from_file(missing)

    def test_from_file_cfg_missing_section(self, tmp_path):
        cfg_file = tmp_path / "bad.cfg"
        cfg_file.write_text("[other_section]\nfoo = bar\n")
        with pytest.raises(ValueError, match="No \\[csync\\] section"):
            CsyncConfig.from_file(str(cfg_file))


# ---------------------------------------------------------------------------
# CsyncConfig._load_gitignore_patterns()
# ---------------------------------------------------------------------------

class TestLoadGitignorePatterns:

    def test_root_gitignore_patterns(self, tmp_path):
        (tmp_path / ".gitignore").write_text("*.pyc\nbuild/\n")
        cfg = CsyncConfig(
            local_path=str(tmp_path),
            remote_host="h",
            remote_path="/r/",
            respect_gitignore=True,
            exclude_patterns=[],
        )
        patterns = cfg._load_gitignore_patterns()
        assert "*.pyc" in patterns
        assert "build/" in patterns
        # Root patterns must NOT have a directory prefix
        for p in patterns:
            assert not p.startswith("/")

    def test_nested_gitignore_prefixed(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / ".gitignore").write_text("*.o\n")
        cfg = CsyncConfig(
            local_path=str(tmp_path),
            remote_host="h",
            remote_path="/r/",
            respect_gitignore=True,
            exclude_patterns=[],
        )
        patterns = cfg._load_gitignore_patterns()
        assert "src/*.o" in patterns

    def test_skips_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / ".gitignore").write_text("secret_pattern\n")
        cfg = CsyncConfig(
            local_path=str(tmp_path),
            remote_host="h",
            remote_path="/r/",
            respect_gitignore=True,
            exclude_patterns=[],
        )
        patterns = cfg._load_gitignore_patterns()
        # Nothing from inside .git/ should appear
        assert not any("secret_pattern" in p for p in patterns)

    def test_ignores_comments_and_blank_lines(self, tmp_path):
        (tmp_path / ".gitignore").write_text(
            "# This is a comment\n"
            "\n"
            "   \n"
            "dist/\n"
        )
        cfg = CsyncConfig(
            local_path=str(tmp_path),
            remote_host="h",
            remote_path="/r/",
            respect_gitignore=True,
            exclude_patterns=[],
        )
        patterns = cfg._load_gitignore_patterns()
        assert "dist/" in patterns
        assert not any(p.startswith("#") for p in patterns)
        assert "" not in patterns
        assert not any(p.strip() == "" for p in patterns)

    def test_no_gitignore_returns_empty(self, tmp_path):
        cfg = CsyncConfig(
            local_path=str(tmp_path),
            remote_host="h",
            remote_path="/r/",
            respect_gitignore=True,
            exclude_patterns=[],
        )
        patterns = cfg._load_gitignore_patterns()
        assert patterns == []


# ---------------------------------------------------------------------------
# find_config_file()
# ---------------------------------------------------------------------------

class TestFindConfigFile:

    def test_finds_in_current_dir(self, tmp_path):
        cfg_file = tmp_path / ".csync.cfg"
        cfg_file.write_text("[csync]\nremote_host = x\n")
        result = find_config_file(str(tmp_path))
        assert result == str(cfg_file)

    def test_finds_in_parent_dir(self, tmp_path):
        cfg_file = tmp_path / ".csync.cfg"
        cfg_file.write_text("[csync]\nremote_host = x\n")
        child = tmp_path / "child"
        child.mkdir()
        result = find_config_file(str(child))
        assert result == str(cfg_file)

    def test_returns_none_when_absent(self, tmp_path):
        # Use a deeply nested directory that has no config anywhere up to tmp_path.
        # We search from tmp_path itself; since no file exists the walk will
        # eventually reach the filesystem root and return None.
        result = find_config_file(str(tmp_path))
        assert result is None

    def test_finds_json_format(self, tmp_path):
        cfg_file = tmp_path / ".csync_config.json"
        cfg_file.write_text(json.dumps({"remote_host": "x", "local_path": ".", "remote_path": "/r/"}))
        result = find_config_file(str(tmp_path))
        assert result == str(cfg_file)


# ---------------------------------------------------------------------------
# load_global_defaults() / save_global_defaults()
# ---------------------------------------------------------------------------

class TestGlobalDefaults:

    def test_load_returns_empty_when_no_file(self, tmp_path):
        fake_path = tmp_path / "defaults.cfg"
        with patch("csync.config.GLOBAL_CONFIG_FILE", fake_path):
            result = load_global_defaults()
        assert result == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        fake_path = tmp_path / "defaults.cfg"
        data = {"remote_host": "myserver", "ssh_user": "alice"}
        with patch("csync.config.GLOBAL_CONFIG_FILE", fake_path):
            save_global_defaults(data)
            result = load_global_defaults()
        assert result["remote_host"] == "myserver"
        assert result["ssh_user"] == "alice"

    def test_load_parses_sync_delay_as_float(self, tmp_path):
        fake_path = tmp_path / "defaults.cfg"
        data = {"sync_delay": "1.5"}
        with patch("csync.config.GLOBAL_CONFIG_FILE", fake_path):
            save_global_defaults(data)
            result = load_global_defaults()
        assert isinstance(result["sync_delay"], float)
        assert result["sync_delay"] == 1.5

    def test_load_parses_ssh_port_as_int(self, tmp_path):
        fake_path = tmp_path / "defaults.cfg"
        data = {"ssh_port": "22"}
        with patch("csync.config.GLOBAL_CONFIG_FILE", fake_path):
            save_global_defaults(data)
            result = load_global_defaults()
        assert isinstance(result["ssh_port"], int)
        assert result["ssh_port"] == 22
