from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models so Alembic can detect them
from app.models.user import User  # noqa: F401, E402
from app.models.task import Task  # noqa: F401, E402
from app.models.comment import Comment  # noqa: F401, E402
from app.models.attachment import Attachment  # noqa: F401, E402
