"""Build the zips to upload to the hosting server: python make_upload.py

dist/surveillance-app.zip    the code; upload it every time the app changes
dist/surveillance-data.zip   the workbooks (data/) and the local app's accounts (legacy-accounts/); upload it once,
                             at the first install: uploading it again would replace the server's newer data
dist/.env                    the server's settings with a new secret key; upload it once, at the first install

Left out of both: this computer's database, secret key, .env, logs, gathered static files and caches.
"""
import json
import os
import secrets
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
DIST = BASE / "dist"
LEGACY = Path(os.environ.get("APPDATA") or Path.home()) / "AFP Watch Out"
LEAVE_OUT_ACCOUNTS = {"baba"}  # local accounts not to bring to the server

SKIP_DIRS = {".git", ".vscode", "__pycache__"}
# Only at the top: the apps' own data folders (core/data, idsr/data) are code and must go up.
SKIP_TOP_DIRS = {"staticfiles", "dist", "data", "private_media", "reference", "tmp", "legacy-accounts"}
SKIP_FILES = {"db.sqlite3", ".secret_key", ".env", "django-errors.log", "Start app.cmd", "make_upload.py"}


def code_files():
    for root, dirs, files in os.walk(BASE):
        top = Path(root) == BASE
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (top and d in SKIP_TOP_DIRS))
        for name in sorted(files):
            if name not in SKIP_FILES and not name.endswith(".pyc"):
                p = Path(root) / name
                yield p, p.relative_to(BASE)


def data_files():
    for p in sorted((BASE / "data").rglob("*")):
        if p.is_file() and not p.name.endswith(".bak.xlsx") and p.name != ".write.lock":
            yield p, p.relative_to(BASE)
    try:
        users = json.loads((LEGACY / "users.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        users = {}
    users = {name: rec for name, rec in users.items() if name not in LEAVE_OUT_ACCOUNTS}
    if not users:
        return
    yield json.dumps(users, indent=2).encode("utf-8"), Path("legacy-accounts/users.json")
    for p in sorted((LEGACY / "photos").glob("*")):
        if p.is_file() and p.stem in users:
            yield p, Path("legacy-accounts/photos") / p.name


def build(name, files):
    DIST.mkdir(exist_ok=True)
    out = DIST / name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        n = 0
        for src, arc in files:
            if isinstance(src, bytes):
                z.writestr(arc.as_posix(), src)
            elif src.suffix == ".sh":  # bash on the server stops at Windows line endings
                z.writestr(arc.as_posix(), src.read_bytes().replace(b"\r\n", b"\n"))
            else:
                z.write(src, arc.as_posix())
            n += 1
    print(f"{out}  ({n} files, {out.stat().st_size // 1024} KB)")


def write_env():
    """dist/.env for a first install: .env.example with a new secret key. Upload it once; later builds make a new
    one, which an update must not upload (signed-in users would be signed out)."""
    text = (BASE / ".env.example").read_text(encoding="utf-8")
    text = text.replace("paste-a-long-random-string-here", secrets.token_urlsafe(50))
    (DIST / ".env").write_text(text, encoding="utf-8", newline="\n")
    print(f"{DIST / '.env'}  (new secret key)")


if __name__ == "__main__":
    build("surveillance-app.zip", code_files())
    build("surveillance-data.zip", data_files())
    write_env()
