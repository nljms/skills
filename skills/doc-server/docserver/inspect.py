"""Heuristic, stdlib-only project inspection for doc-server branch pages.

`inspect_project(source_root)` reads a project's *signal files* (dependency
manifests, docker-compose, .env*) plus a shallow directory listing and returns a
structured summary:

    {
      "overview":     {"languages": [...], "project_type": "...", "entry_points": [...]},
      "architecture": ["src/", "src/app.py", ...],   # feeds build_arch_mermaid
      "services":     [{"name": "Postgres", "kind": "database", "via": "..."}],
    }

Every source is wrapped so a malformed/huge/missing file never raises — the
result simply omits what could not be detected. `inspect_cached` adds a
fingerprint cache so the per-request re-sync stays cheap.
"""
import json
import os
import re
from pathlib import Path

_MAX_READ = 64 * 1024  # never read more than this from any single signal file
_MAX_ARCH = 60         # cap architecture-tree entries
_MAX_CHILDREN = 8      # cap shown children per top-level dir

_NOISE_DIRS = {
    ".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv",
    "target", ".next", "coverage", ".mypy_cache", ".pytest_cache", ".idea",
    ".vscode", "vendor", ".tox", ".cache", "out",
}

_MANIFESTS = [
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "go.mod", "Cargo.toml", "Gemfile",
]
_OTHER_SIGNALS = [
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "Dockerfile", ".env", ".env.example", ".env.sample",
]
_SIGNAL_FILES = _MANIFESTS + _OTHER_SIGNALS

_WEB_FRAMEWORKS = {
    "express", "fastify", "koa", "next", "nuxt", "@nestjs/core", "hapi",
    "fastapi", "flask", "django", "starlette", "aiohttp", "sanic", "tornado",
    "gin", "echo", "fiber", "rails", "sinatra", "actix-web", "axum", "rocket",
}

_PY_ENTRY_FILES = [
    "main.py", "app.py", "cli.py", "__main__.py", "serve.py",
    "manage.py", "wsgi.py", "asgi.py", "run.py",
]

# dependency-name -> (Service, kind)
_DEP_SERVICES = {
    "psycopg": ("Postgres", "database"), "psycopg2": ("Postgres", "database"),
    "asyncpg": ("Postgres", "database"), "pg": ("Postgres", "database"),
    "postgres": ("Postgres", "database"), "mysql": ("MySQL", "database"),
    "mysql2": ("MySQL", "database"), "mariadb": ("MariaDB", "database"),
    "mongoose": ("MongoDB", "database"), "mongodb": ("MongoDB", "database"),
    "pymongo": ("MongoDB", "database"), "redis": ("Redis", "cache"),
    "ioredis": ("Redis", "cache"), "stripe": ("Stripe", "payments"),
    "openai": ("OpenAI", "api"), "anthropic": ("Anthropic", "api"),
    "@anthropic-ai": ("Anthropic", "api"), "cohere": ("Cohere", "api"),
    "boto3": ("AWS", "cloud"), "botocore": ("AWS", "cloud"),
    "aws-sdk": ("AWS", "cloud"), "@aws-sdk": ("AWS", "cloud"),
    "google-cloud": ("Google Cloud", "cloud"), "@google-cloud": ("Google Cloud", "cloud"),
    "firebase": ("Firebase", "cloud"), "firebase-admin": ("Firebase", "cloud"),
    "supabase": ("Supabase", "cloud"), "@supabase": ("Supabase", "cloud"),
    "sentry-sdk": ("Sentry", "observability"), "@sentry": ("Sentry", "observability"),
    "twilio": ("Twilio", "api"), "sendgrid": ("SendGrid", "email"),
    "@sendgrid": ("SendGrid", "email"), "nodemailer": ("SMTP/Email", "email"),
    "elasticsearch": ("Elasticsearch", "search"), "@elastic": ("Elasticsearch", "search"),
    "kafkajs": ("Kafka", "messaging"), "kafka-python": ("Kafka", "messaging"),
    "amqplib": ("RabbitMQ", "messaging"), "pika": ("RabbitMQ", "messaging"),
    "celery": ("Celery", "messaging"), "graphql": ("GraphQL", "api"),
}

