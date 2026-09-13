# Changelog

Versions are CalVer, `YYYY.MM.PATCH`, from 2026.09.0 onwards. Releases up to
0.8.0 used SemVer. CalVer carries no compatibility signal, so any change to the
on-disk index format is called out explicitly in its entry.

## 2026.09.0

**The command is now `pb`, not `proj`.** `brew install proj` installs PROJ, the
cartographic projections library, which puts a `proj` binary on `PATH` and
arrives as a dependency of gdal, postgis and qgis. Shipping a tool that shadows
it, or gets shadowed by it depending on `PATH` order, was a defect rather than a
preference. Nothing in Homebrew or on a stock macOS installs a `pb` command.

- `proj.py` is now `pb.py`, the shell function is `pb`, and the environment
  variable the function sets is `PB_SHELL_WRAPPER`
- **The data directory moved from `~/.proj` to `~/.pb`.** It migrates itself on
  first run, and only when the old directory exists and the new one does not, so
  it can never merge two sets of data or overwrite anything. The notice goes to
  stderr so that stdout stays parseable
- Re-run `bash install.sh && source ~/.zshrc` to replace the old shell function.
  The old `proj` name is deliberately not kept as an alias: it would re-create
  the collision for exactly the people the rename protects
- Add `pb list --json` for scripts and agents. It emits the same object shape as
  `pb info --json`, which means the stored fields plus `status`, computed from
  `last_worked_at` rather than stored. Filters, sorting and `--limit` apply, so
  the JSON is exactly what the table would have shown; an empty result is `[]`
  rather than prose
- Ship a Claude Code skill at `skills/pb/SKILL.md` so an agent can resolve a
  project the user names out loud into a path. `install.sh` offers to link it
  into `~/.claude/skills/` and defaults to no, because a project CLI has no
  business writing into an agent's config directory uninvited
- Remove every em dash and en dash from the repository, including the ADR
  templates that get scaffolded into other people's projects, and add a test
  that fails if one comes back
- `pb info` now prints `-` rather than an em dash for an empty field
- Keep the original product brief in the repository as `docs/original-brief.md`, with a header saying what it is and that the command shipped as `pb`. It was published by the `.gitignore` change in the previous release; keeping it deliberately beats leaving it there by accident

## 0.8.0

- Add a test suite: 85 tests in `test_proj.py`, stdlib `unittest`, no dependencies. Run with `python3 -m unittest discover`. Covers slugging, status thresholds, query resolution, ID allocation, frontmatter, remote-URL parsing, discovery classification, index review, the ignore list, the data layer, template rendering, and both ADR modes
- Fix `is_ignored` comparing paths case-sensitively. It used `os.path.normcase`, which is a no-op on everything except Windows, so the case-insensitive matching the code claimed to do never happened: a path typed into `proj ignore` with different casing to the one on disk silently failed to match. It now casefolds, and compares realpaths on both sides so a symlink matches its target either way round
- Every test that touches disk uses a temp directory, and the data-layer tests repoint proj's module paths, so a test run can never read or write the real `~/.proj`
- Run the tests in CI: a GitHub Actions workflow on push and pull request, against Python 3.9 and 3.13 on macOS. macOS because `proj` shells out to `open` and `pbpaste` and the installer writes to `~/.zshrc`, so a Linux run would pass while proving nothing; 3.9 because that is the `python3` macOS ships
- Rewrite the README opening. It led with one line of description and then a command reference, which told a visitor nothing about why they would want the tool. It now opens with the problem, real `proj list` output, and the three things that are actually distinctive: computed status, discovery, and review
- `.gitignore` no longer ignores all of `docs/`, which meant the project could never commit its own documentation. It now ignores only the generated per-project prompt files

## 0.7.0

- Add an MIT `LICENSE`. The repository was public without one, which meant nobody could legally copy, modify or fork it
- `DEFAULT_CONFIG` no longer ships one person's setup. Categories and GitHub owners start empty, the base directory is `~/Projects`, and the editors are blank (an empty editor name hands the path to whatever the OS opens it with, instead of a named app the user may not have installed)
- The first interactive run asks where projects live, which categories to use, and which GitHub owners `proj new` may create repos under, then writes the config. `proj config init` runs the same prompts. Non-interactive first runs (no tty) fall back to the defaults silently rather than hanging on a prompt
- README states the macOS and zsh requirement up front: `open -a`, `pbpaste` and the `~/.zshrc` shell function are the three things that aren't portable
- README examples use neutral names rather than the author's own categories and organisations

