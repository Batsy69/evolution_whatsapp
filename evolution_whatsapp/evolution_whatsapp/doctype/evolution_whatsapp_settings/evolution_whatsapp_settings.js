frappe.ui.form.on("Evolution Whatsapp Settings", {
    refresh(frm) {
        frm.add_custom_button(__("Test Connection"), () => {
            frappe.call({
                method: "evolution_whatsapp.evolution_whatsapp.doctype.evolution_whatsapp_settings.evolution_whatsapp_settings.test_connection",
                freeze: true,
                freeze_message: __("Pinging Evolution server..."),
                callback: (r) => {
                    if (r.message && r.message.ok) {
                        frappe.show_alert({
                            message: __("Connected to Evolution server."),
                            indicator: "green",
                        });
                    }
                },
            });
        });
    },
});
