"use client";

import { FormEvent, useState } from "react";

import type { AgentRun, Supply } from "../lib/types";

type Props = {
  supplies: Supply[];
  runs: AgentRun[];
  busy: boolean;
  onStart: (supplyId: string) => void;
  onSchedule: (supplyId: string, runAt: Date) => void;
};

function defaultScheduleTime() {
  return new Date(Date.now() + 3 * 60_000).toISOString().slice(0, 16);
}

export function AgentRunsPanel({ supplies, runs, busy, onStart, onSchedule }: Props) {
  const [supplyId, setSupplyId] = useState("");
  const [runAt, setRunAt] = useState(defaultScheduleTime);

  function submitSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedSupply = supplyId || supplies[0]?.id;
    const scheduledAt = new Date(runAt);
    if (!selectedSupply || Number.isNaN(scheduledAt.valueOf())) return;
    onSchedule(selectedSupply, scheduledAt);
  }

  return (
    <section className="card agent-runs">
      <div className="section-heading"><div><p className="eyebrow">Phase 6</p><h2>Replenishment Agent</h2></div><p className="hint">A scheduled run uses the same owner-scoped agent and records its real tool trace. No outcome is simulated.</p></div>
      <div className="run-buttons">{supplies.map((supply) => <button key={supply.id} disabled={busy} onClick={() => onStart(supply.id)}>Evaluate {supply.name}</button>)}</div>
      {supplies.length > 0 && <form className="schedule-run" onSubmit={submitSchedule}>
        <label>Supply<select value={supplyId || supplies[0]?.id || ""} onChange={(event) => setSupplyId(event.target.value)}>{supplies.map((supply) => <option key={supply.id} value={supply.id}>{supply.name}</option>)}</select></label>
        <label>Run at<input type="datetime-local" value={runAt} min={new Date().toISOString().slice(0, 16)} onChange={(event) => setRunAt(event.target.value)} required /></label>
        <button disabled={busy} type="submit">Schedule evaluation</button>
      </form>}
      {!supplies.length && <p className="muted">Add a supply first.</p>}
      {!runs.length && <p className="muted">No agent evaluations recorded yet.</p>}
      <div className="run-list">{runs.map((run) => <article key={run.id} className="run"><header><div><strong>{run.outcome ?? run.status}</strong><small>{run.days_until_stockout} days to projected stock-out · {new Date(run.created_at).toLocaleString()}</small></div><code>{run.trigger_id}</code></header><p>{run.goal}</p>{run.explanation && <p className="run-explanation">{run.explanation}</p>}{run.offer_snapshots.length > 0 && <div className="offers"><b>Live exact offers</b>{run.offer_snapshots.map((offer) => <p key={offer.id}>{offer.product_title}{offer.variant_title ? ` — ${offer.variant_title}` : ""} · {offer.currency} {offer.landed_price} · {offer.available ? "available" : "unavailable"} · delivery quote pending</p>)}</div>}<ol>{run.steps.map((step) => <li key={step.id}><strong>{step.sequence}. {step.stage}</strong><span>{step.tool_name} · {step.status}</span><pre>{JSON.stringify(step.output_summary, null, 2)}</pre></li>)}</ol></article>)}</div>
    </section>
  );
}
