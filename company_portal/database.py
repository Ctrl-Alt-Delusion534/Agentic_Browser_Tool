import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

# database file path
DB_PATH = Path(__file__).parent / "portal.db"


def get_db_connection() -> sqlite3.Connection:
    # connect sqlite database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def generate_audit_hash(vendor: str, invoice_number: str, amount: float, due_date: str) -> str:
    # create audit hash
    payload = f"{vendor.strip().lower()}:{invoice_number.strip()}:{amount:.2f}:{due_date.strip()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def init_db() -> None:
    # initialize database tables
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_name TEXT NOT NULL,
                invoice_number TEXT NOT NULL,
                amount REAL NOT NULL,
                due_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'AUDITED',
                created_at TEXT NOT NULL,
                audit_hash TEXT NOT NULL,
                UNIQUE(vendor_name, invoice_number)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_vendor_number ON invoices(vendor_name, invoice_number)")
        conn.commit()


def add_invoice(
    vendor_name: str,
    invoice_number: str,
    amount: float,
    due_date: str,
    status: str = "AUDITED"
) -> Dict[str, Any]:
    # insert invoice record
    init_db()
    created_at = datetime.now(timezone.utc).isoformat()
    audit_hash = generate_audit_hash(vendor_name, invoice_number, amount, due_date)

    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO invoices (vendor_name, invoice_number, amount, due_date, status, created_at, audit_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (vendor_name.strip(), invoice_number.strip(), float(amount), due_date.strip(), status, created_at, audit_hash))
        conn.commit()
        record_id = cursor.lastrowid

    return {
        "id": record_id,
        "vendor_name": vendor_name.strip(),
        "invoice_number": invoice_number.strip(),
        "amount": float(amount),
        "due_date": due_date.strip(),
        "status": status,
        "created_at": created_at,
        "audit_hash": audit_hash,
    }


def get_all_invoices() -> List[Dict[str, Any]]:
    # fetch all invoices
    init_db()
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]


def get_invoice_by_number(invoice_number: str, vendor_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    # query by number and optional vendor
    init_db()
    with get_db_connection() as conn:
        if vendor_name and vendor_name.strip():
            v = vendor_name.strip().lower()
            row = conn.execute(
                "SELECT * FROM invoices WHERE invoice_number = ? AND (LOWER(vendor_name) = ? OR LOWER(vendor_name) LIKE ? OR ? LIKE '%' || LOWER(vendor_name) || '%') ORDER BY id DESC LIMIT 1",
                (invoice_number.strip(), v, f"%{v}%", v)
            ).fetchone()
            return dict(row) if row else None
        row = conn.execute("SELECT * FROM invoices WHERE invoice_number = ? ORDER BY id DESC LIMIT 1", (invoice_number.strip(),)).fetchone()
        return dict(row) if row else None


def reset_db() -> None:
    # reset clean database
    with get_db_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS invoices")
        conn.commit()
    init_db()


if __name__ == "__main__":
    # run self test
    print("[Self-Test] Initializing DB...")
    init_db()
    reset_db()
    sample = add_invoice("Apex Logistics", "INV-2024-001", 4500.00, "2026-11-15")
    fetched = get_invoice_by_number("INV-2024-001")
    assert fetched is not None
    assert fetched["amount"] == 4500.00
    print("[Self-Test] PASSED!")
