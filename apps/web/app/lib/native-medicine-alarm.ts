import { Capacitor, registerPlugin } from "@capacitor/core";

type MedicineAlarm = { id: number; hour: number; minute: number };

type MedicineAlarmPlugin = {
  sync(options: { reminders: MedicineAlarm[] }): Promise<void>;
};

const NativeMedicineAlarm = registerPlugin<MedicineAlarmPlugin>("MedicineAlarm");

/**
 * Android-only audible playback for the daily reminder. The visible notification continues to be
 * managed by Capacitor; this receiver uses the alarm stream because some MIUI builds suppress
 * notification-channel audio despite a registered sound and full notification volume.
 */
export async function syncNativeMedicineAlarmPlayback(reminders: MedicineAlarm[]): Promise<void> {
  if (Capacitor.getPlatform() !== "android") return;
  await NativeMedicineAlarm.sync({ reminders });
}
