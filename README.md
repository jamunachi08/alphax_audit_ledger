# AlphaX Audit Ledger (v1.0.0)

**Audit General Ledger** for ERPNext v15 — the standard General Ledger, plus a full audit trail on every voucher row.

## What it does

The report calls ERPNext's own General Ledger engine, so every number, opening balance, grouping
("Categorize by Voucher / Account / Party"), dimension, finance book and currency option is identical to
the standard report. Filters are inherited live from the installed General Ledger, so ERPNext updates flow
through automatically. Audit data is then added on top.

### Audit columns (each with an on/off checkbox)

| Toggle | Columns |
|---|---|
| Show Created By / Created On | Voucher owner and creation timestamp |
| Show Modified By / Modified On | Last modifier and timestamp |
| Show Submitted By / On | Document status, submitter, submit time (falls back to first GL posting for docs submitted on insert) |
| Show Cancelled By / On | Canceller and cancel time |
| Show GL Entry Audit Stamps | GL Posted By/On, GL Modified By/On, GL Cancelled |
| Show Complete Activity | Clickable activity summary, event count, edits after submit (red), last activity by/on, amended from |

Clicking **Complete Activity** opens the voucher's full history: field-level changes (old → new), child-table
row changes, submit/cancel, edits after submit, comments, assignments, attachments, sharing, workflow,
emails, print/PDF/export access log, views (if Track Views is on), GL posting and amendments — with a CSV download.

### Audit filters
Created By / Modified By / Submitted By (multi-user), Modified From/To, Only Vouchers Edited After Submit.
When any of these is active, opening and subtotal rows are removed and the balance becomes a running
total of the rows shown (the report displays a note).

### Add columns
* **Add GL Entry Columns** — any readable GL Entry field.
* **Add Voucher Columns** — any header field of the voucher (Journal Entry, Sales/Purchase Invoice, Payment Entry, Stock Entry…). Blank where a voucher type has no such field.
* Standard **Menu → Pick Columns** also works.
* Field-level permissions (permlevel) are respected.

### Show / hide columns, export, print
* **Audit → Show / Hide Columns** — hide any column (standard or audit). Hidden columns are removed server-side,
  so Excel, PDF, Print and Auto Email all match the screen. Choice is remembered per user on that browser.
* **Export → Excel / PDF / Print** toolbar, plus every standard menu action: Export (Excel/CSV), Print, PDF,
  Setup Auto Email, Save As, Add to Workspace, User Permissions.

## Install

**Frappe Cloud:** push this repo to GitHub, add the app to the bench group, deploy, install on the site.

**Bench:**
```bash
bench get-app https://github.com/jamunachi08/alphax_audit_ledger
bench --site <site> install-app alphax_audit_ledger
bench --site <site> migrate
```

Open via the awesome bar: **Audit General Ledger**. Roles: Accounts User, Accounts Manager, Auditor, System Manager.

## Notes
* Submit/cancel history comes from the Version log, which ERPNext enables (Track Changes) on all main vouchers.
  If a doctype has Track Changes off, submitter falls back to the first GL Entry and canceller to the last modifier.
* For very long periods with "Show Complete Activity" on, narrow by account/party for speed, or untick it.
* Run `python3 verify_tree.py` before each push.
