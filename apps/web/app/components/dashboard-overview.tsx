"use client";

import type { Dashboard, TransactionActivity } from "../lib/types";

export function DashboardOverview({ dashboard, transactions }: { dashboard: Dashboard; transactions: TransactionActivity[] }) {
  const supplies = dashboard.beneficiaries.flatMap((item) => item.supplies);
  const ready = supplies.filter((item) => item.setup_status === "ready").length;
  const attention = supplies.filter((item) => item.setup_status === "needs_attention").length;
  const activeMandates = dashboard.merchant_authorizations.filter((item) => item.mandate_status === "active").length;
  const approvedPayments = transactions.filter((item) => item.status === "approved").length;
  return <section className="overview-grid"><article><small>Recurring supplies</small><strong>{ready}<span> ready</span></strong><p>{attention ? `${attention} needs attention` : "All product checks are clear"}</p></article><article><small>Active permissions</small><strong>{activeMandates}<span> merchants</span></strong><p>Bounded by your Prava mandates</p></article><article><small>Approved payments</small><strong>{approvedPayments}</strong><p>Visible in Payment transactions</p></article></section>;
}
