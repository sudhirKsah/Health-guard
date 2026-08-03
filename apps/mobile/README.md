# Health Guard Android app

This Capacitor project packages the same Health Guard frontend as an Android app so daily medicine reminders can use native local notifications even after the app is closed.

## Build it

Use the deployed API URL when producing the mobile bundle. It is embedded in the static JavaScript; never use a secret here.

```bash
NEXT_PUBLIC_API_URL=https://your-api.example npm run build:mobile
npm run sync:android
npm run open:android
```

Open the Android project in Android Studio, then run it on a real Android device. Android 13+ asks the user for notification permission. Android may also ask the user to allow exact alarms; without it, the operating system can delay a reminder to save battery.

## Required reminder sound

Before making a release build, add the approved **WAV** recording named exactly `medicine_reminder.wav` here:

```
apps/mobile/android/app/src/main/res/raw/medicine_reminder.wav
```

Health Guard's Android alarm receiver plays this recording through the device's **alarm** audio stream; the notification channel is retained for the visible notification. A WAV file is used because it is portable across Android and a future iOS build.

The spoken recording should say: “It’s time to take your medicine.”
