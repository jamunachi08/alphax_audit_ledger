# Copyright (c) 2026, Neotec Integrated Solutions and contributors
# For license information, please see license.txt
"""Shared helpers for AlphaX Audit Ledger."""

import json

import frappe
from frappe import _
from frappe.model import no_value_fields, table_fields
from frappe.utils import cint, cstr

CHUNK_SIZE = 500

SKIP_FIELDTYPES = set(no_value_fields) | set(table_fields) | {
	"Password",
	"Attach Image",
	"Signature",
	"Geolocation",
	"Code",
	"JSON",
	"HTML Editor",
	"Markdown Editor",
}

DOCSTATUS_LABELS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def as_list(value):
	"""Normalise MultiSelectList / comma string / JSON list into a clean list of strings."""
	if not value:
		return []
	if isinstance(value, str):
		value = value.strip()
		if value.startswith("["):
			try:
				value = json.loads(value)
			except ValueError:
				value = value.strip("[]").replace('"', "").split(",")
		else:
			value = value.split(",")
	if not isinstance(value, (list, tuple, set)):
		value = [value]
	return [cstr(v).strip() for v in value if cstr(v).strip()]


def chunks(seq, size=CHUNK_SIZE):
	seq = list(seq)
	for i in range(0, len(seq), size):
		yield seq[i : i + size]


def parse_json_safe(value):
	if isinstance(value, dict):
		return value
	try:
		data = json.loads(value or "{}")
		return data if isinstance(data, dict) else {}
	except (TypeError, ValueError):
		return {}


def docstatus_change(data):
	"""Return the new docstatus if this Version records a submit/cancel, else None."""
	for change in data.get("changed") or []:
		if isinstance(change, (list, tuple)) and len(change) >= 3 and change[0] == "docstatus":
			return cint(change[2])
	return None


def has_field_changes(data):
	for change in data.get("changed") or []:
		if isinstance(change, (list, tuple)) and change and change[0] != "docstatus":
			return True
	return bool(data.get("added") or data.get("removed") or data.get("row_changed"))


def docstatus_label(docstatus):
	return _(DOCSTATUS_LABELS.get(cint(docstatus), ""))


def selectable_fields(meta):
	"""Value fields of a doctype the current user is allowed to read."""
	try:
		permitted = set(meta.get_permitted_fieldnames())
	except Exception:
		permitted = None

	out = []
	for df in meta.fields:
		if not df.fieldname or df.fieldtype in SKIP_FIELDTYPES or df.get("is_virtual"):
			continue
		if permitted is not None:
			if df.fieldname not in permitted:
				continue
		elif cint(df.permlevel):
			continue
		out.append(df)
	return out


def column_from_df(df, fieldname, prefix):
	"""Build a report column for an extra (user-added) field."""
	fieldtype = df.fieldtype
	options = df.options
	if fieldtype == "Link":
		pass
	elif fieldtype in ("Date", "Datetime", "Time", "Int", "Float", "Percent", "Check"):
		options = None
	elif fieldtype == "Currency":
		options = None
	else:
		fieldtype, options = "Data", None
	return {
		"fieldname": fieldname,
		"label": f"{prefix}: {_(df.label or df.fieldname)}",
		"fieldtype": fieldtype,
		"options": options,
		"width": 140,
	}


def field_label(meta, fieldname):
	df = meta.get_field(fieldname) if meta else None
	return _(df.label) if df and df.label else cstr(fieldname)


def _fmt(value):
	if value in (None, ""):
		return "∅"
	text = cstr(value)
	return text if len(text) <= 120 else text[:117] + "…"


def describe_version(doctype, data):
	"""Turn a Version JSON payload into (kind, title, readable lines)."""
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		meta = None

	lines = []
	for change in data.get("changed") or []:
		if not isinstance(change, (list, tuple)) or len(change) < 3 or change[0] == "docstatus":
			continue
		lines.append(f"{field_label(meta, change[0])}: {_fmt(change[1])} → {_fmt(change[2])}")

	for key, verb in (("added", _("Row added to {0}")), ("removed", _("Row removed from {0}"))):
		for item in data.get(key) or []:
			if not isinstance(item, (list, tuple)) or not item:
				continue
			row = item[1] if len(item) > 1 and isinstance(item[1], dict) else {}
			idx = f" #{row.get('idx')}" if row.get("idx") else ""
			lines.append(verb.format(field_label(meta, item[0])) + idx)

	for item in data.get("row_changed") or []:
		if not isinstance(item, (list, tuple)) or len(item) < 4:
			continue
		child_meta = None
		table_df = meta.get_field(item[0]) if meta else None
		if table_df and table_df.options:
			try:
				child_meta = frappe.get_meta(table_df.options)
			except Exception:
				child_meta = None
		for change in item[3] or []:
			if isinstance(change, (list, tuple)) and len(change) >= 3:
				lines.append(
					f"{field_label(meta, item[0])} #{item[1]} · {field_label(child_meta, change[0])}: "
					f"{_fmt(change[1])} → {_fmt(change[2])}"
				)

	if data.get("comment"):
		lines.append(cstr(data.get("comment")))

	new_status = docstatus_change(data)
	if new_status == 1:
		return "submitted", _("Submitted"), lines
	if new_status == 2:
		return "cancelled", _("Cancelled"), lines
	return "edited", _("Edited"), lines
