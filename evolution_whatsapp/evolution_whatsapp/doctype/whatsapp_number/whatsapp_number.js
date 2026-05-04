frappe.ui.form.on("WhatsApp Number", {
    refresh(frm) {
        if (frm.is_new()) return;

        // Status indicator (visible to everyone with read access).
        const indicator = {
            "Connected": "green",
            "Awaiting QR Scan": "orange",
            "Connecting": "blue",
            "Pending": "grey",
            "Disconnected": "red",
            "Error": "red",
        }[frm.doc.connection_status] || "grey";
        frm.page.set_indicator(__(frm.doc.connection_status || "Unknown"), indicator);

        // Manager-only controls. Non-managers have read-only access and
        // shouldn't see Assign / Disconnect / QR refresh.
        if (!is_manager()) {
            stop_polling(frm);
            return;
        }

        frm.add_custom_button(__("Assign Users"), () => open_assign_users_dialog(frm), __("Actions"));

        if (["Awaiting QR Scan", "Connecting", "Pending", "Disconnected", "Error"].includes(frm.doc.connection_status)) {
            frm.add_custom_button(__("Refresh QR"), () => refresh_qr(frm));
            frm.add_custom_button(__("Check Status"), () => check_status(frm));
            refresh_qr(frm, /* silent */ true);
            start_polling(frm);
        } else {
            stop_polling(frm);
        }

        if (frm.doc.connection_status === "Connected") {
            frm.add_custom_button(__("Check Status"), () => check_status(frm));
            frm.add_custom_button(__("Disconnect"), () => disconnect_number(frm), __("Actions"));
        }
    },

    onhide(frm) {
        stop_polling(frm);
    },
});


function is_manager() {
    const roles = (frappe.user_roles || frappe.boot.user.roles || []);
    return roles.includes("WhatsApp Manager") || roles.includes("System Manager") || roles.includes("Administrator");
}

// --------------------------------------------------------------------------
// QR + status
// --------------------------------------------------------------------------

function refresh_qr(frm, silent) {
    frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.get_qr",
        args: { name: frm.doc.name },
        freeze: !silent,
        freeze_message: __("Fetching QR code..."),
        callback: (r) => {
            const mount = frm.fields_dict.qr_html.$wrapper.find("#ew-qr-mount");
            if (r.message && r.message.base64) {
                const src = r.message.base64.startsWith("data:")
                    ? r.message.base64
                    : `data:image/png;base64,${r.message.base64}`;
                mount.html(`
                    <div class="text-center" style="padding: 16px;">
                        <img src="${src}" alt="QR Code" style="max-width: 280px; border: 1px solid #eee; padding: 10px; border-radius: 8px;" />
                        <p class="text-muted small mt-3">
                            ${__("Open WhatsApp on the phone for this number → Settings → Linked Devices → Link a Device → scan.")}
                        </p>
                        <p class="text-muted small">${__("QR refreshes automatically. Status updates in seconds after scan.")}</p>
                    </div>
                `);
            } else if (r.message && r.message.error) {
                mount.html(`<div class="text-muted">${frappe.utils.escape_html(r.message.error)}</div>`);
            }
        },
    });
}

function check_status(frm) {
    frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.check_status",
        args: { name: frm.doc.name },
        callback: () => frm.reload_doc(),
    });
}

function disconnect_number(frm) {
    frappe.confirm(
        __("Disconnect this number? Users will not be able to send until it's reconnected via QR scan."),
        () => {
            frappe.call({
                method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.disconnect",
                args: { name: frm.doc.name },
                freeze: true,
                callback: () => frm.reload_doc(),
            });
        }
    );
}

// --------------------------------------------------------------------------
// Assign Users
// --------------------------------------------------------------------------

function open_assign_users_dialog(frm) {
    const existing = (frm.doc.assigned_users || []).map(r => r.user);

    const d = new frappe.ui.Dialog({
        title: __("Assign Users to {0}", [frm.doc.display_name]),
        fields: [
            {
                fieldtype: "MultiSelectPills",
                fieldname: "users",
                label: __("Users"),
                options: "User",
                default: existing,
                get_data: function(txt) {
                    return frappe.db.get_link_options("User", txt, { enabled: 1 });
                },
            },
            {
                fieldtype: "HTML",
                fieldname: "help",
                options: `<p class="text-muted small">${__("Tick all users who can send WhatsApp messages from this number. Changes apply immediately on Save.")}</p>`,
            },
        ],
        primary_action_label: __("Save"),
        primary_action(values) {
            const users = (values.users || []).map(u => typeof u === "string" ? u : u.value);
            frappe.call({
                method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.assign_users",
                args: { name: frm.doc.name, users: JSON.stringify(users) },
                freeze: true,
                callback: (r) => {
                    if (r.message) {
                        frappe.show_alert({
                            message: __("Assigned {0} user(s).", [r.message.count]),
                            indicator: "green",
                        });
                        d.hide();
                        frm.reload_doc();
                    }
                },
            });
        },
    });
    d.show();
}

// --------------------------------------------------------------------------
// Polling
// --------------------------------------------------------------------------

function start_polling(frm) {
    stop_polling(frm);
    let elapsed = 0;
    frm._ew_poll = setInterval(() => {
        elapsed += 5;
        if (elapsed > 300) { stop_polling(frm); return; }
        frappe.call({
            method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.check_status",
            args: { name: frm.doc.name },
            silent: true,
            callback: (r) => {
                if (r.message && r.message.status === "Connected") {
                    stop_polling(frm);
                    frappe.show_alert({
                        message: __("WhatsApp connected: {0}", [r.message.phone_number || ""]),
                        indicator: "green",
                    });
                    frm.reload_doc();
                }
            },
        });
    }, 5000);
}

function stop_polling(frm) {
    if (frm._ew_poll) { clearInterval(frm._ew_poll); frm._ew_poll = null; }
}
