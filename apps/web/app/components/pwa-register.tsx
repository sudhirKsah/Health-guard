"use client";

import { useEffect, useState } from "react";
import { Capacitor } from "@capacitor/core";

type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export function PwaRegister() {
  const [installPrompt, setInstallPrompt] = useState<InstallPromptEvent | null>(null);

  useEffect(() => {
    if (
      Capacitor.isNativePlatform()
      || process.env.NODE_ENV !== "production"
      || !("serviceWorker" in navigator)
    ) return;

    void navigator.serviceWorker.register("/sw.js", { scope: "/" });
    const onBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as InstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
  }, []);

  async function install() {
    if (!installPrompt) return;
    await installPrompt.prompt();
    await installPrompt.userChoice;
    setInstallPrompt(null);
  }

  if (!installPrompt) return null;
  return (
    <button className="install-app" type="button" onClick={() => void install()}>
      Install Health Guard
    </button>
  );
}
