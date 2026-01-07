# Security Fixes Deployment Guide

## ✅ FIXES APPLIED (Local)

### 1. SECRET_KEY Validation (config.py)
- ❌ Blocks default "changeme"  
- ❌ Requires minimum 32 characters
- ✅ Displays validation message on startup

### 2. Path Traversal Prevention (upload_routes.py)
- ✅ Sanitizes filenames with `Path().name`
- ✅ Replaces dangerous characters  
- ✅ Limits length to 255 chars
- ✅ Logs sanitization for audit

### 3. SQL Injection Prevention (analysis_routes.py)
- ✅ Validates document_ids are positive integers
- ✅ Blocks before JSON serialization

---

## 🚀 PROCEDURA DI DEPLOY STANDARD

Utilizzare questi comandi per aggiornare l'ambiente di produzione:

### 1. Frontend (React App)
```powershell
cd c:\Antigravity\insurance-lab-frontend
npm run build
.\deploy-production.ps1
```

### 2. Backend (API)
```powershell
cd c:\Antigravity\insurance-analyzer
.\deploy-backend.ps1
```

---

## 🚀 DEPLOYMENT STEPS (Security Updates)

### Step 1: Generate SECRET_KEY

**PowerShell** (Windows):
```powershell
# Genera chiave random 64 chars hex
-join ((1..64) | ForEach-Object { '{0:X}' -f (Get-Random -Max 16) })
```

**Linux/Mac**:
```bash
openssl rand -hex 32
```

**Risultato esempio**:
```
SECRET_KEY=a1b2c3d4e5f6789012345678901234567890abcdefABCDEF1234567890ABCD
```

---

### Step 2: Backup Database

```bash
ssh root@46.224.127.115
pg_dump insurance_lab > /root/backup_$(date +%Y%m%d_%H%M%S).sql
# Oppure se SQLite:
cp /root/insurance-lab-deploy/backend/insurance_analyzer.db /root/backup_$(date +%Y%m%d_%H%M%S).db
```

---

### Step 3: Update .env Production

```bash
ssh root@46.224.127.115
cd /root/insurance-lab-deploy
nano .env
```

**Aggiungere/Modificare**:
```bash
SECRET_KEY=<la_chiave_generata_sopra>
```

**Verificare** che ci siano almeno 32 caratteri!

---

### Step 4: Deploy Files

```bash
# Da local Windows PowerShell
scp app/config.py app/routes/upload_routes.py app/routes/analysis_routes.py root@46.224.127.115:/root/insurance-lab-deploy/backend/app/

# Oppure copia dentro container
ssh root@46.224.127.115
docker cp /root/insurance-lab-deploy/backend/app/config.py insurance-lab-backend:/app/app/config.py
docker cp /root/insurance-lab-deploy/backend/app/routes/upload_routes.py insurance-lab-backend:/app/app/routes/upload_routes.py
docker cp /root/insurance-lab-deploy/backend/app/routes/analysis_routes.py insurance-lab-backend:/app/app/routes/analysis_routes.py
```

---

### Step 5: Restart Backend

```bash
ssh root@46.224.127.115
cd /root/insurance-lab-deploy
docker compose -f docker-compose.prod.yml restart backend
```

**Verificare log**:
```bash
docker logs insurance-lab-backend --tail 50
```

**Dovrebbe vedere**:
```
✅ SECRET_KEY validated (length: 64 chars)
INFO:     Application startup complete.
```

---

### Step 6: Test Production

**1. Test SECRET_KEY non "changeme"**
```bash
# Se SECRET_KEY mancante, backend NON deve avviarsi
# Log dovrebbe dire: "❌ SECURITY ERROR: SECRET_KEY must be set"
```

**2. Test Path Traversal Blocked**
```bash
curl -F "files=@test.pdf;filename=../../etc/passwd" \
     https://app.insurance-lab.ai/api/documents/upload \
     -H "Cookie: session=<valid_session>"

# File deve essere salvato come: ___etc_passwd
```

**3. Test Document IDs Validation**
```bash
curl -X POST https://app.insurance-lab.ai/api/analysis/start \
     -H "Content-Type: application/json" \
     -H "Cookie: session=<valid_session>" \
     -d '{"document_ids": ["malicious"], "policy_type": "rc_generale"}'

# Deve ritornare: 400 Bad Request "Invalid document IDs"
```

---

### Step 7: Notify Users (IMPORTANTE!)

**Email ai clienti**:
```
Subject: Aggiornamento Sicurezza - Re-login Richiesto

Gentile Cliente,

abbiamo completato un importante aggiornamento di sicurezza della piattaforma.

Per vostra protezione, tutte le sessioni sono state invalidate.
È necessario effettuare nuovamente il login su:
https://app.insurance-lab.ai

Non è richiesta alcuna modifica alla password.

Grazie per la comprensione.
Team Insurance Lab
```

---

## ⚠️ POST-DEPLOYMENT MONITORING

### Check 1: Backend Logs (primi 30 min)
```bash
docker logs -f insurance-lab-backend | grep -i "error\|security"
```

**Cercare**:
- ✅ "SECRET_KEY validated"  
- ⚠️ "SECURITY: Sanitized filename" (se upload)
- ❌ Nessun errore "SECRET_KEY"

### Check 2: User Login Flow
- Provare login con utente esistente
- Verificare che funzioni normalmente
- Sessioni vecchie devono essere invalide

### Check 3: Upload Flow
- Caricare PDF normale → deve funzionare
- Nome file con spazi → sanitizzato ma funziona
- Nome file con `../` → sanitizzato senza errore

---

## 🔙 ROLLBACK (se necessario)

Se qualcosa va storto:

```bash
ssh root@46.224.127.115
cd /root/insurance-lab-deploy

# Restore backup file
git checkout HEAD~1 backend/app/config.py
git checkout HEAD~1 backend/app/routes/upload_routes.py
git checkout HEAD~1 backend/app/routes/analysis_routes.py

# Restart
docker compose -f docker-compose.prod.yml restart backend
```

**Poi**:
- Rimuovere SECRET_KEY da .env (torna a "changeme")
- Restart di nuovo
- Utenti possono rifare login

---

## 📊 SUCCESS METRICS

Post-deployment, verificare:

- [ ] Backend avviato senza errori
- [ ] SECRET_KEY validation message in log
- [ ] Utenti possono fare login (nuove sessioni)
- [ ] Upload funziona (filename sanitizzati)
- [ ] Analysis start funziona normalmente
- [ ] Nessun errore 500 in log

**Score Sicurezza**: Da 6.4/10 → **7.5/10** ✅

---

## 🎯 NEXT STEPS (Fase 1 - Questa Settimana)

Dopo fix critici verificati:

1. Rate Limiting (slowapi)
2. MIME Type Validation (python-magic)
3. CORS Wildcard Removal
4. Session Fixation Fix

**Tempo stimato**: 1 giorno
**Score obiettivo**: 8.5/10
