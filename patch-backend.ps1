# Patch Backend Script (Hot Fix)
# Usage: .\patch-backend.ps1

Write-Host "🚀 Patching Backend (OCR Optimization + Permissions)..." -ForegroundColor Cyan

$VPS_IP = "46.224.127.115"
$VPS_USER = "root"
$LOCAL_MIGRATION = "app/ocr.py"
$CONTAINER_NAME = "insurance-lab-backend"

# Check if ocr.py exists locally
if (-Not (Test-Path $LOCAL_MIGRATION)) {
    Write-Host "❌ Error: $LOCAL_MIGRATION not found!" -ForegroundColor Red
    exit 1
}

# 1. Upload new OCR file to VPS temp
Write-Host "📤 Uploading optimized ocr.py..." -ForegroundColor Yellow
scp $LOCAL_MIGRATION "${VPS_USER}@${VPS_IP}:/tmp/ocr.py"

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ SCP Upload failed!" -ForegroundColor Red
    exit 1
}

# 2. Patch Container
Write-Host "🔧 Patching container..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "docker cp /tmp/ocr.py ${CONTAINER_NAME}:/app/app/ocr.py"

# 3. Fix Permissions (in case uploads hang due to perms)
Write-Host "🔧 Fixing permissions..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "docker exec -u root ${CONTAINER_NAME} chmod -R 777 /app/uploads /app/outputs"

# 4. Restart Container to apply code changes
Write-Host "🔄 Restarting Backend..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "docker restart ${CONTAINER_NAME}"

# 5. Cleanup
ssh "${VPS_USER}@${VPS_IP}" "rm /tmp/ocr.py"

Write-Host "✅ Backend patched and restarted!" -ForegroundColor Green
Write-Host "Try uploading a file now." -ForegroundColor Cyan
