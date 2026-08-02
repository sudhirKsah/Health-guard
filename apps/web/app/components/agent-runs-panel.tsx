"use client";

import type { AgentRun, Supply } from "../lib/types";

type Props = {
  supplies: Supply[];
  runs: AgentRun[];
  busy: boolean;
  onStart: (supplyId: string) => void;
};

const stageLabels: Record<string, string> = {
  observe: "Checked remaining stock",
  discover: "Checked approved stores",
  decide: "Applied your safety and spending rules",
  act: "Requested the approved payment",
  verify: "Confirmed the payment result",
};

function outcomeLabel(run: AgentRun) {
  if (run.outcome === "purchased") return "Order placed";
  if (run.outcome === "checkout_declined") return "Merchant declined";
  if (run.outcome === "blocked") return "No purchase made";
  if (run.outcome === "wait") return "No order needed";
  if (run.outcome === "frequency_wait") return "Waiting for renewal";
  return run.status === "running" ? "Checking now" : "Check completed";
}

export function AgentRunsPanel({ supplies, runs, busy, onStart }: Props) {
  return (
    <section className="card stack agent-runs">
      <div className="section-heading"><div><h2>Automatic supply checks</h2><p className="hint">Health Guard checks stock on schedule. You can also ask it to check now.</p></div><div className="run-buttons">{supplies.filter((supply) => supply.is_enabled).map((supply) => <button className="quiet" key={supply.id} disabled={busy} onClick={() => onStart(supply.id)}>Check {supply.name}</button>)}</div></div>
      {!supplies.length && <p className="empty-state">Add a recurring supply to begin.</p>}
      {!runs.length && supplies.length > 0 && <p className="empty-state">The first automatic check will appear here.</p>}
      <div className="run-list">{runs.slice(0, 10).map((run) => {
        const supply = supplies.find((item) => item.id === run.supply_id);
        return <article key={run.id} className="run-card"><header><div><strong>{supply?.name ?? "Supply check"}</strong><small>{new Date(run.created_at).toLocaleString()}</small></div><span className={`status-pill ${run.outcome === "purchased" ? "approved" : run.outcome === "checkout_declined" ? "declined" : run.outcome ?? run.status}`}>{outcomeLabel(run)}</span></header>{run.explanation && <p>{run.explanation}</p>}<div className="friendly-steps">{run.steps.map((step) => <span className={step.status === "success" ? "done" : step.status} key={step.id}>{stageLabels[step.stage] ?? "Completed a safe check"}</span>)}</div></article>;
      })}</div>
    </section>
  );
}
