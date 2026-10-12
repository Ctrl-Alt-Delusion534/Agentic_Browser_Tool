import os
from typing import Dict, Any, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright, Browser, Page, Playwright
from tools.base import BaseTool, ToolResult


class BrowserTool(BaseTool):
    # tool metadata
    name = "browser_tool"
    description = "Controls a web browser to navigate, click, fill forms, and take screenshots."
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["navigate", "fill", "click", "get_text", "screenshot", "submit_invoice"],
                "description": "Browser action to execute."
            },
            "url": {"type": "string", "description": "Target webpage URL"},
            "selector": {"type": "string", "description": "CSS selector to interact with"},
            "value": {"type": "string", "description": "Text to fill into an input field"},
            "screenshot_path": {"type": "string", "description": "File path to save screenshot"},
            "vendor_name": {"type": "string", "description": "submit_invoice: vendor company name"},
            "invoice_number": {"type": "string", "description": "submit_invoice: invoice reference number"},
            "amount": {"type": "number", "description": "submit_invoice: total amount in USD"},
            "due_date": {"type": "string", "description": "submit_invoice: due date YYYY-MM-DD"}
        },
        "required": ["action"]
    }

    def __init__(self, headless: Optional[bool] = None):
        # browser state
        self.headless = headless
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    def _ensure_browser(self) -> Page:
        # launch browser
        if not self._page:
            env_val = os.getenv("AGENT_HEADLESS", "false").lower()
            if self.headless is not None:
                is_headless = self.headless
            else:
                is_headless = (env_val == "true")
            if env_val == "false":
                is_headless = False

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=is_headless,
                slow_mo=800,
                args=["--start-maximized"]
            )
            self._page = self._browser.new_page(no_viewport=True)
        return self._page

    def _close_internal(self) -> None:
        # cleanup browser
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None
        self._page = None

    def close(self) -> None:
        # worker shutdown
        try:
            self._executor.submit(self._close_internal).result(timeout=10)
        finally:
            self._executor.shutdown(wait=False)

    def _run_action(self, action: str, kwargs: Dict[str, Any]) -> ToolResult:
        # execute action
        page = self._ensure_browser()

        if action == "navigate":
            url = kwargs.get("url", "http://127.0.0.1:8000")
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            return ToolResult(success=True, data={"url": page.url, "title": page.title()})

        elif action == "fill":
            sel, val = kwargs.get("selector"), str(kwargs.get("value", ""))
            page.wait_for_selector(sel, timeout=10000)
            page.fill(sel, val)
            return ToolResult(success=True, data={"filled": sel, "value": val})

        elif action == "click":
            sel = kwargs.get("selector")
            page.wait_for_selector(sel, timeout=10000)
            page.click(sel)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            return ToolResult(success=True, data={"clicked": sel, "current_url": page.url})

        elif action == "get_text":
            sel = kwargs.get("selector", "body")
            page.wait_for_selector(sel, timeout=5000)
            txt = page.inner_text(sel)
            return ToolResult(success=True, data={"text": txt.strip()[:1000]})

        elif action == "screenshot":
            path = kwargs.get("screenshot_path", "screenshot.png")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=path)
            return ToolResult(success=True, data={"screenshot_path": str(Path(path).resolve())})

        elif action == "submit_invoice":
            url = kwargs.get("url", "http://127.0.0.1:8000")
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.fill("#vendor_name", str(kwargs.get("vendor_name", "")))
            page.fill("#invoice_number", str(kwargs.get("invoice_number", "")))
            page.fill("#amount", str(kwargs.get("amount", "")))
            page.fill("#due_date", str(kwargs.get("due_date", "")))
            page.click("#submit_btn")
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            shot_path = Path("artifacts/latest_submission.png")
            shot_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                page.screenshot(path=str(shot_path))
            except Exception:
                pass
            return ToolResult(success=True, data={"submitted": kwargs.get("invoice_number"), "url": page.url, "screenshot": str(shot_path)})

        return ToolResult(success=False, error=f"Unknown browser action: '{action}'")

    def execute(self, action: str, **kwargs) -> ToolResult:
        # submit worker
        act = action.lower().strip()
        try:
            future = self._executor.submit(self._run_action, act, kwargs)
            return future.result(timeout=30)
        except Exception as e:
            return ToolResult(success=False, error=f"Browser action '{action}' failed: {str(e)}")
