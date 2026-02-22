"""
Rsync wrapper module for csync.
Provides functionality to sync files between local and remote machines using rsync.
"""

import subprocess
import sys
import os
import time
from pathlib import Path
from typing import List, Optional

from .config import CsyncConfig


class RsyncWrapper:
    """A wrapper class for rsync operations."""

    def __init__(self, config: CsyncConfig):
        self.config = config
        (Path.home() / ".csync").mkdir(exist_ok=True)
        self._base_cmd: list[str] = self._build_base_cmd()

    def _ssh_control_args(self) -> list[str]:
        """Return rsync -e args that enable SSH ControlMaster connection reuse."""
        control_path = Path.home() / ".csync" / "ssh-%r@%h:%p"
        ssh_cmd = (
            f"ssh -o ControlMaster=auto"
            f" -o ControlPath={control_path}"
            f" -o ControlPersist=60"
        )
        if self.config.ssh_port:
            ssh_cmd += f" -p {self.config.ssh_port}"
        return ["-e", ssh_cmd]

    def _build_base_cmd(self) -> list[str]:
        """Pre-build the static command prefix shared across all rsync invocations."""
        cmd = ["rsync"] + list(self.config.rsync_options or [])
        for pat in (self.config.exclude_patterns or []):
            cmd.extend(["--exclude", pat])
        if self.config.remote_host:
            cmd.extend(self._ssh_control_args())
        return cmd

    def _build_rsync_command(
        self, source: str, destination: str, dry_run: bool = False
    ) -> List[str]:
        cmd = list(self._base_cmd)  # shallow copy of cached prefix
        if dry_run:
            cmd.append("--dry-run")
        cmd.extend([source, destination])
        return cmd

    def _run_with_retry(self, cmd: List[str], verbose: bool, stdin_data: Optional[bytes] = None, partial_ok: bool = False) -> bool:
        """Run a command, retrying up to 3 times with exponential backoff."""
        max_retries = 3
        delay = 2.0
        for attempt in range(max_retries + 1):
            try:
                subprocess.run(cmd, check=True, capture_output=False, input=stdin_data)
                return True
            except subprocess.CalledProcessError as e:
                if partial_ok and e.returncode == 23:
                    # Exit 23 = partial transfer: some targeted files disappeared
                    # before rsync ran. Not a real error — don't retry.
                    print(
                        "⚠️  rsync partial transfer (exit 23): some files may have"
                        " disappeared before sync; treating as success.",
                        file=sys.stderr,
                    )
                    return True
                if attempt == max_retries:
                    print(
                        f"❌ Command failed after {max_retries} retries"
                        f" (exit code {e.returncode})",
                        file=sys.stderr,
                    )
                    return False
                print(
                    f"⚠️  Attempt {attempt + 1} failed, retrying in {delay:.0f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                delay *= 2
            except FileNotFoundError:
                print(
                    "❌ rsync command not found. Please install rsync.",
                    file=sys.stderr,
                )
                return False
        return False

    def push(self, dry_run: bool = False, verbose: bool = True, files_from_paths: Optional[List[str]] = None) -> bool:
        """Push (sync) local files to remote."""
        source = self.config.local_path
        destination = self.config.remote_target

        cmd = self._build_rsync_command(source, destination, dry_run)

        stdin_data: Optional[bytes] = None
        if files_from_paths is not None:
            # Insert --files-from=- before the source/dest args; paths arrive via stdin
            cmd.insert(len(cmd) - 2, "--files-from=-")
            stdin_data = '\n'.join(files_from_paths).encode()

        if verbose:
            print(f"Executing: {' '.join(cmd)}")

        success = self._run_with_retry(cmd, verbose, stdin_data=stdin_data, partial_ok=(files_from_paths is not None))
        if success and verbose:
            print("✅ Push completed successfully!")
        return success

    def pull(self, dry_run: bool = False, verbose: bool = True) -> bool:
        """Pull (sync) remote files to local."""
        source = self.config.remote_target
        destination = self.config.local_path

        os.makedirs(destination, exist_ok=True)

        cmd = self._build_rsync_command(source, destination, dry_run)

        if verbose:
            print(f"Executing: {' '.join(cmd)}")

        success = self._run_with_retry(cmd, verbose)
        if success and verbose:
            print("✅ Pull completed successfully!")
        return success

    def status(self) -> None:
        """Show the current configuration status."""
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel

        console = Console()

        table = Table(
            title="📋 csync Configuration", show_header=True, header_style="bold blue"
        )
        table.add_column("Setting", style="cyan", width=15)
        table.add_column("Value", style="white")

        table.add_row("Local path", self.config.local_path)
        table.add_row("Remote", self.config.remote_target)
        table.add_row(
            "Options",
            " ".join(self.config.rsync_options)
            if self.config.rsync_options
            else "None",
        )
        table.add_row(
            "Excludes",
            f"{len(self.config.exclude_patterns) if self.config.exclude_patterns else 0} patterns",
        )
        table.add_row(
            "Respect .gitignore",
            "Yes" if getattr(self.config, "respect_gitignore", True) else "No",
        )

        if os.path.exists(self.config.local_path):
            table.add_row("Local status", "✅ Path exists")
        else:
            table.add_row("Local status", "❌ Path does not exist")

        console.print(table)

        if self.config.exclude_patterns:
            exclude_panel = Panel(
                "\n".join(
                    f"• {pattern}" for pattern in self.config.exclude_patterns[:10]
                ),
                title="🚫 Exclude Patterns"
                + (
                    " (showing first 10)"
                    if len(self.config.exclude_patterns) > 10
                    else ""
                ),
                border_style="yellow",
            )
            console.print(exclude_panel)

    def dry_run_push(self) -> bool:
        """Perform a dry run push to see what would be synced."""
        print("🔍 Dry run - showing what would be pushed:")
        return self.push(dry_run=True)

    def dry_run_pull(self) -> bool:
        """Perform a dry run pull to see what would be pulled."""
        print("🔍 Dry run - showing what would be pulled:")
        return self.pull(dry_run=True)
