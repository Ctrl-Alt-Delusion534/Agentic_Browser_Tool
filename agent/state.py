from typing import TypedDict, List, Dict, Any, Optional


class AgentState(TypedDict, total=False):
    # original user goal
    goal: str
    # ordered task plan
    plan: List[str]
    # active step index
    step_index: int
    # extracted invoice data
    extracted_data: Dict[str, Any]
    # execution action logs
    history: List[Dict[str, Any]]
    # active error message
    error: Optional[str]
    # retry budget counter
    retries: int
    # execution workflow status
    status: str
    # step output result
    last_result: Optional[Dict[str, Any]]
    # step action type
    action_type: Optional[str]
    # verified proof document
    proof_of_work: Optional[Dict[str, Any]]
    # operator approval flag
    hitl_approved: Optional[bool]
