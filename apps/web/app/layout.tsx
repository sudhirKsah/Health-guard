import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Health Guard",
  description: "A bounded agent for recurring OTC care supplies.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
