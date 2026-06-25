import os

from . import identity, server, state, sync


def _env_port():
    val = os.environ.get("DOC_SERVER_PORT")
    return int(val) if val and val.isdigit() else None


def bring_up(cwd: str, glob: str, port=None, open_browser: bool = False) -> dict:
    home = state.doc_server_home()
    ident = identity.resolve_identity(cwd)
    state.register_target(ident.key, ident.source_root, glob)
    sync.ensure_assets(home)

    preferred = port or _env_port() or state.get_remembered_port() or 8910
    chosen, started = server.ensure_server(home, preferred)
    sync.sync_all(home)

    url = f"http://localhost:{chosen}/{ident.key}/"
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    return {"url": url, "port": chosen, "key": ident.key, "started": started}
