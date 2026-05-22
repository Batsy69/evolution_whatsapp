"""Resolve recipient phone numbers strictly from the Contact DocType.

Resolution rule (per spec):
- The only source of recipient numbers is the Contact DocType, accessed via
  the Dynamic Link table on Contact pointing back to a *party* record.
- The "party" is either:
    1. The source document itself, when it IS a party-type doc (Customer,
       Supplier, Lead, Job Applicant, Employee, Contact, etc.).
    2. The party referenced by a known link field on the source document
       (customer / supplier / lead / employee / applicant / party_name + party_type).
- If the source doc has a direct `contact` field, that Contact's numbers are
  fetched directly (not treated as a party to walk linked contacts from).
- Address phones are NOT used.
- Direct phone fields on the source document are NOT used.

If the source doc IS a Contact, we return that Contact's own phones directly.

Number normalization for Evolution lives in `normalize_for_evolution` — same
contract as before: digits-only, country code prefixed for bare local input,
no '+' anywhere in the output.
"""

import re
import frappe


# Party fields we'll follow from the source doc one level deep.
# Note: `contact` is intentionally excluded — a direct contact field is
# handled separately in resolve() by fetching that Contact directly.
PARTY_FIELDS = {
    "customer":   "Customer",
    "supplier":   "Supplier",
    "lead":       "Lead",
    "employee":   "Employee",
    "applicant":  "Job Applicant",
    "party_name": None,  # paired with party_type field on the doc
}

# When the source doc itself IS one of these, treat it as the party.
SELF_PARTY_DOCTYPES = {
    "Customer", "Supplier", "Lead", "Employee", "Job Applicant",
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_for_evolution(number, country_code=None):
    """Return a digit-only number ready for Evolution.

    Rules:
    - Strip everything except digits and a leading '+'.
    - If number starts with '+': drop the '+', return the rest verbatim.
      Use this for full international numbers (e.g. +971501234567).
    - If 7+ digits and no '+': prepend country_code (default 91).
      The dialog always supplies a country code, so the input is always
      local digits — this covers all listed countries regardless of their
      local number length (8 digits for SG, 9 for UAE/SA/AU/FR/LK, 10 for
      IN/US/UK/PK/BD, 11 for CN, etc.).
    - If <7 digits: invalid → return empty string (caller should error).
    """
    if not number:
        return ""
    s = str(number).strip()

    has_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)

    if has_plus:
        return digits

    if len(digits) >= 7:
        cc = re.sub(r"\D", "", str(country_code or "91"))
        return f"{cc}{digits}"

    return ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_for_display(num):
    """Light cleaning for showing candidates in the dialog (preserves +)."""
    if not num:
        return None
    n = re.sub(r"[^\d+]", "", str(num).strip())
    return n or None


def _contact_label(contact_row):
    """Human-friendly label for the dialog: 'John Doe' or fall back to the contact ID."""
    parts = [
        (contact_row.get("first_name") or "").strip(),
        (contact_row.get("last_name") or "").strip(),
    ]
    name = " ".join(p for p in parts if p)
    return name or contact_row.get("name") or "Contact"


def _push_contact_numbers(contact_row, found, seen_numbers):
    """Append mobile_no (preferred) and phone from a Contact row, deduped."""
    label = _contact_label(contact_row)

    for fieldname in ("mobile_no", "phone"):
        raw = contact_row.get(fieldname)
        cleaned = _clean_for_display(raw)
        if not cleaned or cleaned in seen_numbers:
            continue
        seen_numbers.add(cleaned)
        kind = "mobile" if fieldname == "mobile_no" else "phone"
        found.append({
            "number": cleaned,
            "source": f"{label} · {kind}",
            "contact": contact_row.get("name"),
        })


def _contacts_linked_to(party_doctype, party_name):
    """Return Contact rows dynamically linked to (party_doctype, party_name).

    One DB hit, ordered by is_primary_contact desc to surface primary first.
    """
    if not (party_doctype and party_name):
        return []

    # Find all Contact parents with a Dynamic Link to this party.
    contact_names = [
        r.parent for r in frappe.get_all(
            "Dynamic Link",
            filters={
                "link_doctype": party_doctype,
                "link_name": party_name,
                "parenttype": "Contact",
            },
            fields=["parent"],
        )
    ]
    if not contact_names:
        return []

    # Fetch the Contact rows in one query, primary first.
    rows = frappe.get_all(
        "Contact",
        filters={"name": ["in", contact_names]},
        fields=["name", "first_name", "last_name", "mobile_no", "phone", "is_primary_contact"],
        order_by="is_primary_contact desc, modified desc",
    )
    return rows


def _self_contact(name):
    """When the source doc IS a Contact, fetch its own row."""
    return frappe.db.get_value(
        "Contact", name,
        ["name", "first_name", "last_name", "mobile_no", "phone"],
        as_dict=True,
    )


def _party_targets(doc):
    """Yield (doctype, name) tuples for every party we should follow from `doc`."""
    # The doc itself might be a party.
    if doc.doctype in SELF_PARTY_DOCTYPES:
        yield doc.doctype, doc.name

    # Walk known party link fields on the doc.
    for fname, default_dt in PARTY_FIELDS.items():
        val = doc.get(fname)
        if not val:
            continue
        if fname == "party_name":
            party_dt = doc.get("party_type")
            if not party_dt:
                continue
        else:
            party_dt = default_dt
        if not party_dt:
            continue
        if not frappe.db.exists(party_dt, val):
            continue
        yield party_dt, val


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@frappe.whitelist()
def resolve(doctype, name):
    """Return a deduped list of {number, source, contact} entries for the given doc."""
    if not (doctype and name):
        return []
    if not frappe.db.exists(doctype, name):
        return []
    if not frappe.has_permission(doctype, "read", doc=name):
        frappe.throw("Not permitted")

    doc = frappe.get_doc(doctype, name)
    found = []
    seen_numbers = set()
    seen_contacts = set()

    # Special case: doc IS a Contact → use it directly, no party walk needed.
    if doctype == "Contact":
        c = _self_contact(name)
        if c:
            _push_contact_numbers(c, found, seen_numbers)
        return found

    # If the doc has a direct `contact` field, fetch that Contact's numbers
    # directly — do not treat it as a party to walk linked contacts from.
    direct_contact = doc.get("contact")
    if direct_contact and frappe.db.exists("Contact", direct_contact):
        c = _self_contact(direct_contact)
        if c:
            seen_contacts.add(direct_contact)
            _push_contact_numbers(c, found, seen_numbers)

    # Walk every party target and collect Contacts linked to them.
    for party_dt, party_name in _party_targets(doc):
        for contact_row in _contacts_linked_to(party_dt, party_name):
            cname = contact_row.get("name")
            if cname in seen_contacts:
                continue
            seen_contacts.add(cname)
            _push_contact_numbers(contact_row, found, seen_numbers)

    return found
