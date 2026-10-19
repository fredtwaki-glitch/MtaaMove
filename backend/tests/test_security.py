from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, Base, get_db, User, Booking, UserSession


@pytest.fixture()
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client._test_session_factory = TestingSessionLocal
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def register(client, email="customer@example.com", **overrides):
    payload = {
        "full_name": "Test Customer",
        "email": email,
        "phone": "0712345678",
        "password": "secure-password-123",
        "password_confirmation": "secure-password-123",
    }
    payload.update(overrides)
    return client.post("/api/v1/auth/register", json=payload)


def csrf_headers(client):
    return {"X-CSRF-Token": client.cookies.get("mtaamove_csrf", "")}


def make_booking(client, pickup="Westlands, Nairobi", dropoff="Kilimani, Nairobi"):
    return client.post("/api/v1/bookings", headers=csrf_headers(client), json={
        "pickup": pickup,
        "dropoff": dropoff,
        "move_date": (date.today() + timedelta(days=3)).isoformat(),
        "property_type": "one-bedroom",
        "vehicle_type": "pickup",
        "service_mode": "automatic",
        "inventory_notes": "A few boxes",
    })


def test_anonymous_cannot_read_or_cancel_bookings(client):
    assert client.get("/api/v1/bookings").status_code == 401
    assert client.get("/api/v1/bookings/1").status_code == 401
    assert client.post("/api/v1/bookings/1/cancel").status_code == 401


def test_registration_hashes_password_and_ignores_privileged_role(client):
    response = register(client, role="admin", is_admin=True)
    assert response.status_code == 201
    assert response.json()["role"] == "customer"
    with client._test_session_factory() as db:
        user = db.scalar(select(User).where(User.email == "customer@example.com"))
        assert user.password_hash != "secure-password-123"
        assert user.password_hash.startswith("$argon2")
        assert user.role == "customer"


def test_duplicate_email_is_rejected(client):
    assert register(client).status_code == 201
    response = register(client)
    assert response.status_code == 409


def test_registration_validates_password_confirmation(client):
    response = register(client, password_confirmation="different-password-123")
    assert response.status_code == 422


def test_registration_and_authenticated_booking_creation(client):
    assert register(client).status_code == 201
    response = make_booking(client)
    assert response.status_code == 201
    assert response.json()["customer_name"] == "Test Customer"
    with client._test_session_factory() as db:
        booking = db.get(Booking, response.json()["id"])
        user = db.scalar(select(User).where(User.email == "customer@example.com"))
        assert booking.user_id == user.id


def test_customer_a_cannot_read_or_cancel_customer_b_booking(client):
    assert register(client, "a@example.com").status_code == 201
    booking = make_booking(client)
    assert booking.status_code == 201
    booking_id = booking.json()["id"]

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert register(client, "b@example.com", full_name="Customer B", phone="0798765432").status_code == 201
    assert client.get(f"/api/v1/bookings/{booking_id}").status_code == 404
    assert client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=csrf_headers(client)).status_code == 404
    own_bookings = client.get("/api/v1/bookings").json()
    assert own_bookings == []


def test_logout_revokes_session(client):
    assert register(client).status_code == 201
    assert client.get("/api/v1/auth/me").status_code == 200
    response = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_invalid_login_is_generic(client):
    response = client.post("/api/v1/auth/login", json={"email": "missing@example.com", "password": "not-the-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_booking_creation_requires_csrf_token(client):
    assert register(client).status_code == 201
    response = client.post("/api/v1/bookings", json={
        "pickup": "Westlands", "dropoff": "Kilimani",
        "move_date": (date.today() + timedelta(days=2)).isoformat(),
    })
    assert response.status_code == 403


def test_quote_and_provider_endpoints_remain_public(client):
    quote = client.post("/api/v1/quotes", json={"pickup": "Westlands", "dropoff": "Kilimani"})
    assert quote.status_code == 200
    assert quote.json()["currency"] == "KES"
    assert client.get("/api/v1/providers").status_code == 200


def test_customer_cannot_use_admin_listing(client):
    assert register(client).status_code == 201
    assert client.get("/api/v1/admin/bookings").status_code == 403


def test_customer_can_access_own_booking_and_owner_id_is_ignored(client):
    assert register(client).status_code == 201
    response = client.post("/api/v1/bookings", headers=csrf_headers(client), json={
        "pickup": "Westlands, Nairobi",
        "dropoff": "Kilimani, Nairobi",
        "move_date": (date.today() + timedelta(days=4)).isoformat(),
        "property_type": "one-bedroom",
        "vehicle_type": "pickup",
        "service_mode": "automatic",
        "user_id": 999999,
    })
    assert response.status_code == 201
    booking_id = response.json()["id"]
    assert client.get(f"/api/v1/bookings/{booking_id}").status_code == 200
    with client._test_session_factory() as db:
        booking = db.get(Booking, booking_id)
        user = db.scalar(select(User).where(User.email == "customer@example.com"))
        assert booking.user_id == user.id


def test_cancellation_is_not_repeatable(client):
    assert register(client).status_code == 201
    booking = make_booking(client)
    assert booking.status_code == 201
    booking_id = booking.json()["id"]
    assert client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=csrf_headers(client)).status_code == 200
    second = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=csrf_headers(client))
    assert second.status_code == 409


