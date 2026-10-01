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

---

## Audit General Ledger Query (v1.1.0)

A pure-SQL **Query Report** version with the same audit columns, toggles and row filters.

* Rows: Opening → transactions → Total → Closing (Opening + Total), running Balance.
* Account and Cost Center filters include child accounts / cost centers.
* Toggled-off audit columns are hidden on screen, in Print and PDF; in Excel they appear as empty columns
  (Query Reports have fixed SQL columns — use the Script Report above if Excel must drop them).
* Activity viewer uses the desk's own document timeline data (latest 10 field-change versions; "Open Document"
  shows everything).
* Covers created/modified for: Journal Entry, Sales/Purchase Invoice, Payment Entry, Purchase Receipt,
  Delivery Note, Stock Entry, Stock Reconciliation, Landed Cost Voucher, Period Closing Voucher,
  Exchange Rate Revaluation, Subcontracting Receipt. Other voucher types fall back to GL Entry stamps.
  To add one, edit `VOUCHERS` in `tools/gen_query_sql.py`, run
  `python3 tools/gen_query_sql.py`, paste into the report JSON `query`, and run `verify_tree.py`.

### Using it without the app
Desk → Report → New: Report Type **Query Report**, Ref DocType **GL Entry**, Is Standard **No**,
name **Audit General Ledger Query**. Paste the SQL into *Query* and the JS into *Javascript*, add roles, save.
