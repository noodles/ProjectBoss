# ProjectBoss

Local CLI tool (`proj`) for creating, finding, and managing projects with consistent structure, a searchable index, and automatic staleness tracking.

Zero external dependencies — pure Python 3 + stdlib.

## Installation

```bash
bash install.sh
source ~/.zshrc
```

This will:
- Symlink `proj.py` to `~/bin/proj.py`
- Add a `proj` shell function to `~/.zshrc` (enables `cd` via `proj open`)
- Create `~/.proj/` with default config

## Commands

### `proj new`

Create a new project interactively or with flags.

```bash
proj new                              # interactive
proj new --name "My Project" -c Noodle -s "A cool thing" --no-notes
```

Creates: `{base}/{category}/{slug}/docs/` with initial prompt and README.

### `proj list`

List projects in a table.

```bash
proj list                             # active + stale (non-archived)
proj list --status stale              # only stale
proj list --category Noodle --short   # compact output
proj list --sort name --limit 5
```

### `proj info <query>`

Show full details for a project. Query by ID, name, or slug.

```bash
proj info 3
proj info "my project"
proj info --json 3
```

### `proj edit <query>`

Edit project metadata.

```bash
proj edit 3                           # interactive
proj edit 3 --summary "New summary"
proj edit 3 --archive
proj edit 3 --tag backend --tag api
proj edit 3 --untag api
```

### `proj open <query>`

Open/navigate to a project. The shell function does `cd` automatically.

```bash
proj open 3                           # cd to project root
proj open 3 --docs                    # cd to docs/
proj open 3 --editor                  # open in configured editor
proj open 3 --finder                  # open in Finder
```

### `proj rescan`

Update timestamps from filesystem and discover unindexed projects. Follows symlinks, so symlinked project folders are fully supported.

```bash
proj rescan                           # update timestamps
proj rescan --discover                # also find unindexed projects in base dirs
proj rescan --discover --verbose      # show each discovered project
```

Use `--discover` after initial install to import all your existing projects.

### `proj help`

Show help for any command.

```bash
proj help                             # list all commands
proj help new                         # show flags for a specific command
```

### `proj config`

Manage configuration.

```bash
proj config show                      # print config
proj config init                      # create default config
proj config edit                      # open in editor
proj config set editor code           # set a single value
proj config set status_thresholds.stale_after_days 7
```

## Project Status

Status is computed dynamically from `last_worked_at`:
- **active**: worked on within the last 14 days
- **stale**: 14–90 days since last activity
- **archived**: 90+ days or manually archived

Thresholds are configurable in `~/.proj/config.json`.

## Data

- Config: `~/.proj/config.json`
- Index: `~/.proj/index.json`
- Projects Index: `PROJECTS_INDEX.md` at the root of each base directory

## Symlinks

Symlinked project folders work transparently. If you symlink a project into your base directory structure (e.g. `ln -s /Volumes/WORK/my-project ~/Documents/01_Projects/Noodle/my-project`), it will be discovered by `rescan --discover`, and all commands (`open`, `info`, `rescan` mtime scanning) follow symlinks correctly.

## Shell Integration

The `proj` shell function wraps `proj.py` so that `proj open` can `cd` into the project directory. This coexists with any existing `prj` alias.
