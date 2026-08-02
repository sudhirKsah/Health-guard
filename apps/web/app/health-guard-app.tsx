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
import { TransactionsPanel } from "./components/transactions-panel";
import { TrustPanel } from "./components/trust-panel";
import { ApiError, api, formValue, subscribeToUpdates } from "./lib/api";
import type { AgentRun, Dashboard, LedgerEvent, MandateSetupSession, ProductSuggestion, Session, SupplyAutomationTiming, TransactionActivity } from "./lib/types";
import type { WorkspacePage } from "./workspace-page";

const sessionKey = "health-guard-session";

export function HealthGuardApp({ page, heading }: { page: WorkspacePage; heading: { eyebrow: string; title: string; subtitle: string } }) {
  // Keep the server's first render and the browser's hydration render identical. The stored
  // session is restored only after hydration, rather than being read during useState initialization.
  const [session, setSession] = useState<Session | null>(null);
  const [sessionRestored, setSessionRestored] = useState(false);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [transactions, setTransactions] = useState<TransactionActivity[]>([]);
  const [automationTimings, setAutomationTimings] = useState<SupplyAutomationTiming[]>([]);
  const [mode, setMode] = useState<"login" | "register">("register");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const refreshTimer = useRef<number | null>(null);

  useEffect(() => {
    const restoreSession = window.setTimeout(() => {
      try {
        const raw = window.sessionStorage.getItem(sessionKey);
        setSession(raw ? (JSON.parse(raw) as Session) : null);
      } catch {
        window.sessionStorage.removeItem(sessionKey);
      } finally {
        setSessionRestored(true);
      }
    }, 0);
    return () => window.clearTimeout(restoreSession);
  }, []);

  const refresh = useCallback(async (activeSession: Session) => {
    const [nextDashboard, nextRuns, nextEvents, nextTransactions, nextAutomationTimings] = await Promise.all([
      api<Dashboard>("/setup/dashboard", activeSession.access_token),
      api<AgentRun[]>("/agent-runs", activeSession.access_token),
      api<LedgerEvent[]>("/ledger/events", activeSession.access_token),
      api<TransactionActivity[]>("/activity/transactions", activeSession.access_token),
      api<SupplyAutomationTiming[]>("/agent-runs/automation-timing", activeSession.access_token),
    ]);
    setDashboard(nextDashboard);
    setRuns(nextRuns);
    setEvents(nextEvents);
    setTransactions(nextTransactions);
    setAutomationTimings(nextAutomationTimings);
  }, []);

  const endSession = useCallback(() => {
    window.sessionStorage.removeItem(sessionKey);
    setSession(null);
    setDashboard(null);
    setRuns([]);
    setEvents([]);
    setTransactions([]);
    setAutomationTimings([]);
  }, []);

  useEffect(() => {
    if (!session) return;
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
  const pendingMandateKey = useMemo(
    () => dashboard?.merchant_authorizations
      .filter((item) => item.mandate_status === "pending")
      .map((item) => item.id)
      .sort()
      .join(",") ?? "",
    [dashboard],
  );
  const activeMandateKey = useMemo(
    () => dashboard?.merchant_authorizations.filter((item) => item.mandate_status === "active").map((item) => item.id).sort().join(",") ?? "",
    [dashboard],
  );

  useEffect(() => {
    if (!session || !pendingMandateKey) return;
    const pendingMandateIds = pendingMandateKey.split(",");
    let stopped = false;
    let syncing = false;
    const syncPending = async () => {
      if (syncing || stopped) return;
      syncing = true;
      try {
        await Promise.all(pendingMandateIds.map((id) => api(`/mandates/${id}/sync`, session.access_token, { method: "POST" }).catch(() => undefined)));
        // The authenticated SSE stream refreshes the dashboard after the sync changes a mandate.
        // Calling refresh here as well created a feedback loop of five additional requests.
      } finally {
        syncing = false;
      }
    };
    void syncPending();
    const timer = window.setInterval(() => void syncPending(), 10_000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [pendingMandateKey, session]);

  useEffect(() => {
    if (!session || !activeMandateKey) return;
    const activeIds = activeMandateKey.split(",");
    let stopped = false;
    const syncActive = async () => {
      if (stopped) return;
      await Promise.all(activeIds.map((id) => api(`/mandates/${id}/sync`, session.access_token, { method: "POST" }).catch(() => undefined)));
      // The SSE stream delivers the resulting dashboard refresh.
    };
    void syncActive();
    const timer = window.setInterval(() => void syncActive(), 5 * 60_000);
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
      setNotice(result.run.outcome === "sandbox_settled" ? "Payment test approved. The transaction is now visible in Payment transactions." : result.run.explanation ?? "The payment test finished without a charge.");
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
    const activeSession = session;
    // Clear the browser session immediately. This closes the realtime stream and prevents the
    // workspace from issuing further authenticated refreshes while logout is in flight.
    endSession();
    if (activeSession) {
      await api<void>("/auth/logout", activeSession.access_token, { method: "POST" }).catch(() => undefined);
    }
  }

  if (!sessionRestored) return <main className="auth-shell"><p className="muted">Loading Health Guard…</p></main>;
  if (!session) return <AuthPanel mode={mode} busy={busy} notice={notice} onModeChange={setMode} onSubmit={submitAuth} />;
  if (!dashboard) return <main className="auth-shell"><p className="muted">Loading your care information…</p>{notice && <p className="notice">{notice}</p>}</main>;

  const nav: Array<{ page: WorkspacePage; label: string; icon: string }> = [
    { page: "dashboard", label: "Overview", icon: "⌂" },
    { page: "beneficiaries", label: "Beneficiaries", icon: "◎" },
    { page: "supplies", label: "Recurring supplies", icon: "↻" },
    { page: "merchants", label: "Merchants", icon: "◇" },
    { page: "mandates", label: "Mandates", icon: "▣" },
    { page: "payment-test", label: "Test recurring payment", icon: "▶" },
    { page: "transactions", label: "Payment transactions", icon: "₹" },
    { page: "activity", label: "Activity", icon: "≡" },
  ];
  const setup = page === "beneficiaries" || page === "supplies" || page === "merchants" ? <CareSetup view={page} dashboard={dashboard} automationTimings={automationTimings} busy={busy} onCreate={createSetup} onToggle={toggle} onRetryProductSetup={retryProductSetup} onDeleteSupply={deleteSupply} onUpdateStock={updateStock} onSearchProducts={searchProducts} /> : null;
  const content = page === "dashboard"
    ? <><DashboardOverview dashboard={dashboard} transactions={transactions} /><TrustPanel events={events} supplies={supplies} busy={busy} onRunningLow={signalRunningLow} /><AgentRunsPanel supplies={supplies} runs={runs} busy={busy} onStart={startRun} /></>
    : page === "mandates"
      ? <MandateControls authorizations={dashboard.merchant_authorizations} busy={busy} onSetup={createMandate} onAction={mandateAction} />
      : page === "payment-test"
        ? <PaymentTestPanel dashboard={dashboard} busy={busy} onTest={testPayment} />
      : page === "transactions"
        ? <TransactionsPanel transactions={transactions} />
        : page === "activity"
          ? <ActivityPanel events={events} />
        : setup;
  return <main className="workspace"><aside className="sidebar"><Link className="brand" href="/dashboard"><span className="brand-mark">H</span><span>Health Guard</span></Link><nav>{nav.map((item) => <Link key={item.page} className={page === item.page ? "nav-active" : ""} href={`/${item.page}`}><span className="nav-icon" aria-hidden>{item.icon}</span><span>{item.label}</span></Link>)}</nav><div className="sidebar-account"><span className="account-avatar">{session.user.email.slice(0, 1).toUpperCase()}</span><div><strong>{session.user.display_name ?? "Health Guard user"}</strong><span>{session.user.email}</span></div><button className="quiet" type="button" onClick={signOut}>Sign out</button></div></aside><section className="workspace-content"><header className="page-header"><p className="eyebrow">{heading.eyebrow}</p><h1>{heading.title}</h1><p>{heading.subtitle}</p></header>{notice && <p className="notice" role="status">{notice}</p>}{content}</section></main>;
}
