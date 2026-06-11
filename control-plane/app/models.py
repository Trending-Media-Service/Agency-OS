"""Control-plane system of record (ARCHITECTURE.md §8).

SQLite for dev/tests; Cloud SQL Postgres in deployment. Row-level security is a
Postgres migration (Slice 1 issue) — every table already carries tenant_id so
RLS bolts on without schema change. Secrets NEVER live here; `connections`
stores only references into the brand project's Secret Manager.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(120))
    hosting_tier: Mapped[str] = mapped_column(String(16), default="shared")  # shared|dedicated
    gcp_project: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=_now)


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = mapped_column(default=_now)


class OpRow(Base):
    __tablename__ = "ops"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    domain: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(24), index=True)
    impact: Mapped[int] = mapped_column(Integer)
    reversibility: Mapped[str] = mapped_column(String(16))
    statutory: Mapped[bool] = mapped_column(default=False)
    cost_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    preview_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_op_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sequence_order: Mapped[int] = mapped_column(Integer, default=0)
    idem_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_now, onupdate=_now)


class OpTrace(Base):
    """Execution trace (§4.5): every gate, call, retry, with reasons."""
    __tablename__ = "op_traces"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    op_id: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[dt.datetime] = mapped_column(default=_now)
    kind: Mapped[str] = mapped_column(String(40))  # transition|gate|adapter_call|retry|note
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    op_id: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(60))
    surface: Mapped[str] = mapped_column(String(24))  # whatsapp|web|auto
    decision: Mapped[str] = mapped_column(String(16))  # approve|reject|modify
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts: Mapped[dt.datetime] = mapped_column(default=_now)


class AuditEvent(Base):
    """Append-only, hash-chained (§4.5). Never UPDATE, never DELETE."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40))  # iso8601, part of the hash preimage
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120))
    op_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class TrustEvent(Base):
    __tablename__ = "trust_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    domain: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(40))  # verified_success|override|verify_failure|rejection
    base_delta: Mapped[float] = mapped_column()
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # override reasons are gold (§4.4)
    ts: Mapped[dt.datetime] = mapped_column(default=_now)


class TrustSnapshot(Base):
    __tablename__ = "trust_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    domain: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column()
    tier: Mapped[int] = mapped_column(Integer)
    ts: Mapped[dt.datetime] = mapped_column(default=_now)


class CostEntry(Base):
    """Per-Op cost attribution from day one (§2.6)."""
    __tablename__ = "cost_ledger"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    op_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))  # llm_tokens|api_call|gcp_resource
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[dt.datetime] = mapped_column(default=_now)


class OutboxItem(Base):
    """Transactional outbox (§4.2). Written in the same txn as APPROVED."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    op_id: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)  # PENDING|IN_FLIGHT|DONE|DEAD
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[dt.datetime] = mapped_column(default=_now)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=_now)


class Connection(Base):
    """Manage-pillar credential metadata. secret_ref points into the BRAND
    project's Secret Manager — the secret itself never touches this DB (§3)."""
    __tablename__ = "connections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(16), default="read")  # read|write
    secret_ref: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(default=_now)
class ProcessedWebhookMessage(Base):
    __tablename__ = "processed_webhook_messages"
    message_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    processed_at: Mapped[dt.datetime] = mapped_column(default=_now)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[float] = mapped_column()
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    attributed_campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=_now)


Index("ix_ops_tenant_state", OpRow.tenant_id, OpRow.state)


def make_engine(url: str = "sqlite:///./agencyos.db"):
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # one shared in-memory DB across connections
        return create_engine(url, future=True, **kwargs)
    return create_engine(url, future=True)


def make_session_factory(engine):
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)
