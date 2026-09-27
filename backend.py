"""
همراه — بک‌اند کامل
=====================================
تمام APIها، دیتابیس، احراز هویت، چت و مدیریت درخواست‌ها در یک ماژول.

اجرا: python backend.py
پورت: 8000
مستندات: http://localhost:8000/docs
"""

import os
import json
import sqlite3
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Depends, status, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, EmailStr, Field
import uvicorn


# ============================================================
# تنظیمات
# ============================================================
DB_PATH = "hamrah.db"
SECRET_KEY = os.getenv("HAMRAH_SECRET", secrets.token_hex(32))
TOKEN_TTL_HOURS = 24 * 7  # ۷ روز


# ============================================================
# دیتابیس
# ============================================================
def init_db():
    with get_db() as conn:
        c = conn.cursor()

        # کاربران
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                password_hash TEXT NOT NULL,
                avatar TEXT,
                bio TEXT DEFAULT '',
                rating REAL DEFAULT 5.0,
                rating_count INTEGER DEFAULT 0,
                is_verified INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        # درخواست‌ها
        c.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                title_en TEXT,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                description_en TEXT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                location TEXT NOT NULL,
                location_en TEXT,
                price INTEGER DEFAULT 0,
                conditions TEXT DEFAULT '',
                urgent INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                selected_offer_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # پیشنهادها
        c.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                price INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY(request_id) REFERENCES requests(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # پیام‌ها (چت)
        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                request_id INTEGER,
                body TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(sender_id) REFERENCES users(id),
                FOREIGN KEY(receiver_id) REFERENCES users(id)
            )
        """)

        # اعلان‌ها
        c.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT DEFAULT '',
                type TEXT DEFAULT 'info',
                is_read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # تاریخچه فعالیت
        c.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_id INTEGER,
                meta TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # ایندکس‌ها
        c.execute("CREATE INDEX IF NOT EXISTS idx_req_user ON requests(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_req_cat ON requests(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_off_req ON offers(request_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_msg_users ON messages(sender_id, receiver_id)")

        conn.commit()
    print(f"✅ دیتابیس آماده است: {DB_PATH}")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row) -> dict:
    return dict(row) if row else None


def rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# ============================================================
# امنیت
# ============================================================
def hash_password(password: str) -> str:
    salt = SECRET_KEY[:16]
    return hashlib.sha256((salt + password).encode()).hexdigest()


def verify_password(password: str, hash_: str) -> bool:
    return hash_password(password) == hash_


def make_token(user_id: int) -> str:
    payload = {"uid": user_id, "exp": (datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)).isoformat()}
    raw = json.dumps(payload)
    token = secrets.token_urlsafe(24) + "." + hashlib.sha256((raw + SECRET_KEY).encode()).hexdigest()[:32]
    # در دیتابیس سشن را ذخیره می‌کنیم (ساده‌سازی)
    with get_db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER, expires TEXT)"
        )
        conn.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
                     (token, user_id, payload["exp"]))
        conn.commit()
    return token


def decode_token(token: str) -> Optional[int]:
    with get_db() as conn:
        row = conn.execute("SELECT user_id, expires FROM sessions WHERE token=?", (token,)).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires"]) < datetime.utcnow():
            return None
        return row["user_id"]


# ============================================================
# FastAPI Setup
# ============================================================
app = FastAPI(title="Hamrah API", version="1.0.0", description="API سیستم همراهی")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if not cred:
        raise HTTPException(401, "توکن ارسال نشده")
    uid = decode_token(cred.credentials)
    if not uid:
        raise HTTPException(401, "توکن نامعتبر یا منقضی شده")
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise HTTPException(401, "کاربر یافت نشد")
        return dict(row)


def optional_user(cred: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    if not cred:
        return None
    uid = decode_token(cred.credentials)
    if not uid:
        return None
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(row) if row else None


def log_activity(user_id: int, action: str, target_id: int = None, meta: dict = None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO activities (user_id, action, target_id, meta, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, action, target_id, json.dumps(meta or {}, ensure_ascii=False), datetime.utcnow().isoformat())
        )
        conn.commit()


def add_notification(user_id: int, title: str, body: str = "", type_: str = "info"):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notifications (user_id, title, body, type, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, title, body, type_, datetime.utcnow().isoformat())
        )
        conn.commit()


# ============================================================
# Schemas
# ============================================================
class SignupIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    email: EmailStr
    phone: Optional[str] = None
    password: str = Field(..., min_length=6)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RequestIn(BaseModel):
    title: str = Field(..., min_length=3)
    category: str
    description: str = Field(..., min_length=5)
    date: str
    time: str
    location: str
    price: int = 0
    conditions: str = ""
    urgent: bool = False


class OfferIn(BaseModel):
    price: int = 0
    message: str = ""


class MessageIn(BaseModel):
    receiver_id: int
    body: str
    request_id: Optional[int] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None


# ============================================================
# AUTH
# ============================================================
@app.post("/api/auth/signup", tags=["Auth"])
def signup(data: SignupIn):
    with get_db() as conn:
        exists = conn.execute("SELECT id FROM users WHERE email=?", (data.email,)).fetchone()
        if exists:
            raise HTTPException(400, "این ایمیل قبلاً ثبت شده است")
        avatar = data.name.strip()[0].upper() if data.name.strip() else "U"
        cur = conn.execute(
            """INSERT INTO users (name, email, phone, password_hash, avatar, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (data.name, data.email, data.phone or "", hash_password(data.password),
             avatar, datetime.utcnow().isoformat())
        )
        conn.commit()
        uid = cur.lastrowid

    token = make_token(uid)
    log_activity(uid, "signup")
    add_notification(uid, "🎉 خوش آمدی!", "به جمع همراهان پیوستی.", "success")
    return {"token": token, "user": {"id": uid, "name": data.name, "email": data.email, "avatar": avatar}}


