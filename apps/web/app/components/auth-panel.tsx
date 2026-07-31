"use client";

import { FormEvent } from "react";

type Props = {
  mode: "login" | "register";
  busy: boolean;
  notice: string;
  onModeChange: (mode: "login" | "register") => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function AuthPanel({ mode, busy, notice, onModeChange, onSubmit }: Props) {
  return (
    <main className="auth-shell">
      <p className="eyebrow">Health Guard</p>
      <h1>Care supplies, set up once.</h1>
      <p className="intro">Create a private caregiver account to configure real care inventory and strict product rules.</p>
      <form className="card stack" onSubmit={onSubmit}>
        <div className="tab-row" aria-label="Authentication mode">
          <button className={mode === "register" ? "active" : "quiet"} type="button" onClick={() => onModeChange("register")}>Create account</button>
          <button className={mode === "login" ? "active" : "quiet"} type="button" onClick={() => onModeChange("login")}>Sign in</button>
        </div>
        {mode === "register" && <label>Name <input name="name" autoComplete="name" maxLength={120} /></label>}
        <label>Email <input name="email" type="email" autoComplete="email" required /></label>
        <label>Password <input name="password" type="password" autoComplete={mode === "register" ? "new-password" : "current-password"} minLength={mode === "register" ? 12 : 1} required /></label>
        {mode === "register" && <p className="hint">Use at least 12 characters. Passwords are salted and hashed; Health Guard never stores them in plain text.</p>}
        <button type="submit" disabled={busy}>{busy ? "Working…" : mode === "register" ? "Create account" : "Sign in"}</button>
      </form>
      {notice && <p className="notice" role="status">{notice}</p>}
    </main>
  );
}
