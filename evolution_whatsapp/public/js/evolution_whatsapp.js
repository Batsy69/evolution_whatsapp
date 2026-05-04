/**
 * Evolution Whatsapp — global "Send WhatsApp" menu item on every DocType form.
 *
 * Build notes:
 *  - Send-to is a single HTML field rendering an inline country-code dropdown
 *    plus the recipient digits: [+91 ▾]–[xxxxxxxxxx]. CC default comes from
 *    Evolution Whatsapp Settings.
 *  - Recipient digits auto-fill from the first Contact dynamically linked to
 *    the source doc's party (Customer / Supplier / Lead / etc.). No address
 *    or doc-field phone numbers. See phone_resolver.py.
 *  - Print format field is conditional:
 *      - 0 enabled formats: hidden.
 *      - default set in Customize Form, or exactly 1 enabled format: Check
 *        labelled "Attach print format: <name>", default unchecked.
 *      - 2+ enabled and no default: Select dropdown.
 *  - Letterhead is read silently server-side from doc.letter_head — no UI.
 *  - Send toast is minimal: ✓ Sent — +<number>, 3s.
 *  - Below each form, a "WhatsApp Messages" timeline shows status, sender
 *    number, recipient number, the user who sent, and time.
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
    // Subscribe once to send-completion toasts (minimal, 3s).
    frappe.realtime.on("evolution_whatsapp:message_status", (data) => {
        if (!data) return;
        if (data.status === "Sent") {
            frappe.show_alert({
                message: __("✓ Sent — +{0}", [data.to_number || ""]),
                indicator: "green",
            }, 3);
        } else if (data.status === "Failed") {
            frappe.show_alert({
                message: __("✗ Failed: {0}", [data.error || data.to_number || ""]),
                indicator: "red",
            }, 5);
        }
        // Refresh timeline if the user is still on the source doc.
        try {
            const cur = cur_frm;
            if (cur && cur.doctype === data.reference_doctype && cur.docname === data.reference_name) {
                refresh_timeline(cur);
                render_whatsapp_section(cur);
            }
        } catch (e) { /* swallow */ }
    });

    // Re-register a refresh handler per doctype the user navigates to. The
    // refresh handler re-injects the menu item on every form rerender, since
    // Frappe rebuilds the page menu on each rerender.
    let last_dt = null;
    frappe.router.on("change", () => {
        const route = frappe.get_route();
        if (!(route && route[0] === "Form")) return;
        const dt = route[1];
        if (dt === last_dt) return;
        last_dt = dt;

        if (frappe.ui.form._ew_registered_dts && frappe.ui.form._ew_registered_dts[dt]) return;
        frappe.ui.form._ew_registered_dts = frappe.ui.form._ew_registered_dts || {};
        frappe.ui.form._ew_registered_dts[dt] = true;

        frappe.ui.form.on(dt, {
            refresh: function (frm) {
                if (frm.is_new()) return;
                frm.page.add_menu_item(__("Send WhatsApp"), function () {
                    open_whatsapp_dialog(frm);
                }, /* permanent */ true);
                render_whatsapp_section(frm);
            },
        });
    });
});


// --------------------------------------------------------------------------
// Refresh comments/timeline without a full doc reload
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
// WhatsApp messages timeline section under each document
// --------------------------------------------------------------------------

