# ProjectBoss

Local CLI tool (`proj`) for creating, finding, and managing projects with consistent structure, a searchable index, and automatic staleness tracking.

Zero external dependencies — pure Python 3 + stdlib.

**Requires macOS and zsh.** Opening projects uses `open -a`, the clipboard paste
in `proj new` uses `pbpaste`, and the installer writes a shell function to
`~/.zshrc`. Everything else is portable; those three are not.

## Installation

```bash
bash install.sh
source ~/.zshrc
```

This will:
- Symlink `proj.py` to `~/bin/proj.py`
- Add a `proj` shell function to `~/.zshrc` (enables `cd` via `proj open`)
- Create `~/.proj/`

The first time you run any command, `proj` asks where your projects live, what
categories you use, and which GitHub owners it may create repos under. Nothing
is assumed. Re-run that any time with `proj config init`, or edit the file
directly with `proj config edit`.

## Commands

### `proj new`

Create a new project interactively or with flags.

```bash
proj new                              # interactive
proj new --name "My Project" -c Work -s "A cool thing" --no-notes
proj new --adr                        # skip the decision-log question, always scaffold
proj new --no-adr                     # skip the decision-log question, never scaffold
proj new -o your-org                  # pick the GitHub owner up front
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

`--no-notes` is fully non-interactive: it initialises git (the prompt's default)
and skips every other question, so a decision log and a GitHub repo happen only
when `--adr`/`--adr-site` and `--org` ask for them.

### `proj list`

List projects in a table.

```bash
proj list                             # active + stale (non-archived)
proj list --status stale              # only stale
proj list --category Work --short     # compact output
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

**Misplaced repos.** A repo sitting at category level (e.g. `~/Projects/my-app/` with a `.git` in it) is in the wrong place — its subfolders are parts of one project, not separate projects. Discovery never descends into it. Instead it offers to move the repo under a category, indexes it as a single project, and repoints any existing index entries at the new location.

**`--review`** applies the same tests to what's already indexed. By default it only raises conclusive problems — dependency folders and subfolders of a project — and reports how many "no project markers" judgement calls it held back; add `-v` to review those too. Projects you created with `proj new` are never flagged. Answer `r` to remove from the index, `i` to remove and ignore, `k` to keep. Files on disk are never deleted. When you remove subfolders of a project that isn't itself indexed, it offers to index the real project.

### `proj ignore`

Remove non-project folders from the index and prevent them from being re-discovered.

```bash
proj ignore 3                         # ignore by ID
proj ignore "shared"                  # ignore by name
proj ignore ~/Projects/Work/shared-docs        # ignore by path
proj ignore --list                    # show all ignored paths
proj ignore --remove docs             # un-ignore (substring match)
```

### `proj adr`

A decision log: a durable record of *why* things are the way they are, one
[MADR](https://adr.github.io/)-format markdown file per decision in `docs/adr/`.

```bash
proj adr init                         # scaffold in the project containing the current directory
proj adr init 3                       # scaffold by ID, name, or slug
proj adr new "Postgres over DynamoDB" # write one record, dated and titled
proj adr new "..." -p 3               # write it in another project
proj adr init 3 --no-skill            # skip the .claude/skills/adr/SKILL.md agent skill
proj new --adr                        # scaffold at project creation time without asking
```

`proj new` offers a decision log alongside its other prompts; `--no-adr` skips the question.

Creates:

```
docs/adr/template.md          MADR template with agent guidance
docs/adr/README.md            how to create records, and the immutability rules
.claude/skills/adr/SKILL.md   Claude Code skill so agents read and write the log
```

`proj adr new` copies the template to `docs/adr/YYYYMMDD-slug.md` with the title and date filled
in and the agent-guidance comment stripped. Writing the file by hand works just as well.

Re-running `init` skips files that already exist, so it's safe on a project that already has a
log. `--force` overwrites them.

#### The website (`--site`)

[log4brains](https://github.com/thomvaill/log4brains) renders the same records as a searchable
static site. It's a Node tool, so it earns its place in a project with a real readership and not
in a three-record log or a project that isn't software. It's opt-in:

```bash
proj adr init --site                  # scaffold with the website
proj adr init --site --force          # add the website to a log that already exists
proj new --adr-site                   # at project creation time
```

That adds `docs/adr/index.md` (the knowledge-base homepage), `.log4brains.yml` (project name,
timezone, adrFolder), and a `/.log4brains` line in `.gitignore` for the build output. If the
project has a `package.json`, the `adr:new` / `adr:preview` / `adr:build` / `adr:serve` scripts
are merged into it using the runner matching its lockfile (pnpm, yarn, or npm); projects without
one get the pinned `npx` invocations directly in the generated docs.

The records are identical in both modes, same format and same filenames, so adding the site later
never renames or rewrites one. Use `--force` when you do, otherwise the README and skill are left
describing a markdown-only log.

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
"github_orgs": ["your-username", "your-org", "a-client-org"],
"default_github_org": "your-username"
```

`proj new` offers these when creating a repo. Personal accounts and
organisations are interchangeable here: `gh` treats both as an owner. Leave the
list empty and `proj new` asks for an owner by hand.

## Data

- Config: `~/.proj/config.json`
- Index: `~/.proj/index.json`
- Ignored: `~/.proj/ignored.json`
- Projects Index: `PROJECTS_INDEX.md` at the root of each base directory

## Symlinks

Symlinked project folders work transparently. If you symlink a project into your base directory structure (e.g. `ln -s /Volumes/WORK/my-project ~/Projects/Work/my-project`), it will be discovered by `rescan --discover`, and all commands (`open`, `info`, `rescan` mtime scanning) follow symlinks correctly.

## Shell Integration

The `proj` shell function wraps `proj.py` so that `proj open` can `cd` into the project directory. This coexists with any existing `prj` alias.

## Tests

Stdlib `unittest`, nothing to install:

```bash
python3 -m unittest discover        # all tests
python3 -m unittest discover -v     # per-test names
```

Tests never touch the real `~/.proj`: anything that writes to disk uses a temp
directory, and the data-layer tests repoint the module's paths at it.

## Licence

MIT. See [LICENSE](LICENSE).
