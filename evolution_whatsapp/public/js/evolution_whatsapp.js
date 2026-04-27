/**
 * Evolution Whatsapp — global "Send WhatsApp" menu item on every DocType form.
 *
 * UX principles for this build:
 *  - Compact: one screen, no scroll for typical sends
 *  - "Send from": dropdown of WhatsApp Numbers assigned to the current user
 *  - Country code dropdown next to recipient (default from Settings)
 *  - After send: refresh comments/timeline only (no full doc reload)
 *  - Toast on send completion via realtime event
 */

const COMMON_COUNTRY_CODES = [
    { code: "91",  label: "🇮🇳 +91" },
    { code: "1",   label: "🇺🇸 +1" },
    { code: "44",  label: "🇬🇧 +44" },
    { code: "971", label: "🇦🇪 +971" },
    { code: "966", label: "🇸🇦 +966" },
    { code: "65",  label: "🇸🇬 +65" },
    { code: "61",  label: "🇦🇺 +61" },
    { code: "49",  label: "🇩🇪 +49" },
    { code: "33",  label: "🇫🇷 +33" },
    { code: "81",  label: "🇯🇵 +81" },
    { code: "86",  label: "🇨🇳 +86" },
    { code: "880", label: "🇧🇩 +880" },
    { code: "92",  label: "🇵🇰 +92" },
    { code: "94",  label: "🇱🇰 +94" },
];

// --------------------------------------------------------------------------
// Bootstrap: add menu item on every form + global realtime listener
// --------------------------------------------------------------------------

$(document).on("app_ready", function () {
    // Subscribe once to send-completion toasts
    frappe.realtime.on("evolution_whatsapp:message_status", (data) => {
        if (!data) return;
        if (data.status === "Sent") {
            frappe.show_alert({
                message: __("WhatsApp message sent to {0}", [data.to_number || ""]),
                indicator: "green",
            }, 5);
            try {
                const cur = cur_frm;
                if (cur && cur.doctype === data.reference_doctype && cur.docname === data.reference_name) {
                    refresh_timeline(cur);
                    render_whatsapp_section(cur);
                }
            } catch (e) { /* */ }
        } else if (data.status === "Failed") {
            frappe.show_alert({
                message: __("WhatsApp send failed: {0}", [data.error || data.to_number]),
                indicator: "red",
            }, 7);
            try {
                const cur = cur_frm;
                if (cur && cur.doctype === data.reference_doctype && cur.docname === data.reference_name) {
                    refresh_timeline(cur);
                    render_whatsapp_section(cur);
                }
            } catch (e) { /* */ }
        }
    });

    // Hook menu injection + WhatsApp section rendering on EVERY form refresh.
    // We must re-add on every refresh (not just once) because Frappe rebuilds
    // the menu when the form rerenders (e.g. after dialog close, after save,
    // after navigating to a sibling doc). add_menu_item itself is idempotent
    // per call but the menu *array* is reset on rerender, so we always call it.
    const orig_setup = frappe.ui.form.Form.prototype.refresh;
    // Cleaner: use a once-per-form guard but reset on rerender. Easiest is to
    // hook the global router to set up a fresh refresh listener for each route.
    let last_dt = null;
    frappe.router.on("change", () => {
        const route = frappe.get_route();
        if (!(route && route[0] === "Form")) return;
        const dt = route[1];
        if (dt === last_dt) return;
        last_dt = dt;

        // Register form events ONCE per doctype (Frappe dedupes internally
        // by handler identity, but we still guard).
        if (frappe.ui.form._ew_registered_dts && frappe.ui.form._ew_registered_dts[dt]) return;
        frappe.ui.form._ew_registered_dts = frappe.ui.form._ew_registered_dts || {};
        frappe.ui.form._ew_registered_dts[dt] = true;

        frappe.ui.form.on(dt, {
            refresh: function (frm) {
                if (frm.is_new()) return;
                // Always re-add. add_menu_item internally appends to the page menu;
                // Frappe rebuilds the menu on rerender so we need to add fresh each time.
                frm.page.add_menu_item(__("Send WhatsApp"), function () {
                    open_whatsapp_dialog(frm);
                }, /* permanent */ true);

                // Render the WhatsApp messages section in the form sidebar
                render_whatsapp_section(frm);
            },
        });
    });
});


// --------------------------------------------------------------------------
// Refresh timeline / comments without full doc reload
// --------------------------------------------------------------------------

