"use client";

import type { LedgerEvent, Supply } from "../lib/types";

export function TrustPanel({ events, supplies, busy, onRunningLow }: { events: LedgerEvent[]; supplies: Supply[]; busy: boolean; onRunningLow: (id: string) => void }) {
  return <section className="card stack trust-panel"><div className="section-heading"><div><h2>Recent activity</h2><p className="hint">Clear updates about product checks, orders, payments, and anything needing attention.</p></div><div className="low-actions">{supplies.filter((supply) => supply.is_enabled).map((supply) => <button className="quiet" key={supply.id} disabled={busy} onClick={() => onRunningLow(supply.id)}>I’m low on {supply.name}</button>)}</div></div><div className="ledger-list">{events.length ? events.slice(0, 12).map((event) => <article className={`ledger-event ${event.severity}`} key={event.id}><div><strong>{event.title}</strong><small>{new Date(event.created_at).toLocaleString()}</small></div><p>{event.detail}</p></article>) : <p className="empty-state">Your updates will appear here.</p>}</div></section>;
}
