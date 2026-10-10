from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient

from company_portal.database import (
    init_db,
    reset_db,
    add_invoice,
    get_all_invoices,
    get_invoice_by_number,
    generate_audit_hash,
)
from company_portal.server import app
from company_portal.generate_fixtures import create_all_fixtures, SAMPLE_DIR


@pytest.fixture(autouse=True)
def clean_database():
    # reset database
    reset_db()
    yield
    # reset clean
    reset_db()


def test_database_crud_operations():
    # insert record
    record = add_invoice(
        vendor_name="Acme Corporation",
        invoice_number="INV-TEST-99",
        amount=1500.50,
        due_date="2026-11-30"
    )
    assert record["id"] is not None
    assert record["vendor_name"] == "Acme Corporation"
    assert record["amount"] == 1500.50
    assert len(record["audit_hash"]) == 16

    # query invoices
    all_inv = get_all_invoices()
    assert len(all_inv) == 1
    assert all_inv[0]["invoice_number"] == "INV-TEST-99"

    # fetch single
    single = get_invoice_by_number("INV-TEST-99")
    assert single is not None
    assert single["amount"] == 1500.50

    # duplicate rejection
    with pytest.raises(sqlite3.IntegrityError):
        add_invoice("Duplicate Vendor", "INV-TEST-99", 500.00, "2026-12-01")


def test_audit_hash_integrity():
    # compare hashes
    hash1 = generate_audit_hash("Acme", "INV-1", 100.0, "2026-10-01")
    hash2 = generate_audit_hash("Acme", "INV-1", 100.0, "2026-10-01")
    assert hash1 == hash2

    # verify difference
    hash_diff = generate_audit_hash("Acme", "INV-1", 100.01, "2026-10-01")
    assert hash1 != hash_diff


def test_web_portal_routes():
    # test client
    client = TestClient(app)

    # test dashboard
    response = client.get("/")
    assert response.status_code == 200
    assert "CentrAlign Billing Portal" in response.text

    # test submission
    form_data = {
        "vendor_name": "Global Logistics",
        "invoice_number": "GL-8800",
        "amount": "2750.00",
        "due_date": "2026-12-15"
    }
    post_resp = client.post("/invoices", data=form_data)
    assert post_resp.status_code == 200
    assert "GL-8800" in post_resp.text

    # test upload
    up_resp = client.post(
        "/upload",
        files={"file": ("test_invoice.pdf", b"%PDF-1.4 mock content", "application/pdf")},
        follow_redirects=False
    )
    assert up_resp.status_code == 303
    test_file = SAMPLE_DIR / "test_invoice.pdf"
    if test_file.exists():
        test_file.unlink()


def test_rest_api_endpoints():
    # test client
    client = TestClient(app)

    # empty list
    list_resp = client.get("/api/invoices")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["invoices"]) == 0

    # create invoice
    payload = {
        "vendor_name": "Global Logistics LLC",
        "invoice_number": "GL-2024-551",
        "amount": 8940.25,
        "due_date": "2026-11-20"
    }
    create_resp = client.post("/api/invoices", json=payload)
    assert create_resp.status_code == 201
    assert create_resp.json()["status"] == "success"

    # fetch invoice
    get_resp = client.get("/api/invoices/GL-2024-551")
    assert get_resp.status_code == 200
    assert get_resp.json()["invoice"]["amount"] == 8940.25

    # duplicate conflict
    conflict_resp = client.post("/api/invoices", json=payload)
    assert conflict_resp.status_code == 409

    # reset api
    reset_resp = client.post("/api/reset", headers={"Accept": "application/json"})
    assert reset_resp.status_code == 200


def test_mock_fixtures_generated():
    # generate fixtures
    create_all_fixtures()

    # check files
    pdf_file = SAMPLE_DIR / "AcmeCorp_INV_2024_001.pdf"
    docx_file = SAMPLE_DIR / "GlobalLogistics_INV_8821.docx"

    assert pdf_file.exists()
    assert pdf_file.stat().st_size > 0
    assert docx_file.exists()
    assert docx_file.stat().st_size > 0
