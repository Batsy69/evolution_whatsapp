# Evolution Whatsapp

Frappe v16 app for sending WhatsApp messages from ERPNext via [Evolution API v2](https://doc.evolution-api.com/v2/).

**Shared-number model:** WhatsApp Manager creates org-level numbers ("Sales", "Dispatch", "Support"), assigns users to each. Users send from numbers they're assigned to via the three-dots menu on any DocType.

> Powered by Evolution API.

## Roles

- **WhatsApp Manager** — manages numbers, assigns users, scans QR codes, monitors status. Created automatically as a fixture on install.
- **System Manager** — full access (audit/admin).
- **All other users** — can send from numbers assigned to them. Their WhatsApp Number list is filtered to only the numbers they're assigned to (read-only). Their WhatsApp Message log shows only their own sends.

## Setup

1. Push to GitHub as `evolution_whatsapp` → install on Frappe Cloud bench → install on site.
2. Open **Evolution Whatsapp Settings** (System Manager only):
   - Server URL: `https://evolution.example.com`
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

- **Send from** — only WhatsApp Numbers assigned to the current user are listed.
- **Send to** — single field with an inline country-code dropdown: `[+91 ▾]–[9876543210]`. Country code defaults to the value in Settings; recipient digits auto-fill from the linked Contact (see below).
- **Other contacts** — appears only when 2+ Contacts are linked, lets you swap recipients.
- **Phone resolution** — strictly via the **Contact** DocType. The resolver finds Contacts dynamically linked to the current document (or to its primary party — Customer / Supplier / Lead / Employee / Job Applicant). Address phone numbers and direct phone fields on the source document are not used.
- **Attach** — existing files attached to the doc, an ad-hoc upload, or a Print Format PDF (see below).
- **Print format** — a single Check field if the doctype has exactly one enabled format (or a default is set in Customize Form), or a Select if multiple are available. Letterhead is read silently from the document's `letter_head` field — no UI exposure.
- **Background queue** — the dialog closes instantly and the send happens in a worker. A minimal `✓ Sent — +<number>` toast confirms each send.
- **Timeline** — every document you can send WhatsApp from grows a "WhatsApp Messages" block at the bottom showing each send: status, sender number, recipient number, the user who sent it, time, message preview, and any attachment.

## Permissions

- WhatsApp Numbers are listed in read-only form for users who are assigned to them. Managers see all.
- WhatsApp Messages are owner-scoped: each user sees only their own; System Manager sees all.

## v1 scope

- Outbound only — no inbound webhook receiver, no inbox UI.

## License

MIT
