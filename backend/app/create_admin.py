"""Create or promote an administrator using environment variables; never hardcode credentials."""
import os
from sqlalchemy import select
from app.main import SessionLocal, User, UserRole, password_hash


def main() -> None:
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    full_name = os.environ.get("ADMIN_FULL_NAME", "").strip()
    phone = os.environ.get("ADMIN_PHONE", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not all((email, full_name, phone, password)):
        raise SystemExit("Set ADMIN_EMAIL, ADMIN_FULL_NAME, ADMIN_PHONE and ADMIN_PASSWORD before running.")
    if len(password) < 12:
        raise SystemExit("ADMIN_PASSWORD must be at least 12 characters.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.role = UserRole.admin.value
            user.full_name = full_name
            user.phone = phone
            user.password_hash = password_hash.hash(password)
        else:
            user = User(email=email, full_name=full_name, phone=phone,
                        password_hash=password_hash.hash(password), role=UserRole.admin.value)
            db.add(user)
        db.commit()
    print(f"Administrator account configured for {email}. Keep the credentials private.")


if __name__ == "__main__":
    main()
