"use client";

import type { LedgerEvent, Supply } from "../lib/types";

export function TrustPanel({ events, supplies, busy, onRunningLow }: { events: LedgerEvent[]; supplies: Supply[]; busy: boolean; onRunningLow: (id: string) => void }) {
  return <section className="card trust-panel"><div className="section-heading"><div><p className="eyebrow">Phase 7</p><h2>Caregiver activity</h2></div><p className="hint">Every signal and agent outcome is recorded here. A sandbox payment approval is not a merchant delivery.</p></div><div className="low-actions"><b>I&apos;m running low</b>{supplies.map((supply) => <button className="quiet" key={supply.id} disabled={busy || !supply.is_enabled} onClick={() => onRunningLow(supply.id)}>{supply.name}</button>)}</div><div className="ledger-list">{events.length ? events.map((event) => <article className={`ledger-event ${event.severity}`} key={event.id}><div><strong>{event.title}</strong><small>{new Date(event.created_at).toLocaleString()}</small></div><p>{event.detail}</p></article>) : <p className="muted">Your notifications and agent outcomes will appear here.</p>}</div></section>;
}
