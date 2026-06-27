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

// "Add Discount On Finance Dossier": pull the linked Discount's details into the
// dossier and show/hide the discount fields based on the chosen method.
frappe.ui.form.on("Finance Dossier", {
	onload: function (frm) {
		frm.set_query("custom_discount", function () {
			return {
				filters: {
					party: frm.doc.id,
					docstatus: 1,
				},
			};
		});

		toggle_discount_fields(frm);

		if (frm.doc.custom_discount) {
			fetch_discount_details(frm);
		}
	},

	custom_discount: function (frm) {
		if (frm.doc.custom_discount) {
			fetch_discount_details(frm);
		} else {
			frm.clear_table("custom_slab_discount");
			frm.refresh_field("custom_slab_discount");
		}
	},

	custom_discount_method: function (frm) {
		toggle_discount_fields(frm);
	},

	custom_percentageper_litre: function (frm) {
		toggle_discount_fields(frm);
	},
});

function fetch_discount_details(frm) {
	frappe.call({
		method: "frappe.client.get",
		args: {
			doctype: "Discount",
			name: frm.doc.custom_discount,
		},
		callback: function (r) {
			if (r.message) {
				let discount_doc = r.message;

				frm.silent = true;

				frm.set_value("custom_discount_method", discount_doc.discount_type);
				frm.set_value("custom_percentageper_litre", discount_doc.p_or_v);
				frm.set_value("custom_percentage_value", discount_doc.percentage_value);
				frm.set_value("custom_per_litre_value", discount_doc.per_litre_value);
				frm.set_value("custom_max_discount_value", discount_doc.threshold_value);

				frm.clear_table("custom_slab_discount");
				if (discount_doc.discount_type === "Slab Discount" && discount_doc.slab_discount) {
					discount_doc.slab_discount.forEach(function (slab) {
						let child = frm.add_child("custom_slab_discount");
						child.p_or_v = slab.p_or_v;
						child.qty_limit = slab.qty_limit;
						child.discount_value = slab.discount_value;
						child.threshold_value = slab.threshold_value;
						child.limit = slab.limit;
					});
				}
				frm.refresh_field("custom_slab_discount");

				toggle_discount_fields(frm);

				frm.silent = false;
			}
		},
	});
}

function toggle_discount_fields(frm) {
	if (frm.doc.custom_discount_method === "Slab Discount") {
		frm.set_df_property("custom_percentageper_litre", "hidden", 1);
		frm.set_df_property("custom_percentage_value", "hidden", 1);
		frm.set_df_property("custom_per_litre_value", "hidden", 1);
		frm.set_df_property("custom_max_discount_value", "hidden", 1);
		frm.set_df_property("custom_slab_discount", "hidden", 0);
	} else if (frm.doc.custom_discount_method === "Non-Slab Discount") {
		frm.set_df_property("custom_percentageper_litre", "hidden", 0);
		if (frm.doc.custom_percentageper_litre === "Percentage") {
			frm.set_df_property("custom_percentage_value", "hidden", 0);
			frm.set_df_property("custom_per_litre_value", "hidden", 1);
			frm.set_df_property("custom_slab_discount", "hidden", 1);
		} else if (frm.doc.custom_percentageper_litre === "Per Litre") {
			frm.set_df_property("custom_percentage_value", "hidden", 1);
			frm.set_df_property("custom_per_litre_value", "hidden", 0);
			frm.set_df_property("custom_slab_discount", "hidden", 1);
		} else {
			frm.set_df_property("custom_percentage_value", "hidden", 1);
			frm.set_df_property("custom_per_litre_value", "hidden", 1);
			frm.set_df_property("custom_slab_discount", "hidden", 1);
		}
	} else {
		frm.set_df_property("custom_percentageper_litre", "hidden", 0);
		frm.set_df_property("custom_percentage_value", "hidden", 0);
		frm.set_df_property("custom_per_litre_value", "hidden", 0);
		frm.set_df_property("custom_max_discount_value", "hidden", 0);
		frm.set_df_property("custom_slab_discount", "hidden", 0);
	}
}

// Write this dossier's name back onto the source doc, and make sure the Business
// Documents panel (with the Approve / Reject actions) gets painted on first open.
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

	after_save: function (frm) {
		update_reference_on_linked_doc(frm);
	},
});

function ensure_bizdocs_panel(frm, tries) {
	if (frappe.bizdocs && frappe.bizdocs.render) {
		frappe.bizdocs.render(frm);
	} else if (tries < 20) {
		setTimeout(() => ensure_bizdocs_panel(frm, tries + 1), 150);
	}
}

function update_reference_on_linked_doc(frm) {
	if (!frm.doc.finance_dossier_from || !frm.doc.id) {
		return;
	}

	frappe.call({
		method: "frappe.client.set_value",
		args: {
			doctype: frm.doc.finance_dossier_from,
			name: frm.doc.id,
			fieldname: "custom_finance_dossier",
			value: frm.doc.name,
		},
		callback: function (res) {
			console.log("custom_finance_dossier field updated on " + frm.doc.finance_dossier_from);
		},
	});
}
