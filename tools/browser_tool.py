from typing import Dict, Any, Optional
from pathlib import Path
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
                "enum": ["navigate", "fill", "click", "get_text", "screenshot"],
                "description": "Browser action to execute."
            },
            "url": {"type": "string", "description": "Target webpage URL"},
            "selector": {"type": "string", "description": "CSS selector to interact with"},
            "value": {"type": "string", "description": "Text to fill into an input field"},
            "screenshot_path": {"type": "string", "description": "File path to save screenshot"}
        },
        "required": ["action"]
    }

    def __init__(self, headless: bool = True):
        # browser state
        self.headless = headless
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    def _ensure_browser(self) -> Page:
        # launch browser
        if not self._page:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
            self._page = self._browser.new_page()
        return self._page

    def close(self) -> None:
        # close browser
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None
        self._page = None

    def execute(self, action: str, **kwargs) -> ToolResult:
        # route action
        act = action.lower().strip()
        try:
            page = self._ensure_browser()

            if act == "navigate":
                url = kwargs.get("url", "http://127.0.0.1:8000")
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                return ToolResult(success=True, data={"url": page.url, "title": page.title()})

            elif act == "fill":
                sel, val = kwargs.get("selector"), str(kwargs.get("value", ""))
                page.wait_for_selector(sel, timeout=5000)
                page.fill(sel, val)
                return ToolResult(success=True, data={"filled": sel, "value": val})

            elif act == "click":
                sel = kwargs.get("selector")
                page.wait_for_selector(sel, timeout=5000)
                page.click(sel)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                return ToolResult(success=True, data={"clicked": sel, "current_url": page.url})

            elif act == "get_text":
                sel = kwargs.get("selector", "body")
                page.wait_for_selector(sel, timeout=5000)
                txt = page.inner_text(sel)
                return ToolResult(success=True, data={"text": txt.strip()[:1000]})

            elif act == "screenshot":
                path = kwargs.get("screenshot_path", "screenshot.png")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=path)
                return ToolResult(success=True, data={"screenshot_path": str(Path(path).resolve())})

            return ToolResult(success=False, error=f"Unknown browser action: '{action}'")

        except Exception as e:
            return ToolResult(success=False, error=f"Browser action '{action}' failed: {str(e)}")
