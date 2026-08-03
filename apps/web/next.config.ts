import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Vercel keeps its normal Next.js build. Capacitor needs a self-contained static web bundle.
  output: process.env.CAPACITOR_BUILD === "1" ? "export" : undefined,
};

export default nextConfig;
