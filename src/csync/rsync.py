"""
Rsync wrapper module for csync.
Provides functionality to sync files between local and remote machines using rsync.
"""

import subprocess
import sys
import os
import time
from typing import List, Optional

from .config import CsyncConfig


class RsyncWrapper:
    """A wrapper class for rsync operations."""

    def __init__(self, config: CsyncConfig):
        self.config = config

    def _build_rsync_command(
        self, source: str, destination: str, dry_run: bool = False
    ) -> List[str]:
        cmd = ["rsync"] + (
            self.config.rsync_options.copy() if self.config.rsync_options else []
        )

        if dry_run:
            cmd.append("--dry-run")

        if self.config.exclude_patterns:
            for pattern in self.config.exclude_patterns:
                cmd.extend(["--exclude", pattern])

        if self.config.ssh_port:
            cmd.extend(["-e", f"ssh -p {self.config.ssh_port}"])

        cmd.extend([source, destination])
        return cmd

    def _run_with_retry(self, cmd: List[str], verbose: bool) -> bool:
        """Run a command, retrying up to 3 times with exponential backoff."""
        max_retries = 3
        delay = 2.0
        for attempt in range(max_retries + 1):
            try:
                subprocess.run(cmd, check=True, capture_output=False)
                return True
            except subprocess.CalledProcessError as e:
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

    def push(self, dry_run: bool = False, verbose: bool = True, files_from: Optional[str] = None) -> bool:
        """Push (sync) local files to remote."""
        source = self.config.local_path
        destination = self.config.remote_target

        cmd = self._build_rsync_command(source, destination, dry_run)

        if files_from is not None:
            # Insert --files-from before the source path (last two elements are source and destination)
            cmd.insert(len(cmd) - 2, f"--files-from={files_from}")

        if verbose:
            print(f"Executing: {' '.join(cmd)}")

        success = self._run_with_retry(cmd, verbose)
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
