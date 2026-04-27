"""WhatsApp Message — outgoing send log.

Public entry: send_whatsapp() — invoked from the three-dots dialog. Validates
the user is assigned to the chosen WhatsApp Number, normalizes the number,
creates one Message doc per outgoing payload, enqueues background sends, and
adds a comment trail to the source doc.

Background jobs hit Evolution; on completion they fire a realtime event that
the source-form's JS listens for, surfacing a toast.
"""

import base64
import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

from evolution_whatsapp import evolution_api
from evolution_whatsapp.phone_resolver import normalize_for_evolution


# --------------------------------------------------------------------------
# DocType class
# --------------------------------------------------------------------------

class WhatsAppMessage(Document):
    def before_insert(self):
        if not self.status:
            self.status = "Queued"


def on_doctype_update():
    frappe.db.add_index("WhatsApp Message", ["reference_doctype", "reference_name"])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _user_can_send_from(user, instance_name):
    """True if `user` is in the assigned_users child table of this WhatsApp Number."""
    return bool(frappe.db.exists(
        "WhatsApp Number Assigned User",
        {"parent": instance_name, "parenttype": "WhatsApp Number", "user": user},
    ))


def _file_url_for(file_doc_name):
    return frappe.db.get_value("File", file_doc_name, "file_url") or ""


def _file_basename(file_doc_name):
    return frappe.db.get_value("File", file_doc_name, "file_name") or ""


def _guess_mime(filename):
    import mimetypes
    if not filename:
        return "application/octet-stream"
    mt, _enc = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


def _publish_status(doc, status):
    """Realtime ping to the user who pressed Send so the source form can toast."""
    try:
        frappe.publish_realtime(
            event="evolution_whatsapp:message_status",
            message={
                "name": doc.name,
                "status": status,
                "to_number": doc.to_number,
                "reference_doctype": doc.reference_doctype,
                "reference_name": doc.reference_name,
                "instance": doc.instance,
                "error": doc.error_message or None,
            },
            user=doc.owner,
        )
    except Exception:
        pass


def _record_success(doc, response):
    msg_id = None
    if isinstance(response, dict):
        key = response.get("key") or {}
        msg_id = key.get("id") if isinstance(key, dict) else None
    doc.db_set("status", "Sent", update_modified=True)
    if msg_id:
        doc.db_set("evolution_message_id", msg_id, update_modified=False)
    try:
        doc.db_set("evolution_response", json.dumps(response, default=str)[:140000], update_modified=False)
    except Exception:
        pass

    # Add comment to source doc
    if doc.reference_doctype and doc.reference_name and frappe.db.exists(doc.reference_doctype, doc.reference_name):
        try:
            instance_label = frappe.db.get_value("WhatsApp Number", doc.instance, "display_name") or doc.instance
            target = frappe.get_doc(doc.reference_doctype, doc.reference_name)
            target.add_comment(
                "Comment",
                text=f"<b>WhatsApp sent</b> to {doc.to_number} from <b>{instance_label}</b> by {doc.owner}.",
            )
        except Exception:
            frappe.log_error(title="WhatsApp comment trail failed (send success)")

    _publish_status(doc, "Sent")


def _record_failure(doc, error):
    doc.db_set("status", "Failed", update_modified=True)
    doc.db_set("error_message", str(error)[:1000], update_modified=False)
    frappe.log_error(
        title=f"WhatsApp send failed: {doc.name}",
        message=f"{type(error).__name__}: {error}",
    )

    if doc.reference_doctype and doc.reference_name and frappe.db.exists(doc.reference_doctype, doc.reference_name):
        try:
            target = frappe.get_doc(doc.reference_doctype, doc.reference_name)
            target.add_comment(
                "Comment",
                text=f"<b>WhatsApp failed</b> to {doc.to_number}: {frappe.utils.escape_html(str(error))[:200]}",
            )
        except Exception:
            frappe.log_error(title="WhatsApp comment trail failed (send failure)")

    _publish_status(doc, "Failed")


# --------------------------------------------------------------------------
# Public RPC
# --------------------------------------------------------------------------

