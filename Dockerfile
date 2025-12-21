# TUM Live Downloader Docker Image
FROM node:18-bullseye

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    firefox-esr \
    xvfb \
    wget \
    curl \
    ffmpeg \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# Install geckodriver for Selenium
RUN wget -O /tmp/geckodriver.tar.gz https://github.com/mozilla/geckodriver/releases/download/v0.33.0/geckodriver-v0.33.0-linux64.tar.gz \
    && tar -xzf /tmp/geckodriver.tar.gz -C /usr/local/bin/ \
    && chmod +x /usr/local/bin/geckodriver \
    && rm /tmp/geckodriver.tar.gz

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install Node.js dependencies
RUN npm install

# Copy Python requirements
COPY requirements.txt ./

# Install Python dependencies
RUN pip3 install -r requirements.txt

# Copy application files
COPY . .

# Create necessary directories
RUN mkdir -p /app/downloads /app/tmp

# Configure nginx for web interface
RUN echo 'server {\n\
    listen 80;\n\
    server_name localhost;\n\
    root /app;\n\
    index docker-web.html;\n\
    \n\
    location / {\n\
        try_files $uri $uri/ /docker-web.html;\n\
    }\n\
    \n\
    location /api/ {\n\
        proxy_pass http://localhost:5001;\n\
        proxy_set_header Host $host;\n\
        proxy_set_header X-Real-IP $remote_addr;\n\
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n\
        proxy_set_header X-Forwarded-Proto $scheme;\n\
    }\n\
    \n\
    location /frontend/ {\n\
        alias /app/frontend/;\n\
    }\n\
}' > /etc/nginx/sites-available/default

# Set environment variables
ENV DISPLAY=:99
ENV PYTHONPATH=/app
ENV NODE_ENV=production

# Expose ports
EXPOSE 80 5001

# Create startup script
RUN echo '#!/bin/bash\n\
echo "Starting TUM Live Downloader Docker Container..."\n\
\n\
# Start virtual display for Selenium\n\
echo "Starting virtual display..."\n\
Xvfb :99 -screen 0 1024x768x24 > /dev/null 2>&1 &\n\
\n\
# Start Flask backend\n\
echo "Starting Flask backend..."\n\
cd /app\n\
python3 backend/server.py > /tmp/backend.log 2>&1 &\n\
\n\
# Wait for backend to start\n\
echo "Waiting for backend to start..."\n\
sleep 10\n\
\n\
# Start nginx for web interface\n\
echo "Starting web interface..."\n\
nginx -g "daemon off;" &\n\
\n\
echo "TUM Live Downloader is ready!"\n\
echo "Web Interface: http://localhost"\n\
echo "API Backend: http://localhost:5001"\n\
\n\
# Keep container running and show logs\n\
tail -f /tmp/backend.log\n\
' > /app/start.sh && chmod +x /app/start.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# Start the application
CMD ["/app/start.sh"]