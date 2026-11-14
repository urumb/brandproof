import io
import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from . import db, llm
from .auth import (current_user, hash_password, login_failures, require_roles,
                   review_limiter, verify_password)
from .review import run_review
from .seed import SAMPLE_DRAFT, seed


def _load_dotenv():
    p = Path(__file__).resolve().parent.parent / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_TEXT = 20_000
MAX_UPLOAD = 1_000_000

app = FastAPI(title="BrandProof", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security(request: Request, call_next):
    # CSRF guard: state-changing API calls must come from our own JS (custom header can't be set cross-site).
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("x-brandproof") != "1":
            return JSONResponse({"detail": "Missing request header."}, status_code=403)
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY") or secrets.token_urlsafe(48),
    same_site="lax",
    https_only=os.environ.get("COOKIE_SECURE") == "1",
    max_age=60 * 60 * 12,
)


@app.on_event("startup")
def startup():
    db.init()
    if os.environ.get("SEED_DEMO", "1") == "1":
        conn = db.connect()
        seed(conn)
        conn.close()


def audit(conn, draft_id, user_id, action, detail=None):
    conn.execute("INSERT INTO audit (draft_id, user_id, action, detail) VALUES (?,?,?,?)",
                 (draft_id, user_id, action, detail))


# ---------- auth ----------

class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


@app.get("/api/config")
def config():
    hint = None
    if os.environ.get("DEMO_LOGIN_HINT") == "1":
        hint = {"accounts": ["admin", "creator", "reviewer"], "password": os.environ.get("DEMO_PASSWORD", "change-me-demo")}
    return {"demo": hint, "ai": llm.public_status(), "sample": SAMPLE_DRAFT}


@app.post("/api/login")
def login(body: LoginIn, request: Request, conn=Depends(db.get_conn)):
    ip = request.client.host if request.client else "?"
    if login_failures.blocked(ip):
        raise HTTPException(429, "Too many failed attempts. Wait a few minutes.")
    row = conn.execute("SELECT * FROM users WHERE username=?", (body.username.strip().lower(),)).fetchone()
    if not row or not verify_password(body.password, row["pw_hash"]):
        login_failures.allow(ip)
        raise HTTPException(401, "Wrong username or password.")
    request.session.clear()
    request.session["uid"] = row["id"]
    return {"id": row["id"], "username": row["username"], "name": row["name"], "role": row["role"]}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


# ---------- sources (brand library) ----------

class SourceIn(BaseModel):
    kind: str = Field(pattern="^(guideline|fact|term|banned)$")
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)
    avoid: str | None = Field(default=None, max_length=120)
    prefer: str | None = Field(default=None, max_length=120)
    case_sensitive: bool = False


@app.get("/api/sources")
def list_sources(user=Depends(current_user), conn=Depends(db.get_conn)):
    return [dict(r) for r in conn.execute("SELECT * FROM sources WHERE active=1 ORDER BY kind, id")]


@app.post("/api/sources")
def add_source(body: SourceIn, user=Depends(require_roles("admin")), conn=Depends(db.get_conn)):
    if body.kind in ("term", "banned") and not (body.avoid or "").strip():
        raise HTTPException(400, "Terms and banned phrases need the wording to avoid.")
    if body.kind == "term" and not (body.prefer or "").strip():
        raise HTTPException(400, "Terms need the preferred wording.")
    cur = conn.execute(
        "INSERT INTO sources (kind, title, body, avoid, prefer, case_sensitive) VALUES (?,?,?,?,?,?)",
        (body.kind, body.title.strip(), body.body.strip(), (body.avoid or "").strip() or None,
         (body.prefer or "").strip() or None, int(body.case_sensitive)),
    )
    return {"id": cur.lastrowid}


@app.delete("/api/sources/{sid}")
def delete_source(sid: int, user=Depends(require_roles("admin")), conn=Depends(db.get_conn)):
    conn.execute("UPDATE sources SET active=0 WHERE id=?", (sid,))
    return {"ok": True}


def _extract_text(name: str, data: bytes) -> str:
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 1 MB.")
    lower = (name or "").lower()
    if lower.endswith(".txt") or lower.endswith(".md"):
        return data.decode("utf-8", errors="replace")
    if lower.endswith(".docx"):
        try:
            import docx
            d = docx.Document(io.BytesIO(data))
            return "\n\n".join(p.text for p in d.paragraphs if p.text.strip())
        except Exception:
            raise HTTPException(400, "Could not read that .docx file.")
    raise HTTPException(400, "Upload a .txt, .md or .docx file.")


@app.post("/api/extract")
async def extract(file: UploadFile = File(...), user=Depends(current_user)):
    text = _extract_text(file.filename, await file.read(MAX_UPLOAD + 1))
    return {"text": text[:MAX_TEXT]}


