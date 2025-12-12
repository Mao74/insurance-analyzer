# PoliSight - Guida Deployment Beta Test

## 🚀 Strategia di Deployment

### Opzione 1: URL "Nascosto" (Semplice ma non sicuro)
```
https://beta.polisight.ai
oppure
https://www.polisight.ai/beta-2024-secret
```
- ❌ **Problema**: Gli URL "nascosti" sono security by obscurity - non sicuri
- ❌ I motori di ricerca potrebbero indicizzarli

### Opzione 2: Accesso con Invito (Consigliata) ✅
```
https://app.polisight.ai
```
- ✅ **Registrazione disabilitata**: Solo inviti
- ✅ **Codice invito**: Per creare account (es. `BETA-2024-CLIENTE`)
- ✅ **Isolamento dati**: Già implementato - ogni utente vede solo i propri documenti

---

## 🔒 Sicurezza Dati

L'app **già implementa** l'isolamento:
- Ogni documento è collegato a `user_id`
- Le query filtrano per `user.id`
- L'admin non può vedere i dati degli altri (a meno che non acceda al DB diretto)

### Per maggiore protezione:
| Livello | Cosa fare |
|---------|-----------|
| **Base** | DB SQLite criptato o PostgreSQL con row-level security |
| **Medio** | Crittografia documenti a riposo (AES-256) |
| **Alto** | Zero-knowledge: chiave derivata dalla password utente |

---

## 🌐 Deployment Options

| Piattaforma | Pro | Contro | Costo |
|-------------|-----|--------|-------|
| **Railway.app** | Deploy 1-click, SSL auto | Limiti free tier | $5-20/mese |
| **Render.com** | Simile a Railway | Spin-down su free | $7-25/mese |
| **DigitalOcean App** | Affidabile | Più config | $12-20/mese |
| **VPS (Hetzner)** | Controllo totale | Devi gestire tutto | €4-10/mese |
| **AWS/GCP** | Enterprise-grade | Complesso | Variabile |

**Raccomandazione**: **Railway** o **Render** per iniziare (deploy in 10 minuti).

---

## 📋 Checklist Pre-Deploy

### 1. Variabili d'ambiente
- [ ] `SECRET_KEY` sicura (32+ caratteri random)
- [ ] `GEMINI_API_KEY` 
- [ ] `DATABASE_URL` (PostgreSQL in produzione)

### 2. Sicurezza
- [ ] HTTPS forzato
- [ ] Rate limiting
- [ ] Registrazione con invito

### 3. Storage
- [ ] Upload files su S3/Cloudflare R2 (non filesystem locale)

---

## 🔧 Passi Deploy su Railway (Esempio)

```bash
# 1. Crea account su railway.app
# 2. Connetti repo GitHub
# 3. Aggiungi variabili d'ambiente
# 4. Deploy automatico!
```

### Dockerfile (se necessario)
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements_fixed.txt .
RUN pip install -r requirements_fixed.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 📝 TODO per Produzione

1. **Sistema inviti**: Implementare codici invito per registrazione
2. **Crittografia documenti**: AES-256 per file a riposo
3. **PostgreSQL**: Migrare da SQLite
4. **Cloud Storage**: S3/R2 per uploads
5. **Logging**: Sentry o simile per errori
6. **Backup**: Automatici giornalieri

---

*Documento creato: 2024-12-11*
*Versione: 1.0*
