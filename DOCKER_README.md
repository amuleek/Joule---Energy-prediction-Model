# Docker Containerization

## 📦 What's Included

This project is now fully containerized with Docker:

- ✅ **Dockerfile** - Main container definition
- ✅ **docker-compose.yml** - Easy orchestration
- ✅ **.dockerignore** - Excludes unnecessary files
- ✅ **docker-entrypoint.sh** - Startup script
- ✅ **.env.example** - Environment variable template

## 🚀 Quick Start

### Prerequisites
- Docker installed ([Get Docker](https://www.docker.com/get-started))
- Docker Compose (usually included with Docker Desktop)

### 3-Step Setup

1. **Create `.env` file**:
```bash
cp .env.example .env
# Edit .env and add your Gmail App Password
```

2. **Build and run**:
```bash
docker-compose up -d
```

3. **Check it's working**:
```bash
docker-compose logs -f
```

## 📋 Files Created

### `Dockerfile`
- Base: Python 3.11 slim
- Installs all dependencies
- Sets up timezone (EST)
- Downloads NLTK data
- Runs prediction scheduler

### `docker-compose.yml`
- Defines service configuration
- Environment variables
- Volume mounts for data persistence
- Auto-restart policy
- Health checks

### `.dockerignore`
- Excludes unnecessary files from build
- Reduces image size
- Faster builds

### `docker-entrypoint.sh`
- Startup script
- Initializes data if needed
- Runs scheduler

## 🔧 Configuration

### Environment Variables

Set in `.env` file or `docker-compose.yml`:

```env
SENDER_EMAIL=amuleeksidhu96@gmail.com
SENDER_PASSWORD=your-gmail-app-password
RECIPIENT_EMAILS=email1@gmail.com,email2@yahoo.com
PREDICTION_TIMES=06:00,09:00,12:00,18:00
```

### Data Persistence

The `data/` directory is mounted as a volume:
- Historical data persists
- Predictions saved automatically
- No data loss on restart

## 📝 Common Commands

```bash
# Start container
docker-compose up -d

# Stop container
docker-compose down

# View logs
docker-compose logs -f

# Restart
docker-compose restart

# Rebuild (after code changes)
docker-compose build --no-cache
docker-compose up -d

# Run test prediction
docker-compose exec energy-ai-agent python send_test_prediction.py

# Access container shell
docker-compose exec energy-ai-agent bash
```

## 🐛 Troubleshooting

### Container won't start
```bash
# Check logs
docker-compose logs

# Rebuild
docker-compose build --no-cache
docker-compose up -d
```

### Email not sending
- Verify `SENDER_PASSWORD` in `.env`
- Check container logs for SMTP errors
- Ensure Gmail App Password is correct

### Missing dependencies
```bash
# Rebuild with no cache
docker-compose build --no-cache
```

## 🌐 Deployment Options

### Local Machine
```bash
docker-compose up -d
```

### Cloud Server (AWS EC2, DigitalOcean, etc.)
1. Install Docker on server
2. Copy project files
3. Create `.env` file
4. Run `docker-compose up -d`

### Docker Hub
```bash
# Build
docker build -t yourusername/energy-ai-agent .

# Push
docker push yourusername/energy-ai-agent

# Pull and run
docker run -d --env-file .env yourusername/energy-ai-agent
```

## ✅ Benefits

- ✅ **Isolated** - No conflicts with system Python
- ✅ **Portable** - Runs anywhere Docker runs
- ✅ **Consistent** - Same environment everywhere
- ✅ **Easy Updates** - Just rebuild and restart
- ✅ **Auto-restart** - Container restarts on failure
- ✅ **Resource Limits** - Can set CPU/memory limits

## 📊 Schedule

Container runs prediction scheduler:
- **6:00 AM EST** - Morning report
- **9:00 AM EST** - Mid-morning update
- **12:00 PM EST** - Noon update
- **6:00 PM EST** - Evening report

## 🔒 Security Notes

- Never commit `.env` file to Git
- Use environment variables for secrets
- Gmail App Password is required (not regular password)
- API keys are in `.env` (not in code)

## 📚 More Info

- See `DOCKER_SETUP.md` for detailed setup
- See `QUICK_DOCKER_START.md` for quick reference
