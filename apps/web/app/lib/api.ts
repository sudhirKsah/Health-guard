const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function api<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}/api/v1${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(body?.detail ?? `Request failed (${response.status})`, response.status);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export function subscribeToUpdates(
  token: string,
  onRefresh: () => void,
  onUnauthorized: () => void,
): () => void {
  let stopped = false;
  let controller: AbortController | null = null;

  const connect = async () => {
    while (!stopped) {
      controller = new AbortController();
      try {
        const response = await fetch(`${apiBaseUrl}/api/v1/events/stream`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
          signal: controller.signal,
        });
        if (response.status === 401) {
          onUnauthorized();
          return;
        }
        if (!response.ok || !response.body) throw new Error("Live updates unavailable");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!stopped) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
          const blocks = buffer.split("\n\n");
          buffer = blocks.pop() ?? "";
          for (const block of blocks) {
            if (block.split("\n").some((line) => line.trim() === "event: refresh")) onRefresh();
          }
        }
      } catch (error) {
        if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  };
  void connect();
  return () => {
    stopped = true;
    controller?.abort();
  };
}

export function formValue(form: HTMLFormElement, field: string): string {
  return String(new FormData(form).get(field) ?? "").trim();
}
