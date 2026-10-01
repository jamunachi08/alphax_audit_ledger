"""Generates the Audit General Ledger Query SQL (keeps 12 voucher joins consistent)."""

VOUCHERS = [
    ("Journal Entry", "je"), ("Sales Invoice", "si"), ("Purchase Invoice", "pi"),
    ("Payment Entry", "pe"), ("Purchase Receipt", "pr"), ("Delivery Note", "dn"),
    ("Stock Entry", "ste"), ("Stock Reconciliation", "sr"), ("Landed Cost Voucher", "lcv"),
    ("Period Closing Voucher", "pcv"), ("Exchange Rate Revaluation", "err"),
    ("Subcontracting Receipt", "scr"),
]

def coalesce(field, fallback):
    return "COALESCE(" + ", ".join(f"{a}.{field}" for _, a in VOUCHERS) + f", {fallback})"

def ver_has(ds_from, ds_to):
    return f"IFNULL(JSON_CONTAINS(ver.data, '[[\"docstatus\",{ds_from},{ds_to}]]', '$.changed'), 0) = 1"

NOT_DOCSTATUS = "IFNULL(JSON_CONTAINS(ver.data, '[[\"docstatus\"]]', '$.changed'), 0) = 0"

# GL filters shared by period rows, opening row and the per-voucher audit set
COMMON = """gle.company = %(company)s
      AND (%(finance_book)s = '' OR IFNULL(gle.finance_book, '') IN ('', %(finance_book)s))
      AND (%(account)s = '' OR gle.account IN (
            SELECT ca.name FROM `tabAccount` ca, `tabAccount` pa
            WHERE pa.name = %(account)s AND ca.lft >= pa.lft AND ca.rgt <= pa.rgt))
      AND (%(voucher_type)s = '' OR gle.voucher_type = %(voucher_type)s)
      AND (%(voucher_no)s = '' OR gle.voucher_no = %(voucher_no)s)
      AND (%(party_type)s = '' OR gle.party_type = %(party_type)s)
      AND (%(party)s = '' OR gle.party = %(party)s)
      AND (%(cost_center)s = '' OR gle.cost_center IN (
            SELECT cc.name FROM `tabCost Center` cc, `tabCost Center` pc
            WHERE pc.name = %(cost_center)s AND cc.lft >= pc.lft AND cc.rgt <= pc.rgt))
      AND (%(project)s = '' OR gle.project = %(project)s)
      AND (%(show_cancelled_entries)s = 1 OR gle.is_cancelled = 0)"""

PERIOD = "gle.posting_date BETWEEN %(from_date)s AND %(to_date)s AND IFNULL(gle.is_opening, 'No') = 'No'"
OPENING = "(gle.posting_date < %(from_date)s OR (IFNULL(gle.is_opening, 'No') = 'Yes' AND gle.posting_date <= %(to_date)s))"

# internal column order shared by every UNION branch
COLS = ["seq", "posting_date", "gl_creation", "gl_name", "account", "debit", "credit",
        "voucher_type", "voucher_subtype", "voucher_no", "against", "party_type", "party",
        "cost_center", "project", "against_voucher_type", "against_voucher", "remarks",
        "doc_status", "created_by", "created_on", "modified_by", "modified_on",
        "submitted_by", "submitted_on", "cancelled_by", "cancelled_on",
        "gl_posted_by", "gl_posted_on", "activity", "activity_events",
        "edits_after_submit", "last_activity_by", "last_activity_on"]

def row(values):
    return ", ".join(f"{values.get(c, 'NULL')} AS {c}" for c in COLS)

joins = "\n".join(
    f"    LEFT JOIN `tab{dt}` {a} ON gle.voucher_type = '{dt}' AND {a}.name = gle.voucher_no"
    for dt, a in VOUCHERS)

