// Tiny fetch wrapper: same-origin cookies, CSRF header on mutations, typed JSON errors.
// Every mutation carries an Idempotency-Key (PROTOCOL §5). If the network drops mid-request we retry
// once with the SAME key: the server either replays the stored answer or runs it for the first time,
// so a lost response can never charge, sell or buy twice.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

let csrfToken: string | null = null;

export function setCsrf(token: string | null): void {
  csrfToken = token;
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

export function newKey(): string {
  const c: Crypto | undefined = typeof crypto !== "undefined" ? crypto : undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  const b = new Uint8Array(16);
  if (c) c.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function api<T>(path: string, init: { method?: string; body?: unknown; key?: string } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (init.body !== undefined) headers["content-type"] = "application/json";
  const mutation = method !== "GET";
  if (mutation) {
    const token = csrfToken ?? readCookie("hf_csrf");
    if (token) headers["x-csrf-token"] = token;
    headers["idempotency-key"] = init.key ?? newKey();
  }
  let res: Response | null = null;
  for (let attempt = 0; attempt < (mutation ? 2 : 1) && !res; attempt++) {
    try {
      res = await fetch(path, {
        method,
        headers,
        credentials: "same-origin",
        body: init.body === undefined ? undefined : JSON.stringify(init.body),
      });
    } catch {
      if (attempt === 0 && mutation) await sleep(700);
    }
  }
  if (!res) throw new ApiError(0, "network", "Can't reach the server. Check your connection.");
  if (res.status === 304) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? "error", err.message ?? "Something went wrong.", err.details);
  }
  return data as T;
}
