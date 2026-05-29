# A股选股工具（网页版）

基于 akshare / 东方财富财报数据，按 **自算 PE（TTM）**、**年报+半年报** 指标筛选，默认排除 **ST** 与 **科创板（688）**。

## 功能

- PE(TTM) = 总市值 ÷ TTM 归母扣非净利润（按累计财报折算最近 12 个月）
- 近 6 个半年报/年报：收入、成本、扣非、流动比率、毛利率、净利率等
- 硬性规则（可关闭）：最新流动比率 ≥ 阈值；连续 N 个年报营业总收入递增
- 导出 CSV、查看单股分期明细

## 安装与启动

```bash
pip install fastapi uvicorn pydantic pandas akshare requests beautifulsoup4 lxml

cd scripts/stock_screener_web
python app.py
```

浏览器打开：<http://127.0.0.1:8765>

## GitHub Pages + Render（推荐在线方案）

- 前端：<https://jameschen0304.github.io/akshare-stock-screener/>
- 财报后端（Render，一键部署）：  
  [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/jameschen0304/akshare)  
  详细步骤见 [docs/stock-screener/RENDER_DEPLOY.md](../../docs/stock-screener/RENDER_DEPLOY.md)
- 未部署 Render 时，浏览器用 Service Worker 代理财报（易失败）；部署后 Pages 会自动连云端 API

若遇代理导致请求失败，PowerShell 可先执行：

```powershell
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
$env:ALL_PROXY=""
python app.py
```

## 说明

- 全市场扫描较慢（每只股票约 2 次财报接口），请先用「扫描股票上限」试跑（默认 80）。
- 数据仅供研究，不构成投资建议。
