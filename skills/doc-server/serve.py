#!/usr/bin/env python3
"""doc-server CLI: serve project docs as HTML on a shared local port."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docserver import app, server, state  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve project docs as HTML.")
    parser.add_argument("--docs", default="docs/**/*.md", help="glob of docs to serve")
    parser.add_argument("--port", type=int, default=None, help="preferred port")
    parser.add_argument("--open", action="store_true", help="open the browser")
    parser.add_argument("--context", default=None,
                        help="path (relative to repo root) of the worktree's lead context doc")
    parser.add_argument("--summary-path", action="store_true",
                        help="print the external worktree-summary.md path for this project/branch, then exit")
    parser.add_argument(
        "--migrate", action="store_true",
        help="migrate an existing doc-server home to the <project>/<branch> layout, then exit",
    )
    parser.add_argument("--daemon", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.migrate:
        from docserver import migrate
        migrate.main()
        return

    if args.daemon:
        if args.port is None:
            parser.error("--daemon requires --port")
        server.run_server_forever(state.doc_server_home(), args.port)
        return

    if args.summary_path:
        print(app.summary_path(os.getcwd()))
        return

    result = app.bring_up(os.getcwd(), args.docs, port=args.port, open_browser=args.open,
                          context=args.context)
    print(result["url"])


if __name__ == "__main__":
    main()
