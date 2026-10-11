import threading
import time
import pytest
import uvicorn
from company_portal.server import app
from company_portal.database import reset_db, get_all_invoices
from company_portal.generate_fixtures import create_all_fixtures
from agent.llm import GeminiBrain
from agent.graph import create_agent_graph



@pytest.fixture(autouse=True)
def clean_db():
    # reset database
    reset_db()
    yield
    # reset database
    reset_db()


def test_gemini_brain():
    # test brain
    brain = GeminiBrain()
    plan = brain.plan("Process invoices", ["sample.pdf", "sample.docx"])
    assert len(plan) >= 3
    assert plan[-1] == "verify:ledger"

    # test reasoning
    decision = brain.reason("parse:sample.pdf", {})
    assert decision["tool"] == "parse_document"


def test_agent_graph_execution():
    # setup fixtures
    create_all_fixtures()
    graph = create_agent_graph()

    # run workflow
    result = graph.invoke({"goal": "Discover and record all invoices"})
    assert result.get("status") == "completed"
    assert result.get("step_index") == len(result.get("plan", []))
    assert len(result.get("history", [])) == len(result.get("plan", []))

    # check database
    invoices = get_all_invoices()
    assert len(invoices) >= 2
    assert any(inv["invoice_number"] == "INV-2024-001" for inv in invoices)
    assert any(inv["invoice_number"] == "GL-INV-8821" for inv in invoices)


def test_agent_self_healing_recovery():
    # test recovery
    graph = create_agent_graph()

    # inject failure
    state = {
        "goal": "Test recovery",
        "plan": ["parse:missing_file.pdf"],
        "step_index": 0,
        "extracted_data": {
            "vendor_name": "Recovered Corp",
            "invoice_number": "REC-777",
            "amount": 777.0,
            "due_date": "2026-12-01"
        },
        "history": [],
        "error": None,
        "retries": 0,
        "status": "running"
    }

    # execute recovery
    result = graph.invoke(state)
    assert result.get("status") == "completed"

    # check fallback
    invoices = get_all_invoices()
    assert any(inv["invoice_number"] == "REC-777" for inv in invoices)