def test_admin_listing_requires_admin_role(client):
    assert register(client).status_code == 201
    assert client.get("/api/v1/admin/bookings").status_code == 403
    with client._test_session_factory() as db:
        user = db.scalar(select(User).where(User.email == "customer@example.com"))
        user.role = "admin"
        db.commit()
    assert client.get("/api/v1/admin/bookings").status_code == 200


def test_legacy_migration_adds_nullable_owner_without_deleting_rows():
    from sqlalchemy import create_engine, text, inspect
    from app.migrate import migrate

    legacy_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with legacy_engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE bookings (
                id INTEGER PRIMARY KEY,
                customer_name VARCHAR(120) NOT NULL,
                customer_phone VARCHAR(30) NOT NULL,
                pickup VARCHAR(300) NOT NULL,
                dropoff VARCHAR(300) NOT NULL,
                move_date VARCHAR(30) NOT NULL,
                property_type VARCHAR(50) NOT NULL,
                inventory_notes TEXT NOT NULL DEFAULT '',
                service_mode VARCHAR(30) NOT NULL DEFAULT 'automatic',
                vehicle_type VARCHAR(50) NOT NULL DEFAULT 'pickup',
                estimated_price_kes FLOAT NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'requested',
                created_at DATETIME
            )
        """))
        connection.execute(text("""
            INSERT INTO bookings (id, customer_name, customer_phone, pickup, dropoff, move_date,
                property_type, inventory_notes, service_mode, vehicle_type, estimated_price_kes, status)
            VALUES (1, 'Legacy Customer', '0700000000', 'A', 'B', '2026-12-01',
                'studio', '', 'automatic', 'pickup', 2500, 'requested')
        """))
    migrate(legacy_engine)
    columns = {col["name"] for col in inspect(legacy_engine).get_columns("bookings")}
    with legacy_engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM bookings")).scalar_one()
        owner = connection.execute(text("SELECT user_id FROM bookings WHERE id = 1")).scalar_one()
    assert "user_id" in columns
    assert count == 1
    assert owner is None
    legacy_engine.dispose()


def test_successful_login_creates_authenticated_session(client):
    assert register(client).status_code == 201
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    response = client.post("/api/v1/auth/login", json={
        "email": "customer@example.com",
        "password": "secure-password-123",
    })
    assert response.status_code == 200
    assert response.json()["email"] == "customer@example.com"
    assert client.get("/api/v1/auth/me").status_code == 200


def test_password_change_revokes_sessions_and_new_password_works(client):
    assert register(client).status_code == 201
    response = client.post("/api/v1/auth/change-password", headers=csrf_headers(client), json={
        "current_password": "secure-password-123",
        "new_password": "a-different-password-456",
    })
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    login = client.post("/api/v1/auth/login", json={
        "email": "customer@example.com",
        "password": "a-different-password-456",
    })
    assert login.status_code == 200


def test_invalid_vehicle_and_past_date_are_rejected(client):
    assert register(client).status_code == 201
    bad_vehicle = client.post("/api/v1/bookings", headers=csrf_headers(client), json={
        "pickup": "Westlands, Nairobi", "dropoff": "Kilimani, Nairobi",
        "move_date": (date.today() + timedelta(days=2)).isoformat(),
        "property_type": "one-bedroom", "vehicle_type": "spaceship",
    })
    assert bad_vehicle.status_code == 422
    past_date = client.post("/api/v1/bookings", headers=csrf_headers(client), json={
        "pickup": "Westlands, Nairobi", "dropoff": "Kilimani, Nairobi",
        "move_date": (date.today() - timedelta(days=1)).isoformat(),
        "property_type": "one-bedroom", "vehicle_type": "pickup",
    })
    assert past_date.status_code == 422
