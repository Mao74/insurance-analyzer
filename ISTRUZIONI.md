# Walkthrough - Insurance Policy Analyzer MVP

## Prerequisites
Ensure Python 3.11+ is installed.

### System Dependencies
- **Tesseract OCR**: [Install Instructions](https://github.com/UB-Mannheim/tesseract/wiki) (Windows) or `sudo apt install tesseract-ocr` (Linux).
- **LibMagic**: Included in `python-magic-bin` for Windows, but checking `requirements.txt` is wise.

## Installation

1. **Navigate to the project directory** inside the `Antigravity` workspace:
   ```powershell
   cd insurance-analyzer
   ```

2. **Create and Activate Virtual Environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```
   *Note: creating the correct torch version for Doctr might require specific commands if default fails.*

4. **Environment Setup**:
   The `.env` file has been created for you. 
   **Open `.env` and paste your Gemini API Key**:
   ```ini
   GEMINI_API_KEY=your_real_api_key_here
   ```

5. **Initialize Database**:
   ```powershell
   python -c "from app.database import init_db; init_db()"
   ```
   This creates `insurance_analyzer.db` and default users (`admin`/`changeme123`).

## Running the Application

Start the FastAPI server:
```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## User Flow Verification

1. **Login**: Use `admin` / `changeme123`.
2. **Dashboard**: Verify empty state or recent analyses table.
3. **Upload**: 
   - Drag & Drop a PDF policy.
   - Click "Converti in TXT".
   - Wait for OCR (might take 10-30s first time for Doctr model download).
4. **Masking**:
   - Verify extracted text is shown.
   - Fill in "Contraente" or other fields to test masking.
   - Check "Ho verificato..." box.
   - Click "Analizza".
5. **Analysis**:
   - Wait for LLM processing (2-5s with Flash).
   - Verify redirect to Report page.
6. **Report**:
   - Check "Sintesi Esecutiva" and tables.
   - Verify "Metadata" in sidebar.
   - Test "Download PDF" (requires WeasyPrint dependencies).

## Troubleshooting
- **OCR Errors**: If Doctr fails, the system falls back to Tesseract. Ensure `tesseract` is in your PATH.
- **PDF Generation**: WeasyPrint on Windows requires GTK3. If it fails, use "Download HTML".
