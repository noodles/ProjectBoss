#!/bin/bash
# The demo session, typed out one character at a time so the recording reads
# like someone using the tool. Driven by record.sh; not meant to be run alone.
set -u

PROMPT=$'\033[32m>\033[0m '

type_out() {
    printf '%s' "$PROMPT"
    local i
    for (( i = 0; i < ${#1}; i++ )); do
        printf '%s' "${1:i:1}"
        sleep 0.035
    done
    printf '\n'
}

run() {
    type_out "$1"
    sleep 0.4
    eval "$1"
    sleep "${2:-3}"
    printf '\n'
}

run "pb list" 4
run "pb info recipe" 4
run "pb new -n 'Client Portal' -c Clients -s 'Self-serve portal' --no-notes --adr" 4
run "pb list" 3
run "pb list --json --status stale | jq '.[] | {name, status, project_root}'" 5
