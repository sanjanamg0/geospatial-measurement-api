"""Optional PostGIS support.

On PostgreSQL this tries to enable the PostGIS extension and adds a ``geom`` geometry column
with a GiST index to the features table. On any other database, or when PostGIS is not
available, it does nothing and the API keeps working with bounding-box filtering.
"""
import logging

from django.db import DatabaseError, migrations, transaction

log = logging.getLogger(__name__)


def enable_postgis(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    table = apps.get_model("measurements", "Feature")._meta.db_table
    try:
        with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS geom geometry(Geometry)")
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {table}_geom_gist ON {table} USING GIST (geom)"
            )
    except DatabaseError as exc:  # extension not installed or no permission to create it
        log.warning("PostGIS not enabled, using bounding-box filtering only: %s", exc)


class Migration(migrations.Migration):
    dependencies = [("measurements", "0003_owner_and_bbox")]

    operations = [migrations.RunPython(enable_postgis, migrations.RunPython.noop)]
