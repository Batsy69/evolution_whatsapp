frappe.ui.form.on("WhatsApp Message", {
    refresh(frm) {
        if (!frm.is_new() && frm.doc.status === "Failed") {
            frm.set_intro(__("This message failed to send. See the Error field below."), "red");
        } else if (!frm.is_new() && frm.doc.status === "Sent") {
            frm.set_intro(__("Sent."), "green");
        }
    },
});