## 0.6.0

- Remove `proj reflect`. It reviewed findings from ReflectFlow, which is defunct, and read them from `~/.claude/reflectflow/staging`, a path nobody but its author had, so the command silently did nothing for everyone else. 250 lines gone

## 0.5.0

- The ADR decision log no longer requires log4brains. `proj adr init` now scaffolds plain markdown (`docs/adr/template.md`, `README.md`, and the agent skill) and nothing else: no `.log4brains.yml`, no `package.json` scripts, no `.gitignore` entry, no Node. log4brains is a website generator, which earns its place in a platform with a readership and not in a three-record log or a project that isn't software
- Add `proj adr init --site` for the log4brains version. The records are identical either way, same MADR format and same `YYYYMMDD-slug.md` names, so running it over an existing plain log adds the website without renaming or rewriting a single record (pass `--force` to refresh the README and skill prose, which otherwise still describe a markdown-only log)
- Add `proj adr new "<title>"`, which writes `docs/adr/YYYYMMDD-slug.md` from the project's template with the title and date filled in and the agent-guidance comment stripped. log4brains used to be the only thing that created a record; without this, a plain log had no way to start one
- `proj new` now asks "Add a decision log?" alongside the other prompts, defaulting to yes. `--adr` and the new `--adr-site` still scaffold without asking, and `--no-adr` skips the question
- `--no-notes` is now genuinely non-interactive. It previously still stopped for the git-init and change-directory prompts, so a scripted `proj new` hung or aborted. It takes the git-init default and skips the rest; a decision log or a GitHub repo is created only when the matching flag says so

## 0.4.0

- `proj new` now offers to create a GitHub repo after `git init`, choosing the owner from a new `github_orgs` list in the config with `default_github_org` pre-selected. Personal accounts and organisations are the same thing to `gh`, so both live in the one list
- The repo is created private with `origin` set and pushed. `gh repo create --push` has nothing to push from an empty repo, so an initial commit is made first when the project has none
- Add `proj new --org <owner>` to skip the prompt and `proj new --no-remote` to stay local. Under `--no-notes` a repo is created only when `--org` is given, so unattended runs never publish by accident
- Every failure along the way (staging, committing, `gh`) prints the underlying error and leaves the project intact rather than failing silently
- `git init` now passes `--initial-branch=main`. Without a global `init.defaultBranch` set, every project `proj new` created started on `master` and pushed that to GitHub as the default branch

## 0.3.0

- `proj rescan --discover` now proposes instead of writing. Previously it added every directory it walked past straight to the index and printed the result as a receipt; it now reviews candidates with you and saves only on confirmation
- Discovery skips dependency and build directories (`node_modules`, `dist`, `build`, `.venv`, `target`, …). The skip list already existed but was only used for mtime walks, never for discovery
- Candidates are classified by evidence found inside them: `.git` or a build manifest means project, `README.md`/`docs/`/`src/` alone means maybe, nothing means probably not. The suggested action follows the classification and Enter accepts it
- A repo sitting at category level is treated as misplaced rather than descended into. Discovery offers to move it under a category, indexes it as one project, and repoints existing index entries at the new location
- Moving a repo into a category adds that category to the config list if it's missing
- Add `proj rescan --review` to apply the same tests to entries already in the index, flagging dependency folders and subfolders of a project. Removes from the index only, never deletes files, and offers to index the real parent project
- `--review` holds back "no project markers" judgement calls by default (reporting the count) and includes them with `-v`; entries created via `proj new` are never flagged
- Add `proj rescan --discover --yes` for non-interactive use: adds only candidates with conclusive evidence, leaves the rest alone
- `_base_for_path` compares absolute paths, so a relative or non-normalised base directory in the config still matches index entries

## 0.2.1

- Fix the welcome logo rendering "Project" with the `j` looking like an `i`. The figlet descender row was missing
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
- Zero external dependencies: pure Python 3 stdlib
