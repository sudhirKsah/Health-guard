"use client";

import Link from "next/link";

import { HealthGuardApp } from "./health-guard-app";

export type WorkspacePage = "dashboard" | "caregivers" | "beneficiaries" | "supplies" | "mandates" | "transactions" | "history" | "notifications" | "settings";

const labels: Record<WorkspacePage, { eyebrow: string; title: string; subtitle: string }> = {
  dashboard: { eyebrow: "Command center", title: "Care, kept in motion.", subtitle: "See what needs attention and why the agent acted." },
  caregivers: { eyebrow: "Care network", title: "Caregiver workspace", subtitle: "Manage the people and merchants you are trusted to support." },
  beneficiaries: { eyebrow: "People receiving care", title: "Beneficiaries", subtitle: "Keep each person’s care inventory separate and visible." },
  supplies: { eyebrow: "Care inventory", title: "Supplies and approvals", subtitle: "Only exact, explicitly approved products can be replenished." },
  mandates: { eyebrow: "Spending controls", title: "Mandates", subtitle: "Review, pause, or cancel merchant-specific recurring authorizations." },
  transactions: { eyebrow: "Money movement", title: "Transactions", subtitle: "Review Prava payment outcomes and their safeguard status." },
  history: { eyebrow: "Agent record", title: "Order history", subtitle: "Every evaluation records what the agent observed, decided, and did." },
  notifications: { eyebrow: "Care updates", title: "Notifications", subtitle: "Signals and agent outcomes, written for a caregiver." },
  settings: { eyebrow: "Account", title: "Settings", subtitle: "Review your product boundaries and account controls." },
};

export function WorkspacePage({ page }: { page: WorkspacePage }) {
  return <HealthGuardApp page={page} heading={labels[page]} />;
}
