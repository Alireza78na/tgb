#!/bin/bash
set -e

# Automatic setup for Telegram FileBot

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root or with sudo" >&2
  exit 1
fi

# Install prerequisites
apt update
apt install -y git docker.io docker-compose python3.11 python3.11-venv
systemctl enable --now docker

# Ask for configuration
read -rp "Enter Telegram Bot Token: " BOT_TOKEN
read -rp "Enter download domain (e.g. example.com): " DOWNLOAD_DOMAIN
read -rp "Enter API base URL [http://localhost:8000]: " API_BASE_URL
read -rp "Enter admin IDs separated by comma: " ADMIN_IDS
read -rp "Enter admin API token: " ADMIN_API_TOKEN
read -rp "Enter subscription reminder days [3]: " SUBSCRIPTION_REMINDER_DAYS
read -rp "Enter required channel username or ID (leave blank if none): " REQUIRED_CHANNEL

API_BASE_URL=${API_BASE_URL:-http://localhost:8000}
SUBSCRIPTION_REMINDER_DAYS=${SUBSCRIPTION_REMINDER_DAYS:-3}

cat > .env <<ENV
BOT_TOKEN=$BOT_TOKEN
API_BASE_URL=$API_BASE_URL
DOWNLOAD_DOMAIN=$DOWNLOAD_DOMAIN
ADMIN_IDS=$ADMIN_IDS
ADMIN_API_TOKEN=$ADMIN_API_TOKEN
SUBSCRIPTION_REMINDER_DAYS=$SUBSCRIPTION_REMINDER_DAYS
REQUIRED_CHANNEL=$REQUIRED_CHANNEL
ENV

# Build and run containers
docker-compose up --build -d

echo "\nSetup complete! Use 'docker-compose logs -f' to view logs."
