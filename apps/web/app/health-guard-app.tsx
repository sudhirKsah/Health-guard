"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ActivityPanel } from "./components/activity-panel";
import { AgentRunsPanel } from "./components/agent-runs-panel";
import { AuthPanel } from "./components/auth-panel";
import { CareSetup } from "./components/care-setup";
import { DashboardOverview } from "./components/dashboard-overview";
import { MandateControls } from "./components/mandate-controls";
import { PaymentTestPanel } from "./components/payment-test-panel";
import { SetupGuide, setupSteps } from "./components/setup-guide";
import { TransactionsPanel } from "./components/transactions-panel";
import { TrustPanel } from "./components/trust-panel";
import { ApiError, api, formValue, subscribeToUpdates } from "./lib/api";
import type { AgentRun, Dashboard, LedgerEvent, MandateSetupSession, ProductSuggestion, Session, SupplyAutomationTiming, TransactionActivity } from "./lib/types";
import type { WorkspacePage } from "./workspace-page";

const sessionKey = "health-guard-session";

type Snapshot = {
  dashboard: Dashboard;
  runs: AgentRun[];
  events: LedgerEvent[];
  transactions: TransactionActivity[];
  automationTimings: SupplyAutomationTiming[];
  at: number;
};

// Every sidebar link is its own Next route, so navigating unmounts this component and mounts it
// again from scratch. Without a cache outside React that meant a blank "Loading your care
// information…" and five fresh requests on every single page change. This survives the remount so
// a navigation paints immediately from memory.
let snapshot: Snapshot | null = null;
// Long enough to cover clicking through the sidebar, short enough that a change arriving during
// the brief window when SSE is disconnected mid-navigation cannot go unnoticed for long.
const SNAPSHOT_FRESH_MS = 3_000;
// Mandate approval happens on Prava's site; poll for the result, but give up after ~5 minutes.
const PENDING_SYNC_MS = 5_000;
const PENDING_SYNC_ATTEMPTS = 60;
const ACTIVE_SYNC_MS = 300_000;

