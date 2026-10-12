import threading
import time
import pytest
import uvicorn
from company_portal.server import app
from company_portal.database import reset_db, get_all_invoices
from company_portal.generate_fixtures import create_all_fixtures
from agent.llm import AgentBrain
from agent.graph import create_agent_graph
from agent.nodes import build_default_registry
from tools.base import ToolResult
from tools.browser_tool import BrowserTool

requires_llm = pytest.mark.skipif(AgentBrain().client is None, reason="GROQ_API_KEY not configured")


@pytest.fixture(autouse=True)
def clean_db():
    reset_db()
    yield
    reset_db()


@requires_llm
def test_agent_brain():
    brain = AgentBrain()
    tools = build_default_registry().get_schemas()
    context = "INBOX FILES (1, newest first):\n- company_portal/sample_files/Apex_INV_2024_001.pdf\nERP LEDGER (0 records):"
    plan = brain.plan("What is the amount on the Apex invoice?", context, tools)
    assert not any("submit" in s.lower() or "create" in s.lower() for s in plan)

    decision = brain.reason("Read Apex invoice", "Parse company_portal/sample_files/Apex_INV_2024_001.pdf", {}, [], tools)
    assert decision["tool"] == "parse_document"


@requires_llm
def test_agent_graph_execution():
    create_all_fixtures()
    graph = create_agent_graph()

    result = graph.invoke({"goal": "Record the Apex Logistics and Global Logistics invoices into the ERP"})
    assert result.get("status") == "completed"
    assert result.get("step_index") == len(result.get("plan", []))
    assert result.get("answer")

    invoices = get_all_invoices()
    assert len(invoices) >= 1


@requires_llm
def test_agent_self_healing_recovery(monkeypatch):
    monkeypatch.setattr(BrowserTool, "execute", lambda self, action, **kw: ToolResult(success=False, error="Selector #submit_btn not found"))
    graph = create_agent_graph()

    result = graph.invoke({"goal": "Enter invoice REC-777 from Recovered Corp for $777.00 due 2026-12-01 into the ERP"})
    assert result.get("status") == "completed"

    invoices = get_all_invoices()
    assert any(inv["invoice_number"] == "REC-777" for inv in invoices)
    assert any(h.get("tool") == "enterprise_api" and h.get("success") for h in result["history"])