@app.post("/api/auth/login", tags=["Auth"])
def login(data: LoginIn):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (data.email,)).fetchone()
        if not row or not verify_password(data.password, row["password_hash"]):
            raise HTTPException(401, "ایمیل یا رمز عبور اشتباه است")
        uid = row["id"]
        user = dict(row)
    token = make_token(uid)
    log_activity(uid, "login")
    return {
        "token": token,
        "user": {
            "id": user["id"], "name": user["name"], "email": user["email"],
            "avatar": user["avatar"], "bio": user["bio"], "rating": user["rating"]
        }
    }


@app.get("/api/auth/me", tags=["Auth"])
def me(user: dict = Depends(current_user)):
    return {
        "id": user["id"], "name": user["name"], "email": user["email"],
        "phone": user["phone"], "avatar": user["avatar"], "bio": user["bio"],
        "rating": user["rating"], "rating_count": user["rating_count"],
        "is_verified": bool(user["is_verified"]),
        "created_at": user["created_at"]
    }


@app.patch("/api/auth/me", tags=["Auth"])
def update_me(data: ProfileUpdate, user: dict = Depends(current_user)):
    fields, values = [], []
    if data.name is not None:
        fields.append("name=?"); values.append(data.name)
        fields.append("avatar=?"); values.append(data.name[0].upper())
    if data.bio is not None:
        fields.append("bio=?"); values.append(data.bio)
    if data.phone is not None:
        fields.append("phone=?"); values.append(data.phone)
    if not fields:
        return {"ok": True, "message": "چیزی برای بروزرسانی نبود"}
    values.append(user["id"])
    with get_db() as conn:
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
    return {"ok": True}


# ============================================================
# CATEGORIES
# ============================================================
@app.get("/api/categories", tags=["Meta"])
def categories():
    return [
        {"id": "administrative", "fa": "کار اداری", "en": "Administrative", "emoji": "🏛️"},
        {"id": "cinema", "fa": "سینما", "en": "Cinema", "emoji": "🎬"},
        {"id": "theater", "fa": "تئاتر", "en": "Theater", "emoji": "🎭"},
        {"id": "shopping", "fa": "خرید", "en": "Shopping", "emoji": "🛍️"},
        {"id": "event", "fa": "رویداد", "en": "Event", "emoji": "🎉"},
        {"id": "sport", "fa": "ورزش", "en": "Sport", "emoji": "⚽"},
        {"id": "travel", "fa": "سفر", "en": "Travel", "emoji": "✈️"},
        {"id": "other", "fa": "سایر", "en": "Other", "emoji": "📌"},
    ]


@app.get("/api/stats", tags=["Meta"])
def stats():
    with get_db() as conn:
        users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        reqs = conn.execute("SELECT COUNT(*) as c FROM requests WHERE status='active'").fetchone()["c"]
        matches = conn.execute("SELECT COUNT(*) as c FROM offers WHERE status='accepted'").fetchone()["c"]
    return {"users": 3500 + users, "requests": 1200 + reqs, "matches": 8900 + matches, "cities": 48}


