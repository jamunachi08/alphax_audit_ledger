# Changelog

## 1.0.0 — 2026-10-01
- New Script Report **Audit General Ledger** (ref doctype GL Entry).
- Runs the installed ERPNext General Ledger engine unchanged; inherits its filters/formatter live.
- Audit columns with on/off toggles: Created By/On, Modified By/On, Submitted By/On + status,
  Cancelled By/On, GL Entry audit stamps, Complete Activity (summary, events, edits after submit,
  last activity by/on, amended from).
- Audit row filters: Created/Modified/Submitted By (multi-user), Modified date range,
  Only vouchers edited after submit (running balance recomputed).
- Add Columns: any readable GL Entry field and any voucher header field.
- Column Manager (show/hide, remembered per user/browser) — honoured by Excel, PDF and Print.
- Export toolbar (Excel / PDF / Print) plus all standard menu actions.
- Activity viewer: versions with field-level diffs, child-row changes, comments, assignments,
  workflow, emails, print/export access log, views, GL posting, amendments; CSV download.
- Bilingual EN/AR.
