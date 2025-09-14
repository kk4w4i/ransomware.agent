# Use the official lightweight Python image
FROM python:3.11-slim

# Set environment variables to avoid interactive debconf and python .pyc files
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies: playwright/chromium/ffmpeg/fonts/tor/other deps
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    git \
    wget \
    tor \
    xvfb \
    fonts-liberation \
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxcb1 \
    libx11-xcb1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libxshmfence1 \
    libdrm2 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Install Playwright and download browser binaries
RUN playwright install --with-deps chromium

# Copy project files
COPY . .

# Expose TOR SOCKS proxy port (optional: only if you want to connect externally)
EXPOSE 9050

# Start Tor before running the app
CMD service tor start && python app.py