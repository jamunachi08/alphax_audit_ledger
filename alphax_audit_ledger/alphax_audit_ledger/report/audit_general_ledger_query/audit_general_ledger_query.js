// Copyright (c) 2026, Neotec Integrated Solutions and contributors
// AlphaX Audit General Ledger (Query Report)
//
// Filters + UI for the SQL in audit_general_ledger_query.sql.
// Works both as a standard app report and pasted into the "Javascript" field of a
// Report created from the desk (Report Type = Query Report, Ref DocType = GL Entry).

(function () {
	const REPORT = "Audit General Ledger Query";
	const STORAGE_KEY = "alphax_aglq:" + (frappe.session && frappe.session.user) + ":hidden";

	// Audit column toggles -> column fieldnames (frappe.scrub of the SQL column labels)
	const TOGGLES = {
		show_created_by: ["created_by"],
		show_created_on: ["created_on"],
		show_modified_by: ["modified_by"],
		show_modified_on: ["modified_on"],
		show_submitted: ["document_status", "submitted_by", "submitted_on"],
		show_cancelled_info: ["cancelled_by", "cancelled_on"],
		show_gl_audit: ["gl_posted_by", "gl_posted_on"],
		show_activity: ["complete_activity", "activity_events", "edits_after_submit", "last_activity_by", "last_activity_on"],
	};

	const company = () => frappe.query_report.get_filter_value("company");

	// ------------------------------------------------------------------ filters
	const FILTERS = [
		// ---- ledger filters (same meaning as the standard General Ledger)
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"), reqd: 1 },
		{ fieldname: "finance_book", label: __("Finance Book"), fieldtype: "Link", options: "Finance Book" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1,
			default: frappe.datetime.get_today() },
		{ fieldname: "account", label: __("Account"), fieldtype: "Link", options: "Account",
			get_query: () => ({ filters: { company: company() } }) },
		{ fieldname: "voucher_type", label: __("Voucher Type"), fieldtype: "Link", options: "DocType",
			get_query: () => ({ filters: { is_submittable: 1 } }) },
		{ fieldname: "voucher_no", label: __("Voucher No"), fieldtype: "Data" },
		{ fieldname: "party_type", label: __("Party Type"), fieldtype: "Link", options: "Party Type",
			on_change: () => {
				frappe.query_report.set_filter_value("party", "");
			} },
		{ fieldname: "party", label: __("Party"), fieldtype: "Dynamic Link",
			get_options: () => {
				const pt = frappe.query_report.get_filter_value("party_type");
				if (!pt) frappe.throw(__("Please select Party Type first"));
				return pt;
			} },
		{ fieldname: "cost_center", label: __("Cost Center"), fieldtype: "Link", options: "Cost Center",
			get_query: () => ({ filters: { company: company() } }) },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project",
			get_query: () => ({ filters: { company: company() } }) },
		{ fieldname: "show_cancelled_entries", label: __("Show Cancelled Entries"), fieldtype: "Check", default: 0 },

		// ---- audit row filters
		{ fieldname: "created_by", label: __("Created By"), fieldtype: "Link", options: "User" },
		{ fieldname: "modified_by", label: __("Modified By"), fieldtype: "Link", options: "User" },
		{ fieldname: "submitted_by", label: __("Submitted By"), fieldtype: "Link", options: "User" },
		{ fieldname: "modified_from", label: __("Modified From"), fieldtype: "Date" },
		{ fieldname: "modified_to", label: __("Modified To"), fieldtype: "Date" },
		{ fieldname: "only_edited_after_submit", label: __("Only Vouchers Edited After Submit"), fieldtype: "Check", default: 0 },

		// ---- audit column enable / disable
		{ fieldname: "show_created_by", label: __("Show Created By"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_created_on", label: __("Show Created On"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_modified_by", label: __("Show Modified By"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_modified_on", label: __("Show Modified On"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_submitted", label: __("Show Submitted By / On"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_cancelled_info", label: __("Show Cancelled By / On"), fieldtype: "Check", default: 0 },
		{ fieldname: "show_gl_audit", label: __("Show GL Posted By / On"), fieldtype: "Check", default: 0 },
		{ fieldname: "show_activity", label: __("Show Complete Activity"), fieldtype: "Check", default: 1 },
	];

	// ------------------------------------------------------------------ helpers
	function read_hidden() {
		try {
			return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
		} catch (e) {
			return [];
		}
	}

	function write_hidden(list) {
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
		} catch (e) {
			/* storage blocked: applies for this session only */
		}
	}

	// Query reports pass filters straight into the SQL, so every %(key)s must exist.
	// The desk drops empty/unchecked filters; fill them with "" / 0.
	function patch_filter_values(report) {
		if (report.__axq_patched) return;
		report.__axq_patched = true;
		const original = report.get_filter_values.bind(report);
		report.get_filter_values = function (raise) {
			const values = original(raise) || {};
			(report.filters || []).forEach((f) => {
				const fn = f.df && f.df.fieldname;
				if (fn && (values[fn] === undefined || values[fn] === null)) {
					values[fn] = f.df.fieldtype === "Check" ? 0 : "";
				}
			});
			return values;
		};
	}

	function hidden_fieldnames(report) {
		const hidden = new Set(read_hidden());
		Object.entries(TOGGLES).forEach(([flag, cols]) => {
			if (!cint(report.get_filter_value(flag))) cols.forEach((c) => hidden.add(c));
		});
		return hidden;
	}

	// Hide toggled-off / user-hidden columns before the datatable renders.
	// Print and PDF follow the visible columns.
	function patch_render(report) {
		if (report.__axq_render_patched) return;
		report.__axq_render_patched = true;
		const original = report.render_datatable.bind(report);
		report.render_datatable = function () {
			const hidden = hidden_fieldnames(report);
			(report.columns || []).forEach((col) => {
				col.hidden = hidden.has(col.fieldname) ? 1 : 0;
			});
			return original();
		};
	}

	function open_column_manager(report) {
		const cols = (report.columns || []).filter((c) => c.fieldname);
		if (!cols.length) {
			frappe.msgprint(__("Run the report once, then manage its columns."));
			return;
		}
		const user_hidden = read_hidden();
		const d = new frappe.ui.Dialog({
			title: __("Show / Hide Columns"),
			size: "large",
			fields: [
				{ fieldname: "info", fieldtype: "HTML",
					options: `<p class="text-muted small">${__("Audit columns can also be switched with the 'Show …' checkboxes in the filters. Your choice here is remembered on this browser.")}</p>` },
				{ fieldname: "cols", fieldtype: "MultiCheck", label: __("Columns"), columns: 3, select_all: true,
					options: cols.map((c) => ({ label: c.label, value: c.fieldname, checked: !user_hidden.includes(c.fieldname) })) },
			],
			primary_action_label: __("Apply"),
			primary_action(values) {
				const shown = values.cols || [];
				write_hidden(cols.map((c) => c.fieldname).filter((fn) => !shown.includes(fn)));
				report.render_datatable();
				d.hide();
			},
			secondary_action_label: __("Show All"),
			secondary_action() {
				write_hidden([]);
				report.render_datatable();
				d.hide();
			},
		});
		d.show();
	}

	function export_excel(report) {
		if (typeof report.export_report === "function") return report.export_report();
		frappe.msgprint(__("Use Menu → Export"));
	}

	function print_or_pdf(report, as_pdf) {
		const fn = as_pdf ? report.pdf_report : report.print_report;
		if (typeof fn !== "function" || !frappe.ui.get_print_settings) {
			frappe.msgprint(__("Use Menu → {0}", [as_pdf ? __("PDF") : __("Print")]));
			return;
		}
		frappe.ui.get_print_settings(
			false,
			(settings) => fn.call(report, settings),
			report.report_doc ? report.report_doc.letter_head : null,
			typeof report.get_visible_columns === "function" ? report.get_visible_columns() : undefined
		);
	}

	// ------------------------------------------------------------------ activity viewer
	const KIND_COLOR = {
		created: "blue", edited: "orange", submitted: "green", cancelled: "red", comment: "gray",
		assigned: "yellow", attachment: "gray", info: "gray", workflow: "purple", shared: "gray",
		email: "purple", view: "gray",
	};

	function strip(html) {
		return $("<div>").html(html || "").text().trim();
	}

	function short(v) {
		if (v === null || v === undefined || v === "") return "∅";
		const s = String(v);
		return s.length > 120 ? s.slice(0, 117) + "…" : s;
	}

	function describe_version(doctype, raw) {
		let data = {};
		try {
			data = typeof raw === "string" ? JSON.parse(raw) : raw || {};
		} catch (e) {
			data = {};
		}
		const label = (fn, dt) => frappe.meta.get_label(dt || doctype, fn) || fn;
		const lines = [];
		let kind = "edited";
		let title = __("Edited");

		(data.changed || []).forEach((c) => {
			if (c[0] === "docstatus") {
				if (cint(c[2]) === 1) [kind, title] = ["submitted", __("Submitted")];
				if (cint(c[2]) === 2) [kind, title] = ["cancelled", __("Cancelled")];
				return;
			}
			lines.push(`${label(c[0])}: ${short(c[1])} → ${short(c[2])}`);
		});
		(data.added || []).forEach((a) => lines.push(__("Row added to {0}", [label(a[0])])));
		(data.removed || []).forEach((a) => lines.push(__("Row removed from {0}", [label(a[0])])));
		(data.row_changed || []).forEach((rc) => {
			const table_df = frappe.meta.get_docfield(doctype, rc[0]);
			const child_dt = table_df && table_df.options;
			(rc[3] || []).forEach((c) => {
				lines.push(`${label(rc[0])} #${cint(rc[1]) + 1} · ${label(c[0], child_dt)}: ${short(c[1])} → ${short(c[2])}`);
			});
		});
		return { kind, title, lines };
	}

	function build_events(doctype, header, info) {
		const events = [];
		const add = (time, user, kind, title, details) =>
			time && events.push({ time, user, kind, title, details: details || [] });

		add(header.creation, header.owner, "created", __("Created"));

		(info.versions || []).forEach((v) => {
			const d = describe_version(doctype, v.data);
			add(v.creation, v.owner, d.kind, d.title, d.lines);
		});
		(info.comments || []).forEach((c) => add(c.creation, c.owner, "comment", __("Comment"), [strip(c.content)]));
		(info.assignment_logs || []).forEach((c) => add(c.creation, c.owner, "assigned", __(c.comment_type), [strip(c.content)]));
		(info.attachment_logs || []).forEach((c) => add(c.creation, c.owner, "attachment", __(c.comment_type), [strip(c.content)]));
		(info.info_logs || []).forEach((c) => add(c.creation, c.owner, "info", __(c.comment_type), [strip(c.content)]));
		(info.workflow_logs || []).forEach((c) => add(c.creation, c.owner, "workflow", __("Workflow"), [strip(c.content)]));
		(info.shared || []).forEach((c) => add(c.creation, c.owner, "shared", __(c.comment_type || "Shared"), [strip(c.content)]));
		(info.communications || []).forEach((m) =>
			add(m.creation, m.sender || m.owner, "email", __(m.communication_medium || "Communication"), [m.subject || ""]));
		(info.views || []).forEach((v) => add(v.creation, v.owner, "view", __("Viewed")));

		events.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
		return events;
	}

	function render(doctype, header, info, events) {
		const esc = frappe.utils.escape_html;
		const user = (u) => esc(frappe.user.full_name(u) || u || "");
		const when = (t) => (t ? esc(frappe.datetime.str_to_user(t)) : "");
		const status = { 0: __("Draft"), 1: __("Submitted"), 2: __("Cancelled") }[cint(header.docstatus)];
		const more = (info.versions || []).length >= 10
			? `<div class="text-muted small" style="margin-bottom:8px">${__("Showing the latest 10 field-change versions. Open the document for the full timeline.")}</div>`
			: "";

		const rows = events.map((e) => `
			<tr>
				<td class="text-nowrap">${when(e.time)}</td>
				<td class="text-nowrap">${user(e.user)}</td>
				<td class="text-nowrap"><span class="indicator-pill ${KIND_COLOR[e.kind] || "gray"}">${esc(e.title || "")}</span></td>
				<td>${e.details.filter(Boolean).map((l) => `<div>${esc(l)}</div>`).join("")}</td>
			</tr>`).join("");

		return `
			<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:12px">
				<div class="frappe-card" style="padding:10px"><div class="text-muted small">${__("Created")}</div><b>${user(header.owner)}</b><div class="small">${when(header.creation)}</div></div>
				<div class="frappe-card" style="padding:10px"><div class="text-muted small">${__("Last Modified")}</div><b>${user(header.modified_by)}</b><div class="small">${when(header.modified)}</div></div>
				<div class="frappe-card" style="padding:10px"><div class="text-muted small">${__("Status")}</div><b>${esc(status || "")}</b></div>
			</div>
			${more}
			<div style="max-height:55vh;overflow:auto">
				<table class="table table-bordered table-sm" style="font-size:12px;margin:0">
					<thead><tr><th>${__("When")}</th><th>${__("User")}</th><th>${__("Event")}</th><th>${__("Details")}</th></tr></thead>
					<tbody>${rows || `<tr><td colspan="4" class="text-muted">${__("No activity recorded")}</td></tr>`}</tbody>
				</table>
			</div>`;
	}

	async function show_activity(doctype, name) {
		await frappe.model.with_doctype(doctype);
		const header = (await frappe.db.get_value(doctype, name,
			["owner", "creation", "modified_by", "modified", "docstatus"])).message || {};
		const r = await frappe.call({ method: "frappe.desk.form.load.get_docinfo", args: { doctype, name } });
		const info = (r && r.docinfo) || {};
		const events = build_events(doctype, header, info);

		const d = new frappe.ui.Dialog({
			title: __("Activity: {0} {1}", [__(doctype), name]),
			size: "extra-large",
			fields: [{ fieldname: "body", fieldtype: "HTML" }],
			primary_action_label: __("Open Document"),
			primary_action() {
				d.hide();
				frappe.set_route("Form", doctype, name);
			},
			secondary_action_label: __("Download CSV"),
			secondary_action() {
				const csv = [[__("When"), __("User"), __("Event"), __("Details")]].concat(
					events.map((e) => [e.time, frappe.user.full_name(e.user) || e.user, e.title, e.details.join(" | ")])
				);
				frappe.tools.downloadify(csv, null, `${name}-activity`);
			},
		});
		d.fields_dict.body.$wrapper.html(render(doctype, header, info, events));
		d.show();
	}

	// ------------------------------------------------------------------ report definition
	frappe.query_reports[REPORT] = {
		filters: FILTERS,

		formatter(value, row, column, data, default_formatter) {
			let out = default_formatter(value, row, column, data);
			if (!column || !data) return out;

			// Opening / Total / Closing rows in bold, like the standard ledger
			if (typeof data.account === "string" && data.account.startsWith("'")) return `<b>${out}</b>`;

			if (column.fieldname === "complete_activity" && value && data.voucher_no) {
				return `<a class="axq-activity" data-vt="${encodeURIComponent(data.voucher_type || "")}"`
					+ ` data-vn="${encodeURIComponent(data.voucher_no)}" title="${__("View complete activity")}">`
					+ `${frappe.utils.escape_html(String(value))}</a>`;
			}
			if (column.fieldname === "edits_after_submit" && cint(value) > 0) {
				return `<span style="color:var(--red-600);font-weight:600">${out}</span>`;
			}
			if (column.fieldname === "document_status" && value) {
				const color = { Submitted: "var(--green-600)", Cancelled: "var(--red-600)" }[value];
				return color ? `<span style="color:${color};font-weight:600">${__(value)}</span>` : out;
			}
			return out;
		},

		onload(report) {
			patch_filter_values(report);
			patch_render(report);

			report.page.add_inner_button(__("Show / Hide Columns"), () => open_column_manager(report), __("Audit"));
			report.page.add_inner_button(__("Excel"), () => export_excel(report), __("Export"));
			report.page.add_inner_button(__("PDF"), () => print_or_pdf(report, true), __("Export"));
			report.page.add_inner_button(__("Print"), () => print_or_pdf(report, false), __("Export"));

			$(report.page.wrapper)
				.off("click.axq")
				.on("click.axq", ".axq-activity", function (e) {
					e.preventDefault();
					e.stopPropagation();
					show_activity(
						decodeURIComponent($(this).attr("data-vt") || ""),
						decodeURIComponent($(this).attr("data-vn") || "")
					);
				});
		},
	};
})();
