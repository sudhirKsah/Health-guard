"use client";

import { HealthGuardApp } from "./health-guard-app";

export type WorkspacePage = "dashboard" | "beneficiaries" | "supplies" | "merchants" | "mandates" | "payment-test" | "transactions" | "activity";

const labels: Record<WorkspacePage, { eyebrow: string; title: string; subtitle: string }> = {
  dashboard: { eyebrow: "Overview", title: "Everything important, at a glance.", subtitle: "Live supply, payment, and agent updates without refreshing." },
  beneficiaries: { eyebrow: "People", title: "Who are the supplies for?", subtitle: "Add yourself or someone you help care for." },
  supplies: { eyebrow: "Recurring supplies", title: "Tell us what should never run out.", subtitle: "Use ordinary label details. Health Guard handles catalog IDs and exact-product approval." },
  merchants: { eyebrow: "Stores", title: "Choose merchants you trust.", subtitle: "The agent searches and buys only from the stores you select." },
  mandates: { eyebrow: "Spending permissions", title: "Set clear payment limits.", subtitle: "Approve once with Prava, then pause or cancel whenever you want." },
  "payment-test": { eyebrow: "Sandbox payment test", title: "Verify recurring payments safely.", subtitle: "Run one confirmed payment through the same product, policy and Prava mandate flow used by the agent." },
  transactions: { eyebrow: "Payment transactions", title: "Every payment result, clearly shown.", subtitle: "Approved, declined and processing payments appear here in real time." },
  activity: { eyebrow: "Activity", title: "See what Health Guard has been doing.", subtitle: "Supply setup, changes and agent decisions without payment transaction noise." },
};

export function WorkspacePage({ page }: { page: WorkspacePage }) {
  return <HealthGuardApp page={page} heading={labels[page]} />;
}
