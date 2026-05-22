"""WhatsApp Number — shared org-level connected WhatsApp account.

Lifecycle:
    create (display_name) -> auto-slug instance_name
    after_insert -> POST /instance/create on Evolution -> store hash + qr
    user scans QR -> client polls -> connection_status flips to Connected
    on_trash -> auto-logout + delete on Evolution (re-raised on failure to
                keep Frappe and Evolution in sync)

Permission model:
    WhatsApp Manager / System Manager: full CRUD on every number.
    Everyone else: read-only access, list filtered to numbers they're
    listed in via the assigned_users child table.
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
    """Ensure uniqueness across existing WhatsApp Numbers.

    The check-then-insert is not atomic, so two concurrent creates with the
    same display name could theoretically collide. The random fallback makes
    that window practically impossible. A proper fix would be a DB unique
    index on instance_name.
    """
    import random
    candidate = base
    suffix = 0
    while frappe.db.exists("WhatsApp Number", {"instance_name": candidate}):
        suffix += 1
        candidate = f"{base}-{suffix}"
        if suffix > 50:
            candidate = f"{base}-{random.randint(10000, 99999)}"
            break
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
    try:
        d.save()
    except Exception:
        # Save failed — delete the orphaned Evolution instance so local and
        # remote stay in sync. Log but don't re-raise the cleanup error.
        try:
            evolution_api.delete_instance(doc.instance_name, api_key)
        except Exception:
            frappe.log_error(title=f"Evolution orphan cleanup failed: {doc.instance_name}")
        frappe.db.set_value(
            "WhatsApp Number", doc.name,
            {"connection_status": "Error"},
            update_modified=False,
        )
        raise

    qr_b64 = qrcode.get("base64") if isinstance(qrcode, dict) else None
    if qr_b64:
        frappe.cache().set_value(f"ew_qr::{doc.name}", qr_b64, expires_in_sec=120)


def on_trash(doc, method=None):
    """Best-effort logout, then delete on Evolution.

    If the Evolution-side delete fails we re-raise, which causes Frappe to
    roll back the doc deletion so the local record and the remote instance
    stay in sync. No orphaned instances on Evolution.
    """
    if not doc.instance_name:
        return

    api_key = doc.get_password("instance_api_key", raise_exception=False)

    # 1. Try to logout (graceful — already-disconnected, network blip, etc.)
    if api_key:
        try:
            evolution_api.logout_instance(doc.instance_name, api_key)
        except Exception:
            frappe.log_error(title=f"Evolution logout failed (continuing): {doc.instance_name}")

    # 2. Delete the instance — surface failure so the local doc rolls back.
    try:
        evolution_api.delete_instance(doc.instance_name, api_key)
    except Exception as e:
        frappe.log_error(title=f"Evolution delete failed: {doc.instance_name}")
        frappe.throw(
            _("Could not delete the instance on Evolution: {0}. Doc not deleted.").format(str(e))
        )


# ---------------------------------------------------------------------------
# Permission gating
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


def get_permission_query_conditions(user=None):
    """List-view filter for WhatsApp Number.

    Managers see everything (returns empty string). Everyone else sees only
    numbers where they appear in the `assigned_users` child table.
    """
    user = user or frappe.session.user
    if _can_manage(user):
        return ""

    safe_user = frappe.db.escape(user)
    return (
        "(`tabWhatsApp Number`.name IN ("
        "SELECT u.parent FROM `tabWhatsApp Number Assigned User` u "
        f"WHERE u.parenttype = 'WhatsApp Number' AND u.user = {safe_user}"
        "))"
    )


def has_permission(doc, ptype="read", user=None):
    """Per-doc permission check — same membership rule as the list filter.

    Only governs `read`. Write/delete fall through to the standard role-based
    permissions defined in whatsapp_number.json (Manager/System Manager only).
    """
    user = user or frappe.session.user
    if _can_manage(user):
        return True
    if ptype != "read":
        return False
    return bool(frappe.db.exists(
        "WhatsApp Number Assigned User",
        {"parent": doc.name, "parenttype": "WhatsApp Number", "user": user},
    ))


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
    """Logout the instance on Evolution and mark it Disconnected locally.

    Surfaces failures (symmetric with on_trash). If Evolution can't be reached
    or the logout fails, the local status stays untouched and the user sees
    the actual error — preventing a desync where Frappe says "Disconnected"
    but the WhatsApp session is still live.
    """
    _ensure_can_manage()
    doc = frappe.get_doc("WhatsApp Number", name)
    api_key = doc.get_password("instance_api_key", raise_exception=False)

    if api_key:
        try:
            evolution_api.logout_instance(doc.instance_name, api_key)
        except Exception as e:
            frappe.log_error(title=f"Disconnect failed for {doc.instance_name}")
            frappe.throw(
                _("Could not disconnect on Evolution: {0}. Status not changed.").format(str(e))
            )

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

    # De-dupe + filter to existing users.
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
    doc.flags.ignore_permissions = False
    doc.save()
    return {"count": len(cleaned)}


# ---------------------------------------------------------------------------
# Used by the send dialog
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_numbers_for_user():
    """Active, connected WhatsApp Numbers assigned to the current user."""
    user = frappe.session.user

    rows = frappe.db.sql(
        """
        SELECT n.name, n.display_name, n.phone_number, n.connection_status
        FROM `tabWhatsApp Number` n
        INNER JOIN `tabWhatsApp Number Assigned User` u
            ON u.parent = n.name AND u.parenttype = 'WhatsApp Number'
        WHERE n.enabled = 1 AND n.connection_status = 'Connected' AND u.user = %s
        ORDER BY n.display_name
        """,
        (user,),
        as_dict=True,
    )
    return rows
