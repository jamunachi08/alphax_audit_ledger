# Copyright (c) 2026, Neotec Integrated Solutions and contributors
# For license information, please see license.txt
"""AlphaX Audit General Ledger.

Runs ERPNext's own General Ledger engine unchanged — so opening balances, grouping,
dimensions, finance books and currency handling always match the standard report on
whatever v15 patch level is installed — then layers an audit trail on every voucher row.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

from erpnext.accounts.report.general_ledger.general_ledger import execute as gl_execute

from alphax_audit_ledger.utils import (
	as_list,
	chunks,
	column_from_df,
	docstatus_change,
	docstatus_label,
	has_field_changes,
	parse_json_safe,
	selectable_fields,
)

# Column toggles and their defaults when the report is run without the UI (API / scheduler).
TOGGLE_DEFAULTS = {
	"show_created_by": 1,
	"show_created_on": 1,
	"show_modified_by": 1,
	"show_modified_on": 1,
	"show_submitted": 1,
	"show_cancelled": 0,
	"show_gl_audit": 0,
	"show_activity": 1,
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	opts = extract_options(filters)

	result = gl_execute(filters)
	columns = list(result[0] or [])
	data = list(result[1] or [])
	extra = list(result[2:]) if len(result) > 2 else []

	voucher_rows = [
		r for r in data if isinstance(r, dict) and r.get("voucher_type") and r.get("voucher_no")
	]

	ctx = AuditContext(voucher_rows, opts)
	ctx.load()
	ctx.apply()

	note = None
	if opts.has_row_filters:
		data = apply_row_filters(data, voucher_rows, opts)
		note = _(
			"Audit filters are active: opening and group subtotal rows are hidden and the "
			"balance is a running total of the rows shown."
		)

	columns.extend(ctx.columns())
	if opts.hidden_columns:
		columns = [c for c in columns if column_fieldname(c) not in opts.hidden_columns]

	if note and not extra:
		return columns, data, note
	return (columns, data, *extra)


def extract_options(filters):
	"""Remove audit-only keys so the standard GL engine never sees them."""
	ui = filters.pop("audit_ui", None)
	opts = frappe._dict()
	for key, default in TOGGLE_DEFAULTS.items():
		raw = filters.pop(key, None)
		# The desk omits unchecked boxes; when the UI marker is present, missing means "off".
		opts[key] = (0 if ui else default) if raw in (None, "") else cint(raw)

	opts.created_by_users = set(as_list(filters.pop("audit_created_by", None)))
	opts.modified_by_users = set(as_list(filters.pop("audit_modified_by", None)))
	opts.submitted_by_users = set(as_list(filters.pop("audit_submitted_by", None)))
	opts.modified_from = filters.pop("audit_modified_from", None)
	opts.modified_to = filters.pop("audit_modified_to", None)
	opts.only_edited_after_submit = cint(filters.pop("only_edited_after_submit", 0))
	opts.extra_gl_fields = as_list(filters.pop("extra_gl_fields", None))
	opts.extra_voucher_fields = as_list(filters.pop("extra_voucher_fields", None))
	opts.hidden_columns = set(as_list(filters.pop("hidden_columns", None)))

	opts.has_row_filters = bool(
		opts.created_by_users
		or opts.modified_by_users
		or opts.submitted_by_users
		or opts.modified_from
		or opts.modified_to
		or opts.only_edited_after_submit
	)
	return opts


def column_fieldname(col):
	if isinstance(col, dict):
		return col.get("fieldname")
	return frappe.scrub(str(col).split(":")[0])


class AuditContext:
	def __init__(self, rows, opts):
		self.rows = rows
		self.opts = opts
		self.by_type = defaultdict(set)
		for r in rows:
			self.by_type[r.get("voucher_type")].add(r.get("voucher_no"))

		self.vouchers = {}
		self.versions = defaultdict(list)
		self.comments = defaultdict(list)
		self.gl = {}
		self.summary = {}
		self.voucher_extra_df = {}
		self.gl_extra_df = {}

	@property
	def needs_history(self):
		o = self.opts
		return bool(
			o.show_submitted
			or o.show_cancelled
			or o.show_activity
			or o.only_edited_after_submit
			or o.submitted_by_users
		)

	# ---------------------------------------------------------------- loading
	def load(self):
		if not self.rows:
			self._register_extra_columns_only()
			return
		self._load_vouchers()
		if self.needs_history:
			self._load_versions()
		if self.opts.show_activity:
			self._load_comments()
		self._load_gl()
		self._summarise()

	def _register_extra_columns_only(self):
		"""Keep requested extra columns visible even when the period has no rows."""
		gl_meta = frappe.get_meta("GL Entry")
		allowed = {df.fieldname: df for df in selectable_fields(gl_meta)}
		for f in self.opts.extra_gl_fields:
			if f in allowed:
				self.gl_extra_df[f] = allowed[f]

	def _load_vouchers(self):
		for vt, names in self.by_type.items():
			if not vt or not frappe.db.exists("DocType", vt):
				continue
			meta = frappe.get_meta(vt)
			if meta.istable or meta.issingle:
				continue
			fields = ["name", "owner", "creation", "modified_by", "modified", "docstatus"]
			if meta.has_field("amended_from"):
				fields.append("amended_from")

			allowed = {df.fieldname: df for df in selectable_fields(meta)}
			extras = [f for f in self.opts.extra_voucher_fields if f in allowed]
			for f in extras:
				self.voucher_extra_df.setdefault(f, allowed[f])
				if f not in fields:
					fields.append(f)

			for chunk in chunks(sorted(names)):
				for d in frappe.get_all(vt, filters={"name": ("in", chunk)}, fields=fields):
					self.vouchers[(vt, d.name)] = d

	def _load_versions(self):
		for vt, names in self.by_type.items():
			for chunk in chunks(sorted(names)):
				for v in frappe.get_all(
					"Version",
					filters={"ref_doctype": vt, "docname": ("in", chunk)},
					fields=["docname", "owner", "creation", "data"],
					order_by="creation asc",
				):
					self.versions[(vt, v.docname)].append(v)

	def _load_comments(self):
		for vt, names in self.by_type.items():
			for chunk in chunks(sorted(names)):
				for c in frappe.get_all(
					"Comment",
					filters={
						"reference_doctype": vt,
						"reference_name": ("in", chunk),
						"comment_type": ("not in", ("Like", "Label")),
					},
					fields=["reference_name", "owner", "creation", "comment_type"],
					order_by="creation asc",
				):
					self.comments[(vt, c.reference_name)].append(c)

	def _load_gl(self):
		o = self.opts
		gl_meta = frappe.get_meta("GL Entry")
		allowed = {df.fieldname: df for df in selectable_fields(gl_meta)}
		extras = [f for f in o.extra_gl_fields if f in allowed]
		for f in extras:
			self.gl_extra_df[f] = allowed[f]

		if not (o.show_gl_audit or extras):
			return
		names = {r.get("gl_entry") for r in self.rows if r.get("gl_entry")}
		fields = ["name", "owner", "creation", "modified_by", "modified", "is_cancelled"]
		fields += [f for f in extras if f not in fields]
		for chunk in chunks(sorted(names)):
			for g in frappe.get_all("GL Entry", filters={"name": ("in", chunk)}, fields=fields):
				self.gl[g.name] = g

	# ------------------------------------------------------------ summarising
	def _summarise(self):
		pending_submit = defaultdict(list)

		for key, doc in self.vouchers.items():
			s = frappe._dict(
				created_by=doc.owner,
				created_on=doc.creation,
				modified_by=doc.modified_by,
				modified_on=doc.modified,
				docstatus=cint(doc.docstatus),
				amended_from=doc.get("amended_from"),
				submitted_by=None,
				submitted_on=None,
				cancelled_by=None,
				cancelled_on=None,
				draft_edits=0,
				post_submit_edits=0,
				events=1,
				comments=0,
				last_by=doc.modified_by,
				last_on=doc.modified,
			)

			for v in self.versions.get(key, []):
				data = parse_json_safe(v.data)
				new_status = docstatus_change(data)
				if new_status == 1:
					s.submitted_by, s.submitted_on = v.owner, v.creation
				elif new_status == 2:
					s.cancelled_by, s.cancelled_on = v.owner, v.creation
				elif has_field_changes(data):
					if s.submitted_on and not s.cancelled_on:
						s.post_submit_edits += 1
					elif not s.submitted_on:
						s.draft_edits += 1
				s.events += 1
				self._touch(s, v.owner, v.creation)

			for c in self.comments.get(key, []):
				s.events += 1
				if c.comment_type == "Comment":
					s.comments += 1
				self._touch(s, c.owner, c.creation)

			if s.docstatus == 2 and not s.cancelled_by:
				s.cancelled_by, s.cancelled_on = doc.modified_by, doc.modified
			if s.docstatus in (1, 2) and not s.submitted_by and self.needs_history:
				pending_submit[key[0]].append(key[1])

			self.summary[key] = s

		self._fill_submit_from_gl(pending_submit)

		for s in self.summary.values():
			s.text = self._summary_text(s)

	@staticmethod
	def _touch(s, user, when):
		if when and (not s.last_on or get_datetime(when) > get_datetime(s.last_on)):
			s.last_by, s.last_on = user, when

	def _fill_submit_from_gl(self, pending):
		"""Docs submitted on insert (API, POS, auto-created) have no submit Version:
		the first GL Entry carries the submitting user and timestamp."""
		for vt, names in pending.items():
			for chunk in chunks(sorted(set(names))):
				seen = set()
				for g in frappe.db.sql(
					"""select voucher_no, owner, creation from `tabGL Entry`
					where voucher_type = %s and voucher_no in %s
					order by creation asc""",
					(vt, tuple(chunk)),
					as_dict=True,
				):
					if g.voucher_no in seen:
						continue
					seen.add(g.voucher_no)
					s = self.summary.get((vt, g.voucher_no))
					if s and not s.submitted_by:
						s.submitted_by, s.submitted_on = g.owner, g.creation

	@staticmethod
	def _summary_text(s):
		parts = [_("Created")]
		if s.draft_edits:
			parts.append(_("{0} draft edit(s)").format(s.draft_edits))
		if s.docstatus in (1, 2):
			parts.append(_("Submitted"))
		if s.post_submit_edits:
			parts.append(_("{0} edit(s) after submit").format(s.post_submit_edits))
		if s.docstatus == 2:
			parts.append(_("Cancelled"))
		if s.amended_from:
			parts.append(_("Amended from {0}").format(s.amended_from))
		if s.comments:
			parts.append(_("{0} comment(s)").format(s.comments))
		return " → ".join(parts)

	# ---------------------------------------------------------------- output
	def apply(self):
		for r in self.rows:
			s = self.summary.get((r.get("voucher_type"), r.get("voucher_no")))
			if s:
				r["v_created_by"] = s.created_by
				r["v_created_on"] = s.created_on
				r["v_modified_by"] = s.modified_by
				r["v_modified_on"] = s.modified_on
				r["v_doc_status"] = docstatus_label(s.docstatus)
				r["v_submitted_by"] = s.submitted_by
				r["v_submitted_on"] = s.submitted_on
				r["v_cancelled_by"] = s.cancelled_by
				r["v_cancelled_on"] = s.cancelled_on
				r["v_amended_from"] = s.amended_from
				r["v_activity_summary"] = s.text
				r["v_activity_events"] = s.events
				r["v_edits_after_submit"] = s.post_submit_edits
				r["v_last_activity_by"] = s.last_by
				r["v_last_activity_on"] = s.last_on

				doc = self.vouchers.get((r.get("voucher_type"), r.get("voucher_no"))) or {}
				for f in self.voucher_extra_df:
					r["vx_" + f] = doc.get(f)

			g = self.gl.get(r.get("gl_entry"))
			if g:
				r["gl_created_by"] = g.owner
				r["gl_created_on"] = g.creation
				r["gl_modified_by"] = g.modified_by
				r["gl_modified_on"] = g.modified
				r["gl_is_cancelled"] = cint(g.is_cancelled)
				for f in self.gl_extra_df:
					r["glx_" + f] = g.get(f)

	def columns(self):
		o = self.opts
		cols = []

		def add(fieldname, label, fieldtype, options=None, width=150):
			cols.append(
				{"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "options": options, "width": width}
			)

		if o.show_created_by:
			add("v_created_by", _("Created By"), "Link", "User", 170)
		if o.show_created_on:
			add("v_created_on", _("Created On"), "Datetime", None, 165)
		if o.show_modified_by:
			add("v_modified_by", _("Modified By"), "Link", "User", 170)
		if o.show_modified_on:
			add("v_modified_on", _("Modified On"), "Datetime", None, 165)
		if o.show_submitted:
			add("v_doc_status", _("Document Status"), "Data", None, 115)
			add("v_submitted_by", _("Submitted By"), "Link", "User", 170)
			add("v_submitted_on", _("Submitted On"), "Datetime", None, 165)
		if o.show_cancelled:
			add("v_cancelled_by", _("Cancelled By"), "Link", "User", 170)
			add("v_cancelled_on", _("Cancelled On"), "Datetime", None, 165)
		if o.show_gl_audit:
			add("gl_created_by", _("GL Posted By"), "Link", "User", 170)
			add("gl_created_on", _("GL Posted On"), "Datetime", None, 165)
			add("gl_modified_by", _("GL Modified By"), "Link", "User", 170)
			add("gl_modified_on", _("GL Modified On"), "Datetime", None, 165)
			add("gl_is_cancelled", _("GL Cancelled"), "Check", None, 95)
		if o.show_activity:
			add("v_activity_summary", _("Complete Activity"), "Data", None, 330)
			add("v_activity_events", _("Activity Events"), "Int", None, 105)
			add("v_edits_after_submit", _("Edits After Submit"), "Int", None, 125)
			add("v_last_activity_by", _("Last Activity By"), "Link", "User", 170)
			add("v_last_activity_on", _("Last Activity On"), "Datetime", None, 165)
			add("v_amended_from", _("Amended From"), "Data", None, 150)

		for f, df in self.voucher_extra_df.items():
			cols.append(column_from_df(df, "vx_" + f, _("Voucher")))
		for f, df in self.gl_extra_df.items():
			cols.append(column_from_df(df, "glx_" + f, _("GL")))
		return cols


def apply_row_filters(data, voucher_rows, opts):
	ids = {id(r) for r in voucher_rows}
	from_date = getdate(opts.modified_from) if opts.modified_from else None
	to_date = getdate(opts.modified_to) if opts.modified_to else None

	def keep(r):
		if opts.created_by_users and r.get("v_created_by") not in opts.created_by_users:
			return False
		if opts.modified_by_users and r.get("v_modified_by") not in opts.modified_by_users:
			return False
		if opts.submitted_by_users and r.get("v_submitted_by") not in opts.submitted_by_users:
			return False
		if from_date or to_date:
			if not r.get("v_modified_on"):
				return False
			modified = getdate(r.get("v_modified_on"))
			if from_date and modified < from_date:
				return False
			if to_date and modified > to_date:
				return False
		if opts.only_edited_after_submit and not cint(r.get("v_edits_after_submit")):
			return False
		return True

	kept = [r for r in data if id(r) in ids and keep(r)]

	balance = total_debit = total_credit = 0.0
	for r in kept:
		total_debit += flt(r.get("debit"))
		total_credit += flt(r.get("credit"))
		balance += flt(r.get("debit")) - flt(r.get("credit"))
		r["balance"] = balance

	kept.append(
		frappe._dict(
			account="'" + _("Total") + "'",
			debit=total_debit,
			credit=total_credit,
			balance=balance,
			bold=1,
		)
	)
	return kept