# ============================================================
# REQUESTS
# ============================================================
def _request_with_meta(r: dict, viewer_id: Optional[int] = None) -> dict:
    with get_db() as conn:
        u = conn.execute("SELECT id, name, avatar FROM users WHERE id=?", (r["user_id"],)).fetchone()
        offers_count = conn.execute(
            "SELECT COUNT(*) as c FROM offers WHERE request_id=?", (r["id"],)
        ).fetchone()["c"]
        user_offered = False
        if viewer_id:
            row = conn.execute(
                "SELECT id FROM offers WHERE request_id=? AND user_id=?",
                (r["id"], viewer_id)
            ).fetchone()
            user_offered = bool(row)
    r["user"] = {"id": u["id"], "name": u["name"], "avatar": u["avatar"]} if u else None
    r["offers_count"] = offers_count
    r["urgent"] = bool(r["urgent"])
    r["user_offered"] = user_offered
    return r


@app.get("/api/requests", tags=["Requests"])
def list_requests(
    category: Optional[str] = None,
    search: Optional[str] = None,
    urgent: Optional[bool] = None,
    status_: str = Query("active", alias="status"),
    limit: int = 100,
    offset: int = 0,
    viewer: Optional[dict] = Depends(optional_user),
):
    q = "SELECT * FROM requests WHERE 1=1"
    params = []
    if status_ != "all":
        q += " AND status=?"; params.append(status_)
    if category and category != "all":
        q += " AND category=?"; params.append(category)
    if urgent:
        q += " AND urgent=1"
    if search:
        q += " AND (title LIKE ? OR description LIKE ? OR title_en LIKE ? OR description_en LIKE ?)"
        s = f"%{search}%"
        params += [s, s, s, s]
    q += " ORDER BY urgent DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    with get_db() as conn:
        rows = conn.execute(q, params).fetchall()
    viewer_id = viewer["id"] if viewer else None
    return [_request_with_meta(dict(r), viewer_id) for r in rows]


@app.get("/api/requests/{req_id}", tags=["Requests"])
def get_request(req_id: int, viewer: Optional[dict] = Depends(optional_user)):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM requests WHERE id=?", (req_id,)).fetchone()
    if not row:
        raise HTTPException(404, "درخواست یافت نشد")
    r = _request_with_meta(dict(row), viewer["id"] if viewer else None)
    with get_db() as conn:
        offers = conn.execute("""
            SELECT o.*, u.name as user_name, u.avatar as user_avatar, u.rating as user_rating
            FROM offers o JOIN users u ON u.id=o.user_id
            WHERE o.request_id=? ORDER BY o.id DESC
        """, (req_id,)).fetchall()
    r["offers"] = rows_to_list(offers)
    return r


