from __future__ import annotations

from django.db import migrations


def _table_exists(schema_editor, table_name: str) -> bool:
    return table_name in set(schema_editor.connection.introspection.table_names())


def create_dmis_user_auth_m2m(apps, schema_editor) -> None:
    if not _table_exists(schema_editor, "user"):
        return

    dmis_user = apps.get_model("accounts", "DmisUser")
    for through_model in (
        dmis_user.groups.through,
        dmis_user.user_permissions.through,
    ):
        if not _table_exists(schema_editor, through_model._meta.db_table):
            schema_editor.create_model(through_model)


def drop_dmis_user_auth_m2m(apps, schema_editor) -> None:
    dmis_user = apps.get_model("accounts", "DmisUser")
    for through_model in (
        dmis_user.user_permissions.through,
        dmis_user.groups.through,
    ):
        if _table_exists(schema_editor, through_model._meta.db_table):
            schema_editor.delete_model(through_model)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_dmis_user_auth_m2m,
            reverse_code=drop_dmis_user_auth_m2m,
        ),
    ]
