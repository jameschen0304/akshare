/**
 * GitHub Pages 前端需连接独立 API 服务（Pages 不能运行 Python 后端）。
 * 在 Render 部署后，将下方地址改为你的服务 URL，例如：
 * https://akshare-stock-screener.onrender.com
 */
(function () {
  const host = location.hostname;
  if (host === "localhost" || host === "127.0.0.1") {
    window.SCREENER_API_BASE = "";
    return;
  }
  if (host.endsWith("github.io")) {
    window.SCREENER_API_BASE = "";
    return;
  }
  window.SCREENER_API_BASE = "";
})();
