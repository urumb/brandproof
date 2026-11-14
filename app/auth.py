import hashlib
import hmac
import os
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from .db import get_conn


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


class Limiter:
    """Small in-memory sliding-window limiter (single process)."""

    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self.hits = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def blocked(self, key: str) -> bool:
        now = time.time()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return len(q) >= self.limit


login_failures = Limiter(limit=8, window=300)
review_limiter = Limiter(limit=25, window=600)


def current_user(request: Request, conn=Depends(get_conn)):
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(401, "Please sign in.")
    row = conn.execute("SELECT id, username, name, role FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        request.session.clear()
        raise HTTPException(401, "Please sign in.")
    return dict(row)


def require_roles(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "Your role cannot do this.")
        return user

    return dep
