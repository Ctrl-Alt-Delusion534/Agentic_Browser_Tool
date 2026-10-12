from typing import Literal
from langgraph.graph import StateGraph, START, END
from agent.state import AgentState
from agent.nodes import plan_node, execute_node, observe_node, recover_node, respond_node


def route_next_step(state: AgentState) -> Literal["execute", "recover", "respond"]:
    # check error condition
    if state.get("error"):
        return "recover" if state.get("retries", 0) < 3 else "respond"

    # check plan completion
    plan = state.get("plan", [])
    idx = state.get("step_index", 0)
    if idx < len(plan):
        return "execute"

    # summarize outcome
    return "respond"


def route_after_recovery(state: AgentState) -> Literal["execute", "respond"]:
    # verify recovery state
    if not state.get("error") and state.get("step_index", 0) < len(state.get("plan", [])):
        return "execute"
    return "respond"


def route_after_plan(state: AgentState) -> Literal["execute", "respond"]:
    # verify plan ready
    if not state.get("plan") or state.get("status") == "failed":
        return "respond"
    return "execute"


def create_agent_graph():
    # initialize state workflow
    workflow = StateGraph(AgentState)

    # register graph nodes
    workflow.add_node("plan", plan_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("observe", observe_node)
    workflow.add_node("recover", recover_node)
    workflow.add_node("respond", respond_node)

    # connect deterministic edges
    workflow.add_edge(START, "plan")
    workflow.add_conditional_edges("plan", route_after_plan, {
        "execute": "execute",
        "respond": "respond"
    })
    workflow.add_edge("execute", "observe")
    workflow.add_edge("respond", END)

    # add conditional edges
    workflow.add_conditional_edges("observe", route_next_step, {
        "execute": "execute",
        "recover": "recover",
        "respond": "respond"
    })
    workflow.add_conditional_edges("recover", route_after_recovery, {
        "execute": "execute",
        "respond": "respond"
    })

    # compile runnable application
    return workflow.compile().with_config(recursion_limit=80)
