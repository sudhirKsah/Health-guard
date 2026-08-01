"use client";

import { FormEvent, useState } from "react";

import { formValue } from "../lib/api";
import type { MandateSetupSession, MerchantAuthorization } from "../lib/types";

type SetupBody = {
  approved_amount: number;
  currency: string;
  recurring_frequency: string;
  valid_until: string;
};

type Props = {
  authorizations: MerchantAuthorization[];
  busy: boolean;
  onSetup: (id: string, body: SetupBody) => Promise<MandateSetupSession>;
  onAction: (id: string, action: "pause" | "resume" | "cancel") => Promise<void>;
};

function oneYearFromNow(): string {
  const date = new Date();
  date.setFullYear(date.getFullYear() + 1);
  return date.toISOString().slice(0, 16);
}

function mandateLabel(status: string | null): string {
  if (!status) return "Not created";
  if (status === "active") return "Active";
  if (status === "pending") return "Waiting for approval";
  if (status === "paused") return "Paused";
  if (status === "cancelled" || status === "canceled") return "Cancelled";
  return status.replaceAll("_", " ");
}

export function MandateControls({ authorizations, busy, onSetup, onAction }: Props) {
  const [approval, setApproval] = useState<{ url: string; merchant: string; expiresAt: string | null } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>, item: MerchantAuthorization) {
    event.preventDefault();
    const form = event.currentTarget;
    const session = await onSetup(item.id, {
      approved_amount: Number(formValue(form, "cap")),
      currency: "INR",
      recurring_frequency: formValue(form, "frequency"),
      valid_until: formValue(form, "validUntil"),
    });
    setApproval({ url: session.iframe_url, merchant: item.merchant_name, expiresAt: session.expires_at });
  }

  async function act(item: MerchantAuthorization, action: "pause" | "resume" | "cancel") {
    const wording = action === "cancel" ? "Cancel this mandate permanently? Future automatic payments at this merchant will stop." : `${action === "pause" ? "Pause" : "Resume"} automatic payments at ${item.merchant_name}?`;
    if (!window.confirm(wording)) return;
    await onAction(item.id, action);
  }

  return (
    <section className="stack page-section">
      <div className="plain-heading"><h2>Your spending permissions</h2><p>You approve each merchant once with a passkey. Health Guard can then pay only within the merchant, amount, frequency, and end date you choose.</p></div>
      {approval && <div className="approval-panel"><div><strong>Secure approval ready for {approval.merchant}</strong><p>Complete the passkey approval on Prava. Health Guard will detect the result automatically when you return.</p></div><a className="button-link" href={approval.url} target="_blank" rel="noreferrer">Continue to Prava</a>{approval.expiresAt && <small>This link expires {new Date(approval.expiresAt).toLocaleString()}.</small>}</div>}
      {!authorizations.length && <p className="empty-state card">Select a merchant before creating a spending permission.</p>}
      <div className="mandate-grid">{authorizations.map((item) => {
        const activeOrPaused = item.mandate_status === "active" || item.mandate_status === "paused";
        return <article className="card mandate-card" key={item.id}><header><div><strong>{item.merchant_name}</strong><small>{item.merchant_domain}</small></div><span className={`status-pill ${item.mandate_status === "active" ? "approved" : item.mandate_status ?? "not-created"}`}>{mandateLabel(item.mandate_status)}</span></header>{activeOrPaused ? <><div className="mandate-summary"><span><small>Per-payment limit</small><b>{item.mandate_currency ?? "INR"} {item.mandate_approved_amount ?? "—"}</b></span><span><small>How often</small><b>{item.mandate_frequency ?? "—"}</b></span><span><small>Health Guard stops</small><b>{item.health_guard_stop_after ? new Date(item.health_guard_stop_after).toLocaleDateString() : "—"}</b></span></div><div className="card-actions">{item.mandate_status === "active" ? <button className="quiet" disabled={busy} onClick={() => act(item, "pause")}>Pause payments</button> : <button disabled={busy} onClick={() => act(item, "resume")}>Resume payments</button>}<button className="danger" disabled={busy} onClick={() => act(item, "cancel")}>Cancel permission</button></div></> : <form className="stack mandate-form-simple" onSubmit={(event) => submit(event, item)}><label>Maximum for one payment<small>The agent can pay less, but never more than this amount.</small><div className="money-input"><span>₹</span><input name="cap" type="number" min="1" step="0.01" defaultValue={item.mandate_approved_amount ?? "1000"} required /></div></label><label>How often may a payment happen?<small>Choose how frequently this recurring permission can be used.</small><select name="frequency" defaultValue={item.mandate_frequency ?? "monthly"}><option value="weekly">Once each week</option><option value="monthly">Once each month</option><option value="yearly">Once each year</option></select></label><label>Stop automatic payments after<small>The permission remains bounded even if you forget to pause it.</small><input name="validUntil" type="datetime-local" defaultValue={item.health_guard_stop_after ? new Date(item.health_guard_stop_after).toISOString().slice(0, 16) : oneYearFromNow()} required /></label><button disabled={busy || !item.is_enabled}>Create secure approval</button>{item.mandate_status === "pending" && <p className="hint">Finish the existing Prava approval. Its status updates automatically.</p>}</form>}</article>;
      })}</div>
    </section>
  );
}
