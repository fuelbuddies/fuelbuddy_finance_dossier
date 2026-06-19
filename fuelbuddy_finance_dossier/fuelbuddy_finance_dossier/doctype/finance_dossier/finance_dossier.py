# Copyright (c) 2026, Fuelbuddy and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

DOCSTATUS_LABELS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


class FinanceDossier(Document):
	def on_update(self):
		self.sync_opportunity_status()

	def on_submit(self):
		self.sync_opportunity_status()
		self._maybe_create_sales_order()

	def on_update_after_submit(self):
		# Safety net: if SO wasn't created at submit time, retry when the
		# submitted Finance Dossier is saved again.
		self._maybe_create_sales_order()

	def _maybe_create_sales_order(self):
		if self.finance_dossier_from == "Opportunity" and self.id:
			try:
				from fuelbuddy_crm.sales_automation import create_sales_order_if_ready

				create_sales_order_if_ready(self.id)
			except ImportError:
				pass

	def on_cancel(self):
		self.sync_opportunity_status()

	def sync_opportunity_status(self):
		"""Reflect this Finance Dossier's docstatus on the source Opportunity."""
		if self.finance_dossier_from != "Opportunity" or not self.id:
			return

		if not frappe.db.exists("Opportunity", self.id):
			return

		status = DOCSTATUS_LABELS.get(self.docstatus, "Draft")
		frappe.db.set_value(
			"Opportunity", self.id, "custom_finance_dossier_status", status, update_modified=False
		)
