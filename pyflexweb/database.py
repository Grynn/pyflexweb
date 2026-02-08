"""Database module for storing tokens, queries, and download history."""

import os
import sqlite3
from datetime import datetime, timedelta

import platformdirs


class FlexDatabase:
    """Manages the local database for tokens, queries, and download history."""

    DB_VERSION = 4  # Increment when schema changes

    def __init__(self, db_dir: str = None):
        self.db_dir = db_dir if db_dir is not None else platformdirs.user_data_dir("pyflexweb")
        os.makedirs(self.db_dir, exist_ok=True)
        self.db_path = os.path.join(self.db_dir, "status.db")
        self.conn = self._init_db()

    def get_db_path(self) -> str:
        """Return the path to the database file."""
        return self.db_path

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
        )

        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS queries (
            id TEXT PRIMARY KEY,
            name TEXT,
            added_on DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
        )

        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY,
            query_id TEXT,
            status TEXT,
            requested_at DATETIME,
            completed_at DATETIME,
            last_updated DATETIME,
            output_path TEXT,
            FOREIGN KEY (query_id) REFERENCES queries(id)
        )
        """
        )

        self._check_migration(conn)
        return conn

    def _check_migration(self, conn: sqlite3.Connection) -> None:
        """Check if database needs migration and perform if needed."""
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM config WHERE key = 'db_version' LIMIT 1")
        result = cursor.fetchone()
        current_version = int(result[0]) if result else 0

        if current_version >= self.DB_VERSION:
            return

        if current_version < 1:
            try:
                cursor.execute("ALTER TABLE requests ADD COLUMN last_updated DATETIME")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        if current_version < 2:
            cursor.execute("PRAGMA table_info(queries)")
            columns = cursor.fetchall()
            has_report_type = any(col[1] == "report_type" for col in columns)

            if has_report_type:
                cursor.execute("SELECT id, name FROM queries")
                queries = cursor.fetchall()
                cursor.execute("DROP TABLE queries")
                cursor.execute(
                    """
                CREATE TABLE queries (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    added_on DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
                )
                for query_id, name in queries:
                    cursor.execute("INSERT INTO queries (id, name) VALUES (?, ?)", (query_id, name))

        if current_version < 3:
            try:
                cursor.execute("ALTER TABLE queries ADD COLUMN min_interval INTEGER")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        if current_version < 4:
            try:
                cursor.execute("ALTER TABLE queries ADD COLUMN type TEXT DEFAULT 'activity'")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        cursor.execute(
            "INSERT OR REPLACE INTO config VALUES (?, ?)",
            ("db_version", str(self.DB_VERSION)),
        )
        conn.commit()

    # --- Token ---

    def set_token(self, token: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO config VALUES (?, ?)", ("token", token))
        self.conn.commit()

    def get_token(self) -> str | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", ("token",))
        result = cursor.fetchone()
        return result[0] if result else None

    def unset_token(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM config WHERE key = ?", ("token",))
        self.conn.commit()

    # --- Config ---

    def set_config(self, key: str, value: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def get_config(self, key: str, default: str = None) -> str:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else default

    def list_config(self) -> dict:
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM config WHERE key != 'token' AND key != 'db_version' ORDER BY key")
        return dict(cursor.fetchall())

    def unset_config(self, key: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM config WHERE key = ?", (key,))
        self.conn.commit()
        return cursor.rowcount > 0

    # --- Queries ---

    def add_query(self, query_id: str, name: str, query_type: str = "activity", min_interval: int | None = None) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO queries (id, name, type, min_interval) VALUES (?, ?, ?, ?)",
            (query_id, name, query_type, min_interval),
        )
        self.conn.commit()

    def set_query_interval(self, query_id: str, min_interval: int | None) -> bool:
        """Set the minimum download interval (hours) for a query. None to use type default."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE queries SET min_interval = ? WHERE id = ?", (min_interval, query_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def remove_query(self, query_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM queries WHERE id = ?", (query_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def rename_query(self, query_id: str, new_name: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("UPDATE queries SET name = ? WHERE id = ?", (new_name, query_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def list_queries(self) -> list[tuple[str, str]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name FROM queries ORDER BY added_on")
        return cursor.fetchall()

    def get_query_info(self, query_id: str) -> dict | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, type, min_interval FROM queries WHERE id = ?", (query_id,))
        result = cursor.fetchone()
        if not result:
            return None
        return {"id": result[0], "name": result[1], "type": result[2] or "activity", "min_interval": result[3]}

    def get_all_queries_with_status(self) -> list[dict]:
        """Get all queries with their latest download status."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, type, min_interval FROM queries ORDER BY added_on")
        queries = cursor.fetchall()

        result = []
        for query_id, name, query_type, min_interval in queries:
            query_info = {
                "id": query_id,
                "name": name,
                "type": query_type or "activity",
                "min_interval": min_interval,
                "latest_request": None,
            }
            latest = self.get_latest_request(query_id)
            if latest:
                query_info["latest_request"] = latest
            result.append(query_info)

        return result

    # --- Download history (internal) ---

    def add_request(self, request_id: str, query_id: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO requests (request_id, query_id, status, requested_at) VALUES (?, ?, ?, ?)",
            (request_id, query_id, "pending", datetime.now().isoformat()),
        )
        self.conn.commit()

    def update_request_status(self, request_id: str, status: str, output_path: str | None = None) -> None:
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        if status == "completed":
            cursor.execute(
                "UPDATE requests SET status = ?, completed_at = ?, output_path = ?, last_updated = ? WHERE request_id = ?",
                (status, now, output_path, now, request_id),
            )
        else:
            cursor.execute(
                "UPDATE requests SET status = ?, last_updated = ? WHERE request_id = ?",
                (status, now, request_id),
            )
        self.conn.commit()

    def get_request_info(self, request_id: str) -> dict | None:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT request_id, query_id, status, requested_at, completed_at, output_path FROM requests WHERE request_id = ?",
            (request_id,),
        )
        result = cursor.fetchone()
        if not result:
            return None
        return {
            "request_id": result[0],
            "query_id": result[1],
            "status": result[2],
            "requested_at": result[3],
            "completed_at": result[4],
            "output_path": result[5],
        }

    def get_latest_request(self, query_id: str) -> dict | None:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT request_id FROM requests WHERE query_id = ? ORDER BY requested_at DESC LIMIT 1",
            (query_id,),
        )
        result = cursor.fetchone()
        if not result:
            return None
        return self.get_request_info(result[0])

    def get_queries_needing_download(self, type_defaults: dict[str, int]) -> list[dict]:
        """Get queries that haven't been downloaded within their effective interval.

        Resolution: per-query min_interval > type-based default from type_defaults.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, type, min_interval FROM queries")
        all_queries = cursor.fetchall()

        result = []
        for query_id, name, query_type, min_interval in all_queries:
            query_type = query_type or "activity"
            hours = min_interval if min_interval is not None else type_defaults.get(query_type, 6)
            cutoff_time = (datetime.now() - timedelta(hours=hours)).isoformat()

            cursor.execute(
                """
                SELECT r.request_id FROM requests r
                WHERE r.query_id = ?
                  AND r.status = 'completed'
                  AND (r.last_updated > ? OR r.completed_at > ?)
                ORDER BY r.last_updated DESC
                LIMIT 1
            """,
                (query_id, cutoff_time, cutoff_time),
            )

            if not cursor.fetchone():
                result.append({"id": query_id, "name": name, "type": query_type, "min_interval": min_interval})

        return result

    def close(self) -> None:
        self.conn.close()
