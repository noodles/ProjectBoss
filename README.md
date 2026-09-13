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
proj new --adr                        # also scaffold an ADR decision log
proj new -o momentous-developments    # pick the GitHub owner up front
proj new --no-remote                  # local git only, no GitHub repo
```

Creates: `{base}/{category}/{slug}/docs/` with initial prompt and README.

After `git init` it offers to create a GitHub repo. The owner comes from the
`github_orgs` list in `~/.proj/config.json`, with `default_github_org`
pre-selected; a personal account is just another entry in that list. The repo is
created private, an initial commit is made if the project has none, and `origin`
is set and pushed.

`--org` skips the prompt and uses that owner. `--no-remote` skips GitHub
entirely. With `--no-notes`, a repo is only created when `--org` is given, so an
unattended run never publishes anything by accident.

### `proj list`

List projects in a table.

```bash
proj list                             # active + stale (non-archived)
proj list --status stale              # only stale
proj list --category Noodle --short   # compact output
proj list --sort name --limit 5
```

### `proj info <query>`

Show full details for a project. Query by ID, name, or slug. Auto-detects GitHub/Bitbucket repo URLs from git remotes.

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
proj rescan --discover                # review unindexed folders, add the real projects
proj rescan --discover --yes          # add obvious projects without prompting
proj rescan --review                  # re-check entries already in the index
proj rescan --review -v               # also review folders with no project markers
```

Use `--discover` after initial install to import all your existing projects.

**How discovery decides what's a project.** Projects live at `<base>/<category>/<project>`. Discovery skips dependency and build folders (`node_modules`, `dist`, `build`, `.venv`, `target`, …), then looks inside each remaining folder for evidence:

| Evidence | Verdict |
|---|---|
| `.git`, or a manifest (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, …) | looks like a project — suggested `add` |
| Only `README.md`, `docs/`, `src/`, `CLAUDE.md` | might be — suggested `add` |
| Nothing | probably not — suggested `ignore` |

Nothing is written until you confirm. Answer `a` to add, `i` to ignore permanently, `s` to skip, or `q` to stop; Enter accepts the suggestion. `--yes` skips the review and adds only the folders with conclusive evidence.

**Misplaced repos.** A repo sitting at category level (e.g. `01_Projects/my-app/` with a `.git` in it) is in the wrong place — its subfolders are parts of one project, not separate projects. Discovery never descends into it. Instead it offers to move the repo under a category, indexes it as a single project, and repoints any existing index entries at the new location.

**`--review`** applies the same tests to what's already indexed. By default it only raises conclusive problems — dependency folders and subfolders of a project — and reports how many "no project markers" judgement calls it held back; add `-v` to review those too. Projects you created with `proj new` are never flagged. Answer `r` to remove from the index, `i` to remove and ignore, `k` to keep. Files on disk are never deleted. When you remove subfolders of a project that isn't itself indexed, it offers to index the real project.

### `proj ignore`

Remove non-project folders from the index and prevent them from being re-discovered.

```bash
proj ignore 3                         # ignore by ID
proj ignore "shared"                  # ignore by name
proj ignore ~/Documents/01_Projects/NVE/docs   # ignore by path
proj ignore --list                    # show all ignored paths
proj ignore --remove docs             # un-ignore (substring match)
```

### `proj adr init`

Scaffold an Architecture Decision Record log in a project — a durable record of *why* things are
the way they are, in [MADR](https://adr.github.io/) format, browsable as a searchable site via
[log4brains](https://github.com/thomvaill/log4brains).

```bash
proj adr init                         # scaffold in the project containing the current directory
proj adr init 3                       # scaffold by ID, name, or slug
proj adr init 3 --force               # overwrite existing scaffold files
proj adr init 3 --no-skill            # skip the .claude/skills/adr/SKILL.md agent skill
proj new --adr                        # scaffold at project creation time
```

Creates:

```
docs/adr/template.md          MADR template with agent guidance
docs/adr/README.md            how to browse, and the immutability rules
docs/adr/index.md             knowledge-base homepage
.log4brains.yml               project name, timezone, adrFolder
.claude/skills/adr/SKILL.md   Claude Code skill so agents read and write the log
.gitignore                    appends /.log4brains (build output)
```

If the project has a `package.json`, the `adr:new` / `adr:preview` / `adr:build` / `adr:serve`
scripts are merged into it, using the runner matching its lockfile (pnpm, yarn, or npm). Projects
without one get the pinned `npx` invocations directly in the generated docs — log4brains needs
only `.log4brains.yml` and `docs/adr/template.md`, not a Node project.

Re-running skips files that already exist, so it's safe on a project that already has a log.

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

## GitHub owners

```json
"github_orgs": ["noodles", "momentous-developments", "NVE-Team"],
"default_github_org": "noodles"
```

`proj new` offers these when creating a repo. Personal accounts and
organisations are interchangeable here: `gh` treats both as an owner.

## Data

- Config: `~/.proj/config.json`
- Index: `~/.proj/index.json`
- Ignored: `~/.proj/ignored.json`
- Projects Index: `PROJECTS_INDEX.md` at the root of each base directory

## Symlinks

Symlinked project folders work transparently. If you symlink a project into your base directory structure (e.g. `ln -s /Volumes/WORK/my-project ~/Documents/01_Projects/Noodle/my-project`), it will be discovered by `rescan --discover`, and all commands (`open`, `info`, `rescan` mtime scanning) follow symlinks correctly.

## Shell Integration

The `proj` shell function wraps `proj.py` so that `proj open` can `cd` into the project directory. This coexists with any existing `prj` alias.
