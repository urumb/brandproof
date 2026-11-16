# BrandProof — Team Maverick (CodeNova India 2026)

Pre-publication brand governance. Content is checked against an organisation's **approved** guidelines,
facts and terminology. Every finding quotes the source it is based on and suggests a fix. People make
every decision.

## What works (Round 2)
- Sign in with roles: **admin** (brand library), **creator** (drafts), **reviewer** (approval).
- Brand library: guidelines, approved facts, terminology (avoid → prefer), banned phrases; import a
  `.txt`/`.docx` guideline document (each paragraph becomes a citable passage).
- Review of pasted text or uploaded `.txt`/`.docx` drafts:
  1. Rule checks (terminology, banned phrases) — no AI.
  2. Keyword (BM25) retrieval of the relevant guidelines and facts.
  3. AI review of claims, tone and messaging (any OpenAI-compatible API; default Groq free tier).
  4. **Grounding check:** an AI finding is kept only if its excerpt is in the draft and its quote is
     copied word for word from an approved source. Everything else is discarded and counted.
- Accept / edit / dismiss each finding (with reason); every change creates a version.
- Submit for approval → reviewer approves or requests changes, with comments. Approving with open
  findings needs explicit confirmation and is logged. Approved drafts are locked.
- Activity log and AI-use / privacy page.

## Run locally (free)
```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # macOS/Linux: .venv/bin/pip
cp .env.example .env                               # then fill in values
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```
Open http://localhost:8000. Without `LLM_API_KEY` the app still works with rule checks only.

Tests: `.venv/Scripts/python -m pytest -q`

## Free AI (Groq)
Create a free key at console.groq.com, put it in `.env` as `LLM_API_KEY`, and set `LLM_MODEL` to a
current model from Groq's model list. To switch provider, change `LLM_BASE_URL` / `LLM_MODEL` only.

## Security
- Secrets only in `.env` / host environment variables; `.env` is git-ignored.
- Passwords hashed with scrypt; signed, HTTP-only session cookie (`SameSite=Lax`, `Secure` when
  `COOKIE_SECURE=1`).
- CSRF guard (custom header on every write), strict Content-Security-Policy, no `innerHTML` with data.
- Role checks on every endpoint; creators only see their own drafts.
- Login and review rate limits; size limits on text and uploads.
- Draft text is treated as untrusted data in the AI prompt, and AI output is validated before use.
- Only the draft and matching approved sources are sent to the AI provider.

## Deploy (free)
`render.yaml` is a Render Blueprint for one free web service (New > Blueprint, pick this repo,
then enter `LLM_API_KEY` and `DEMO_PASSWORD`; `SECRET_KEY` is generated). On any other free Python host:
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`
  (proxy headers let rate limits see each visitor's IP instead of the host's proxy)
- Env vars: `LLM_API_KEY`, `LLM_MODEL`, `SECRET_KEY` (long random), `COOKIE_SECURE=1`,
  `SEED_DEMO=1`, `DEMO_PASSWORD`, `DEMO_LOGIN_HINT=1`, `DEMO_LOCK_LIBRARY=1`.
- Free hosts may sleep and reset the SQLite file; the demo workspace is re-seeded on start.
  Use a free uptime pinger on `/healthz` so judges don't hit a cold start.

## Disclosure
Built during the official Round 2 window with help from an AI coding assistant (Claude Code).
AI review calls go to the configured LLM provider (default Groq). Demo brand "Verdant" is fictional.
