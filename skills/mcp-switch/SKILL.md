---
name: mcp-switch
description: Switch an MCP provider between named account profiles — a work Linear workspace and a personal one, two Notion accounts, two Sentry orgs — with one command. Profiles are stored per project and one of them is active per project, so every worktree of a repo shares the same account. Use when the user wants to change which account or workspace an MCP server points at, register a second account for a provider, or see which profile is active here.
---

# mcp-switch

Named profiles per MCP provider, stored and activated per project. Run
everything from the project directory:

```
python3 <skill-dir>/switch.py <command>
```

## Commands

```
switch.py list [provider]                       profiles, active marker, live status
switch.py use <provider> <profile>              activate a profile for this project
switch.py add <provider> <profile> --url <url> [-H "Name: value"] [--transport http|sse] [--server <name>]
switch.py add <provider> <profile> --json '<server json>'
switch.py save <provider> <profile> --from <server> [--server <name>]   capture a configured server
switch.py rm <provider> <profile>               delete a profile from the store
```

`--server` names the server the profile registers as, on both `add` and `save`;
it defaults to `<provider>-<profile>` on `add` and to the captured server's own
name on `save`. `rm` refuses to delete the profile that is currently active —
switch to another one first, or unregister it by hand.

## Where things live

```
~/.claude/mcp/<project>/
  state.json                   active profile per provider, keyed by project
  <provider>/<profile>.json    the server JSON, plus an optional "server" name
```

`<project>` is the main repository's directory name. Both halves are **per
project**: a repo's worktrees and subdirectories share one set of profiles and
one active profile per provider. That is not a choice — `claude mcp add-json -s
local` files every registration under the main repository root, whichever
directory it is run from, so one repo cannot hold two live accounts for the same
provider at once.

## Two things to tell the user every time

1. **A switch needs a reconnect.** MCP servers load at session start. After
   `use`, the user runs `/mcp` (or restarts the session) for it to take effect.
2. **Auth may need one browser round-trip.** Each profile owns its own server
   name, so credentials normally survive a switch. When they do not, `use`
   prints the exact command: `claude mcp login <server>`.

## Setting up a provider with two accounts

```
switch.py add linear work --url https://mcp.linear.app/mcp
switch.py add linear personal --url https://mcp.linear.app/mcp
switch.py use linear work
claude mcp login linear-work        # once, in an interactive terminal
```

Then switching later is one command plus `/mcp`.

## Limits worth stating up front

- **claude.ai connectors cannot be switched.** A connector's account is set in
  claude.ai settings, not on disk. If one is live on the same host as the active
  profile, `use` warns that both sets of tools are visible.
- **One active profile per provider per project**, for the reason above.
- The skill never touches stored credentials — no `logout`, no keychain access.
- Everything is written to **local scope** (`-s local`), never user or project scope.

## Tests

```
./run_tests.sh
```
