# Automate Subcontracting ERPNext

A custom Frappe app for Rinix Automation Pvt Ltd that automates the ERPNext subcontracting workflow.

## What it does

Adds an **Automate Subcontracting** button on submitted Subcontracting Material Requests. From one form, it automatically creates:

- Bill of Materials (if not already existing)
- Subcontracting Purchase Order
- Subcontracting Order

## Requirements

- ERPNext v16
- Frappe v16

## Installation

```bash
bench get-app https://github.com/YOUR_USERNAME/automate_subcontracting
bench --site your-site install-app automate_subcontracting
bench --site your-site migrate
```
