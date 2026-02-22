"""
Modern command-line interface for csync using Typer and Rich.
"""

import hashlib
import os
from pathlib import Path
from typing import Optional, Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .config import (
    CsyncConfig,
    find_config_file,
    create_gitignore_if_needed,
    load_global_defaults,
    save_global_defaults,
    GLOBAL_CONFIG_FILE,
)
from .rsync import RsyncWrapper
from .analyzer import analyze_project_smart
from .daemon import start_daemon
from .process_manager import get_process_manager

# Create the main Typer app
app = typer.Typer(
    name="csync",
    help="🚀 A modern Python wrapper for rsync to sync code between local and remote machines",
    add_completion=False,
    rich_markup_mode="rich",
)

# Create Rich console for colored output
console = Console()


def find_and_load_config(config_path: Optional[str] = None) -> CsyncConfig:
    """
    Find and load configuration file.

    Args:
        config_path: Optional explicit path to config file

    Returns:
        CsyncConfig instance

    Raises:
        typer.Exit: If config file not found or invalid
    """
    if config_path:
        if not os.path.exists(config_path):
            console.print(f"❌ Config file not found: {config_path}", style="red")
            raise typer.Exit(1)
        config_file = config_path
    else:
        config_file = find_config_file()
        if not config_file:
            console.print(
                "❌ No .csync.cfg file found in current directory or parent directories.",
                style="red",
            )
            console.print(
                "Create a .csync.cfg file with your sync configuration.", style="yellow"
            )
            console.print("\n[bold]Example:[/bold]")
            gd = load_global_defaults()
            example_host = gd.get("remote_host", "your-server.com")
            example_user = gd.get("ssh_user", "your-username")
            example_panel = Panel(
                f"""[cyan][csync][/cyan]
[yellow]local_path[/yellow] = .
[yellow]remote_host[/yellow] = {example_host}
[yellow]remote_path[/yellow] = /home/user/myproject
[yellow]ssh_user[/yellow] = {example_user}""",
                title="Sample .csync.cfg",
                border_style="blue",
            )
            console.print(example_panel)
            console.print(
                "\n💡 Use '[bold cyan]csync init[/bold cyan]' to create a sample config file."
            )
            raise typer.Exit(1)

    try:
        return CsyncConfig.from_file(config_file)
    except Exception as e:
        console.print(f"❌ Error loading config file {config_file}: {e}", style="red")
        raise typer.Exit(1)


@app.command()
def push(
    config: Annotated[
        Optional[str], typer.Option("--config", "-c", help="Path to config file")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Show what would be pushed without actually doing it",
        ),
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress verbose output")
    ] = False,
) -> None:
    """
    🚀 Push local files to remote server.

    Syncs your local files to the remote server using rsync.
    """
    config_obj = find_and_load_config(config)
    wrapper = RsyncWrapper(config_obj)

    if dry_run:
        console.print("🔍 [yellow]Dry run - showing what would be pushed:[/yellow]")
        success = wrapper.dry_run_push()
    else:
        success = wrapper.push(verbose=not quiet)

    if not success:
        raise typer.Exit(1)


@app.command()
def pull(
    config: Annotated[
        Optional[str], typer.Option("--config", "-c", help="Path to config file")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Show what would be pulled without actually doing it",
        ),
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress verbose output")
    ] = False,
) -> None:
    """
    📥 Pull remote files to local directory.

    Syncs remote files to your local directory using rsync.
    """
    config_obj = find_and_load_config(config)
    wrapper = RsyncWrapper(config_obj)

    if dry_run:
        console.print("🔍 [yellow]Dry run - showing what would be pulled:[/yellow]")
        success = wrapper.dry_run_pull()
    else:
        success = wrapper.pull(verbose=not quiet)

    if not success:
        raise typer.Exit(1)


@app.command()
def status(
    config: Annotated[
        Optional[str], typer.Option("--config", "-c", help="Path to config file")
    ] = None,
) -> None:
    """
    📋 Show configuration status and connection details.
    """
    config_obj = find_and_load_config(config)
    wrapper = RsyncWrapper(config_obj)
    wrapper.status()


