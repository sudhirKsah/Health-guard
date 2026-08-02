"use client";

import type { LedgerEvent } from "../lib/types";

export function ActivityPanel({ events }: { events: LedgerEvent[] }) {
  const paymentEventTypes = new Set(["agent_purchased", "agent_checkout_declined"]);
  const generalEvents = events.filter((event) => !event.purchase_order_id && !paymentEventTypes.has(event.event_type));
  return <section className="card stack page-section"><div className="plain-heading"><h2>Care activity</h2><p>Product setup, supply changes, mandate controls and agent decisions. Payment results stay in Payment transactions.</p></div>{generalEvents.length ? <div className="ledger-list">{generalEvents.map((event) => <article className={`ledger-event ${event.severity}`} key={event.id}><div><strong>{event.title}</strong><small>{new Date(event.created_at).toLocaleString()}</small></div><p>{event.detail}</p></article>)}</div> : <p className="empty-state">No care activity yet.</p>}</section>;
}
