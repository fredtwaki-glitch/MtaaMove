from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
from enum import Enum
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, String, Float, DateTime, Text, ForeignKey, select, func, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError


class Settings(BaseSettings):
    app_name: str = "MtaaMove API"
    environment: str = "development"
    database_url: str = "sqlite:///./mtaamove.db"
    cors_origins: str = "http://localhost:5173"
    session_cookie_name: str = "mtaamove_session"
    session_hours: int = 12
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
class PasswordService:
    """Argon2id password hashing adapter with non-throwing verification."""
    def __init__(self):
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, stored_hash: str) -> bool:
        try:
            return self._hasher.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError):
            return False


password_hash = PasswordService()
DUMMY_PASSWORD_HASH = password_hash.hash("fixed-dummy-password-for-timing-only")


class Base(DeclarativeBase):
    pass


class UserRole(str, Enum):
    customer = "customer"
    admin = "admin"


class BookingStatus(str, Enum):
    requested = "requested"
    quoted = "quoted"
    confirmed = "confirmed"
    searching = "searching"
    assigned = "assigned"
    completed = "completed"
    cancelled = "cancelled"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.customer.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    customer_phone: Mapped[str] = mapped_column(String(30))
    pickup: Mapped[str] = mapped_column(String(300))
    dropoff: Mapped[str] = mapped_column(String(300))
    move_date: Mapped[str] = mapped_column(String(30))
    property_type: Mapped[str] = mapped_column(String(50))
    inventory_notes: Mapped[str] = mapped_column(Text, default="")
    service_mode: Mapped[str] = mapped_column(String(30), default="automatic")
    vehicle_type: Mapped[str] = mapped_column(String(50), default="pickup")
    estimated_price_kes: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default=BookingStatus.requested.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


app = FastAPI(title=settings.app_name, version="0.2.0", description="MtaaMove moving and delivery marketplace API")
origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cookie_secure() -> bool:
    return settings.environment.lower() in {"production", "prod", "staging"}


def _set_auth_cookies(response: Response, raw_token: str, csrf_token: str, expires: datetime) -> None:
    common = {"secure": _cookie_secure(), "samesite": "lax", "path": "/", "expires": expires}
    response.set_cookie(settings.session_cookie_name, raw_token, httponly=True, **common)
    response.set_cookie("mtaamove_csrf", csrf_token, httponly=False, **common)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/", secure=_cookie_secure(), httponly=True, samesite="lax")
    response.delete_cookie("mtaamove_csrf", path="/", secure=_cookie_secure(), httponly=False, samesite="lax")


def get_current_session(request: Request, db: Session = Depends(get_db)) -> tuple[User, UserSession]:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_record = db.scalar(select(UserSession).where(UserSession.token_hash == _digest(raw_token)))
    if not session_record or session_record.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Authentication required")
    expires = session_record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired; please sign in again")
    user = db.get(User, session_record.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user, session_record


def get_current_user(session_pair: tuple[User, UserSession] = Depends(get_current_session)) -> User:
    return session_pair[0]


def require_csrf(request: Request, session_pair: tuple[User, UserSession] = Depends(get_current_session)) -> tuple[User, UserSession]:
    user, session_record = session_pair
    cookie_token = request.cookies.get("mtaamove_csrf", "")
    header_token = request.headers.get("X-CSRF-Token", "")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if not hmac.compare_digest(_digest(header_token), session_record.csrf_hash):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return user, session_record


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=30)
    password: str = Field(min_length=12, max_length=128)
    password_confirmation: str = Field(min_length=12, max_length=128)

    @field_validator("full_name", "phone")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    def validate_password_confirmation(self) -> None:
        if self.password != self.password_confirmation:
            raise HTTPException(status_code=422, detail="Passwords do not match")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserOut(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    phone: str
    role: str
    created_at: datetime
    model_config = {"from_attributes": True}


class QuoteRequest(BaseModel):
    pickup: str = Field(min_length=3, max_length=300)
    dropoff: str = Field(min_length=3, max_length=300)
    property_type: str = "one-bedroom"
    vehicle_type: str = "pickup"
    inventory_notes: str = Field(default="", max_length=3000)


class BookingCreate(QuoteRequest):
    move_date: date
    service_mode: str = "automatic"

    @field_validator("property_type")
    @classmethod
    def valid_property(cls, value: str) -> str:
        if value not in {"studio", "one-bedroom", "two-bedroom", "three-bedroom", "office"}:
            raise ValueError("Unsupported property type")
        return value

    @field_validator("vehicle_type")
    @classmethod
    def valid_vehicle(cls, value: str) -> str:
        if value not in {"motorbike", "pickup", "canter", "truck"}:
            raise ValueError("Unsupported vehicle type")
        return value

    @field_validator("move_date")
    @classmethod
    def date_not_past(cls, value: date) -> date:
        if value < datetime.now(timezone.utc).date():
            raise ValueError("Move date cannot be in the past")
        return value


class BookingOut(BaseModel):
    id: int
    customer_name: str
    customer_phone: str
    pickup: str
    dropoff: str
    move_date: str
    property_type: str
    inventory_notes: str
    service_mode: str
    vehicle_type: str
    estimated_price_kes: float
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}


