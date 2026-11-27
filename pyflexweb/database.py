"""Database module for storing tokens, queries, and download history."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta

import platformdirs

from .locks import acquire_file_lock, release_file_lock

PLACEHOLDER_ACCOUNT_ID = "__default__"

# Format of every UTC timestamp written by schema v7 (accounts.token_expires_at,
# request_errors.occurred_at). Fixed width, so string order is time order.
UTC_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# request_errors rows older than this are pruned (per query) on each insert.
REQUEST_ERRORS_RETENTION_DAYS = 90

REQUEST_ERROR_STAGES = ("send", "get", "skipped")
REQUEST_ERROR_KINDS = ("token", "rate_limit", "not_ready", "other")

# Schema v7 contract: external monitors read this table from a copy of status.db.
# Keep the column names and value sets stable.
REQUEST_ERRORS_DDL = """
CREATE TABLE IF NOT EXISTS request_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT NOT NULL,
    account_id TEXT,
    occurred_at TEXT NOT NULL,  -- ISO-8601 UTC, YYYY-MM-DDTHH:MM:SSZ
    stage TEXT NOT NULL,        -- 'send' | 'get' | 'skipped'
    error_code TEXT,            -- IBKR Flex ErrorCode, NULL for network/parse failures
    error_message TEXT,
    kind TEXT NOT NULL          -- 'token' | 'rate_limit' | 'not_ready' | 'other'
)
"""
REQUEST_ERRORS_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_request_errors_query_time ON request_errors (query_id, occurred_at)"


# Serialises "read db_version -> migrate" across processes. A file of its own,
# so a `download` (which holds download.lock) can never deadlock on it.
MIGRATE_LOCK_FILENAME = "migrate.lock"
MIGRATE_LOCK_WAIT_SECONDS = 60
MIGRATE_LOCK_POLL_SECONDS = 0.1


class MigrationError(RuntimeError):
    """The schema migration could not run; status.db was left unchanged."""


def resolve_data_dir() -> str:
    """Resolve pyflexweb data directory with fallback chain.

    Resolution order:
    1. PYFLEXWEB_DATA_DIR env var (explicit override)
    2. platformdirs.user_data_dir (if directory exists — user override)
    3. platformdirs.site_data_dir (system-wide shared default)
    """
    env_dir = os.getenv("PYFLEXWEB_DATA_DIR")
    if env_dir:
        return env_dir
    user_dir = platformdirs.user_data_dir("pyflexweb")
    if os.path.isdir(user_dir):
        return user_dir
    return platformdirs.site_data_dir("pyflexweb")


class FlexDatabase:
    """Manages the local database for tokens, queries, and download history."""

    DB_VERSION = 7  # Increment when schema changes

    def __init__(self, db_dir: str | None = None):
        self.db_dir = db_dir if db_dir is not None else resolve_data_dir()
        os.makedirs(self.db_dir, exist_ok=True)
        self.db_path = os.path.join(self.db_dir, "status.db")
        # A brand-new file holds nothing worth a pre-migration backup.
        self._created_now = not os.path.exists(self.db_path)
        self.conn = self._init_db()

    def get_db_path(self) -> str:
        """Return the path to the database file."""
        return self.db_path

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
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
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            name TEXT,
            token TEXT NOT NULL,
            added_on DATETIME DEFAULT CURRENT_TIMESTAMP,
            token_expires_at TEXT
        )
        """
        )

        # NOTE: This CREATE TABLE only runs on a *fresh* database (version 0).
        # For existing DBs the migration path in _check_migration recreates the
        # table with the correct NOT NULL constraint.  New DBs include it here.
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS queries (
            id TEXT PRIMARY KEY,
            name TEXT,
            added_on DATETIME DEFAULT CURRENT_TIMESTAMP,
            min_interval INTEGER,
            type TEXT DEFAULT 'activity',
            account_id TEXT NOT NULL REFERENCES accounts(id)
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

    @staticmethod
    def _read_version(conn: sqlite3.Connection) -> int:
        result = conn.execute("SELECT value FROM config WHERE key = 'db_version' LIMIT 1").fetchone()
        return int(result[0]) if result else 0

    def _check_migration(self, conn: sqlite3.Connection) -> None:
        """Migrate the schema if needed, one process at a time.

        An up-to-date database takes no lock. Otherwise an exclusive flock on
        migrate.lock is taken (waiting up to MIGRATE_LOCK_WAIT_SECONDS), the
        version is re-read (another process may have just migrated), a
        WAL-complete backup is written, and only then is the schema changed.
        """
        if self._read_version(conn) >= self.DB_VERSION:
            return

        lock_path = os.path.join(self.db_dir, MIGRATE_LOCK_FILENAME)
        lock_fd = acquire_file_lock(lock_path, MIGRATE_LOCK_WAIT_SECONDS, MIGRATE_LOCK_POLL_SECONDS)
        if lock_fd is None:
            raise MigrationError(
                f"Timed out after {MIGRATE_LOCK_WAIT_SECONDS}s waiting for {lock_path}: another pyflexweb process "
                "is migrating status.db. Try again when it has finished."
            )
        try:
            current_version = self._read_version(conn)
            if current_version >= self.DB_VERSION:
                return
            if not self._created_now:
                self._backup_before_migration(conn, current_version)
            self._migrate(conn, current_version)
        finally:
            release_file_lock(lock_fd)

    def _backup_path(self, version: int) -> str:
        """status.db.v<N>.bak, or a timestamped name if that already exists (never overwrite a backup)."""
        path = f"{self.db_path}.v{version}.bak"
        if not os.path.exists(path):
            return path
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = f"{self.db_path}.v{version}.{stamp}.bak"
        n = 1
        while os.path.exists(path):
            n += 1
            path = f"{self.db_path}.v{version}.{stamp}-{n}.bak"
        return path

    def _backup_before_migration(self, conn: sqlite3.Connection, version: int) -> None:
        """Write a backup with SQLite's backup API (includes rows still in the WAL).

        Any failure raises MigrationError before the schema is touched.
        """
        backup_path = self._backup_path(version)
        try:
            dst = sqlite3.connect(backup_path)
            try:
                conn.backup(dst)
            finally:
                dst.close()
        except (sqlite3.Error, OSError) as e:
            try:
                if os.path.exists(backup_path):
                    os.remove(backup_path)
            except OSError:
                pass
            raise MigrationError(
                f"Could not write the pre-migration backup {backup_path}: {e}. status.db was not changed (still schema v{version})."
            ) from e

    def _migrate(self, conn: sqlite3.Connection, current_version: int) -> None:
        """Run every migration step after current_version. Caller holds the migrate lock."""
        cursor = conn.cursor()

        # Temporarily disable FK enforcement so table renames/drops
        # don't trigger foreign-key violations during migration.
        conn.execute("PRAGMA foreign_keys = OFF")

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

        if current_version < 5:
            # Create accounts table (if not already created by _init_db above)
            cursor.execute(
                """
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT,
                token TEXT NOT NULL,
                added_on DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
            )
            conn.commit()

            # Add nullable account_id column to queries (temporary; made NOT NULL in v6)
            try:
                cursor.execute("ALTER TABLE queries ADD COLUMN account_id TEXT REFERENCES accounts(id)")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        if current_version < 6:
            # Check the current queries schema to decide if we need to rebuild.
            cursor.execute("PRAGMA table_info(queries)")
            col_info = {row[1]: row for row in cursor.fetchall()}
            needs_rebuild = (
                "account_id" not in col_info  # column missing entirely
                or col_info["account_id"][3] == 0  # column exists but is nullable
            )

            if needs_rebuild:
                # If there is a legacy global token, create a placeholder account.
                cursor.execute("SELECT value FROM config WHERE key = 'token'")
                token_row = cursor.fetchone()
                global_token = token_row[0] if token_row else None

                # Fetch existing rows before rebuild to check for orphans
                has_account_col = "account_id" in col_info
                if has_account_col:
                    cursor.execute("SELECT id, name, added_on, min_interval, type, account_id FROM queries")
                else:
                    cursor.execute("SELECT id, name, added_on, min_interval, type FROM queries")
                existing_queries = cursor.fetchall()

                # Determine whether any queries will need a placeholder account
                has_orphans = any((row[5] if has_account_col and len(row) > 5 else None) is None for row in existing_queries)

                if global_token or has_orphans:
                    # Use the global token when available; otherwise fall back to
                    # a marker so queries are preserved (the user can update it later).
                    placeholder_token = global_token or "__MISSING__"
                    cursor.execute(
                        "INSERT OR IGNORE INTO accounts (id, name, token) VALUES (?, NULL, ?)",
                        (PLACEHOLDER_ACCOUNT_ID, placeholder_token),
                    )
                    conn.commit()

                cursor.execute("SELECT 1 FROM accounts WHERE id = ?", (PLACEHOLDER_ACCOUNT_ID,)).fetchone()

                # Recreate table with NOT NULL constraint (SQLite requires full rebuild)
                cursor.execute("DROP TABLE IF EXISTS queries_old")
                cursor.execute("ALTER TABLE queries RENAME TO queries_old")
                cursor.execute(
                    """
                CREATE TABLE queries (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    added_on DATETIME DEFAULT CURRENT_TIMESTAMP,
                    min_interval INTEGER,
                    type TEXT DEFAULT 'activity',
                    account_id TEXT NOT NULL REFERENCES accounts(id)
                )
                """
                )

                for row in existing_queries:
                    qid, qname, added_on, min_interval, qtype = row[:5]
                    account_id = row[5] if has_account_col else None
                    if account_id is None:
                        account_id = PLACEHOLDER_ACCOUNT_ID
                    cursor.execute(
                        "INSERT INTO queries (id, name, added_on, min_interval, type, account_id) VALUES (?, ?, ?, ?, ?, ?)",
                        (qid, qname, added_on, min_interval, qtype or "activity", account_id),
                    )

                cursor.execute("DROP TABLE queries_old")
                conn.commit()

        if current_version < 7:
            # Token expiry record + per-query error log (idempotent: column added
            # only if missing; table/index use IF NOT EXISTS).
            cursor.execute("PRAGMA table_info(accounts)")
            if "token_expires_at" not in {row[1] for row in cursor.fetchall()}:
                cursor.execute("ALTER TABLE accounts ADD COLUMN token_expires_at TEXT")
            cursor.execute(REQUEST_ERRORS_DDL)
            cursor.execute(REQUEST_ERRORS_INDEX_DDL)
            conn.commit()

        cursor.execute(
            "INSERT OR REPLACE INTO config VALUES (?, ?)",
            ("db_version", str(self.DB_VERSION)),
        )
        conn.commit()

        # Re-enable FK enforcement after migration is complete.
        conn.execute("PRAGMA foreign_keys = ON")

    def update_account(self, account_id: str, new_id: str | None = None, new_name: str | None = None) -> bool:
        """Update an account's ID and/or name.

        Returns True if the account was found and updated, False if not found.
        When changing the ID, updates all query FK references as well.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,))
        if not cursor.fetchone():
            return False

        if new_id and new_id != account_id:
            # Temporarily disable FK so we can re-point queries
            self.conn.execute("PRAGMA foreign_keys = OFF")
            cursor.execute("UPDATE accounts SET id = ? WHERE id = ?", (new_id, account_id))
            cursor.execute("UPDATE queries SET account_id = ? WHERE account_id = ?", (new_id, account_id))
            self.conn.commit()
            self.conn.execute("PRAGMA foreign_keys = ON")
            account_id = new_id  # for subsequent name update

        if new_name is not None:
            cursor.execute("UPDATE accounts SET name = ? WHERE id = ?", (new_name, account_id))
            self.conn.commit()

        return True

    # --- Token (legacy — kept for migration compatibility only) ---

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

    # --- Accounts ---

    def add_account(self, account_id: str, name: str | None, token: str, token_expires_at: str | None = None) -> bool:
        """Add an account, or replace the token of an existing one.

        On a re-add the token and token_expires_at are replaced (None clears the
        expiry: a new token's expiry is unknown until stated), added_on is reset
        to now (readers treat it as "token last set"), and the name is kept when
        name is None.

        Returns True if the account already existed, False if it was created.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,))
        existed = cursor.fetchone() is not None
        if existed:
            cursor.execute(
                "UPDATE accounts SET token = ?, name = COALESCE(?, name), token_expires_at = ?, added_on = CURRENT_TIMESTAMP WHERE id = ?",
                (token, name, token_expires_at, account_id),
            )
        else:
            cursor.execute(
                "INSERT INTO accounts (id, name, token, token_expires_at) VALUES (?, ?, ?, ?)",
                (account_id, name, token, token_expires_at),
            )
        self.conn.commit()
        return existed

    def set_token_expiry(self, account_id: str, token_expires_at: str | None) -> bool:
        """Set (or clear, with None) an account's token expiry. Returns False if the account is unknown."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE accounts SET token_expires_at = ? WHERE id = ?", (token_expires_at, account_id))
        self.conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _account_row(r: tuple) -> dict:
        return {"id": r[0], "name": r[1], "token": r[2], "added_on": r[3], "token_expires_at": r[4]}

    def get_account(self, account_id: str) -> dict | None:
        """Get account info by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, token, added_on, token_expires_at FROM accounts WHERE id = ?", (account_id,))
        result = cursor.fetchone()
        if not result:
            return None
        return self._account_row(result)

    def list_accounts(self) -> list[dict]:
        """List all accounts."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, token, added_on, token_expires_at FROM accounts ORDER BY added_on")
        return [self._account_row(r) for r in cursor.fetchall()]

    def remove_account(self, account_id: str) -> bool | None:
        """Remove an account.

        Returns:
            True  — account removed successfully
            False — blocked: queries still reference this account
            None  — account not found
        """
        cursor = self.conn.cursor()
        # Check the account exists first
        cursor.execute("SELECT COUNT(*) FROM accounts WHERE id = ?", (account_id,))
        if cursor.fetchone()[0] == 0:
            return None  # not found
        # Check for associated queries
        cursor.execute("SELECT COUNT(*) FROM queries WHERE account_id = ?", (account_id,))
        if cursor.fetchone()[0] > 0:
            return False  # blocked — caller must reassign or remove queries first
        cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self.conn.commit()
        return True

    def rename_account(self, account_id: str, new_name: str) -> bool:
        """Rename an account (convenience wrapper around update_account)."""
        return self.update_account(account_id, new_name=new_name)

    def get_token_for_account(self, account_id: str) -> str | None:
        """Get the token for a specific account."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT token FROM accounts WHERE id = ?", (account_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    # --- Queries ---

    def add_query(
        self,
        query_id: str,
        name: str,
        query_type: str = "activity",
        min_interval: int | None = None,
        account_id: str | None = None,
    ) -> None:
        """Add or update a query. account_id is required."""
        if account_id is None:
            raise ValueError("account_id is required — every query must belong to an account")
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO queries (id, name, type, min_interval, account_id) VALUES (?, ?, ?, ?, ?)",
            (query_id, name, query_type, min_interval, account_id),
        )
        self.conn.commit()

    def set_query_account(self, query_id: str, account_id: str) -> bool:
        """Set the account association for a query. account_id is required."""
        if not account_id:
            raise ValueError("account_id cannot be empty")
        cursor = self.conn.cursor()
        cursor.execute("UPDATE queries SET account_id = ? WHERE id = ?", (account_id, query_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def set_query_interval(self, query_id: str, min_interval: int | None) -> bool:
        """Set the minimum download interval (hours) for a query. None to use type default."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE queries SET min_interval = ? WHERE id = ?", (min_interval, query_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def set_query_type(self, query_id: str, query_type: str) -> bool:
        """Change a query's type in place (name, account, added_on, min_interval and history untouched)."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE queries SET type = ? WHERE id = ?", (query_type, query_id))
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
        cursor.execute("SELECT id, name, type, min_interval, account_id FROM queries WHERE id = ?", (query_id,))
        result = cursor.fetchone()
        if not result:
            return None
        return {"id": result[0], "name": result[1], "type": result[2] or "activity", "min_interval": result[3], "account_id": result[4]}

    def get_all_queries_with_status(self) -> list[dict]:
        """Get all queries with their latest download status."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, type, min_interval, account_id FROM queries ORDER BY added_on")
        queries = cursor.fetchall()

        result = []
        for query_id, name, query_type, min_interval, account_id in queries:
            query_info = {
                "id": query_id,
                "name": name,
                "type": query_type or "activity",
                "min_interval": min_interval,
                "account_id": account_id,
                "latest_request": None,
            }
            latest = self.get_latest_request(query_id)
            if latest:
                query_info["latest_request"] = latest
            result.append(query_info)

        return result

    # --- Token Resolution ---

    def resolve_token(self, query_id: str) -> str | None:
        """Resolve the token for a query via its account.

        Every query must have an account_id; the token comes from that account.
        Returns None if the account or its token cannot be found.
        """
        query_info = self.get_query_info(query_id)
        if not query_info:
            return None
        account_id = query_info.get("account_id")
        if not account_id:
            return None
        return self.get_token_for_account(account_id)

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

    def add_request_error(
        self,
        query_id: str,
        account_id: str | None,
        stage: str,
        error_code: str | None,
        error_message: str | None,
        kind: str,
    ) -> None:
        """Record a failed Flex request and prune this query's rows older than the retention window."""
        if stage not in REQUEST_ERROR_STAGES:
            raise ValueError(f"invalid stage {stage!r}; expected one of {REQUEST_ERROR_STAGES}")
        if kind not in REQUEST_ERROR_KINDS:
            raise ValueError(f"invalid kind {kind!r}; expected one of {REQUEST_ERROR_KINDS}")
        now = datetime.now(UTC)
        cutoff = (now - timedelta(days=REQUEST_ERRORS_RETENTION_DAYS)).strftime(UTC_TIMESTAMP_FORMAT)
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM request_errors WHERE query_id = ? AND occurred_at < ?", (query_id, cutoff))
        cursor.execute(
            "INSERT INTO request_errors (query_id, account_id, occurred_at, stage, error_code, error_message, kind)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (query_id, account_id, now.strftime(UTC_TIMESTAMP_FORMAT), stage, error_code, error_message, kind),
        )
        self.conn.commit()

    def list_request_errors(self, query_id: str | None = None) -> list[dict]:
        """Return request_errors rows (oldest first), optionally for one query."""
        cursor = self.conn.cursor()
        sql = "SELECT id, query_id, account_id, occurred_at, stage, error_code, error_message, kind FROM request_errors"
        params: tuple = ()
        if query_id is not None:
            sql += " WHERE query_id = ?"
            params = (query_id,)
        cursor.execute(sql + " ORDER BY occurred_at, id", params)
        cols = ("id", "query_id", "account_id", "occurred_at", "stage", "error_code", "error_message", "kind")
        return [dict(zip(cols, row, strict=True)) for row in cursor.fetchall()]

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
        """Get queries that haven't been downloaded within their effective interval."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, type, min_interval, account_id FROM queries")
        all_queries = cursor.fetchall()

        result = []
        for query_id, name, query_type, min_interval, account_id in all_queries:
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
                result.append({"id": query_id, "name": name, "type": query_type, "min_interval": min_interval, "account_id": account_id})

        return result

    def close(self) -> None:
        self.conn.close()
