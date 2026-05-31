import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.store import Store


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, server_default="{}")

    stores: Mapped[list["Store"]] = relationship(back_populates="tenant")
