# Docker Setup Guide

## Quick Start

### Option 1: Using Docker Compose (Recommended)

1. **Create `.env` file** (copy from `.env.example`):
```bash
cp .env.example .env
# Edit .env and add your Gmail App Password
```

2. **Build and run**:
```bash
docker-compose up -d
```

3. **View logs**:
```bash
docker-compose logs -f
```

4. **Stop**:
```bash
docker-compose down
```

### Option 2: Using Docker Directly

1. **Build the image**:
```bash
docker build -t energy-ai-agent .
```

2. **Run the container**:
```bash
docker run -d \
  --name energy-ai-agent \
  --restart unless-stopped \
  -e SENDER_PASSWORD="your-gmail-app-password" \
  -v $(pwd)/data:/app/data \
  energy-ai-agent
```

3. **View logs**:
```bash
docker logs -f energy-ai-agent
```

## Environment Variables

Create a `.env` file with your configuration:

```env
SENDER_EMAIL=amuleeksidhu96@gmail.com
SENDER_PASSWORD=your-gmail-app-password
RECIPIENT_EMAILS=amuleeksidhu96@gmail.com,rangi93@yahoo.com
PREDICTION_TIMES=06:00,09:00,12:00,18:00
```

## Data Persistence

The `data/` directory is mounted as a volume, so:
- ✅ Historical data persists across container restarts
- ✅ Predictions are saved to `data/predictions.json`
- ✅ Price history in `data/prices.csv`

## Commands

### Start container:
```bash
docker-compose up -d
```

### Stop container:
```bash
docker-compose down
```

### View logs:
```bash
docker-compose logs -f
```

### Restart container:
```bash
docker-compose restart
```

### Run one-time prediction (test):
```bash
docker-compose exec energy-ai-agent python send_test_prediction.py
```

### Access container shell:
```bash
docker-compose exec energy-ai-agent bash
```

## Schedule

The container runs the prediction scheduler automatically:
- **6:00 AM EST** - Morning report
- **9:00 AM EST** - Mid-morning update
- **12:00 PM EST** - Noon update
- **6:00 PM EST** - Evening report

## Troubleshooting

### Container won't start:
```bash
# Check logs
docker-compose logs

# Rebuild image
docker-compose build --no-cache
```

### Email not sending:
- Verify `SENDER_PASSWORD` in `.env` is correct (Gmail App Password)
- Check container logs for SMTP errors

### Missing data:
- Ensure `data/` directory exists and is writable
- Check volume mount: `docker-compose config`

## Production Deployment

### For 24/7 operation:

1. **Use Docker on a server** (AWS EC2, DigitalOcean, etc.)
2. **Set up auto-restart** (already configured with `restart: unless-stopped`)
3. **Monitor logs**:
```bash
docker-compose logs -f --tail=100
```

4. **Set up log rotation** (optional):
```yaml
# Add to docker-compose.yml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

## Benefits of Docker

✅ **Isolated environment** - No conflicts with system Python
✅ **Easy deployment** - Works on any system with Docker
✅ **Automatic restarts** - Container restarts if it crashes
✅ **Data persistence** - Data survives container restarts
✅ **Easy updates** - Just rebuild and restart
✅ **Resource limits** - Can set CPU/memory limits

## Next Steps

1. Create `.env` file with your credentials
2. Run `docker-compose up -d`
3. Check logs to verify it's working
4. Receive prediction emails at scheduled times!