# env-key substring (uppercased) -> (Service, kind). Ordered: first match wins.
_ENV_SERVICES = [
    ("DATABASE_URL", ("Database", "database")), ("POSTGRES", ("Postgres", "database")),
    ("PGHOST", ("Postgres", "database")), ("MYSQL", ("MySQL", "database")),
    ("MONGO", ("MongoDB", "database")), ("REDIS", ("Redis", "cache")),
    ("STRIPE", ("Stripe", "payments")), ("OPENAI", ("OpenAI", "api")),
    ("ANTHROPIC", ("Anthropic", "api")), ("AWS_", ("AWS", "cloud")),
    ("S3_", ("AWS S3", "cloud")), ("GOOGLE_APPLICATION_CREDENTIALS", ("Google Cloud", "cloud")),
    ("GCP", ("Google Cloud", "cloud")), ("FIREBASE", ("Firebase", "cloud")),
    ("SUPABASE", ("Supabase", "cloud")), ("SENTRY_DSN", ("Sentry", "observability")),
    ("TWILIO", ("Twilio", "api")), ("SENDGRID", ("SendGrid", "email")),
    ("SMTP", ("SMTP/Email", "email")), ("ELASTIC", ("Elasticsearch", "search")),
    ("KAFKA", ("Kafka", "messaging")), ("RABBITMQ", ("RabbitMQ", "messaging")),
    ("AMQP", ("RabbitMQ", "messaging")),
]

# docker-compose image substring -> (Service, kind)
_IMAGE_SERVICES = [
    ("postgres", ("Postgres", "database")), ("mysql", ("MySQL", "database")),
    ("mariadb", ("MariaDB", "database")), ("mongo", ("MongoDB", "database")),
    ("redis", ("Redis", "cache")), ("memcached", ("Memcached", "cache")),
    ("rabbitmq", ("RabbitMQ", "messaging")), ("kafka", ("Kafka", "messaging")),
    ("elasticsearch", ("Elasticsearch", "search")), ("nginx", ("Nginx", "infra")),
    ("minio", ("MinIO", "storage")),
]

