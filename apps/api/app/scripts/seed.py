from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import db_session
from app.models import User


def main() -> None:
    """
    Basic user seeding script.
    
    Note: Manufacturing data (machines, materials, tools) should be seeded
    via Alembic migration 20250817_1900_task_28 (Task 2.8).
    
    This script only handles basic user accounts for development.
    """
    with db_session() as session:
        assert isinstance(session, Session)
        if not session.query(User).filter_by(email="dev@local").first():
            user = User(email="dev@local", role="engineer", locale="tr")
            session.add(user)
            session.commit()
            print("[seed] dev@local eklendi")
        else:
            print("[seed] dev@local mevcut")
    
    print("\nFor manufacturing data (machines, materials, tools),")
    print("run: alembic upgrade head")
    print("This will apply Task 2.8 seed data migration.")


if __name__ == "__main__":
    main()


