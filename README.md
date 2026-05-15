# csync 🚀

This is a fork of @anhvth’s repo: [https://github.com/anhvth/csync](https://github.com/anhvth/csync)

> Yet another modern Python wrapper for `rsync` to sync code between local and remote machines.

My workflow is simple: I write code on my local machine, sync it to an HPC server to run and collect results, create backups with Git, and sometimes sync the entire codebase to a remote development server for backup.

The original author no longer maintains the project, so I decided to fork it and maintain my own version.

## Quick start

```bash
uv pip install -e .
csync configure --remote-host my.server.com --ssh-user me   # one-time global defaults
csync init                                                  # creates .csync.cfg in cwd
csync push                                                  # one-shot push
csync start                                                 # daemon: watch local, push on change
csync start --mode pull                                     # daemon: poll remote, pull every sync_delay
```

## Configuration

Per-project config lives in `.csync.cfg` (INI, JSON, or YAML). `csync init` generates a starter file. Global defaults are merged in from `~/.config/csync/config.cfg` (managed via `csync configure`).

| Field | Type | Default | Purpose |
|---|---|---|---|
| `local_path` | str | `.` | Local directory to sync. Absolutized at load; on Windows, MSYS-style paths like `/f/xxx` are preserved verbatim. |
| `remote_host` | str | _(required)_ | Hostname or IP of the remote. |
| `remote_path` | str | _(required)_ | Destination path on the remote. |
| `ssh_user` | str | _from global defaults_ | SSH username. |
| `ssh_port` | int | _from global defaults_ | SSH port (rsync uses 22 when unset). |
| `exclude_patterns` | list[str] | sensible defaults (`.git/`, `__pycache__/`, `*.pyc`, `.DS_Store`, `node_modules/`, `.venv/`, `venv/`, `.pytest_cache/`, `*.log`) | Paths/globs to skip. Directory patterns end with `/`. |
| `rsync_options` | list[str] | `["-av", "--progress"]` | Extra rsync flags. `--delete` is intentionally not included. |
| `respect_gitignore` | bool | `true` | Merge `.gitignore` patterns into `exclude_patterns` on load. |
| `sync_mode` | str (`push`/`pull`) | `push` | Daemon direction. Ignored by one-shot `push`/`pull` commands. |

### Global defaults

Stored in `~/.config/csync/config.cfg` and used by `csync init` and the daemon. Currently supported keys: `remote_host`, `ssh_user`, `remote_path`, `ssh_port`, `sync_delay` (daemon debounce/poll interval in seconds; default `5.0`).

## Daemon modes

- **`push`** (default): watchdog observes the local directory and triggers an rsync push after an adaptive debounce window (~100 ms for a single file, longer for bursts).
- **`pull`**: no FS watching; the daemon runs `rsync` from remote to local every `sync_delay` seconds. Useful when changes originate on the remote side.

Override at start time with `csync start --mode pull` (or set `sync_mode = pull` in `.csync.cfg`).

## Worklogs

* 2026/02/03
   * Fixed the daemon spawn issue that previously did not work.
   * Added unit tests to support further development.
   * Added worktree and subagent setup for a smoother development workflow.
* 2026/05/15
   * Added daemon pull mode (`csync start --mode pull`) — polls remote and pulls into local.
   * Preserved MSYS/Git-Bash style paths (e.g. `/f/xxx`) verbatim on Windows so rsync receives them unchanged.
   * Fixed `csync init` so `ssh_user` is always emitted (with a `your-username` placeholder if no global default is set).
