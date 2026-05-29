/**
 * 东方财富 CORS 代理（部署到 Cloudflare Workers 免费版）
 * 部署后把地址填入 config.js：window.SCREENER_PROXY_BASE = "https://xxx.workers.dev";
 */
export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: corsHeaders(),
      });
    }

    const reqUrl = new URL(request.url);
    const target = reqUrl.searchParams.get("url");
    if (!target) {
      return json({ error: "missing url param" }, 400);
    }

    let targetUrl;
    try {
      targetUrl = new URL(target);
    } catch (_) {
      return json({ error: "invalid url" }, 400);
    }

    if (targetUrl.protocol !== "https:") {
      return json({ error: "https only" }, 400);
    }

    const host = targetUrl.hostname;
    const allowed =
      host.endsWith(".eastmoney.com") || host === "eastmoney.com";
    if (!allowed) {
      return json({ error: "host not allowed" }, 403);
    }

    const referer = host.includes("emweb.securities")
      ? "https://emweb.securities.eastmoney.com/"
      : "https://quote.eastmoney.com/";

    const upstream = await fetch(target, {
      headers: {
        Referer: referer,
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        Accept: "application/json, text/plain, */*",
      },
    });

    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: {
        ...corsHeaders(),
        "Content-Type":
          upstream.headers.get("Content-Type") ||
          "application/json; charset=utf-8",
      },
    });
  },
};

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
  };
}

function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: {
      ...corsHeaders(),
      "Content-Type": "application/json",
    },
  });
}