@frappe.whitelist()
def send_whatsapp(
    instance,
    to_number,
    country_code=None,
    message=None,
    reference_doctype=None,
    reference_name=None,
    attached_files=None,
    print_format=None,
    letterhead=None,
    print_language=None,
):
    """Queue WhatsApp send(s)."""
    if not instance:
        frappe.throw(_("Pick a WhatsApp number to send from"))

    user = frappe.session.user
    if not _user_can_send_from(user, instance):
        frappe.throw(_("You are not assigned to this WhatsApp number"), frappe.PermissionError)

    number_doc = frappe.get_doc("WhatsApp Number", instance)
    if not number_doc.enabled:
        frappe.throw(_("This WhatsApp number is disabled"))
    if number_doc.connection_status != "Connected":
        frappe.throw(_("'{0}' is currently <b>{1}</b>. Ask a WhatsApp Manager to reconnect it.").format(
            number_doc.display_name, number_doc.connection_status
        ))

    # Normalize the recipient number
    settings_cc = frappe.db.get_single_value("Evolution Whatsapp Settings", "default_country_code") or "91"
    cc = country_code or settings_cc
    normalized = normalize_for_evolution(to_number, country_code=cc)
    if not normalized:
        frappe.throw(_("Recipient number is invalid"))

    # Parse attached_files JSON
    if isinstance(attached_files, str):
        try:
            attached_files = json.loads(attached_files)
        except Exception:
            attached_files = []
    attached_files = attached_files or []

    has_print = bool(print_format and reference_doctype and reference_name)
    has_files = bool(attached_files) or has_print
    has_text = bool(message and message.strip())

    if not (has_text or has_files):
        frappe.throw(_("Add a message, a file, or a print format"))

    single_caption_case = has_text and (
        (len(attached_files) == 1 and not has_print) or
        (len(attached_files) == 0 and has_print)
    )

    created = []

    # 1. Text-only payload (when files are absent OR shouldn't merge into caption)
    if has_text and not single_caption_case:
        doc = frappe.get_doc({
            "doctype": "WhatsApp Message",
            "to_number": normalized,
            "message": message,
            "instance": instance,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "status": "Queued",
        }).insert(ignore_permissions=False)
        created.append(doc.name)
        frappe.enqueue(_send_text_job, queue="short", job_name=f"WAM:text:{doc.name}", message_name=doc.name)

    # 2. Each user-picked file
    for idx, file_name in enumerate(attached_files):
        caption = message if (single_caption_case and idx == 0 and not has_print) else None
        doc = frappe.get_doc({
            "doctype": "WhatsApp Message",
            "to_number": normalized,
            "message": caption or "",
            "attach": _file_url_for(file_name),
            "attach_file_name": _file_basename(file_name),
            "instance": instance,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "status": "Queued",
        }).insert(ignore_permissions=False)
        created.append(doc.name)
        frappe.enqueue(
            _send_media_from_file_job, queue="short", job_name=f"WAM:media:{doc.name}",
            message_name=doc.name, file_name=file_name, caption=caption,
        )

    # 3. Print format -> generated PDF
    if has_print:
        caption = message if (single_caption_case and not attached_files) else None
        doc = frappe.get_doc({
            "doctype": "WhatsApp Message",
            "to_number": normalized,
            "message": caption or "",
            "attach_file_name": f"{reference_name}.pdf",
            "instance": instance,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "status": "Queued",
        }).insert(ignore_permissions=False)
        created.append(doc.name)
        frappe.enqueue(
            _send_print_format_job, queue="long", job_name=f"WAM:pdf:{doc.name}",
            message_name=doc.name,
            reference_doctype=reference_doctype, reference_name=reference_name,
            print_format=print_format, letterhead=letterhead,
            print_language=print_language, caption=caption,
        )

    # Add a "queued" comment trail on the source doc (immediately, before sends complete)
    if reference_doctype and reference_name and frappe.db.exists(reference_doctype, reference_name):
        try:
            target = frappe.get_doc(reference_doctype, reference_name)
            instance_label = number_doc.display_name
            summary_bits = []
            if has_text:
                summary_bits.append(f"text ({len((message or '').strip())} chars)")
            if attached_files:
                summary_bits.append(f"{len(attached_files)} file(s)")
            if has_print:
                summary_bits.append(f"print: {print_format}")
            summary = ", ".join(summary_bits) or "—"
            target.add_comment(
                "Comment",
                text=f"<b>WhatsApp queued</b> to {normalized} from <b>{instance_label}</b> ({summary}).",
            )
        except Exception:
            frappe.log_error(title="WhatsApp comment trail failed (queue)")

    return {"queued": created, "to_number": normalized}


# --------------------------------------------------------------------------
# Background jobs
# --------------------------------------------------------------------------

def _get_job_doc(message_name):
    doc = frappe.get_doc("WhatsApp Message", message_name)
    number_doc = frappe.get_doc("WhatsApp Number", doc.instance)
    return doc, number_doc


def _send_text_job(message_name):
    try:
        doc, number_doc = _get_job_doc(message_name)
        api_key = number_doc.get_password("instance_api_key")
        response = evolution_api.send_text(
            number_doc.instance_name, api_key, doc.to_number, doc.message or "",
        )
        _record_success(doc, response)
    except Exception as e:
        try:
            doc, _n = _get_job_doc(message_name)
            _record_failure(doc, e)
        except Exception:
            pass


