// Copyright (c) 2026, Neotec Integrated Solutions and contributors
// For license information, please see license.txt
//
// AlphaX Audit General Ledger
// Inherits the installed ERPNext "General Ledger" filters/formatter at runtime (so it always
// matches your v15 patch level) and adds audit toggles, user filters, extra columns,
// a persistent column manager, quick Excel/PDF/Print buttons and a full activity viewer.

(function () {
	const REPORT = "Audit General Ledger";
	const STORAGE_KEY = "alphax_audit_ledger:" + (frappe.session && frappe.session.user) + ":columns";
	const known_labels = {};

	// ------------------------------------------------------------------ base GL definition
	function load_gl_definition() {
		if (frappe.query_reports["General Ledger"]) return frappe.query_reports["General Ledger"];
		try {
			$.ajax({
				url: "/api/method/frappe.desk.query_report.get_script",
				type: "GET",
				data: { report_name: "General Ledger" },
				dataType: "json",
				async: false,
				headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
				success(r) {
					const script = r && r.message && r.message.script;
					if (script) frappe.dom.eval(script);
				},
			});
		} catch (e) {
			console.warn("AlphaX Audit Ledger: could not load General Ledger definition", e);
		}
		return frappe.query_reports["General Ledger"] || null;
	}

	function fallback_filters() {
		const company_filter = () => ({ company: frappe.query_report.get_filter_value("company") });
		return [
			{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
				default: frappe.defaults.get_user_default("Company"), reqd: 1 },
			{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
				default: frappe.datetime.add_months(frappe.datetime.get_today(), -1), reqd: 1 },
			{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date",
				default: frappe.datetime.get_today(), reqd: 1 },
			{ fieldname: "account", label: __("Account"), fieldtype: "MultiSelectList", options: "Account",
				get_data: (txt) => frappe.db.get_link_options("Account", txt, company_filter()) },
			{ fieldname: "voucher_no", label: __("Voucher No"), fieldtype: "Data" },
			{ fieldname: "party_type", label: __("Party Type"), fieldtype: "Link", options: "Party Type" },
			{ fieldname: "party", label: __("Party"), fieldtype: "MultiSelectList",
				get_data: (txt) => {
					const pt = frappe.query_report.get_filter_value("party_type");
					return pt ? frappe.db.get_link_options(pt, txt) : [];
				} },
			{ fieldname: "cost_center", label: __("Cost Center"), fieldtype: "MultiSelectList", options: "Cost Center",
				get_data: (txt) => frappe.db.get_link_options("Cost Center", txt, company_filter()) },
			{ fieldname: "project", label: __("Project"), fieldtype: "MultiSelectList", options: "Project",
				get_data: (txt) => frappe.db.get_link_options("Project", txt, company_filter()) },
			{ fieldname: "include_dimensions", label: __("Consider Accounting Dimensions"), fieldtype: "Check", default: 1 },
			{ fieldname: "include_default_book_entries", label: __("Include Default FB Entries"), fieldtype: "Check", default: 1 },
			{ fieldname: "show_cancelled_entries", label: __("Show Cancelled Entries"), fieldtype: "Check" },
		];
	}

	// ------------------------------------------------------------------ audit filters
	const user_picker = (txt) => frappe.xcall("alphax_audit_ledger.api.get_users", { txt });

	const AUDIT_FILTERS = [
		{ fieldname: "audit_ui", label: "Audit UI", fieldtype: "Data", hidden: 1, default: "1" },
		{ fieldname: "hidden_columns", label: __("Hidden Columns"), fieldtype: "Data", hidden: 1 },

		{ fieldname: "show_created_by", label: __("Show Created By"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_created_on", label: __("Show Created On"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_modified_by", label: __("Show Modified By"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_modified_on", label: __("Show Modified On"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_submitted", label: __("Show Submitted By / On"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_cancelled", label: __("Show Cancelled By / On"), fieldtype: "Check", default: 0 },
		{ fieldname: "show_gl_audit", label: __("Show GL Entry Audit Stamps"), fieldtype: "Check", default: 0 },
		{ fieldname: "show_activity", label: __("Show Complete Activity"), fieldtype: "Check", default: 1 },
		{ fieldname: "only_edited_after_submit", label: __("Only Vouchers Edited After Submit"), fieldtype: "Check", default: 0 },

		{ fieldname: "audit_created_by", label: __("Created By (User)"), fieldtype: "MultiSelectList", get_data: user_picker },
		{ fieldname: "audit_modified_by", label: __("Modified By (User)"), fieldtype: "MultiSelectList", get_data: user_picker },
		{ fieldname: "audit_submitted_by", label: __("Submitted By (User)"), fieldtype: "MultiSelectList", get_data: user_picker },
		{ fieldname: "audit_modified_from", label: __("Modified From"), fieldtype: "Date" },
		{ fieldname: "audit_modified_to", label: __("Modified To"), fieldtype: "Date" },

		{ fieldname: "extra_gl_fields", label: __("Add GL Entry Columns"), fieldtype: "MultiSelectList",
			get_data: (txt) => frappe.xcall("alphax_audit_ledger.api.get_field_options", { scope: "gl", txt }) },
		{ fieldname: "extra_voucher_fields", label: __("Add Voucher Columns"), fieldtype: "MultiSelectList",
			get_data: (txt) => frappe.xcall("alphax_audit_ledger.api.get_field_options", { scope: "voucher", txt }) },
	];

	// ------------------------------------------------------------------ column manager
	function read_saved() {
		try {
			return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
		} catch (e) {
			return null;
		}
	}

	function write_saved(hidden) {
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify({ hidden, labels: known_labels }));
		} catch (e) {
			/* storage unavailable: setting still applies for this session */
		}
	}

	function current_hidden(report) {
		return String(report.get_filter_value("hidden_columns") || "")
			.split(",").map((s) => s.trim()).filter(Boolean);
	}

	function remember_columns(report) {
		(report.columns || []).forEach((c) => {
			if (c && c.fieldname) known_labels[c.fieldname] = c.label || c.fieldname;
		});
	}

	function open_column_manager(report) {
		remember_columns(report);
		const hidden = current_hidden(report);
		const all = Object.keys(known_labels);
		if (!all.length) {
			frappe.msgprint(__("Run the report once, then manage its columns."));
			return;
		}
		const d = new frappe.ui.Dialog({
			title: __("Show / Hide Columns"),
			size: "large",
			fields: [
				{ fieldname: "info", fieldtype: "HTML",
					options: `<p class="text-muted small">${__("Hidden columns are also removed from Excel, PDF and Print output. Your choice is remembered on this browser.")}</p>` },
				{ fieldname: "cols", fieldtype: "MultiCheck", label: __("Columns"), columns: 3, select_all: true,
					options: all.map((fn) => ({ label: known_labels[fn], value: fn, checked: !hidden.includes(fn) })) },
			],
			primary_action_label: __("Apply"),
			primary_action(values) {
				const shown = values.cols || [];
				const new_hidden = all.filter((fn) => !shown.includes(fn));
				write_saved(new_hidden);
				report.set_filter_value("hidden_columns", new_hidden.join(","));
				d.hide();
			},
			secondary_action_label: __("Show All"),
			secondary_action() {
				write_saved([]);
				report.set_filter_value("hidden_columns", "");
				d.hide();
			},
		});
		d.show();
	}

	// ------------------------------------------------------------------ export helpers
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
		created: "blue", edited: "orange", post_submit: "red", submitted: "green", cancelled: "red",
		posted: "green", amended: "blue", comment: "gray", info: "gray", assigned: "yellow",
		attachment: "gray", shared: "gray", workflow: "purple", email: "purple", access: "gray", view: "gray",
	};

	function render_activity(r) {
		const esc = frappe.utils.escape_html;
		const uname = (u) => esc((r.users && r.users[u]) || u || "");
		const when = (t) => (t ? esc(frappe.datetime.str_to_user(t)) : "");
		const h = r.header || {};

		const card = (title, user, time, extra) => `
			<div class="ax-card">
				<div class="ax-card-t">${esc(title)}</div>
				<div class="ax-card-u">${user ? uname(user) : "—"}</div>
				<div class="text-muted small">${when(time)}${extra ? " · " + esc(extra) : ""}</div>
			</div>`;

		const cards = [
			card(__("Created"), h.created_by, h.created_on),
			card(__("Last Modified"), h.modified_by, h.modified_on),
			card(__("Submitted"), h.submitted_by, h.submitted_on),
			card(__("Cancelled"), h.cancelled_by, h.cancelled_on),
		].join("");

		const meta = [
			`${__("Status")}: <b>${esc(h.status || "")}</b>`,
			`${__("Edits After Submit")}: <b>${esc(String(h.edits_after_submit || 0))}</b>`,
			`${__("GL Rows")}: <b>${esc(String((r.gl && r.gl.total) || 0))}</b>`,
			h.amended_from ? `${__("Amended From")}: <b>${esc(h.amended_from)}</b>` : "",
			(h.amendments || []).length ? `${__("Amendments")}: <b>${esc(h.amendments.join(", "))}</b>` : "",
		].filter(Boolean).join(" &nbsp;|&nbsp; ");

		const rows = (r.events || []).map((e) => `
			<tr>
				<td class="text-nowrap">${when(e.time)}</td>
				<td class="text-nowrap">${uname(e.user)}</td>
				<td class="text-nowrap"><span class="indicator-pill ${KIND_COLOR[e.kind] || "gray"}">${esc(e.title || "")}</span></td>
				<td>${(e.details || []).map((l) => `<div>${esc(l)}</div>`).join("")}</td>
			</tr>`).join("");

		return `
			<style>
				.ax-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-bottom: 12px; }
				.ax-card { border: 1px solid var(--border-color); border-radius: 8px; padding: 10px 12px; background: var(--card-bg); }
				.ax-card-t { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); }
				.ax-card-u { font-weight: 600; margin: 2px 0; }
				.ax-meta { margin-bottom: 10px; font-size: 12px; }
				.ax-tl { max-height: 55vh; overflow: auto; }
				.ax-tl table { font-size: 12px; margin: 0; }
				.ax-tl th { position: sticky; top: 0; background: var(--subtle-fg); z-index: 1; }
			</style>
			<div class="ax-cards">${cards}</div>
			<div class="ax-meta">${meta}</div>
			<div class="ax-tl">
				<table class="table table-bordered table-sm">
					<thead><tr><th>${__("When")}</th><th>${__("User")}</th><th>${__("Event")}</th><th>${__("Details")}</th></tr></thead>
					<tbody>${rows || `<tr><td colspan="4" class="text-muted">${__("No activity recorded")}</td></tr>`}</tbody>
				</table>
			</div>`;
	}

	function show_activity(voucher_type, voucher_no) {
		frappe.xcall("alphax_audit_ledger.api.get_voucher_activity", { voucher_type, voucher_no }).then((r) => {
			const d = new frappe.ui.Dialog({
				title: __("Activity: {0} {1}", [__(voucher_type), voucher_no]),
				size: "extra-large",
				fields: [{ fieldname: "body", fieldtype: "HTML" }],
				primary_action_label: __("Open Document"),
				primary_action() {
					d.hide();
					frappe.set_route("Form", voucher_type, voucher_no);
				},
				secondary_action_label: __("Download CSV"),
				secondary_action() {
					const name = (u) => (r.users && r.users[u]) || u || "";
					const csv = [[__("When"), __("User"), __("Event"), __("Details")]].concat(
						(r.events || []).map((e) => [e.time, name(e.user), e.title, (e.details || []).join(" | ")])
					);
					frappe.tools.downloadify(csv, null, `${voucher_no}-activity`);
				},
			});
			d.fields_dict.body.$wrapper.html(render_activity(r));
			d.show();
		});
	}

	// ------------------------------------------------------------------ assemble report
	const base = load_gl_definition() || {};
	const base_filters = (base.filters && base.filters.length ? base.filters : fallback_filters())
		.map((f) => Object.assign({}, f));

	function formatter(value, row, column, data, default_formatter) {
		let out = base.formatter
			? base.formatter(value, row, column, data, default_formatter)
			: default_formatter(value, row, column, data);

		if (!column || !data) return out;

		if (column.fieldname === "v_activity_summary" && data.voucher_no && value) {
			const vt = encodeURIComponent(data.voucher_type || "");
			const vn = encodeURIComponent(data.voucher_no || "");
			return `<a class="ax-audit-activity" data-vt="${vt}" data-vn="${vn}" title="${__("View complete activity")}">`
				+ `${frappe.utils.escape_html(String(value))}</a>`;
		}
		if (column.fieldname === "v_edits_after_submit" && cint(value) > 0) {
			return `<span style="color: var(--red-600); font-weight: 600;">${out}</span>`;
		}
		if (column.fieldname === "v_doc_status" && value) {
			const color = { [__("Submitted")]: "var(--green-600)", [__("Cancelled")]: "var(--red-600)" }[value];
			return color ? `<span style="color: ${color}; font-weight: 600;">${out}</span>` : out;
		}
		return out;
	}

	frappe.query_reports[REPORT] = Object.assign({}, base, {
		filters: base_filters.concat(AUDIT_FILTERS),
		formatter,

		onload(report) {
			if (typeof base.onload === "function") base.onload(report);

			const saved = read_saved();
			if (saved) {
				Object.assign(known_labels, saved.labels || {});
				if ((saved.hidden || []).length) report.set_filter_value("hidden_columns", saved.hidden.join(","));
			}

			report.page.add_inner_button(__("Show / Hide Columns"), () => open_column_manager(report), __("Audit"));
			report.page.add_inner_button(__("Excel"), () => export_excel(report), __("Export"));
			report.page.add_inner_button(__("PDF"), () => print_or_pdf(report, true), __("Export"));
			report.page.add_inner_button(__("Print"), () => print_or_pdf(report, false), __("Export"));

			$(report.page.wrapper)
				.off("click.axaudit")
				.on("click.axaudit", ".ax-audit-activity", function (e) {
					e.preventDefault();
					e.stopPropagation();
					show_activity(
						decodeURIComponent($(this).attr("data-vt") || ""),
						decodeURIComponent($(this).attr("data-vn") || "")
					);
				});
		},

		after_datatable_render(datatable) {
			if (typeof base.after_datatable_render === "function") base.after_datatable_render(datatable);
			remember_columns(frappe.query_report);
		},
	});

	if (window.erpnext && erpnext.utils && typeof erpnext.utils.add_dimensions === "function") {
		erpnext.utils.add_dimensions(REPORT, 15);
	}
})();
