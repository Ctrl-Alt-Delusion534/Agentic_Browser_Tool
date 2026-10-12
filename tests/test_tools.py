from pathlib import Path
import threading
import time
import pytest
import uvicorn
from company_portal.server import app
from company_portal.database import reset_db
from company_portal.generate_fixtures import create_all_fixtures, SAMPLE_DIR
from tools.base import BaseTool, ToolResult
from tools.registry import ToolRegistry
from tools.document_tool import DocumentParserTool
from tools.enterprise_tool import EnterpriseApiTool
from tools.browser_tool import BrowserTool



@pytest.fixture(autouse=True)
def clean_db():
    # clean db
    reset_db()
    yield
    # reset db
    reset_db()


def test_tool_registry():
    # init registry
    reg = ToolRegistry()
    parser = DocumentParserTool()
    api = EnterpriseApiTool()

    # register tools
    reg.register(parser)
    reg.register(api)
    assert len(reg.list_tools()) == 2
    assert "parse_document" in reg.list_tools()
    assert "enterprise_api" in reg.list_tools()

    # check schemas
    schemas = reg.get_schemas()
    assert len(schemas) == 2
    assert any(s["name"] == "parse_document" for s in schemas)

    # execute unknown
    bad_res = reg.execute("unknown_tool", action="test")
    assert bad_res.success is False
    assert "not found" in bad_res.error


def test_document_parser_tool():
    # ensure fixtures
    create_all_fixtures()
    tool = DocumentParserTool()

    # parse pdf
    pdf_path = SAMPLE_DIR / "Apex_INV_2024_001.pdf"
    pdf_res = tool.execute(file_path=str(pdf_path))
    assert pdf_res.success is True
    assert pdf_res.data["invoice_number"] == "INV-2024-001"
    assert pdf_res.data["amount"] == 4500.0
    assert "APEX" in pdf_res.data["vendor_name"].upper()

    # parse docx
    docx_path = SAMPLE_DIR / "GlobalLogistics_INV_8821.docx"
    docx_res = tool.execute(file_path=str(docx_path))
    assert docx_res.success is True
    assert docx_res.data["invoice_number"] == "GL-INV-8821"
    assert docx_res.data["amount"] == 12850.75
    assert "GLOBAL" in docx_res.data["vendor_name"].upper()


def test_enterprise_api_tool():
    # init tool
    tool = EnterpriseApiTool()

    # create invoice
    res_create = tool.execute(
        action="create",
        vendor_name="Apex Technologies",
        invoice_number="INV-2024-001",
        amount=4500.0,
        due_date="2026-11-15"
    )
    assert res_create.success is True
    assert res_create.data["status"] == "success"

    # get invoice
    res_get = tool.execute(action="get", invoice_number="INV-2024-001")
    assert res_get.success is True
    assert res_get.data["invoice"]["amount"] == 4500.0

    # list invoices
    res_list = tool.execute(action="list")
    assert res_list.success is True
    assert len(res_list.data["invoices"]) == 1

    # reset portal
    res_reset = tool.execute(action="reset")
    assert res_reset.success is True


def test_browser_tool():
    # init browser
    tool = BrowserTool(headless=True)
    shot_path = Path("artifacts/test_portal.png")

    try:
        # navigate portal
        nav = tool.execute("navigate", url="http://127.0.0.1:8000")
        assert nav.success is True

        # fill form
        tool.execute("fill", selector="#vendor_name", value="Global Logistics Inc.")
        tool.execute("fill", selector="#invoice_number", value="GL-INV-8821")
        tool.execute("fill", selector="#amount", value="12850.75")
        tool.execute("fill", selector="#due_date", value="2026-11-20")

        # click submit
        click_res = tool.execute("click", selector="#submit_btn")
        assert click_res.success is True

        # inspect text
        text_res = tool.execute("get_text", selector="#invoices_table")
        assert text_res.success is True
        assert "GL-INV-8821" in text_res.data["text"]

        # take screenshot
        shot_res = tool.execute("screenshot", screenshot_path=str(shot_path))
        assert shot_res.success is True
        assert shot_path.exists()

    finally:
        # close browser
        tool.close()