function refresh_timeline(frm) {
    if (!frm) return;
    try {
        if (frm.timeline && frm.timeline.refresh) {
            frm.timeline.refresh();
            return;
        }
        if (frm.comment_box && frm.comment_box.refresh) {
            frm.comment_box.refresh();
        }
    } catch (e) { /* swallow */ }
}


// --------------------------------------------------------------------------
// WhatsApp messages section under each document
// --------------------------------------------------------------------------

function render_whatsapp_section(frm) {
    if (!frm || frm.is_new()) return;
    if (!frm.fields_dict) return;

    // Anchor: append a custom block at the bottom of the form's main area.
    const $anchor = frm.layout.wrapper.find(".form-layout") .first();
    if (!$anchor.length) return;

    // Idempotent: remove old block if present, re-render
    frm.layout.wrapper.find(".ew-messages-block").remove();

    const $block = $(`
        <div class="ew-messages-block" style="margin: 12px 0; padding: 12px 16px; border: 1px solid var(--border-color); border-radius: 6px; background: var(--card-bg);">
            <div class="ew-header" style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                <div style="font-weight:600; font-size: 13px;">
                    <i class="fa fa-whatsapp" style="color:#25D366; margin-right:6px;"></i>
                    ${__("WhatsApp Messages")}
                </div>
                <a class="ew-refresh small text-muted" style="cursor:pointer; font-size:11px;">${__("Refresh")}</a>
            </div>
            <div class="ew-list small text-muted">${__("Loading...")}</div>
        </div>
    `);

    $anchor.append($block);

    $block.find(".ew-refresh").on("click", () => fetch_messages(frm, $block));
    fetch_messages(frm, $block);
}


function fetch_messages(frm, $block) {
    frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_message.whatsapp_message.list_messages_for",
        args: {
            reference_doctype: frm.doctype,
            reference_name: frm.docname,
        },
        silent: true,
        callback: (r) => {
            const rows = r.message || [];
            const $list = $block.find(".ew-list");
            if (!rows.length) {
                $list.html(`<div class="text-muted small">${__("No WhatsApp messages sent for this document yet.")}</div>`);
                return;
            }

            const html = rows.map(m => {
                const status_color = { "Sent": "green", "Queued": "blue", "Failed": "red" }[m.status] || "grey";
                const sent_label = m.from_phone ? frappe.utils.escape_html(m.from_phone) : (m.instance_label || "");
                const when = m.creation ? frappe.datetime.comment_when(m.creation) : "";
                const preview = (m.message || "").substring(0, 80);
                const file_chip = m.attach_file_name
                    ? `<span class="text-muted small">📎 ${frappe.utils.escape_html(m.attach_file_name)}</span>`
                    : "";
                return `
                    <div style="padding: 6px 0; border-top: 1px solid var(--border-color);">
                        <div style="display:flex; justify-content:space-between; gap:12px; align-items:center;">
                            <div style="flex:1; min-width:0;">
                                <span class="indicator-pill ${status_color}" style="font-size:10px;">${m.status}</span>
                                <span style="margin-left:6px; font-size:12px;">
                                    <b>${frappe.utils.escape_html(sent_label)}</b>
                                    <span class="text-muted">→</span>
                                    <b>${frappe.utils.escape_html(m.to_number)}</b>
                                </span>
                            </div>
                            <span class="text-muted small" style="white-space:nowrap;">${when}</span>
                        </div>
                        ${preview ? `<div class="text-muted small" style="margin-top:2px; padding-left: 4px;">${frappe.utils.escape_html(preview)}${m.message && m.message.length > 80 ? '…' : ''}</div>` : ''}
                        ${file_chip ? `<div style="margin-top:2px; padding-left: 4px;">${file_chip}</div>` : ''}
                        ${m.error_message ? `<div class="text-danger small" style="margin-top:2px; padding-left: 4px;">${frappe.utils.escape_html(m.error_message)}</div>` : ''}
                    </div>
                `;
            }).join("");

            $list.html(html);
        },
    });
}


// --------------------------------------------------------------------------
// Dialog
// --------------------------------------------------------------------------

