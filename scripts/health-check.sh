#!/bin/bash
# Health check script to verify all services are running

set -e

echo "🔍 Checking Track2stem services..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running"
    exit 1
fi

echo "✅ Docker is running"

# Check if containers are running
BACKEND_STATUS=$(docker compose ps backend --status running --quiet 2>/dev/null || echo "")
FRONTEND_STATUS=$(docker compose ps frontend --status running --quiet 2>/dev/null || echo "")
PROCESSOR_STATUS=$(docker compose ps processor --status running --quiet 2>/dev/null || echo "")

if [ -z "$BACKEND_STATUS" ]; then
    echo "❌ Backend container is not running"
    exit 1
fi
echo "✅ Backend container is running"

if [ -z "$FRONTEND_STATUS" ]; then
    echo "❌ Frontend container is not running"
    exit 1
fi
echo "✅ Frontend container is running"

if [ -z "$PROCESSOR_STATUS" ]; then
    echo "❌ Processor container is not running"
    exit 1
fi
echo "✅ Processor container is running"

# Check backend health endpoint
echo "🔍 Checking backend health endpoint..."
BACKEND_HEALTH=$(curl -s http://localhost:8080/api/health 2>/dev/null || echo "")
if echo "$BACKEND_HEALTH" | grep -q "ok"; then
    echo "✅ Backend is healthy"
else
    echo "❌ Backend health check failed"
    exit 1
fi

# Check frontend is accessible
echo "🔍 Checking frontend..."
FRONTEND_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null || echo "000")
if [ "$FRONTEND_CHECK" = "200" ]; then
    echo "✅ Frontend is accessible"
else
    echo "⚠️  Frontend returned status code: $FRONTEND_CHECK (may be starting up)"
fi

echo ""
echo "🎉 All services are running!"
echo "   Frontend: http://localhost:3000"
echo "   Backend:  http://localhost:8080"