@app.command("init")
def init_config(
    config: Annotated[
        Optional[str], typer.Option("--config", "-c", help="Config file path to create")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite existing config file")
    ] = False,
    smart: Annotated[
        bool,
        typer.Option("--smart", help="Use smart analysis to suggest exclude patterns"),
    ] = False,
) -> None:
    """
    🚀 Create a sample configuration file.

    Generates a .csync.cfg file with sample configuration that you can customize.
    Use --smart to analyze the project and suggest intelligent exclude patterns.
    """
    config_path = config or ".csync.cfg"

    if os.path.exists(config_path) and not force:
        console.print(f"❌ Config file already exists: {config_path}", style="red")
        console.print("💡 Use --force to overwrite existing file", style="yellow")
        raise typer.Exit(1)

    # Default exclude patterns
    default_excludes = [
        ".git/",
        "__pycache__/",
        "*.pyc",
        ".DS_Store",
        "node_modules/",
        ".venv/",
        "venv/",
        ".pytest_cache/",
        "*.log",
    ]

    # If smart analysis is requested, analyze the project
    if smart:
        console.print("🧠 [cyan]Running smart analysis...[/cyan]")
        try:
            from .analyzer import analyze_project_smart

            analysis_result = analyze_project_smart(".", console)

            # Display analysis results
            if hasattr(analysis_result, "display_analysis"):
                analysis_result.display_analysis(analysis_result)
            else:
                # Create analyzer instance and use its display method
                from .analyzer import SmartAnalyzer

                analyzer = SmartAnalyzer(console)
                analyzer.display_analysis(analysis_result)

            # Use suggested excludes from analysis
            suggested_excludes = analysis_result.suggested_excludes
            if suggested_excludes:
                console.print(
                    f"\n✨ Found {len(suggested_excludes)} smart exclude suggestions",
                    style="green",
                )
                default_excludes = suggested_excludes
            else:
                console.print(
                    "\n💡 No additional smart suggestions found, using defaults",
                    style="yellow",
                )

        except ImportError:
            console.print("❌ Smart analysis not available", style="red")
        except Exception as e:
            console.print(f"⚠️ Smart analysis failed: {e}", style="yellow")
            console.print("Using default exclude patterns", style="yellow")

    # Merge global defaults so users don't have to retype them every project
    gd = load_global_defaults()
    sample_config = CsyncConfig(
        local_path=".",
        remote_host=gd.get("remote_host", "your-server.com"),
        remote_path=gd.get("remote_path") or f'~/projects/{Path.cwd().name}',
        ssh_user=gd.get("ssh_user") or None,
        ssh_port=gd.get("ssh_port"),
        rsync_options=["-av", "--progress"],
        exclude_patterns=default_excludes,
        respect_gitignore=True,
    )

    # Save config and get content for display
    content = sample_config.to_file(config_path)

    console.print(
        f"✅ Created sample config file: [bold cyan]{config_path}[/bold cyan]",
        style="green",
    )

    # Show the config content
    config_panel = Panel(
        content,
        title=f"Generated {config_path}" + (" (with smart analysis)" if smart else ""),
        border_style="green",
    )
    console.print(config_panel)

    # Check/create .gitignore
    gitignore_created = create_gitignore_if_needed()
    if gitignore_created:
        console.print(
            "✅ Created [bold].gitignore[/bold] file (added .csync.cfg to it)",
            style="green",
        )
    else:
        console.print("📄 [bold].gitignore[/bold] already exists", style="blue")

    console.print(
        "\n💡 [yellow]Please edit the config file with your actual server details.[/yellow]"
    )
    # TODO check if git has .csync.cfg ignored, if automatically add it to .gitignore
    if os.path.exists(".gitignore"):
        with open(".gitignore", "r") as f:
            gitignore_contents = f.read()
        if ".csync.cfg" not in gitignore_contents:
            console.print(
                "💡 [yellow]Consider adding .csync.cfg to your .gitignore to avoid committing sensitive info.[/yellow]"
            )
            with open(".gitignore", "a") as f:
                f.write("\n# Ignore csync config file\n.csync.cfg\n")
            console.print("✅ Added .csync.cfg to .gitignore", style="green")


@app.command()
def configure(
    remote_host: Annotated[
        Optional[str], typer.Option("--remote-host", "-H", help="Default remote hostname")
    ] = None,
    ssh_user: Annotated[
        Optional[str], typer.Option("--ssh-user", "-u", help="Default SSH username")
    ] = None,
    remote_path: Annotated[
        Optional[str], typer.Option("--remote-path", "-p", help="Default remote path")
    ] = None,
    ssh_port: Annotated[
        Optional[int], typer.Option("--ssh-port", help="Default SSH port")
    ] = None,
    show: Annotated[
        bool, typer.Option("--show", "-s", help="Show current global defaults")
    ] = False,
) -> None:
    """
    ⚙️  Set or show global defaults stored in ~/.config/csync/config.cfg.

    Values set here are used as defaults when running 'csync init'.
    """
    from rich.table import Table

    current = load_global_defaults()

    if show or not any([remote_host, ssh_user, remote_path, ssh_port]):
        if not current:
            console.print(
                f"No global defaults set. Config file: [cyan]{GLOBAL_CONFIG_FILE}[/cyan]",
                style="yellow",
            )
            console.print(
                "Use options like [bold cyan]--remote-host[/bold cyan] to set defaults."
            )
            return

        table = Table(title="⚙️  Global csync Defaults", header_style="bold blue")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        for key, value in current.items():
            table.add_row(key, str(value))
        console.print(table)
        console.print(f"\nConfig file: [dim]{GLOBAL_CONFIG_FILE}[/dim]")
        return

    updates = {
        k: v for k, v in {
            'remote_host': remote_host,
            'ssh_user': ssh_user,
            'remote_path': remote_path,
            'ssh_port': ssh_port,
        }.items() if v is not None
    }

    save_global_defaults(updates)
    console.print("✅ Global defaults updated:", style="green")
    for key, value in updates.items():
        console.print(f"  [cyan]{key}[/cyan] = {value}")
    console.print(f"\nSaved to [dim]{GLOBAL_CONFIG_FILE}[/dim]")


