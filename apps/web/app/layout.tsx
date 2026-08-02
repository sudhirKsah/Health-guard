import type { Metadata } from "next";
import { PwaRegister } from "./components/pwa-register";
import "./globals.css";

export const metadata: Metadata = {
  title: "Health Guard",
  description: "A bounded agent for recurring OTC care supplies.",
  applicationName: "Health Guard",
  manifest: "/manifest.webmanifest",
  themeColor: "#195337",
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
    <html lang="en">
      <body>
        {children}
        <PwaRegister />
      </body>
    </html>
  );
}
