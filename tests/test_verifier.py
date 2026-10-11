import pytest
from pathlib import Path
from company_portal.database import reset_db, add_invoice, get_invoice_by_number
from verifier.verifier import OutcomeVerifier
from verifier.hitl import HITLGate
from agent.graph import create_agent_graph


@pytest.fixture(autouse=True)
def clean_db():
    # reset test database
    reset_db()
    yield
    # reset test database
    reset_db()


def test_outcome_verifier():
    # setup sample invoice
    add_invoice("Acme Corp", "INV-VERIF-01", 1500.0, "2026-11-01")
    verifier = OutcomeVerifier()

    # test positive match
    res = verifier.verify_invoice("INV-VERIF-01", "Acme Corp", 1500.0, "2026-11-01")
    assert res["verified"] is True
    assert res["record"]["vendor_name"] == "Acme Corp"

    # test mismatched amount
    bad_res = verifier.verify_invoice("INV-VERIF-01", "Acme Corp", 9999.0, "2026-11-01")
    assert bad_res["verified"] is False

    # test missing invoice
    missing_res = verifier.verify_invoice("INV-UNKNOWN", "Acme Corp", 1500.0, "2026-11-01")
    assert missing_res["verified"] is False


def test_proof_of_work_generation(tmp_path):
    # setup test record
    add_invoice("Global Logistics Inc", "GL-POW-99", 3200.0, "2026-12-01")
    verifier = OutcomeVerifier()
    res = verifier.verify_invoice("GL-POW-99", "Global Logistics Inc", 3200.0, "2026-12-01")

    # generate proof artifact
    proof_file = tmp_path / "test_pow.json"
    proof = verifier.generate_proof_of_work(res, "Verify Global Logistics invoice", output_path=proof_file)

    assert proof["verified"] is True
    assert proof["invoice_number"] == "GL-POW-99"
    assert proof["audit_hash"] is not None
    assert proof_file.exists()


def test_hitl_safety_gate():
    # test threshold boundary
    gate = HITLGate(threshold_amount=10000.0, auto_approve=True)
    assert gate.requires_approval(4500.0) is False
    assert gate.requires_approval(12850.75) is True

    # test auto approval
    approval = gate.request_approval("Global Logistics", "GL-8821", 12850.75)
    assert approval["approved"] is True


def test_agent_with_verifier_and_pow():
    # run full agent
    graph = create_agent_graph()
    result = graph.invoke({
        "goal": "Find the latest invoice from Acme Corp, extract the amount and due date, enter it into our internal system, and tell me once it is done."
    })

    assert result.get("status") == "completed"
    pow_doc = result.get("proof_of_work")
    assert pow_doc is not None
    assert pow_doc.get("verified") is True
    assert pow_doc.get("invoice_number") == "INV-2024-001"
