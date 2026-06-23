# Joule — Energy Prediction Model

**Joule** is an AI-powered energy market forecasting system for **Crude Oil (WTI)**, **RBOB Gasoline**, and **ULSD Diesel**. It combines statistical models, gradient boosting, news sentiment, and fundamentals into multi-horizon price forecasts with a live web dashboard.

## Features

- **Multi-horizon forecasts** — Day 1, Day 4, and Day 7 for all three products
- **Model stack** — VAR/Prophet base, XGBoost (RBOB day-1), CatBoost (day 4/7), ensemble layers, bias correction
- **Data pipeline** — Yahoo Finance, EIA inventory/retail/operational data, NewsAPI, weather, dollar index, crack spreads
- **Joule Dashboard** — Modern web UI with charts, live news, inventory, accuracy tracking, and manual pipeline runs
- **Email reports** — HTML forecast summaries to configured recipients
- **Docker support** — 24/7 scheduler + dashboard via `docker-compose`

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys and email settings
```

Required keys: `EIA_API_KEY`, `NEWS_API_KEY` (recommended). See `.env.example` for all options.

### 3. Run predictions

```bash
python prediction_engine.py
```

### 4. Launch the Joule dashboard

```bash
python dashboard/app.py
# Or on Windows:
.\start_dashboard.ps1
```

Open **http://localhost:8080**

### 5. Run on a schedule (24/7)

```bash
python prediction_scheduler.py
```

### Docker

```bash
docker-compose up --build
```

Dashboard: **http://localhost:8080**

## Project Structure

```
├── prediction_engine.py    # Full prediction pipeline
├── prediction_scheduler.py # Scheduled runs + email
├── predictor.py            # VAR / Prophet forecasting
├── ensemble_models.py      # Technical + fundamental + news layers
├── rbob_xgb_model.py       # XGBoost RBOB day-1 overlay
├── medium_term_model.py    # CatBoost day 4/7 models
├── dashboard/              # Joule web UI (Flask + Plotly)
│   ├── app.py
│   ├── data_loader.py
│   ├── templates/
│   └── static/
├── scripts/                # Data fetch + preprocessing
├── data/                   # Market data, predictions, trained models
└── config.py               # Configuration (reads from env)
```

## Dashboard API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Joule dashboard UI |
| `GET /api/predictions` | Latest forecasts |
| `GET /api/prices` | Price history |
| `GET /api/news` | Energy headlines + sentiment |
| `GET /api/inventory` | EIA weekly stocks |
| `GET /api/market` | Crack spreads, DXY, fundamentals |
| `GET /api/accuracy` | Forecast vs actual scores |
| `POST /api/run` | Trigger full pipeline |

## Products Tracked

| Product | Symbol | Unit |
|---------|--------|------|
| WTI Crude | CL=F | $/bbl |
| RBOB Gasoline | RB=F | $/gal |
| ULSD Diesel | HO=F | $/gal |

## License

Provided as-is for energy market research and forecasting.
