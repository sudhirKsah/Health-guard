import { NextResponse } from "next/server";

const profile = {
  ucp: {
    version: "2026-04-08",
    capabilities: {
      "dev.ucp.shopping.cart": [{ version: "2026-04-08" }],
      "dev.ucp.shopping.checkout": [{ version: "2026-04-08" }],
    },
  },
};

export function GET() {
  return NextResponse.json(profile, {
    headers: {
      "Cache-Control": "public, max-age=300",
    },
  });
}
