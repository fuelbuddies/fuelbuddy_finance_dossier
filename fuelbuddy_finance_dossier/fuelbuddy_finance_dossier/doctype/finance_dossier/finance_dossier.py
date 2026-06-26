# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

DOCSTATUS_LABELS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


class FinanceDossier(Document):
	def before_submit(self):
		# Documents must be uploaded and the source Quotation submitted before a
		# Finance Dossier can be submitted/approved.
		self._require_documents()
		self._require_submitted_quotation()

	def on_update(self):
		self.sync_opportunity_status()

	def on_submit(self):
		self.sync_opportunity_status()
		self._maybe_create_sales_order()

	def on_update_after_submit(self):
		# Safety net: if SO wasn't created at submit time, retry when the
		# submitted Finance Dossier is saved again.
		self._maybe_create_sales_order()

	def on_cancel(self):
		self.sync_opportunity_status()

	# -- validation -----------------------------------------------------------

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
		the dossier's document panel; at least one document must exist."""
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
		"""The Quotation this Finance Dossier was raised from must be submitted."""
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