voucher_audit = f"""
    LEFT JOIN (
      SELECT s.*,
        COALESCE(s.submitted_by_v, s.first_gl_by) AS submitted_by,
        COALESCE(s.submitted_on_v, s.first_gl_on) AS submitted_on,
        (SELECT COUNT(*) FROM `tabVersion` ver
          WHERE ver.ref_doctype = s.voucher_type AND ver.docname = s.voucher_no
            AND {NOT_DOCSTATUS}
            AND ver.creation < COALESCE(s.submitted_on_v, s.first_gl_on, '9999-12-31')) AS draft_edits,
        (SELECT COUNT(*) FROM `tabVersion` ver
          WHERE ver.ref_doctype = s.voucher_type AND ver.docname = s.voucher_no
            AND {NOT_DOCSTATUS}
            AND ver.creation > COALESCE(s.submitted_on_v, s.first_gl_on, '9999-12-31')
            AND ver.creation < COALESCE(s.cancelled_on_v, '9999-12-31')) AS post_submit_edits
      FROM (
        SELECT d.voucher_type, d.voucher_no,
          (SELECT ver.owner FROM `tabVersion` ver WHERE ver.ref_doctype = d.voucher_type AND ver.docname = d.voucher_no
             AND {ver_has(0, 1)} ORDER BY ver.creation LIMIT 1) AS submitted_by_v,
          (SELECT ver.creation FROM `tabVersion` ver WHERE ver.ref_doctype = d.voucher_type AND ver.docname = d.voucher_no
             AND {ver_has(0, 1)} ORDER BY ver.creation LIMIT 1) AS submitted_on_v,
          (SELECT ver.owner FROM `tabVersion` ver WHERE ver.ref_doctype = d.voucher_type AND ver.docname = d.voucher_no
             AND {ver_has(1, 2)} ORDER BY ver.creation LIMIT 1) AS cancelled_by_v,
          (SELECT ver.creation FROM `tabVersion` ver WHERE ver.ref_doctype = d.voucher_type AND ver.docname = d.voucher_no
             AND {ver_has(1, 2)} ORDER BY ver.creation LIMIT 1) AS cancelled_on_v,
          (SELECT COUNT(*) FROM `tabVersion` ver WHERE ver.ref_doctype = d.voucher_type AND ver.docname = d.voucher_no) AS version_count,
          (SELECT ver.creation FROM `tabVersion` ver WHERE ver.ref_doctype = d.voucher_type AND ver.docname = d.voucher_no
             ORDER BY ver.creation DESC LIMIT 1) AS last_version_on,
          (SELECT ver.owner FROM `tabVersion` ver WHERE ver.ref_doctype = d.voucher_type AND ver.docname = d.voucher_no
             ORDER BY ver.creation DESC LIMIT 1) AS last_version_by,
          (SELECT COUNT(*) FROM `tabComment` cm WHERE cm.reference_doctype = d.voucher_type AND cm.reference_name = d.voucher_no
             AND cm.comment_type NOT IN ('Like', 'Label')) AS comment_events,
          (SELECT COUNT(*) FROM `tabComment` cm WHERE cm.reference_doctype = d.voucher_type AND cm.reference_name = d.voucher_no
             AND cm.comment_type = 'Comment') AS comment_count,
          (SELECT cm.creation FROM `tabComment` cm WHERE cm.reference_doctype = d.voucher_type AND cm.reference_name = d.voucher_no
             AND cm.comment_type NOT IN ('Like', 'Label') ORDER BY cm.creation DESC LIMIT 1) AS last_comment_on,
          (SELECT cm.owner FROM `tabComment` cm WHERE cm.reference_doctype = d.voucher_type AND cm.reference_name = d.voucher_no
             AND cm.comment_type NOT IN ('Like', 'Label') ORDER BY cm.creation DESC LIMIT 1) AS last_comment_by,
          (SELECT g2.owner FROM `tabGL Entry` g2 WHERE g2.voucher_type = d.voucher_type AND g2.voucher_no = d.voucher_no
             ORDER BY g2.creation LIMIT 1) AS first_gl_by,
          (SELECT g2.creation FROM `tabGL Entry` g2 WHERE g2.voucher_type = d.voucher_type AND g2.voucher_no = d.voucher_no
             ORDER BY g2.creation LIMIT 1) AS first_gl_on
        FROM (
          SELECT DISTINCT gle.voucher_type, gle.voucher_no
          FROM `tabGL Entry` gle
          WHERE {COMMON}
            AND {PERIOD}
        ) d
      ) s
    ) va ON va.voucher_type = gle.voucher_type AND va.voucher_no = gle.voucher_no"""

docstatus = coalesce("docstatus", "IF(gle.is_cancelled = 1, 2, 1)")
modified = coalesce("modified", "gle.modified")
modified_by = coalesce("modified_by", "gle.modified_by")

