"""Single shared MetaData instance for all store modules.

All Table definitions across user_store, trace_store, and session_store
register on this MetaData so ``create_all()`` creates every table at once
and Alembic can autogenerate migrations for the full schema.
"""

from sqlalchemy import MetaData

shared_metadata = MetaData()
