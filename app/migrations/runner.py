from pathlib import Path
from alembic import op
import traceback



def run_sql(name: str) -> str:
    # __file__ = migrations/versions/<revision_file>.py
    version_dir = Path(__file__).parent               # migrations/versions
    sql_path = version_dir / "versions/sql" / name      # migrations/sql/<name>

    # Normalize relative path
    print( "Running SQL file:", sql_path )
    sql_path = sql_path.resolve()

    return sql_path.read_text(encoding="utf-8")



def trigger(file_name: str):
    
    try:
        sql = run_sql(file_name)
        print("Executing SQL...")
        op.execute(sql)

    except Exception as e:
        print("Migration failed while executing SQL file.")
        print("File: ",file_name)
        print("Error:", e)
        print("Stacktrace:")
        # traceback.print_exc()

        # Re-raise so Alembic marks migration as FAILED
        raise