import pytest
import subprocess
import sys
from pathlib import Path
from company_portal.database import reset_db, get_all_invoices, get_invoice_by_number
from company_portal.generate_fixtures import create_all_fixtures
from company_portal.server import get_incoming_files_list
from agent.llm import AgentBrain
from agent.graph import create_agent_graph
from agent.nodes import reset_shared_registry
from verifier.verifier import OutcomeVerifier
from verifier.hitl import HITLGate

requires_llm = pytest.mark.skipif(AgentBrain().client is None, reason="GROQ_API_KEY not configured")


@pytest.fixture(autouse=True)
def clean_environment():
    # clean baseline before and after test
    reset_db()
    reset_shared_registry()
    create_all_fixtures()
    yield
    reset_db()
    reset_shared_registry()


@requires_llm
def test_end_to_end_autonomous_workflow():
    # goal: discover, extract and record invoice
    reset_db()
    create_all_fixtures()
    
    # 1. verify initial inbox has pending items
    initial_inbox = get_incoming_files_list()
    assert len(initial_inbox) >= 1
    assert any(item["status"] == "PENDING" for item in initial_inbox)

    # 2. run agent graph on a specific pending invoice
    graph = create_agent_graph()
    goal = "Find the latest invoice from Apex Technologies, extract the amount and due date, enter it into our internal system, and tell me once it is done."
    
    initial_state = {
        "goal": goal,
        "context": "",
        "plan": [],
        "step_index": 0,
        "extracted_data": {},
        "last_result": None,
        "action_type": "",
        "proof_of_work": None,
        "history": [],
        "retries": 0,
        "error": None,
        "status": "pending",
        "answer": ""
    }

    final_state = graph.invoke(initial_state)

    # 3. verify execution finished successfully
    assert final_state["status"] == "completed"
    assert final_state.get("answer") is not None

    # 4. verify ground-truth database record exists
    invoices = get_all_invoices()
    assert len(invoices) >= 1
    inv = get_invoice_by_number("INV-2024-001")
    assert inv is not None
    assert inv["amount"] == 4500.0

    # 5. verify proof of work artifact was created and verified
    verifier = OutcomeVerifier()
    check = verifier.verify_invoice("INV-2024-001", "APEX TECHNOLOGIES", 4500.0, "2026-11-15")
    assert check["verified"] is True
    assert check["record"]["audit_hash"] == inv["audit_hash"]

    # 6. verify inbox status updated: invoice is now marked AUDITED
    updated_inbox = get_incoming_files_list()
    apex_files = [f for f in updated_inbox if f.get("file_name") == "Apex_INV_2024_001.pdf"]
    if apex_files:
        assert apex_files[0]["status"] == "AUDITED"


def test_hitl_threshold_enforcement():
    # test hitl behavior for standard vs high-stakes amounts
    gate = HITLGate(threshold_amount=10000.0, auto_approve=False)
    
    # standard invoice below threshold -> approved automatically
    std_approval = gate.request_approval("Nexus Tech", "INV-2024-001", 4500.0)
    assert std_approval["approved"] is True

    # high-stakes invoice above threshold -> requires approval
    assert gate.requires_approval(12850.75) is True


def test_duplicate_invoice_numbers_across_different_companies():
    import sqlite3
    from company_portal.database import add_invoice

    # company A records INV-2024-001
    inv_a = add_invoice("Nexus Tech", "INV-2024-001", 4500.0, "2026-11-15")
    assert inv_a["vendor_name"] == "Nexus Tech"

    # company B records the same reference INV-2024-001 without collision
    inv_b = add_invoice("Zephyrine Quokka Logistics", "INV-2024-001", 3200.0, "2026-11-11")
    assert inv_b["vendor_name"] == "Zephyrine Quokka Logistics"

    # querying by vendor returns the respective company record
    rec_a = get_invoice_by_number("INV-2024-001", vendor_name="Nexus Tech")
    rec_b = get_invoice_by_number("INV-2024-001", vendor_name="Zephyrine Quokka Logistics")
    assert rec_a["amount"] == 4500.0
    assert rec_b["amount"] == 3200.0

    # verifier isolates each record by vendor
    verifier = OutcomeVerifier()
    res_b = verifier.verify_invoice("INV-2024-001", "Zephyrine Quokka Logistics", 3200.0, "2026-11-11")
    assert res_b["verified"] is True
    assert res_b["record"]["vendor_name"] == "Zephyrine Quokka Logistics"

    # same company submitting the same invoice number again is rejected as duplicate
    with pytest.raises(sqlite3.IntegrityError):
        add_invoice("Nexus Tech", "INV-2024-001", 4500.0, "2026-11-15")

