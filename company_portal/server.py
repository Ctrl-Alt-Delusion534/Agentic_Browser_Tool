import sys
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
import sqlite3

# resolve root path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from company_portal.database import (
    init_db,
    add_invoice,
    get_all_invoices,
    get_invoice_by_number,
    reset_db,
)

# setup templates
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# request schema
class InvoiceCreateRequest(BaseModel):
    vendor_name: str = Field(..., description="Vendor name")
    invoice_number: str = Field(..., description="Unique invoice identifier")
    amount: float = Field(..., gt=0, description="Invoice amount in USD")
    due_date: str = Field(..., description="Due date in YYYY-MM-DD")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # init database
    init_db()
    yield

from fastapi.staticfiles import StaticFiles

# init app
app = FastAPI(
    title="CentrAlign Enterprise Billing Portal",
    lifespan=lifespan
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

def get_incoming_files_list():
    # inspect sample files
    sample_dir = Path(__file__).parent / "sample_files"
    if not sample_dir.exists():
        return []
    from tools.document_tool import DocumentParserTool
    parser = DocumentParserTool()
    files = sorted(list(sample_dir.glob("*.pdf")) + list(sample_dir.glob("*.docx")))
    items = []
    for f in files:
        res = parser.execute(str(f))
        if res.success and res.data:
            items.append(res.data)
        else:
            items.append({"file_name": f.name, "vendor_name": "Unknown", "invoice_number": "N/A", "amount": 0.0, "due_date": "N/A"})
    return items


# html dashboard
@app.get("/", response_class=HTMLResponse)
async def portal_dashboard(request: Request, message: Optional[str] = None):
    # render dashboard
    invoices = get_all_invoices()
    incoming = get_incoming_files_list()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"invoices": invoices, "incoming_invoices": incoming, "message": message}
    )
    
@app.post("/invoices", response_class=HTMLResponse)
async def handle_form_submission(
    request: Request,
    vendor_name: str = Form(...),
    invoice_number: str = Form(...),
    amount: float = Form(...),
    due_date: str = Form(...)
):
    # submit form
    try:
        record = add_invoice(vendor_name, invoice_number, amount, due_date)
        msg = f"Successfully recorded invoice {record['invoice_number']} for {record['vendor_name']}!"
    except sqlite3.IntegrityError:
        msg = f"Error: Invoice number '{invoice_number}' already exists!"
    
    invoices = get_all_invoices()
    incoming = get_incoming_files_list()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"invoices": invoices, "incoming_invoices": incoming, "message": msg}
    )


@app.post("/upload", response_class=RedirectResponse)
async def handle_file_upload(file: UploadFile = File(...)):
    # save incoming file
    dest_dir = Path(__file__).parent / "sample_files"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename
    dest_path.write_bytes(await file.read())
    return RedirectResponse(
        url=f"/?message=Uploaded+{file.filename}+to+inbox",
        status_code=status.HTTP_303_SEE_OTHER
    )


# rest endpoints
@app.get("/api/inbox")
async def api_list_inbox():
    # list inbox files
    return {"inbox": get_incoming_files_list()}

@app.get("/api/invoices")
async def api_list_invoices():
    # list records
    return {"invoices": get_all_invoices()}

@app.post("/api/invoices", status_code=status.HTTP_201_CREATED)
async def api_create_invoice(payload: InvoiceCreateRequest):
    # create record
    try:
        record = add_invoice(payload.vendor_name, payload.invoice_number, payload.amount, payload.due_date)
        return {"status": "success", "invoice": record}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Invoice '{payload.invoice_number}' already exists.")

@app.get("/api/invoices/{invoice_number}")
async def api_get_invoice(invoice_number: str):
    # fetch record
    record = get_invoice_by_number(invoice_number)
    if not record:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return {"status": "found", "invoice": record}

@app.post("/api/reset")
async def api_reset_database(request: Request):
    # reset database
    reset_db()
    if "application/json" in request.headers.get("accept", ""):
        return {"status": "success", "message": "Database reset cleanly."}
    return RedirectResponse(url="/?message=Database+reset+to+empty+baseline", status_code=status.HTTP_303_SEE_OTHER)


if __name__ == "__main__":
    # run server
    import uvicorn
    print("Starting CentrAlign Company Portal on http://127.0.0.1:8000 ...")
    uvicorn.run("company_portal.server:app", host="127.0.0.1", port=8000, reload=True)