# Lightweight process-local login throttle. For multi-instance production, use a shared rate limiter.
_login_attempts: dict[str, deque[float]] = defaultdict(deque)


def check_login_rate(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = _login_attempts[key]
    while attempts and now - attempts[0] > 60:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a minute.")
    attempts.append(now)


@app.get("/")
def root():
    return {"service": settings.app_name, "version": app.version, "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(select(1))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.post("/api/v1/auth/register", response_model=UserOut, status_code=201)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=422, detail="Passwords do not match")
    existing = db.scalar(select(User.id).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(full_name=payload.full_name, email=str(payload.email), phone=payload.phone,
                password_hash=password_hash.hash(payload.password), role=UserRole.customer.value)
    db.add(user)
    try:
        db.flush()
        raw_token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
        db.add(UserSession(user_id=user.id, token_hash=_digest(raw_token), csrf_hash=_digest(csrf_token), expires_at=expires))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)
    _set_auth_cookies(response, raw_token, csrf_token, expires)
    return user


@app.post("/api/v1/auth/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    check_login_rate(request)
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    # Perform a dummy hash verification for unknown emails to reduce timing differences.
    if not user:
        password_hash.hash("dummy-password-for-timing-only")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    raw_token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
    db.add(UserSession(user_id=user.id, token_hash=_digest(raw_token), csrf_hash=_digest(csrf_token), expires_at=expires))
    db.commit()
    _set_auth_cookies(response, raw_token, csrf_token, expires)
    return user


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@app.post("/api/v1/auth/logout", status_code=204)
def logout(response: Response, session_pair: tuple[User, UserSession] = Depends(require_csrf), db: Session = Depends(get_db)):
    _, session_record = session_pair
    session_record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    _clear_auth_cookies(response)
    response.status_code = 204
    return response


@app.post("/api/v1/auth/change-password", status_code=204)
def change_password(payload: ChangePasswordRequest, response: Response, session_pair: tuple[User, UserSession] = Depends(require_csrf), db: Session = Depends(get_db)):
    user, session_record = session_pair
    if not password_hash.verify(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = password_hash.hash(payload.new_password)
    # Revoke every session for this user; current cookie is cleared as well.
    db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).update(
        {UserSession.revoked_at: datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    _clear_auth_cookies(response)
    response.status_code = 204
    return response


# Temporary transparent estimate for the MVP; replace with distance-based pricing using Google Routes API.
def estimate_price(payload: QuoteRequest) -> float:
    base = {"studio": 2500, "one-bedroom": 4000, "two-bedroom": 6500, "three-bedroom": 9500, "office": 7000}[payload.property_type]
    vehicle = {"motorbike": 800, "pickup": 0, "canter": 3500, "truck": 6500}[payload.vehicle_type]
    stairs = 500 if any(word in payload.inventory_notes.lower() for word in ["stairs", "no lift", "third floor", "fourth floor"]) else 0
    return float(base + vehicle + stairs)


@app.post("/api/v1/quotes")
def create_quote(payload: QuoteRequest):
    if payload.property_type not in {"studio", "one-bedroom", "two-bedroom", "three-bedroom", "office"}:
        raise HTTPException(status_code=422, detail="Unsupported property type")
    if payload.vehicle_type not in {"motorbike", "pickup", "canter", "truck"}:
        raise HTTPException(status_code=422, detail="Unsupported vehicle type")
    return {"currency": "KES", "estimated_price": estimate_price(payload), "payment_method": "cash_on_completion", "disclaimer": "Indicative estimate only. Final price must be confirmed before the move."}


@app.post("/api/v1/bookings", response_model=BookingOut, status_code=201)
def create_booking(payload: BookingCreate, session_pair: tuple[User, UserSession] = Depends(require_csrf), db: Session = Depends(get_db)):
    user, _ = session_pair
    if payload.service_mode not in {"automatic", "choose_provider"}:
        raise HTTPException(status_code=422, detail="service_mode must be automatic or choose_provider")
    booking = Booking(user_id=user.id, customer_name=user.full_name, customer_phone=user.phone,
                      pickup=payload.pickup.strip(), dropoff=payload.dropoff.strip(),
                      move_date=payload.move_date.isoformat(), property_type=payload.property_type,
                      inventory_notes=payload.inventory_notes, service_mode=payload.service_mode,
                      vehicle_type=payload.vehicle_type, estimated_price_kes=estimate_price(payload),
                      status=BookingStatus.requested.value)
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@app.get("/api/v1/bookings", response_model=list[BookingOut])
def list_bookings(user: User = Depends(get_current_user), db: Session = Depends(get_db), limit: int = 50, offset: int = 0):
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(status_code=422, detail="Invalid pagination")
    query = select(Booking).order_by(Booking.id.desc()).offset(offset).limit(limit)
    if user.role != UserRole.admin.value:
        query = query.where(Booking.user_id == user.id)
    return list(db.scalars(query))


@app.get("/api/v1/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, session_pair: tuple[User, UserSession] = Depends(get_current_session), db: Session = Depends(get_db)):
    user, _ = session_pair
    query = select(Booking).where(Booking.id == booking_id)
    if user.role != UserRole.admin.value:
        query = query.where(Booking.user_id == user.id)
    booking = db.scalar(query)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@app.post("/api/v1/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: int, session_pair: tuple[User, UserSession] = Depends(require_csrf), db: Session = Depends(get_db)):
    user, _ = session_pair
    query = select(Booking).where(Booking.id == booking_id)
    if user.role != UserRole.admin.value:
        query = query.where(Booking.user_id == user.id)
    booking = db.scalar(query)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status in {BookingStatus.completed.value, BookingStatus.cancelled.value}:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {booking.status} booking")
    booking.status = BookingStatus.cancelled.value
    db.commit()
    db.refresh(booking)
    return booking


@app.get("/api/v1/admin/bookings", response_model=list[BookingOut])
def admin_list_bookings(_: User = Depends(require_admin), db: Session = Depends(get_db), limit: int = 50, offset: int = 0):
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(status_code=422, detail="Invalid pagination")
    return list(db.scalars(select(Booking).order_by(Booking.id.desc()).offset(offset).limit(limit)))


@app.get("/api/v1/providers")
def providers():
    return [
        {"id": "demo-1", "name": "CityLift Movers (demo)", "vehicle_type": "pickup", "rating": 4.8, "price_from_kes": 3500, "verified": False},
        {"id": "demo-2", "name": "Mtaa Cargo (demo)", "vehicle_type": "canter", "rating": 4.6, "price_from_kes": 6000, "verified": False},
        {"id": "demo-3", "name": "SwiftMove (demo)", "vehicle_type": "truck", "rating": 4.7, "price_from_kes": 9000, "verified": False},
    ]
