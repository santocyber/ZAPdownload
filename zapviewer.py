#!/usr/bin/env python3
"""WhatsApp Export Viewer — monobloco Python.
Zero dependencias externas. Banco, auth, upload chunked, import TXT/ZIP, servidor HTTP.
"""

import http.server
import json
import sqlite3
import os
import sys
import hashlib
import hmac
import secrets
import re
import html
import mimetypes
import shutil
import urllib.parse
import zipfile
import io
import socketserver
import time
import math
from datetime import datetime, timezone
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
STORAGE_ROOT = BASE_DIR / "python_storage"
DB_PATH = STORAGE_ROOT / "database.sqlite"
UPLOAD_DIR = STORAGE_ROOT / "uploads"
CHUNK_DIR = STORAGE_ROOT / "chunks"
MEDIA_DIR = STORAGE_ROOT / "media"
EXTRACT_DIR = STORAGE_ROOT / "extracts"

MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_CHUNKS = 100000
CHUNK_SIZE = 2 * 1024 * 1024  # 2 MB
SESSION_EXPIRE_DAYS = 30
PBKDF2_ITERATIONS = 260000
SECRET_KEY = None  # Set at startup

# Port via env or default
PORT = int(os.environ.get("PORT", "8001"))
HOST = os.environ.get("HOST", "0.0.0.0")

# ── Storage bootstrap ────────────────────────────────────────────────────────

for d in [STORAGE_ROOT, UPLOAD_DIR, CHUNK_DIR, MEDIA_DIR, EXTRACT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Database helpers ─────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn

def migrate():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
            last_login_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            csrf_token TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            source_file TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, imported_at);

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender TEXT,
            body TEXT NOT NULL,
            sender_search TEXT,
            body_search TEXT,
            sent_at TEXT,
            media_path TEXT,
            raw_line INTEGER,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id);
        CREATE INDEX IF NOT EXISTS idx_msg_sent ON messages(sent_at);
    """)
    conn.close()

# ── Password helpers ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${h.hex()}"

def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    iterations = int(parts[1])
    salt = parts[2]
    expected = parts[3]
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return hmac.compare_digest(h.hex(), expected)

# ── Session helpers ──────────────────────────────────────────────────────────

def make_session(user_id: int) -> tuple[str, str]:
    """Create a new session, return (session_id, cookie_value)."""
    sid = secrets.token_hex(32)
    csrf = secrets.token_hex(32)
    expires = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_str = expires.strftime("%Y-%m-%d %H:%M:%S")
    
    sig = hmac.new(SECRET_KEY.encode(), sid.encode(), "sha256").hexdigest()
    cookie_val = f"{sid}|{sig}"
    
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (id, user_id, csrf_token, expires_at) VALUES (?, ?, ?, datetime('now', '+{} days'))".format(SESSION_EXPIRE_DAYS),
        (sid, user_id, csrf)
    )
    conn.commit()
    conn.close()
    return sid, cookie_val

def get_session(cookie_val: str | None) -> dict | None:
    if not cookie_val or "|" not in cookie_val:
        return None
    sid, sig = cookie_val.split("|", 1)
    expected = hmac.new(SECRET_KEY.encode(), sid.encode(), "sha256").hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ? AND expires_at > datetime('now')",
        (sid,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_session(cookie_val: str | None):
    if not cookie_val or "|" not in cookie_val:
        return
    sid = cookie_val.split("|", 1)[0]
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    conn.commit()
    conn.close()

# ── Helpers ──────────────────────────────────────────────────────────────────

def clean_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    name = name.strip(" ._")
    return name if name else "upload"

def clean_identifier(ident: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_-]", "", ident)
    return ident[:160]

def normalize_search_text(text: str | None) -> str:
    if not text:
        return ""
    t = text.lower().strip()
    # Transliterate accents using simple mapping
    accent_map = {
        "á": "a", "à": "a", "â": "a", "ã": "a", "ä": "a",
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "í": "i", "ì": "i", "î": "i", "ï": "i",
        "ó": "o", "ò": "o", "ô": "o", "õ": "o", "ö": "o",
        "ú": "u", "ù": "u", "û": "u", "ü": "u",
        "ç": "c", "ñ": "n",
    }
    for acc, asc in accent_map.items():
        t = t.replace(acc, asc)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def build_set_cookie_header(cookie_val: str) -> str:
    return (
        f"zapviewer_session={cookie_val}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_EXPIRE_DAYS * 86400}"
    )

def delete_cookie_header() -> str:
    return "zapviewer_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

def allowed_extension(filename: str) -> bool:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return ext in ("txt", "zip")

def like_pattern(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

def search_terms(query: str) -> list[str]:
    norm = normalize_search_text(query)
    if not norm:
        return []
    terms = [t for t in norm.split() if len(t) >= 2]
    return list(dict.fromkeys(terms))

# ── WhatsApp Importer ────────────────────────────────────────────────────────

MEDIA_EXTS = {
    "jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "m4v", "3gp",
    "mp3", "m4a", "opus", "ogg", "wav", "pdf", "doc", "docx", "xls",
    "xlsx", "ppt", "pptx", "vcf", "csv", "txt"
}

DATE_PATTERNS = [
    re.compile(r"^\[(?P<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}),?\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ampm>[AP]\.?M\.?)?\]\s*(?P<body>.*)$", re.I),
    re.compile(r"^(?P<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}),?\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ampm>[AP]\.?M\.?)?\s+-\s*(?P<body>.*)$", re.I),
]

def parse_message_line(line: str) -> dict | None:
    for pat in DATE_PATTERNS:
        m = pat.match(line)
        if not m:
            continue
        dt = m.group("date")
        tm = m.group("time")
        ap = m.group("ampm")
        body_raw = m.group("body")
        
        sent_at = normalize_date_time(dt, tm, ap)
        if sent_at is None:
            return None
        
        sender, body = split_sender_body(body_raw)
        return {"sender": sender, "body": body, "sent_at": sent_at}
    return None

def split_sender_body(raw: str) -> tuple[str | None, str]:
    idx = raw.find(": ")
    if idx == -1:
        return None, raw.strip()
    sender = raw[:idx].strip()
    body = raw[idx + 2:].strip()
    return (sender if sender else None, body)

def normalize_date_time(date_str: str, time_str: str, ampm: str | None) -> str | None:
    parts = re.split(r"[/.\-]", date_str)
    if len(parts) != 3:
        return None
    try:
        first, second, year = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    
    if year < 100:
        year += 1900 if year >= 70 else 2000
    
    if second > 12 and first <= 12:
        month, day = first, second
    else:
        day, month = first, second
    
    try:
        import calendar
        if not (1 <= month <= 12 and 1 <= day <= 31):
            day, month = month, day
    except ValueError:
        pass
    
    time_parts_list = time_str.split(":")
    try:
        hour, minute = int(time_parts_list[0]), int(time_parts_list[1])
        sec = int(time_parts_list[2]) if len(time_parts_list) > 2 else 0
    except (ValueError, IndexError):
        return None
    
    if ampm:
        ap = ampm.replace(".", "").strip().upper()
        if ap == "PM" and hour < 12:
            hour += 12
        if ap == "AM" and hour == 12:
            hour = 0
    
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= sec <= 59):
        return None
    
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{sec:02d}"

class WhatsAppImporter:
    def __init__(self, uploaded_filename: str, user_id: int):
        self.uploaded_filename = clean_filename(uploaded_filename)
        self.user_id = user_id
    
    def import_file(self) -> dict:
        upload_path = UPLOAD_DIR / self.uploaded_filename
        if not upload_path.is_file():
            raise RuntimeError("Arquivo enviado nao foi encontrado.")
        
        ext = self.uploaded_filename.lower().rsplit(".", 1)[-1]
        import_key = self._make_import_key()
        
        if ext == "zip":
            prepared = self._prepare_zip(str(upload_path), import_key)
            txt_path = prepared["txt_path"]
            media_map = prepared["media_map"]
        else:
            txt_path = str(upload_path)
            media_map = {}
        
        title = self._make_title(txt_path)
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO conversations (user_id, title, source_file, imported_at) VALUES (?, ?, ?, ?)",
                (self.user_id, title, self.uploaded_filename, now_utc_str())
            )
            conv_id = cur.lastrowid
            count = self._import_text(txt_path, conv_id, media_map, conn)
            conn.execute(
                "UPDATE conversations SET message_count = ? WHERE id = ?",
                (count, conv_id)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        
        return {"conversation_id": conv_id, "title": title, "messages": count}
    
    def _import_text(self, txt_path: str, conv_id: int, media_map: dict, conn) -> int:
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        pending = None
        count = 0
        line_num = 0
        
        for raw_line in lines:
            line_num += 1
            line = raw_line.rstrip("\r\n")
            if line_num == 1:
                line = line.lstrip("\ufeff")
            
            msg = parse_message_line(line)
            if msg is not None:
                if pending is not None:
                    self._insert_message(conn, conv_id, pending, media_map)
                    count += 1
                msg["raw_line"] = line_num
                pending = msg
            elif pending is not None:
                pending["body"] += "\n" + line
        
        if pending is not None:
            self._insert_message(conn, conv_id, pending, media_map)
            count += 1
        
        return count
    
    def _insert_message(self, conn, conv_id: int, msg: dict, media_map: dict):
        media_path = self._find_media(msg["body"], media_map)
        sender_search = normalize_search_text(msg.get("sender"))
        body_search = normalize_search_text(msg["body"])
        conn.execute(
            """INSERT INTO messages
               (conversation_id, sender, body, sender_search, body_search, sent_at, media_path, raw_line)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (conv_id, msg.get("sender"), msg["body"], sender_search, body_search,
             msg["sent_at"], media_path, msg.get("raw_line"))
        )
    
    def _find_media(self, body: str, media_map: dict) -> str | None:
        if not media_map:
            return None
        pat = re.compile(
            r"([A-Za-z0-9._() @-]+?\.(?:jpe?g|png|gif|webp|mp4|mov|m4v|3gp|mp3|m4a|opus|ogg|wav|pdf|docx?|xlsx?|pptx?|vcf|csv))",
            re.I
        )
        for m in pat.finditer(body):
            key = m.group(1).strip().lower()
            base = key.split("/")[-1]
            if base in media_map:
                return media_map[base]
        return None
    
    def _prepare_zip(self, zip_path: str, import_key: str) -> dict:
        extract_dir = EXTRACT_DIR / import_key
        media_dir = MEDIA_DIR / import_key
        extract_dir.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)
        
        txt_files = []
        media_map = {}
        
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                entry = info.filename.replace("\\", "/")
                if not self._is_safe(entry):
                    raise RuntimeError(f"ZIP contem caminho inseguro: {entry}")
                
                ext = entry.lower().rsplit(".", 1)[-1] if "." in entry else ""
                if ext not in MEDIA_EXTS:
                    continue
                
                base_name = entry.rsplit("/", 1)[-1]
                is_txt = ext == "txt"
                target_dir = extract_dir if is_txt else media_dir
                target_name = self._unique_name(target_dir, base_name)
                
                zf.extract(info, str(extract_dir.parent))  # extract to extract_dir parent, then move
                src = extract_dir.parent / entry
                dst = target_dir / target_name
                if src != dst:
                    shutil.move(str(src), str(dst))
                    # Clean up any empty dirs
                    self._cleanup_dir(src.parent)
                
                if is_txt:
                    txt_files.append({"path": str(dst), "size": info.file_size})
                else:
                    media_map[base_name.lower()] = f"{import_key}/{target_name}"
        
        if not txt_files:
            raise RuntimeError("Nenhum arquivo .txt encontrado dentro do ZIP.")
        
        txt_files.sort(key=lambda x: -x["size"])
        return {"txt_path": txt_files[0]["path"], "media_map": media_map}
    
    def _is_safe(self, entry: str) -> bool:
        if "\0" in entry or entry.startswith("/"):
            return False
        if re.match(r"^[A-Za-z]:", entry):
            return False
        for part in entry.split("/"):
            if part == "..":
                return False
        return True
    
    def _unique_name(self, directory: Path, filename: str) -> str:
        name = clean_filename(filename)
        stem, ext = os.path.splitext(name)
        candidate = name
        i = 1
        while (directory / candidate).exists():
            candidate = f"{stem}_{i}{ext}"
            i += 1
        return candidate
    
    def _make_import_key(self) -> str:
        base = self.uploaded_filename.lower().rsplit(".", 1)[0]
        base = re.sub(r"[^a-z0-9_-]", "_", base) or "import"
        base = base.strip("_-")[:80]
        return f"{base}_{secrets.token_hex(4)}"
    
    def _make_title(self, txt_path: str) -> str:
        base = os.path.splitext(os.path.basename(txt_path))[0]
        base = re.sub(r"^Conversa do WhatsApp com\s+", "", base, flags=re.I)
        base = re.sub(r"^WhatsApp Chat(?: with)?\s+", "", base, flags=re.I)
        base = base.replace("_", " ").replace("-", " ")
        base = re.sub(r"\s+", " ", base).strip()
        return base if base else "Conversa importada"
    
    def _cleanup_dir(self, path: Path):
        try:
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            pass


