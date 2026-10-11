from typing import Literal
from langgraph.graph import StateGraph, START, END
from agent.state import AgentState
from agent.nodes import plan_node, execute_node, observe_node, recover_node


def route_next_step(state: AgentState) -> Literal["execute", "recover", "__end__"]:
    # check error condition
    if state.get("error") and state.get("retries", 0) < 3:
        return "recover"

    # check plan completion
    plan = state.get("plan", [])
    idx = state.get("step_index", 0)
    if idx < len(plan):
        return "execute"

    # terminate graph execution
    return END


def route_after_recovery(state: AgentState) -> Literal["execute", "__end__"]:
    # verify recovery state
    if not state.get("error") and state.get("step_index", 0) < len(state.get("plan", [])):
        return "execute"
    return END


def route_after_plan(state: AgentState) -> Literal["execute", "__end__"]:
    # verify plan ready
    if not state.get("plan") or state.get("status") in ["not_found", "failed"]:
        return END
    return "execute"


def create_agent_graph():
    # initialize state workflow
    workflow = StateGraph(AgentState)

    # register graph nodes
    workflow.add_node("plan", plan_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("observe", observe_node)
    workflow.add_node("recover", recover_node)

    # connect deterministic edges
    workflow.add_edge(START, "plan")
    workflow.add_conditional_edges("plan", route_after_plan, {
        "execute": "execute",
        END: END
    })
    workflow.add_edge("execute", "observe")

    # add conditional edges
    workflow.add_conditional_edges("observe", route_next_step, {
        "execute": "execute",
        "recover": "recover",
        END: END
    })
    workflow.add_conditional_edges("recover", route_after_recovery, {
        "execute": "execute",
        END: END
    })

    # compile runnable application
    return workflow.compile()
