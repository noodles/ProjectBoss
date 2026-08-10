# Changelog

## 0.2.1

- Fix the welcome logo rendering "Project" with the `j` looking like an `i` — the figlet descender row was missing
- `proj idea --list` now prints a usage hint (`proj idea -d <id>` / `proj idea --delete <id>`) so the listed IDs point at the right command
- `install.sh` now replaces an existing `proj` shell function in `~/.zshrc` instead of skipping it, so shell-side features ship on reinstall (backs up to `~/.zshrc.proj-backup`); previously the cd-on-new handler never reached existing installs
- The shell function sets `PROJ_SHELL_WRAPPER=1`; `proj new` uses it to warn and print a `cd` command when the wrapper is missing, instead of silently doing nothing

## 0.2.0

- Add `proj adr init` to scaffold an Architecture Decision Record log in a project
- Scaffolds `docs/adr/` (template, README, knowledge-base index), `.log4brains.yml`, a `/.log4brains` gitignore entry, and a `.claude/skills/adr/SKILL.md` agent skill
- Merges `adr:new` / `adr:preview` / `adr:build` / `adr:serve` scripts into `package.json` when the project has one; otherwise the generated docs use pinned `npx` invocations directly (log4brains needs no Node project, only `.log4brains.yml` + `template.md`)
- Detects the script runner from the lockfile (pnpm / yarn / npm) and the IANA timezone from `/etc/localtime`
- Resolves the target project from a query, or from the current directory when none is given
- `--force` overwrites existing scaffold files; `--no-skill` skips the agent skill
- Add `proj new --adr` to scaffold the log at project creation time

## 0.1.9

- Add `proj reflect` command for interactive review of ReflectFlow findings
- Interactive flow: view each finding, then Apply (route to rules/CLAUDE.md/memory), Dismiss (archive), Skip, or Show full
- `--list` flag for non-interactive summary of pending findings by type
- `--dismiss-errors` flag to bulk-archive error-only findings
- Auto-dismisses error-only findings (e.g. "Error: Exceeded USD budget") before interactive review

## 0.1.8

- Add `--reslug-check` flag to `proj rescan` for interactive review of each project directory name with accept/custom/skip options
- Fix `--reslug` failing on macOS case-insensitive filesystem (e.g. `Bookstart` → `bookstart` was incorrectly skipped as "already exists")

## 0.1.7

- Add `--reslug` flag to `proj rescan` to rename existing project directories to match current slugify rules and update all index paths

## 0.1.6

- Improve `slugify` to insert hyphens at camelCase boundaries (e.g. "CalendarSync" → `calendar-sync` instead of `calendarsync`)

## 0.1.5

- Add "Change into the new project directory?" prompt as the final step of `proj new`
- Shell function updated to handle cd-target signal so the parent shell changes directory

## 0.1.4

- Add `proj delete` command (aliased as `proj rm`) for removing projects from the index, with optional disk cleanup
- Add `--prune` flag to `proj rescan` to bulk-remove projects whose directories no longer exist
- Add `--delete <id>` flag to `proj idea` for deleting ideas
- `proj rescan` now reports missing projects by default instead of silently skipping them
- Skip `node_modules`, `__pycache__`, `venv`, and other heavy directories during rescan to fix slow/hanging rescans
- Update welcome screen to list all commands instead of a subset
- Add missing help text to `list` and `edit` argument parsers

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
