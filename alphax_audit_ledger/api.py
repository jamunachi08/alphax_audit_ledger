# Copyright (c) 2026, Neotec Integrated Solutions and contributors
# For license information, please see license.txt
"""Whitelisted endpoints used by the Audit General Ledger report."""

import frappe
from frappe import _
from frappe.utils import cint, cstr, get_datetime, strip_html

from alphax_audit_ledger.utils import (
	describe_version,
	docstatus_label,
	parse_json_safe,
	selectable_fields,
)

VOUCHER_DOCTYPES = (
	"Journal Entry",
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Purchase Receipt",
	"Delivery Note",
	"Stock Entry",
	"Stock Reconciliation",
	"Landed Cost Voucher",
	"Period Closing Voucher",
	"Exchange Rate Revaluation",
	"Invoice Discounting",
	"Asset",
	"Asset Capitalization",
	"Subcontracting Receipt",
	"POS Invoice",
	"Expense Claim",
	"Payroll Entry",
)

COMMENT_KIND = {
	"Comment": "comment",
	"Info": "info",
	"Edit": "info",
	"Assigned": "assigned",
	"Assignment Completed": "assigned",
	"Attachment": "attachment",
	"Attachment Removed": "attachment",
	"Shared": "shared",
	"Unshared": "shared",
	"Workflow": "workflow",
	"Like": "info",
	"Label": "info",
}


def _check_report_access():
	if not frappe.has_permission("GL Entry", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def get_field_options(scope="gl", txt=None):
	"""Field picker for the 'Add GL Entry Columns' / 'Add Voucher Columns' filters."""
	_check_report_access()
	txt = cstr(txt).lower().strip()

	if scope == "gl":
		doctypes = ["GL Entry"]
	else:
		doctypes = [d for d in VOUCHER_DOCTYPES if frappe.db.exists("DocType", d)]

	options = {}
	for doctype in doctypes:
		meta = frappe.get_meta(doctype)
		for df in selectable_fields(meta):
			label = _(df.label or df.fieldname)
			if scope != "gl":
				label = f"{label} — {_(doctype)}"
			if df.fieldname in options:
				if scope != "gl" and _(doctype) not in options[df.fieldname]:
					options[df.fieldname] += f", {_(doctype)}"
				continue
			options[df.fieldname] = label

	result = [
		{"value": fieldname, "description": label}
		for fieldname, label in options.items()
		if not txt or txt in fieldname.lower() or txt in label.lower()
	]
	result.sort(key=lambda d: d["description"].lower())
	return result[:200]


@frappe.whitelist()
def get_users(txt=None):
	"""User picker for audit filters (avoids needing read access on User)."""
	_check_report_access()
	or_filters = None
	if txt:
		like = f"%{cstr(txt).strip()}%"
		or_filters = {"name": ("like", like), "full_name": ("like", like)}
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ("!=", "Guest")},
		or_filters=or_filters,
		fields=["name", "full_name"],
		order_by="full_name asc",
		limit_page_length=30,
	)
	return [{"value": u.name, "description": u.full_name or ""} for u in users]