function open_whatsapp_dialog(frm) {
    const doctype = frm.doctype;
    const docname = frm.docname;

    // Prefetch in parallel
    const p_numbers = frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.get_numbers_for_user",
    });
    const p_resolve = frappe.call({
        method: "evolution_whatsapp.phone_resolver.resolve",
        args: { doctype, name: docname },
    });
    const p_files = frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_message.whatsapp_message.list_files_for",
        args: { reference_doctype: doctype, reference_name: docname },
    });
    const p_pf = frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_message.whatsapp_message.list_print_formats_for",
        args: { reference_doctype: doctype },
    });
    const p_cc = frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.evolution_whatsapp_settings.evolution_whatsapp_settings.get_default_country_code",
    });

    Promise.all([p_numbers, p_resolve, p_files, p_pf, p_cc]).then(([rN, rR, rF, rP, rCC]) => {
        const numbers = rN.message || [];
        const candidates = rR.message || [];
        const existing_files = rF.message || [];
        const print_formats = (rP.message || []).map(p => p.name);
        const default_cc = rCC.message || "91";

        if (!numbers.length) {
            frappe.msgprint({
                title: __("No WhatsApp Number Assigned"),
                message: __("You don't have any WhatsApp number assigned to your user. Please contact your WhatsApp Manager."),
                indicator: "orange",
            });
            return;
        }

        build_dialog(frm, doctype, docname, numbers, candidates, existing_files, print_formats, default_cc);
    });
}


function build_dialog(frm, doctype, docname, numbers, candidates, existing_files, print_formats, default_cc) {
    // Send-from options: "Sales Number — +91 8433953040"
    const send_from_options = numbers.map(n => {
        const phone = n.phone_number ? `  ·  ${n.phone_number}` : "";
        return `${n.display_name}${phone}|||${n.name}`;  // we'll split on |||
    });

    const default_number = candidates.length ? candidates[0].number : "";

    const cc_options = COMMON_COUNTRY_CODES.map(c => c.label).join("\n");

    const fields = [];

    // Row 1: Send from
    fields.push({
        fieldtype: "Select",
        fieldname: "send_from",
        label: __("Send from"),
        reqd: 1,
        options: send_from_options.map(o => o.split("|||")[0]).join("\n"),
        default: send_from_options[0].split("|||")[0],
    });

    // Row 2: Country code + Recipient
    fields.push({ fieldtype: "Section Break" });
    fields.push({
        fieldtype: "Select",
        fieldname: "country_code",
        label: __("Code"),
        options: cc_options,
        default: cc_label_for(default_cc),
    });
    fields.push({ fieldtype: "Column Break" });
    fields.push({
        fieldtype: "Data",
        fieldname: "to_number",
        label: __("Send to"),
        reqd: 1,
        default: default_number,
        description: candidates.length
            ? __("Auto-resolved. Override if needed. Country code prefix added automatically for 10-digit numbers.")
            : __("Enter manually. Country code prefix added automatically for 10-digit numbers."),
    });

    if (candidates.length > 1) {
        fields.push({
            fieldtype: "Select",
            fieldname: "candidate_picker",
            label: __("Other numbers found on this document"),
            options: ["", ...candidates.map(c => `${c.number}  —  ${c.source}`)].join("\n"),
            change: function () {
                const picked = dialog.get_value("candidate_picker");
                if (!picked) return;
                dialog.set_value("to_number", picked.split("  —  ")[0]);
            },
        });
    }

    // Message
    fields.push({ fieldtype: "Section Break" });
    fields.push({
        fieldtype: "Small Text",
        fieldname: "message",
        label: __("Message"),
    });

    // Existing files (only if any)
    if (existing_files.length) {
        fields.push({ fieldtype: "Section Break", label: __("Attach Files") });
        fields.push({
            fieldtype: "HTML",
            fieldname: "files_html",
            options: render_files_html(existing_files),
        });
    }

    // Print format (only if any)
    if (print_formats.length) {
        fields.push({ fieldtype: "Section Break", label: __("Print Format"), collapsible: 1, collapsible_depends_on: "eval:!doc.print_format" });
        fields.push({
            fieldtype: "Select",
            fieldname: "print_format",
            label: __("Print Format"),
            options: ["", ...print_formats].join("\n"),
        });
        fields.push({
            fieldtype: "Link",
            fieldname: "letterhead",
            label: __("Letterhead"),
            options: "Letter Head",
            depends_on: "eval:doc.print_format",
        });
        fields.push({
            fieldtype: "Link",
            fieldname: "print_language",
            label: __("Language"),
            options: "Language",
            depends_on: "eval:doc.print_format",
        });
    }

    // Ad-hoc upload (always last, collapsed)
    fields.push({ fieldtype: "Section Break", label: __("Upload New File"), collapsible: 1, collapsible_depends_on: "eval:!doc.ad_hoc_file" });
    fields.push({
        fieldtype: "Attach",
        fieldname: "ad_hoc_file",
        label: __("File"),
    });

    var dialog = new frappe.ui.Dialog({
        title: __("Send WhatsApp Message"),
        size: "small",   // compact!
        fields: fields,
        primary_action_label: __("Send"),
        primary_action(values) {
            do_send(frm, doctype, docname, values, dialog, send_from_options);
        },
        on_hide() {
            // Re-inject the menu item after dialog closes (Frappe rebuilds the
            // menu on form rerender; explicit re-add ensures it's always there)
            try {
                if (frm && frm.page) {
                    frm.page.add_menu_item(__("Send WhatsApp"), function () {
                        open_whatsapp_dialog(frm);
                    }, true);
                }
            } catch (e) { /* */ }
        },
    });

    dialog.show();
}


