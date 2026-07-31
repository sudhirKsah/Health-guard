"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { AgentRunsPanel } from "./components/agent-runs-panel";
import { AuthPanel } from "./components/auth-panel";
import { CareSetup } from "./components/care-setup";
import { api, formValue } from "./lib/api";
import type { AgentRun, Dashboard, Session } from "./lib/types";

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

  async function signOut() {
    if (session) await api<void>("/auth/logout", session.access_token, { method: "POST" }).catch(() => undefined);
    window.sessionStorage.removeItem(sessionKey); setSession(null); setDashboard(null); setRuns([]);
  }

  if (!session) return <AuthPanel mode={mode} busy={busy} notice={notice} onModeChange={setMode} onSubmit={submitAuth} />;
  if (!dashboard) return <main className="auth-shell"><p className="muted">Loading your private care setup…</p>{notice && <p className="notice">{notice}</p>}</main>;

  return <main className="dashboard-shell"><header className="topbar"><div><p className="eyebrow">Health Guard</p><h1>Your care setup</h1></div><div className="account"><span>{session.user.email}</span><button className="quiet" type="button" onClick={signOut}>Sign out</button></div></header><p className="intro">The agent only observes declared inventory and exact product approvals. Until live UCP discovery is connected, it will safely wait or block—never invent an offer or attempt a payment.</p>{notice && <p className="notice" role="status">{notice}</p>}<AgentRunsPanel supplies={supplies} runs={runs} busy={busy} onStart={startRun} /><CareSetup dashboard={dashboard} busy={busy} onCreate={createSetup} onToggle={toggle} /></main>;
}
