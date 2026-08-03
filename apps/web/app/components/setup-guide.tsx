"use client";

import Link from "next/link";

import type { Dashboard, TransactionActivity } from "../lib/types";
import type { WorkspacePage } from "../workspace-page";

export type GuideStep = {
  key: string;
  page: WorkspacePage;
  title: string;
  why: string;
  cta: string;
  done: boolean;
  /** Shown instead of the CTA when an earlier step has to happen first. */
  blockedBy?: string;
  /** A finished step that still needs attention — done, but not fully safe yet. */
  warn?: string;
};

/**
 * Derived entirely from live data rather than a stored "onboarding progress" flag, so it is always
 * truthful: delete a mandate and the step reopens by itself. The order encodes the app's real
 * dependency chain — a supply cannot be matched without a shop, and nothing can be paid for
 * without an active limit.
 */
export function setupSteps(dashboard: Dashboard, transactions: TransactionActivity[]): GuideStep[] {
  const people = dashboard.beneficiaries.filter((b) => b.is_active);
  const hasPerson = people.length > 0;
  const missingAddress = people.filter((b) => !b.has_delivery_address);
  const shops = dashboard.merchant_authorizations.filter((m) => m.is_enabled);
  const hasShop = shops.length > 0;
  const hasLimit = dashboard.merchant_authorizations.some((m) => m.mandate_status === "active");
  const supplies = dashboard.beneficiaries.flatMap((b) => b.supplies);
  const hasReadySupply = supplies.some((s) => s.setup_status === "ready");
  const hasPayment = transactions.length > 0;

  return [
    {
      key: "person", page: "beneficiaries",
      title: "Add who you're caring for",
      why: "Their delivery address decides where orders are shipped.",
      cta: "Add a person", done: hasPerson,
      warn: hasPerson && missingAddress.length
        ? `${missingAddress.map((b) => b.name).join(", ")} still needs a delivery address — orders can't ship without one.`
        : undefined,
    },
    {
      key: "shop", page: "merchants",
      title: "Choose shops you trust",
      why: "Health Guard only ever buys from shops you pick.",
      cta: "Choose shops", done: hasShop,
      blockedBy: hasPerson ? undefined : "Add a person first",
    },
    {
      key: "limit", page: "mandates",
      title: "Set a spending limit",
      why: "Approve once with a passkey. This is what lets Health Guard pay.",
      cta: "Set a limit", done: hasLimit,
      blockedBy: hasShop ? undefined : "Choose a shop first",
    },
    {
      key: "supply", page: "supplies",
      title: "Add something to reorder",
      why: "We search your shops and confirm the exact product.",
      cta: "Add a supply", done: hasReadySupply,
      blockedBy: hasShop ? undefined : "Choose a shop first",
    },
    {
      key: "test", page: "payment-test",
      title: "Try a test payment",
      why: "Runs the whole flow safely so you can see it work.",
      cta: "Run a test", done: hasPayment,
      blockedBy: hasLimit && hasReadySupply ? undefined : "Finish the steps above first",
    },
  ];
}

export function SetupGuide({
  dashboard, transactions,
}: { dashboard: Dashboard; transactions: TransactionActivity[] }) {
  const steps = setupSteps(dashboard, transactions);
  const doneCount = steps.filter((s) => s.done).length;
  const next = steps.find((s) => !s.done && !s.blockedBy) ?? steps.find((s) => !s.done);
  const attention = steps.filter((s) => s.warn);
  const complete = doneCount === steps.length;

  if (complete && !attention.length) {
    return (
      <section className="guide guide-done">
        <span className="guide-tick" aria-hidden>✓</span>
        <div>
          <strong>Health Guard is set up and watching.</strong>
          <small>Nothing to do. Checks run automatically — you&apos;ll see every decision in Activity.</small>
        </div>
        <Link className="button-link compact-cta" href="/activity">View activity</Link>
      </section>
    );
  }

  return (
    <section className="guide">
      <header className="guide-head">
        <div>
          <h2>Getting started</h2>
          <p className="hint">{next ? `Next: ${next.title.toLowerCase()}.` : "Finish the highlighted step."}</p>
        </div>
        <span className="guide-count">{doneCount} of {steps.length} done</span>
      </header>

      <div className="guide-bar" role="meter" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={doneCount} aria-label="Setup progress">
        <i style={{ width: `${(doneCount / steps.length) * 100}%` }} />
      </div>

      <ol className="guide-list">
        {steps.map((step, index) => {
          const isNext = step === next;
          const state = step.done ? "done" : step.blockedBy ? "locked" : isNext ? "now" : "todo";
          return (
            <li key={step.key} className={`guide-step ${state}`}>
              <span className="guide-n" aria-hidden>{step.done ? "✓" : index + 1}</span>
              <div className="guide-text">
                <strong>{step.title}</strong>
                <small>{step.warn ?? step.why}</small>
                {step.warn && <span className="guide-warn">Needs attention</span>}
              </div>
              {step.done && !step.warn
                ? <span className="guide-state" aria-label="Done">Done</span>
                : step.blockedBy
                  ? <span className="guide-state locked">{step.blockedBy}</span>
                  : <Link className={isNext || step.warn ? "button-link compact-cta" : "guide-link"} href={`/${step.page}`}>{step.warn ? "Fix it" : step.cta}</Link>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
