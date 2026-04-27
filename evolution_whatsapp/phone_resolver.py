"""Resolve recipient phone numbers from any DocType + normalize for Evolution.

Resolution walk order:
1. Direct phone fields on the document
2. Contacts dynamically linked to the doc
3. Addresses dynamically linked to the doc
4. Party fields (customer/supplier/lead/employee) — recurse one level
"""

import re
import frappe


DIRECT_PHONE_FIELDS = (
    "whatsapp_no",
    "mobile_no",
    "cell_number",
    "personal_mobile",
    "phone",
    "contact_mobile",
    "contact_no",
    "phone_no",
)

PARTY_FIELDS = {
    "customer": "Customer",
    "supplier": "Supplier",
    "lead": "Lead",
    "employee": "Employee",
    "applicant": "Job Applicant",
    "contact": "Contact",
    "party_name": None,  # paired with party_type
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_for_evolution(number, country_code=None):
    """Return a digit-only number ready for Evolution.

    Rules:
    - Strip everything except digits and a leading '+'
    - If number starts with '+': drop the '+' and use the rest verbatim
    - If 10 digits and no '+': prepend country_code (default 91)
    - If 11+ digits: assume country code is already there, use verbatim
    - If <10 digits: invalid → return empty string (caller should error)
    """
    if not number:
        return ""
    s = str(number).strip()

    has_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)

    if has_plus:
        return digits

    if len(digits) >= 11:
        return digits

    if len(digits) == 10:
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


def _add(found, number, source):
    cleaned = _clean_for_display(number)
    if not cleaned:
        return
    if any(item["number"] == cleaned for item in found):
        return
    found.append({"number": cleaned, "source": source})


def _from_doc_fields(doc, found):
    for fname in DIRECT_PHONE_FIELDS:
        if doc.get(fname):
            _add(found, doc.get(fname), f"{doc.doctype} · {fname}")


def _from_dynamic_links(doctype, name, found):
    rows = frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": doctype, "link_name": name},
        fields=["parent", "parenttype"],
    )
    for row in rows:
        if row.parenttype == "Contact":
            c = frappe.db.get_value("Contact", row.parent, ["mobile_no", "phone"], as_dict=True)
            if c:
                _add(found, c.mobile_no, f"Contact · {row.parent}")
                _add(found, c.phone, f"Contact · {row.parent}")
        elif row.parenttype == "Address":
            a = frappe.db.get_value("Address", row.parent, ["phone"], as_dict=True)
            if a:
                _add(found, a.phone, f"Address · {row.parent}")


def _from_party(doc, found, depth=0):
    if depth > 1:
        return
    for fname, default_dt in PARTY_FIELDS.items():
        val = doc.get(fname)
        if not val:
            continue
        if fname == "party_name":
            party_doctype = doc.get("party_type")
            if not party_doctype:
                continue
        else:
            party_doctype = default_dt
        if not party_doctype or not frappe.db.exists(party_doctype, val):
            continue
        try:
            party_doc = frappe.get_doc(party_doctype, val)
        except Exception:
            continue
        _from_doc_fields(party_doc, found)
        _from_dynamic_links(party_doctype, val, found)


@frappe.whitelist()
def resolve(doctype, name):
    if not (doctype and name):
        return []
    if not frappe.db.exists(doctype, name):
        return []
    if not frappe.has_permission(doctype, "read", doc=name):
        frappe.throw("Not permitted")

    doc = frappe.get_doc(doctype, name)
    found = []
    _from_doc_fields(doc, found)
    _from_dynamic_links(doctype, name, found)
    _from_party(doc, found)
    return found
