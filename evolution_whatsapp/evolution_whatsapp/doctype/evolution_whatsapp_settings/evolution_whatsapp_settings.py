import frappe
from frappe.model.document import Document


class EvolutionWhatsappSettings(Document):
    def validate(self):
        if self.server_url:
            self.server_url = self.server_url.strip().rstrip("/")
        if self.default_country_code:
            import re
            self.default_country_code = re.sub(r"\D", "", self.default_country_code) or "91"


@frappe.whitelist()
def test_connection():
    """Verify reachability + global API key. Status-only, body discarded."""
    settings = frappe.get_doc("Evolution Whatsapp Settings")
    if not (settings.server_url and settings.get_password("global_api_key", raise_exception=False)):
        frappe.throw("Server URL and Global API Key are required")

    import requests
    try:
        r = requests.get(
            f"{settings.server_url.rstrip('/')}/instance/fetchInstances",
            headers={"apikey": settings.get_password("global_api_key")},
            timeout=10,
            stream=True,
        )
        status = r.status_code
        r.close()
    except Exception as e:
        frappe.throw(f"Could not reach Evolution server: {e}")

    if status == 200:
        return {"ok": True}
    if status == 401:
        frappe.throw("Evolution server reached, but Global API Key is invalid (401)")
    frappe.throw(f"Evolution server returned an unexpected status: {status}")


@frappe.whitelist()
def get_default_country_code():
    """Used by send dialog JS."""
    return frappe.db.get_single_value("Evolution Whatsapp Settings", "default_country_code") or "91"
