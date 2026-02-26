# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProjectBoss is a local CLI tool (`proj`) for creating, finding, and managing projects with consistent directory structure, a searchable index, and automatic staleness tracking. It is a **single-file Python 3 application** (`proj.py`, ~1400 lines) with **zero external dependencies** — pure stdlib only.

## Running

```bash
# Direct execution
python3 proj.py <command> [options]

# After installation (symlinks + shell function)
bash install.sh && source ~/.zshrc
proj <command>
```

There is no build step, no test suite, no linter configured.

## Architecture

`proj.py` is organized in clearly delimited sections:

1. **Constants** — `PROJ_DIR` (~/.proj/), paths to config/index/ignored JSON files, `DEFAULT_CONFIG`
2. **Helpers** — filesystem utils (`atomic_write_json`), text processing (`slugify`), status computation, frontmatter parsing, interactive prompts (`read_key`, `prompt_text`, `prompt_choice`), table formatting, date utils, git integration
3. **Data layer** — `load_config()`/`save_config()`, `load_index()`/`save_index()`, `load_ignored()`/`save_ignored()`, `find_entry()` for query resolution
4. **Template generation** — `generate_projects_index()`, `create_initial_prompt()`, `create_readme()`
5. **Command handlers** — `cmd_config`, `cmd_new`, `cmd_list`, `cmd_info`, `cmd_edit`, `cmd_open`, `cmd_rescan`, `cmd_ignore`, `cmd_help`
6. **CLI parser** — `build_parser()` using argparse with subparsers
7. **Main** — dispatch via command-name-to-function dictionary

### Key Design Decisions

- **Atomic writes**: All JSON saves go through `atomic_write_json()` (temp file + `os.replace`) to prevent corruption
- **Dynamic status**: Project status (active/stale/archived) is computed from `last_worked_at` timestamps, never stored
- **Flexible queries**: `find_entry()` resolves projects by numeric ID, ID prefix, name substring, or slug — handles ambiguity with user-friendly errors
- **Shell integration**: `proj open` requires a shell function (installed by `install.sh`) to `cd` into project directories
- **Custom frontmatter**: Hand-rolled YAML-ish frontmatter parser/writer to avoid PyYAML dependency
- **Symlink-aware**: Full symlink support with cycle detection via visited-realpath set

### Data Files (stored in ~/.proj/)

- `config.json` — base directories, categories, thresholds, editor preferences
- `index.json` — array of project entries (id, name, slug, category, path, timestamps, tags, etc.)
- `ignored.json` — array of paths excluded from discovery

## Code Conventions

- `snake_case` for all functions and variables; `UPPER_CASE` for constants
- Command handlers are named `cmd_<command>`
- Private/internal helpers prefixed with `_`
- Section dividers use `# ─────` comment lines
- Every command handler follows the pattern: load config/index → operate → save if modified
