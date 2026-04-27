"""Thin wrapper around Evolution API v2.

Auth model:
- /instance/* endpoints use the *global* API key from Evolution Whatsapp Settings.
- /message/* and /chat/* endpoints use the *per-instance* API key (the `hash`
  returned by Evolution at instance create time), stored on each WhatsApp Number.
"""

import frappe
import requests
from frappe import _
from urllib.parse import quote


SETTINGS_DOCTYPE = "Evolution Whatsapp Settings"
TIMEOUT = 30


def _settings():
    return frappe.get_cached_doc(SETTINGS_DOCTYPE)


def _global_headers():
    s = _settings()
    if not s.server_url:
        frappe.throw(_("Evolution Whatsapp Settings: Server URL is not set"))
    return {
        "apikey": s.get_password("global_api_key"),
        "Content-Type": "application/json",
    }


def _instance_headers(instance_api_key):
    return {
        "apikey": instance_api_key,
        "Content-Type": "application/json",
    }


def _base_url():
    return _settings().server_url.rstrip("/")


def _q(name):
    """URL-encode the instance name for path segments."""
    return quote(name or "", safe="")


def _handle(response):
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}

    if response.status_code >= 400:
        msg = None
        if isinstance(body, dict):
            resp = body.get("response") or {}
            if isinstance(resp, dict):
                msg = resp.get("message")
            if isinstance(msg, list):
                msg = "; ".join(str(m) for m in msg)
            msg = msg or body.get("message")
        msg = msg or response.text or "Evolution API error"
        frappe.log_error(
            title=f"Evolution API {response.status_code}",
            message=f"URL: {response.url}\nStatus: {response.status_code}\nBody: {body}",
        )
        frappe.throw(_(str(msg)), title=_("Evolution API Error"))

    return body


# ---------------------------------------------------------------------------
# Instance management (uses global API key)
# ---------------------------------------------------------------------------

def create_instance(instance_name):
    url = f"{_base_url()}/instance/create"
    payload = {
        "instanceName": instance_name,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }
    resp = requests.post(url, headers=_global_headers(), json=payload, timeout=TIMEOUT)
    return _handle(resp)


def get_qrcode(instance_name, instance_api_key):
    url = f"{_base_url()}/instance/connect/{_q(instance_name)}"
    resp = requests.get(url, headers=_instance_headers(instance_api_key), timeout=TIMEOUT)
    return _handle(resp)


def connection_state(instance_name, instance_api_key):
    url = f"{_base_url()}/instance/connectionState/{_q(instance_name)}"
    resp = requests.get(url, headers=_instance_headers(instance_api_key), timeout=TIMEOUT)
    return _handle(resp)


def fetch_instance(instance_name):
    url = f"{_base_url()}/instance/fetchInstances"
    params = {"instanceName": instance_name}
    resp = requests.get(url, headers=_global_headers(), params=params, timeout=TIMEOUT)
    return _handle(resp)


def logout_instance(instance_name, instance_api_key):
    url = f"{_base_url()}/instance/logout/{_q(instance_name)}"
    resp = requests.delete(url, headers=_instance_headers(instance_api_key), timeout=TIMEOUT)
    return _handle(resp)


def delete_instance(instance_name, instance_api_key=None):
    url = f"{_base_url()}/instance/delete/{_q(instance_name)}"
    headers = _instance_headers(instance_api_key) if instance_api_key else _global_headers()
    resp = requests.delete(url, headers=headers, timeout=TIMEOUT)
    return _handle(resp)


# ---------------------------------------------------------------------------
# Messaging (uses per-instance API key)
# ---------------------------------------------------------------------------

def send_text(instance_name, instance_api_key, number, text):
    url = f"{_base_url()}/message/sendText/{_q(instance_name)}"
    payload = {"number": number, "text": text}
    resp = requests.post(
        url, headers=_instance_headers(instance_api_key), json=payload, timeout=TIMEOUT
    )
    return _handle(resp)


def send_media(
    instance_name, instance_api_key, number,
    media_base64, file_name, mime_type, caption=None,
):
    url = f"{_base_url()}/message/sendMedia/{_q(instance_name)}"

    media_type = "document"
    if mime_type.startswith("image/"):
        media_type = "image"
    elif mime_type.startswith("video/"):
        media_type = "video"
    elif mime_type.startswith("audio/"):
        media_type = "audio"

    payload = {
        "number": number,
        "mediatype": media_type,
        "mimetype": mime_type,
        "media": media_base64,
        "fileName": file_name,
    }
    if caption:
        payload["caption"] = caption

    resp = requests.post(
        url, headers=_instance_headers(instance_api_key), json=payload, timeout=TIMEOUT * 2
    )
    return _handle(resp)
