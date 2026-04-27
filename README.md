# Evolution Whatsapp

Frappe v16 app for sending WhatsApp messages from ERPNext via [Evolution API v2](https://doc.evolution-api.com/v2/).

**Shared-number model:** WhatsApp Manager creates org-level numbers ("Sales", "Dispatch", "Support"), assigns users to each. Users send from numbers they're assigned to via the three-dots menu on any DocType.

> Powered by Evolution API.

## Roles

- **WhatsApp Manager** — manages numbers, assigns users, scans QR codes, monitors status. Created automatically as a fixture on install.
- **System Manager** — full access (audit/admin).
- **All other users** — can send from numbers assigned to them, only see their own sent message log.

## Setup

1. Push to GitHub as `evolution_whatsapp` → install on Frappe Cloud bench → install on site.
2. Open **Evolution Whatsapp Settings** (System Manager only):
   - Server URL: `https://evolution.metalmanautomation.com`
   - Global API Key: from your Evolution `AUTHENTICATION_API_KEY`
   - Default Country Code: `91` (or your region's default)
   - Click **Test Connection**.
3. Assign the **WhatsApp Manager** role to whoever should manage numbers.
4. **WhatsApp Manager → New WhatsApp Number:**
   - Display Name: e.g. "Sales Number"
   - Save → instance is created on Evolution → QR appears
   - Scan from a phone (WhatsApp → Settings → Linked Devices)
   - Status flips to **Connected**, phone number is fetched automatically
5. **Assign Users:** open the WhatsApp Number → Actions → **Assign Users** → tick users → Save.
6. Anyone assigned can now: open any document → ⋯ menu → **Send WhatsApp**.

## Send dialog

- Picks "Send from" number (only assigned numbers shown)
- Country code dropdown next to recipient (default from Settings, override per send)
- Phone resolution: walks doc fields → linked Contacts → linked Addresses → party records
- Attach: existing files attached to the doc, or generate a Print Format PDF, or upload ad-hoc
- Background queue: dialog closes instantly, send happens in worker, real-time toast on success/failure
- Timeline comment is added to the source document with sender + number + timestamp

## v1 scope

- Outbound only — no inbound webhook receiver, no inbox UI.
- Per-user audit on `WhatsApp Message` records (each user sees only their own sends; System Manager sees all).

## License

MIT
