from typing import Dict, Any, Optional
import httpx
from tools.base import BaseTool, ToolResult


class EnterpriseApiTool(BaseTool):
    # tool metadata
    name = "enterprise_api"
    description = "Communicates with the CentrAlign ERP API to query, submit, or verify invoices."
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "get", "reset"],
                "description": "API action: 'list', 'create', 'get', or 'reset'."
            },
            "vendor_name": {"type": "string", "description": "Vendor company name"},
            "invoice_number": {"type": "string", "description": "Invoice reference number"},
            "amount": {"type": "number", "description": "Total amount in USD"},
            "due_date": {"type": "string", "description": "Payment due date YYYY-MM-DD"},
        },
        "required": ["action"]
    }

    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        # server url
        self.base_url = base_url.rstrip("/")

    def _req(self, method: str, path: str, **kwargs) -> ToolResult:
        # http request
        try:
            with httpx.Client(base_url=self.base_url, timeout=5.0) as client:
                res = client.request(method, path, **kwargs)
                if res.status_code in [200, 201]:
                    return ToolResult(success=True, data=res.json())
                if res.status_code == 404:
                    return ToolResult(success=False, error="Invoice not found.")
                if res.status_code == 409:
                    return ToolResult(success=False, error="Invoice already exists in ledger.")
                return ToolResult(success=False, error=f"HTTP {res.status_code}: {res.text}")
        except Exception as e:
            return ToolResult(success=False, error=f"Network error: {str(e)}")

    def execute(self, action: str, **kwargs) -> ToolResult:
        # route action
        act = action.lower().strip()
        if act == "list":
            return self._req("GET", "/api/invoices")
        elif act == "create":
            payload = {k: kwargs[k] for k in ["vendor_name", "invoice_number", "amount", "due_date"] if k in kwargs}
            return self._req("POST", "/api/invoices", json=payload)
        elif act == "get":
            return self._req("GET", f"/api/invoices/{kwargs.get('invoice_number', '')}")
        elif act == "reset":
            return self._req("POST", "/api/reset", headers={"Accept": "application/json"})
        return ToolResult(success=False, error=f"Unsupported action: '{action}'")
