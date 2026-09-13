---
name: pb
description: Look up the user's local projects with the `pb` CLI, which keeps an index of where each project lives, what it is for, and when it was last worked on. Use when the user names a project without giving a path, asks where something lives, asks what they were working on or what has gone stale, or wants a new project created.
---

# pb

`pb` is a local command-line tool that indexes the user's projects. The index
knows each project's path, category, one-line summary, and when it was last
touched. It is the fastest way to turn a project name the user says out loud
into a directory you can work in.

## When to use it

- The user names a project without a path: "the invoice chaser", "that Shopify thing".
- They ask where something lives, or what they were last working on.
- They ask what has gone stale or what they have abandoned.
- They want a new project created with the usual structure.

## When not to use it

- You are already inside the project being discussed. You have the path.
- The question is about the code, not about which project it is in.
- The user gave you an explicit path.

Do not run `pb` speculatively at the start of a session. It is for answering a
question the user actually asked.

## Check it is installed first

```bash
command -v pb || echo "pb is not installed"
```

If it is missing, say so once and carry on without it. Do not try to install it.

## Reading the index

Always pass `--json`. The human-facing output is a Unicode table meant for eyes,
not for parsing.

```bash
pb list --json                       # every non-archived project
pb list --json --status stale        # only the stale ones
pb list --json --category Work       # one category
pb info "invoice chaser" --json      # one project, by any fragment of its name
```

Each object carries the stored fields plus `status`, which is computed from
`last_worked_at` rather than stored: `active` under two weeks, `stale` up to
three months, `archived` beyond that. `project_root` is the directory to work
in. `repo_url` appears when the project has a git remote.

Queries resolve by ID, ID prefix, name substring, or slug. An ambiguous query
returns nothing and prints the candidates, so pass more of the name.

## Creating a project

`pb new` is interactive by default. When running it unattended, pass every
answer:

```bash
pb new --name "Invoice Chaser" -c Work -s "Chases overdue invoices" \
       --no-notes --no-remote --no-adr
```

`--no-notes` makes it non-interactive. Without `--org`, no GitHub repository is
created; without `--adr`, no decision log is scaffolded. Never create a GitHub
repository on the user's behalf unless they asked for one.

## Recording a decision

If the project has a decision log (`docs/adr/`), record architecturally
significant choices there rather than letting them evaporate:

```bash
pb adr new "Postgres over DynamoDB"
```

That writes `docs/adr/YYYYMMDD-slug.md` from the project's template. Fill in the
context, the options considered, the decision, and its consequences. One
decision per file, and never rewrite an accepted record: supersede it with a new
one and link the two.
