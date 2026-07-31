"use client";

import { FormEvent, useState } from "react";

import { formValue } from "../lib/api";
import type { MandateSetupSession, MerchantAuthorization } from "../lib/types";

type SetupBody = {
  approved_amount: number;
  currency: string;
  recurring_frequency: string;
  max_charges: number;
  valid_until: string;
};

type Props = {
  authorizations: MerchantAuthorization[];
  busy: boolean;
  onSetup: (id: string, body: SetupBody) => Promise<MandateSetupSession>;
  onSync: (id: string) => Promise<void>;
  onAction: (id: string, action: "pause" | "resume" | "cancel") => Promise<void>;
};

function oneYearFromNow(): string {
  const date = new Date();
  date.setFullYear(date.getFullYear() + 1);
  return date.toISOString().slice(0, 16);
}

function statusText(item: MerchantAuthorization): string {
  if (!item.mandate_status) return "No Prava mandate yet";
  const cap = item.mandate_approved_amount
    ? ` · cap ${item.mandate_currency ?? "INR"} ${item.mandate_approved_amount}`
    : "";
  return `${item.mandate_status}${cap}`;
}

export function MandateControls({ authorizations, busy, onSetup, onSync, onAction }: Props) {
  const [approval, setApproval] = useState<{ url: string; merchant: string; expiresAt: string | null } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>, item: MerchantAuthorization) {
    event.preventDefault();
    const form = event.currentTarget;
    const session = await onSetup(item.id, {
      approved_amount: Number(formValue(form, "cap")),
      currency: "INR",
      recurring_frequency: formValue(form, "frequency"),
      max_charges: Number(formValue(form, "maxCharges")),
      valid_until: formValue(form, "validUntil"),
    });
    setApproval({ url: session.iframe_url, merchant: item.merchant_name, expiresAt: session.expires_at });
  }

  async function act(item: MerchantAuthorization, action: "pause" | "resume" | "cancel") {
    const wording = action === "cancel" ? "This permanently stops future autonomous charges." : `Confirm ${action} for this merchant mandate.`;
    if (!window.confirm(wording)) return;
    await onAction(item.id, action);
  }

  return (
    <section className="card mandates stack">
      <div className="section-heading">
        <div><h2>5. Prava mandate controls</h2><p className="hint">Each recurring authorization is limited to one merchant. Health Guard never sees card details or payment credentials.</p></div>
      </div>
      {approval && <div className="approval-panel"><strong>Approval ready for {approval.merchant}</strong><p>Open Prava&apos;s secure passkey page, finish approval, then return here and sync status.</p><a className="button-link" href={approval.url} target="_blank" rel="noreferrer">Open secure Prava approval</a>{approval.expiresAt && <small>Approval session expires {new Date(approval.expiresAt).toLocaleString()}.</small>}</div>}
      {!authorizations.length && <p className="muted">Approve a merchant above before creating its mandate.</p>}
      {authorizations.map((item) => <article className="mandate" key={item.id}><header><div><strong>{item.merchant_name}</strong><small>{statusText(item)}</small></div><button className="quiet" type="button" disabled={busy} onClick={() => onSync(item.id)}>Sync Prava status</button></header>{item.mandate_status === "active" || item.mandate_status === "paused" ? <div className="mandate-actions">{item.mandate_status === "active" ? <button className="quiet" type="button" disabled={busy} onClick={() => act(item, "pause")}>Pause future purchases</button> : <button className="quiet" type="button" disabled={busy} onClick={() => act(item, "resume")}>Resume purchases</button>}<button className="danger" type="button" disabled={busy} onClick={() => act(item, "cancel")}>Cancel mandate</button></div> : <form className="mandate-form" onSubmit={(event) => submit(event, item)}><label>Per-order cap (INR)<input name="cap" type="number" min="1" step="0.01" defaultValue={item.mandate_approved_amount ?? "1000"} required /></label><label>Frequency<select name="frequency" defaultValue={item.mandate_frequency ?? "monthly"}><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></label><label>Maximum charges<input name="maxCharges" type="number" min="1" max="104" defaultValue={item.mandate_max_charges ?? 12} required /></label><label>Health Guard stops after<input name="validUntil" type="datetime-local" defaultValue={item.health_guard_stop_after ? new Date(item.health_guard_stop_after).toISOString().slice(0, 16) : oneYearFromNow()} required /></label><button disabled={busy || !item.is_enabled}>Create passkey approval</button><small>Health Guard will not initiate a charge after this time.</small>{!item.is_enabled && <small>Resume the merchant permission before creating its mandate.</small>}</form>}</article>)}
    </section>
  );
}