tx_inner = f"""
    SELECT
      gle.posting_date, gle.creation AS gl_creation, gle.name AS gl_name, gle.account,
      gle.debit, gle.credit, gle.voucher_type, gle.voucher_subtype, gle.voucher_no, gle.against,
      gle.party_type, gle.party, gle.cost_center, gle.project,
      gle.against_voucher_type, gle.against_voucher, gle.remarks,
      {docstatus} AS docstatus,
      {coalesce("owner", "gle.owner")} AS created_by,
      {coalesce("creation", "gle.creation")} AS created_on,
      {modified_by} AS modified_by,
      {modified} AS modified_on,
      va.submitted_by, va.submitted_on,
      va.cancelled_by_v, va.cancelled_on_v,
      gle.owner AS gl_posted_by, gle.creation AS gl_posted_on,
      IFNULL(va.version_count, 0) AS version_count,
      IFNULL(va.comment_events, 0) AS comment_events,
      IFNULL(va.comment_count, 0) AS comment_count,
      IFNULL(va.draft_edits, 0) AS draft_edits,
      IFNULL(va.post_submit_edits, 0) AS post_submit_edits,
      va.last_version_on, va.last_version_by, va.last_comment_on, va.last_comment_by
    FROM `tabGL Entry` gle
{joins}{voucher_audit}
    WHERE {COMMON}
      AND {PERIOD}"""

last_on = ("GREATEST(IFNULL(x.modified_on, '1900-01-01'), IFNULL(x.last_version_on, '1900-01-01'), "
           "IFNULL(x.last_comment_on, '1900-01-01'))")

tx_values = {
    "seq": "1", "posting_date": "x.posting_date", "gl_creation": "x.gl_creation", "gl_name": "x.gl_name",
    "account": "x.account", "debit": "x.debit", "credit": "x.credit", "voucher_type": "x.voucher_type",
    "voucher_subtype": "x.voucher_subtype", "voucher_no": "x.voucher_no", "against": "x.against",
    "party_type": "x.party_type", "party": "x.party", "cost_center": "x.cost_center", "project": "x.project",
    "against_voucher_type": "x.against_voucher_type", "against_voucher": "x.against_voucher",
    "remarks": "x.remarks",
    "doc_status": "CASE x.docstatus WHEN 0 THEN 'Draft' WHEN 1 THEN 'Submitted' WHEN 2 THEN 'Cancelled' END",
    "created_by": "x.created_by", "created_on": "x.created_on",
    "modified_by": "x.modified_by", "modified_on": "x.modified_on",
    "submitted_by": "IF(x.docstatus IN (1, 2), x.submitted_by, NULL)",
    "submitted_on": "IF(x.docstatus IN (1, 2), x.submitted_on, NULL)",
    "cancelled_by": "IF(x.docstatus = 2, COALESCE(x.cancelled_by_v, x.modified_by), NULL)",
    "cancelled_on": "IF(x.docstatus = 2, COALESCE(x.cancelled_on_v, x.modified_on), NULL)",
    "gl_posted_by": "x.gl_posted_by", "gl_posted_on": "x.gl_posted_on",
    "activity": ("CONCAT_WS(' → ', 'Created', "
                 "IF(x.draft_edits > 0, CONCAT(x.draft_edits, ' draft edit(s)'), NULL), "
                 "IF(x.docstatus IN (1, 2), 'Submitted', NULL), "
                 "IF(x.post_submit_edits > 0, CONCAT(x.post_submit_edits, ' edit(s) after submit'), NULL), "
                 "IF(x.docstatus = 2, 'Cancelled', NULL), "
                 "IF(x.comment_count > 0, CONCAT(x.comment_count, ' comment(s)'), NULL))"),
    "activity_events": "1 + x.version_count + x.comment_events",
    "edits_after_submit": "x.post_submit_edits",
    "last_activity_by": (f"CASE {last_on} WHEN IFNULL(x.last_comment_on, '1900-01-01') THEN x.last_comment_by "
                         f"WHEN IFNULL(x.last_version_on, '1900-01-01') THEN x.last_version_by ELSE x.modified_by END"),
    "last_activity_on": last_on,
}

audit_where = """WHERE (%(created_by)s = '' OR x.created_by = %(created_by)s)
      AND (%(modified_by)s = '' OR x.modified_by = %(modified_by)s)
      AND (%(submitted_by)s = '' OR (x.docstatus IN (1, 2) AND x.submitted_by = %(submitted_by)s))
      AND (%(modified_from)s = '' OR DATE(x.modified_on) >= %(modified_from)s)
      AND (%(modified_to)s = '' OR DATE(x.modified_on) <= %(modified_to)s)
      AND (%(only_edited_after_submit)s <> 1 OR x.post_submit_edits > 0)"""