@app.post("/api/sources/import")
async def import_guidelines(file: UploadFile = File(...), user=Depends(require_roles("admin")), conn=Depends(db.get_conn)):
    text = _extract_text(file.filename, await file.read(MAX_UPLOAD + 1))
    paras = [p.strip() for p in text.replace("\r", "").split("\n") if len(p.strip()) >= 20][:200]
    base = Path(file.filename or "Imported").stem[:60]
    for i, p in enumerate(paras, 1):
        conn.execute("INSERT INTO sources (kind, title, body) VALUES ('guideline',?,?)", (f"{base} §{i}", p[:2000]))
    return {"imported": len(paras)}


# ---------- drafts ----------

class DraftIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    channel: str = Field(pattern="^(social|ad|email|web|document)$")
    content: str = Field(min_length=1, max_length=MAX_TEXT)


class ContentIn(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_TEXT)


def _get_draft(conn, did, user, write=False):
    d = conn.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
    if not d:
        raise HTTPException(404, "Draft not found.")
    if user["role"] == "creator" and d["author_id"] != user["id"]:
        raise HTTPException(404, "Draft not found.")
    if write and d["status"] == "approved":
        raise HTTPException(409, "This draft is approved and locked.")
    return dict(d)


def _check_rate(user):
    if not review_limiter.allow(f"u{user['id']}"):
        raise HTTPException(429, "Too many reviews in a short time. Wait a few minutes.")


def _detail(conn, did, user, note=None):
    d = _get_draft(conn, did, user)
    findings = [dict(r) for r in conn.execute(
        """SELECT f.*, s.title AS source_title, s.kind AS source_kind FROM findings f
           JOIN sources s ON s.id=f.source_id WHERE f.draft_id=?
           ORDER BY CASE f.status WHEN 'open' THEN 0 ELSE 1 END, f.id""", (did,))]
    comments = [dict(r) for r in conn.execute(
        "SELECT c.*, u.name FROM comments c JOIN users u ON u.id=c.user_id WHERE draft_id=? ORDER BY c.id", (did,))]
    log = [dict(r) for r in conn.execute(
        "SELECT a.*, u.name FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE draft_id=? ORDER BY a.id DESC", (did,))]
    versions = conn.execute("SELECT COUNT(*) FROM versions WHERE draft_id=?", (did,)).fetchone()[0]
    author = conn.execute("SELECT name FROM users WHERE id=?", (d["author_id"],)).fetchone()
    d["author_name"] = author["name"] if author else "?"
    is_author = d["author_id"] == user["id"]
    reviewer = user["role"] in ("reviewer", "admin")
    editable = d["status"] in ("draft", "changes_requested")
    return {
        "draft": d, "findings": findings, "comments": comments, "audit": log, "versions": versions, "note": note,
        "can": {
            "edit": editable and (is_author or user["role"] == "admin"),
            "resolve": d["status"] != "approved" and (is_author or reviewer),
            "submit": editable and is_author,
            "decide": d["status"] == "in_review" and reviewer,
        },
    }


@app.get("/api/drafts")
def list_drafts(user=Depends(current_user), conn=Depends(db.get_conn)):
    q = """SELECT d.id, d.title, d.channel, d.status, d.updated_at, u.name AS author_name,
           (SELECT COUNT(*) FROM findings f WHERE f.draft_id=d.id AND f.status='open') AS open_findings
           FROM drafts d JOIN users u ON u.id=d.author_id"""
    if user["role"] == "creator":
        rows = conn.execute(q + " WHERE d.author_id=? ORDER BY d.id DESC", (user["id"],))
    else:
        rows = conn.execute(q + " ORDER BY d.id DESC")
    return [dict(r) for r in rows]


@app.post("/api/drafts")
def create_draft(body: DraftIn, user=Depends(require_roles("creator", "admin")), conn=Depends(db.get_conn)):
    _check_rate(user)
    cur = conn.execute("INSERT INTO drafts (author_id, title, channel, content) VALUES (?,?,?,?)",
                       (user["id"], body.title.strip(), body.channel, body.content))
    did = cur.lastrowid
    conn.execute("INSERT INTO versions (draft_id, content, note) VALUES (?,?,?)", (did, body.content, "Created"))
    note = run_review(conn, did, body.content)
    n = conn.execute("SELECT COUNT(*) FROM findings WHERE draft_id=? AND status='open'", (did,)).fetchone()[0]
    audit(conn, did, user["id"], "created", f"Reviewed automatically: {n} finding(s)")
    return _detail(conn, did, user, note)


@app.get("/api/drafts/{did}")
def get_draft(did: int, user=Depends(current_user), conn=Depends(db.get_conn)):
    return _detail(conn, did, user)


@app.put("/api/drafts/{did}")
def update_draft(did: int, body: ContentIn, user=Depends(current_user), conn=Depends(db.get_conn)):
    d = _get_draft(conn, did, user, write=True)
    if not _detail(conn, did, user)["can"]["edit"]:
        raise HTTPException(403, "You cannot edit this draft now.")
    _check_rate(user)
    _save_content(conn, d, body.content, user, "Edited by hand")
    note = run_review(conn, did, body.content)
    audit(conn, did, user["id"], "re-reviewed")
    return _detail(conn, did, user, note)


