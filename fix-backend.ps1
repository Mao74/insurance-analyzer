# Update Backend Script
# Usage: .\update-backend.ps1

Write-Host "🚀 Updating Backend..." -ForegroundColor Cyan

$VPS_IP = "46.224.127.115"
$VPS_USER = "root"
$REMOTE_BACKEND_DIR = "/root/insurance-lab-deploy/backend"  # Guessed path based on frontend
# Note: If this path is wrong, the user will need to adjust it or we need to find it first.

# 1. Update Permissions (Fix hangs)
Write-Host "🔧 Fixing permissions on Uploads folder..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "docker exec -u root insurance-lab-backend chmod -R 777 /app/uploads /app/outputs || echo 'Container path might vary'"

# 2. Restart Backend (to clear memory leaks)
Write-Host "🔄 Restarting Backend Container..." -ForegroundColor Yellow
ssh "${VPS_USER}@${VPS_IP}" "docker restart insurance-lab-backend"

# 3. Check logs (Optional)
Write-Host "📊 Checking recent logs..." -ForegroundColor Cyan
ssh "${VPS_USER}@${VPS_IP}" "docker logs --tail 20 insurance-lab-backend"

Write-Host "✅ Backend restarted. Try uploading again." -ForegroundColor Green
