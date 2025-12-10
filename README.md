# Insurance Policy Analyzer

Applicazione web per l'analisi automatica di polizze assicurative RC (Responsabilità Civile) utilizzando AI (Google Gemini).

---

## 📋 Prerequisiti

### 1. Python 3.10+
Scarica da: https://www.python.org/downloads/
- Durante installazione: ✅ "Add Python to PATH"

### 2. Git (per versionamento)
Scarica da: https://git-scm.com/download/win
- Durante installazione: usa le opzioni di default
- Dopo installazione, apri CMD e verifica: `git --version`

### 3. API Key Gemini
1. Vai su https://aistudio.google.com/app/apikey
2. Clicca "Create API Key"
3. Copia la chiave

---

## 🚀 Installazione

### Prima Installazione (Nuovo PC)

```bash
# 1. Clona il repository (se usi Git)
git clone https://github.com/TUO_USERNAME/insurance-analyzer.git
cd insurance-analyzer

# OPPURE: Copia manualmente la cartella

# 2. Crea ambiente virtuale
python -m venv venv

# 3. Attiva ambiente virtuale
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 4. Installa dipendenze
pip install -r requirements.txt

# 5. Crea file .env
# Copia .env.example in .env e inserisci la tua API key
copy .env.example .env
# Modifica .env con un editor di testo
```

### File .env (esempio)
```
GEMINI_API_KEY=la_tua_chiave_api_qui
SECRET_KEY=cambiami_in_produzione
```

---

## ▶️ Avvio

```bash
# Attiva ambiente virtuale (se non già attivo)
venv\Scripts\activate

# Avvia il server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Apri nel browser
# http://127.0.0.1:8000
```

### Credenziali Default
- **Username:** `admin`
- **Password:** `changeme123`

---

## 📁 Struttura Progetto

```
insurance-analyzer/
├── app/
│   ├── routes/           # API endpoints
│   ├── templates/        # HTML templates (Jinja2)
│   ├── main.py          # FastAPI app
│   ├── models.py        # Database models
│   ├── llm_client.py    # Gemini AI client
│   └── masking.py       # Data masking utils
├── prompts/
│   └── rc_generale/
│       ├── base.txt             # Prompt base
│       ├── intermedio.txt       # Prompt intermedio
│       ├── avanzato.txt         # Prompt avanzato
│       ├── template_base.html   # Template HTML base
│       ├── template_intermedio.html
│       └── template_avanzato.html
├── static/               # CSS, JS
├── uploads/              # PDF caricati
├── outputs/              # Testi estratti
├── requirements.txt
├── .env                  # Configurazione (NON committare!)
└── data.db              # Database SQLite
```

---

## 🔧 Configurazione Livelli Analisi

L'app supporta 3 livelli di analisi, ognuno con prompt e template separati:

| Livello | Prompt | Template |
|---------|--------|----------|
| Base | `prompts/rc_generale/base.txt` | `template_base.html` |
| Intermedio | `prompts/rc_generale/intermedio.txt` | `template_intermedio.html` |
| Avanzato | `prompts/rc_generale/avanzato.txt` | `template_avanzato.html` |

Se un template specifico non esiste, viene usato `template.html` come fallback.

---

## 🔄 Backup e Sincronizzazione con Git

### Prima volta (sul PC originale)
```bash
cd insurance-analyzer
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/TUO_USER/insurance-analyzer.git
git push -u origin main
```

### Su un nuovo PC
```bash
git clone https://github.com/TUO_USER/insurance-analyzer.git
cd insurance-analyzer
# Segui i passi di installazione sopra
```

### Aggiornare il repository
```bash
# Dopo modifiche locali
git add .
git commit -m "Descrizione modifiche"
git push

# Per scaricare modifiche da altro PC
git pull
```

---

## ⚠️ File da NON committare

Aggiungi al `.gitignore`:
```
.env
data.db
uploads/
outputs/
venv/
__pycache__/
```

---

## 🐛 Troubleshooting

### Errore 504 Timeout
L'analisi di documenti grandi può richiedere 2-5 minuti. Il sistema usa streaming per evitare timeout.

### Errore GTK3 / WeasyPrint
Per generare PDF, installa GTK3:
- Windows: https://github.com/nickvergessen/gtk-for-windows-runtime-environment-installer/releases

### Database locked
Riavvia il server. L'app usa WAL mode per SQLite.

---

## 📝 Licenza

Uso interno / Progetto privato
