import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from groq import Groq

# load environment variables
load_dotenv()


class GroqBrain:
    def __init__(self, api_key: Optional[str] = None):
        # initialize groq client
        key = api_key or os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.client = Groq(api_key=key) if key and not key.startswith("your_") else None
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.direct_data: Dict[str, Any] = {}

    def plan(self, goal: str, files: List[str]) -> List[str]:
        # generate plan steps
        self.direct_data = {}
        if self.client:
            # prompt groq model
            system_msg = (
                "You are an autonomous enterprise task worker. Return JSON with 'plan' (list of strings) "
                "and optional 'extracted_data' (dict with vendor_name, invoice_number, amount, due_date)."
            )
            user_msg = (
                f"User Goal: {goal}\n"
                f"Available Files: {files}\n"
                "Instructions:\n"
                "1. If the goal specifies explicit invoice/audit parameters directly (e.g. vendor name, amount, date) to enter into the records without relying on a file: "
                "return plan: [\"submit:direct\", \"verify:ledger\"] and extracted_data: {\"vendor_name\": str, \"invoice_number\": str, \"amount\": float, \"due_date\": \"YYYY-MM-DD\"}. "
                "If no invoice number is in the goal, set invoice_number to e.g. '<VENDOR>-AUDIT-<AMOUNT>'.\n"
                "2. If the goal refers to an invoice file in Available Files, select that file and return steps 'parse:<path>', 'submit:<filename>', 'verify:ledger'.\n"
                "3. If the goal refers to an unknown company file that does NOT exist in Available Files (and gives no direct data), return empty plan: {\"plan\": []}.\n"
                "4. If the goal wants all invoices, select all files.\n"
                "Return JSON object: {\"plan\": [...], \"extracted_data\": {...}}"
            )
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                raw = json.loads(response.choices[0].message.content)
                self.direct_data = raw.get("extracted_data") or {}
                if self.direct_data and not self.direct_data.get("invoice_number"):
                    v = self.direct_data.get("vendor_name", "AUDIT").upper()
                    self.direct_data["invoice_number"] = f"{v}-AUDIT-01"
                plan = raw.get("plan") or raw.get("steps") or (raw if isinstance(raw, list) else None)
                if isinstance(plan, list):
                    if len(plan) >= 2 or len(plan) == 0:
                        print(f"Reasoning Engine: Groq API ({self.model})")
                        return plan
            except Exception as e:
                # print fallback reason
                err_info = "Rate limit reached" if "429" in str(e) else str(e).splitlines()[0][:50]
                print(f"Reasoning Engine: Fallback Mode ({err_info})")
        else:
            # print missing key
            print("Reasoning Engine: Fallback Mode (Equip GROQ_API_KEY in .env)")

        # detect direct audit
        import re
        goal_lower = goal.lower()
        amt_match = re.search(r"(?:amount|ampunt|\$)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", goal_lower)
        date_match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})", goal)
        if amt_match and date_match:
            raw_date = date_match.group(1).replace("/", "-")
            date_parts = raw_date.split("-")
            formatted_date = f"{date_parts[2]}-{date_parts[1].zfill(2)}-{date_parts[0].zfill(2)}" if len(date_parts[0]) <= 2 else raw_date
            vendor_match = re.search(r"(?:audit|record|enter|vendor)\s+([a-zA-Z0-9_-]+)", goal_lower)
            vname = vendor_match.group(1).capitalize() if vendor_match else "Vendor"
            amt_val = float(amt_match.group(1))
            self.direct_data = {
                "vendor_name": vname,
                "invoice_number": f"{vname.upper()}-AUDIT-{int(amt_val)}",
                "amount": amt_val,
                "due_date": formatted_date
            }
            return ["submit:direct", "verify:ledger"]

        # resolve matching files
        selected_files = files
        if goal and files:
            goal_clean = goal.lower().replace(" ", "").replace("_", "").replace("-", "")
            matches = [
                f for f in files
                if Path(f).stem.lower().split("_")[0] in goal_clean
                or Path(f).stem.lower().replace("_", "") in goal_clean
            ]
            is_targeted = any(w in goal.lower() for w in ["from", "for", "invoice from", "latest invoice"]) or len(matches) > 0
            if matches:
                selected_files = [matches[0]]
            elif is_targeted and not any(w in goal.lower() for w in ["all", "every", "each"]):
                # vendor not found
                return []

        # fallback structured plan
        steps = []
        for f in sorted(selected_files):
            steps.extend([f"parse:{f}", f"submit:{os.path.basename(f)}"])
        return steps + ["verify:ledger"]

    def reason(self, step: str, facts: Dict[str, Any]) -> Dict[str, Any]:
        # resolve tool parameters
        act, _, target = step.partition(":")
        if act == "parse":
            return {"tool": "parse_document", "params": {"file_path": target}}
        if act == "submit":
            return {
                "tool": "browser_tool",
                "params": {
                    "action": "submit_invoice",
                    "vendor_name": facts.get("vendor_name", "Unknown"),
                    "invoice_number": facts.get("invoice_number", "INV-000"),
                    "amount": facts.get("amount", 0.0),
                    "due_date": facts.get("due_date", "2026-12-31"),
                }
            }
        return {"tool": "enterprise_api", "params": {"action": "list"}}


    def extract_document_fields(self, text: str) -> Dict[str, Any]:
        # analyze document text with llm
        if not self.client or not text.strip():
            return {}
        try:
            prompt = (
                "Extract structured invoice fields from this document text. "
                "Return a JSON object with keys: "
                "'vendor_name' (str), 'invoice_number' (str), 'amount' (float), 'due_date' (YYYY-MM-DD format). "
                "If any field cannot be found, set its value to null.\n\n"
                f"DOCUMENT TEXT:\n{text[:4000]}"
            )
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise invoice extraction engine. Return valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            data = json.loads(resp.choices[0].message.content)
            return {
                k: v for k, v in data.items()
                if v is not None and v != "" and v != "null"
            }
        except Exception:
            return {}


# backwards compatibility alias
GeminiBrain = GroqBrain
