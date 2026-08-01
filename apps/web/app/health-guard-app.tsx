"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { AgentRunsPanel } from "./components/agent-runs-panel";
import { AuthPanel } from "./components/auth-panel";
import { CareSetup } from "./components/care-setup";
import { MandateControls } from "./components/mandate-controls";
import { TrustPanel } from "./components/trust-panel";
import { api, formValue } from "./lib/api";
import type { AgentRun, Dashboard, LedgerEvent, MandateSetupSession, Session } from "./lib/types";
import type { WorkspacePage } from "./workspace-page";

const sessionKey = "health-guard-session";

export function HealthGuardApp({ page, heading }: { page: WorkspacePage; heading: { eyebrow: string; title: string; subtitle: string } }) {
  const [session, setSession] = useState<Session | null>(() => {
    if (typeof window === "undefined") return null;
    const raw = window.sessionStorage.getItem(sessionKey);
    return raw ? (JSON.parse(raw) as Session) : null;
  });
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [mode, setMode] = useState<"login" | "register">("register");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async (activeSession: Session) => {
    const [nextDashboard, nextRuns, nextEvents] = await Promise.all([
      api<Dashboard>("/setup/dashboard", activeSession.access_token),
      api<AgentRun[]>("/agent-runs", activeSession.access_token),
      api<LedgerEvent[]>("/ledger/events", activeSession.access_token),
    ]);
    setDashboard(nextDashboard);
    setRuns(nextRuns);
    setEvents(nextEvents);
  }, []);

  useEffect(() => {
    if (!session) return;
    // Restored browser-session state must be synchronized with the backend before rendering care data.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh(session).catch(() => {
      window.sessionStorage.removeItem(sessionKey);
      setSession(null);
      setNotice("Your session ended. Please sign in again.");
    });
  }, [refresh, session]);

  const supplies = useMemo(
    () => dashboard?.beneficiaries.flatMap((beneficiary) => beneficiary.supplies) ?? [],
    [dashboard],
  );

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
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not authenticate"); }
    finally { setBusy(false); }
  }

  async function createSetup(event: FormEvent<HTMLFormElement>, path: string, body: object) {
    event.preventDefault(); if (!session) return;
    setBusy(true); setNotice("");
    try { await api(path, session.access_token, { method: "POST", body: JSON.stringify(body) }); await refresh(session); event.currentTarget.reset(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not save this setup step"); }
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
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not start the agent"); }
    finally { setBusy(false); }
  }

  async function signalRunningLow(supplyId: string) {
    if (!session) return;
    setBusy(true); setNotice("");
    try { await api(`/ledger/supplies/${supplyId}/running-low`, session.access_token, { method: "POST" }); await refresh(session); setNotice("Low-supply signal recorded. The agent evaluated it under the existing limits."); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not record the low-supply signal"); }
    finally { setBusy(false); }
  }

  async function scheduleRun(supplyId: string, runAt: Date) {
    if (!session) return;
    setBusy(true); setNotice("");
    try {
      const scheduled = await api<{ run_at: string }>(`/agent-runs/supplies/${supplyId}/schedule`, session.access_token, { method: "POST", body: JSON.stringify({ run_at: runAt.toISOString() }) });
      setNotice(`Agent evaluation scheduled for ${new Date(scheduled.run_at).toLocaleString()}.`);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not schedule the agent"); }
    finally { setBusy(false); }
  }

  async function createMandate(authorizationId: string, body: object): Promise<MandateSetupSession> {
    if (!session) throw new Error("Please sign in again");
    setBusy(true); setNotice("");
    try {
      const result = await api<MandateSetupSession>(`/mandates/${authorizationId}/setup-session`, session.access_token, { method: "POST", body: JSON.stringify(body) });
      await refresh(session);
      return result;
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not create the Prava approval session"); throw error; }
    finally { setBusy(false); }
  }

  async function syncMandate(authorizationId: string) {
    if (!session) return;
    setBusy(true); setNotice("");
    try { await api(`/mandates/${authorizationId}/sync`, session.access_token, { method: "POST" }); await refresh(session); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not sync Prava mandate status"); }
    finally { setBusy(false); }
  }

  async function mandateAction(authorizationId: string, action: "pause" | "resume" | "cancel") {
    if (!session) return;
    setBusy(true); setNotice("");
    try { await api(`/mandates/${authorizationId}/${action}`, session.access_token, { method: "POST", body: JSON.stringify({ confirmed: true }) }); await refresh(session); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Could not change the Prava mandate"); }
    finally { setBusy(false); }
  }

  async function signOut() {
    if (session) await api<void>("/auth/logout", session.access_token, { method: "POST" }).catch(() => undefined);
    window.sessionStorage.removeItem(sessionKey); setSession(null); setDashboard(null); setRuns([]);
  }

  if (!session) return <AuthPanel mode={mode} busy={busy} notice={notice} onModeChange={setMode} onSubmit={submitAuth} />;
  if (!dashboard) return <main className="auth-shell"><p className="muted">Loading your private care setup…</p>{notice && <p className="notice">{notice}</p>}</main>;

  const nav: Array<[WorkspacePage, string]> = [["dashboard", "Overview"], ["caregivers", "Caregivers"], ["beneficiaries", "Beneficiaries"], ["supplies", "Supplies"], ["mandates", "Mandates"], ["transactions", "Transactions"], ["history", "History"], ["notifications", "Notifications"], ["settings", "Settings"]];
  const route = (item: WorkspacePage) => `/${item}`;
  const setup = <CareSetup dashboard={dashboard} busy={busy} onCreate={createSetup} onToggle={toggle} />;
  const content = page === "dashboard" ? <><TrustPanel events={events} supplies={supplies} busy={busy} onRunningLow={signalRunningLow} /><AgentRunsPanel supplies={supplies} runs={runs} busy={busy} onStart={startRun} onSchedule={scheduleRun} /></> : page === "mandates" ? <MandateControls authorizations={dashboard.merchant_authorizations} busy={busy} onSetup={createMandate} onSync={syncMandate} onAction={mandateAction} /> : page === "notifications" ? <TrustPanel events={events} supplies={supplies} busy={busy} onRunningLow={signalRunningLow} /> : page === "history" || page === "transactions" ? <AgentRunsPanel supplies={supplies} runs={runs} busy={busy} onStart={startRun} onSchedule={scheduleRun} /> : setup;
  return <main className="workspace"><aside className="sidebar"><Link className="brand" href="/">Health Guard</Link><nav>{nav.map(([item, label]) => <Link key={item} className={page === item ? "nav-active" : ""} href={route(item)}>{label}</Link>)}</nav><div className="sidebar-account"><span>{session.user.email}</span><button className="quiet" type="button" onClick={signOut}>Sign out</button></div></aside><section className="workspace-content"><header className="page-header"><p className="eyebrow">{heading.eyebrow}</p><h1>{heading.title}</h1><p>{heading.subtitle}</p></header>{notice && <p className="notice" role="status">{notice}</p>}{content}</section></main>;
}
