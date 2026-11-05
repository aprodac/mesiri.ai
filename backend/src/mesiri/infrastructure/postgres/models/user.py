import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID

from .base import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"
    SITE_MANAGER = "site_manager"
    WORKER = "worker"


class UserModel(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role: Column = Column(Enum(UserRole), nullable=False)

    whatsapp_number = Column(String, unique=True, index=True, nullable=True)
    # Added by migration 0060_users_add_status_sites_access
    status = Column(String, nullable=False, server_default="active")
    access_policy = Column(JSON, nullable=True)
    # Added by migration 0501 (WA-169): the language WhatsApp replies are always in; NULL = follow each message.
    reply_language = Column(String(20), nullable=True)
    # WA-246: show what was heard above a voice note's reply; NULL follows the company's voice_transcript setting.
    voice_transcript = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