def _send_media_from_file_job(message_name, file_name, caption):
    try:
        doc, number_doc = _get_job_doc(message_name)
        api_key = number_doc.get_password("instance_api_key")

        file_doc = frappe.get_doc("File", file_name)
        content = file_doc.get_content()
        if isinstance(content, str):
            content = content.encode("utf-8")
        media_b64 = base64.b64encode(content).decode("ascii")

        mime_type = _guess_mime(file_doc.file_name)
        response = evolution_api.send_media(
            number_doc.instance_name, api_key, doc.to_number,
            media_b64, file_doc.file_name, mime_type, caption=caption or None,
        )
        _record_success(doc, response)
    except Exception as e:
        try:
            doc, _n = _get_job_doc(message_name)
            _record_failure(doc, e)
        except Exception:
            pass


def _send_print_format_job(
    message_name, reference_doctype, reference_name,
    print_format, letterhead, print_language, caption,
):
    try:
        doc, number_doc = _get_job_doc(message_name)
        api_key = number_doc.get_password("instance_api_key")

        if print_language:
            frappe.local.lang = print_language
        pdf_bytes = frappe.get_print(
            doctype=reference_doctype, name=reference_name,
            print_format=print_format, letterhead=letterhead, as_pdf=True,
        )
        if isinstance(pdf_bytes, str):
            pdf_bytes = pdf_bytes.encode("latin-1", errors="ignore")

        media_b64 = base64.b64encode(pdf_bytes).decode("ascii")
        file_name = f"{reference_name}.pdf".replace("/", "_")

        response = evolution_api.send_media(
            number_doc.instance_name, api_key, doc.to_number,
            media_b64, file_name, "application/pdf", caption=caption or None,
        )
        _record_success(doc, response)
    except Exception as e:
        try:
            doc, _n = _get_job_doc(message_name)
            _record_failure(doc, e)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Listing helpers used by the dialog
# --------------------------------------------------------------------------

@frappe.whitelist()
def list_files_for(reference_doctype, reference_name):
    if not (reference_doctype and reference_name):
        return []
    if not frappe.has_permission(reference_doctype, "read", doc=reference_name):
        frappe.throw(_("Not permitted"))
    files = frappe.get_all(
        "File",
        filters={"attached_to_doctype": reference_doctype, "attached_to_name": reference_name},
        fields=["name", "file_name", "file_url", "file_size"],
    )
    return files


@frappe.whitelist()
def list_print_formats_for(reference_doctype):
    if not reference_doctype:
        return []
    rows = frappe.get_all(
        "Print Format",
        filters={"doc_type": reference_doctype, "disabled": 0},
        fields=["name", "standard"],
    )
    rows.sort(key=lambda r: (r.get("standard") != "Yes", r["name"]))
    return rows


@frappe.whitelist()
def list_messages_for(reference_doctype, reference_name, limit=10):
    """WhatsApp messages sent for a given source document.

    Returns at most `limit` recent rows that the current user is allowed to
    see (owner-scoped per the WhatsApp Message permission model). Used by the
    inline "WhatsApp Messages" section under each document form.
    """
    if not (reference_doctype and reference_name):
        return []
    if not frappe.has_permission(reference_doctype, "read", doc=reference_name):
        frappe.throw(_("Not permitted"))

    user = frappe.session.user
    is_sysmgr = "System Manager" in frappe.get_roles(user)

    filters = {
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
    }
    if not is_sysmgr:
        filters["owner"] = user

    rows = frappe.get_all(
        "WhatsApp Message",
        filters=filters,
        fields=[
            "name", "status", "to_number", "instance",
            "message", "attach_file_name", "error_message",
            "creation", "owner",
        ],
        order_by="creation desc",
        limit=int(limit),
    )

    # Hydrate from-number/display_name from the linked WhatsApp Number, in one pass
    instance_names = list({r["instance"] for r in rows if r.get("instance")})
    info = {}
    if instance_names:
        for r in frappe.get_all(
            "WhatsApp Number",
            filters={"name": ["in", instance_names]},
            fields=["name", "display_name", "phone_number"],
        ):
            info[r["name"]] = {
                "instance_label": r["display_name"],
                "from_phone": r["phone_number"] or r["display_name"],
            }

    for r in rows:
        meta = info.get(r.get("instance") or "", {})
        r["instance_label"] = meta.get("instance_label", r.get("instance") or "")
        r["from_phone"] = meta.get("from_phone", "")

    return rows
