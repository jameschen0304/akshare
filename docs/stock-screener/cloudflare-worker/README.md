# 财报 CORS 代理（Cloudflare Workers）

GitHub Pages 无法直连东方财富财报接口，需部署此代理（免费）。

## 部署步骤

1. 注册 [Cloudflare](https://dash.cloudflare.com/) 并安装 Wrangler：

   ```bash
   npm install -g wrangler
   wrangler login
   ```

2. 在本目录执行：

   ```bash
   cd docs/stock-screener/cloudflare-worker
   wrangler deploy
   ```

3. 记下输出的地址，例如 `https://akshare-em-proxy.xxxx.workers.dev`

4. 编辑 `docs/stock-screener/config.js`：

   ```javascript
   window.SCREENER_PROXY_BASE = "https://akshare-em-proxy.xxxx.workers.dev";
   ```

5. 推送 GitHub 后刷新选股页面。

## 不部署代理时

本地运行 Python 后端（推荐）：

```bash
pip install fastapi uvicorn pandas akshare
python scripts/stock_screener_web/app.py
```

浏览器打开 http://127.0.0.1:8765
