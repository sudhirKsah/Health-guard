"use client";

import type { LedgerEvent } from "../lib/types";

export function ActivityPanel({ events }: { events: LedgerEvent[] }) {
  const generalEvents = events.filter((event) => !event.purchase_order_id && event.event_type !== "agent_sandbox_settled");
  return <section className="card stack page-section"><div className="plain-heading"><h2>Care activity</h2><p>Product setup, supply changes, mandate controls and agent decisions. Payment results stay in Payment transactions.</p></div>{generalEvents.length ? <div className="ledger-list">{generalEvents.map((event) => <article className={`ledger-event ${event.severity}`} key={event.id}><div><strong>{event.title}</strong><small>{new Date(event.created_at).toLocaleString()}</small></div><p>{event.detail}</p></article>)}</div> : <p className="empty-state">No care activity yet.</p>}</section>;
}