@frappe.whitelist()
def get_voucher_activity(voucher_type, voucher_no):
	"""Complete activity of one voucher: versions, comments, emails, prints/exports, views, GL postings."""
	voucher_type = cstr(voucher_type).strip()
	voucher_no = cstr(voucher_no).strip()

	if not voucher_type or not voucher_no or not frappe.db.exists("DocType", voucher_type):
		frappe.throw(_("Invalid voucher reference"))
	meta = frappe.get_meta(voucher_type)
	if meta.istable or meta.issingle:
		frappe.throw(_("Invalid voucher reference"))
	if not frappe.db.exists(voucher_type, voucher_no):
		frappe.throw(_("{0} {1} does not exist").format(_(voucher_type), voucher_no))
	frappe.has_permission(voucher_type, "read", doc=voucher_no, throw=True)

	fields = ["name", "owner", "creation", "modified_by", "modified", "docstatus"]
	if meta.has_field("amended_from"):
		fields.append("amended_from")
	doc = frappe.db.get_value(voucher_type, voucher_no, fields, as_dict=True)

	header = frappe._dict(
		created_by=doc.owner,
		created_on=cstr(doc.creation),
		modified_by=doc.modified_by,
		modified_on=cstr(doc.modified),
		docstatus=cint(doc.docstatus),
		status=docstatus_label(doc.docstatus),
		amended_from=doc.get("amended_from"),
		submitted_by=None,
		submitted_on=None,
		cancelled_by=None,
		cancelled_on=None,
		edits_after_submit=0,
		amendments=[],
	)
	events = []

	def add(time, user, kind, title, details=None):
		if time:
			events.append(
				{"time": cstr(time), "user": user, "kind": kind, "title": title, "details": details or []}
			)

	add(doc.creation, doc.owner, "created", _("Created"),
		[_("Amended from {0}").format(doc.amended_from)] if doc.get("amended_from") else [])

	# 1. Versions (field-level change history)
	for v in frappe.get_all(
		"Version",
		filters={"ref_doctype": voucher_type, "docname": voucher_no},
		fields=["owner", "creation", "data"],
		order_by="creation asc",
	):
		kind, title, lines = describe_version(voucher_type, parse_json_safe(v.data))
		if kind == "submitted":
			header.submitted_by, header.submitted_on = v.owner, cstr(v.creation)
		elif kind == "cancelled":
			header.cancelled_by, header.cancelled_on = v.owner, cstr(v.creation)
		elif header.submitted_on and not header.cancelled_on:
			kind, title = "post_submit", _("Edited after submit")
			header.edits_after_submit += 1
		add(v.creation, v.owner, kind, title, lines)

	# 2. Comments, assignments, attachments, shares, workflow
	for c in frappe.get_all(
		"Comment",
		filters={"reference_doctype": voucher_type, "reference_name": voucher_no},
		fields=["comment_type", "content", "owner", "creation"],
		order_by="creation asc",
	):
		text = strip_html(cstr(c.content)).strip()
		add(c.creation, c.owner, COMMENT_KIND.get(c.comment_type, "info"), _(c.comment_type),
			[text[:500]] if text else [])

	# 3. Emails / communications
	for m in frappe.get_all(
		"Communication",
		filters={"reference_doctype": voucher_type, "reference_name": voucher_no},
		fields=["communication_medium", "sent_or_received", "subject", "sender", "owner", "creation"],
		order_by="creation asc",
	):
		add(m.creation, m.owner, "email",
			_("{0} ({1})").format(_(m.communication_medium or "Communication"), _(m.sent_or_received or "")),
			[x for x in (cstr(m.subject), _("From: {0}").format(m.sender) if m.sender else "") if x])

	# 4. Prints / PDF downloads / exports (Access Log)
	if frappe.db.exists("DocType", "Access Log"):
		try:
			for a in frappe.get_all(
				"Access Log",
				filters={"export_from": voucher_type, "reference_document": voucher_no},
				fields=["user", "creation", "file_type", "method"],
				order_by="creation asc",
			):
				add(a.creation, a.user, "access",
					_("{0} {1}").format(_(a.method or "Accessed"), a.file_type or "").strip())
		except Exception:
			pass

	# 5. Views (only when "Track Views" is enabled on the doctype)
	if cint(meta.get("track_views")) and frappe.db.exists("DocType", "View Log"):
		try:
			for vl in frappe.get_all(
				"View Log",
				filters={"reference_doctype": voucher_type, "reference_name": voucher_no},
				fields=["viewed_by", "creation"],
				order_by="creation asc",
			):
				add(vl.creation, vl.viewed_by, "view", _("Viewed"))
		except Exception:
			pass

	# 6. GL postings
	gl_rows = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no},
		fields=["owner", "creation", "is_cancelled", "modified_by", "modified"],
		order_by="creation asc",
	)
	gl = {"total": len(gl_rows), "cancelled": sum(cint(g.is_cancelled) for g in gl_rows)}
	if gl_rows:
		first = gl_rows[0]
		gl.update(posted_by=first.owner, posted_on=cstr(first.creation))
		add(first.creation, first.owner, "posted",
			_("GL entries posted"), [_("{0} GL rows, {1} cancelled").format(gl["total"], gl["cancelled"])])
		if not header.submitted_by and header.docstatus in (1, 2):
			header.submitted_by, header.submitted_on = first.owner, cstr(first.creation)
	if header.docstatus == 2 and not header.cancelled_by:
		header.cancelled_by, header.cancelled_on = doc.modified_by, cstr(doc.modified)

	# 7. Amendments made from this voucher
	if meta.has_field("amended_from"):
		for am in frappe.get_all(
			voucher_type,
			filters={"amended_from": voucher_no},
			fields=["name", "owner", "creation"],
		):
			header.amendments.append(am.name)
			add(am.creation, am.owner, "amended", _("Amended as {0}").format(am.name))

	events.sort(key=lambda e: get_datetime(e["time"]))

	user_ids = {e["user"] for e in events if e.get("user")} | {
		u for u in (header.created_by, header.modified_by, header.submitted_by, header.cancelled_by) if u
	}
	users = {
		u.name: (u.full_name or u.name)
		for u in frappe.get_all("User", filters={"name": ("in", list(user_ids) or [""])}, fields=["name", "full_name"])
	}

	return {
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"header": header,
		"events": events,
		"gl": gl,
		"users": users,
	}
