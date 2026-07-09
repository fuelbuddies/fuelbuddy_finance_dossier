# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

DOCSTATUS_LABELS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}

# Shared "Fuelbuddy Settings" single doctype (hosted in fuelbuddy_crm, read by all
# FuelBuddy apps): the "document_required" flag gates every Business Documentation
# validation on the deal flow. When off, the Finance Dossier submits without any
# documents and no document-status check blocks it.
FB_SETTINGS_DOCTYPE = "Fuelbuddy Settings"


def documents_required():
	"""True when Business Documents are enforced ("Document Required" in Fuelbuddy
	Settings). Defaults to enforced when the flag has never been set, preserving the
	original always-required behaviour. Read straight from tabSingles because
	``get_single_value`` casts a missing Check field to 0, hiding "never set"."""
	row = frappe.db.sql(
		"select value from `tabSingles` where doctype=%s and field=%s",
		(FB_SETTINGS_DOCTYPE, "document_required"),
	)
	if not row:
		return True
	return bool(frappe.utils.cint(row[0][0]))


def fd_first_flow():
	"""The "FD-First Flow" switch on the shared Fuelbuddy Settings single (hosted in
	fuelbuddy_crm). ON: the Quotation validates that its dossier is submitted and the
	Sales Order is triggered by the Quotation submit. OFF (default): legacy order —
	the dossier requires a submitted Quotation and its submit triggers the SO.
	Reading a Single needs no schema, and any failure (fuelbuddy_crm not installed)
	falls back to the legacy order, so the two apps deploy independently."""
	try:
		return bool(frappe.db.get_single_value("Fuelbuddy Settings", "fd_first_flow"))
	except Exception:
		return False


