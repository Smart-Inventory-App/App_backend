from sqlalchemy import Column, String, DateTime, func
from app.core.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(String, primary_key=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