opening_values = {"seq": "0", "posting_date": "%(from_date)s", "account": "'''Opening'''",
                  "debit": "IFNULL(SUM(gle.debit), 0)", "credit": "IFNULL(SUM(gle.credit), 0)"}

def toggle(flag, expr):
    return f"IF(%({flag})s = 1, {expr}, NULL)"

D = "SUM(IF(t.seq = 1, t.debit, 0)) OVER ()"
C = "SUM(IF(t.seq = 1, t.credit, 0)) OVER ()"
OD = "SUM(IF(t.seq IN (0, 1), t.debit, 0)) OVER ()"
OC = "SUM(IF(t.seq IN (0, 1), t.credit, 0)) OVER ()"
ORDER = "t.seq, t.posting_date, t.gl_creation, t.gl_name"

outer = [
    ("t.posting_date", "Posting Date:Date:100"),
    ("t.account", "Account:Link/Account:200"),
    (f"CASE t.seq WHEN 2 THEN {D} WHEN 3 THEN {OD} ELSE t.debit END", "Debit:Currency:120"),
    (f"CASE t.seq WHEN 2 THEN {C} WHEN 3 THEN {OC} ELSE t.credit END", "Credit:Currency:120"),
    (f"SUM(IF(t.seq IN (0, 1), t.debit - t.credit, 0)) OVER (ORDER BY {ORDER} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)",
     "Balance:Currency:130"),
    ("t.voucher_type", "Voucher Type:Link/DocType:130"),
    ("t.voucher_subtype", "Voucher Subtype:Data:120"),
    ("t.voucher_no", "Voucher No:Dynamic Link/voucher_type:170"),
    ("t.against", "Against Account:Data:150"),
    ("t.party_type", "Party Type:Link/DocType:100"),
    ("t.party", "Party:Dynamic Link/party_type:150"),
    ("t.project", "Project:Link/Project:110"),
    ("t.cost_center", "Cost Center:Link/Cost Center:140"),
    ("t.against_voucher_type", "Against Voucher Type:Link/DocType:130"),
    ("t.against_voucher", "Against Voucher:Dynamic Link/against_voucher_type:160"),
    ("t.remarks", "Remarks:Data:200"),
    (toggle("show_submitted", "t.doc_status"), "Document Status:Data:110"),
    (toggle("show_created_by", "t.created_by"), "Created By:Link/User:160"),
    (toggle("show_created_on", "t.created_on"), "Created On:Datetime:160"),
    (toggle("show_modified_by", "t.modified_by"), "Modified By:Link/User:160"),
    (toggle("show_modified_on", "t.modified_on"), "Modified On:Datetime:160"),
    (toggle("show_submitted", "t.submitted_by"), "Submitted By:Link/User:160"),
    (toggle("show_submitted", "t.submitted_on"), "Submitted On:Datetime:160"),
    (toggle("show_cancelled_info", "t.cancelled_by"), "Cancelled By:Link/User:160"),
    (toggle("show_cancelled_info", "t.cancelled_on"), "Cancelled On:Datetime:160"),
    (toggle("show_gl_audit", "t.gl_posted_by"), "GL Posted By:Link/User:160"),
    (toggle("show_gl_audit", "t.gl_posted_on"), "GL Posted On:Datetime:160"),
    (toggle("show_activity", "t.activity"), "Complete Activity:Data:330"),
    (toggle("show_activity", "t.activity_events"), "Activity Events:Int:110"),
    (toggle("show_activity", "t.edits_after_submit"), "Edits After Submit:Int:130"),
    (toggle("show_activity", "t.last_activity_by"), "Last Activity By:Link/User:160"),
    (toggle("show_activity", "t.last_activity_on"), "Last Activity On:Datetime:160"),
]

select_list = ",\n  ".join(f"{expr} AS `{label}`" for expr, label in outer)

SQL = f"""SELECT
  {select_list}
FROM (
  /* 0: opening balance */
  SELECT {row(opening_values)}
  FROM `tabGL Entry` gle
  WHERE {COMMON}
    AND {OPENING}

  UNION ALL

  /* 1: period transactions with audit trail */
  SELECT {row(tx_values)}
  FROM ({tx_inner}
  ) x
  {audit_where}

  UNION ALL
  /* 2: period total, 3: closing (values computed by window functions above) */
  SELECT {row({"seq": "2", "account": "'''Total'''"})}
  UNION ALL
  SELECT {row({"seq": "3", "account": "'''Closing (Opening + Total)'''"})}
) t
ORDER BY {ORDER}
"""

if __name__ == "__main__":
    print(SQL)