function cc_label_for(code) {
    const found = COMMON_COUNTRY_CODES.find(c => c.code === String(code));
    return found ? found.label : COMMON_COUNTRY_CODES[0].label;
}


function code_from_label(label) {
    if (!label) return "91";
    // Label looks like "🇮🇳 +91" — extract the digits after '+'
    const m = String(label).match(/\+(\d+)/);
    return m ? m[1] : "91";
}


function render_files_html(files) {
    const rows = files.map(f => `
        <label class="d-block" style="margin-bottom: 4px; cursor: pointer;">
            <input type="checkbox" class="ew-file-cb" value="${frappe.utils.escape_html(f.name)}" />
            <span style="margin-left: 6px;">${frappe.utils.escape_html(f.file_name || f.name)}</span>
        </label>
    `).join("");
    return `<div style="max-height: 140px; overflow-y: auto; padding: 4px;">${rows}</div>`;
}


// --------------------------------------------------------------------------
// Send pipeline
// --------------------------------------------------------------------------

function do_send(frm, doctype, docname, values, dialog, send_from_options) {
    const wrapper = dialog.fields_dict.files_html ? dialog.fields_dict.files_html.$wrapper : null;
    const checked_existing = wrapper
        ? wrapper.find(".ew-file-cb:checked").map((_i, el) => el.value).get()
        : [];

    let attached = checked_existing.slice();

    // Map "Send from" label back to the actual WhatsApp Number doc name
    const picked_label = values.send_from;
    const pair = send_from_options.find(o => o.split("|||")[0] === picked_label);
    const instance_name = pair ? pair.split("|||")[1] : null;

    if (!instance_name) {
        frappe.msgprint(__("Please pick a number to send from"));
        return;
    }

    if (values.ad_hoc_file) {
        frappe.db.get_value("File", { file_url: values.ad_hoc_file }, "name").then(r => {
            if (r.message && r.message.name) attached.push(r.message.name);
            fire_send(frm, doctype, docname, values, attached, instance_name, dialog);
        });
    } else {
        fire_send(frm, doctype, docname, values, attached, instance_name, dialog);
    }
}


function fire_send(frm, doctype, docname, values, attached_files, instance_name, dialog) {
    if (!values.to_number) {
        frappe.msgprint(__("Recipient number is required"));
        return;
    }
    if (!values.message && !attached_files.length && !values.print_format) {
        frappe.msgprint(__("Add a message, a file, or a print format."));
        return;
    }

    const cc = code_from_label(values.country_code);

    frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_message.whatsapp_message.send_whatsapp",
        args: {
            instance: instance_name,
            to_number: values.to_number,
            country_code: cc,
            message: values.message || "",
            reference_doctype: doctype,
            reference_name: docname,
            attached_files: JSON.stringify(attached_files),
            print_format: values.print_format || null,
            letterhead: values.letterhead || null,
            print_language: values.print_language || null,
        },
        freeze: true,
        freeze_message: __("Queueing..."),
        callback: (r) => {
            if (r.message && r.message.queued) {
                frappe.show_alert({
                    message: __("Queued — sending to {0}...", [r.message.to_number]),
                    indicator: "blue",
                }, 4);
                dialog.hide();
                refresh_timeline(frm);
                render_whatsapp_section(frm);
            }
        },
    });
}
