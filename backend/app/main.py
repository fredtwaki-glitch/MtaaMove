from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import os

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, String, Float, DateTime, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session


class Settings(BaseSettings):
    app_name: str = "MtaaMove API"
    environment: str = "development"
    database_url: str = "sqlite:///./mtaamove.db"
    cors_origins: str = "http://localhost:5173"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

class BookingStatus(str, Enum):
    requested = "requested"
    quoted = "quoted"
    confirmed = "confirmed"
    searching = "searching"
    assigned = "assigned"
    completed = "completed"
    cancelled = "cancelled"

class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
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

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0", description="MtaaMove moving and delivery marketplace MVP API")
origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class QuoteRequest(BaseModel):
    pickup: str = Field(min_length=3, max_length=300)
    dropoff: str = Field(min_length=3, max_length=300)
    property_type: str = "one-bedroom"
    vehicle_type: str = "pickup"
    inventory_notes: str = ""

class BookingCreate(QuoteRequest):
    customer_name: str = Field(min_length=2, max_length=120)
    customer_phone: str = Field(min_length=7, max_length=30)
    move_date: str
    service_mode: str = "automatic"

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

# Temporary transparent estimate for the MVP. Replace with distance-based pricing using Google Routes API.
def estimate_price(payload: QuoteRequest) -> float:
    base = {"studio": 2500, "one-bedroom": 4000, "two-bedroom": 6500, "three-bedroom": 9500, "office": 7000}.get(payload.property_type, 4000)
    vehicle = {"motorbike": 800, "pickup": 0, "canter": 3500, "truck": 6500}.get(payload.vehicle_type, 0)
    stairs = 500 if any(word in payload.inventory_notes.lower() for word in ["stairs", "no lift", "third floor", "fourth floor"]) else 0
    return float(base + vehicle + stairs)

@app.get("/")
def root():
    return {"service": settings.app_name, "version": "0.1.0", "docs": "/docs"}

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

@app.post("/api/v1/quotes")
def create_quote(payload: QuoteRequest):
    return {"currency": "KES", "estimated_price": estimate_price(payload), "payment_method": "cash_on_completion", "disclaimer": "Indicative estimate only. Final price must be confirmed before the move."}

@app.post("/api/v1/bookings", response_model=BookingOut, status_code=201)
def create_booking(payload: BookingCreate, db: Session = Depends(get_db)):
    if payload.service_mode not in {"automatic", "choose_provider"}:
        raise HTTPException(status_code=422, detail="service_mode must be automatic or choose_provider")
    booking = Booking(**payload.model_dump(), estimated_price_kes=estimate_price(payload), status=BookingStatus.requested.value)
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking

@app.get("/api/v1/bookings", response_model=list[BookingOut])
def list_bookings(db: Session = Depends(get_db)):
    # MVP demonstration endpoint; production must require authentication and return only authorized records.
    return list(db.scalars(select(Booking).order_by(Booking.id.desc()).limit(100)))

@app.get("/api/v1/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking

@app.post("/api/v1/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status in {BookingStatus.completed.value, BookingStatus.cancelled.value}:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {booking.status} booking")
    booking.status = BookingStatus.cancelled.value
    db.commit()
    db.refresh(booking)
    return booking

@app.get("/api/v1/providers")
def providers():
    # Sample seed data for interface development, not verified real providers.
    return [
        {"id": "demo-1", "name": "CityLift Movers (demo)", "vehicle_type": "pickup", "rating": 4.8, "price_from_kes": 3500, "verified": False},
        {"id": "demo-2", "name": "Mtaa Cargo (demo)", "vehicle_type": "canter", "rating": 4.6, "price_from_kes": 6000, "verified": False},
        {"id": "demo-3", "name": "SwiftMove (demo)", "vehicle_type": "truck", "rating": 4.7, "price_from_kes": 9000, "verified": False},
    ]
