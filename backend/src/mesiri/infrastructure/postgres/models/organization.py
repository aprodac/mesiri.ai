import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID

from .base import Base


class DeploymentType(str, enum.Enum):
    SAAS = "SaaS"
    ON_PREM = "On-Prem"


class OrganizationStatus(str, enum.Enum):
    # Lowercase, like every other status in the database (migration 0463).
    ACTIVE = "active"
    SUSPENDED = "suspended"

    @classmethod
    def _missing_(cls, value: object) -> "OrganizationStatus | None":
        # Accept "Active", " ACTIVE " etc.: rows written before 0463, or by
        # an older build after a rollback, must still read (and validate in
        # API responses) rather than raise.
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in cls:
                if member.value == normalized:
                    return member
        return None


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True, nullable=False)
    deployment_type: Column = Column(Enum(DeploymentType), nullable=False)
    db_route = Column(String, nullable=False)
    # A plain string, not Enum(OrganizationStatus): the column is VARCHAR in
    # the database, older rows (or an older build after a rollback) may hold
    # "Active", and an Enum column raises on any value it doesn't know.
    # Writers pass OrganizationStatus.<X>.value.
    status = Column(String, nullable=False)

    code = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    primary_contact = Column(String, nullable=True)
    timezone = Column(String, nullable=False, server_default="UTC")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