@app.post("/api/requests", tags=["Requests"])
def create_request(data: RequestIn, user: dict = Depends(current_user)):
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO requests (user_id, title, title_en, category, description, description_en,
                                  date, time, location, location_en, price, conditions, urgent,
                                  status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """, (
            user["id"], data.title, data.title, data.category,
            data.description, data.description, data.date, data.time,
            data.location, data.location, data.price, data.conditions,
            1 if data.urgent else 0, datetime.utcnow().isoformat()
        ))
        conn.commit()
        rid = cur.lastrowid
    log_activity(user["id"], "create_request", rid)
    return {"ok": True, "id": rid}


@app.delete("/api/requests/{req_id}", tags=["Requests"])
def delete_request(req_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        row = conn.execute("SELECT user_id FROM requests WHERE id=?", (req_id,)).fetchone()
        if not row:
            raise HTTPException(404, "یافت نشد")
        if row["user_id"] != user["id"]:
            raise HTTPException(403, "اجازه ندارید")
        conn.execute("DELETE FROM requests WHERE id=?", (req_id,))
        conn.execute("DELETE FROM offers WHERE request_id=?", (req_id,))
        conn.commit()
    log_activity(user["id"], "delete_request", req_id)
    return {"ok": True}


@app.get("/api/my/requests", tags=["Requests"])
def my_requests(user: dict = Depends(current_user)):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM requests WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    return [_request_with_meta(dict(r), user["id"]) for r in rows]


# ============================================================
# OFFERS
# ============================================================
@app.post("/api/requests/{req_id}/offers", tags=["Offers"])
def create_offer(req_id: int, data: OfferIn, user: dict = Depends(current_user)):
    with get_db() as conn:
        req = conn.execute("SELECT * FROM requests WHERE id=?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(404, "درخواست یافت نشد")
        if req["user_id"] == user["id"]:
            raise HTTPException(400, "نمی‌توانید برای درخواست خودتان پیشنهاد بدهید")
        exists = conn.execute(
            "SELECT id FROM offers WHERE request_id=? AND user_id=?",
            (req_id, user["id"])
        ).fetchone()
        if exists:
            raise HTTPException(400, "قبلاً پیشنهاد داده‌اید")
        cur = conn.execute("""
            INSERT INTO offers (request_id, user_id, price, message, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (req_id, user["id"], data.price, data.message, datetime.utcnow().isoformat()))
        conn.commit()
        oid = cur.lastrowid

    add_notification(
        req["user_id"],
        "💌 پیشنهاد جدید",
        f"{user['name']} برای «{req['title']}» پیشنهاد داد.",
        "offer"
    )
    log_activity(user["id"], "create_offer", oid, {"request_id": req_id})
    return {"ok": True, "id": oid}


@app.get("/api/requests/{req_id}/offers", tags=["Offers"])
def list_offers(req_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        req = conn.execute("SELECT user_id FROM requests WHERE id=?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(404, "یافت نشد")
        if req["user_id"] != user["id"]:
            raise HTTPException(403, "فقط صاحب درخواست می‌تواند پیشنهادها را ببیند")
        rows = conn.execute("""
            SELECT o.*, u.name as user_name, u.avatar as user_avatar, u.rating as user_rating
            FROM offers o JOIN users u ON u.id=o.user_id
            WHERE o.request_id=? ORDER BY o.id DESC
        """, (req_id,)).fetchall()
    return rows_to_list(rows)


@app.get("/api/my/offers", tags=["Offers"])
def my_offers(user: dict = Depends(current_user)):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT o.*, r.title as request_title, r.category, r.date, r.time, r.location
            FROM offers o JOIN requests r ON r.id=o.request_id
            WHERE o.user_id=? ORDER BY o.id DESC
        """, (user["id"],)).fetchall()
    return rows_to_list(rows)


@app.post("/api/offers/{offer_id}/accept", tags=["Offers"])
def accept_offer(offer_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        off = conn.execute("SELECT * FROM offers WHERE id=?", (offer_id,)).fetchone()
        if not off:
            raise HTTPException(404, "پیشنهاد یافت نشد")
        req = conn.execute("SELECT * FROM requests WHERE id=?", (off["request_id"],)).fetchone()
        if req["user_id"] != user["id"]:
            raise HTTPException(403, "اجازه ندارید")
        # رد بقیه
        conn.execute(
            "UPDATE offers SET status='rejected' WHERE request_id=? AND id!=?",
            (off["request_id"], offer_id)
        )
        conn.execute("UPDATE offers SET status='accepted' WHERE id=?", (offer_id,))
        conn.execute("UPDATE requests SET status='matched', selected_offer_id=? WHERE id=?",
                     (offer_id, off["request_id"]))
        conn.commit()
        winner_id = off["user_id"]
        req_title = req["title"]

    add_notification(winner_id, "🎉 پیشنهاد شما پذیرفته شد!", f"درخواست «{req_title}»", "success")
    log_activity(user["id"], "accept_offer", offer_id)
    return {"ok": True}


@app.post("/api/offers/{offer_id}/reject", tags=["Offers"])
def reject_offer(offer_id: int, user: dict = Depends(current_user)):
    with get_db() as conn:
        off = conn.execute("SELECT * FROM offers WHERE id=?", (offer_id,)).fetchone()
        if not off:
            raise HTTPException(404, "یافت نشد")
        req = conn.execute("SELECT user_id FROM requests WHERE id=?", (off["request_id"],)).fetchone()
        if req["user_id"] != user["id"]:
            raise HTTPException(403, "اجازه ندارید")
        conn.execute("UPDATE offers SET status='rejected' WHERE id=?", (offer_id,))
        conn.commit()
    return {"ok": True}


@app.get("/api/my/received-offers", tags=["Offers"])
def received_offers(user: dict = Depends(current_user)):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT o.*, u.name as offerer_name, u.avatar as offerer_avatar, u.rating as offerer_rating,
                   r.title as request_title
            FROM offers o
            JOIN requests r ON r.id=o.request_id
            JOIN users u ON u.id=o.user_id
            WHERE r.user_id=? ORDER BY o.id DESC
        """, (user["id"],)).fetchall()
    return rows_to_list(rows)


# ============================================================
# MESSAGES (Chat)
# ============================================================
@app.get("/api/messages/{other_id}", tags=["Messages"])
def get_messages(other_id: int, user: dict = Depends(current_user), limit: int = 100):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM messages
            WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
            ORDER BY id ASC LIMIT ?
        """, (user["id"], other_id, other_id, user["id"], limit)).fetchall()
        # علامت خوانده‌شده
        conn.execute(
            "UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=?",
            (other_id, user["id"])
        )
        conn.commit()
    return rows_to_list(rows)


@app.post("/api/messages", tags=["Messages"])
def send_message(data: MessageIn, user: dict = Depends(current_user)):
    if data.receiver_id == user["id"]:
        raise HTTPException(400, "نمی‌توانید به خودتان پیام بدهید")
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO messages (sender_id, receiver_id, request_id, body, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user["id"], data.receiver_id, data.request_id, data.body, datetime.utcnow().isoformat()))
        conn.commit()
        mid = cur.lastrowid
    add_notification(data.receiver_id, "💬 پیام جدید", f"از {user['name']}", "message")
    return {"ok": True, "id": mid}


@app.get("/api/conversations", tags=["Messages"])
def conversations(user: dict = Depends(current_user)):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
              CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END as other_id,
              MAX(id) as last_id
            FROM messages
            WHERE sender_id=? OR receiver_id=?
            GROUP BY other_id ORDER BY last_id DESC
        """, (user["id"], user["id"], user["id"])).fetchall()

        result = []
        for r in rows:
            other = conn.execute("SELECT id, name, avatar FROM users WHERE id=?", (r["other_id"],)).fetchone()
            last = conn.execute("SELECT * FROM messages WHERE id=?", (r["last_id"],)).fetchone()
            unread = conn.execute("""
                SELECT COUNT(*) as c FROM messages
                WHERE sender_id=? AND receiver_id=? AND is_read=0
            """, (r["other_id"], user["id"])).fetchone()["c"]
            result.append({
                "other": dict(other) if other else None,
                "last_message": dict(last) if last else None,
                "unread": unread
            })
    return result


# ============================================================
# NOTIFICATIONS
# ============================================================
@app.get("/api/notifications", tags=["Notifications"])
def notifications(user: dict = Depends(current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50",
            (user["id"],)
        ).fetchall()
        unread = conn.execute(
            "SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND is_read=0",
            (user["id"],)
        ).fetchone()["c"]
    return {"items": rows_to_list(rows), "unread": unread}


@app.post("/api/notifications/read-all", tags=["Notifications"])
def read_all_notifs(user: dict = Depends(current_user)):
    with get_db() as conn:
        conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user["id"],))
        conn.commit()
    return {"ok": True}