class FinanceDossier(Document):
	def before_submit(self):
		# Documents must be uploaded before a Finance Dossier can be submitted.
		# FD-first flow ON: the QUOTATION validates that this dossier is submitted
		# (fuelbuddy_crm.finance_dossier.require_submitted_dossier), not vice versa.
		# OFF: legacy order — this dossier requires a submitted Quotation.
		self._require_documents()
		if not fd_first_flow():
			self._require_submitted_quotation()

	def on_update(self):
		self.sync_opportunity_status()

	def on_submit(self):
		self.sync_opportunity_status()
		if not fd_first_flow():
			self._maybe_create_sales_order()

	def on_update_after_submit(self):
		# Legacy-flow safety net: if the SO wasn't created at submit time, retry
		# when the submitted Finance Dossier is saved again.
		if not fd_first_flow():
			self._maybe_create_sales_order()

	def on_cancel(self):
		self.sync_opportunity_status()

	def on_trash(self):
		self._block_delete_in_workflow()

	# -- validation -----------------------------------------------------------

	def _block_delete_in_workflow(self):
		"""Block deleting a Finance Dossier once it has entered the approval workflow
		(BUG-011).

		Only a *clean Draft* may be deleted: one that is not submitted/cancelled, whose
		source Quotation is not yet submitted, and that has no documents under review or
		already approved. Deleting a dossier that is mid-approval (or beyond) would
		permanently destroy the approval record with no way to re-approve."""
		if self.docstatus != 0:
			frappe.throw(
				_(
					"Cannot delete a Finance Dossier that is submitted or cancelled — it "
					"carries the approval record of the deal."
				)
			)

		if (
			self.finance_dossier_from == "Quotation"
			and self.id
			and frappe.db.get_value("Quotation", self.id, "docstatus") == 1
		):
			frappe.throw(
				_(
					"Cannot delete a Finance Dossier whose Quotation is already submitted "
					"(the deal is contracted). Cancel/amend the deal instead."
				)
			)

		if not documents_required():
			return  # documents not enforced -> their status never blocks deletion

		for ref_doctype, ref_name in self._document_reference_chain():
			if frappe.db.exists(
				"Business Documentation",
				{
					"reference_doctype": ref_doctype,
					"reference_name": ref_name,
					"status": ["in", ["PENDING_APPROVAL", "APPROVED"]],
				},
			):
				frappe.throw(
					_(
						"Cannot delete a Finance Dossier that is in the approval workflow — "
						"documents are pending review or already approved. Cancel/amend instead."
					)
				)

	def _document_reference_chain(self):
		"""Every ``(doctype, name)`` whose Business Documentation counts toward this
		Finance Dossier -- the same deal chain the dossier's document panel shows:
		this Finance Dossier, its source Quotation/Opportunity, the Opportunity it
		belongs to, and the underlying Customer/Lead. Documents uploaded anywhere on
		the chain are reviewed and approved from the dossier."""
		refs = [(self.doctype, self.name)]
		if self.id:
			refs.append((self.finance_dossier_from, self.id))

		opportunity = self._opportunity()
		if opportunity:
			refs.append(("Opportunity", opportunity))

		# The underlying party (Customer / Lead): documents are often uploaded there.
		party_dt = party_name = None
		if self.finance_dossier_from == "Quotation" and self.id:
			party_dt, party_name = frappe.db.get_value(
				"Quotation", self.id, ["quotation_to", "party_name"]
			) or (None, None)
		elif self.finance_dossier_from == "Opportunity" and self.id:
			party_dt, party_name = frappe.db.get_value(
				"Opportunity", self.id, ["opportunity_from", "party_name"]
			) or (None, None)
		if party_dt and party_name:
			refs.append((party_dt, party_name))

		seen, uniq = set(), []
		for ref in refs:
			if ref[0] and ref[1] and ref not in seen:
				seen.add(ref)
				uniq.append(ref)
		return uniq

	def _require_documents(self):
		"""Every Business Documentation across the deal chain (this Finance Dossier,
		its Quotation/Opportunity, and the underlying Customer/Lead) must be APPROVED
		before the Finance Dossier can be submitted. Approval is done manually from
		the dossier's document panel; at least one document must exist.

		Skipped entirely when "Document Required" is off in Fuelbuddy Settings."""
		if not documents_required():
			return

		docs = []
		for ref_doctype, ref_name in self._document_reference_chain():
			docs += frappe.get_all(
				"Business Documentation",
				filters={"reference_doctype": ref_doctype, "reference_name": ref_name},
				fields=["name", "document_type", "status"],
			)

		if not docs:
			frappe.throw(
				_(
					"Upload at least one document (on the Opportunity, the Quotation, the "
					"Customer/Lead, or this Finance Dossier) before submitting the Finance Dossier."
				)
			)

		pending = [d for d in docs if d.status != "APPROVED"]
		if pending:
			labels = ", ".join(sorted({(d.document_type or d.name) for d in pending}))
			frappe.throw(
				_(
					"All documents must be approved before submitting the Finance Dossier. "
					"Not yet approved: {0}."
				).format(labels)
			)

	def _require_submitted_quotation(self):
		"""Legacy order (FD-First Flow OFF): the Quotation this Finance Dossier was
		raised from must be submitted first."""
		if self.finance_dossier_from != "Quotation" or not self.id:
			return
		if frappe.db.get_value("Quotation", self.id, "docstatus") != 1:
			frappe.throw(
				_("Quotation {0} must be submitted before submitting the Finance Dossier.").format(self.id)
			)

	# -- linkage / automation -------------------------------------------------

	def _opportunity(self):
		"""The Opportunity this dossier ultimately belongs to. The dossier links to a
		Quotation; the Opportunity is resolved through the Quotation. (Legacy dossiers
		linked directly to an Opportunity are still supported.)"""
		if self.finance_dossier_from == "Opportunity":
			return self.id
		if self.finance_dossier_from == "Quotation" and self.id:
			return frappe.db.get_value("Quotation", self.id, "custom_opportunity_from")
		return None

	def _maybe_create_sales_order(self):
		"""Legacy order (FD-First Flow OFF): FD submit kicks the SO automation."""
		opportunity = self._opportunity()
		if not opportunity:
			return
		try:
			from fuelbuddy_crm.sales_automation import create_sales_order_if_ready

			create_sales_order_if_ready(opportunity)
		except ImportError:
			pass

	def sync_opportunity_status(self):
		"""Reflect this Finance Dossier's docstatus on the source Opportunity."""
		opportunity = self._opportunity()
		if not opportunity or not frappe.db.exists("Opportunity", opportunity):
			return

		status = DOCSTATUS_LABELS.get(self.docstatus, "Draft")
		frappe.db.set_value(
			"Opportunity", opportunity, "custom_finance_dossier_status", status, update_modified=False
		)
