"use client";

import type { AgentRun, Supply } from "../lib/types";

type Props = {
  supplies: Supply[];
  runs: AgentRun[];
  busy: boolean;
  onStart: (supplyId: string) => void;
};

export function AgentRunsPanel({ supplies, runs, busy, onStart }: Props) {
  return (
    <section className="card agent-runs">
      <div className="section-heading"><div><p className="eyebrow">Phase 3</p><h2>Replenishment Agent</h2></div><p className="hint">Read-only evaluation only. It cannot charge, check out, or simulate a purchase.</p></div>
      <div className="run-buttons">{supplies.map((supply) => <button key={supply.id} disabled={busy} onClick={() => onStart(supply.id)}>Evaluate {supply.name}</button>)}</div>
      {!supplies.length && <p className="muted">Add a supply first.</p>}
      {!runs.length && <p className="muted">No agent evaluations recorded yet.</p>}
      <div className="run-list">{runs.map((run) => <article key={run.id} className="run"><header><div><strong>{run.outcome ?? run.status}</strong><small>{run.days_until_stockout} days to projected stock-out · {new Date(run.created_at).toLocaleString()}</small></div><code>{run.trigger_id}</code></header><p>{run.goal}</p>{run.explanation && <p className="run-explanation">{run.explanation}</p>}<ol>{run.steps.map((step) => <li key={step.id}><strong>{step.sequence}. {step.stage}</strong><span>{step.tool_name} · {step.status}</span><pre>{JSON.stringify(step.output_summary, null, 2)}</pre></li>)}</ol></article>)}</div>
    </section>
  );
}
