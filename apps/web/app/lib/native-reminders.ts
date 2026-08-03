import { Capacitor } from "@capacitor/core";
import { LocalNotifications } from "@capacitor/local-notifications";

import type { MedicationReminder, Supply } from "./types";
import { syncNativeMedicineAlarmPlayback } from "./native-medicine-alarm";

// Android channel audio is unreliable on some MIUI devices even when the channel is configured
// correctly. Android uses a native alarm receiver for sound; this channel remains for the visible
// notification only.
const CHANNEL_ID = "medicine-reminders-v3";

function nativeNotificationId(reminderId: string): number {
  let value = 0;
  for (const character of reminderId) value = (value * 31 + character.charCodeAt(0)) | 0;
  return Math.abs(value) || 1;
}

function dailyClockTime(timeOfDay: string): { hour: number; minute: number } {
  const [hours, minutes] = timeOfDay.split(":").map(Number);
  return { hour: hours, minute: minutes };
}

export function isNativeHealthGuardApp(): boolean {
  return Capacitor.isNativePlatform();
}

export async function syncNativeMedicineReminders(
  reminders: MedicationReminder[],
  supplies: Supply[],
): Promise<void> {
  if (!isNativeHealthGuardApp()) return;

  const supplyById = new Map(supplies.map((supply) => [supply.id, supply]));
  const enabled = reminders.filter((reminder) => reminder.enabled && supplyById.has(reminder.supply_id));

  // Clearing or disabling a reminder should not make Android ask for notification permission.
  // Cancel any Health Guard schedules first, then leave when there is nothing to recreate.
  const pending = await LocalNotifications.getPending();
  const existing = pending.notifications.filter(
    (notification) => (notification.extra as { health_guard_reminder?: boolean } | undefined)?.health_guard_reminder,
  );
  if (existing.length) await LocalNotifications.cancel({ notifications: existing.map(({ id }) => ({ id })) });
  if (!enabled.length) {
    await syncNativeMedicineAlarmPlayback([]);
    return;
  }

  const permission = await LocalNotifications.checkPermissions();
  const display = permission.display === "granted"
    ? permission
    : await LocalNotifications.requestPermissions();
  if (display.display !== "granted") throw new Error("Allow notifications to enable medicine reminders.");

  // Android 8+ assigns notification sounds to channels. iOS does not expose
  // Android notification channels, so attempting this there would fail.
  if (Capacitor.getPlatform() === "android") {
    const exactAlarm = await LocalNotifications.checkExactNotificationSetting();
    if (exactAlarm.exact_alarm !== "granted") {
      const result = await LocalNotifications.changeExactNotificationSetting();
      if (result.exact_alarm !== "granted") {
        throw new Error("Allow Alarms & reminders in Android settings to use the selected daily time.");
      }
    }
    await LocalNotifications.createChannel({
      id: CHANNEL_ID,
      name: "Medicine reminders",
      description: "Daily Health Guard medicine reminders",
      importance: 5,
      vibration: true,
    });
  }

  await LocalNotifications.schedule({
    notifications: enabled.map((reminder) => {
      const supply = supplyById.get(reminder.supply_id)!;
      return {
        id: nativeNotificationId(reminder.id),
        title: "Time to take your medicine",
        body: `It’s time to take ${supply.name}.`,
        channelId: CHANNEL_ID,
        // Do not use `at` + `repeats`: Android treats the time between now and the first
        // occurrence as the repeat interval (e.g. a 2-minute test becomes every 2 minutes).
        // `on` is Capacitor's cron-style schedule and reschedules itself for the same time daily.
        schedule: { on: dailyClockTime(reminder.time_of_day), allowWhileIdle: true },
        extra: { health_guard_reminder: true, reminder_id: reminder.id, supply_id: supply.id },
      };
    }),
  });

  await syncNativeMedicineAlarmPlayback(
    enabled.map((reminder) => ({
      id: nativeNotificationId(reminder.id),
      ...dailyClockTime(reminder.time_of_day),
    })),
  );
}
