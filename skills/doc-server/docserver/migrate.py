"""Migrate an existing ~/.claude/doc-server/ home from the old
<project>/main + <project>/worktrees/<name> layout to the new
<project>/<branch> layout.

The generated HTML is a disposable cache: it is always reproducible from the
registry + the live source docs. So migration:

  1. Re-keys every registry entry by re-resolving its identity (which now yields
     <project>/<branch>) from the recorded source_root. Entries whose source no
     longer exists on disk are dropped.
  2. Removes every generated project directory (everything under home except
     _assets/ and the *.json state files).
  3. Re-runs a full sync, regenerating the new-layout HTML from scratch.

It is safe to run more than once; an already-migrated home is a no-op beyond a
fresh re-sync.
"""
import os
import shutil
from pathlib import Path

from . import identity, state, sync

_KEEP = {"_assets", "_context"}


def migrate_home(home: Path) -> dict:
    home = Path(home)
    reg = state.read_registry()

    new_reg = {}
    remapped = []
    dropped = []
    for old_key, info in reg.items():
        src = info.get("source_root", "")
        if src and os.path.isdir(src):
            ident = identity.resolve_identity(src)
            new_reg[ident.key] = info
            if ident.key != old_key:
                remapped.append((old_key, ident.key))
        else:
            dropped.append(old_key)

    # Wipe generated project directories; the cache is fully regenerable.
    removed_dirs = []
    if home.is_dir():
        for child in home.iterdir():
            if child.is_dir() and child.name not in _KEEP:
                shutil.rmtree(child)
                removed_dirs.append(child.name)

    state._write_json(state._registry_file(), new_reg)
    sync.ensure_assets(home)
    sync.sync_all(home)

    return {
        "remapped": remapped,
        "dropped": dropped,
        "removed_dirs": removed_dirs,
        "registry": new_reg,
    }


def main(argv=None):
    home = state.doc_server_home()
    result = migrate_home(home)
    print(f"doc-server migrated: {home}")
    for old, new in result["remapped"]:
        print(f"  remapped  {old}  ->  {new}")
    for key in result["dropped"]:
        print(f"  dropped   {key}  (source no longer on disk)")
    if not result["remapped"] and not result["dropped"]:
        print("  registry already in new layout; regenerated HTML.")


if __name__ == "__main__":
    main()
