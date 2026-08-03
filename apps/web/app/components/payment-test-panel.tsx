"use client";

import type { Dashboard } from "../lib/types";

type Props = {
  dashboard: Dashboard;
  busy: boolean;
  onTest: (supplyId: string, supplyName: string) => void;
};

function nextOrderLabel(value: string, due: boolean) {
  if (due) return "Due now";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function PaymentTestPanel({ dashboard, busy, onTest }: Props) {
  const rows = dashboard.beneficiaries.flatMap((beneficiary) =>
    beneficiary.supplies.map((supply) => ({ beneficiary, supply })),
  );
  const authorizations = new Map(dashboard.merchant_authorizations.map((item) => [item.id, item]));

  return <div className="stack page-section"><section className="test-hero"><div><span className="test-badge">Sandbox only</span><h2>Test one recurring payment safely</h2><p>Choose a due supply. Health Guard rechecks the approved catalog item, applies the active mandate limits, requests one sandbox payment and records the result.</p></div><div className="test-flow" aria-label="Payment test steps"><span>1 Product</span><span>2 Rules</span><span>3 Prava</span><span>4 Result</span></div></section><section className="test-grid">{rows.map(({ beneficiary, supply }) => {
    const variants = supply.equivalence_sets.flatMap((item) => item.approved_variants);
    // The agent may have exact matches at more than one merchant. Prefer a variant whose
    // merchant has an active mandate, so this readiness screen matches what the agent can use.
    const variant = variants.find((item) => authorizations.get(item.merchant_authorization_id)?.mandate_status === "active") ?? variants[0];
    const authorization = variant ? authorizations.get(variant.merchant_authorization_id) : undefined;
    const due = supply.order_due;
    const ready = supply.setup_status === "ready" && supply.is_enabled;
    const mandateReady = authorization?.mandate_status === "active";
    const canTest = ready && due && mandateReady;
    const reason = !ready ? "Finish product setup and enable automatic orders first." : !due ? "This supply has not reached its reorder point yet." : !mandateReady ? "An active Prava mandate is required for the selected merchant." : "Ready for one confirmed sandbox payment test.";
    // Each precondition gets its own line with a tick or a cross, so "Not ready" always says why.
    const checks = [
      { ok: ready, label: "Product approved and orders on" },
      { ok: due, label: "Stock has reached the reorder level" },
      { ok: mandateReady, label: "Spending permission is active" },
    ];
    return <article className={`test-card ${canTest ? "ready" : ""}`} key={supply.id}>
      <header><div><small>{beneficiary.name}</small><h3>{supply.name}</h3></div><span className={`status-pill ${canTest ? "approved" : "pending"}`}>{canTest ? "Ready to test" : "Not ready"}</span></header>
      <div className="test-product"><span>Approved product</span><strong>{variant?.display_name ?? "No product selected"}</strong><small>{authorization?.merchant_name ?? "No approved merchant"}</small></div>
      <ul className="check-list">
        {checks.map((c) => (
          <li key={c.label} className={c.ok ? "ok" : "no"}><span aria-hidden>{c.ok ? "✓" : "×"}</span>{c.label}</li>
        ))}
      </ul>
      <div className="test-facts">
        <div><small>Next automatic order</small><b>{nextOrderLabel(supply.next_order_at, supply.order_due)}</b></div>
        <div><small>Limit left</small><b>{authorization?.mandate_currency ?? ""} {authorization?.mandate_remaining_amount ?? "—"}</b></div>
      </div>
      <p className="test-reason">{reason}</p>
      <button disabled={busy || !canTest} onClick={() => onTest(supply.id, supply.name)}>{busy ? "Running secure test…" : "Run payment test"}</button>
    </article>;
  })}{!rows.length && <p className="empty-state">Add a recurring supply before testing a payment.</p>}</section><p className="sandbox-note">This verifies the Prava sandbox mandate charge and APPROVED/DECLINED reporting flow. It does not create physical merchant fulfillment.</p></div>;
}
