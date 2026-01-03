# Insurance Lab - Backend Deployment Script
# Usage: .\deploy-backend.ps1

Write-Host "======================================" -ForegroundColor Cyan
Write-Host " INSURANCE LAB - BACKEND DEPLOYMENT  " -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

$VPS_IP = "46.224.127.115"
$VPS_USER = "root"
$DEPLOY_DIR = "/root/insurance-lab-deploy"

# Step 1: Backup current backend on VPS
Write-Host "`n[1/5] Creating backup of current backend..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "cd ${DEPLOY_DIR} && cp -r backend backend.backup.`$(date +%Y%m%d_%H%M%S)"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Backup creato" -ForegroundColor Green
}
else {
    Write-Host "⚠️  Backup fallito (continuo comunque)" -ForegroundColor Yellow
}

# Step 2: Upload backend files
Write-Host "`n[2/5] Uploading backend files..." -ForegroundColor Yellow

# Upload app directory
scp -r app "${VPS_USER}@${VPS_IP}:${DEPLOY_DIR}/backend/"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Errore upload directory app" -ForegroundColor Red
    exit 1
}

# Upload prompts directory
Write-Host "  Uploading prompts directory..." -ForegroundColor Gray
scp -r prompts "${VPS_USER}@${VPS_IP}:${DEPLOY_DIR}/backend/"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Errore upload directory prompts" -ForegroundColor Red
    exit 1
}

# Upload requirements.txt
scp requirements.txt "${VPS_USER}@${VPS_IP}:${DEPLOY_DIR}/backend/"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Errore upload requirements.txt" -ForegroundColor Red
    exit 1
    exit 1
}

# Upload static directory
Write-Host "  Uploading static directory..." -ForegroundColor Gray
scp -r static "${VPS_USER}@${VPS_IP}:${DEPLOY_DIR}/backend/"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Errore upload directory static" -ForegroundColor Red
    exit 1
}

# Upload Dockerfile if exists
if (Test-Path "Dockerfile.prod") {
    scp Dockerfile.prod "${VPS_USER}@${VPS_IP}:${DEPLOY_DIR}/backend/"
}

Write-Host "✅ File backend caricati (app + prompts + requirements)" -ForegroundColor Green

# Step 3: Rebuild backend container
Write-Host "`n[3/5] Rebuilding backend container..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "cd ${DEPLOY_DIR} && docker compose -f docker-compose.prod.yml build backend"

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Errore build container" -ForegroundColor Red
    Write-Host "Ripristino backup..." -ForegroundColor Yellow
    ssh "${VPS_USER}@${VPS_IP}" "cd ${DEPLOY_DIR} && rm -rf backend && cp -r backend.backup.* backend"
    exit 1
}

Write-Host "✅ Container rebuilded" -ForegroundColor Green

# Step 4: Restart backend
Write-Host "`n[4/5] Restarting backend..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "cd ${DEPLOY_DIR} && docker compose -f docker-compose.prod.yml up -d backend"

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Errore restart backend" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Backend riavviato" -ForegroundColor Green

# Step 5: Verify health check
Write-Host "`n[5/5] Verifying backend health..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

$healthCheck = ssh "${VPS_USER}@${VPS_IP}" "curl -s http://localhost:8000/health 2>&1"

if ($LASTEXITCODE -eq 0 -and $healthCheck -match "healthy") {
    Write-Host "✅ Backend is healthy!" -ForegroundColor Green
}
else {
    Write-Host "⚠️  Health check failed or backend starting" -ForegroundColor Yellow
    Write-Host "Check logs with: ssh root@46.224.127.115 'docker logs insurance-lab-backend --tail 50'" -ForegroundColor Gray
}

# Show logs
Write-Host "`nUltimi log del backend:" -ForegroundColor Cyan
ssh "${VPS_USER}@${VPS_IP}" "docker logs insurance-lab-backend --tail 15"

Write-Host "`n======================================" -ForegroundColor Green
Write-Host "✅ BACKEND DEPLOYMENT COMPLETATO!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host ""
Write-Host "🌐 API Health: https://app.insurance-lab.ai/api/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "Comandi utili:" -ForegroundColor Gray
Write-Host "  ssh root@46.224.127.115" -ForegroundColor Gray
Write-Host "  docker logs insurance-lab-backend --tail 50 -f" -ForegroundColor Gray
Write-Host "  docker restart insurance-lab-backend" -ForegroundColor Gray
Write-Host "  curl https://app.insurance-lab.ai/api/health" -ForegroundColor Gray
Write-Host ""
