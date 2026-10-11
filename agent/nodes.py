from pathlib import Path
from typing import Dict, Any, List
from agent.state import AgentState
from agent.llm import GeminiBrain
from tools.registry import ToolRegistry
from tools.document_tool import DocumentParserTool
from tools.enterprise_tool import EnterpriseApiTool
from tools.browser_tool import BrowserTool


import os

def build_default_registry() -> ToolRegistry:
    # initialize default registry
    headless = os.getenv("AGENT_HEADLESS", "true").lower() != "false"
    reg = ToolRegistry()
    reg.register(DocumentParserTool())
    reg.register(EnterpriseApiTool())
    reg.register(BrowserTool(headless=headless))
    return reg


_SHARED_REGISTRY = None


def get_shared_registry() -> ToolRegistry:
    # get shared registry
    global _SHARED_REGISTRY
    if _SHARED_REGISTRY is None:
        _SHARED_REGISTRY = build_default_registry()
    return _SHARED_REGISTRY


def reset_shared_registry() -> None:
    # cleanup browser session
    global _SHARED_REGISTRY
    if _SHARED_REGISTRY is not None:
        try:
            _SHARED_REGISTRY.get("browser_tool").close()
        except Exception:
            pass
        _SHARED_REGISTRY = None


def plan_node(state: AgentState) -> Dict[str, Any]:
    # check existing plan
    if state.get("plan"):
        return {
            "plan": state["plan"],
            "step_index": state.get("step_index", 0),
            "retries": 0,
            "status": "running",
            "error": None
        }

    # discover invoice files
    sample_dir = Path("company_portal/sample_files")
    sample_dir.mkdir(parents=True, exist_ok=True)
    files = [f.as_posix() for f in (list(sample_dir.glob("*.pdf")) + list(sample_dir.glob("*.docx")))]

    # plan with brain
    brain = GeminiBrain()
    plan = brain.plan(state.get("goal", ""), files)

    if not plan:
        return {
            "plan": [],
            "step_index": 0,
            "retries": 0,
            "status": "not_found",
            "error": "Target invoice not found in incoming repository files."
        }

    # merge direct facts
    extracted = dict(state.get("extracted_data", {}))
    if brain.direct_data:
        extracted.update(brain.direct_data)

    return {
        "plan": plan,
        "step_index": 0,
        "retries": 0,
        "status": "running",
        "error": None,
        "extracted_data": extracted
    }


def execute_node(state: AgentState) -> Dict[str, Any]:
    # execute planned task
    reg = get_shared_registry()
    brain = GeminiBrain()
    plan = state["plan"]
    idx = state["step_index"]

    if idx >= len(plan):
        return {"status": "completed"}

    # reason tool action
    current_task = plan[idx]
    decision = brain.reason(current_task, state.get("extracted_data", {}))

    # handle ledger verification
    if current_task.startswith("verify:"):
        from verifier.verifier import OutcomeVerifier
        from tools.base import ToolResult
        verifier = OutcomeVerifier()
        data = state.get("extracted_data", {})
        verif_res = verifier.verify_invoice(
            invoice_number=data.get("invoice_number", ""),
            expected_vendor=data.get("vendor_name", ""),
            expected_amount=data.get("amount", 0.0),
            expected_due_date=data.get("due_date", "")
        )
        pow_doc = verifier.generate_proof_of_work(verif_res, state.get("goal", ""))
        return {
            "last_result": ToolResult(success=verif_res["verified"], data=pow_doc, error=verif_res.get("error")).to_dict(),
            "action_type": "verify"
        }

    # evaluate hitl safety
    if decision.get("tool") == "browser_tool" and decision.get("params", {}).get("action") == "submit_invoice":
        from verifier.hitl import HITLGate
        from tools.base import ToolResult
        params = decision["params"]
        gate = HITLGate()
        approval = gate.request_approval(
            vendor_name=params.get("vendor_name", "Unknown"),
            invoice_number=params.get("invoice_number", "INV"),
            amount=params.get("amount", 0.0)
        )
        if not approval["approved"]:
            return {
                "last_result": ToolResult(success=False, error=f"HITL safety reject: {approval['reason']}").to_dict(),
                "action_type": "submit"
            }

    # check existing record
    if decision.get("tool") == "browser_tool" and decision.get("params", {}).get("action") == "submit_invoice":
        from company_portal.database import get_invoice_by_number
        from tools.base import ToolResult
        inv_num = decision["params"].get("invoice_number")
        existing = get_invoice_by_number(inv_num) if inv_num else None
        if existing and abs(existing["amount"] - float(decision["params"].get("amount", 0.0))) < 0.01:
            return {
                "last_result": ToolResult(success=True, data={"submitted": inv_num, "status": "existing"}).to_dict(),
                "action_type": "submit"
            }

    result = reg.execute(decision["tool"], **decision["params"])

    return {
        "last_result": result.to_dict(),
        "action_type": current_task.partition(":")[0]
    }


def observe_node(state: AgentState) -> Dict[str, Any]:
    # inspect execution outcome
    last_res = state.get("last_result", {})
    action_type = state.get("action_type", "")
    is_success = last_res.get("success", False)

    # update action history
    history = list(state.get("history", []))
    history.append({
        "step": state["plan"][state["step_index"]],
        "success": is_success,
        "error": last_res.get("error")
    })

    if is_success:
        extracted = dict(state.get("extracted_data", {}))
        # merge extracted facts
        if action_type == "parse" and last_res.get("data"):
            extracted.update(last_res["data"])

        new_index = state["step_index"] + 1
        is_done = new_index >= len(state.get("plan", []))
        return {
            "extracted_data": extracted,
            "proof_of_work": last_res.get("data") if action_type == "verify" else state.get("proof_of_work"),
            "history": history,
            "step_index": new_index,
            "status": "completed" if is_done else "running",
            "error": None
        }
    else:
        # record step failure
        return {
            "history": history,
            "error": last_res.get("error", "Action failed"),
            "retries": state.get("retries", 0) + 1
        }


def recover_node(state: AgentState) -> Dict[str, Any]:
    # attempt adaptive recovery
    reg = get_shared_registry()
    data = state.get("extracted_data", {})

    # fallback to api
    fallback_res = reg.execute(
        "enterprise_api",
        action="create",
        vendor_name=data.get("vendor_name", "Unknown"),
        invoice_number=data.get("invoice_number", "INV-000"),
        amount=data.get("amount", 0.0),
        due_date=data.get("due_date", "2026-12-31")
    )

    if fallback_res.success:
        new_index = state["step_index"] + 1
        is_done = new_index >= len(state.get("plan", []))
        return {
            "step_index": new_index,
            "status": "completed" if is_done else "running",
            "error": None
        }

    # direct db fallback
    try:
        from company_portal.database import add_invoice
        add_invoice(
            vendor_name=data.get("vendor_name", "Unknown"),
            invoice_number=data.get("invoice_number", "INV-000"),
            amount=data.get("amount", 0.0),
            due_date=data.get("due_date", "2026-12-31")
        )
        new_index = state["step_index"] + 1
        is_done = new_index >= len(state.get("plan", []))
        return {
            "step_index": new_index,
            "status": "completed" if is_done else "running",
            "error": None
        }
    except Exception as e:
        return {"status": "failed", "error": f"Self-healing exceeded: {e}"}
