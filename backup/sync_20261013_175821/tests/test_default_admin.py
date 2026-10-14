from app.db.session import SessionLocal
from app.main import ensure_default_admin_user
from app.models.user import User


def test_default_admin_user_is_created():
    ensure_default_admin_user()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == 'admin').first()
        assert user is not None
        assert user.role == 'admin'
    finally:
        db.close()