function render_whatsapp_section(frm) {
    if (!frm || frm.is_new()) return;
    if (!frm.fields_dict) return;

    const $anchor = frm.layout.wrapper.find(".form-layout").first();
    if (!$anchor.length) return;

    // Idempotent: remove old block if present, re-render.
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
        args: { reference_doctype: frm.doctype, reference_name: frm.docname },
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
                const sent_label = m.from_phone || m.instance_label || "";
                const instance_chip = m.instance_label ? `<span class="text-muted">(${frappe.utils.escape_html(m.instance_label)})</span>` : "";
                const when = m.creation ? frappe.datetime.comment_when(m.creation) : "";
                const owner_label = m.owner_full_name || m.owner || "";
                const preview = (m.message || "").substring(0, 80);
                const file_chip = m.attach_file_name
                    ? `<span class="text-muted small">📎 ${frappe.utils.escape_html(m.attach_file_name)}</span>`
                    : "";
                return `
                    <div style="padding: 8px 0; border-top: 1px solid var(--border-color);">
                        <div style="display:flex; justify-content:space-between; gap:12px; align-items:center;">
                            <div style="flex:1; min-width:0;">
                                <span class="indicator-pill ${status_color}" style="font-size:10px;">${m.status}</span>
                                <span style="margin-left:6px; font-size:12px;">
                                    <b>${frappe.utils.escape_html(sent_label)}</b>
                                    ${instance_chip}
                                    <span class="text-muted">→</span>
                                    <b>${frappe.utils.escape_html(m.to_number)}</b>
                                </span>
                            </div>
                            <span class="text-muted small" style="white-space:nowrap;">${when}</span>
                        </div>
                        <div class="text-muted small" style="margin-top:2px; padding-left: 4px;">
                            ${__("by")} ${frappe.utils.escape_html(owner_label)}
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
// Send dialog
// --------------------------------------------------------------------------

function open_whatsapp_dialog(frm) {
    const doctype = frm.doctype;
    const docname = frm.docname;

    // Prefetch in parallel.
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
        const print_format_data = rP.message || { default: null, formats: [] };
        const default_cc = rCC.message || "91";

        if (!numbers.length) {
            frappe.msgprint({
                title: __("No WhatsApp Number Assigned"),
                message: __("You don't have any WhatsApp number assigned to your user. Please contact your WhatsApp Manager."),
                indicator: "orange",
            });
            return;
        }

        build_dialog(frm, doctype, docname, numbers, candidates, existing_files, print_format_data, default_cc);
    });
}


function build_dialog(frm, doctype, docname, numbers, candidates, existing_files, pf_data, default_cc) {
    // Send-from options: "Sales Number  ·  +91 8433953040"
    const send_from_options = numbers.map(n => {
        const phone = n.phone_number ? `  ·  ${n.phone_number}` : "";
        return `${n.display_name}${phone}|||${n.name}`;
    });

    const default_digits = candidates.length ? digits_only(candidates[0].number) : "";
    const default_cc_clean = String(default_cc || "91").replace(/\D/g, "") || "91";

    // Resolve print format mode up front — needed to decide layout.
    const formats = pf_data.formats || [];
    const pf_default = pf_data.default || null;
    let pf_mode = "hidden";
    let pf_resolved_for_check = null;
    if (formats.length === 0) {
        pf_mode = "hidden";
    } else if (pf_default) {
        pf_mode = "check";
        pf_resolved_for_check = pf_default;
    } else if (formats.length === 1) {
        pf_mode = "check";
        pf_resolved_for_check = formats[0];
    } else {
        pf_mode = "select";
    }

    const has_files = existing_files.length > 0;
    const has_pf    = pf_mode !== "hidden";

    const fields = [];

    // ── Row 1: Send from (left) | Send to (right) ──────────────────────────
    fields.push({
        fieldtype: "Select",
        fieldname: "send_from",
        label: __("Send from"),
        reqd: 1,
        options: send_from_options.map(o => o.split("|||")[0]).join("\n"),
        default: send_from_options[0].split("|||")[0],
    });
    fields.push({ fieldtype: "Column Break" });
    fields.push({
        fieldtype: "HTML",
        fieldname: "send_to",
        options: render_send_to_html(default_cc_clean, default_digits),
    });

    // ── Row 2: Other contacts (full width, only when 2+ candidates) ─────────
    if (candidates.length > 1) {
        const opts = ["", ...candidates.map(c => `${c.number}  —  ${c.source}`)].join("\n");
        fields.push({ fieldtype: "Section Break" });
        fields.push({
            fieldtype: "Select",
            fieldname: "candidate_picker",
            label: __("Other contacts"),
            options: opts,
            change: function () {
                const picked = dialog.get_value("candidate_picker");
                if (!picked) return;
                const num = picked.split("  —  ")[0];
                set_send_to_digits(dialog, digits_only(num));
            },
        });
    }

    // ── Row 3: Message (full width) ──────────────────────────────────────────
    fields.push({ fieldtype: "Section Break" });
    fields.push({
        fieldtype: "Small Text",
        fieldname: "message",
        label: __("Message"),
    });

    // ── Row 4: Attach files (left) | Print format + Upload (right) ───────────
    //
    // Four cases depending on what exists:
    //   A  files + pf  → two columns: checklist left, pf+upload right
    //   B  files only  → two columns: checklist left, upload right
    //   C  pf only     → two columns: pf left, upload right
    //   D  neither     → upload full width (no section header needed)

    fields.push({ fieldtype: "Section Break" });

    if (has_files) {
        // Left column: existing file checklist
        fields.push({
            fieldtype: "HTML",
            fieldname: "files_html",
            label: __("Attach files"),
            options: render_files_html(existing_files),
        });
        fields.push({ fieldtype: "Column Break" });
    }

    if (has_pf && !has_files) {
        // No files column — pf goes on the left, upload on the right.
        if (pf_mode === "check") {
            fields.push({
                fieldtype: "Check",
                fieldname: "attach_print_format",
                label: __("Attach print format: {0}", [pf_resolved_for_check]),
                default: 0,
            });
        } else {
            fields.push({
                fieldtype: "Select",
                fieldname: "print_format",
                label: __("Print Format"),
                options: ["", ...formats].join("\n"),
            });
        }
        fields.push({ fieldtype: "Column Break" });
    } else if (has_pf && has_files) {
        // Right column (after the Column Break from the files side).
        if (pf_mode === "check") {
            fields.push({
                fieldtype: "Check",
                fieldname: "attach_print_format",
                label: __("Attach print format: {0}", [pf_resolved_for_check]),
                default: 0,
            });
        } else {
            fields.push({
                fieldtype: "Select",
                fieldname: "print_format",
                label: __("Print Format"),
                options: ["", ...formats].join("\n"),
            });
        }
    }

    // Upload — always in the rightmost column (or full width when no files/pf).
    fields.push({
        fieldtype: "Attach",
        fieldname: "ad_hoc_file",
        label: __("Upload new file"),
    });

    var dialog = new frappe.ui.Dialog({
        title: __("Send WhatsApp Message"),
        size: "small",
        fields: fields,
        primary_action_label: __("Send"),
        primary_action(values) {
            do_send(frm, doctype, docname, values, dialog, send_from_options, pf_mode, pf_resolved_for_check);
        },
        on_hide() {
            // Re-inject the menu item after dialog closes.
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


// --------------------------------------------------------------------------
// Send-to (HTML field) — rendering, reading, writing
// --------------------------------------------------------------------------

function render_send_to_html(default_cc, default_digits) {
    const cc_options = COMMON_COUNTRY_CODES.map(c => {
        const sel = c.code === default_cc ? " selected" : "";
        return `<option value="${c.code}"${sel}>${c.label}</option>`;
    }).join("");

    // Inline CC + digits, styled to look like one cohesive field.
    return `
        <div class="form-group">
            <label class="control-label" style="font-size: 12px; padding-right: 0px; margin-bottom: 4px;">
                ${__("Send to")}<span class="text-danger" style="margin-left:2px;">*</span>
            </label>
            <div class="ew-sendto-wrap" style="display:flex; align-items:stretch; border:1px solid var(--input-border-color, #d1d8dd); border-radius:4px; overflow:hidden; background:var(--input-bg, #fff);">
                <select class="ew-cc" style="border:0; border-right:1px solid var(--input-border-color, #d1d8dd); padding:6px 6px; background:var(--gray-50, #f8f9fa); font-size:12px; outline:none;">
                    ${cc_options}
                </select>
                <span class="ew-cc-sep" style="padding:6px 6px; color:var(--text-muted); user-select:none;">–</span>
                <input class="ew-num" type="tel" inputmode="tel"
                    placeholder="${__("Recipient digits")}"
                    value="${frappe.utils.escape_html(default_digits || "")}"
                    style="flex:1; border:0; padding:6px 8px; font-size:13px; outline:none; background:transparent;" />
            </div>
        </div>
    `;
}


function read_send_to(dialog) {
    const $w = dialog.fields_dict.send_to.$wrapper;
    const cc = String($w.find(".ew-cc").val() || "91").replace(/\D/g, "");
    const digits = digits_only($w.find(".ew-num").val() || "");
    return { cc, digits };
}


function set_send_to_digits(dialog, digits) {
    const $w = dialog.fields_dict.send_to.$wrapper;
    $w.find(".ew-num").val(digits || "");
}


function digits_only(s) {
    return String(s || "").replace(/\D/g, "");
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

function do_send(frm, doctype, docname, values, dialog, send_from_options, pf_mode, pf_resolved_for_check) {
    const wrapper = dialog.fields_dict.files_html ? dialog.fields_dict.files_html.$wrapper : null;
    const checked_existing = wrapper
        ? wrapper.find(".ew-file-cb:checked").map((_i, el) => el.value).get()
        : [];

    let attached = checked_existing.slice();

    // Map "Send from" label back to the actual WhatsApp Number doc name.
    const picked_label = values.send_from;
    const pair = send_from_options.find(o => o.split("|||")[0] === picked_label);
    const instance_name = pair ? pair.split("|||")[1] : null;

    if (!instance_name) {
        frappe.msgprint(__("Please pick a number to send from"));
        return;
    }

    // Read the merged Send-to field.
    const { cc, digits } = read_send_to(dialog);
    if (!digits) {
        frappe.msgprint(__("Recipient number is required"));
        return;
    }

    // Resolve print_format argument from the conditional UI.
    let print_format_arg = null;
    if (pf_mode === "check") {
        print_format_arg = values.attach_print_format ? pf_resolved_for_check : null;
    } else if (pf_mode === "select") {
        print_format_arg = values.print_format || null;
    }

    if (!values.message && !attached.length && !values.ad_hoc_file && !print_format_arg) {
        frappe.msgprint(__("Add a message, a file, or a print format."));
        return;
    }

    if (values.ad_hoc_file) {
        frappe.db.get_value("File", { file_url: values.ad_hoc_file }, "name").then(r => {
            if (r.message && r.message.name) attached.push(r.message.name);
            fire_send(frm, doctype, docname, values, attached, instance_name, cc, digits, print_format_arg, dialog);
        });
    } else {
        fire_send(frm, doctype, docname, values, attached, instance_name, cc, digits, print_format_arg, dialog);
    }
}


function fire_send(frm, doctype, docname, values, attached_files, instance_name, cc, digits, print_format_arg, dialog) {
    frappe.call({
        method: "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_message.whatsapp_message.send_whatsapp",
        args: {
            instance: instance_name,
            to_number: digits,
            country_code: cc,
            message: values.message || "",
            reference_doctype: doctype,
            reference_name: docname,
            attached_files: JSON.stringify(attached_files),
            print_format: print_format_arg,
        },
        freeze: true,
        freeze_message: __("Queueing..."),
        callback: (r) => {
            if (r.message && r.message.queued) {
                dialog.hide();
                refresh_timeline(frm);
                render_whatsapp_section(frm);
            }
        },
    });
}
