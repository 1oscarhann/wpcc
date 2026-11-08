// Cloudflare Pages (optional, D-123): serve the static build from Pages and proxy /api and /ws to the API,
// so the browser still sees one origin (Safari keeps the session cookie, PLAN B2).
// Set API_ORIGIN in the Pages project (e.g. https://hearthforge.onrender.com).
interface Env {
  API_ORIGIN: string;
}

export const onRequest = async (ctx: { request: Request; env: Env; next: () => Promise<Response> }): Promise<Response> => {
  const url = new URL(ctx.request.url);
  if (!url.pathname.startsWith("/api/") && url.pathname !== "/ws") return ctx.next();
  const target = new URL(url.pathname + url.search, ctx.env.API_ORIGIN);
  // websockets pass straight through: fetch() keeps the Upgrade header and returns the 101
  return fetch(new Request(target.toString(), ctx.request));
};