@app.command()
def start(
    config: Annotated[
        Optional[str], typer.Option("--config", "-c", help="Path to config file")
    ] = None,
    foreground: Annotated[
        bool,
        typer.Option(
            "--foreground", "-f", help="Run in foreground instead of daemon mode"
        ),
    ] = False,
) -> None:
    """
    🚀 Start background daemon to watch for changes and auto-sync.

    The daemon will watch for file changes and automatically push them to the remote server.
    """
    config_obj = find_and_load_config(config)

    try:
        from .daemon import start_daemon

        success = start_daemon(config_obj, console, detach=not foreground)
        if not success:
            raise typer.Exit(1)
    except ImportError:
        console.print(
            "❌ Daemon functionality not available. Install required dependencies.",
            style="red",
        )
        raise typer.Exit(1)


@app.command()
def stop(
    config: Annotated[
        Optional[str], typer.Option("--config", "-c", help="Path to config file")
    ] = None,
    local_path: Annotated[
        Optional[str], typer.Option("--path", help="Local path of daemon to stop")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Force kill the daemon")
    ] = False,
) -> None:
    """
    🛑 Stop the background daemon for the current or specified path.
    """
    # Determine which daemon to stop
    if local_path:
        target_path = os.path.abspath(local_path)
    elif config:
        config_obj = find_and_load_config(config)
        target_path = config_obj.local_path
    else:
        target_path = os.path.abspath(".")

    try:
        from .process_manager import get_process_manager

        process_manager = get_process_manager(console)
        success = process_manager.stop_daemon(target_path, force)
        if not success:
            raise typer.Exit(1)
    except ImportError:
        console.print("❌ Process management not available", style="red")
        raise typer.Exit(1)


@app.command("daemon-status")
def daemon_status() -> None:
    """
    📊 Show status of all running csync daemons.
    """
    try:
        from .process_manager import get_process_manager
        from rich.table import Table

        process_manager = get_process_manager(console)
        running_daemons = process_manager.list_running_daemons()

        if not running_daemons:
            console.print("🔍 No running csync daemons found", style="yellow")
            return

        # Create status table
        table = Table(
            title="🚀 Running csync Daemons", show_header=True, header_style="bold blue"
        )
        table.add_column("PID", style="cyan", width=8)
        table.add_column("Local Path", style="yellow")
        table.add_column("Remote Target", style="green")
        table.add_column("Started", style="white")
        table.add_column("Syncs", style="blue", justify="right")
        table.add_column("Last Sync", style="white")

        for daemon_info in running_daemons.values():
            import datetime

            started_time = datetime.datetime.fromtimestamp(
                daemon_info.started_at
            ).strftime("%H:%M:%S")

            last_sync = "Never"
            if daemon_info.last_sync:
                last_sync_time = datetime.datetime.fromtimestamp(daemon_info.last_sync)
                last_sync = last_sync_time.strftime("%H:%M:%S")

            table.add_row(
                str(daemon_info.pid),
                daemon_info.local_path,
                daemon_info.remote_target,
                started_time,
                str(daemon_info.sync_count),
                last_sync,
            )

        console.print(table)

    except ImportError:
        console.print("❌ Daemon functionality not available", style="red")
        raise typer.Exit(1)


@app.command()
def logs(
    config: Annotated[
        Optional[str], typer.Option("--config", "-c", help="Path to config file")
    ] = None,
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Follow log output (like tail -f)")
    ] = False,
) -> None:
    """
    📜 Show daemon log output for the current project.
    """
    import hashlib

    config_obj = find_and_load_config(config)
    abs_path = config_obj.local_path.rstrip("/")
    signature = "csync-" + hashlib.md5(abs_path.encode()).hexdigest()[:12]

    log_path = Path.home() / ".csync" / "daemons" / f"{signature}.log"
    if not log_path.exists():
        log_path = Path.home() / ".csync" / "daemon.log"
    if not log_path.exists():
        console.print("❌ No daemon log file found. Has a daemon been started?", style="red")
        raise typer.Exit(1)

    console.print(f"📜 Log file: [dim]{log_path}[/dim]")

    if not follow:
        lines = log_path.read_text().splitlines()
        for line in lines[-50:]:
            console.print(line)
        return

    console.print("Following log (Ctrl-C to stop)...", style="dim")
    with open(log_path, "r") as f:
        f.seek(0, 2)  # Seek to end
        try:
            while True:
                line = f.readline()
                if line:
                    console.print(line, end="")
                else:
                    import time as _time
                    _time.sleep(0.5)
        except KeyboardInterrupt:
            pass


@app.command()
def version() -> None:
    """
    Show version information.
    """
    from . import __version__

    version_text = Text()
    version_text.append("csync ", style="bold cyan")
    version_text.append(f"v{__version__}", style="bold green")

    panel = Panel(version_text, title="Version", border_style="blue")
    console.print(panel)


def main() -> None:
    """Main entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
