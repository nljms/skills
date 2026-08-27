# mcp-switch

One provider, several accounts. `mcp-switch` keeps named profiles for an MCP
provider — a work Linear workspace and a personal one, two Notion accounts — and
flips between them with one command, per project.

```
switch.py add linear work --url https://mcp.linear.app/mcp
switch.py add linear personal --url https://mcp.linear.app/mcp
switch.py use linear personal
```

Profiles live in `~/.claude/mcp/<project>/`, keyed on the main repository's
directory name, so every worktree and subdirectory of a repo shares them — and
shares the active one too. `claude mcp add-json -s local` files every
registration under the main repository root whatever directory it runs from, so
a project has exactly one live account per provider.

Each profile owns its own registered server name (`linear-work`,
`linear-personal`), which is what lets both stay authenticated — Claude Code
keys OAuth credentials per server name. A switch removes the previously active
server from local scope, adds the chosen one, then verifies it, printing
`claude mcp login <server>` if authentication is missing.

Two things it will not do: switch a claude.ai account connector (their account
is set in claude.ai settings, not on disk — the skill warns when one shadows
your profile), and touch stored credentials.

After switching, run `/mcp` or restart the session — MCP servers load at session
start.

See [`SKILL.md`](./SKILL.md) for the full command surface.
