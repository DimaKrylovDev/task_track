from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    connect_args={"server_settings": {"application_name": "krasova-primary"}},
)
session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

# Read-only workloads use a physically separate PostgreSQL hot standby.  Routing is
# explicit at the API boundary so a write transaction can never accidentally use it.
replica_engine = create_async_engine(
    settings.replica_database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    connect_args={"server_settings": {"application_name": "krasova-read-replica"}},
)
replica_session_factory = async_sessionmaker(
    replica_engine, expire_on_commit=False, autoflush=False
)
