import type { Metadata, Viewport } from "next";
import { PwaRegister } from "./components/pwa-register";
import "./globals.css";

// themeColor belongs in `viewport`, not `metadata` — Next stopped emitting it from metadata, so
// the PWA/browser-chrome colour was silently absent from the served HTML. Zoom is deliberately
// left unrestricted: capping it is an accessibility failure for the readers this app is built for.
export const viewport: Viewport = {
  themeColor: "#1b4d3e",
  width: "device-width",
  initialScale: 1,
};

export const metadata: Metadata = {
  title: "Health Guard",
  description: "A bounded agent for recurring OTC care supplies.",
  applicationName: "Health Guard",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Health Guard",
  },
  icons: {
    icon: "/icons/icon-512.png",
    apple: "/icons/apple-touch-icon.png",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // Browser extensions mutate <html>/<body> before React hydrates (adding class="hidden",
    // Grammarly attributes, dark-mode shims). suppressHydrationWarning applies to THIS element's
    // own attributes only — one level deep, never its descendants — so genuine mismatches inside
    // the app are still reported.
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        {children}
        <PwaRegister />
      </body>
    </html>
  );
}
