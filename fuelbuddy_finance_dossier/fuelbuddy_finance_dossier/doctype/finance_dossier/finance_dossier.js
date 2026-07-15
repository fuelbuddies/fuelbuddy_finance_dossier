// Copyright (c) 2026, Fuelbuddy and contributors
// For license information, please see license.txt

// Ported from Client Scripts (code-first, no DB Client Scripts):
//   - "Finance Dossier"                          -> finance_dossier_from query
//   - "Add Discount On Finance Dossier"          -> discount fetch + field toggling
//   - "Fetch Discount Reference On Finance Dossier" -> discount reference sync to linked doc

// "Finance Dossier": restrict the source link to Opportunity / Quotation.
frappe.ui.form.on("Finance Dossier", {
	onload: function (frm) {
		frm.set_query("finance_dossier_from", function () {
			return {
				filters: [["name", "in", ["Opportunity", "Quotation"]]],
			};
		});
	},
});

// Make sure the Business Documents panel (with the Approve / Reject actions) gets
// painted on first open.
//
// NOTE: the "write this dossier's name back onto the source doc" after_save handler
// moved server-side (fuelbuddy_crm.finance_dossier.sync_source_reference) so it also
// covers dossiers created/amended outside the browser. The dead "Add Discount On
// Finance Dossier" / toggle blocks (custom_-prefixed fields that don't exist on this
// doctype) were removed with it.
//
// NOTE: the dossier's `discount` is set server-side when the FD is created (and kept
// in sync from the Opportunity). The old `set_discount_from_linked_doc` re-read a
// `discount` field off the source Quotation/Opportunity -- which have no such field --
// so on every refresh it ran `frm.set_value("discount", "")`, clearing the link and
// marking the freshly-opened form *dirty* (and wiping the discount on save). Removed.
frappe.ui.form.on("Finance Dossier", {
	refresh: function (frm) {
		// The Business Documents panel is painted by a DB Client Script on `refresh`.
		// On the first Finance Dossier opened in a session that script can finish
		// loading *after* this refresh fires, so the panel -- and its Approve/Reject
		// buttons -- only appears after a manual reload. This controller JS is bundled
		// with the app and always loaded before refresh, so paint it from here too
		// (idempotent), retrying until the shared bizdocs helper is available.
		if (!frm.is_new()) {
			ensure_bizdocs_panel(frm, 0);
		}
	},
});

function ensure_bizdocs_panel(frm, tries) {
	if (frappe.bizdocs && frappe.bizdocs.render) {
		frappe.bizdocs.render(frm);
	} else if (tries < 20) {
		setTimeout(() => ensure_bizdocs_panel(frm, tries + 1), 150);
	}
}
