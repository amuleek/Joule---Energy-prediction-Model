# Quick Docker Start Guide

## 🚀 Fast Setup (3 Steps)

### 1. Create `.env` file
```bash
# Copy the example
cp .env.example .env

# Edit .env and add your Gmail App Password:
# SENDER_PASSWORD=aznj dfcj nrxw mluq
```

### 2. Build and Run
```bash
docker-compose up -d
```

### 3. Check Logs
```bash
docker-compose logs -f
```

## ✅ That's It!

The container will:
- ✅ Run prediction scheduler automatically
- ✅ Send emails at 6 AM, 9 AM, 12 PM, 6 PM EST
- ✅ Persist data in `./data` directory
- ✅ Auto-restart if it crashes

## Common Commands

```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# View logs
docker-compose logs -f

# Restart
docker-compose restart

# Test email
docker-compose exec energy-ai-agent python send_test_prediction.py
```

## Troubleshooting

**Container won't start?**
```bash
docker-compose logs
```

**Email not working?**
- Check `SENDER_PASSWORD` in `.env`
- Verify Gmail App Password is correct

**Need to rebuild?**
```bash
docker-compose build --no-cache
docker-compose up -d
```

## What Gets Containerized?

- ✅ All Python code
- ✅ Dependencies (Prophet, Pandas, etc.)
- ✅ Prediction scheduler
- ✅ Email system
- ✅ Data collection scripts

## Data Persistence

Your `data/` folder is mounted, so:
- Historical data persists
- Predictions saved automatically
- No data loss on restart

## Next: Deploy to Cloud

Once working locally, deploy to:
- AWS EC2
- DigitalOcean
- Google Cloud Run
- Any Docker host

See `DOCKER_SETUP.md` for details!
