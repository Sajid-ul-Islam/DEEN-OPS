"""Persist Pathao submission outcomes so reruns cannot resend an order blindly.

Pending records deliberately have no expiry: an interrupted request may already
have created a consignment. Those records need reconciliation in Pathao before
any retry, just like explicitly uncertain outcomes.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

from src.config.constants import DATA_DIR, bd_now


def _canonical_merchant_id(value):
    """Source row ordering must not turn the same merged parcel into a new one."""
    return ", ".join(
        sorted({part.strip() for part in str(value).split(",") if part.strip()})
    )


def ledger_key(account_scope, merchant_order_id, warehouse_outlet):
    """Identify one merchant parcel, independent of editable shipment details.

    The caller supplies an account scope (for example a hash of API host,
    client ID and username). Warehouse distinguishes parcels split by outlet.
    Do not include store, COD or recipient details in this identity.
    """
    account_scope = str(account_scope).strip()
    merchant_order_id = _canonical_merchant_id(merchant_order_id)
    if not account_scope or not merchant_order_id:
        raise ValueError("Account scope and merchant order ID are required.")
    identity = [account_scope, merchant_order_id, str(warehouse_outlet).strip()]
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class DispatchLedger:
    """A SQLite submission ledger, with atomic reservations across processes.

    Use one instance per thread, preferably as a context manager. Only an
    explicitly failed attempt is eligible for a subsequent reservation. Callers
    should store concise outcome messages, never payloads or customer details.
    """

    def __init__(self, path=None):
        ledger_path = (
            Path(path)
            if path is not None
            else Path(DATA_DIR) / "pathao_dispatch.sqlite3"
        )
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            ledger_path, timeout=30, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatch_attempts (
                key TEXT PRIMARY KEY,
                merchant_order_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending', 'created', 'failed', 'uncertain')
                ),
                consignment_id TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def get(self, key):
        """Return a persisted attempt, or None when never reserved."""
        record = self._connection.execute(
            "SELECT * FROM dispatch_attempts WHERE key = ?", (key,)
        ).fetchone()
        return dict(record) if record is not None else None

    def reserve(self, key, merchant_order_id):
        """Atomically reserve a new or explicitly failed attempt.

        A false result means another attempt owns this parcel or its outcome
        requires checking in Pathao. Never submit an API request in that case.
        """
        merchant_order_id = _canonical_merchant_id(merchant_order_id)
        if not key or not merchant_order_id:
            raise ValueError("Ledger key and merchant order ID are required.")
        now = bd_now().isoformat()
        cursor = self._connection.execute(
            """
            INSERT INTO dispatch_attempts (
                key, merchant_order_id, status, created_at, updated_at
            ) VALUES (?, ?, 'pending', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                status = 'pending',
                consignment_id = '',
                message = '',
                updated_at = excluded.updated_at
            WHERE dispatch_attempts.status = 'failed'
              AND dispatch_attempts.merchant_order_id = excluded.merchant_order_id
            """,
            (key, merchant_order_id, now, now),
        )
        return cursor.rowcount == 1

    def finish(self, key, status, *, consignment_id="", message=""):
        """Record a pending attempt's outcome without replacing a final result."""
        if status not in {"created", "failed", "uncertain"}:
            raise ValueError("Outcome must be created, failed or uncertain.")
        cursor = self._connection.execute(
            """
            UPDATE dispatch_attempts
               SET status = ?, consignment_id = ?, message = ?, updated_at = ?
             WHERE key = ? AND status = 'pending'
            """,
            (
                status,
                str(consignment_id),
                str(message),
                bd_now().isoformat(),
                key,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("Only a reserved pending attempt can be finished.")

    def close(self):
        """Close this instance; every completed write is already committed."""
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, traceback):
        self.close()
