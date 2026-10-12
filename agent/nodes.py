import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from agent.state import AgentState
from agent.llm import AgentBrain
from tools.base import ToolResult
from tools.registry import ToolRegistry
from tools.document_tool import DocumentParserTool
from tools.enterprise_tool import EnterpriseApiTool
from tools.browser_tool import BrowserTool


def build_default_registry() -> ToolRegistry:
    # initialize default registry
    headless = os.getenv("AGENT_HEADLESS", "false").lower() == "true"
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


def build_context() -> str:
    # observe inbox and ledger
    sample_dir = Path("company_portal/sample_files")
    sample_dir.mkdir(parents=True, exist_ok=True)
    files = list(sample_dir.glob("*.pdf")) + list(sample_dir.glob("*.docx"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    parser = DocumentParserTool()
    lines = [f"INBOX FILES ({len(files)}, newest first):"]
    for f in files:
        d = parser.execute(str(f)).data or {}
        modified = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(
            f"- {f.as_posix()} | modified {modified} | vendor={d.get('vendor_name')}, "
            f"invoice={d.get('invoice_number')}, amount={d.get('amount')}, due={d.get('due_date')}"
        )

    ledger = get_shared_registry().execute("enterprise_api", action="list")
    records = (ledger.data or {}).get("invoices", []) if ledger.success else []
    lines.append(f"ERP LEDGER ({len(records)} records):")
    lines += [f"- {r['invoice_number']} | {r['vendor_name']} | {r['amount']} | due {r['due_date']}" for r in records[:25]]
    return "\n".join(lines)


def plan_node(state: AgentState) -> Dict[str, Any]:
    # observe environment
    context = state.get("context") or build_context()

    # check existing plan
    if state.get("plan"):
        return {
            "plan": state["plan"],
            "step_index": state.get("step_index", 0),
            "retries": 0,
            "status": "running",
            "error": None,
            "context": context
        }

    # plan with brain
    plan = AgentBrain().plan(state.get("goal", ""), context, get_shared_registry().get_schemas())
    print("Plan:" if plan else "Plan: no tool actions required")
    for i, step in enumerate(plan, 1):
        print(f"  {i}. {step}")

    return {
        "plan": plan,
        "step_index": 0,
        "retries": 0,
        "status": "running",
        "error": None,
        "context": context
    }


def submit_with_safeguards(reg: ToolRegistry, tool: str, params: Dict[str, Any], goal: str) -> ToolResult:
    # guard erp writes
    from verifier.hitl import HITLGate
    from verifier.verifier import OutcomeVerifier
    from company_portal.database import get_invoice_by_number

    inv_num = str(params.get("invoice_number") or "").strip()
    if not inv_num or params.get("amount") in (None, "") or not params.get("vendor_name") or not params.get("due_date"):
        return ToolResult(success=False, error="Missing required invoice fields; refusing to submit.")

    # evaluate hitl safety
    approval = HITLGate().request_approval(params["vendor_name"], inv_num, params["amount"])
    if not approval["approved"]:
        return ToolResult(success=False, error=f"HITL rejected: {approval['reason']}")

    # execute tool action
    result = reg.execute(tool, **params)
    if not result.success:
        return result

    # verify ground truth
    verifier = OutcomeVerifier()
    check = verifier.verify_invoice(inv_num, str(params["vendor_name"]), float(params["amount"]), str(params["due_date"]))
    proof = verifier.generate_proof_of_work(check, goal)
    if check["verified"]:
        return ToolResult(success=True, data=proof)
    return ToolResult(success=False, data=proof, error=check.get("error") or f"Ledger mismatch: {check.get('discrepancies')}")


def execute_node(state: AgentState) -> Dict[str, Any]:
    # execute planned step
    reg = get_shared_registry()
    plan = state["plan"]
    idx = state["step_index"]

    if idx >= len(plan):
        return {"status": "completed"}

    # reason tool action
    step = plan[idx]
    decision = AgentBrain().reason(
        state.get("goal", ""), step, state.get("extracted_data", {}), state.get("history", []), reg.get_schemas()
    )
    tool, params = decision["tool"], decision["params"]
    print(f"[{idx + 1}/{len(plan)}] {step}\n      -> {tool} {json.dumps(params, default=str)}")

    is_submit = (tool == "browser_tool" and params.get("action") == "submit_invoice") or \
                (tool == "enterprise_api" and params.get("action") == "create")
    if not tool:
        result = ToolResult(success=True, data={"skipped": decision["thought"]})
    elif is_submit:
        result = submit_with_safeguards(reg, tool, params, state.get("goal", ""))
    else:
        result = reg.execute(tool, **params)

    result.metadata = {"tool": tool, "params": params, "thought": decision["thought"]}
    return {
        "last_result": result.to_dict(),
        "action_type": "submit" if is_submit else tool
    }


def observe_node(state: AgentState) -> Dict[str, Any]:
    # inspect execution outcome
    last_res = state.get("last_result", {})
    action_type = state.get("action_type", "")
    is_success = last_res.get("success", False)
    meta = last_res.get("metadata", {})

    # update action history
    history = list(state.get("history", []))
    history.append({
        "step": state["plan"][state["step_index"]],
        "tool": meta.get("tool"),
        "params": meta.get("params"),
        "success": is_success,
        "error": last_res.get("error"),
        "observation": json.dumps(last_res.get("data"), default=str)[:800] if last_res.get("data") else None
    })

    if is_success:
        extracted = dict(state.get("extracted_data", {}))
        # merge extracted facts
        if action_type == "parse_document" and last_res.get("data"):
            extracted.update(last_res["data"])

        new_index = state["step_index"] + 1
        is_done = new_index >= len(state.get("plan", []))
        return {
            "extracted_data": extracted,
            "proof_of_work": last_res.get("data") if action_type == "submit" else state.get("proof_of_work"),
            "history": history,
            "step_index": new_index,
            "retries": 0,
            "status": "completed" if is_done else "running",
            "error": None
        }

    # record step failure
    print(f"      !! {last_res.get('error', 'Action failed')}")
    return {
        "history": history,
        "error": last_res.get("error", "Action failed"),
        "retries": state.get("retries", 0) + 1
    }


def recover_node(state: AgentState) -> Dict[str, Any]:
    # classify failure
    err = str(state.get("error", ""))
    if err.startswith(("HITL", "Missing required")):
        # never bypass safety
        return {"status": "failed"}

    # retry with failure in history
    print(f"      Adapting (attempt {state.get('retries', 0) + 1}/3)")
    return {"error": None, "status": "running"}


def respond_node(state: AgentState) -> Dict[str, Any]:
    # synthesize final answer
    failed = state.get("status") == "failed" or bool(state.get("error"))
    try:
        answer = AgentBrain().respond(
            state.get("goal", ""), state.get("context", ""), state.get("extracted_data", {}), state.get("history", [])
        )
    except Exception as e:
        answer = f"Could not synthesize answer: {e}"
    return {"answer": answer, "status": "failed" if failed else "completed"}
