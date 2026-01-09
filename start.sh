#!/bin/bash

# TUM Live Downloader Startup Script
# This script starts both the Python backend and Electron frontend

set -e  # Exit on any error

echo "Starting TUM Live Downloader..."

# Function to cleanup processes on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    
    # Kill frontend first (Electron will handle Python cleanup)
    if [ ! -z "$FRONTEND_PID" ]; then
        echo "Stopping Electron frontend (PID: $FRONTEND_PID)..."
        kill -TERM $FRONTEND_PID 2>/dev/null || true
        
        # Wait a bit for graceful shutdown
        sleep 2
        
        # Force kill if still running
        if kill -0 $FRONTEND_PID 2>/dev/null; then
            echo "Force killing Electron frontend..."
            kill -KILL $FRONTEND_PID 2>/dev/null || true
        fi
    fi
    
    # Kill backend (redundant but safe)
    if [ ! -z "$BACKEND_PID" ]; then
        echo "Stopping Python backend (PID: $BACKEND_PID)..."
        kill -TERM $BACKEND_PID 2>/dev/null || true
        
        # Wait a bit for graceful shutdown
        sleep 2
        
        # Force kill if still running
        if kill -0 $BACKEND_PID 2>/dev/null; then
            echo "Force killing Python backend..."
            kill -KILL $BACKEND_PID 2>/dev/null || true
        fi
    fi
    
    # Kill any remaining Python download processes
    echo "Cleaning up any remaining download processes..."
    pkill -f "downloader.py" 2>/dev/null || true
    pkill -f "tum_video_scraper" 2>/dev/null || true
    
    echo "Cleanup complete"
    exit 0
}

# Set up signal handlers for immediate cleanup
trap cleanup SIGINT SIGTERM EXIT

# Function to handle emergency shutdown
emergency_cleanup() {
    echo ""
    echo "EMERGENCY SHUTDOWN"
    
    # Kill everything immediately
    [ ! -z "$FRONTEND_PID" ] && kill -KILL $FRONTEND_PID 2>/dev/null || true
    [ ! -z "$BACKEND_PID" ] && kill -KILL $BACKEND_PID 2>/dev/null || true
    
    # Nuclear option - kill all related processes
    pkill -f "electron" 2>/dev/null || true
    pkill -f "server.py" 2>/dev/null || true
    pkill -f "downloader.py" 2>/dev/null || true
    pkill -f "tum_video_scraper" 2>/dev/null || true
    
    exit 1
}

# Set up emergency handler for double Ctrl+C
trap emergency_cleanup SIGQUIT

# Check if Python is available
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "Error: Python is not installed or not in PATH"
    exit 1
fi

# Check if Node.js is available
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is not installed or not in PATH"
    exit 1
fi

# Check if npm is available
if ! command -v npm &> /dev/null; then
    echo "Error: npm is not installed or not in PATH"
    exit 1
fi

# Determine Python command
PYTHON_CMD="python"
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
fi

echo "Starting Python backend..."

# Start Python backend in background
$PYTHON_CMD backend/server.py &
BACKEND_PID=$!

echo "Python backend started (PID: $BACKEND_PID)"

# Wait a moment for backend to start
sleep 2

# Check if backend is still running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "Error: Python backend failed to start"
    exit 1
fi

echo "Waiting for backend to be ready..."

# Wait for backend to be ready (max 30 seconds)
for i in {1..30}; do
    if curl -s http://127.0.0.1:5001/health > /dev/null 2>&1; then
        echo "Backend is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Error: Backend health check timeout"
        cleanup
        exit 1
    fi
    sleep 1
done

echo "Starting Electron frontend..."

# Start Electron frontend
npm start &
FRONTEND_PID=$!

echo "Electron frontend started (PID: $FRONTEND_PID)"
echo ""
echo "TUM Live Downloader is now running!"
echo "The application window should open automatically"
echo "Backend API: http://127.0.0.1:5001"
echo ""
echo "Press Ctrl+C to stop both services"
echo "Press Ctrl+\\ for emergency shutdown"

# Wait for processes to finish
wait $FRONTEND_PID
cleanup