# ── Request Handler ──────────────────────────────────────────────────────────

class ZapHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[zapviewer] {args[0]} {args[1]} {args[2]}\n")
    
    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._end_headers()
        self.wfile.write(body)
    
    def _fail(self, msg: str, status: int = 400):
        self._send_json({"success": False, "error": msg}, status)
    
    def _success(self, data: dict):
        data["success"] = True
        self._send_json(data)
    
    def _render_html(self, html_str: str, status: int = 200):
        body = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._end_headers()
        self.wfile.write(body)
    
    def _end_headers(self):
        # Suppress default Date/Server headers by using send_header
        self.end_headers()
    
    def _get_cookie(self) -> str | None:
        c = self.headers.get("Cookie", "")
        for part in c.split(";"):
            part = part.strip()
            if part.startswith("zapviewer_session="):
                return part[len("zapviewer_session="):]
        return None
    
    def _require_login(self) -> dict | None:
        session = get_session(self._get_cookie())
        if not session:
            self._fail("Login necessario.", 401)
            return None
        conn = get_db()
        user = conn.execute(
            "SELECT id, username, role FROM users WHERE id = ? AND active = 1",
            (session["user_id"],)
        ).fetchone()
        conn.close()
        if not user:
            self._fail("Login necessario.", 401)
            return None
        return dict(user)
    
    def _require_admin(self) -> dict | None:
        user = self._require_login()
        if not user:
            return None
        if user["role"] != "admin":
            self._send_json({"success": False, "error": "Acesso negado."}, 403)
            return None
        return user
    
    def _read_body(self, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length > max_bytes:
            return b""
        return self.rfile.read(length)
    
    def _read_json(self) -> dict:
        body = self._read_body(1024 * 1024)  # 1 MB max for JSON
        if not body:
            return {}
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    
    def _parse_qs(self, body: bytes) -> dict:
        try:
            return dict(urllib.parse.parse_qsl(body.decode("utf-8", "replace")))
        except Exception:
            return {}
    
    def _redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self._end_headers()
    
    def _get_query(self) -> dict:
        parsed = urllib.parse.urlparse(self.path)
        return dict(urllib.parse.parse_qsl(parsed.query))
    
    def _path_no_query(self) -> str:
        return urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
    
    # ── Routes ───────────────────────────────────────────────────────────────
    
    def do_GET(self):
        path = self._path_no_query()
        q = self._get_query()
        
        if path in ("/", "/index.php"):
            session = get_session(self._get_cookie())
            if not session:
                self._redirect("/login")
                return
            user = self._require_login()
            if user:
                self._page_index(user)
            return
        if path in ("/login", "/login.php"):
            if get_session(self._get_cookie()):
                self._redirect("/")
                return
            self._page_login()
            return
        if path == "/logout":
            delete_session(self._get_cookie())
            self._redirect("/login")
            return
        if path in ("/admin-users", "/admin-users.php"):
            session = get_session(self._get_cookie())
            if not session:
                self._redirect("/login")
                return
            user = self._require_admin()
            if user:
                self._page_admin(user)
            return
        if path == "/api/conversations":
            self._api_conversations()
            return
        if path == "/api/messages":
            self._api_messages(q)
            return
        if path == "/api/search":
            self._api_search(q)
            return
        if path == "/upload-chunk":
            self._chunk_check(q)
            return
        if path == "/media":
            self._serve_media(q)
            return
        if path == "/health":
            self._send_json({"status": "ok"})
            return
        
        self._send_json({"error": "Nao encontrado"}, 404)
    
    def do_POST(self):
        path = self._path_no_query()
        
        if path in ("/login", "/login.php"):
            self._post_login()
            return
        if path in ("/admin-users", "/admin-users.php"):
            user = self._require_admin()
            if user:
                self._post_admin(user)
            return
        if path == "/upload-chunk":
            self._chunk_upload()
            return
        if path == "/import":
            self._post_import()
            return
        if path == "/api/delete-conversation":
            self._api_delete()
            return
        
        self._send_json({"error": "Nao encontrado"}, 404)
    
    # ── Login page ───────────────────────────────────────────────────────────
    
    def _page_login(self):
        session = get_session(self._get_cookie())
        if session:
            self._redirect("/")
            return
        
        conn = get_db()
        has_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
        conn.close()
        
        is_setup = not has_users
        
        error_msg = ""
        if self._get_query().get("error"):
            error_msg = html.escape(self._get_query()["error"])
        
        html_out = PAGE_LOGIN
        html_out = html_out.replace("__HAS_USERS__", str(has_users).lower())
        html_out = html_out.replace("__LOGIN_TITLE__", "Criar primeiro admin" if is_setup else "Entrar")
        html_out = html_out.replace("__SUBTITLE__",
            "Nenhum usuario existe ainda. Crie o administrador inicial." if is_setup
            else "Acesse suas conversas importadas.")
        html_out = html_out.replace("__ACTION__", "setup" if is_setup else "login")
        html_out = html_out.replace("__AUTOCOMPLETE__", "new-password" if is_setup else "current-password")
        html_out = html_out.replace("__SUBMIT__", "Criar admin" if is_setup else "Entrar")
        html_out = html_out.replace("__CONFIRM_STYLE__", "flex" if is_setup else "none")
        html_out = html_out.replace("__ERROR_MSG__", f'<div class="auth-error" id="errorMsg">{error_msg}</div>' if error_msg else '<div class="auth-error" id="errorMsg" style="display:none"></div>')
        self._render_html(html_out)
    
    def _post_login(self):
        content_type = self.headers.get("Content-Type", "")
        if "application/x-www-form-urlencoded" in content_type:
            body = self._read_body(65536)
            data = self._parse_qs(body)
        else:
            data = self._read_json()
        
        username = data.get("username", "").strip().lower()
        password = data.get("password", "")
        action = data.get("action", "login")
        
        conn = get_db()
        has_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
        
        try:
            if action == "setup" and not has_users:
                confirm = data.get("password_confirm", "")
                if password != confirm:
                    raise RuntimeError("As senhas nao conferem.")
                uid = self._create_user(username, password, "admin", 1, conn)
                _, cookie_val = make_session(uid)
                conn.close()
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", build_set_cookie_header(cookie_val))
                self._end_headers()
                return
            
            if action == "login":
                user = conn.execute(
                    "SELECT id, password_hash, active FROM users WHERE username = ?",
                    (username,)
                ).fetchone()
                if user and user["active"] and verify_password(password, user["password_hash"]):
                    _, cookie_val = make_session(user["id"])
                    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
                               (now_utc_str(), user["id"]))
                    conn.commit()
                    conn.close()
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Set-Cookie", build_set_cookie_header(cookie_val))
                    self._end_headers()
                    return
                
                raise RuntimeError("Usuario ou senha invalidos.")
            
            raise RuntimeError("Acao invalida.")
        except RuntimeError as e:
            conn.close()
            self._redirect(f"/login?error={urllib.parse.quote(str(e))}")
    
    def _create_user(self, username: str, password: str, role: str, active: int, conn) -> int:
        username = re.sub(r"[^a-z0-9._-]", "", username)[:60]
        if not username:
            raise RuntimeError("Informe um usuario valido.")
        if len(password) < 6:
            raise RuntimeError("A senha precisa ter pelo menos 6 caracteres.")
        
        ph = hash_password(password)
        role = "admin" if role == "admin" else "user"
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role, active, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, ph, role, active, now_utc_str())
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise RuntimeError("Este usuario ja existe.")
    
    # ── Index page ───────────────────────────────────────────────────────────
    
    def _page_index(self, user: dict):
        conn = get_db()
        csrf = conn.execute(
            "SELECT csrf_token FROM sessions WHERE user_id = ? AND expires_at > datetime('now')",
            (user["id"],)
        ).fetchone()
        conn.close()
        
        csrf_token = csrf["csrf_token"] if csrf else ""
        is_admin = user["role"] == "admin"
        admin_link = '<a class="mini-link" href="/admin-users">Admin</a>' if is_admin else ""
        
        html_out = PAGE_INDEX.replace("{USERNAME}", html.escape(user.get("username", "")))
        html_out = html_out.replace("{ADMIN_LINK}", admin_link)
        html_out = html_out.replace("{CSRF_TOKEN}", html.escape(csrf_token))
        self._render_html(html_out)
    
    # ── Admin page ───────────────────────────────────────────────────────────
    
    def _page_admin(self, user: dict):
        conn = get_db()
        csrf = conn.execute(
            "SELECT csrf_token FROM sessions WHERE user_id = ? AND expires_at > datetime('now')",
            (user["id"],)
        ).fetchone()
        csrf_token = csrf["csrf_token"] if csrf else ""
        
        rows = conn.execute("""
            SELECT u.id, u.username, u.role, u.active, u.created_at, u.last_login_at,
                   COUNT(c.id) AS conversation_count
            FROM users u
            LEFT JOIN conversations c ON c.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at ASC, u.id ASC
        """).fetchall()
        conn.close()
        
        user_rows_html = ""
        for row in rows:
            active_checked = "checked" if row["active"] else ""
            role_user_sel = "selected" if row["role"] == "user" else ""
            role_admin_sel = "selected" if row["role"] == "admin" else ""
            user_rows_html += f"""
            <form method="post" class="user-row">
                <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                <input type="hidden" name="action" value="update">
                <input type="hidden" name="user_id" value="{row['id']}">
                <div class="user-info">
                    <strong>{html.escape(row['username'])}</strong>
                    <small>{row['conversation_count']} conversas</small>
                </div>
                <select name="role">
                    <option value="user" {role_user_sel}>Usuario</option>
                    <option value="admin" {role_admin_sel}>Admin</option>
                </select>
                <label class="check-label compact">
                    <input name="active" type="checkbox" {active_checked}>
                    <span>Ativo</span>
                </label>
                <input name="password" type="password" placeholder="nova senha opcional">
                <button class="button small" type="submit">Salvar</button>
            </form>"""
        
        html_out = PAGE_ADMIN.replace("{CSRF_TOKEN}", html.escape(csrf_token))
        html_out = html_out.replace("{USER_ROWS}", user_rows_html)
        self._render_html(html_out)
    
    def _post_admin(self, user: dict):
        content_type = self.headers.get("Content-Type", "")
        if "application/x-www-form-urlencoded" in content_type:
            body = self._read_body(65536)
            data = self._parse_qs(body)
        else:
            data = self._read_json()
        
        csrf = data.get("csrf_token", "")
        session = get_session(self._get_cookie())
        if not session or csrf != session.get("csrf_token", ""):
            self._redirect("/admin-users")
            return
        
        action = data.get("action", "")
        conn = get_db()
        
        try:
            if action == "create":
                self._create_user(
                    data.get("username", ""),
                    data.get("password", ""),
                    data.get("role", "user"),
                    1 if data.get("active") else 0,
                    conn
                )
            elif action == "update":
                uid = int(data.get("user_id", "0"))
                role = data.get("role", "user")
                active = 1 if data.get("active") else 0
                password = data.get("password", "")
                
                if uid == user["id"] and (role != "admin" or active != 1):
                    raise RuntimeError("Voce nao pode remover seu proprio acesso admin.")
                
                if password:
                    if len(password) < 6:
                        raise RuntimeError("A senha precisa ter pelo menos 6 caracteres.")
                    ph = hash_password(password)
                    conn.execute(
                        "UPDATE users SET role = ?, active = ?, password_hash = ? WHERE id = ?",
                        (role, active, ph, uid)
                    )
                else:
                    conn.execute(
                        "UPDATE users SET role = ?, active = ? WHERE id = ?",
                        (role, active, uid)
                    )
                conn.commit()
        except RuntimeError as e:
            pass
        finally:
            conn.close()
        
        self._redirect("/admin-users")
    
    # ── API: conversations ───────────────────────────────────────────────────
    
    def _api_conversations(self):
        user = self._require_login()
        if not user:
            return
        conn = get_db()
        rows = conn.execute("""
            SELECT c.id, c.title, c.source_file, c.message_count, c.imported_at,
                   lm.body AS last_message, lm.sent_at AS last_date
            FROM conversations c
            LEFT JOIN messages lm ON lm.id = (
                SELECT id FROM messages
                WHERE conversation_id = c.id
                ORDER BY COALESCE(sent_at, '') DESC, id DESC
                LIMIT 1
            )
            WHERE c.user_id = ?
            ORDER BY c.imported_at DESC, c.id DESC
        """, (user["id"],)).fetchall()
        conn.close()
        
        self._success({"conversations": [dict(r) for r in rows]})
    
    # ── API: messages ────────────────────────────────────────────────────────
    
    def _api_messages(self, q: dict):
        user = self._require_login()
        if not user:
            return
        conv_id = max(0, int(q.get("conversation_id", "0")))
        limit = min(2000, max(1, int(q.get("limit", "500"))))
        offset = max(0, int(q.get("offset", "0")))
        
        if conv_id < 1:
            self._fail("Conversa invalida.", 400)
            return
        
        conn = get_db()
        rows = conn.execute("""
            SELECT m.id, m.conversation_id, m.sender, m.body, m.sent_at, m.media_path, m.raw_line
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.conversation_id = ? AND c.user_id = ?
            ORDER BY m.id ASC
            LIMIT ? OFFSET ?
        """, (conv_id, user["id"], limit, offset)).fetchall()
        conn.close()
        
        msgs = []
        for r in rows:
            d = dict(r)
            d["media_url"] = f"/media?file={urllib.parse.quote(d['media_path'])}" if d.get("media_path") else None
            msgs.append(d)
        
        self._success({"messages": msgs})
    
    # ── API: search ──────────────────────────────────────────────────────────
    
    def _api_search(self, q: dict):
        user = self._require_login()
        if not user:
            return
        
        query = q.get("q", "").strip()
        conv_id = max(0, int(q.get("conversation_id", "0")))
        limit = min(200, max(1, int(q.get("limit", "80"))))
        date_start = q.get("date_start", "")
        date_end = q.get("date_end", "")
        sort_dir = "ASC" if q.get("sort", "").lower() == "asc" else "DESC"
        
        norm = normalize_search_text(query)
        terms = search_terms(query)
        
        where_parts = ["c.user_id = ?"]
        params = [user["id"]]
        
        if conv_id > 0:
            where_parts.append("m.conversation_id = ?")
            params.append(conv_id)
        
        if date_start:
            where_parts.append("m.sent_at >= ?")
            params.append(date_start)
        if date_end:
            where_parts.append("m.sent_at <= ?")
            params.append(date_end + " 23:59:59")
        
        search_clauses = []
        if norm:
            search_clauses.append("(COALESCE(m.body_search, '') LIKE ? ESCAPE '\\' OR COALESCE(m.sender_search, '') LIKE ? ESCAPE '\\')")
            params.append(like_pattern(norm))
            params.append(like_pattern(norm))
        if query:
            search_clauses.append("(m.body LIKE ? ESCAPE '\\' OR COALESCE(m.sender, '') LIKE ? ESCAPE '\\')")
            params.append(like_pattern(query))
            params.append(like_pattern(query))
        for i, term in enumerate(terms):
            search_clauses.append(f"(COALESCE(m.body_search, '') LIKE ? ESCAPE '\\' OR COALESCE(m.sender_search, '') LIKE ? ESCAPE '\\')")
            p = like_pattern(term)
            params.append(p)
            params.append(p)
        
        if search_clauses:
            where_parts.append("(" + " OR ".join(search_clauses) + ")")
        
        where_sql = " AND ".join(where_parts)
        order = f"ORDER BY COALESCE(m.sent_at, '') {sort_dir}, m.id {sort_dir}"
        
        conn = get_db()
        sql = f"""
            SELECT m.id, m.conversation_id, m.sender, m.body, m.sent_at, m.media_path, m.raw_line,
                   c.title AS conversation_title
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE {where_sql}
            {order}
            LIMIT ?
        """
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        
        msgs = []
        for r in rows:
            d = dict(r)
            d["media_url"] = f"/media?file={urllib.parse.quote(d['media_path'])}" if d.get("media_path") else None
            msgs.append(d)
        
        self._success({"messages": msgs})
    
    # ── API: delete conversation ─────────────────────────────────────────────
    
    def _api_delete(self):
        user = self._require_login()
        if not user:
            return
        data = self._read_json()
        conv_id = max(0, int(data.get("conversation_id", "0")))
        if conv_id < 1:
            self._fail("Conversa invalida.", 400)
            return
        
        conn = get_db()
        conv = conn.execute(
            "SELECT id, source_file FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user["id"])
        ).fetchone()
        if not conv:
            conn.close()
            self._fail("Conversa nao encontrada.", 404)
            return
        
        # Get media paths before delete
        media_rows = conn.execute("""
            SELECT DISTINCT media_path FROM messages
            WHERE conversation_id = ? AND media_path IS NOT NULL AND media_path != ''
        """, (conv_id,)).fetchall()
        
        conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"]))
        conn.commit()
        conn.close()
        
        # Remove source file
        src = UPLOAD_DIR / conv["source_file"]
        if src.is_file():
            src.unlink()
        
        # Remove media files
        for mr in media_rows:
            p = MEDIA_DIR / mr["media_path"]
            if p.is_file():
                p.unlink()
        
        self._success({"deleted_id": conv_id})
    
    # ── Chunk upload ─────────────────────────────────────────────────────────
    
    def _chunk_params(self, q: dict = None) -> dict | None:
        if q is None:
            parsed = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(parsed.query))
        
        ident = clean_identifier(q.get("identifier", ""))
        filename = clean_filename(q.get("filename", ""))
        try:
            chunk_num = int(q.get("chunkNumber", "0"))
            total_chunks = int(q.get("totalChunks", "0"))
            total_size = int(q.get("totalSize", "0"))
        except (ValueError, KeyError):
            return None
        
        if not ident or not filename or chunk_num < 1 or total_chunks < 1 or chunk_num > total_chunks:
            return None
        if total_chunks > MAX_CHUNKS or total_size < 1 or total_size > MAX_UPLOAD_BYTES:
            return None
        if not allowed_extension(filename):
            return None
        
        return {
            "identifier": ident,
            "filename": filename,
            "chunkNumber": chunk_num,
            "totalChunks": total_chunks,
            "totalSize": total_size,
        }
    
    def _chunk_check(self, q: dict):
        user = self._require_login()
        if not user:
            return
        params = self._chunk_params(q)
        if not params:
            self._fail("Parametros de upload invalidos.", 400)
            return
        
        chunk_dir = CHUNK_DIR / f"u{user['id']}_{params['identifier']}"
        chunk_path = chunk_dir / f"chunk_{params['chunkNumber']}"
        final_path = UPLOAD_DIR / f"u{user['id']}_{params['identifier']}_{params['filename']}"
        
        if chunk_path.is_file() or final_path.is_file():
            self.send_response(200)
            self._end_headers()
        else:
            self.send_response(204)
            self._end_headers()
    
    def _chunk_upload(self):
        user = self._require_login()
        if not user:
            return
        params = self._chunk_params()
        if not params:
            self._fail("Parametros de upload invalidos.", 400)
            return
        
        final_filename = f"u{user['id']}_{params['identifier']}_{params['filename']}"
        final_path = UPLOAD_DIR / final_filename
        chunk_dir = CHUNK_DIR / f"u{user['id']}_{params['identifier']}"
        chunk_path = chunk_dir / f"chunk_{params['chunkNumber']}"
        
        if final_path.is_file():
            self._success({"complete": True, "file": final_filename})
            return
        
        body = self._read_body(CHUNK_SIZE + 65536)  # allow some overhead
        if not body:
            self._fail("Chunk nao recebido.", 400)
            return
        
        chunk_dir.mkdir(parents=True, exist_ok=True)
        with open(chunk_path, "wb") as f:
            f.write(body)
        
        # Check if all chunks received
        for i in range(1, params["totalChunks"] + 1):
            if not (chunk_dir / f"chunk_{i}").is_file():
                self._success({"complete": False, "chunk": params["chunkNumber"]})
                return
        
        # Assemble
        lock_path = chunk_dir / "assemble.lock"
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            self._success({"complete": True, "file": final_filename})
            return
        
        try:
            if not final_path.is_file():
                tmp = final_path.with_suffix(".part")
                with open(tmp, "wb") as out:
                    for i in range(1, params["totalChunks"] + 1):
                        cp = chunk_dir / f"chunk_{i}"
                        with open(cp, "rb") as inp:
                            shutil.copyfileobj(inp, out)
                tmp.rename(final_path)
            
            # Clean up chunks
            for i in range(1, params["totalChunks"] + 1):
                cp = chunk_dir / f"chunk_{i}"
                if cp.is_file():
                    cp.unlink()
            os.close(lock_fd)
            os.unlink(str(lock_path))
        except Exception as e:
            os.close(lock_fd)
            try:
                os.unlink(str(lock_path))
            except OSError:
                pass
            self._fail(str(e), 500)
            return
        
        self._success({"complete": True, "file": final_filename})
    
    # ── Import ───────────────────────────────────────────────────────────────
    
    def _post_import(self):
        user = self._require_login()
        if not user:
            return
        data = self._read_json()
        filename = clean_filename(data.get("file", ""))
        if not filename:
            self._fail("Arquivo nao informado.", 400)
            return
        
        prefix = f"u{user['id']}_"
        if not filename.startswith(prefix):
            filename = prefix + filename
        
        try:
            importer = WhatsAppImporter(filename, user["id"])
            result = importer.import_file()
            self._success({"conversation": result})
        except RuntimeError as e:
            self._fail(str(e), 500)
    
    # ── Serve media ──────────────────────────────────────────────────────────
    
    def _serve_media(self, q: dict):
        user = self._require_login()
        if not user:
            return
        file_param = q.get("file", "")
        file_param = file_param.replace("\\", "/")
        
        if not file_param or "\0" in file_param or file_param.startswith("/") or ".." in file_param:
            self.send_response(400)
            self._end_headers()
            return
        
        media_path = (MEDIA_DIR / file_param).resolve()
        media_root = MEDIA_DIR.resolve()
        
        if not str(media_path).startswith(str(media_root)) or not media_path.is_file():
            self.send_response(404)
            self._end_headers()
            return
        
        # Verify ownership
        conn = get_db()
        row = conn.execute("""
            SELECT 1 FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.user_id = ? AND m.media_path = ?
            LIMIT 1
        """, (user["id"], file_param)).fetchone()
        conn.close()
        
        if not row:
            self.send_response(403)
            self._end_headers()
            return
        
        mime_type, _ = mimetypes.guess_type(str(media_path))
        if not mime_type:
            mime_type = "application/octet-stream"
        
        file_size = media_path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Content-Disposition", f'inline; filename="{media_path.name}"')
        self._end_headers()
        
        with open(media_path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)


