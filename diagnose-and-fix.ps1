# Diagnose and Fix Script (Robust)
# Usage: .\diagnose-and-fix.ps1

$VPS_IP = "46.224.127.115"
$VPS_USER = "root"
$CONTAINER = "insurance-lab-backend"
$LOCAL_OCR = "app/ocr.py"

Write-Host "🔍 STARTING DIAGNOSTICS & FIX..." -ForegroundColor Cyan

# 1. Check Disk Space
Write-Host "`n📊 Checking Disk Space on VPS..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "df -h / | grep '/'"
# If disk is > 90% full, that's the problem.

# 2. Check Memory/Container Status
Write-Host "`n🧠 Checking Container Status..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "docker stats ${CONTAINER} --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'"

# 3. Apply Patch
Write-Host "`n🚑 Applying Backend Patch..." -ForegroundColor Yellow

if (-Not (Test-Path $LOCAL_OCR)) {
    Write-Host "❌ Error: $LOCAL_OCR not found locally!" -ForegroundColor Red
    exit 1
}

# Upload ocr.py
Write-Host "  > Uploading optimized ocr.py..." -ForegroundColor Gray
scp $LOCAL_OCR "${VPS_USER}@${VPS_IP}:/tmp/ocr.py"
if ($LASTEXITCODE -ne 0) { Write-Host "❌ Upload failed"; exit 1 }

# Patch container
Write-Host "  > Injecting patch into container..." -ForegroundColor Gray
ssh "${VPS_USER}@${VPS_IP}" "docker cp /tmp/ocr.py ${CONTAINER}:/app/app/ocr.py"

# Fix Permissions
Write-Host "  > Fixing permissions on /app/uploads..." -ForegroundColor Gray
ssh "${VPS_USER}@${VPS_IP}" "docker exec -u root ${CONTAINER} chmod -R 777 /app/uploads /app/outputs"

# Restart
Write-Host "🔄 Restarting Backend Container..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "docker restart ${CONTAINER}"

# Cleanup
ssh "${VPS_USER}@${VPS_IP}" "rm /tmp/ocr.py"

Write-Host "`n✅ FIX APPLIED!" -ForegroundColor Green
Write-Host "Please try uploading a file again."
Write-Host "If it still fails, check the disk space output above." -ForegroundColor Cyan