# ============================================================
# ACTIVITY / HISTORY
# ============================================================
@app.get("/api/my/activities", tags=["Activity"])
def my_activities(user: dict = Depends(current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activities WHERE user_id=? ORDER BY id DESC LIMIT 100",
            (user["id"],)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["meta"] = json.loads(d["meta"]) if d["meta"] else {}
        except Exception:
            d["meta"] = {}
        out.append(d)
    return out


# ============================================================
# WebSocket برای چت Real-time
# ============================================================
active_connections: dict[int, list[WebSocket]] = {}


@app.websocket("/ws/chat/{user_id}")
async def ws_chat(websocket: WebSocket, user_id: int, token: str = Query(...)):
    uid = decode_token(token)
    if not uid or uid != user_id:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    active_connections.setdefault(user_id, []).append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            receiver = int(data.get("receiver_id", 0))
            body = (data.get("body") or "").strip()
            request_id = data.get("request_id")
            if not receiver or not body:
                continue

            with get_db() as conn:
                cur = conn.execute("""
                    INSERT INTO messages (sender_id, receiver_id, request_id, body, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, receiver, request_id, body, datetime.utcnow().isoformat()))
                conn.commit()
                mid = cur.lastrowid
                msg_row = conn.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()

            payload = {"type": "message", "data": dict(msg_row)}

            for ws in active_connections.get(receiver, []):
                try:
                    await ws.send_json(payload)
                except Exception:
                    pass
            for ws in active_connections.get(user_id, []):
                try:
                    await ws.send_json({"type": "sent", "data": dict(msg_row)})
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        if user_id in active_connections and websocket in active_connections[user_id]:
            active_connections[user_id].remove(websocket)


# ============================================================
# ریشه
# ============================================================
@app.get("/", tags=["Meta"])
def root():
    return {
        "app": "همراه",
        "message": "بک‌اند آماده است 🚀",
        "docs": "/docs",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Meta"])
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# ============================================================
# اجرا
# ============================================================
def main():
    init_db()
    print("\n" + "=" * 60)
    print("🤝  سرور همراه در حال اجراست")
    print("=" * 60)
    print(f"  🌐 URL       : http://localhost:8000")
    print(f"  📖 Docs      : http://localhost:8000/docs")
    print(f"  🎨 Frontend  : http://localhost:8000/app")
    print(f"  💾 Database  : {DB_PATH}")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()