"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { AgentRunsPanel } from "./components/agent-runs-panel";
import { AuthPanel } from "./components/auth-panel";
import { CareSetup } from "./components/care-setup";
import { MandateControls } from "./components/mandate-controls";
import { api, formValue } from "./lib/api";
import type { AgentRun, Dashboard, MandateSetupSession, Session } from "./lib/types";

const sessionKey = "health-guard-session";

export function HealthGuardApp() {
  const [session, setSession] = useState<Session | null>(() => {
    if (typeof window === "undefined") return null;
    const raw = window.sessionStorage.getItem(sessionKey);
    return raw ? (JSON.parse(raw) as Session) : null;
  });
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [mode, setMode] = useState<"login" | "register">("register");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async (activeSession: Session) => {
    const [nextDashboard, nextRuns] = await Promise.all([
      api<Dashboard>("/setup/dashboard", activeSession.access_token),
      api<AgentRun[]>("/agent-runs", activeSession.access_token),
    ]);
    setDashboard(nextDashboard);
    setRuns(nextRuns);
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

  return <main className="dashboard-shell"><header className="topbar"><div><p className="eyebrow">Health Guard</p><h1>Your care setup</h1></div><div className="account"><span>{session.user.email}</span><button className="quiet" type="button" onClick={signOut}>Sign out</button></div></header><p className="intro">The Replenishment Agent works only from declared inventory, exact product approvals, and active merchant mandates. It never invents an offer, bypasses a cap, or sees payment credentials.</p>{notice && <p className="notice" role="status">{notice}</p>}<AgentRunsPanel supplies={supplies} runs={runs} busy={busy} onStart={startRun} onSchedule={scheduleRun} /><CareSetup dashboard={dashboard} busy={busy} onCreate={createSetup} onToggle={toggle} /><MandateControls authorizations={dashboard.merchant_authorizations} busy={busy} onSetup={createMandate} onSync={syncMandate} onAction={mandateAction} /></main>;
}
