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

	def _require_documents(self):
		"""At least one Business Documentation must be uploaded in the Documents tab."""
		count = frappe.db.count(
			"Business Documentation",
			{"reference_doctype": self.doctype, "reference_name": self.name},
		)
		if not count:
			frappe.throw(
				_("Upload at least one document in the Documents tab before submitting the Finance Dossier.")
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
