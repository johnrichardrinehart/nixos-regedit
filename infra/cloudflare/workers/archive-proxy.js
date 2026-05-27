const DEFAULT_MAX_BYTES = 512 * 1024 * 1024;
const DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60;
const DEFAULT_APP_URL = "https://johnrichardrinehart.github.io/nixos-regedit/";
const ARCHIVE_EXTENSIONS = [
  ".tar",
  ".tar.gz",
  ".tgz",
  ".tar.xz",
  ".txz",
  ".tar.bz2",
  ".tbz2",
  ".tar.zst",
  ".zip",
];

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowed = String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  const allowAny = allowed.includes("*");
  const allowNull = allowed.includes("null") && origin === "null";
  const allowOrigin = allowAny ? "*" : allowNull || allowed.includes(origin) ? origin : "";

  const headers = {
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Accept, If-None-Match, Range, X-Upstream-Authorization",
    "Access-Control-Expose-Headers":
      "Content-Length, Content-Type, ETag, Last-Modified, X-Upstream-URL, X-NixOS-Regedit-Proxy-Cache",
    Vary: "Origin",
  };
  if (allowOrigin) headers["Access-Control-Allow-Origin"] = allowOrigin;
  return headers;
}

function withCors(response, request, env) {
  const headers = new Headers(response.headers);
  for (const name of [...headers.keys()]) {
    if (name.toLowerCase().startsWith("access-control-")) headers.delete(name);
  }
  Object.entries(corsHeaders(request, env)).forEach(([name, value]) => {
    if (value) headers.set(name, value);
  });
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function jsonResponse(payload, status, request, env) {
  return withCors(
    Response.json(payload, {
      status,
      headers: {
        "Cache-Control": "no-store",
      },
    }),
    request,
    env,
  );
}

function isGitHubArchive(url) {
  if (url.protocol !== "https:" || url.hostname !== "github.com") return false;
  const parts = url.pathname.split("/").filter(Boolean);
  return parts.length >= 4 && parts[2] === "archive";
}

function isCodeloadArchive(url) {
  if (url.protocol !== "https:" || url.hostname !== "codeload.github.com") return false;
  const parts = url.pathname.split("/").filter(Boolean);
  if (parts.length < 4) return false;
  return ["tar.gz", "zip", "legacy.tar.gz", "legacy.zip"].includes(parts[2]);
}

function isGitLabArchive(url) {
  if (url.protocol !== "https:" || !url.hostname.endsWith("gitlab.com")) return false;
  const parts = url.pathname.split("/").filter(Boolean);
  if (parts.includes("archive.tar.gz") || parts.includes("archive.zip")) return true;
  const archiveIndex = parts.indexOf("archive");
  return archiveIndex >= 1 && parts[archiveIndex - 1] === "-" && hasArchiveExtension(url);
}

function isSourcehutArchive(url) {
  if (url.protocol !== "https:" || !url.hostname.endsWith("git.sr.ht")) return false;
  const parts = url.pathname.split("/").filter(Boolean);
  return parts.includes("archive") && hasArchiveExtension(url);
}

function hasArchiveExtension(url) {
  const path = url.pathname.toLowerCase();
  return ARCHIVE_EXTENSIONS.some((extension) => path.endsWith(extension));
}

function isArchiveUrl(url) {
  if (url.protocol !== "https:") return false;
  return (
    isGitHubArchive(url) ||
    isCodeloadArchive(url) ||
    isGitLabArchive(url) ||
    isSourcehutArchive(url) ||
    hasArchiveExtension(url)
  );
}

function parseTarget(request) {
  const url = new URL(request.url);
  const target = url.searchParams.get("url");
  if (!target) throw new Error("missing url query parameter");
  const parsed = new URL(target);
  if (!isArchiveUrl(parsed)) {
    throw new Error(
      "only HTTPS archive URLs are allowed; supported forms include GitHub, GitLab, SourceHut, and common tar/zip archive URLs",
    );
  }
  return parsed;
}

function appUrl(env) {
  const value = String(env.APP_URL || "").trim();
  return value || DEFAULT_APP_URL;
}

function shouldRedirectToApp(request) {
  const url = new URL(request.url);
  return (
    (request.method === "GET" || request.method === "HEAD") && url.pathname === "/" && !url.search
  );
}

async function rateLimit(request, env, target) {
  if (!env.ARCHIVE_PROXY_RATE_LIMITER) return null;
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const key = `${ip}:${target.hostname}`;
  const { success } = await env.ARCHIVE_PROXY_RATE_LIMITER.limit({ key });
  if (success) return null;
  return jsonResponse(
    {
      ok: false,
      error: "rate limit exceeded",
    },
    429,
    request,
    env,
  );
}

function maxBytes(env) {
  const value = Number(env.MAX_RESPONSE_BYTES || DEFAULT_MAX_BYTES);
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_MAX_BYTES;
}

function cacheTtl(env) {
  const value = Number(env.CACHE_TTL_SECONDS || DEFAULT_CACHE_TTL_SECONDS);
  return Number.isFinite(value) && value >= 0 ? value : DEFAULT_CACHE_TTL_SECONDS;
}

function cacheableRequest(request, upstreamAuthorized) {
  return request.method === "GET" && !upstreamAuthorized && !request.headers.has("Range");
}

function archiveCacheKey(target) {
  return new Request(target.toString(), { method: "GET" });
}

function headFromCached(cached, request, env) {
  return withCors(
    new Response(null, { status: cached.status, headers: cached.headers }),
    request,
    env,
  );
}

function upstreamHeaders(request) {
  const headers = new Headers();
  const accept = request.headers.get("Accept");
  const range = request.headers.get("Range");
  const etag = request.headers.get("If-None-Match");
  const auth = request.headers.get("X-Upstream-Authorization");
  if (accept) headers.set("Accept", accept);
  if (range) headers.set("Range", range);
  if (etag) headers.set("If-None-Match", etag);
  if (auth) headers.set("Authorization", auth);
  headers.set("User-Agent", "nixos-regedit-archive-proxy");
  return headers;
}

async function proxy(request, env) {
  if (shouldRedirectToApp(request)) {
    return Response.redirect(appUrl(env), 302);
  }

  if (request.method === "OPTIONS")
    return new Response(null, { headers: corsHeaders(request, env) });
  if (request.method !== "GET" && request.method !== "HEAD") {
    return jsonResponse({ ok: false, error: "method not allowed" }, 405, request, env);
  }

  let target;
  try {
    target = parseTarget(request);
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error.message || error) }, 400, request, env);
  }

  const limited = await rateLimit(request, env, target);
  if (limited) return limited;

  const auth = request.headers.get("X-Upstream-Authorization");
  const cacheKey = archiveCacheKey(target);
  if (request.method === "HEAD" && !auth) {
    const cached = await caches.default.match(cacheKey);
    if (cached) {
      const response = headFromCached(cached, request, env);
      response.headers.set("X-NixOS-Regedit-Proxy-Cache", "HIT");
      return response;
    }
  }
  if (cacheableRequest(request, Boolean(auth))) {
    const cached = await caches.default.match(cacheKey);
    if (cached) {
      const response = withCors(cached, request, env);
      response.headers.set("X-NixOS-Regedit-Proxy-Cache", "HIT");
      return response;
    }
  }

  const upstream = await fetch(target, {
    method: request.method,
    headers: upstreamHeaders(request),
    redirect: "follow",
  });

  const length = Number(upstream.headers.get("Content-Length") || 0);
  if (length > maxBytes(env)) {
    if (upstream.body) upstream.body.cancel();
    return jsonResponse({ ok: false, error: "archive is too large" }, 413, request, env);
  }

  const headers = new Headers(upstream.headers);
  headers.set("X-Upstream-URL", upstream.url || target.toString());
  if (cacheableRequest(request, Boolean(auth)) && upstream.ok) {
    headers.set("Cache-Control", `public, max-age=${cacheTtl(env)}, immutable`);
  } else {
    headers.set("Cache-Control", "no-store");
  }
  headers.set("X-NixOS-Regedit-Proxy-Cache", "MISS");

  const response = new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });

  if (cacheableRequest(request, Boolean(auth)) && upstream.ok) {
    await caches.default.put(cacheKey, response.clone());
  }
  return withCors(response, request, env);
}

export default {
  fetch: proxy,
};