# ── HTML, CSS, JS ────────────────────────────────────────────────────────────

PAGE_LOGIN = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Login - WhatsApp Export Viewer</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:#f5f5f5;color:#222;display:flex;min-height:100vh;align-items:center;justify-content:center}
.auth-card{background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:100%;max-width:420px;margin:20px}
.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#888;margin-bottom:4px}
h1{font-size:24px;margin-bottom:8px}
.auth-copy{color:#666;margin-bottom:24px;line-height:1.5}
.auth-error{background:#fef2f2;color:#b91c1c;padding:10px 14px;border-radius:8px;margin-bottom:16px;font-size:14px}
.auth-form{display:flex;flex-direction:column;gap:16px}
label{display:flex;flex-direction:column;gap:4px;font-size:14px;font-weight:500}
input{padding:10px 14px;border:1px solid #d1d5db;border-radius:8px;font-size:15px;outline:none;transition:border-color .15s}
input:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.15)}
.button{display:inline-flex;align-items:center;justify-content:center;padding:10px 20px;border:none;border-radius:8px;font-size:15px;font-weight:500;cursor:pointer;transition:background .15s;background:#2563eb;color:#fff;text-decoration:none}
.button:hover{background:#1d4ed8}
</style>
</head>
<body>
<main class="auth-card">
<p class="eyebrow">Backup local</p>
<h1>__LOGIN_TITLE__</h1>
<p class="auth-copy">__SUBTITLE__</p>"""
PAGE_LOGIN += """__ERROR_MSG__
<form method="post" class="auth-form" autocomplete="on" id="loginForm">
<input type="hidden" name="action" value="__ACTION__">
<label>
<span>Usuario</span>
<input name="username" type="text" required autofocus autocomplete="username" placeholder="admin">
</label>
<label>
<span>Senha</span>
<input name="password" type="password" required autocomplete="__AUTOCOMPLETE__" placeholder="minimo 6 caracteres">
</label>
"""
PAGE_LOGIN += """<label id="confirmLabel" style="display:__CONFIRM_STYLE__">
<span>Confirmar senha</span>
<input name="password_confirm" type="password" autocomplete="new-password">
</label>
<button class="button" type="submit">__SUBMIT__</button>
</form>
</main>
<script>
const hasUsers = __HAS_USERS__;
const actionInput = document.querySelector('[name=action]');
const confirmLabel = document.getElementById('confirmLabel');
const passwordInput = document.querySelector('[name=password]');
const confirmInput = document.querySelector('[name=password_confirm]');
if(!hasUsers){ confirmLabel.style.display='flex'; actionInput.value='setup'; }
document.getElementById('loginForm').addEventListener('submit',function(e){
const err=document.getElementById('errorMsg');
const pwd=passwordInput.value.trim();
if(pwd.length<6){ e.preventDefault(); err.textContent='A senha precisa ter pelo menos 6 caracteres.'; err.style.display='block'; return; }
if(!hasUsers && confirmInput.value!==pwd){ e.preventDefault(); err.textContent='As senhas nao conferem.'; err.style.display='block'; return; }
});
const params=new URLSearchParams(location.search);
if(params.get('error')){ document.getElementById('errorMsg').textContent=params.get('error'); document.getElementById('errorMsg').style.display='block'; }
</script>
</body>
</html>"""

# ── Index page ────────────────────────────────────────────────────────────────

PAGE_INDEX = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WhatsApp Export Viewer</title>
<style>
:root{--sidebar-w:380px;--radius:12px;--border:#e5e7eb;--bg:#f9fafb;--accent:#2563eb;--accent-hover:#1d4ed8}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:#fff;color:#222;display:flex;height:100vh;overflow:hidden}
.app-shell{display:flex;width:100%;height:100%}
.sidebar{width:var(--sidebar-w);min-width:var(--sidebar-w);background:var(--bg);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.brand{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:flex-start}
.brand .eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#888}
.brand h1{font-size:18px;font-weight:700}
.user-actions{display:flex;align-items:center;gap:10px;font-size:13px}
.current-user{color:#666}
.mini-link{color:var(--accent);text-decoration:none;font-size:13px}
.mini-link:hover{text-decoration:underline}
.danger-link{color:#dc2626}
.icon-button{width:28px;height:28px;border:1px solid var(--border);border-radius:6px;background:#fff;cursor:pointer;font-size:13px;font-weight:600;display:flex;align-items:center;justify-content:center;transition:background .15s}
.icon-button:hover{background:#f3f4f6}
.upload-card{margin:12px 16px;padding:14px;background:#fff;border:2px dashed var(--border);border-radius:var(--radius);cursor:pointer;transition:border-color .2s}
.upload-card.dragover{border-color:var(--accent);background:#eff6ff}
.upload-copy{display:flex;flex-direction:column;gap:2px;margin-bottom:10px}
.upload-copy strong{font-size:14px}
.upload-copy span{font-size:12px;color:#888}
.upload-actions{display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.button{display:inline-flex;align-items:center;justify-content:center;padding:7px 14px;border:none;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer;transition:background .15s;background:var(--accent);color:#fff;text-decoration:none;white-space:nowrap}
.button:hover{background:var(--accent-hover)}
.button.secondary{background:#fff;color:#374151;border:1px solid var(--border)}
.button.secondary:hover{background:#f3f4f6}
.button.ghost{background:transparent;color:#888;border:1px solid transparent}
.button.ghost:hover{background:#f3f4f6;color:#222}
.button.small{padding:5px 10px;font-size:12px}
.button:disabled{opacity:.5;cursor:default}
.progress-wrap{display:flex;align-items:center;gap:8px;font-size:12px;color:#666}
progress{flex:1;height:6px;border-radius:3px;overflow:hidden}
progress::-webkit-progress-bar{background:#e5e7eb;border-radius:3px}
progress::-webkit-progress-value{background:var(--accent);border-radius:3px}
.search-box{padding:8px 16px 4px;display:flex;flex-direction:column;gap:4px}
.search-box span{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#888}
.search-box input{padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;outline:none;transition:border-color .15s}
.search-box input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(37,99,235,.12)}
.date-filter{padding:4px 16px 8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.date-filter label{display:flex;flex-direction:column;gap:2px;flex:1;min-width:0}
.date-filter label span{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#888}
.date-filter input{padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;outline:none}
.date-filter input:focus{border-color:var(--accent)}
.conversation-list{flex:1;overflow-y:auto;padding:4px 12px 12px}
.muted-card{padding:20px;text-align:center;color:#888;font-size:13px}
.conversation-row{display:flex;align-items:center;gap:0;border-radius:8px;margin-bottom:2px}
.conversation-row.active{background:#e0e7ff}
.conversation-item{flex:1;display:flex;align-items:center;gap:10px;padding:10px 12px;border:none;background:transparent;cursor:pointer;text-align:left;border-radius:8px;transition:background .1s;overflow:hidden}
.conversation-item:hover{background:#e5e7eb}
.conversation-row.active .conversation-item:hover{background:#d0d7f0}
.avatar{width:36px;height:36px;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:14px;flex-shrink:0}
.conversation-text{flex:1;min-width:0}
.conversation-text strong{display:block;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.conversation-text small{display:block;font-size:11px;color:#888;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.conversation-meta{display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex-shrink:0}
.conversation-meta time{font-size:10px;color:#888}
.conversation-meta b{font-size:11px;color:#666}
.delete-conversation{width:28px;height:28px;border:none;background:transparent;color:#ccc;cursor:pointer;border-radius:6px;font-size:13px;font-weight:600;flex-shrink:0;transition:color .15s,background .15s;display:flex;align-items:center;justify-content:center}
.delete-conversation:hover{color:#dc2626;background:#fee2e2}
.chat-panel{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.chat-header{padding:16px 24px;border-bottom:1px solid var(--border)}
.chat-title-block .eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#888}
.chat-title-block h2{font-size:20px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chat-tools{display:flex;gap:10px;margin-top:10px;flex-wrap:wrap;align-items:center}
.chat-search{display:flex;flex-direction:column;gap:2px;flex:1;min-width:160px}
.chat-search span{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#888}
.chat-search input{padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;outline:none}
.chat-search input:focus{border-color:var(--accent)}
.chat-date-filter{display:flex;gap:8px;align-items:center}
.chat-date-filter label{display:flex;flex-direction:column;gap:2px}
.chat-date-filter label span{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#888}
.chat-date-filter input{padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;outline:none}
.message-count{font-size:12px;color:#888;white-space:nowrap}
.messages{flex:1;overflow-y:auto;padding:18px clamp(12px,3vw,42px) 24px;background:#efeae2;background-image:linear-gradient(rgba(239,234,226,.88),rgba(239,234,226,.88)),radial-gradient(circle at 20% 20%,rgba(37,99,235,.08),transparent 24%),radial-gradient(circle at 80% 10%,rgba(18,140,126,.10),transparent 26%)}
.messages.empty-state{display:flex;align-items:center;justify-content:center}
.messages.empty-state div{text-align:center;color:#888}
.messages.empty-state h3{font-size:16px;margin-bottom:4px}
.messages.empty-state p{font-size:13px}
.date-chip,.conversation-chip{width:max-content;max-width:75%;margin:10px auto;padding:6px 12px;border-radius:8px;background:rgba(255,255,255,.82);box-shadow:0 1px 1px rgba(0,0,0,.08);color:#667781;font-size:12px;font-weight:600;text-align:center}
.conversation-chip{margin-top:16px;color:#2563eb}
.message-row{display:flex;flex-direction:column;align-items:flex-start;margin:2px 0}
.message-row.group-start{margin-top:9px}
.message-row.mine{align-items:flex-end}
.msg-bubble{max-width:min(680px,76%);position:relative;background:#fff;border-radius:8px 8px 8px 2px;padding:7px 10px 5px;box-shadow:0 1px 1px rgba(0,0,0,.10);font-size:14px;line-height:1.38;color:#111b21;word-break:break-word;overflow-wrap:anywhere}
.message-row.mine .msg-bubble{background:#d9fdd3;border-radius:8px 8px 2px 8px}
.msg-sender{display:block;margin-bottom:3px;color:#2563eb;font-size:12px;font-weight:700;line-height:1.2}
.msg-body{display:block;white-space:pre-wrap;padding-right:48px}
.msg-body img,.msg-body video{max-width:100%;max-height:360px;border-radius:7px;display:block;margin:5px 0}
.msg-body audio{display:block;width:260px;max-width:100%;margin:5px 0}
.msg-body a{color:#2563eb;font-weight:600;text-decoration:none}
.msg-time{float:right;margin:5px 0 0 10px;color:#667781;font-size:11px;line-height:1;white-space:nowrap}
.system-msg{width:max-content;max-width:min(78%,620px);margin:10px auto;padding:6px 12px;border-radius:8px;background:rgba(255,255,255,.82);box-shadow:0 1px 1px rgba(0,0,0,.08);color:#667781;font-size:12px;line-height:1.35;text-align:center;clear:both}
.system-time{display:block;margin-top:3px;color:#87939a;font-size:10px}
.empty-chat{text-align:center;color:#888;padding:40px 20px;font-size:14px}
.search-highlight{background:#fde68a;border-radius:2px;padding:0 1px}
</style>
</head>
<body>
<div class="app-shell">
<aside class="sidebar">
<header class="brand">
<div>
<p class="eyebrow">Backup local</p>
<h1>Conversas</h1>
</div>
<div class="user-actions">
<span class="current-user">{USERNAME}</span>
{ADMIN_LINK}
<a class="mini-link danger-link" href="/logout">Sair</a>
<button id="refreshButton" class="icon-button" type="button" title="Atualizar">R</button>
</div>
</header>
<section id="dropArea" class="upload-card">
<div class="upload-copy">
<strong>Importar exportacao</strong>
<span>Arraste um .txt ou .zip grande aqui.</span>
</div>
<div class="upload-actions">
<span id="browseButton" class="button secondary" role="button" tabindex="0">Escolher</span>
<button id="startUpload" class="button" type="button" disabled>Enviar</button>
<button id="pauseUpload" class="button ghost" type="button" disabled>Pausar</button>
</div>
<div class="progress-wrap">
<progress id="progressBar" value="0" max="100"></progress>
<span id="progressText">Nenhum arquivo selecionado.</span>
</div>
</section>
<label class="search-box">
<span>Buscar geral</span>
<input id="globalSearchInput" type="search" placeholder="palavra, pessoa ou trecho">
</label>
<div class="date-filter">
<label><span>De</span><input id="globalDateStart" type="date"></label>
<label><span>Ate</span><input id="globalDateEnd" type="date"></label>
<button id="clearGlobalSearch" class="button ghost small" type="button">Limpar</button>
</div>
<nav id="conversationList" class="conversation-list" aria-label="Conversas importadas"></nav>
</aside>
<main class="chat-panel">
<header class="chat-header">
<div class="chat-title-block">
<p id="chatSubtitle" class="eyebrow">Selecione uma conversa</p>
<h2 id="chatTitle">WhatsApp Export Viewer</h2>
</div>
<div class="chat-tools">
<label class="chat-search">
<span>Buscar neste chat</span>
<input id="chatSearchInput" type="search" placeholder="mensagem neste chat" disabled>
</label>
<div class="chat-date-filter">
<label><span>De</span><input id="chatDateStart" type="date" disabled></label>
<label><span>Ate</span><input id="chatDateEnd" type="date" disabled></label>
</div>
<button id="clearChatSearch" class="button ghost small" type="button" disabled>Limpar</button>
<span id="messageCount" class="message-count"></span>
</div>
</header>
<section id="messages" class="messages empty-state">
<div>
<h3>Importe uma exportacao do WhatsApp</h3>
<p>Use .txt para conversas simples ou .zip para incluir midias exportadas.</p>
</div>
</section>
</main>
</div>
<script>
// ── State ──────────────────────────────────────────────────────────────────
const STATE={conversations:[],activeId:null,selectedFile:null,fileId:null,
timers:{global:null,chat:null},requests:{conv:0,msgs:0,gSearch:0,cSearch:0},
uploading:false,paused:false,chunksSent:[],chunkTotal:0,chunkIdent:null,
chunkFilename:null,chunkSize:0};
const EL=Object.fromEntries([
'dropArea','browseButton','startUpload','pauseUpload','progressBar','progressText',
'refreshButton','globalSearchInput','globalDateStart','globalDateEnd','clearGlobalSearch',
'chatSearchInput','chatDateStart','chatDateEnd','clearChatSearch',
'conversationList','messages','chatTitle','chatSubtitle','messageCount'
].map(id=>[id,document.getElementById(id)]));

// ── Helpers ─────────────────────────────────────────────────────────────────
function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}
function fmtDate(v){if(!v)return '';const d=new Date(v.replace(' ','T'));return isNaN(d.getTime())?v:d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'})}
function normSender(v){return String(v??'').normalize('NFD').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim()}
function isOwnSender(sender){const n=normSender(sender);const current=normSender(document.querySelector('.current-user')?.textContent||'');return !!n&&(['voce','you','me','eu','santocyber'].includes(n)||n===current)}
function cmpMsg(a,b){return String(a.sent_at||'').localeCompare(String(b.sent_at||''))||Number(a.raw_line||0)-Number(b.raw_line||0)||Number(a.id||0)-Number(b.id||0)}
function dateKey(v){return String(v||'').slice(0,10)}
function sameDay(a,b){return a.getFullYear()===b.getFullYear()&&a.getMonth()===b.getMonth()&&a.getDate()===b.getDate()}
function fmtDay(v){const key=dateKey(v);if(!key)return '';const d=new Date(key+'T00:00:00');if(isNaN(d.getTime()))return key;const today=new Date();const yesterday=new Date(today);yesterday.setDate(today.getDate()-1);if(sameDay(d,today))return 'HOJE';if(sameDay(d,yesterday))return 'ONTEM';return d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric'})}
function fmtTime(v){if(!v)return '';const d=new Date(String(v).replace(' ','T'));if(isNaN(d.getTime())){const m=String(v).match(/([0-9]{1,2}:[0-9]{2})/);return m?m[1]:String(v)}return d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}
function shortT(v,l=80){return String(v??'').replace(/\\s+/g,' ').trim().slice(0,l)+(String(v??'').length>l?'...':'')}
function setPct(p,t){EL.progressBar.value=p;EL.progressText.textContent=t}
function showErr(m){EL.progressText.textContent=m;setTimeout(()=>{},3500)}
async function fetchJ(u,o={}){const r=await fetch(u,o);let d;try{d=await r.json()}catch(e){throw new Error('Resposta invalida.')}if(!r.ok||!d.success)throw new Error(d.error||'Falha.');return d}
function debounce(t,f){return function(...a){clearTimeout(t);t=setTimeout(()=>f.apply(this,a),300)}}

// ── Upload ──────────────────────────────────────────────────────────────────
const CHUNK_SZ=2*1024*1024;
function uid(){return Math.random().toString(36).slice(2)+Date.now().toString(36)}

function initUploader(){
EL.browseButton.addEventListener('click',()=>{const inp=document.createElement('input');inp.type='file';inp.accept='.txt,.zip';inp.onchange=()=>{if(inp.files[0])onFile(inp.files[0])};inp.click()});
EL.dropArea.addEventListener('dragover',e=>{e.preventDefault();EL.dropArea.classList.add('dragover')});
['dragleave','drop'].forEach(ev=>EL.dropArea.addEventListener(ev,()=>EL.dropArea.classList.remove('dragover')));
EL.dropArea.addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer.files[0])onFile(e.dataTransfer.files[0])});
EL.startUpload.addEventListener('click',startChunkUpload);
EL.pauseUpload.addEventListener('click',()=>{STATE.paused=!STATE.paused;EL.pauseUpload.textContent=STATE.paused?'Continuar':'Pausar'})
}

function onFile(f){
STATE.selectedFile=f;
STATE.fileId=uid();
EL.startUpload.disabled=false;
EL.pauseUpload.disabled=true;
setPct(0,'Selecionado: '+f.name)
}

async function startChunkUpload(){
if(!STATE.selectedFile)return;
const f=STATE.selectedFile;
STATE.uploading=true;STATE.paused=false;STATE.chunksSent=[];
EL.startUpload.disabled=true;EL.pauseUpload.disabled=false;EL.pauseUpload.textContent='Pausar';
const total=Math.ceil(f.size/CHUNK_SZ);
STATE.chunkTotal=total;STATE.chunkIdent=STATE.fileId;
STATE.chunkFilename=f.name;STATE.chunkSize=f.size;
for(let i=1;i<=total;i++){
while(STATE.paused){await new Promise(r=>setTimeout(r,200))}
if(!STATE.uploading)return;
const ok=await sendChunk(f,i,total);
if(!ok){showErr('Erro no chunk '+i);break}
STATE.chunksSent.push(i);
setPct(Math.floor(i/total*100),'Enviando '+f.name+': '+Math.floor(i/total*100)+'%')
}
if(STATE.chunksSent.length===total){
setPct(100,'Upload concluido. Importando...');
await doImport()
}
STATE.uploading=false;STATE.paused=false;
EL.startUpload.disabled=true;EL.pauseUpload.disabled=true
}

async function sendChunk(f,chunk,total){
const start=(chunk-1)*CHUNK_SZ;
const end=Math.min(start+CHUNK_SZ,f.size);
const blob=f.slice(start,end);
const params=new URLSearchParams({
identifier:STATE.chunkIdent,chunkNumber:chunk,totalChunks:total,
filename:f.name,totalSize:f.size
});
try{
const check=await fetch('/upload-chunk?'+params,{method:'GET'});
if(check.status===200)return true;
const resp=await fetch('/upload-chunk?'+params,{method:'POST',body:blob});
if(!resp.ok)return false;
const d=await resp.json();
return d.success
}catch(e){return false}
}

async function doImport(){
try{
const d=await fetchJ('/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:STATE.chunkIdent+'_'+STATE.chunkFilename})});
const conv=d.conversation;
setPct(100,'Importado: '+conv.messages+' mensagens.');
STATE.selectedFile=null;STATE.chunksSent=[];
EL.startUpload.disabled=true;EL.pauseUpload.disabled=true;
await loadConversations();
if(conv.conversation_id)await openConversation(conv.conversation_id)
}catch(e){showErr(e.message)}
}

// ── Conversations ───────────────────────────────────────────────────────────
async function loadConversations(){
const id=++STATE.requests.conv;
try{
const d=await fetchJ('/api/conversations');
if(id!==STATE.requests.conv)return;
STATE.conversations=d.conversations;
if(STATE.activeId&&!d.conversations.some(c=>Number(c.id)===STATE.activeId))setWelcome();
renderConversations()
}catch(e){showErr(e.message||'Erro ao carregar conversas.')}
}

function renderConversations(){
if(!STATE.conversations.length){EL.conversationList.innerHTML='<div class="muted-card">Nenhuma conversa importada ainda.</div>';return}
EL.conversationList.innerHTML=STATE.conversations.map(c=>{
const act=Number(c.id)===STATE.activeId;
return '<div class="conversation-row'+(act?' active':'')+'">'+
'<button class="conversation-item" data-id="'+c.id+'" type="button">'+
'<span class="avatar">'+esc((c.title||'?')[0].toUpperCase())+'</span>'+
'<span class="conversation-text"><strong>'+esc(c.title)+'</strong>'+
'<small>'+esc(shortT(c.last_message||'Sem mensagens'))+'</small></span>'+
'<span class="conversation-meta"><time>'+esc(fmtDate(c.last_date))+'</time>'+
'<b>'+c.message_count+'</b></span></button>'+
'<button class="delete-conv" data-id="'+c.id+'" type="button" title="Apagar">X</button></div>'
}).join('');
EL.conversationList.querySelectorAll('.conversation-item').forEach(b=>{
b.addEventListener('click',()=>openConversation(Number(b.dataset.id)))
});
EL.conversationList.querySelectorAll('.delete-conv').forEach(b=>{
b.addEventListener('click',async e=>{
e.stopPropagation();
if(!confirm('Apagar esta conversa e todas as mensagens?'))return;
try{await fetchJ('/api/delete-conversation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:Number(b.dataset.id)})});
await loadConversations();setWelcome()}catch(e){showErr(e.message)}
})
})
}

function setWelcome(){
STATE.activeId=null;
EL.chatTitle.textContent='WhatsApp Export Viewer';
EL.chatSubtitle.textContent='Selecione uma conversa';
EL.messageCount.textContent='';
EL.messages.className='messages empty-state';
EL.messages.innerHTML='<div><h3>Importe uma exportacao do WhatsApp</h3><p>Use .txt para conversas simples ou .zip para incluir midias exportadas.</p></div>';
setChatEnabled(false);renderConversations()
}

function setChatEnabled(en){
EL.chatSearchInput.disabled=!en;
EL.chatDateStart.disabled=!en;
EL.chatDateEnd.disabled=!en;
EL.clearChatSearch.disabled=!en
}

// ── Messages ────────────────────────────────────────────────────────────────
async function openConversation(id){
STATE.activeId=Number(id);
STATE.requests.gSearch++;
clearGlobalFilters(false);clearChatFilters(false);
setChatEnabled(true);renderConversations();
const conv=STATE.conversations.find(c=>Number(c.id)===id);
EL.chatTitle.textContent=conv?.title||'Conversa';
EL.chatSubtitle.textContent='Mensagens importadas';
EL.messageCount.textContent=conv?conv.message_count+' mensagens':'';
await loadMessages(id)
}

async function loadMessages(convId){
const id=++STATE.requests.msgs;
try{
const d=await fetchJ('/api/messages?conversation_id='+convId+'&limit=2000');
if(id!==STATE.requests.msgs||STATE.activeId!==convId)return;
renderMessages(d.messages)
}catch(e){showErr(e.message)}
}

function renderMessages(msgs){
EL.messages.classList.remove('empty-state');
if(!msgs.length){EL.messages.innerHTML='<div class="empty-chat">Nenhuma mensagem encontrada.</div>';return}
const ordered=[...msgs].sort(cmpMsg);
let html='';let lastSender=null;let lastDay=null;
ordered.forEach(m=>{
const day=dateKey(m.sent_at);
if(day&&day!==lastDay){html+='<div class="date-chip">'+esc(fmtDay(m.sent_at))+'</div>';lastDay=day;lastSender=null}
const sender=m.sender||null;
if(sender===null){
const time=fmtTime(m.sent_at);
html+='<div class="system-msg">'+renderBody(m)+(time?'<span class="system-time">'+esc(time)+'</span>':'')+'</div>';
lastSender=null;return}
const mine=isOwnSender(sender);
const groupStart=sender!==lastSender;
html+='<article class="message-row '+(mine?'mine ':'')+(groupStart?'group-start':'group-follow')+'" data-message-id="'+esc(m.id||'')+'"><div class="msg-bubble">';
if(groupStart&&!mine)html+='<strong class="msg-sender">'+esc(sender)+'</strong>';
html+='<div class="msg-body">'+renderBody(m)+'</div><time class="msg-time">'+esc(fmtTime(m.sent_at))+'</time></div></article>';
lastSender=sender
});
EL.messages.innerHTML=html;
EL.messages.scrollTop=EL.messages.scrollHeight
}

function renderBody(m){
let body=esc(m.body||'').replace(/\\n/g,'<br>');
if(m.media_url){
const ext=(m.media_path||'').toLowerCase();
if(ext.match(/\\.(jpe?g|png|gif|webp)$/))body+='<br><img src="'+esc(m.media_url)+'" loading="lazy">';
else if(ext.match(/\\.(mp4|mov|m4v|3gp)$/))body+='<br><video controls src="'+esc(m.media_url)+'"></video>';
else if(ext.match(/\\.(mp3|m4a|opus|ogg|wav)$/))body+='<br><audio controls src="'+esc(m.media_url)+'"></audio>';
else body+='<br><a href="'+esc(m.media_url)+'" target="_blank">Abrir midia</a>'
}
const sq=STATE.searchQuery;
if(sq&&body.toLowerCase().includes(sq.toLowerCase())){
const re=new RegExp('('+sq.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&')+')','gi');
body=body.replace(re,'<span class="search-highlight">$1</span>');
}
return body
}

// ── Search ──────────────────────────────────────────────────────────────────
let STATE_searchQuery='';
Object.defineProperty(STATE,'searchQuery',{get(){return STATE_searchQuery},set(v){STATE_searchQuery=v}});

async function doGlobalSearch(){
const q=EL.globalSearchInput.value.trim();
const ds=EL.globalDateStart.value;
const de=EL.globalDateEnd.value;
const id=++STATE.requests.gSearch;
if(!q&&!ds&&!de){await loadConversations();setWelcome();return}
try{
let url='/api/search?limit=200&q='+encodeURIComponent(q);
if(ds)url+='&date_start='+ds;
if(de)url+='&date_end='+de;
const d=await fetchJ(url);
if(id!==STATE.requests.gSearch)return;
STATE.searchQuery=q;
renderGlobalResults(d.messages)
}catch(e){showErr(e.message)}
}

function renderGlobalResults(msgs){
STATE.activeId=null;setChatEnabled(false);renderConversations();
EL.messages.classList.remove('empty-state');
if(!msgs.length){EL.messages.innerHTML='<div class="empty-chat">Nenhum resultado.</div>';return}
let html='';let lastConv=0;let lastSender=null;
msgs.forEach(m=>{
if(m.conversation_id!==lastConv){
const conv=STATE.conversations.find(c=>Number(c.id)===m.conversation_id);
html+='<div class="conversation-chip">'+esc(conv?conv.title:'Conversa')+'</div>';
lastConv=m.conversation_id;lastSender=null}
const sender=m.sender||null;
if(sender===null){
const time=fmtTime(m.sent_at);
html+='<div class="system-msg">'+renderBody(m)+(time?'<span class="system-time">'+esc(time)+'</span>':'')+'</div>';
lastSender=null;return}
const mine=isOwnSender(sender);
const groupStart=sender!==lastSender;
html+='<article class="message-row '+(mine?'mine ':'')+(groupStart?'group-start':'group-follow')+'" data-conversation-id="'+esc(m.conversation_id||'')+'"><div class="msg-bubble">';
if(groupStart&&!mine)html+='<strong class="msg-sender">'+esc(sender)+'</strong>';
html+='<div class="msg-body">'+renderBody(m)+'</div><time class="msg-time">'+esc(fmtTime(m.sent_at))+'</time></div></article>';
lastSender=sender
});
EL.messages.innerHTML=html;
EL.chatSubtitle.textContent='Resultados da busca geral';
EL.chatTitle.textContent='Busca: '+esc(EL.globalSearchInput.value);
EL.messageCount.textContent=msgs.length+' resultados'
}

async function doChatSearch(){
if(!STATE.activeId)return;
const q=EL.chatSearchInput.value.trim();
const ds=EL.chatDateStart.value;
const de=EL.chatDateEnd.value;
const id=++STATE.requests.cSearch;
try{
let url='/api/search?conversation_id='+STATE.activeId+'&limit=500&sort=asc&q='+encodeURIComponent(q);
if(ds)url+='&date_start='+ds;
if(de)url+='&date_end='+de;
const d=await fetchJ(url);
if(id!==STATE.requests.cSearch)return;
STATE.searchQuery=q;
renderMessages(d.messages)
}catch(e){showErr(e.message)}
}

function clearGlobalFilters(load=true){
EL.globalSearchInput.value='';EL.globalDateStart.value='';EL.globalDateEnd.value='';
STATE.searchQuery='';
if(load){loadConversations();setWelcome()}
}

function clearChatFilters(load=true){
EL.chatSearchInput.value='';EL.chatDateStart.value='';EL.chatDateEnd.value='';
STATE.searchQuery='';
if(load&&STATE.activeId)loadMessages(STATE.activeId)
}

// ── Events ──────────────────────────────────────────────────────────────────
EL.refreshButton.addEventListener('click',()=>{loadConversations()});
EL.globalSearchInput.addEventListener('input',debounce(STATE.timers.global,doGlobalSearch));
EL.globalDateStart.addEventListener('change',debounce(STATE.timers.global,doGlobalSearch));
EL.globalDateEnd.addEventListener('change',debounce(STATE.timers.global,doGlobalSearch));
EL.clearGlobalSearch.addEventListener('click',()=>clearGlobalFilters(true));
EL.chatSearchInput.addEventListener('input',debounce(STATE.timers.chat,doChatSearch));
EL.chatDateStart.addEventListener('change',debounce(STATE.timers.chat,doChatSearch));
EL.chatDateEnd.addEventListener('change',debounce(STATE.timers.chat,doChatSearch));
EL.clearChatSearch.addEventListener('click',()=>clearChatFilters(true));

// ── Init ────────────────────────────────────────────────────────────────────
initUploader();
loadConversations();
if(location.hash){const m=location.hash.match(/c(\\d+)/);if(m)openConversation(Number(m[1]))}
</script>
</body>
</html>"""

# ── Admin page ────────────────────────────────────────────────────────────────

PAGE_ADMIN = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin - Usuarios</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:#f5f5f5;color:#222}
.admin-shell{max-width:720px;margin:0 auto;padding:24px 16px}
.admin-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px}
.admin-header .eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#888}
.admin-header h1{font-size:22px}
.admin-nav{display:flex;gap:8px}
.button{display:inline-flex;align-items:center;justify-content:center;padding:8px 16px;border:none;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;transition:background .15s;background:#2563eb;color:#fff;text-decoration:none}
.button:hover{background:#1d4ed8}
.button.secondary{background:#fff;color:#374151;border:1px solid #d1d5db}
.button.secondary:hover{background:#f3f4f6}
.button.ghost{background:transparent;color:#888;border:1px solid transparent}
.button.ghost:hover{background:#f3f4f6;color:#222}
.admin-card{background:#fff;border-radius:12px;padding:24px;box-shadow:0 1px 6px rgba(0,0,0,.06);margin-bottom:16px}
.admin-card h2{font-size:16px;margin-bottom:16px}
.admin-form{display:flex;flex-direction:column;gap:12px}
label{display:flex;flex-direction:column;gap:4px;font-size:13px;font-weight:500}
input,select{padding:8px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:14px;outline:none}
input:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.12)}
.check-label{flex-direction:row;align-items:center;gap:8px;font-weight:400}
.check-label.compact{flex-direction:row;align-items:center;gap:6px;font-size:13px}
.user-list{display:flex;flex-direction:column;gap:8px}
.user-row{display:flex;align-items:center;gap:8px;padding:10px 12px;background:#f9fafb;border-radius:8px;flex-wrap:wrap}
.user-info{flex:1;min-width:120px}
.user-info strong{display:block;font-size:14px}
.user-info small{font-size:12px;color:#888}
.user-row select,.user-row input[type=password]{padding:5px 8px;font-size:13px;width:auto;min-width:80px;flex-shrink:0}
</style>
</head>
<body>
<main class="admin-shell">
<header class="admin-header">
<div>
<p class="eyebrow">Administracao</p>
<h1>Usuarios</h1>
</div>
<nav class="admin-nav">
<a class="button secondary" href="/">Voltar</a>
<a class="button ghost" href="/logout">Sair</a>
</nav>
</header>
<section class="admin-card">
<h2>Criar usuario</h2>
<form method="post" class="admin-form">
<input type="hidden" name="csrf_token" value="{CSRF_TOKEN}">
<input type="hidden" name="action" value="create">
<label><span>Usuario</span><input name="username" type="text" required placeholder="usuario"></label>
<label><span>Senha</span><input name="password" type="password" required placeholder="minimo 6 caracteres"></label>
<label><span>Tipo</span>
<select name="role">
<option value="user">Usuario</option>
<option value="admin">Admin</option>
</select>
</label>
<label class="check-label"><input name="active" type="checkbox" checked><span>Ativo</span></label>
<button class="button" type="submit">Cadastrar</button>
</form>
</section>
<section class="admin-card">
<h2>Usuarios cadastrados</h2>
<div class="user-list">
{USER_ROWS}
</div>
</section>
</main>
</body>
</html>"""

# ── Server ───────────────────────────────────────────────────────────────────

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def main():
    global SECRET_KEY
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        migrate()
        print("Banco e storage prontos em:", STORAGE_ROOT)
        return
    
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        global PORT
        PORT = int(sys.argv[idx + 1])
    
    SECRET_KEY = os.environ.get("ZAPVIEWER_SECRET", secrets.token_hex(32))
    migrate()
    
    server = ThreadedHTTPServer((HOST, PORT), ZapHandler)
    print(f"ZapViewer rodando em http://{HOST}:{PORT}")
    print(f"Storage: {STORAGE_ROOT}")
    print("Pressione Ctrl+C para parar.")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nParando...")
        server.shutdown()

if __name__ == "__main__":
    main()
