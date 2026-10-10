// portal client logic

document.addEventListener("DOMContentLoaded", () => {
    // filter ledger table
    const searchInput = document.getElementById("search_input");
    const tableBody = document.querySelector("#invoices_table tbody");

    if (searchInput && tableBody) {
        searchInput.addEventListener("input", (e) => {
            const query = e.target.value.toLowerCase().trim();
            const rows = tableBody.querySelectorAll("tr");

            rows.forEach((row) => {
                if (row.classList.contains("empty-row")) return;
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(query) ? "" : "none";
            });
        });
    }

    // copy audit hash
    document.querySelectorAll(".copy-trigger").forEach((el) => {
        el.addEventListener("click", async () => {
            const textToCopy = el.getAttribute("data-copy") || el.textContent.trim();
            try {
                await navigator.clipboard.writeText(textToCopy);
                const originalTitle = el.title;
                el.title = "Copied!";
                setTimeout(() => {
                    el.title = originalTitle;
                }, 1500);
            } catch (err) {
                console.error("Clipboard copy failed:", err);
            }
        });
    });

    // dismiss alert box
    const alertBox = document.getElementById("status_alert");
    if (alertBox) {
        setTimeout(() => {
            alertBox.style.transition = "opacity 0.4s ease, transform 0.4s ease";
            alertBox.style.opacity = "0";
            alertBox.style.transform = "translateY(-6px)";
            setTimeout(() => alertBox.remove(), 400);
        }, 5000);
    }
});
