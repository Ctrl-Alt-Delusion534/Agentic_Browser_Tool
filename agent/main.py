import warnings
warnings.filterwarnings("ignore")

import sys
import os
import time
import threading
import urllib.request
from pathlib import Path

# setup root path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.graph import create_agent_graph
from agent.nodes import reset_shared_registry
from company_portal.generate_fixtures import create_all_fixtures, generate_pdf_invoice
from tools.document_tool import DocumentParserTool


def get_inbox_files() -> list:
    # scan incoming directory
    sdir = Path("company_portal/sample_files")
    sdir.mkdir(parents=True, exist_ok=True)
    files = sorted(list(sdir.glob("*.pdf")) + list(sdir.glob("*.docx")))
    parser = DocumentParserTool()
    items = []
    for f in files:
        res = parser.execute(str(f))
        items.append(res.data if res.success and res.data else {"file_name": f.name})
    return items


def show_inbox():
    # render inbox table
    invoices = get_inbox_files()
    print("-" * 75)
    print("CENTRALIGN INCOMING INBOX (Pending Processing)")
    print("-" * 75)
    print(f"{'Vendor':<24} {'Invoice':<14} {'Amount':<12} {'Due Date':<12} {'File'}")
    print("-" * 75)
    for inv in invoices:
        v = (inv.get("vendor_name") or "Unknown")[:22]
        num = (inv.get("invoice_number") or "N/A")[:12]
        amt = f"${inv.get('amount', 0.0):,.2f}"
        due = inv.get("due_date") or "N/A"
        print(f"{v:<24} {num:<14} {amt:<12} {due:<12} {inv.get('file_name', '')}")
    print("-" * 75)
    print(f"Total: {len(invoices)} document(s) ready.\n")


def ensure_server():
    # guarantee portal running
    create_all_fixtures()
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/api/invoices", timeout=0.5)
    except Exception:
        import uvicorn
        from company_portal.server import app
        srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
        threading.Thread(target=srv.run, daemon=True).start()
        for _ in range(30):
            time.sleep(0.2)
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/api/invoices", timeout=0.3)
                break
            except Exception:
                pass


def handle_add_invoice():
    # stage custom document
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--invoice", default="INV-999")
    parser.add_argument("--amount", type=float, default=5000.0)
    parser.add_argument("--due", default="2026-12-31")
    args, _ = parser.parse_known_args([a for a in sys.argv[1:] if a != "--add-invoice"])
    p = generate_pdf_invoice(args.vendor, args.invoice, args.amount, args.due)
    print(f"Staged invoice: {p.name}")
    show_inbox()


def print_completion(result: dict):
    # display completion summary
    status = result.get("status")
    print("-" * 60)
    print(f"Execution Status: {status.upper()}")
    for h in result.get("history", []):
        tag = "OK" if h.get("success") else "FAIL"
        err = f" ({h.get('error')})" if not h.get("success") and h.get("error") else ""
        print(f" [{tag}] {h.get('step')}{err}")
    print("-" * 60)

    if status == "completed":
        d = result.get("extracted_data", {})
        print(f"Vendor:   {d.get('vendor_name', 'N/A')}")
        print(f"Invoice:  {d.get('invoice_number', 'N/A')}")
        print(f"Amount:   ${d.get('amount', 0.0):,.2f}")
        print(f"Due Date: {d.get('due_date', 'N/A')}")
        pow_doc = result.get("proof_of_work")
        if pow_doc and pow_doc.get("audit_hash"):
            print(f"Audit:    SHA-256 ({pow_doc['audit_hash']})")
        print("Outcome:  Recorded into ERP and verified in ledger.")
    elif status == "not_found":
        print("Notice:   Requested invoice not found in incoming repository files.")
        print("Action:   Run with --list to view pending files or provide record fields directly.")
    print("-" * 60)


def run():
    # parse execution mode
    if "--headed" in sys.argv:
        os.environ["AGENT_HEADLESS"] = "false"

    ensure_server()

    if "--list" in sys.argv or "--inbox" in sys.argv:
        show_inbox()
        return

    if "--add-invoice" in sys.argv:
        handle_add_invoice()
        return

    if "--reset" in sys.argv:
        from company_portal.database import reset_db
        reset_db()

    # handle direct file
    if "--file" in sys.argv:
        fidx = sys.argv.index("--file")
        if fidx + 1 < len(sys.argv):
            src_path = Path(sys.argv[fidx + 1])
            if src_path.exists():
                dest = Path("company_portal/sample_files") / src_path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src_path.resolve() != dest.resolve():
                    import shutil
                    shutil.copy2(src_path, dest)
                goal = f"Extract and record invoice from {src_path.name}"
            else:
                print(f"Error: File not found at {src_path}")
                return

    # parse target goal
    if "--file" not in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        goal = args[0] if args else "Discover, extract, and record all pending invoices into ERP"

    if any(q in goal.lower() for q in ["what invoices", "list invoices", "show inbox"]):
        show_inbox()
        return {"status": "completed", "invoices": get_inbox_files()}

    print("-" * 60)
    print(f"CENTRALIGN TASK WORKER | Goal: {goal}")
    print(f"Mode: {'Headed Browser' if os.getenv('AGENT_HEADLESS') == 'false' else 'Headless'}")
    print("-" * 60)

    try:
        # execute graph pipeline
        graph = create_agent_graph()
        result = graph.invoke({"goal": goal})
    finally:
        # cleanup browser instance
        reset_shared_registry()

    print_completion(result)
    return result


if __name__ == "__main__":
    # execute agent entrypoint
    run()
