frappe.ui.form.on("WhatsApp Message", {
    refresh(frm) {
        const indicator = {
            "Sent": "green",
            "Queued": "blue",
            "Failed": "red",
        }[frm.doc.status] || "grey";
        frm.page.set_indicator(__(frm.doc.status || "Unknown"), indicator);
    },
});
