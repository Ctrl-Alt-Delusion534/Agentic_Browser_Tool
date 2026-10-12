import pytest
from pathlib import Path
from company_portal.database import reset_db, add_invoice, get_invoice_by_number
from verifier.verifier import OutcomeVerifier
from verifier.hitl import HITLGate
from agent.graph import create_agent_graph
from agent.llm import AgentBrain


@pytest.fixture(autouse=True)
def clean_db():
    reset_db()
    yield
    reset_db()


def test_outcome_verifier():
    add_invoice("Nexus Technologies", "INV-VERIF-01", 1500.0, "2026-11-01")
    verifier = OutcomeVerifier()

    res = verifier.verify_invoice("INV-VERIF-01", "Nexus Technologies", 1500.0, "2026-11-01")
    assert res["verified"] is True
    assert res["record"]["vendor_name"] == "Nexus Technologies"

    bad_res = verifier.verify_invoice("INV-VERIF-01", "Nexus Technologies", 9999.0, "2026-11-01")
    assert bad_res["verified"] is False

    missing_res = verifier.verify_invoice("INV-UNKNOWN", "Nexus Technologies", 1500.0, "2026-11-01")
    assert missing_res["verified"] is False


def test_proof_of_work_generation(tmp_path):
    add_invoice("Global Logistics Inc", "GL-POW-99", 3200.0, "2026-12-01")
    verifier = OutcomeVerifier()
    res = verifier.verify_invoice("GL-POW-99", "Global Logistics Inc", 3200.0, "2026-12-01")

    proof_file = tmp_path / "test_pow.json"
    proof = verifier.generate_proof_of_work(res, "Verify Global Logistics invoice", output_path=proof_file)

    assert proof["verified"] is True
    assert proof["invoice_number"] == "GL-POW-99"
    assert proof["audit_hash"] is not None
    assert proof_file.exists()


def test_hitl_safety_gate():
    gate = HITLGate(threshold_amount=10000.0, auto_approve=True)
    assert gate.requires_approval(4500.0) is False
    assert gate.requires_approval(12850.75) is True

    approval = gate.request_approval("Global Logistics", "GL-8821", 12850.75)
    assert approval["approved"] is True
