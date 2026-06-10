from datetime import datetime
from typing import Any, Dict
import uuid

from app.database import Base
from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column


class Tenant(Base):
  """Control Plane Tenants represents isolated brands/sub-organizations."""

  __tablename__ = "tenants"

  id: Mapped[str] = mapped_column(
      String(36), primary_key=True, default=lambda: str(uuid.uuid4())
  )
  name: Mapped[str] = mapped_column(String(255), nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Brand(Base):
  """A brand context owned by a specific tenant."""

  __tablename__ = "brands"

  id: Mapped[str] = mapped_column(
      String(36), primary_key=True, default=lambda: str(uuid.uuid4())
  )
  tenant_id: Mapped[str] = mapped_column(
      String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
  )
  name: Mapped[str] = mapped_column(String(255), nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Op(Base):
  """Universal, vendor-neutral Op primitive mapping all state changes."""

  __tablename__ = "ops"

  id: Mapped[str] = mapped_column(
      String(36), primary_key=True, default=lambda: str(uuid.uuid4())
  )
  tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
  brand_id: Mapped[str] = mapped_column(
      String(36), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
  )
  domain: Mapped[str] = mapped_column(
      String(50), nullable=False
  )  # "provision", "build", "manage", "grow"
  action: Mapped[str] = mapped_column(
      String(100), nullable=False
  )  # e.g., "provision.dns_zone.create"
  params: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
  cost_estimate_millicents: Mapped[int | None] = mapped_column(
      BigInteger, nullable=True
  )
  severity: Mapped[str] = mapped_column(
      String(20), nullable=False
  )  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
  reversibility: Mapped[str] = mapped_column(
      String(20), nullable=False
  )  # "REVERSIBLE", "COMPENSATABLE", "IRREVERSIBLE"
  status: Mapped[str] = mapped_column(String(30), default="PROPOSED")
  parent_op_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
  created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditEvent(Base):
  """Append-only tamper-evident blockchain-like secure audit logging ledger."""

  __tablename__ = "audit_events"

  id: Mapped[int] = mapped_column(
      BigInteger, primary_key=True, autoincrement=True
  )
  tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
  actor: Mapped[str] = mapped_column(String(255), nullable=False)
  role: Mapped[str] = mapped_column(String(100), nullable=False)
  surface: Mapped[str] = mapped_column(String(50), nullable=False)
  op_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
  before_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
  after_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
  prev_row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
  row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
  timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
