import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from groq import Groq

# load environment variables from absolute path
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

# shared agent persona
SYSTEM_PROMPT = (
    "You are CentrAlign, an autonomous enterprise AI worker that operates a company's invoice inbox "
    "and internal ERP portal through tools. Reason carefully about what the user actually wants. "
    "Questions are answered without side effects; the ERP is only modified when the user explicitly asks "
    "to enter, record, submit or process invoices. Never invent invoice data. Return valid JSON only."
)


class GroqBrain:
    def __init__(self, api_key: Optional[str] = None):
        # initialize groq client
        load_dotenv(dotenv_path=ENV_PATH, override=True)
        raw_key = api_key or os.getenv("GROQ_API_KEY", "")
        key = str(raw_key).strip().strip('"').strip("'")
        self.client = Groq(api_key=key, timeout=30.0, max_retries=2) if key and not key.startswith("your_") else None
        self.model = str(os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")).strip().strip('"').strip("'")

    def _ask(self, prompt: str, system: str = SYSTEM_PROMPT) -> Dict[str, Any]:
        # query llm for json
        if not self.client:
            load_dotenv(dotenv_path=ENV_PATH, override=True)
            raw_key = os.getenv("GROQ_API_KEY", "")
            key = str(raw_key).strip().strip('"').strip("'")
            if key and not key.startswith("your_"):
                self.client = Groq(api_key=key, timeout=30.0, max_retries=2)
            if not self.client:
                raise RuntimeError("GROQ_API_KEY is not configured in .env or system environment.")
        models_to_try = [self.model, "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
        models_to_try = list(dict.fromkeys(models_to_try))

        last_err = None
        for current_model in models_to_try:
            for attempt in range(2):
                try:
                    resp = self.client.chat.completions.create(
                        model=current_model,
                        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                        response_format={"type": "json_object"},
                        temperature=0.0
                    )
                    return json.loads(resp.choices[0].message.content)
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    if "rate_limit" in err_str or "429" in err_str:
                        break
                    time.sleep(1)
        if last_err:
            raise last_err

    def plan(self, goal: str, context: str, tools: List[Dict[str, Any]]) -> List[str]:
        # decompose goal into steps
        raw = self._ask(
            f"GOAL: {goal}\n\nENVIRONMENT:\n{context}\n\nTOOLS:\n{json.dumps(tools)}\n\n"
            "Decompose the goal into the minimal ordered list of steps. Each step is exactly one tool call, "
            "written in plain English with exact file paths and values. Rules:\n"
            "- Information requests only read data (parse_document, enterprise_api list/get). Never submit.\n"
            "- To enter an invoice into the ERP: parse its file first, then submit it with browser_tool "
            "action submit_invoice (enterprise_api create is the fallback). ERP writes are verified "
            "automatically, so never add verification steps.\n"
            "- If the goal itself states vendor, invoice number, amount and due date, submit those values "
            "directly without any file.\n"
            "- 'Latest' or 'newest' means the most recently modified inbox file.\n"
            "- Skip invoices already in the ERP ledger (an invoice is only in the ledger if BOTH vendor name and invoice number match an existing entry). Different companies can legitimately have identical invoice numbers.\n"
            "- Return an empty plan if the goal is fully answerable from the environment, or asks to enter an "
            "invoice that is neither in the inbox nor fully specified in the goal.\n"
            'Return {"thought": "<short reasoning>", "plan": ["step 1", "step 2"]}'
        )
        return [str(s) for s in raw.get("plan") or []]

    def reason(self, goal: str, step: str, facts: Dict[str, Any], history: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        # choose next tool call
        raw = self._ask(
            f"GOAL: {goal}\nCURRENT STEP: {step}\n\n"
            f"KNOWN FACTS: {json.dumps(facts, default=str)}\n"
            f"PREVIOUS ACTIONS: {json.dumps(history[-6:], default=str)}\n\n"
            f"TOOLS:\n{json.dumps(tools)}\n\n"
            "Choose the single tool call that completes the current step. Take parameter values only from the "
            "step, known facts or previous observations. Dates must be YYYY-MM-DD and amounts numeric. "
            "If a previous attempt at this step failed, adapt: fix the parameters or switch to an alternative tool. "
            "If the step needs no action, set tool to null.\n"
            'Return {"thought": "<short reasoning>", "tool": "<tool name or null>", "params": {}}'
        )
        return {"tool": raw.get("tool"), "params": raw.get("params") or {}, "thought": raw.get("thought", "")}

    def respond(self, goal: str, context: str, facts: Dict[str, Any], history: List[Dict[str, Any]]) -> str:
        # synthesize final answer
        raw = self._ask(
            f"GOAL: {goal}\n\nENVIRONMENT:\n{context}\n\n"
            f"KNOWN FACTS: {json.dumps(facts, default=str)}\n"
            f"ACTIONS TAKEN: {json.dumps(history, default=str)}\n\n"
            "Write the final reply to the user. Answer exactly what was asked, concisely, using only the "
            "information above. State clearly what was changed in the ERP, if anything. If something failed "
            "or was not found, say so honestly.\n"
            'Return {"answer": "<reply>"}'
        )
        return str(raw.get("answer", "")).strip()

    def extract_document_fields(self, text: str) -> Dict[str, Any]:
        # analyze document text with llm
        if not self.client or not text.strip():
            return {}
        try:
            data = self._ask(
                "Extract structured invoice fields from this document text. "
                "Return a JSON object with keys: "
                "'vendor_name' (str), 'invoice_number' (str), 'amount' (float), 'due_date' (YYYY-MM-DD format). "
                "If any field cannot be found, set its value to null.\n\n"
                f"DOCUMENT TEXT:\n{text[:4000]}",
                system="You are a precise invoice extraction engine. Return valid JSON only."
            )
            return {k: v for k, v in data.items() if v not in (None, "", "null")}
        except Exception:
            return {}


# primary brain export
AgentBrain = GroqBrain
