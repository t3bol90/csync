"""
Process management module for csync daemon.
Handles PID files, process signatures, and daemon lifecycle.
"""

import os
import sys
import signal
import hashlib
import psutil
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, asdict
import json

from rich.console import Console


@dataclass
class DaemonInfo:
    """Information about a running csync daemon."""

    pid: int
    local_path: str
    remote_target: str
    config_file: str
    signature: str
    started_at: float
    last_sync: Optional[float] = None
    sync_count: int = 0


class ProcessManager:
    """Manages csync daemon processes with PID files and signatures."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self.daemon_dir = Path.home() / ".csync" / "daemons"
        self.daemon_dir.mkdir(parents=True, exist_ok=True)

    def generate_signature(self, local_path: str) -> str:
        """
        Generate a unique signature for a daemon based on local path.

        Args:
            local_path: Local directory path

        Returns:
            Unique signature string
        """
        # Use absolute path for consistency
        abs_path = os.path.abspath(local_path)
        # Create hash of path for shorter signature
        signature = hashlib.md5(abs_path.encode()).hexdigest()[:12]
        return f"csync-{signature}"

    def get_pid_file_path(self, signature: str) -> Path:
        """Get path to PID file for given signature."""
        return self.daemon_dir / f"{signature}.pid"

    def get_info_file_path(self, signature: str) -> Path:
        """Get path to daemon info file for given signature."""
        return self.daemon_dir / f"{signature}.json"

    def is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is running and not a zombie."""
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def write_daemon_info(self, daemon_info: DaemonInfo) -> None:
        """Write daemon information to files."""
        # Write PID file
        pid_file = self.get_pid_file_path(daemon_info.signature)
        with open(pid_file, "w") as f:
            f.write(str(daemon_info.pid))

        # Write info file
        info_file = self.get_info_file_path(daemon_info.signature)
        with open(info_file, "w") as f:
            json.dump(asdict(daemon_info), f, indent=2)

    def read_daemon_info(self, signature: str) -> Optional[DaemonInfo]:
        """Read daemon information from files."""
        info_file = self.get_info_file_path(signature)

        if not info_file.exists():
            return None

        try:
            with open(info_file, "r") as f:
                data = json.load(f)
            return DaemonInfo(**data)
        except (json.JSONDecodeError, TypeError, FileNotFoundError):
            return None

    def get_daemon_by_path(self, local_path: str) -> Optional[DaemonInfo]:
        """Get daemon info for a specific local path."""
        signature = self.generate_signature(local_path)
        daemon_info = self.read_daemon_info(signature)

        if daemon_info and self.is_process_running(daemon_info.pid):
            return daemon_info
        elif daemon_info:
            # Process not running, clean up stale files
            self.cleanup_daemon_files(signature)

        return None

    def start_daemon(self, daemon_info: DaemonInfo) -> bool:
        """
        Register a daemon as started.

        Args:
            daemon_info: Information about the daemon

        Returns:
            True if successfully registered
        """
        # Check if daemon already running for this path
        existing = self.get_daemon_by_path(daemon_info.local_path)
        if existing:
            self.console.print(
                f"❌ Daemon already running for {daemon_info.local_path} (PID: {existing.pid})",
                style="red",
            )
            return False

        # Write daemon info
        self.write_daemon_info(daemon_info)

        self.console.print(
            f"✅ Daemon started for {daemon_info.local_path} (PID: {daemon_info.pid})",
            style="green",
        )
        return True

    def stop_daemon(self, local_path: str, force: bool = False) -> bool:
        """
        Stop a daemon for the given local path.

        Args:
            local_path: Local directory path
            force: If True, use SIGKILL instead of SIGTERM

        Returns:
            True if successfully stopped
        """
        signature = self.generate_signature(local_path)
        daemon_info = self.read_daemon_info(signature)

        if not daemon_info:
            self.console.print(f"❌ No daemon found for {local_path}", style="red")
            return False

        if not self.is_process_running(daemon_info.pid):
            self.console.print(
                "⚠️ Daemon not running, cleaning up stale files", style="yellow"
            )
            self.cleanup_daemon_files(signature)
            return True

        # Try to stop the process
        try:
            process = psutil.Process(daemon_info.pid)

            if force:
                process.kill()  # SIGKILL
                self.console.print(
                    f"💀 Force killed daemon (PID: {daemon_info.pid})", style="red"
                )
            else:
                process.terminate()  # SIGTERM
                self.console.print(
                    f"🛑 Sent stop signal to daemon (PID: {daemon_info.pid})",
                    style="yellow",
                )

                # Wait for graceful shutdown
                try:
                    process.wait(timeout=10)
                except psutil.TimeoutExpired:
                    self.console.print(
                        "⏰ Daemon didn't stop gracefully, force killing...",
                        style="yellow",
                    )
                    process.kill()

            # Clean up files
            self.cleanup_daemon_files(signature)
            self.console.print(f"✅ Daemon stopped for {local_path}", style="green")
            return True

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.console.print(f"❌ Failed to stop daemon: {e}", style="red")
            return False

    def cleanup_daemon_files(self, signature: str) -> None:
        """Clean up PID and info files for a daemon."""
        pid_file = self.get_pid_file_path(signature)
        info_file = self.get_info_file_path(signature)

        for file_path in [pid_file, info_file]:
            try:
                if file_path.exists():
                    file_path.unlink()
            except OSError:
                pass

    def list_running_daemons(self) -> Dict[str, DaemonInfo]:
        """List all running csync daemons."""
        running_daemons = {}

        # Scan all daemon info files
        for info_file in self.daemon_dir.glob("*.json"):
            signature = info_file.stem
            daemon_info = self.read_daemon_info(signature)

            if daemon_info and self.is_process_running(daemon_info.pid):
                running_daemons[signature] = daemon_info
            elif daemon_info:
                # Clean up stale files
                self.cleanup_daemon_files(signature)

        return running_daemons

    def update_daemon_stats(
        self, local_path: str, last_sync_time: float, sync_count: int
    ) -> None:
        """Update daemon statistics."""
        signature = self.generate_signature(local_path)
        daemon_info = self.read_daemon_info(signature)

        if daemon_info:
            daemon_info.last_sync = last_sync_time
            daemon_info.sync_count = sync_count
            self.write_daemon_info(daemon_info)

    def setup_signal_handlers(self, daemon_signature: str) -> None:
        """Set up signal handlers for graceful daemon shutdown."""

        def signal_handler(signum, frame):
            self.console.print(
                f"\n🛑 Received signal {signum}, shutting down daemon...",
                style="yellow",
            )
            self.cleanup_daemon_files(daemon_signature)
            sys.exit(0)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C


def get_process_manager(console: Optional[Console] = None) -> ProcessManager:
    """Get a ProcessManager instance."""
    return ProcessManager(console)
