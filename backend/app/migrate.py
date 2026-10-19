"""Idempotent, additive schema migration. Back up production before running."""
from sqlalchemy import inspect, text
from app.main import Base, engine


def migrate(target_engine=engine) -> None:
    # Creates new tables only; SQLAlchemy create_all does not recreate existing tables.
    Base.metadata.create_all(bind=target_engine)
    inspector = inspect(target_engine)
    columns = {column["name"] for column in inspector.get_columns("bookings")}
    if "user_id" not in columns:
        # Existing bookings remain unowned (NULL) until manually reconciled.
        with target_engine.begin() as connection:
            connection.execute(text("ALTER TABLE bookings ADD COLUMN user_id INTEGER REFERENCES users(id)"))
    inspector = inspect(target_engine)
    indexes = {index["name"] for index in inspector.get_indexes("bookings")}
    if "ix_bookings_user_id" not in indexes:
        with target_engine.begin() as connection:
            connection.execute(text("CREATE INDEX ix_bookings_user_id ON bookings (user_id)"))
    print("MtaaMove migration complete. Existing booking owners were not guessed or backfilled.")


if __name__ == "__main__":
    migrate()
