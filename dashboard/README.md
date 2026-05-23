# Quant Strategy Dashboard

量化永續合約策略研究 dashboard。後端 FastAPI + 前端 React/Vite。

## 本機開發啟動

### 1. 後端

```bash
cd dashboard/server
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac
pip install -r requirements.txt

# 指向 sample data 快速測試
set REPO_ROOT=..\sample_data   # Windows
# export REPO_ROOT=../sample_data  # Linux/Mac

uvicorn main:app --reload --port 8000
```

API 文件：http://localhost:8000/docs

### 2. 前端

```bash
cd dashboard/web
npm install
npm run dev
```

前端：http://localhost:5173（透過 Vite proxy 自動轉到後端 /api/）

---

## Docker 啟動

```bash
cd dashboard
docker compose up --build
```

前端：http://localhost  
後端 API：http://localhost/api/

### 環境變數（選填）

| 變數 | 預設 | 說明 |
|------|------|------|
| `REPO_ROOT` | `/repo` | repo 根目錄（docker-compose 已掛 host repo 到此路徑） |
| `CORS_ORIGINS` | `http://localhost` | 允許的前端來源，逗號分隔 |

---

## 資料目錄結構

後端讀取 `$REPO_ROOT` 下的：

```
research/
  manifests/
    <strategy_id>/manifest.json   # 策略 manifest
    factor_<symbol>.json          # 因子分析
    regime_<symbol>.json          # regime 分類
    selection.json                # 選策略結果
runs/
  <run_id>/equity.csv             # 淨值曲線
  <run_id>/trades.csv             # 成交明細
  testnet/<strategy_id>/testnet_status.json
```

範例資料在 `dashboard/sample_data/`，可直接用於測試。

---

## 測試

```bash
cd dashboard/server
pytest -q   # 107 tests
```
