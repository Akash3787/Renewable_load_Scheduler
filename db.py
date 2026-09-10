import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "scheduler.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a connection to the SQLite database with row factory enabled."""
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH) -> None:
    """Initialize the database schema from schema.sql."""
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")
    
    conn = get_connection(db_path)
    try:
        with open(schema_path, 'r') as f:
            schema_script = f.read()
        conn.executescript(schema_script)
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
