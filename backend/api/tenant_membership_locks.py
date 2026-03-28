from __future__ import annotations

from django.db import connection


_PRIMARY_TENANT_LOCK_NAMESPACE = 8412


def lock_primary_tenant_membership(cursor, *, user_id: int) -> None:
    if getattr(connection, "vendor", "") != "postgresql":
        return
    cursor.execute(
        "SELECT pg_advisory_xact_lock(%s, %s)",
        [_PRIMARY_TENANT_LOCK_NAMESPACE, int(user_id)],
    )
