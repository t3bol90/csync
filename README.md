# csync 🚀

A modern Python wrapper for rsync to sync code between local and remote machines.
## QUICK START
```bash
# install
uv pip install git+https://github.com/anhvth/csync
# run
csync --help
```
## Features

- 🎨 **Modern CLI** - Built with Typer and Rich for beautiful, colorful output
- 📁 **Push & Pull** - Bidirectional sync between local and remote
- 🔧 **Flexible Config** - Support for .cfg, JSON, and YAML formats  
- 🔍 **Dry Run** - Preview changes before syncing
- 🚫 **Smart Excludes** - Automatic .gitignore integration
- 📋 **Rich Status** - Beautiful configuration overview
- 🔄 **Auto-discovery** - Finds config files automatically

## Installation

Install using uv:

```bash
uv pip install .
```

Or install from source:

```bash
git clone <repository>
cd csync
uv pip install .
```

## Quick Start

1. **Initialize configuration:**
   ```bash
   csync init
   ```

2. **Edit the generated `.csync.cfg`** with your server details:
   ```ini
   [csync]
   local_path = .
   remote_host = your-server.com
   remote_path = /path/to/remote/directory
   ssh_user = your-username
   ```

3. **Push local files to remote:**
   ```bash
   csync push
   ```

4. **Pull remote files to local:**
   ```bash
   csync pull
   ```

## Commands

### `csync init`

Create a sample configuration file with automatic .gitignore creation.

```bash
csync init                    # Create .csync.cfg
csync init -c myconfig.cfg    # Create custom config file
csync init --force            # Overwrite existing config
```

### `csync push`

🚀 Push local files to remote server.

```bash
csync push                    # Push files
csync push --dry-run          # Preview what would be pushed
csync push --quiet            # Suppress verbose output
```

### `csync pull`

📥 Pull remote files to local directory.

```bash
csync pull                    # Pull files  
csync pull --dry-run          # Preview what would be pulled
csync pull --quiet            # Suppress verbose output
```

### `csync status`

📋 Show beautiful configuration overview with Rich formatting.

```bash
csync status
```

### `csync version`

Show version information.

```bash
csync version
```

## Configuration

The configuration file (`.csync.cfg`) uses INI format and supports auto-discovery - csync will search the current directory and parent directories.

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `local_path` | string | **required** | Local directory path to sync |
| `remote_host` | string | **required** | Remote server hostname/IP |
| `remote_path` | string | **required** | Remote directory path |
| `ssh_user` | string | optional | SSH username |
| `ssh_port` | number | optional | SSH port (if not 22) |
| `rsync_options` | comma-separated | `-av, --progress` | Rsync options |
| `exclude_patterns` | comma-separated | see below | Files/directories to exclude |
| `respect_gitignore` | boolean | `true` | Include .gitignore patterns |

### Default Exclude Patterns

```
.git/, __pycache__/, *.pyc, .DS_Store, node_modules/, .venv/, venv/, .pytest_cache/, *.log
```

### Example Configuration

```ini
[csync]
local_path = .
remote_host = myserver.com
remote_path = /home/user/myproject
ssh_user = user
ssh_port = 2222
rsync_options = -av, --progress, --delete
exclude_patterns = .git/, __pycache__/, *.pyc, build/, dist/
respect_gitignore = true
```

### Alternative Formats

You can also use JSON or YAML formats:

**JSON (.csync_config.json):**
```json
{
  "local_path": ".",
  "remote_host": "myserver.com",
  "remote_path": "/home/user/myproject",
  "ssh_user": "user",
  "respect_gitignore": true
}
```

**YAML (.csync_config.yml):**
```yaml
local_path: "."
remote_host: "myserver.com"
remote_path: "/home/user/myproject"
ssh_user: "user"
respect_gitignore: true
```

## Global Options

- `-c, --config PATH`: Use specific config file (default: auto-discover)

## Examples

### Basic Workflow

```bash
# Set up configuration
csync init
# Edit .csync.cfg with your settings

# Check configuration
csync status

# Preview changes
csync push --dry-run

# Push local changes to remote
csync push

# Pull remote changes to local
csync pull
```

### Advanced Usage

```bash
# Use custom config file
csync -c production.cfg push

# Quiet mode for scripts
csync push --quiet

# Preview before pulling
csync pull --dry-run
```

## Modern CLI Features

Built with modern Python CLI best practices:

- ✨ **Typer** - Modern CLI framework with automatic help generation
- 🎨 **Rich** - Beautiful terminal output with colors, tables, and panels
- 🔤 **Type Hints** - Full type safety and better IDE support  
- 📖 **Auto Documentation** - Commands are self-documenting
- 🎯 **User-Friendly** - Clear error messages and helpful guidance
- 🔧 **Extensible** - Easy to add new commands and features

## Requirements

- Python 3.13+
- rsync (must be installed and available in PATH)
- SSH access to remote server (for remote operations)

## Dependencies

- **typer** - Modern CLI framework
- **rich** - Beautiful terminal output  
- **pyyaml** - YAML configuration support

## Project Structure

```
src/
└── csync/
    ├── __init__.py          # Package initialization
    ├── cli.py               # Modern Typer CLI interface  
    ├── config.py            # Configuration handling (.cfg/JSON/YAML)
    └── rsync.py             # Rsync wrapper functionality
```

## License

MIT License
