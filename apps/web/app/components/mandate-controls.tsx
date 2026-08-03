"use client";

import { useState } from "react";

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

function mandateLabel(status: string | null): string {
  if (!status) return "Not created";
  if (status === "active") return "Active";
  if (status === "pending") return "Waiting for approval";
  if (status === "paused") return "Paused";
  if (status === "cancelled" || status === "canceled") return "Cancelled";
  return status.replaceAll("_", " ");
}

const CAP_PRESETS = [500, 1000, 2000, 5000];
const FREQUENCIES = [
  { value: "weekly", label: "Once a week", help: "For things used up quickly" },
  { value: "monthly", label: "Once a month", help: "Most people choose this" },
  { value: "yearly", label: "Once a year", help: "For rarely-bought items" },
];
const STOP_PRESETS = [
  { months: 3, label: "3 months" },
  { months: 6, label: "6 months" },
  { months: 12, label: "1 year" },
];

function monthsFromNow(months: number): string {
  const date = new Date();
  date.setMonth(date.getMonth() + months);
  return date.toISOString().slice(0, 16);
}

/** Own state per merchant, so each card's choices stay independent. */
function MandateSetupForm({
  item, busy, onSubmit,
}: { item: MerchantAuthorization; busy: boolean; onSubmit: (body: SetupBody) => void }) {
  const [cap, setCap] = useState(String(item.mandate_approved_amount ?? "1000"));
  const [frequency, setFrequency] = useState(item.mandate_frequency ?? "monthly");
  const [stopAfter, setStopAfter] = useState(
    item.health_guard_stop_after ? new Date(item.health_guard_stop_after).toISOString().slice(0, 16) : monthsFromNow(12),
  );

  return (
    <form
      className="mandate-form-simple"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ approved_amount: Number(cap), currency: "INR", recurring_frequency: frequency, valid_until: stopAfter });
      }}
    >
      <section className="fstep">
        <header><span className="fstep-n">1</span><div><h3>Most for one payment</h3><small>Health Guard can spend less, never more.</small></div></header>
        <div className="fstep-body">
          <div className="money-input"><span>₹</span><input value={cap} onChange={(event) => setCap(event.target.value)} type="number" inputMode="decimal" min="1" step="0.01" required aria-label="Maximum for one payment" /></div>
          <div className="chip-row">
            {CAP_PRESETS.map((amount) => (
              <button type="button" key={amount} className={`chip ${Number(cap) === amount ? "chip-on" : ""}`} aria-pressed={Number(cap) === amount} onClick={() => setCap(String(amount))}>₹{amount.toLocaleString("en-IN")}</button>
            ))}
          </div>
        </div>
      </section>

      <section className="fstep">
        <header><span className="fstep-n">2</span><div><h3>How often may it pay?</h3><small>One payment per period, at this shop only.</small></div></header>
        <div className="fstep-body">
          <div className="choice-list">
            {FREQUENCIES.map((f) => (
              <button type="button" key={f.value} className={`choice ${frequency === f.value ? "chip-on" : ""}`} aria-pressed={frequency === f.value} onClick={() => setFrequency(f.value)}>
                <span><b>{f.label}</b><small>{f.help}</small></span>
                <span className="choice-tick" aria-hidden>{frequency === f.value ? "✓" : ""}</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="fstep">
        <header><span className="fstep-n">3</span><div><h3>Stop automatically after</h3><small>A hard end date, even if you forget to pause it.</small></div></header>
        <div className="fstep-body">
          <div className="chip-row">
            {STOP_PRESETS.map((s) => (
              <button type="button" key={s.months} className={`chip ${stopAfter === monthsFromNow(s.months) ? "chip-on" : ""}`} onClick={() => setStopAfter(monthsFromNow(s.months))}>{s.label}</button>
            ))}
          </div>
          <details className="opt-block">
            <summary><span>Pick an exact date instead</span><small>Optional</small></summary>
            <div className="opt-body">
              <input value={stopAfter} onChange={(event) => setStopAfter(event.target.value)} type="datetime-local" required aria-label="Stop automatic payments after" />
            </div>
          </details>
        </div>
      </section>

      <div className="mandate-recap">
        <span>You are allowing</span>
        <strong>up to ₹{Number(cap || 0).toLocaleString("en-IN")} · {FREQUENCIES.find((f) => f.value === frequency)?.label.toLowerCase()}</strong>
        <small>at {item.merchant_name} only, until {stopAfter ? new Date(stopAfter).toLocaleDateString() : "—"}</small>
      </div>

      <button className="submit-cta" disabled={busy || !item.is_enabled}>Create secure approval</button>
      {item.mandate_status === "pending" && <p className="hint">Finish the existing Prava approval. Its status updates automatically.</p>}
    </form>
  );
}

export function MandateControls({ authorizations, busy, onSetup, onAction }: Props) {
  const [approval, setApproval] = useState<{ url: string; merchant: string; expiresAt: string | null } | null>(null);

  async function submit(item: MerchantAuthorization, body: SetupBody) {
    const session = await onSetup(item.id, body);
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
        return <article className="card mandate-card" key={item.id}><header><div><strong>{item.merchant_name}</strong><small>{item.merchant_domain}</small></div><span className={`status-pill ${item.mandate_status === "active" ? "approved" : item.mandate_status ?? "not-created"}`}>{mandateLabel(item.mandate_status)}</span></header>{activeOrPaused ? <><div className="mandate-summary"><span><small>Per-payment limit</small><b>{item.mandate_currency ?? "INR"} {item.mandate_approved_amount ?? "—"}</b></span><span><small>How often</small><b>{item.mandate_frequency ?? "—"}</b></span><span><small>Health Guard stops</small><b>{item.health_guard_stop_after ? new Date(item.health_guard_stop_after).toLocaleDateString() : "—"}</b></span></div><div className="card-actions">{item.mandate_status === "active" ? <button className="quiet" disabled={busy} onClick={() => act(item, "pause")}>Pause payments</button> : <button disabled={busy} onClick={() => act(item, "resume")}>Resume payments</button>}<button className="danger" disabled={busy} onClick={() => act(item, "cancel")}>Cancel permission</button></div></> : <MandateSetupForm item={item} busy={busy} onSubmit={(body) => void submit(item, body)} />}</article>;
      })}</div>
    </section>
  );
}
