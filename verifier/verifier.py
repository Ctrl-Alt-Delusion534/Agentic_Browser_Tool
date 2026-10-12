import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# default db path
DB_PATH = Path(__file__).resolve().parent.parent / "company_portal" / "portal.db"


class OutcomeVerifier:
    def __init__(self, db_path: Optional[Path] = None):
        # assign db path
        self.db_path = db_path or DB_PATH

    def verify_invoice(
        self,
        invoice_number: str,
        expected_vendor: str,
        expected_amount: float,
        expected_due_date: str
    ) -> Dict[str, Any]:
        # query ground truth
        if not self.db_path.exists():
            return {"verified": False, "error": "Database not found"}

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = None
            if invoice_number and invoice_number.strip():
                if expected_vendor and expected_vendor.strip():
                    v = expected_vendor.strip().lower()
                    row = conn.execute(
                        "SELECT * FROM invoices WHERE invoice_number = ? AND (LOWER(vendor_name) = ? OR LOWER(vendor_name) LIKE ? OR ? LIKE '%' || LOWER(vendor_name) || '%') ORDER BY id DESC LIMIT 1",
                        (invoice_number.strip(), v, f"%{v}%", v)
                    ).fetchone()
                if not row:
                    row = conn.execute(
                        "SELECT * FROM invoices WHERE invoice_number = ? ORDER BY id DESC LIMIT 1",
                        (invoice_number.strip(),)
                    ).fetchone()
            elif expected_vendor:
                row = conn.execute(
                    "SELECT * FROM invoices WHERE LOWER(vendor_name) = LOWER(?) ORDER BY id DESC LIMIT 1",
                    (expected_vendor.strip(),)
                ).fetchone()

        if not row:
            return {"verified": False, "error": f"Invoice '{invoice_number or expected_vendor}' not found in ledger"}

        record = dict(row)
        vendor_match = expected_vendor.strip().lower() in record["vendor_name"].strip().lower() or record["vendor_name"].strip().lower() in expected_vendor.strip().lower()
        amount_match = abs(record["amount"] - float(expected_amount)) < 0.01
        due_match = record["due_date"].strip() == expected_due_date.strip()

        verified = vendor_match and amount_match and due_match
        return {
            "verified": verified,
            "record": record,
            "discrepancies": {
                "vendor_match": vendor_match,
                "amount_match": amount_match,
                "due_match": due_match
            }
        }

    def generate_proof_of_work(
        self,
        verification_result: Dict[str, Any],
        goal: str,
        output_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        # build proof document
        record = verification_result.get("record", {})
        proof = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "goal": goal,
            "verified": verification_result.get("verified", False),
            "invoice_number": record.get("invoice_number"),
            "vendor_name": record.get("vendor_name"),
            "amount": record.get("amount"),
            "due_date": record.get("due_date"),
            "audit_hash": record.get("audit_hash"),
            "ledger_id": record.get("id"),
        }

        # save proof artifact
        save_target = output_path or (Path(__file__).resolve().parent.parent / "proof_of_work.json")
        with open(save_target, "w", encoding="utf-8") as f:
            json.dump(proof, f, indent=2)

        return proof