def _save_content(conn, d, content, user, why):
    conn.execute("UPDATE drafts SET content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (content, d["id"]))
    conn.execute("INSERT INTO versions (draft_id, content, note) VALUES (?,?,?)", (d["id"], content, why))


class ResolveIn(BaseModel):
    action: str = Field(pattern="^(accept|edit|dismiss)$")
    text: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)


@app.post("/api/findings/{fid}/resolve")
def resolve(fid: int, body: ResolveIn, user=Depends(current_user), conn=Depends(db.get_conn)):
    f = conn.execute("SELECT * FROM findings WHERE id=?", (fid,)).fetchone()
    if not f:
        raise HTTPException(404, "Finding not found.")
    d = _get_draft(conn, f["draft_id"], user, write=True)
    if not _detail(conn, d["id"], user)["can"]["resolve"]:
        raise HTTPException(403, "You cannot resolve findings on this draft.")
    if f["status"] != "open":
        raise HTTPException(409, "This finding is already resolved.")
    if body.action == "dismiss":
        conn.execute("UPDATE findings SET status='dismissed', resolution_note=? WHERE id=?",
                     ((body.reason or "").strip() or None, fid))
        audit(conn, d["id"], user["id"], "dismissed finding", f'"{f["excerpt"]}"' + (f" — {body.reason}" if body.reason else ""))
        return _detail(conn, d["id"], user)
    new_text = f["replacement"] if body.action == "accept" else body.text
    if new_text is None:
        raise HTTPException(400, "No replacement text given.")
    if f["excerpt"] not in d["content"]:
        raise HTTPException(409, "That text is no longer in the draft. Re-run the review.")
    content = d["content"].replace(f["excerpt"], new_text, 1)
    status = "accepted" if body.action == "accept" else "edited"
    conn.execute("UPDATE findings SET status=?, resolution_note=? WHERE id=?", (status, new_text, fid))
    _save_content(conn, d, content, user, f"{status} suggestion")
    audit(conn, d["id"], user["id"], f"{status} suggestion", f'"{f["excerpt"]}" → "{new_text}"')
    return _detail(conn, d["id"], user)


@app.post("/api/drafts/{did}/review")
def rereview(did: int, user=Depends(current_user), conn=Depends(db.get_conn)):
    d = _get_draft(conn, did, user, write=True)
    if not _detail(conn, did, user)["can"]["resolve"]:
        raise HTTPException(403, "You cannot review this draft now.")
    _check_rate(user)
    note = run_review(conn, did, d["content"])
    audit(conn, did, user["id"], "re-reviewed")
    return _detail(conn, did, user, note)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|changes)$")
    comment: str | None = Field(default=None, max_length=2000)
    acknowledge_open: bool = False


@app.post("/api/drafts/{did}/submit")
def submit(did: int, user=Depends(current_user), conn=Depends(db.get_conn)):
    _get_draft(conn, did, user, write=True)
    if not _detail(conn, did, user)["can"]["submit"]:
        raise HTTPException(403, "Only the author can submit this draft now.")
    conn.execute("UPDATE drafts SET status='in_review', updated_at=CURRENT_TIMESTAMP WHERE id=?", (did,))
    audit(conn, did, user["id"], "submitted for approval")
    return _detail(conn, did, user)


@app.post("/api/drafts/{did}/decision")
def decide(did: int, body: DecisionIn, user=Depends(require_roles("reviewer", "admin")), conn=Depends(db.get_conn)):
    d = _get_draft(conn, did, user, write=True)
    if d["status"] != "in_review":
        raise HTTPException(409, "This draft is not waiting for approval.")
    open_n = conn.execute("SELECT COUNT(*) FROM findings WHERE draft_id=? AND status='open'", (did,)).fetchone()[0]
    if body.decision == "approve" and open_n and not body.acknowledge_open:
        raise HTTPException(409, f"There are {open_n} open finding(s). Confirm to approve anyway.")
    status = "approved" if body.decision == "approve" else "changes_requested"
    conn.execute("UPDATE drafts SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, did))
    if body.comment and body.comment.strip():
        conn.execute("INSERT INTO comments (draft_id, user_id, body) VALUES (?,?,?)", (did, user["id"], body.comment.strip()))
    detail = f"with {open_n} open finding(s) acknowledged" if (status == "approved" and open_n) else None
    audit(conn, did, user["id"], "approved" if status == "approved" else "requested changes", detail)
    return _detail(conn, did, user)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@app.post("/api/drafts/{did}/comments")
def comment(did: int, body: CommentIn, user=Depends(current_user), conn=Depends(db.get_conn)):
    _get_draft(conn, did, user)
    conn.execute("INSERT INTO comments (draft_id, user_id, body) VALUES (?,?,?)", (did, user["id"], body.body.strip()))
    return _detail(conn, did, user)


# ---------- frontend ----------

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def health():
    return {"ok": True}