_EXT_LANG = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust",
    ".rb": "Ruby", ".java": "Java", ".php": "PHP", ".sh": "Shell",
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _read_capped(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(_MAX_READ)
    except Exception:
        return ""


def _exists(root: str, name: str) -> bool:
    return os.path.isfile(os.path.join(root, name))


def _dep_matches(dep: str, key: str) -> bool:
    if dep == key:
        return True
    for sep in ("-", "/", "_", "."):
        if dep.startswith(key + sep):
            return True
    if key.startswith("@") and dep.startswith(key):
        return True
    return len(key) >= 4 and dep.startswith(key)


# ---------------------------------------------------------------------------
# Manifest parsers (each returns best-effort, never raises)
# ---------------------------------------------------------------------------

def _node_manifest(root: str):
    """(deps:set, entry_points:list, is_cli:bool, has_main:bool)"""
    if not _exists(root, "package.json"):
        return set(), [], False, False
    try:
        data = json.loads(_read_capped(os.path.join(root, "package.json")))
    except Exception:
        return set(), [], False, False
    deps = set()
    for k in ("dependencies", "devDependencies", "peerDependencies"):
        d = data.get(k)
        if isinstance(d, dict):
            deps.update(str(x).lower() for x in d.keys())
    entries, has_main = [], False
    if isinstance(data.get("main"), str):
        entries.append(data["main"]); has_main = True
    binv = data.get("bin")
    is_cli = bool(binv)
    if isinstance(binv, dict):
        entries.extend(v for v in binv.values() if isinstance(v, str))
    elif isinstance(binv, str):
        entries.append(binv)
    return deps, entries, is_cli, has_main


def _scan_pyproject(text: str):
    deps, scripts = set(), []
    for m in re.finditer(r'dependencies\s*=\s*\[(.*?)\]', text, re.S):
        for sm in re.finditer(r'["\']([A-Za-z0-9_.\-]+)', m.group(1)):
            deps.add(sm.group(1).lower())
    for m in re.finditer(r'\[project\.scripts\](.*?)(?:\n\[|\Z)', text, re.S):
        for sm in re.finditer(r'^\s*([A-Za-z0-9_\-]+)\s*=', m.group(1), re.M):
            scripts.append(sm.group(1))
    return deps, scripts


def _python_signals(root: str):
    """(deps:set, entry_points:list, has_console_scripts:bool, packaged:bool)"""
    deps, scripts, packaged = set(), [], False
    req = os.path.join(root, "requirements.txt")
    if os.path.isfile(req):
        for line in _read_capped(req).splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-")):
                continue
            name = re.split(r"[<>=!~\[ ;]", line, 1)[0].strip().lower()
            if name:
                deps.add(name)
    if _exists(root, "pyproject.toml"):
        packaged = True
        d, scripts = _scan_pyproject(_read_capped(os.path.join(root, "pyproject.toml")))
        deps |= d
    if _exists(root, "setup.py") or _exists(root, "setup.cfg"):
        packaged = True
    entries = [f for f in _PY_ENTRY_FILES if _exists(root, f)]
    return deps, scripts + entries, bool(scripts), packaged


def _line_deps(root: str, fname: str, pattern: str):
    if not _exists(root, fname):
        return set()
    out = set()
    for line in _read_capped(os.path.join(root, fname)).splitlines():
        m = re.search(pattern, line.strip())
        if m:
            out.add(m.group(1).lower())
    return out


# ---------------------------------------------------------------------------
# Service detection
# ---------------------------------------------------------------------------

def _dep_services(deps):
    out = []
    for dep in sorted(deps):
        for key, (svc, kind) in _DEP_SERVICES.items():
            if _dep_matches(dep, key):
                out.append((svc, kind, f"dependency: {dep}"))
                break
    return out


def _env_services(root):
    out = []
    for fname in (".env", ".env.example", ".env.sample"):
        if not _exists(root, fname):
            continue
        for line in _read_capped(os.path.join(root, fname)).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            raw_key = line.split("=", 1)[0].strip()
            key = raw_key.upper()
            for pat, (svc, kind) in _ENV_SERVICES:
                if pat in key:
                    out.append((svc, kind, f"{fname}: {raw_key}"))
                    break
    return out


def _compose_services(root):
    out = []
    for fname in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        if not _exists(root, fname):
            continue
        for m in re.finditer(r'image:\s*["\']?([\w.\-/]+)', _read_capped(os.path.join(root, fname))):
            image = m.group(1).lower()
            for sub, (svc, kind) in _IMAGE_SERVICES:
                if sub in image:
                    out.append((svc, kind, f"{fname}: {m.group(1)}"))
                    break
    return out


def _collect_services(root, deps):
    seen = {}
    for svc, kind, via in _dep_services(deps) + _env_services(root) + _compose_services(root):
        seen.setdefault(svc, {"name": svc, "kind": kind, "via": via})
    return sorted(seen.values(), key=lambda s: s["name"].lower())


# ---------------------------------------------------------------------------
# Architecture tree
# ---------------------------------------------------------------------------

def _arch_tree(root):
    rels = []
    try:
        top = sorted(os.listdir(root))
    except OSError:
        return rels
    for name in top:
        if name in _NOISE_DIRS or name.startswith("."):
            continue
        full = os.path.join(root, name)
        if os.path.isdir(full):
            rels.append(name + "/")
            try:
                children = sorted(os.listdir(full))
            except OSError:
                children = []
            shown = 0
            for c in children:
                if c in _NOISE_DIRS or c.startswith("."):
                    continue
                suffix = "/" if os.path.isdir(os.path.join(full, c)) else ""
                rels.append(f"{name}/{c}{suffix}")
                shown += 1
                if shown >= _MAX_CHILDREN:
                    rels.append(f"{name}/…")
                    break
        else:
            rels.append(name)
        if len(rels) >= _MAX_ARCH:
            break
    return rels[:_MAX_ARCH]


# ---------------------------------------------------------------------------
# Languages / project type
# ---------------------------------------------------------------------------

def _languages(root, deps, arch):
    langs = []
    if _exists(root, "package.json"):
        langs.append("TypeScript" if _exists(root, "tsconfig.json") else "JavaScript")
    if any(_exists(root, m) for m in ("pyproject.toml", "setup.py", "requirements.txt", "setup.cfg")):
        langs.append("Python")
    if _exists(root, "go.mod"):
        langs.append("Go")
    if _exists(root, "Cargo.toml"):
        langs.append("Rust")
    if _exists(root, "Gemfile"):
        langs.append("Ruby")
    if not langs:  # fall back to file extensions seen at the top levels
        counts = {}
        for rel in arch:
            ext = os.path.splitext(rel.rstrip("/"))[1]
            if ext in _EXT_LANG:
                counts[_EXT_LANG[ext]] = counts.get(_EXT_LANG[ext], 0) + 1
        langs = [l for l, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:2]
    # de-dup, preserve order
    seen, out = set(), []
    for l in langs:
        if l not in seen:
            seen.add(l); out.append(l)
    return out


def _project_type(deps, node_cli, node_main, py_console, py_packaged, root):
    if deps & _WEB_FRAMEWORKS or any(
        _dep_matches(d, f) for f in _WEB_FRAMEWORKS for d in deps
    ):
        return "Web server"
    if node_cli or py_console or _exists(root, "cli.py") or _exists(root, "__main__.py") \
            or _exists(root, "main.go") or _exists(root, os.path.join("src", "main.rs")):
        return "CLI tool"
    if node_main or py_packaged:
        return "Library"
    return "Application"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _empty():
    return {"overview": {}, "architecture": [], "services": []}


def inspect_project(source_root: str) -> dict:
    if not source_root or not os.path.isdir(source_root):
        return _empty()
    root = source_root

    node_deps, node_entries, node_cli, node_main = _node_manifest(root)
    py_deps, py_entries, py_console, py_packaged = _python_signals(root)
    go_deps = _line_deps(root, "go.mod", r'^(?:require\s+)?([\w./\-]+)\s+v\d')
    rust_deps = _line_deps(root, "Cargo.toml", r'^([A-Za-z0-9_\-]+)\s*=')
    ruby_deps = _line_deps(root, "Gemfile", r'gem\s+["\']([A-Za-z0-9_\-]+)')
    deps = node_deps | py_deps | go_deps | rust_deps | ruby_deps

    arch = _arch_tree(root)
    languages = _languages(root, deps, arch)
    project_type = _project_type(deps, node_cli, node_main, py_console, py_packaged, root)

    entries = []
    for e in node_entries + py_entries:
        if e and e not in entries:
            entries.append(e)
    entries = entries[:4]

    overview = {}
    if languages:
        overview["languages"] = languages
    overview["project_type"] = project_type
    if entries:
        overview["entry_points"] = entries

    return {
        "overview": overview,
        "architecture": arch,
        "services": _collect_services(root, deps),
    }


def _fingerprint(root: str) -> str:
    items = []
    for name in _SIGNAL_FILES:
        try:
            st = os.stat(os.path.join(root, name))
            items.append((name, int(st.st_mtime), st.st_size))
        except OSError:
            pass
    try:
        items.append(("__top__", tuple(sorted(os.listdir(root)))))
    except OSError:
        pass
    return repr(items)


def inspect_cached(source_root: str, dest) -> dict:
    """inspect_project with a fingerprint cache at dest/.inspect.json."""
    if not source_root or not os.path.isdir(source_root):
        return _empty()
    cache = Path(dest) / ".inspect.json"
    fp = _fingerprint(source_root)
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("fingerprint") == fp:
            return cached["data"]
    except Exception:
        pass
    data = inspect_project(source_root)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"fingerprint": fp, "data": data}), encoding="utf-8")
    except Exception:
        pass
    return data