export function HealthGuardApp({ page, heading }: { page: WorkspacePage; heading: { eyebrow: string; title: string; subtitle: string } }) {
  // Read on the client only, after mount. Reading sessionStorage in the initializer made the
  // server render the signed-out view while the client rendered the signed-in one, which React
  // reports as a hydration mismatch and then throws the whole tree away.
  const [session, setSession] = useState<Session | null>(null);
  const [restored, setRestored] = useState(false);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [transactions, setTransactions] = useState<TransactionActivity[]>([]);
  const [automationTimings, setAutomationTimings] = useState<SupplyAutomationTiming[]>([]);
  const [mode, setMode] = useState<"login" | "register">("register");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const refreshTimer = useRef<number | null>(null);

  const refresh = useCallback(async (activeSession: Session) => {
    const [nextDashboard, nextRuns, nextEvents, nextTransactions, nextAutomationTimings] = await Promise.all([
      api<Dashboard>("/setup/dashboard", activeSession.access_token),
      api<AgentRun[]>("/agent-runs", activeSession.access_token),
      api<LedgerEvent[]>("/ledger/events", activeSession.access_token),
      api<TransactionActivity[]>("/activity/transactions", activeSession.access_token),
      api<SupplyAutomationTiming[]>("/agent-runs/automation-timing", activeSession.access_token),
    ]);
    snapshot = {
      dashboard: nextDashboard,
      runs: nextRuns,
      events: nextEvents,
      transactions: nextTransactions,
      automationTimings: nextAutomationTimings,
      at: Date.now(),
    };
    setDashboard(nextDashboard);
    setRuns(nextRuns);
    setEvents(nextEvents);
    setTransactions(nextTransactions);
    setAutomationTimings(nextAutomationTimings);
  }, []);

  const applySnapshot = useCallback((cached: Snapshot) => {
    setDashboard(cached.dashboard);
    setRuns(cached.runs);
    setEvents(cached.events);
    setTransactions(cached.transactions);
    setAutomationTimings(cached.automationTimings);
  }, []);

  const endSession = useCallback(() => {
    window.sessionStorage.removeItem(sessionKey);
    snapshot = null;
    setSession(null);
    setDashboard(null);
    setRuns([]);
    setEvents([]);
    setTransactions([]);
    setAutomationTimings([]);
  }, []);

  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(sessionKey);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (raw) setSession(JSON.parse(raw) as Session);
       
      if (snapshot) applySnapshot(snapshot);
    } catch {
      // A corrupt stored session must not take the whole app down: drop it and show sign-in.
      window.sessionStorage.removeItem(sessionKey);
    }
    setRestored(true);
  }, [applySnapshot]);

  useEffect(() => {
    if (!session) return;
    // A navigation that happened moments ago is already showing current data, and SSE is watching
    // for changes, so re-fetching everything would only add latency to the page switch.
    if (snapshot && Date.now() - snapshot.at < SNAPSHOT_FRESH_MS) return;
    // Restored browser-session state is synchronized after mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh(session).catch((error) => {
      if (error instanceof ApiError && error.status === 401) {
        endSession();
        setNotice("Your session ended. Please sign in again.");
      } else setNotice("Health Guard could not load the latest information. It will try again.");
    });
  }, [endSession, refresh, session]);

  useEffect(() => {
    if (!session) return;
    const queueRefresh = () => {
      if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
      refreshTimer.current = window.setTimeout(() => void refresh(session).catch(() => undefined), 180);
    };
    const unsubscribe = subscribeToUpdates(session.access_token, queueRefresh, endSession);
    return () => {
      unsubscribe();
      if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    };
  }, [endSession, refresh, session]);

  const supplies = useMemo(() => dashboard?.beneficiaries.flatMap((beneficiary) => beneficiary.supplies) ?? [], [dashboard]);
  // Both of these MUST be stable strings, not arrays. A fresh array identity on every dashboard
  // update re-runs the effect below, which syncs, which refreshes, which produces a new dashboard —
  // an unbounded request loop that ignores the interval entirely.
  const pendingMandateKey = useMemo(
    () => dashboard?.merchant_authorizations.filter((item) => item.mandate_status === "pending").map((item) => item.id).sort().join(",") ?? "",
    [dashboard],
  );
  const activeMandateKey = useMemo(
    () => dashboard?.merchant_authorizations.filter((item) => item.mandate_status === "active").map((item) => item.id).sort().join(",") ?? "",
    [dashboard],
  );

  // A pending mandate is approved on Prava's own site, so its result is genuinely unobservable
  // here — this is the one case that warrants polling. It stops as soon as the mandate leaves
  // "pending", and gives up after PENDING_SYNC_ATTEMPTS so an abandoned approval cannot hammer
  // Prava forever. No refresh() call: the sync changes the database, and SSE delivers that.
  useEffect(() => {
    if (!session || !pendingMandateKey) return;
    const ids = pendingMandateKey.split(",");
    let stopped = false;
    let attempts = 0;
    const timer = window.setInterval(() => {
      if (stopped) return;
      if (++attempts > PENDING_SYNC_ATTEMPTS) { window.clearInterval(timer); return; }
      void Promise.all(ids.map((id) => api(`/mandates/${id}/sync`, session.access_token, { method: "POST" }).catch(() => undefined)));
    }, PENDING_SYNC_MS);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [pendingMandateKey, session]);

  // An active mandate only changes through our own charges (which sync before charging) or an
  // action taken in Prava's dashboard. A slow reconciliation is enough; the cap and remaining
  // balance shown here being a few minutes stale never affects a payment decision.
  useEffect(() => {
    if (!session || !activeMandateKey) return;
    const ids = activeMandateKey.split(",");
    let stopped = false;
    const timer = window.setInterval(() => {
      if (stopped) return;
      void Promise.all(ids.map((id) => api(`/mandates/${id}/sync`, session.access_token, { method: "POST" }).catch(() => undefined)));
    }, ACTIVE_SYNC_MS);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [activeMandateKey, session]);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setNotice("");
    try {
      const form = event.currentTarget;
      const body = mode === "register"
        ? { email: formValue(form, "email"), password: formValue(form, "password"), display_name: formValue(form, "name") || null }
        : { email: formValue(form, "email"), password: formValue(form, "password") };
      const nextSession = await api<Session>(`/auth/${mode === "register" ? "register" : "login"}`, undefined, { method: "POST", body: JSON.stringify(body) });
      window.sessionStorage.setItem(sessionKey, JSON.stringify(nextSession));
      setSession(nextSession); await refresh(nextSession); form.reset();
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not sign in"); }
    finally { setBusy(false); }
  }

  async function createSetup(event: FormEvent<HTMLFormElement>, path: string, body: object) {
    event.preventDefault(); if (!session) return;
    const form = event.currentTarget;
    setBusy(true); setNotice("");
    try { await api(path, session.access_token, { method: "POST", body: JSON.stringify(body) }); await refresh(session); form.reset(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not save this information"); }
    finally { setBusy(false); }
  }

  async function toggle(path: string, body: object) {
    if (!session) return;
    setBusy(true); setNotice("");
    try { await api(path, session.access_token, { method: "PATCH", body: JSON.stringify(body) }); await refresh(session); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not update this setting"); }
    finally { setBusy(false); }
  }

  async function startRun(supplyId: string) {
    if (!session) return;
    setBusy(true); setNotice("");
    try { await api(`/agent-runs/supplies/${supplyId}`, session.access_token, { method: "POST", body: JSON.stringify({ trigger_id: `manual:${crypto.randomUUID()}` }) }); await refresh(session); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not check this supply"); }
    finally { setBusy(false); }
  }

  async function signalRunningLow(supplyId: string) {
    if (!session) return;
    setBusy(true); setNotice("");
    try { await api(`/ledger/supplies/${supplyId}/running-low`, session.access_token, { method: "POST" }); await refresh(session); setNotice("Health Guard checked the supply using your existing product and payment limits."); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not check this supply"); }
    finally { setBusy(false); }
  }

  async function retryProductSetup(supplyId: string) {
    if (!session) return;
    setBusy(true); setNotice("");
    try { await api(`/setup/supplies/${supplyId}/auto-configure`, session.access_token, { method: "POST" }); await refresh(session); setNotice("Health Guard is checking approved merchant catalogs now."); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not restart the product check"); }
    finally { setBusy(false); }
  }

  async function deleteSupply(supplyId: string, supplyName: string) {
    if (!session || !window.confirm(`Delete ${supplyName}? Past payment transactions will remain in your history.`)) return;
    setBusy(true); setNotice("");
    try { await api<void>(`/setup/supplies/${supplyId}`, session.access_token, { method: "DELETE" }); await refresh(session); setNotice(`${supplyName} was removed from recurring supplies.`); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not delete this recurring supply"); }
    finally { setBusy(false); }
  }

  async function updateStock(supplyId: string, quantityOnHand: number) {
    if (!session) return;
    setBusy(true); setNotice("");
    try {
      await api(`/setup/supplies/${supplyId}/stock-count`, session.access_token, {
        method: "POST",
        body: JSON.stringify({ quantity_on_hand: quantityOnHand }),
      });
      await refresh(session);
      setNotice("Stock updated. The next automatic order time has been recalculated.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not update stock"); }
    finally { setBusy(false); }
  }

  async function testPayment(supplyId: string, supplyName: string) {
    if (!session || !window.confirm(`Run one sandbox payment test for ${supplyName}? This will use its active Prava mandate.`)) return;
    setBusy(true); setNotice("");
    try {
      const result = await api<{ run: AgentRun; reused: boolean }>(`/agent-runs/supplies/${supplyId}/test-payment`, session.access_token, { method: "POST", body: JSON.stringify({ confirmed: true, trigger_id: `payment-test:${crypto.randomUUID()}` }) });
      await refresh(session);
      setNotice(result.run.outcome === "purchased" ? "Order placed. The merchant accepted the payment — see Payment transactions." : result.run.outcome === "checkout_declined" ? "End-to-end flow completed: the one-time card reached the merchant and was declined, which is the expected sandbox result. No stock was added." : result.run.explanation ?? "The payment test finished without a charge.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not run the payment test"); }
    finally { setBusy(false); }
  }

  async function createMandate(authorizationId: string, body: object): Promise<MandateSetupSession> {
    if (!session) throw new Error("Please sign in again");
    setBusy(true); setNotice("");
    try {
      const result = await api<MandateSetupSession>(`/mandates/${authorizationId}/setup-session`, session.access_token, { method: "POST", body: JSON.stringify(body) });
      await refresh(session);
      return result;
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not create the secure Prava approval"); throw error; }
    finally { setBusy(false); }
  }

  async function mandateAction(authorizationId: string, action: "pause" | "resume" | "cancel") {
    if (!session) return;
    setBusy(true); setNotice("");
    try { await api(`/mandates/${authorizationId}/${action}`, session.access_token, { method: "POST", body: JSON.stringify({ confirmed: true }) }); await refresh(session); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not change this spending permission"); }
    finally { setBusy(false); }
  }

  const searchProducts = useCallback(async (query: string): Promise<ProductSuggestion[]> => {
    if (!session) return [];
    const parameters = new URLSearchParams({ query });
    return api<ProductSuggestion[]>(`/setup/product-suggestions?${parameters}`, session.access_token);
  }, [session]);

  async function signOut() {
    if (session) await api<void>("/auth/logout", session.access_token, { method: "POST" }).catch(() => undefined);
    endSession();
  }

  // Until the stored session has been read, render exactly what the server rendered.
  if (!restored) return <main className="auth-shell"><p className="muted">Loading Health Guard…</p></main>;
  if (!session) return <AuthPanel mode={mode} busy={busy} notice={notice} onModeChange={setMode} onSubmit={submitAuth} />;
  if (!dashboard) return <main className="auth-shell"><p className="muted">Loading your care information…</p>{notice && <p className="notice">{notice}</p>}</main>;

  const nav: Array<{ page: WorkspacePage; label: string; icon: string }> = [
    // Short labels: these sit in a phone-width tap target, and the page heading already carries
    // the long form. "Supplies" beats "Recurring supplies" wrapped onto three lines.
    { page: "dashboard", label: "Overview", icon: "⌂" },
    { page: "beneficiaries", label: "People", icon: "◎" },
    { page: "supplies", label: "Supplies", icon: "↻" },
    { page: "merchants", label: "Shops", icon: "◇" },
    { page: "mandates", label: "Limits", icon: "▣" },
    { page: "payment-test", label: "Test pay", icon: "▶" },
    { page: "transactions", label: "Payments", icon: "₹" },
    { page: "activity", label: "Activity", icon: "≡" },
  ];
  // The one step the user should do next — used to badge the sidebar so the path forward is
  // visible from any page, not just Overview.
  const steps = setupSteps(dashboard, transactions);
  const nextStep = steps.find((s) => s.warn) ?? steps.find((s) => !s.done && !s.blockedBy);

  const setup = page === "beneficiaries" || page === "supplies" || page === "merchants" ? <CareSetup view={page} dashboard={dashboard} automationTimings={automationTimings} busy={busy} onCreate={createSetup} onToggle={toggle} onRetryProductSetup={retryProductSetup} onDeleteSupply={deleteSupply} onUpdateStock={updateStock} onSearchProducts={searchProducts} /> : null;
  const content = page === "dashboard"
    ? <><SetupGuide dashboard={dashboard} transactions={transactions} /><DashboardOverview dashboard={dashboard} transactions={transactions} /><TrustPanel events={events} supplies={supplies} busy={busy} onRunningLow={signalRunningLow} /><AgentRunsPanel supplies={supplies} runs={runs} busy={busy} onStart={startRun} /></>
    : page === "mandates"
      ? <MandateControls authorizations={dashboard.merchant_authorizations} busy={busy} onSetup={createMandate} onAction={mandateAction} />
      : page === "payment-test"
        ? <PaymentTestPanel dashboard={dashboard} busy={busy} onTest={testPayment} />
      : page === "transactions"
        ? <TransactionsPanel transactions={transactions} />
        : page === "activity"
          ? <ActivityPanel events={events} />
        : setup;
  return <main className="workspace"><aside className="sidebar"><Link className="brand" href="/dashboard"><span className="brand-mark">H</span><span>Health Guard</span></Link><nav>{nav.map((item) => <Link key={item.page} className={`${page === item.page ? "nav-active" : ""} ${nextStep?.page === item.page ? "nav-next" : ""}`.trim()} href={`/${item.page}`} aria-label={nextStep?.page === item.page ? `${item.label} — next step` : undefined}><span className="nav-icon" aria-hidden>{item.icon}</span><span>{item.label}</span>{nextStep?.page === item.page && <span className="nav-dot" aria-hidden />}</Link>)}</nav><div className="sidebar-account"><span className="account-avatar">{session.user.email.slice(0, 1).toUpperCase()}</span><div><strong>{session.user.display_name ?? "Health Guard user"}</strong><span>{session.user.email}</span></div><button className="quiet" type="button" onClick={signOut}>Sign out</button></div></aside><section className="workspace-content"><header className="page-header"><p className="eyebrow">{heading.eyebrow}</p><h1>{heading.title}</h1><p>{heading.subtitle}</p></header>{notice && <p className="notice" role="status">{notice}</p>}{content}</section></main>;
}