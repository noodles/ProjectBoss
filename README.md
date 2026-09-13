# ProjectBoss

[![test](https://github.com/noodles/ProjectBoss/actions/workflows/test.yml/badge.svg)](https://github.com/noodles/ProjectBoss/actions/workflows/test.yml)

`pb` is a command-line tool for people whose projects folder has got away
from them. It creates projects with the same structure every time, keeps an
index of them so you can find one by a fragment of its name, and tells you
which ones you have quietly stopped working on.

```console
$ pb list
ID   Name             Status   Category   Last Worked   Summary
──   ──────────────   ──────   ────────   ───────────   ────────────────────────
1    Invoice Chaser   active   Work       2026-09-13    Chases overdue invoices…
2    Site Redesign    stale    Clients    2026-08-23    Marketing site rebuild
3    Recipe Box       stale    Personal   2026-08-04    Somewhere to keep recip…

$ pb open recipe        # any fragment of the name works, and it cd's you there
Opened: /Users/you/Projects/Personal/recipe-box
```

`pb new` asks a few questions, then makes the folder, a README, a docs
folder, a git repo, optionally a GitHub repo, and optionally a decision log,
and records it all in the index.

**Status is worked out, not stored.** A project is active, stale after two
weeks of silence, or archived after three months. You never mark anything;
`pb list` just stops lying to you about what you are actually working on.

**Nothing gets lost.** `pb rescan --discover` walks your projects folder and
offers to index anything it finds that looks like a real project, and
`--review` does the reverse: it flags entries that turned out to be a
`node_modules`, or a subfolder of a project you already have.

## Requirements

Python 3.9 or newer, macOS, and zsh. No packages to install: it is one file of
standard library.

The macOS part is real rather than untested caution. Opening projects uses
`open -a`, the clipboard paste in `pb new` uses `pbpaste`, and the installer
writes a shell function to `~/.zshrc`. Everything else is portable; those three
are not.

## Installation

```bash
bash install.sh
source ~/.zshrc
```

This will:
- Symlink `pb.py` to `~/bin/pb.py`
- Add a `pb` shell function to `~/.zshrc` (enables `cd` via `pb open`)
- Create `~/.pb/`
- Offer, but not force, a Claude Code skill (see [Agents](#agents))

The first time you run any command, `pb` asks where your projects live, what
categories you use, and which GitHub owners it may create repos under. Nothing
is assumed. Re-run that any time with `pb config init`, or edit the file
directly with `pb config edit`.

## Commands

### `pb new`

Create a new project interactively or with flags.

```bash
pb new                              # interactive
pb new --name "My Project" -c Work -s "A cool thing" --no-notes
pb new --adr                        # skip the decision-log question, always scaffold
pb new --no-adr                     # skip the decision-log question, never scaffold
pb new -o your-org                  # pick the GitHub owner up front
pb new --no-remote                  # local git only, no GitHub repo
```

Creates: `{base}/{category}/{slug}/docs/` with initial prompt and README.

After `git init` it offers to create a GitHub repo. The owner comes from the
`github_orgs` list in `~/.pb/config.json`, with `default_github_org`
pre-selected; a personal account is just another entry in that list. The repo is
created private, an initial commit is made if the project has none, and `origin`
is set and pushed.

`--org` skips the prompt and uses that owner. `--no-remote` skips GitHub
entirely. With `--no-notes`, a repo is only created when `--org` is given, so an
unattended run never publishes anything by accident.

`--no-notes` is fully non-interactive: it initialises git (the prompt's default)
and skips every other question, so a decision log and a GitHub repo happen only
when `--adr`/`--adr-site` and `--org` ask for them.

### `pb list`

List projects in a table.

```bash
pb list                             # active + stale (non-archived)
pb list --status stale              # only stale
pb list --category Work --short     # compact output
pb list --sort name --limit 5
```

### `pb info <query>`

Show full details for a project. Query by ID, name, or slug. Auto-detects GitHub/Bitbucket repo URLs from git remotes.

```bash
pb info 3
pb info "my project"
pb info --json 3
```

### `pb edit <query>`

Edit project metadata.

```bash
pb edit 3                           # interactive
pb edit 3 --summary "New summary"
pb edit 3 --archive
pb edit 3 --tag backend --tag api
pb edit 3 --untag api
```

### `pb open <query>`

Open/navigate to a project. The shell function does `cd` automatically.

```bash
pb open 3                           # cd to project root
pb open 3 --docs                    # cd to docs/
pb open 3 --editor                  # open in configured editor
pb open 3 --finder                  # open in Finder
```

### `pb rescan`

Update timestamps from filesystem and discover unindexed projects. Follows symlinks, so symlinked project folders are fully supported.

```bash
pb rescan                           # update timestamps
pb rescan --discover                # review unindexed folders, add the real projects
pb rescan --discover --yes          # add obvious projects without prompting
pb rescan --review                  # re-check entries already in the index
pb rescan --review -v               # also review folders with no project markers
```

Use `--discover` after initial install to import all your existing projects.

**How discovery decides what's a project.** Projects live at `<base>/<category>/<project>`. Discovery skips dependency and build folders (`node_modules`, `dist`, `build`, `.venv`, `target`, …), then looks inside each remaining folder for evidence:

| Evidence | Verdict |
|---|---|
| `.git`, or a manifest (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, …) | looks like a project, suggested `add` |
| Only `README.md`, `docs/`, `src/`, `CLAUDE.md` | might be, suggested `add` |
| Nothing | probably not, suggested `ignore` |

Nothing is written until you confirm. Answer `a` to add, `i` to ignore permanently, `s` to skip, or `q` to stop; Enter accepts the suggestion. `--yes` skips the review and adds only the folders with conclusive evidence.

**Misplaced repos.** A repo sitting at category level (e.g. `~/Projects/my-app/` with a `.git` in it) is in the wrong place: its subfolders are parts of one project, not separate projects. Discovery never descends into it. Instead it offers to move the repo under a category, indexes it as a single project, and repoints any existing index entries at the new location.

**`--review`** applies the same tests to what's already indexed. By default it only raises conclusive problems (dependency folders and subfolders of a project) and reports how many "no project markers" judgement calls it held back; add `-v` to review those too. Projects you created with `pb new` are never flagged. Answer `r` to remove from the index, `i` to remove and ignore, `k` to keep. Files on disk are never deleted. When you remove subfolders of a project that isn't itself indexed, it offers to index the real project.

### `pb ignore`

Remove non-project folders from the index and prevent them from being re-discovered.

```bash
pb ignore 3                         # ignore by ID
pb ignore "shared"                  # ignore by name
pb ignore ~/Projects/Work/shared-docs        # ignore by path
pb ignore --list                    # show all ignored paths
pb ignore --remove docs             # un-ignore (substring match)
```

### `pb adr`

A decision log: a durable record of *why* things are the way they are, one
[MADR](https://adr.github.io/)-format markdown file per decision in `docs/adr/`.

```bash
pb adr init                         # scaffold in the project containing the current directory
pb adr init 3                       # scaffold by ID, name, or slug
pb adr new "Postgres over DynamoDB" # write one record, dated and titled
pb adr new "..." -p 3               # write it in another project
pb adr init 3 --no-skill            # skip the .claude/skills/adr/SKILL.md agent skill
pb new --adr                        # scaffold at project creation time without asking
```

`pb new` offers a decision log alongside its other prompts; `--no-adr` skips the question.

Creates:

```
docs/adr/template.md          MADR template with agent guidance
docs/adr/README.md            how to create records, and the immutability rules
.claude/skills/adr/SKILL.md   Claude Code skill so agents read and write the log
```

`pb adr new` copies the template to `docs/adr/YYYYMMDD-slug.md` with the title and date filled
in and the agent-guidance comment stripped. Writing the file by hand works just as well.

Re-running `init` skips files that already exist, so it's safe on a project that already has a
log. `--force` overwrites them.

#### The website (`--site`)

[log4brains](https://github.com/thomvaill/log4brains) renders the same records as a searchable
static site. It's a Node tool, so it earns its place in a project with a real readership and not
in a three-record log or a project that isn't software. It's opt-in:

```bash
pb adr init --site                  # scaffold with the website
pb adr init --site --force          # add the website to a log that already exists
pb new --adr-site                   # at project creation time
```

That adds `docs/adr/index.md` (the knowledge-base homepage), `.log4brains.yml` (project name,
timezone, adrFolder), and a `/.log4brains` line in `.gitignore` for the build output. If the
project has a `package.json`, the `adr:new` / `adr:preview` / `adr:build` / `adr:serve` scripts
are merged into it using the runner matching its lockfile (pnpm, yarn, or npm); projects without
one get the pinned `npx` invocations directly in the generated docs.

The records are identical in both modes, same format and same filenames, so adding the site later
never renames or rewrites one. Use `--force` when you do, otherwise the README and skill are left
describing a markdown-only log.

### `pb help`

Show help for any command.

```bash
pb help                             # list all commands
pb help new                         # show flags for a specific command
```

### `pb config`

Manage configuration.

```bash
pb config show                      # print config
pb config init                      # create default config
pb config edit                      # open in editor
pb config set editor code           # set a single value
pb config set status_thresholds.stale_after_days 7
```

## Project Status

Status is computed dynamically from `last_worked_at`:
- **active**: worked on within the last 14 days
- **stale**: 14 to 90 days since last activity
- **archived**: 90+ days or manually archived

Thresholds are configurable in `~/.pb/config.json`.

## GitHub owners

```json
"github_orgs": ["your-username", "your-org", "a-client-org"],
"default_github_org": "your-username"
```

`pb new` offers these when creating a repo. Personal accounts and
organisations are interchangeable here: `gh` treats both as an owner. Leave the
list empty and `pb new` asks for an owner by hand.

## Data

- Config: `~/.pb/config.json`
- Index: `~/.pb/index.json`
- Ignored: `~/.pb/ignored.json`
- Projects Index: `PROJECTS_INDEX.md` at the root of each base directory

## Symlinks

Symlinked project folders work transparently. If you symlink a project into your base directory structure (e.g. `ln -s /Volumes/WORK/my-project ~/Projects/Work/my-project`), it will be discovered by `rescan --discover`, and all commands (`open`, `info`, `rescan` mtime scanning) follow symlinks correctly.

## Shell Integration

The `pb` shell function wraps `pb.py` so that `pb open` can `cd` into the project directory. This coexists with any existing `prj` alias.

## Agents

`pb list --json` and `pb info <query> --json` emit the same object shape: the
stored fields plus `status`, which is computed from `last_worked_at` rather than
stored and so is not otherwise available to anything parsing the output.
Filters, sorting and `--limit` apply, so the JSON is exactly what the table
would have shown, and an empty result is `[]`.

```bash
pb list --json --status stale | jq -r '.[] | "\(.name)\t\(.project_root)"'
```

A Claude Code skill ships in `skills/pb/SKILL.md`, which teaches an agent to
turn a project the user names out loud into a path. `install.sh` offers to link
it into `~/.claude/skills/` and defaults to no. To add it later:

```bash
mkdir -p ~/.claude/skills/pb
ln -s "$PWD/skills/pb/SKILL.md" ~/.claude/skills/pb/SKILL.md
```

## Tests

Stdlib `unittest`, nothing to install:

```bash
python3 -m unittest discover        # all tests
python3 -m unittest discover -v     # per-test names
```

Tests never touch the real `~/.pb`: anything that writes to disk uses a temp
directory, and the data-layer tests repoint the module's paths at it.

## Versioning

CalVer, `YYYY.MM.PATCH`. Releases up to 0.8.0 used SemVer. CalVer says nothing
about compatibility, so any change to the on-disk index format is called out in
its changelog entry.

## Where this came from

[`docs/original-brief.md`](docs/original-brief.md) is the brief the tool was
built from, written before any code existed. It is kept as provenance: what was
asked for tends to be more useful than a description written afterwards.

## Licence

MIT. See [LICENSE](LICENSE).
