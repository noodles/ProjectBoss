# Changelog

## 0.1.3

- Add `proj idea` command for quick-capturing project ideas with emoji category labels (bug, feature, improvement, etc.)
- "New App" type option for capturing ideas that aren't tied to an existing project
- Interactive flow narrows projects by project group first to keep lists manageable
- Ideas are stored locally in `~/.proj/ideas.json` and can optionally be pushed as GitHub issues via `gh`
- Support `--list` to view open ideas grouped by project, `--done <id>` to mark ideas complete, and `--quick` for non-interactive capture

## 0.1.2

- Add colorized welcome screen with Project Boss ASCII art logo, dynamic project stats, quick-start command reference, and bordered tips box
- ANSI colors degrade gracefully when piped or when `NO_COLOR` is set

## 0.1.1

- Add optional `git init` step to `proj new` workflow

## 0.1.0

- Initial release of `proj` CLI
- Project creation (`proj new`) with interactive prompts, clipboard paste support, and editor menu
- Project listing (`proj list`) with status filtering, sorting, and table output
- Project lookup (`proj info`, `proj open`, `proj edit`) by ID, name, or slug
- Automatic status computation (active/stale/archived) based on `last_worked_at` timestamps
- `proj rescan` for discovering unindexed projects in base directories
- `proj ignore` for excluding non-project folders from discovery
- `proj config` for managing settings (base directories, categories, thresholds, editors)
- Shell integration via `install.sh` for `proj open` directory switching
- Symlink-aware scanning with cycle detection
- Atomic JSON writes to prevent data corruption
- Zero external dependencies — pure Python 3 stdlib
