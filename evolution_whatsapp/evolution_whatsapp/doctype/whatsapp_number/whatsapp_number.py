"""WhatsApp Number — shared org-level connected WhatsApp account.

Lifecycle:
    create (display_name) -> auto-slug instance_name
    after_insert -> POST /instance/create on Evolution -> store hash + qr
    user scans QR -> client polls -> connection_status flips to Connected
    on_trash -> auto-logout + delete on Evolution
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document

from evolution_whatsapp import evolution_api


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def slugify_for_evolution(text):
    """Convert 'Sales Number' -> 'sales-number'.

    Evolution accepts hyphens, underscores, alphanumerics. We strip everything
    else, lowercase, collapse repeats.
    """
    if not text:
        return ""
    s = str(text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:60]  # keep it short


def _unique_instance_name(base):
    """Ensure uniqueness across existing WhatsApp Numbers."""
    candidate = base
    suffix = 0
    while frappe.db.exists("WhatsApp Number", {"instance_name": candidate}):
        suffix += 1
        candidate = f"{base}-{suffix}"
        if suffix > 50:
            frappe.throw(_("Could not allocate a unique instance name"))
    return candidate


# ---------------------------------------------------------------------------
# DocType class
# ---------------------------------------------------------------------------

class WhatsAppNumber(Document):
    pass


# ---------------------------------------------------------------------------
# Lifecycle hooks (registered in hooks.py)
# ---------------------------------------------------------------------------

def before_insert(doc, method=None):
    if not doc.display_name:
        frappe.throw(_("Display Name is required"))

    if not doc.instance_name:
        slug = slugify_for_evolution(doc.display_name)
        if not slug:
            frappe.throw(_("Display Name must contain at least one alphanumeric character"))
        doc.instance_name = _unique_instance_name(slug)

    doc.connection_status = "Pending"


def after_insert(doc, method=None):
    """Create the instance on Evolution and stash the per-instance API key + QR."""
    try:
        result = evolution_api.create_instance(doc.instance_name)
    except Exception:
        frappe.db.set_value(
            "WhatsApp Number", doc.name,
            {"connection_status": "Error"},
            update_modified=False,
        )
        raise

    instance = result.get("instance", {}) if isinstance(result, dict) else {}
    qrcode = result.get("qrcode", {}) if isinstance(result, dict) else {}
    api_key = result.get("hash") or result.get("apikey")

    d = frappe.get_doc("WhatsApp Number", doc.name)
    if api_key:
        d.instance_api_key = api_key
    d.instance_id = instance.get("instanceId") or ""
    d.connection_status = "Awaiting QR Scan"
    d.flags.ignore_permissions = True
    d.save()

    qr_b64 = qrcode.get("base64") if isinstance(qrcode, dict) else None
    if qr_b64:
        frappe.cache().set_value(f"ew_qr::{doc.name}", qr_b64, expires_in_sec=120)


def on_trash(doc, method=None):
    """Best-effort: logout then delete the Evolution instance."""
    if not doc.instance_name:
        return

    api_key = doc.get_password("instance_api_key", raise_exception=False)

    # 1. Try to logout (graceful)
    if api_key:
        try:
            evolution_api.logout_instance(doc.instance_name, api_key)
        except Exception:
            # Not fatal — already disconnected, network blip, etc.
            frappe.log_error(title=f"Evolution logout failed (continuing): {doc.instance_name}")

    # 2. Delete the instance — this we DO want to surface if it fails,
    # otherwise we'd orphan an instance on Evolution.
    try:
        evolution_api.delete_instance(doc.instance_name, api_key)
    except Exception as e:
        frappe.log_error(title=f"Evolution delete failed: {doc.instance_name}")
        # Re-raise so Frappe rolls back the doc deletion. User sees the error.
        frappe.throw(
            _("Could not delete the instance on Evolution: {0}. Doc not deleted.").format(str(e))
        )


# ---------------------------------------------------------------------------
# Permission & assignment helpers
# ---------------------------------------------------------------------------

def _can_manage(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    roles = frappe.get_roles(user)
    return "WhatsApp Manager" in roles or "System Manager" in roles


def _ensure_can_manage():
    if not _can_manage():
        frappe.throw(_("Only WhatsApp Manager or System Manager can perform this action"), frappe.PermissionError)


# ---------------------------------------------------------------------------
# Whitelisted RPCs
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_qr(name):
    _ensure_can_manage()
    doc = frappe.get_doc("WhatsApp Number", name)

    cached = frappe.cache().get_value(f"ew_qr::{name}")
    if cached:
        return {"base64": cached, "fresh": False}

    api_key = doc.get_password("instance_api_key", raise_exception=False)
    if not api_key:
        return {"base64": None, "error": "Instance not yet created"}

    result = evolution_api.get_qrcode(doc.instance_name, api_key)
    qrcode = result.get("qrcode") if isinstance(result, dict) else None
    base64 = (qrcode or {}).get("base64") if isinstance(qrcode, dict) else None
    if not base64 and isinstance(result, dict):
        base64 = result.get("base64")

    if base64:
        frappe.cache().set_value(f"ew_qr::{name}", base64, expires_in_sec=120)

    return {"base64": base64, "fresh": True}


@frappe.whitelist()
def check_status(name):
    _ensure_can_manage()
    doc = frappe.get_doc("WhatsApp Number", name)

    api_key = doc.get_password("instance_api_key", raise_exception=False)
    if not api_key:
        return {"status": "Pending"}

    result = evolution_api.connection_state(doc.instance_name, api_key)
    state = ((result or {}).get("instance") or {}).get("state") or "close"

    mapping = {"open": "Connected", "connecting": "Connecting", "close": "Disconnected"}
    new_status = mapping.get(state, "Disconnected")

    updates = {
        "connection_status": new_status,
        "last_status_check": frappe.utils.now_datetime(),
    }

    if new_status == "Connected" and not doc.phone_number:
        try:
            info = evolution_api.fetch_instance(doc.instance_name)
            owner_jid = None
            if isinstance(info, list) and info:
                owner_jid = info[0].get("ownerJid") or (info[0].get("instance") or {}).get("ownerJid")
            elif isinstance(info, dict):
                owner_jid = info.get("ownerJid") or (info.get("instance") or {}).get("ownerJid")
            if owner_jid:
                num = owner_jid.split("@", 1)[0]
                if num.isdigit():
                    updates["phone_number"] = f"+{num}"
        except Exception:
            frappe.log_error(title=f"fetchInstances failed for {doc.instance_name}")

        frappe.cache().delete_value(f"ew_qr::{name}")

    frappe.db.set_value("WhatsApp Number", name, updates, update_modified=False)
    return {"status": new_status, "phone_number": updates.get("phone_number") or doc.phone_number}


@frappe.whitelist()
def disconnect(name):
    _ensure_can_manage()
    doc = frappe.get_doc("WhatsApp Number", name)
    api_key = doc.get_password("instance_api_key", raise_exception=False)
    if api_key:
        try:
            evolution_api.logout_instance(doc.instance_name, api_key)
        except Exception:
            frappe.log_error(title=f"Disconnect failed for {doc.instance_name}")

    frappe.db.set_value(
        "WhatsApp Number", name,
        {"connection_status": "Disconnected", "phone_number": ""},
        update_modified=False,
    )
    return {"ok": True}


@frappe.whitelist()
def assign_users(name, users):
    """Replace the assigned_users child table with the given list of user emails."""
    import json
    _ensure_can_manage()

    if isinstance(users, str):
        try:
            users = json.loads(users)
        except Exception:
            users = [u.strip() for u in users.split(",") if u.strip()]
    users = users or []

    # De-dupe + filter to existing users
    seen = set()
    cleaned = []
    for u in users:
        if not u or u in seen:
            continue
        if not frappe.db.exists("User", u):
            continue
        seen.add(u)
        cleaned.append(u)

    doc = frappe.get_doc("WhatsApp Number", name)
    doc.set("assigned_users", [])
    for u in cleaned:
        doc.append("assigned_users", {"user": u})
    doc.flags.ignore_permissions = False  # respect WhatsApp Manager perm
    doc.save()
    return {"count": len(cleaned)}


# ---------------------------------------------------------------------------
# Used by the send dialog
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_numbers_for_user(user=None):
    """Return active, connected WhatsApp Numbers assigned to `user`."""
    user = user or frappe.session.user

    # Find all enabled+connected numbers where this user appears in assigned_users.
    rows = frappe.db.sql(
        """
        SELECT n.name, n.display_name, n.phone_number, n.connection_status
        FROM `tabWhatsApp Number` n
        INNER JOIN `tabWhatsApp Number Assigned User` u
            ON u.parent = n.name AND u.parenttype = 'WhatsApp Number'
        WHERE n.enabled = 1 AND u.user = %s
        ORDER BY n.display_name
        """,
        (user,),
        as_dict=True,
    )
    return rows
