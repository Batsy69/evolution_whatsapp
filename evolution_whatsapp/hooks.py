from . import __version__ as app_version  # noqa: F401

app_name = "evolution_whatsapp"
app_title = "Evolution Whatsapp"
app_publisher = "Yusuf"
app_description = "ERPNext WhatsApp integration via Evolution API v2 (shared-number model)"
app_email = "yusufpaloba43@outlook.com"
app_license = "MIT"

# Inject the three-dots menu "Send WhatsApp" item on every DocType form.
app_include_js = "/assets/evolution_whatsapp/js/evolution_whatsapp.js"

doc_events = {
    "WhatsApp Number": {
        "before_insert": "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.before_insert",
        "after_insert": "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.after_insert",
        "on_trash": "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.on_trash",
    },
}

# Filter the WhatsApp Number list to only show numbers assigned to the current
# user (managers bypass via empty filter). Both list query and individual-doc
# permission checks go through the same membership predicate.
permission_query_conditions = {
    "WhatsApp Number": "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.get_permission_query_conditions",
}

has_permission = {
    "WhatsApp Number": "evolution_whatsapp.evolution_whatsapp.doctype.whatsapp_number.whatsapp_number.has_permission",
}

# Ship the WhatsApp Manager role so it's created on first migrate.
fixtures = [
    {"dt": "Role", "filters": [["name", "in", ["WhatsApp Manager"]]]},
]
