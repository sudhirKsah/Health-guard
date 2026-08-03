"use client";

import { FormEvent } from "react";

import type { Dashboard, MedicationReminder } from "../lib/types";
import { isNativeHealthGuardApp } from "../lib/native-reminders";

type Props = {
  dashboard: Dashboard;
  reminders: MedicationReminder[];
  busy: boolean;
  onCreate: (payload: { supply_id: string; enabled: boolean; time_of_day: string; timezone: string }) => Promise<void>;
  onUpdate: (id: string, payload: { enabled?: boolean; time_of_day?: string; timezone?: string }) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
};

function localTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function ReminderSettings({ dashboard, reminders, busy, onCreate, onUpdate, onDelete }: Props) {
  const supplies = dashboard.beneficiaries.flatMap((beneficiary) => beneficiary.supplies.map((supply) => ({ supply, beneficiary })));
  const supplyById = new Map(supplies.map((item) => [item.supply.id, item]));
  const unconfigured = supplies.filter((item) => !reminders.some((reminder) => reminder.supply_id === item.supply.id));
  const native = isNativeHealthGuardApp();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await onCreate({
      supply_id: String(form.get("supply_id")),
      enabled: true,
      time_of_day: String(form.get("time_of_day")),
      timezone: localTimezone(),
    });
    event.currentTarget.reset();
  }

  return <section className="stack page-section">
    <div className="plain-heading"><h2>Daily medicine reminders</h2><p>Choose a time for each supply. On the Android app, Health Guard schedules a native alert that can play even when the app is closed.</p></div>
    {!native && <p className="notice">Install the Android app to receive dependable closed-app alarms. The web app saves these preferences but cannot play a background alarm.</p>}
    {unconfigured.length > 0 && <form className="card reminder-form" onSubmit={(event) => void submit(event)}><label>Medicine<select name="supply_id" required defaultValue=""><option value="" disabled>Select a supply</option>{unconfigured.map(({ supply, beneficiary }) => <option key={supply.id} value={supply.id}>{supply.name} · {beneficiary.name}</option>)}</select></label><label>Daily reminder time<input name="time_of_day" type="time" required defaultValue="08:00" /></label><button disabled={busy}>Enable daily reminder</button></form>}
    <div className="stack">{reminders.map((reminder) => {
      const item = supplyById.get(reminder.supply_id);
      if (!item) return null;
      return <article className="card reminder-row" key={reminder.id}><div><strong>{item.supply.name}</strong><small>For {item.beneficiary.name} · every day at {reminder.time_of_day} ({reminder.timezone})</small></div><label className="reminder-time">Time<input type="time" value={reminder.time_of_day} disabled={busy} onChange={(event) => void onUpdate(reminder.id, { time_of_day: event.target.value, timezone: localTimezone() })} /></label><button className="quiet" disabled={busy} onClick={() => void onUpdate(reminder.id, { enabled: !reminder.enabled })}>{reminder.enabled ? "Enabled" : "Disabled"}</button><button className="danger-outline" disabled={busy} onClick={() => void onDelete(reminder.id)}>Remove</button></article>;
    })}{!reminders.length && <p className="empty-state">No medicine reminders yet.</p>}</div>
  </section>;
}
