#!/usr/bin/env python3
"""mcp-switch CLI: flip an MCP provider between named account profiles."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcpswitch import cli, commands, identity  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(
        description="Switch an MCP provider between named account profiles.")
    subs = parser.add_subparsers(dest="command", required=True)

    show = subs.add_parser("list", help="show profiles and which one is active here")
    show.add_argument("provider", nargs="?", default=None)

    use = subs.add_parser("use", help="activate a profile for this project")
    use.add_argument("provider")
    use.add_argument("profile")

    add = subs.add_parser("add", help="define a profile")
    add.add_argument("provider")
    add.add_argument("profile")
    add.add_argument("--url", default=None, help="server URL (http/sse)")
    add.add_argument("--transport", default="http", choices=["http", "sse"])
    add.add_argument("-H", "--header", action="append", default=[],
                     help='header, e.g. -H "X-Api-Key: abc"')
    add.add_argument("--json", dest="json_config", default=None,
                     help="raw server JSON, for stdio or anything unusual")
    add.add_argument("--server", default=None,
                     help="registered server name (default <provider>-<profile>)")

    save = subs.add_parser("save", help="capture an already-configured server")
    save.add_argument("provider")
    save.add_argument("profile")
    save.add_argument("--from", dest="from_server", required=True)
    save.add_argument("--server", default=None)

    remove = subs.add_parser("rm", help="delete a profile from the store")
    remove.add_argument("provider")
    remove.add_argument("profile")

    return parser


def main(argv=None, claude=None) -> int:
    args = _parser().parse_args(argv)
    cwd = os.getcwd()
    # Claude Code keys local-scope MCP config on the main repository root, so
    # that is what activation is keyed on too — resolved once, handed down.
    project = identity.project_root(cwd)
    root = identity.project_store(cwd)
    claude = claude or cli.Claude()

    if args.command == "list":
        result = commands.show(root, cwd, project, claude, provider=args.provider)
    elif args.command == "use":
        result = commands.use(root, cwd, project, args.provider, args.profile, claude)
    elif args.command == "add":
        result = commands.add(root, args.provider, args.profile, url=args.url,
                              transport=args.transport, headers=args.header,
                              json_config=args.json_config, server=args.server)
    elif args.command == "save":
        result = commands.save(root, cwd, args.provider, args.profile,
                               args.from_server, claude, server=args.server)
    else:
        result = commands.rm(root, project, args.provider, args.profile)

    for line in result.lines:
        print(line)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
