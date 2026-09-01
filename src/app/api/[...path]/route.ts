/**
 * Catch-all API proxy: forwards every /api/* request to the Python
 * save-parser backend (mini-services/save-parser/server.py).
 *
 * Why this exists:
 *   The frontend calls relative URLs like `/api/upload?XTransformPort=3001`.
 *   - On the hosting platform, the edge gateway intercepts requests carrying
 *     the XTransformPort param and routes them straight to the backend port.
 *   - On a LOCAL deployment (pnpm dev + python server.py) there is no such
 *     gateway, so the request lands on the Next.js server, which previously
 *     had no /api routes at all -> the infamous
 *     "POST /api/upload?XTransformPort=3001 404" error.
 *
 *   This route closes that gap: Next.js itself proxies /api/* to the backend,
 *   so local and hosted deployments behave identically.
 *
 * Routing priority for the backend port:
 *   1. XTransformPort query param (same convention as the platform gateway,
 *      digits only - safe, host is always 127.0.0.1)
 *   2. BACKEND_PORT env var (read at request time, so dev-mode changes work)
 *   3. default 3001
 *   BACKEND_URL env var overrides the whole base URL if set.
 *
 * Alternatives that keep working:
 *   - NEXT_PUBLIC_API_URL: the frontend bypasses this proxy entirely and
 *     calls the backend directly (see src/lib/save-api.ts).
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Hop-by-hop / connection-managed headers must never be forwarded.
// "expect" (curl sends it for bodies >1MB as `Expect: 100-continue`) is
// rejected by Node's undici fetch -> always strip it.
const REQUEST_STRIP = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "accept-encoding",
  "keep-alive",
  "upgrade",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailers",
  "expect",
]);
const RESPONSE_STRIP = new Set([
  "connection",
  "content-length",
  "content-encoding",
  "transfer-encoding",
  "keep-alive",
  "upgrade",
]);

function resolveBackendUrl(req: NextRequest): string {
  const backendUrl = process.env.BACKEND_URL;
  if (backendUrl) return backendUrl.replace(/\/+$/, "");

  let port = process.env.BACKEND_PORT || "3001";
  // Same convention as the platform gateway: XTransformPort selects the port.
  const xPort = req.nextUrl.searchParams.get("XTransformPort");
  if (xPort && /^\d{1,5}$/.test(xPort)) {
    const parsed = parseInt(xPort, 10);
    if (parsed > 0 && parsed < 65536) port = String(parsed);
  }
  const host = process.env.BACKEND_HOST || "127.0.0.1";
  return `http://${host}:${port}`;
}

async function proxy(req: NextRequest): Promise<Response> {
  const backend = resolveBackendUrl(req);
  // req.nextUrl.pathname is the full path (/api/...) thanks to the catch-all.
  const suffix = req.nextUrl.pathname + req.nextUrl.search;
  const target = `${backend}${suffix}`;

  const method = req.method;
  const hasBody = method !== "GET" && method !== "HEAD";
  // Buffer the body: .sav files are a few MB, and a buffered forward is far
  // more predictable than streaming (no duplex concerns, exact length).
  const bodyBuffer = hasBody ? Buffer.from(await req.arrayBuffer()) : undefined;

  const headers: Record<string, string> = {};
  req.headers.forEach((value, key) => {
    if (!REQUEST_STRIP.has(key.toLowerCase())) headers[key] = value;
  });
  if (bodyBuffer && bodyBuffer.length > 0) {
    headers["content-length"] = String(bodyBuffer.length);
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body: bodyBuffer && bodyBuffer.length > 0 ? bodyBuffer : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch (err) {
    console.error(`[api-proxy] ${method} ${suffix} -> ${target} FAILED:`, err);
    return NextResponse.json(
      {
        error: `无法连接 Python 后端 (${target})。请先启动后端服务：在 mini-services/save-parser 目录运行 "python server.py"（或使用仓库根目录的 start.ps1 一键启动前后端），然后重试。`,
      },
      { status: 502, headers: { "access-control-allow-origin": "*" } }
    );
  }

  // Buffer the response so we can recompute an exact content-length.
  const resBuffer = Buffer.from(await upstream.arrayBuffer());
  const resHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!RESPONSE_STRIP.has(key.toLowerCase())) resHeaders.set(key, value);
  });
  resHeaders.set("content-length", String(resBuffer.length));

  console.log(`[api-proxy] ${method} ${suffix} -> backend ${upstream.status}`);
  return new NextResponse(new Uint8Array(resBuffer), {
    status: upstream.status,
    headers: resHeaders,
  });
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
  proxy as OPTIONS,
  proxy as HEAD,
};
