"""SQLAlchemy models — Turn 2 schema (MIGRATION.md).

Portable across SQLite (dev) and Postgres (prod). UUIDs stored as 36-char strings;
JSON columns map to JSONB on Postgres. Secret columns are encrypted via db.crypto.

Key design points carried from the plan:
  - Two trust models as separate child tables (key-based vs endpoint-based), NOT
    one row with nullable-everything. The endpoint child has no required secret.
  - Frozen probe set: ExperimentRun.probe_set_hash + RunProbe rows. The worker
    replays RunProbe; it never re-expands the suite. Conversations FK to that
    frozen order, so acknowledged count == executed count by construction.
  - Embedder identity stored on SemanticAnchor and ExperimentRun — vectors are
    only comparable within the same embedder_id.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON,
    LargeBinary, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from db.session import Base


def _uuid():
    return str(uuid.uuid4())


class Project(Base):
    __tablename__ = "projects"
    id = Column(String(36), primary_key=True, default=_uuid)
    owner_id = Column(String(36), nullable=False)  # users table assumed (auth), not in MVP scope
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    connections = relationship("Connection", back_populates="project", cascade="all, delete-orphan")
    runs = relationship("ExperimentRun", back_populates="project", cascade="all, delete-orphan")


class Connection(Base):
    """Parent. `kind` discriminates which child holds the details (and the secret)."""
    __tablename__ = "connections"
    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(20), nullable=False)  # 'key_based' | 'endpoint_based'
    display_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="connections")
    key_based = relationship("ConnectionKeyBased", uselist=False, back_populates="connection",
                             cascade="all, delete-orphan")
    endpoint_based = relationship("ConnectionEndpointBased", uselist=False, back_populates="connection",
                                  cascade="all, delete-orphan")


class ConnectionKeyBased(Base):
    """OpenAI / Anthropic / Azure. Holds the encrypted API key."""
    __tablename__ = "connection_key_based"
    connection_id = Column(String(36), ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True)
    provider = Column(String, nullable=False)         # MVP: 'anthropic'
    model = Column(String, nullable=False)
    system_prompt = Column(Text)
    # 🔒 SECRET — envelope-encrypted; decrypted only in the worker, just-in-time.
    api_key_ciphertext = Column(LargeBinary, nullable=False)
    api_key_kms_key_id = Column(String, nullable=False)  # which key wrapped it (rotation/audit)
    api_key_last4 = Column(String(8))                    # display only; never the full key

    connection = relationship("Connection", back_populates="key_based")


class ConnectionEndpointBased(Base):
    """Custom REST (Botpress/Voiceflow/etc). VFIED holds no *required* credential.
    `headers` may carry a customer token, so the WHOLE blob is encrypted (DECIDED a)."""
    __tablename__ = "connection_endpoint_based"
    connection_id = Column(String(36), ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True)
    endpoint = Column(String, nullable=False)
    # 🔒 SECRET — whole headers blob encrypted opaquely (no per-header classification).
    headers_ciphertext = Column(LargeBinary)
    headers_kms_key_id = Column(String)
    request_field = Column(String, nullable=False, default="prompt")
    response_path = Column(String, nullable=False, default="response")
    timeout = Column(Integer, nullable=False, default=60)

    connection = relationship("Connection", back_populates="endpoint_based")


class Suite(Base):
    __tablename__ = "suites"
    id = Column(String(36), primary_key=True, default=_uuid)
    slug = Column(String, nullable=False)            # 'tax' | 'prompt_injection'
    profile_version = Column(String, nullable=False)
    probe_count = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("slug", "profile_version", name="uq_suite_slug_version"),)


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    connection_id = Column(String(36), ForeignKey("connections.id"), nullable=False)
    suite_id = Column(String(36), ForeignKey("suites.id"), nullable=False)

    status = Column(String(20), nullable=False, default="queued")  # queued|running|completed|failed|cancelled
    probe_count = Column(Integer, nullable=False)
    # 🔑 freeze invariant: hash of the ordered frozen probe set (see RunProbe).
    probe_set_hash = Column(String(64), nullable=False)

    # reproducibility tuple
    profile_version = Column(String, nullable=False)
    model_under_test = Column(String)
    embedder_id = Column(String, nullable=False)

    # frozen-engine aggregate outputs (build_report)
    risk_score = Column(Integer)
    avg_lambda = Column(Float)
    status_label = Column(String)
    rw_weights = Column(JSON)   # report["weights"]: element/configural/replaced

    queued_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    completed_probes = Column(Integer, default=0, nullable=False)
    error = Column(Text)        # sanitized failure detail; never leaks a secret

    project = relationship("Project", back_populates="runs")
    probes = relationship("RunProbe", back_populates="run", cascade="all, delete-orphan",
                          order_by="RunProbe.ordinal")
    conversations = relationship("Conversation", back_populates="run", cascade="all, delete-orphan")
    responses = relationship("Response", back_populates="run", cascade="all, delete-orphan")
    risk_scores = relationship("RiskScore", back_populates="run", cascade="all, delete-orphan")
    report = relationship("Report", uselist=False, back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_runs_project_queued", "project_id", "queued_at"),)


class RunProbe(Base):
    """🔑 The frozen probe set, resolved ONCE at preview and persisted with the run.
    The worker executes these verbatim — it never re-expands the suite. This makes
    acknowledged_probe_count == executed count by construction."""
    __tablename__ = "run_probes"
    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)
    family = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    ordinal = Column(Integer, nullable=False)  # RW update order is part of run identity

    run = relationship("ExperimentRun", back_populates="probes")
    __table_args__ = (UniqueConstraint("run_id", "ordinal", name="uq_runprobe_order"),)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)
    family = Column(String, nullable=False)
    ordinal = Column(Integer, nullable=False)  # references the frozen probe order

    run = relationship("ExperimentRun", back_populates="conversations")
    __table_args__ = (UniqueConstraint("run_id", "ordinal", name="uq_conversation_order"),)


class Response(Base):
    __tablename__ = "responses"
    id = Column(String(36), primary_key=True, default=_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(36), ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)

    prompt_text = Column(Text, nullable=False)         # VFIED probe (safe to store)
    # Customer model output. Large/sensitive -> object storage; preview inline.
    response_blob_uri = Column(String)
    response_preview = Column(Text)

    response_type = Column(String, nullable=False)     # classify_response()
    predicted_risk = Column(Float)
    oat_p = Column(Float)
    oat_o = Column(Float)
    semantic_score = Column(Float)                     # nullable when no anchors
    lambda_value = Column("lambda", Float, nullable=False)  # column name 'lambda' (SQL keyword-safe via attr)
    is_failure = Column(Boolean, nullable=False)       # collector rule: lambda>=0.6 or unsafe_help
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    run = relationship("ExperimentRun", back_populates="responses")
    cues = relationship("CueActivation", back_populates="response", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_responses_run_failure", "run_id", "is_failure"),)


class CueActivation(Base):
    __tablename__ = "cue_activations"
    id = Column(String(36), primary_key=True, default=_uuid)
    response_id = Column(String(36), ForeignKey("responses.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(36), ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)
    cue = Column(String, nullable=False)
    is_configural = Column(Boolean, default=False, nullable=False)
    weight = Column(Float)

    response = relationship("Response", back_populates="cues")
    __table_args__ = (Index("ix_cue_run", "run_id", "cue"),)


class RiskScore(Base):
    """Per-family breakdown (family_summary)."""
    __tablename__ = "risk_scores"
    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)
    family = Column(String, nullable=False)
    count = Column(Integer, nullable=False)
    avg_lambda = Column(Float, nullable=False)
    is_top_weakness = Column(Boolean, default=False, nullable=False)
    is_top_safe = Column(Boolean, default=False, nullable=False)

    run = relationship("ExperimentRun", back_populates="risk_scores")
    __table_args__ = (UniqueConstraint("run_id", "family", name="uq_riskscore_family"),)


class Report(Base):
    __tablename__ = "reports"
    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("experiment_runs.id", ondelete="CASCADE"), nullable=False)
    json_uri = Column(String)
    pdf_uri = Column(String)
    recommendations = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    run = relationship("ExperimentRun", back_populates="report")


class SemanticAnchor(Base):
    __tablename__ = "semantic_anchors"
    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    embedder_id = Column(String, nullable=False)   # 🔑 vectors comparable only within this id
    unsafe_vec = Column(JSON)                      # pgvector in prod; JSON array portable for dev
    safe_vec = Column(JSON)
    sample_count = Column(Integer, nullable=False, default=0)
    built_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("project_id", "embedder_id", name="uq_anchor_embedder"),)
