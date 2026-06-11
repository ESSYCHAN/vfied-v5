"""Database engine + session (MIGRATION.md Step 3).

Targets SQLite in dev (zero setup) and Postgres in prod via DATABASE_URL.
The schema is written to be portable across both (UUIDs as strings, JSON via
SQLAlchemy's JSON type which maps to JSONB on Postgres).
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Dev default: local SQLite file. Prod: set DATABASE_URL=postgresql+psycopg://...
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///vfied.db")

# check_same_thread is a SQLite-only flag; harmless to omit for Postgres.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

Base = declarative_base()


def init_db():
    """Create tables. Dev convenience; prod uses migrations (Alembic) instead."""
    from db import models  # noqa: F401 — register mappers
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()
