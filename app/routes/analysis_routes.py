import os
import json
import base64
from datetime import datetime
from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict
from weasyprint import HTML
from ..database import get_db
from .. import models, masking, llm_client
from ..config import settings
try:
    from weasyprint import HTML
    HAS_WEASYPRINT = True
except (ImportError, OSError):
    HAS_WEASYPRINT = False
from xhtml2pdf import pisa
from io import BytesIO

router = APIRouter()

# Request/Response Models

class MaskingData(BaseModel):
    # Accept both English (from new React frontend) and Italian field names
    numero_polizza: Optional[str] = ""
    contraente: Optional[str] = ""
    partita_iva: Optional[str] = ""
    codice_fiscale: Optional[str] = ""
    assicurato: Optional[str] = ""
    altri: Optional[str] = ""
    
    # Aliases to accept English field names from React frontend
    policyNumber: Optional[str] = None
    contractor: Optional[str] = None
    vat: Optional[str] = None
    fiscalCode: Optional[str] = None
    insured: Optional[str] = None
    other: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    cap: Optional[str] = None
    
    def get_numero_polizza(self):
        return self.policyNumber or self.numero_polizza or ""
    def get_contraente(self):
        return self.contractor or self.contraente or ""
    def get_partita_iva(self):
        return self.vat or self.partita_iva or ""
    def get_codice_fiscale(self):
        return self.fiscalCode or self.codice_fiscale or ""
    def get_assicurato(self):
        return self.insured or self.assicurato or ""
    def get_altri(self):
        return self.other or self.altri or ""
    def get_address(self):
        return self.address or ""
    def get_city(self):
        return self.city or ""
    def get_cap(self):
        return self.cap or ""

class StartAnalysisRequest(BaseModel):
    document_ids: List[int]
    policy_type: str = "rc_generale"  # incendio | rc_generale | trasporti
    analysis_level: str = "cliente"  # cliente | compagnia
    masking_data: Optional[MaskingData] = None
    skip_masking: bool = False
    llm_model: Optional[str] = None

class AnalysisResponse(BaseModel):
    analysis_id: int
    status: str
    policy_type: str
    analysis_level: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    report_html: Optional[str] = None
    report_html_masked: Optional[str] = None  # CRITICAL: Was missing!
    error: Optional[str] = None
    title: Optional[str] = None  # For display in dashboard

class AnalysisListItem(BaseModel):
    analysis_id: int
    status: str
    policy_type: str
    analysis_level: str
    title: Optional[str] = None
    is_saved: bool
    created_at: datetime
    completed_at: Optional[datetime] = None

class StartAnalysisResponse(BaseModel):
    analysis_id: int
    status: str
    message: str

class CorrectionRequest(BaseModel):
    correction_message: str

# Section dependency mapping - when a section is corrected, which sections need regeneration
SECTION_DEPENDENCIES = {
    "indirizzo": ["ubicazioni", "mappa", "cat-nat"],
    "ubicazione": ["ubicazioni", "mappa", "cat-nat"],
    "location": ["ubicazioni", "mappa", "cat-nat"],
    "somma": ["partite", "garanzie", "premio"],
    "capitale": ["partite", "garanzie", "premio"],
    "massimale": ["garanzie", "premio"],
    "polizza": ["anagrafica"],
    "contraente": ["anagrafica"],
    "copertura": ["garanzie", "esclusioni"],
    "esclusione": ["esclusioni"],
    "franchigia": ["garanzie"],
    "data": ["anagrafica"],
}


# Routes

@router.get("/", response_model=List[AnalysisListItem])
async def list_analyses(
    request: Request,
    saved_only: bool = False,
    db: Session = Depends(get_db)
):
    """List all analyses for the current user"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Get analyses with document_id (normal analyses)
    query = db.query(models.Analysis).outerjoin(models.Document, models.Analysis.document_id == models.Document.id).filter(
        models.Document.user_id == user_data["id"]
    )

    if saved_only:
        query = query.filter(models.Analysis.is_saved == True)
    else:
        # Dashboard view: default to showing only visible items
        # If specific filter params are added later, adjust here.
        # For now, Dashboard (saved_only=False) should imply show_in_dashboard=True.
        # However, checking if existing logic relies on listing everything?
        # User request implies dashboard should HIDE items.
        query = query.filter(models.Analysis.show_in_dashboard == True)

    normal_analyses = query.all()

    # Get comparisons (document_id is NULL, use source_document_ids)
    comp_query = db.query(models.Analysis).filter(
        models.Analysis.document_id == None,
        models.Analysis.source_document_ids != None
    )

    if saved_only:
        comp_query = comp_query.filter(models.Analysis.is_saved == True)

    comparisons = comp_query.all()

    # Filter comparisons by ownership (check if any document in source_document_ids belongs to user)
    user_comparisons = []
    for comp in comparisons:
        if comp.source_document_ids:
            try:
                doc_ids = json.loads(comp.source_document_ids)
                # Flatten if nested
                if isinstance(doc_ids[0], list):
                    doc_ids = [item for sublist in doc_ids for item in sublist]
                # Check if any document belongs to user
                doc = db.query(models.Document).filter(
                    models.Document.id.in_(doc_ids),
                    models.Document.user_id == user_data["id"]
                ).first()
                if doc:
                    user_comparisons.append(comp)
            except:
                pass

    # Combine and sort
    analyses = normal_analyses + user_comparisons
    analyses.sort(key=lambda a: a.created_at, reverse=True)
    
    return [
        AnalysisListItem(
            analysis_id=a.id,
            status=a.status.value if a.status else "unknown",
            policy_type=a.policy_type or "",
            analysis_level=a.prompt_level or "",
            title=a.title,
            is_saved=a.is_saved or False,
            created_at=a.created_at,
            completed_at=a.completed_at
        )
        for a in analyses
    ]

@router.post("/start", response_model=StartAnalysisResponse)
async def start_analysis(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: StartAnalysisRequest,
    db: Session = Depends(get_db)
):
    """Start a new analysis on selected documents"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Validate documents exist and belong to user
    docs = db.query(models.Document).filter(
        models.Document.id.in_(payload.document_ids),
        models.Document.user_id == user_data["id"]
    ).all()
    
    if not docs:
        raise HTTPException(status_code=404, detail="Documents not found")
    
    if len(docs) != len(payload.document_ids):
        raise HTTPException(status_code=404, detail="Some documents not found")
    
    # Check all documents are ready
    for doc in docs:
        if not doc.extracted_text_path or not os.path.exists(doc.extracted_text_path):
            raise HTTPException(
                status_code=400, 
                detail=f"Document {doc.original_filename} is still processing"
            )
    
    # Order documents as requested
    docs_map = {d.id: d for d in docs}
    ordered_docs = [docs_map[d_id] for d_id in payload.document_ids if d_id in docs_map]
    primary_doc = ordered_docs[0]
    
    # 🔒 CRITICAL SECURITY: Validate document_ids before JSON serialization
    # Prevents SQL injection via malicious JSON payload
    if not all(isinstance(x, int) and x > 0 for x in payload.document_ids):
        raise HTTPException(
            status_code=400, 
            detail="Invalid document IDs: must be positive integers"
        )
    
    # Determine model to use
    selected_model = payload.llm_model
    if not selected_model:
        # Fetch from SystemSettings
        settings_obj = db.query(models.SystemSettings).first()
        if settings_obj and settings_obj.llm_model_name:
            selected_model = settings_obj.llm_model_name
        else:
             # Fallback default if no settings exist
            selected_model = "gemini-3-flash-preview"
        
    # Fix: Sanitize model name if loaded from DB (handle underscore vs dash)
    if selected_model and "gemini" in selected_model and "_" in selected_model:
        selected_model = selected_model.replace("_", "-")

    # Create Analysis record
    analysis = models.Analysis(
        document_id=primary_doc.id,
        source_document_ids=json.dumps(payload.document_ids),  # Now safe to serialize
        status=models.AnalysisStatus.ANALYZING,
        policy_type=payload.policy_type,
        prompt_level=payload.analysis_level,
        llm_model=selected_model,
        masking_skipped=payload.skip_masking
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    
    # Prepare masking data (use getters to handle both EN/IT field names)
    sensitive_data = {}
    if payload.masking_data:
        md = payload.masking_data
        altri_raw = md.get_altri()
        # Support both semicolon and newline separators
        import re
        altri_list = []
        if altri_raw:
            # Split by ; or newline
            altri_list = [x.strip() for x in re.split(r'[;\n]', altri_raw) if x.strip()]
        sensitive_data = {
            'numero_polizza': md.get_numero_polizza(),
            'contraente': md.get_contraente(),
            'partita_iva': md.get_partita_iva(),
            'codice_fiscale': md.get_codice_fiscale(),
            'assicurato': md.get_assicurato(),
            'indirizzo': md.get_address(),
            'citta': md.get_city(),
            'cap': md.get_cap(),
            'altri': altri_list
        }
    
    # Run analysis in background
    background_tasks.add_task(
        full_analysis_pipeline,
        analysis.id,
        payload.document_ids,
        sensitive_data,
        payload.skip_masking,
        payload.analysis_level,
        payload.policy_type,
        payload.llm_model,
        user_data["id"]  # Pass user ID for token tracking
    )
    
    return StartAnalysisResponse(
        analysis_id=analysis.id,
        status="processing",
        message="Analysis started. Poll GET /api/analysis/{id} for results."
    )

@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db)
):
    """Get analysis status and result"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Verify ownership
    doc = db.query(models.Document).filter(models.Document.id == analysis.document_id).first()
    if doc and doc.user_id != user_data["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return AnalysisResponse(
        analysis_id=analysis.id,
        status=analysis.status.value if analysis.status else "unknown",
        policy_type=analysis.policy_type or "",
        analysis_level=analysis.prompt_level or "",
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        report_html=analysis.report_html_display,
        report_html_masked=analysis.report_html_masked,
        error=analysis.error_message
    )

@router.get("/{analysis_id}/html")
async def get_analysis_html(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db)
):
    """Get raw HTML report (for iframe embedding)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    if not analysis.report_html_display:
        raise HTTPException(status_code=404, detail="Report not ready")
    
    return Response(
        content=analysis.report_html_display,
        media_type="text/html"
    )

@router.get("/{analysis_id}/download-html")
def download_analysis_html(
    request: Request,
    analysis_id: int,
    type: str = "clear",  # "clear" or "masked"
    db: Session = Depends(get_db)
):
    """Download HTML report as file (clear or masked version)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Select HTML content based on type
    if type == "masked":
        html_content = analysis.report_html_masked
        suffix = "_mascherato"
    else:
        html_content = analysis.report_html_display
        suffix = "_chiaro"
    
    if not html_content:
        raise HTTPException(status_code=404, detail="Report content not ready")
    
    # Generate filename
    filename = f"Insurance-Lab.ai_Report_{analysis_id}{suffix}.html"
    if analysis.title:
        safe_title = "".join([c for c in analysis.title if c.isalnum() or c in (' ', '-', '_')]).strip()
        filename = f"{safe_title}{suffix}.html"
    
    return Response(
        content=html_content,
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/{analysis_id}/pdf")
def download_analysis_pdf(
    request: Request,
    analysis_id: int,
    type: str = "clear",  # "clear" or "masked"
    db: Session = Depends(get_db)
):
    """Generate and download PDF report (clear or masked version)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Select HTML content based on type
    if type == "masked":
        html_content = analysis.report_html_masked
        suffix = "_mascherato"
    else:
        html_content = analysis.report_html_display
        suffix = "_chiaro"
    
    if not html_content:
        raise HTTPException(status_code=404, detail="Report content not ready")
    
    # Generate filename (include suffix for clear/masked)
    filename = f"Insurance-Lab.ai_Report_{analysis_id}{suffix}.pdf"
    if analysis.title:
        safe_title = "".join([c for c in analysis.title if c.isalnum() or c in (' ', '-', '_')]).strip()
        filename = f"{safe_title}{suffix}.pdf"



    # Inject Logo for PDF Cover
    try:
        # Use direct path from app root
        # logo_path = "/app/static/img/logo-white.png" # Linux/Docker only
        logo_path = os.path.join(os.getcwd(), "static", "img", "logo-white.png")

        if os.path.exists(logo_path):
            with open(logo_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                logo_src = f"data:image/png;base64,{encoded_string}"
                # Replace placeholder if exists, or prep for cover page injection
                html_content = html_content.replace("[LOGO_IMG]", logo_src)
                print(f"DEBUG: Logo injected from {logo_path}")
        else:
            print(f"WARNING: Logo not found at {logo_path}")
    except Exception as e:
        print(f"Error injecting logo: {e}")

    # Inject Server-Side Chart for PDF (Matplotlib)
    try:
        # Import chart generation module locally to avoid circular imports or issues if unavailable
        from ..charts import generate_bar_chart
        import re

        # Initialize default chart data
        chart_labels = ['Anno 1', 'Anno 2', 'Anno 3']
        chart_datasets = [
            {
                'label': 'Premio Imponibile',
                'data': [0, 0, 0],
                'color': '#36A2EB'
            },
            {
                'label': 'Sinistri Pagati',
                'data': [0, 0, 0],
                'color': '#FF6384'
            }
        ]

        # Robust Data Extraction for Chart
        # We look for the JavaScript arrays injected by the prompt logic:
        # labels: ['2023', '2024'], data: [15000, 16000], etc.

        try:
            # Extract Labels: labels: ['2023', '2024']
            labels_match = re.search(r"labels:\s*\[(.*?)\]", html_content)
            if labels_match:
                labels_str = labels_match.group(1)
                chart_labels = [label.strip().strip("'").strip('"') for label in labels_str.split(',')]

            # Extract Premi: label: 'Premio Imponibile', data: [1000, 2000]
            premi_match = re.search(r"label:\s*['\"]Premio.*?['\"],\s*data:\s*\[(.*?)\]", html_content, re.DOTALL)
            if premi_match:
                premi_data_str = premi_match.group(1)
                chart_datasets[0]["data"] = [float(x.strip()) for x in premi_data_str.split(',') if x.strip()]

            # Extract Sinistri: label: 'Sinistri Pagati', data: [0, 500]
            sinistri_match = re.search(r"label:\s*['\"]Sinistri.*?['\"],\s*data:\s*\[(.*?)\]", html_content, re.DOTALL)
            if sinistri_match:
                sinistri_data_str = sinistri_match.group(1)
                chart_datasets[1]["data"] = [float(x.strip()) for x in sinistri_data_str.split(',') if x.strip()]

            print(f"DEBUG: Extracted Chart Data - Labels: {chart_labels}, Premi: {chart_datasets[0]['data']}, Sinistri: {chart_datasets[1]['data']}")

        except Exception as e:
            print(f"Error extracting chart data via regex: {e}")
            # Fallback to defaults already initialized

        # Generate the chart image
        try:
            chart_base64 = generate_bar_chart(
                labels=chart_labels,
                datasets=chart_datasets,
                title="Storico Premi e Sinistri (Anteprima PDF)",
                y_label="Importo (€)"
            )
            
            # Inject the chart
            html_content = html_content.replace("[CHART_IMG_SRC]", chart_base64)
            
        except Exception as e:
             print(f"Error generating PDF chart image: {e}")

    except Exception as e:
        print(f"Error generating PDF chart: {e}")


    # Generate PDF using WeasyPrint
    # Generate PDF using WeasyPrint with Fallback to xhtml2pdf
    pdf_bytes = None
    
    if HAS_WEASYPRINT:
        try:
            pdf_bytes = HTML(string=html_content).write_pdf()
        except Exception as e:
            print(f"WeasyPrint runtime error: {e}. Falling back to xhtml2pdf.")
            # Fallback will trigger below
            pdf_bytes = None

    if pdf_bytes is None:
        try:
            print("Generating PDF with xhtml2pdf...")
            buffer = BytesIO()
            pisa_status = pisa.CreatePDF(html_content, dest=buffer)
            if not pisa_status.err:
                pdf_bytes = buffer.getvalue()
            else:
                print("xhtml2pdf error")
                raise Exception("PDF generation failed with both engines")
        except Exception as e:
            print(f"xhtml2pdf Exception: {e}")
            raise HTTPException(status_code=500, detail=f"PDF Generation failed: {str(e)}")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

class UpdateAnalysisContentRequest(BaseModel):
    html_content: str

@router.post("/{analysis_id}/content")
async def update_analysis_content(
    request: Request,
    analysis_id: int,
    payload: UpdateAnalysisContentRequest,
    db: Session = Depends(get_db)
):
    """Update report HTML content (for user edits)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Check if html_content is valid
    if not payload.html_content or len(payload.html_content) < 100:
        raise HTTPException(status_code=400, detail="Invalid HTML content")
    
    analysis.report_html_display = payload.html_content
    analysis.last_updated = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": "Report updated"}

class SaveRequest(BaseModel):
    title: Optional[str] = None

@router.post("/{analysis_id}/save")
async def save_analysis(
    request: Request,
    analysis_id: int,
    payload: SaveRequest,
    db: Session = Depends(get_db)
):
    """Mark analysis as saved (archive)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    print(f"DEBUG Archive: Saving analysis {analysis_id}, title={payload.title}")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        print(f"ERROR Archive: Analysis {analysis_id} not found")
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    try:
        analysis.is_saved = True
        if payload.title:
            analysis.title = payload.title
        analysis.last_updated = datetime.utcnow()
        db.commit()
        db.refresh(analysis)
        
        print(f"SUCCESS Archive: Analysis {analysis_id} saved with title '{analysis.title}', is_saved={analysis.is_saved}")
        
        return {"status": "success", "message": "Analysis saved to archive"}
    except Exception as e:
        db.rollback()
        print(f"ERROR Archive: Database commit failed - {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save analysis: {str(e)}")

@router.delete("/{analysis_id}")
async def delete_analysis(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db)
):
    """Delete an analysis"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Verify ownership
    doc = db.query(models.Document).filter(models.Document.id == analysis.document_id).first()
    if doc and doc.user_id != user_data["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Delete masked text file if exists
    if analysis.masked_text_path and os.path.exists(analysis.masked_text_path):
        os.remove(analysis.masked_text_path)
    
    db.delete(analysis)
    db.commit()
    
    return {"status": "success", "message": "Analysis deleted"}

@router.post("/{analysis_id}/dismiss")
async def dismiss_analysis_from_dashboard(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db)
):
    """Hide analysis from dashboard without deleting it (if archived/saved)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Verify ownership
    doc = db.query(models.Document).filter(models.Document.id == analysis.document_id).first()
    if doc and doc.user_id != user_data["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
        
    analysis.show_in_dashboard = False
    db.commit()
    
    return {"status": "success", "message": "Analysis hidden from dashboard"}


# Background Analysis Pipeline (unchanged core logic)

def full_analysis_pipeline(
    analysis_id: int,
    doc_ids_list: List[int],
    sensitive_data: dict,
    is_skipped: bool,
    analysis_level: str,
    policy_type: str,
    llm_model: str,
    user_id: int
):
    from ..database import SessionLocal
    db = SessionLocal()
    
    try:
        analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
        if not analysis:
            return
        
        # 1. Combine Text
        docs = db.query(models.Document).filter(models.Document.id.in_(doc_ids_list)).all()
        docs_map = {d.id: d for d in docs}
        ordered_docs = [docs_map[d_id] for d_id in doc_ids_list if d_id in docs_map]
        
        original_text = ""
        total_tokens = 0
        
        for doc in ordered_docs:
            if doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
                with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    original_text += f"\n\n--- DOCUMENTO: {doc.original_filename} ---\n\n"
                    original_text += content
                total_tokens += doc.token_count or 0
        
        original_text = original_text.strip()
        analysis.total_tokens = total_tokens
        db.commit()
        
        # 2. Masking
        masked_text = original_text
        reverse_mapping = {}
        
        if not is_skipped and sensitive_data:
            masked_text, _, reverse_mapping = masking.mask_document(original_text, sensitive_data)
        
        # 3. Save Masked Text
        primary_doc = ordered_docs[0]
        masked_filename = f"{primary_doc.stored_filename}.combined.masked.txt"
        masked_path = os.path.join("outputs", masked_filename)
        os.makedirs("outputs", exist_ok=True)
        
        with open(masked_path, "w", encoding="utf-8") as f:
            f.write(masked_text)
        
        analysis.masked_text_path = masked_path
        analysis.reverse_mapping_json = masking.serialize_mapping(reverse_mapping)
        db.commit()
        
        # 4. LLM Analysis
        safe_policy_type = ''.join(c for c in policy_type if c.isalnum() or c in ('_', '-'))
        if not safe_policy_type:
            safe_policy_type = "rc_generale"
        
        # Determina la cartella base e il tipo di polizza
        if analysis_level == "sinistro":
            base_folder = "analisi_sinistri"
            # Rimuovi "rc_generale" -> "rc" per sinistri
            folder_type = safe_policy_type.replace("rc_generale", "rc")
            # Nuova convenzione: prompt_sinistro_{type}.txt
            prompt_path = f"prompts/{base_folder}/{folder_type}/prompt_sinistro_{folder_type}.txt"
            template_path = f"prompts/{base_folder}/{folder_type}/template_sinistro_{folder_type}.html"
            
        elif safe_policy_type == "analisi_economica":
            base_folder = "analisi_economica"
            folder_type = "standard" # Default folder for now
            # Naming convention: prompt_{type}_{variant}.txt
            prompt_path = f"prompts/{base_folder}/{folder_type}/prompt_analisi_economica_standard.txt"
            template_path = f"prompts/{base_folder}/{folder_type}/template_analisi_economica_standard.html"
        elif safe_policy_type == "analisi_capitolati":
            base_folder = "analisi_capitolati"
            folder_type = "standard" # Default folder for now
            prompt_path = f"prompts/{base_folder}/{folder_type}/prompt_analisi_capitolati.txt"
            template_path = f"prompts/{base_folder}/{folder_type}/template_analisi_capitolati.html"
        else:
            base_folder = "analisi_polizze"
            folder_type = safe_policy_type
            # Nuova convenzione: prompt_{type}_{level}.txt
            prompt_path = f"prompts/{base_folder}/{folder_type}/prompt_{folder_type}_{analysis_level}.txt"
            template_path = f"prompts/{base_folder}/{folder_type}/template_{folder_type}_{analysis_level}.html"
        
        # Fallback per file non trovati
        if not os.path.exists(prompt_path):
            # Prova con nome generico base.txt
            fallback_prompt = f"prompts/{base_folder}/{folder_type}/base.txt"
            if os.path.exists(fallback_prompt):
                prompt_path = fallback_prompt
            else:
                print(f"WARNING: Prompt file not found: {prompt_path}")
        
        if not os.path.exists(template_path):
            # Prova con nome generico template.html
            fallback_template = f"prompts/{base_folder}/{folder_type}/template.html"
            if os.path.exists(fallback_template):
                template_path = fallback_template
            else:
                print(f"WARNING: Template file not found: {template_path}")
        
        print(f"DEBUG: Using prompt: {prompt_path}")
        print(f"DEBUG: Using template: {template_path}")
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        
        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
        
        client = llm_client.LLMClient(model_name=llm_model)
        report_masked, report_display, input_tokens, output_tokens = client.analyze(
            document_text=masked_text,
            prompt_template=prompt_template,
            html_template=html_template,
            reverse_mapping=reverse_mapping if not is_skipped else None,
            template_path=template_path
        )
        
        # 5. Complete
        analysis.report_html_masked = report_masked
        analysis.report_html_display = report_display
        analysis.status = models.AnalysisStatus.COMPLETED
        analysis.completed_at = datetime.utcnow()
        analysis.total_tokens = input_tokens + output_tokens  # Total for analysis
        analysis.input_tokens = input_tokens  # Store input tokens separately
        analysis.output_tokens = output_tokens  # Store output tokens separately
        
        # 6. Update user's token counters (separate for cost calculation)
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user:
            user.total_input_tokens = (user.total_input_tokens or 0) + input_tokens
            user.total_output_tokens = (user.total_output_tokens or 0) + output_tokens
            user.total_tokens_used = (user.total_tokens_used or 0) + input_tokens + output_tokens
            
            # Calculate cost for logging
            input_cost = (input_tokens / 1_000_000) * 0.50
            output_cost = (output_tokens / 1_000_000) * 3.00
            total_cost = input_cost + output_cost
            
            print(f"DEBUG: Updated user {user_id} tokens: input +{input_tokens}, output +{output_tokens}")
            print(f"DEBUG: This analysis cost: ${total_cost:.4f} (input: ${input_cost:.4f}, output: ${output_cost:.4f})")
        
        db.commit()
        
        print(f"DEBUG: Analysis {analysis_id} completed. Report size: {len(report_display or '')} chars. Tokens: {input_tokens}+{output_tokens}")
        
    except Exception as e:
        print(f"Analysis Pipeline Error: {e}")
        import traceback
        traceback.print_exc()
        
        if analysis:
            analysis.status = models.AnalysisStatus.ERROR
            analysis.error_message = str(e)
            try:
                db.commit()
            except:
                pass
    finally:
        db.close()
        print(f"DEBUG: Background Analysis Task Finished. ID={analysis_id}")


@router.post("/{analysis_id}/correct")
async def correct_analysis(
    analysis_id: int,
    correction: CorrectionRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Apply a correction to an analysis and regenerate affected sections"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the analysis
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Get original extracted text from documents
    doc_ids = []
    if analysis.source_document_ids:
        try:
            raw_ids = json.loads(analysis.source_document_ids)
            # Fix: Flatten if nested (e.g. for comparisons [[1,2], [3]])
            if raw_ids and isinstance(raw_ids[0], list):
                doc_ids = [item for sublist in raw_ids for item in sublist]
            else:
                doc_ids = raw_ids
        except:
            pass
            
    if analysis.document_id and analysis.document_id not in doc_ids:
        doc_ids.append(analysis.document_id)
    
    original_text = ""
    if doc_ids:
        # Preserve order
        documents = db.query(models.Document).filter(models.Document.id.in_(doc_ids)).all()
        doc_map = {d.id: d for d in documents}
        
        # Load text from extracted_text_path files
        for d_id in doc_ids:
            doc = doc_map.get(d_id)
            if doc and doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
                try:
                    with open(doc.extracted_text_path, 'r', encoding='utf-8') as f:
                        original_text += f"\n--- FILE: {doc.original_filename} ---\n" + f.read() + "\n\n"
                except Exception as e:
                    print(f"Error loading text from {doc.extracted_text_path}: {e}")
    
    # Use masked version for LLM to protect sensitive data
    current_html = analysis.report_html_masked or analysis.report_html_display or ""
    
    # Identify which sections need regeneration based on keywords in correction message
    correction_lower = correction.correction_message.lower()
    sections_to_update = set()
    
    for keyword, sections in SECTION_DEPENDENCIES.items():
        if keyword in correction_lower:
            sections_to_update.update(sections)
    
    # If no specific sections identified, regenerate all
    if not sections_to_update:
        sections_to_update = {"all"}
    
    sections_list = list(sections_to_update)
    
    # Build correction prompt
    correction_prompt = f"""
SEI UN SISTEMA DI CORREZIONE CHIRURGICA DEI REPORT.
L'utente ha segnalato il seguente errore nel report generato:
"{correction.correction_message}"

TESTO ORIGINALE ESTRATTO DAL DOCUMENTO:
{original_text[:25000]}  

REPORT HTML ATTUALE (DA PRESERVARE IL PIÙ POSSIBILE):
{current_html[:50000] if len(current_html) > 50000 else current_html}

ISTRUZIONI CRITICHE:
1. Analizza la richiesta di correzione.
2. Identifica ESATTAMENTE quale parte dell'HTML necessita di modifica.
3. Applica la modifica SOLAMENTE ai dati errati, basandoti sul TESTO ORIGINALE.
4. COPIA IL RESTO DEL REPORT ESATTAMENTE COME È (VERBATIM). Non cambiare stile, non cambiare parole, non cambiare formattazione nelle parti non coinvolte.

AMBITO DI MODIFICA STIMATO: {', '.join(sections_list) if 'all' not in sections_list else 'INTERO DOCUMENTO (Solo se strettamente necessario)'}

OUTPUT OBBLIGATORIO:
- Restituisci l'INTERO codice HTML del report.
- Il codice deve essere IDENTICO all'originale tranne per la correzione puntuale richiesta.
- NON USARE MARKDOWN (```html), restituisci SOLO il testo grezzo.
"""
    
    try:
        # Determine model: Prioritize analysis specific, then SystemSettings, then default
        model_name = analysis.llm_model
        
        if not model_name:
            settings_obj = db.query(models.SystemSettings).first()
            if settings_obj and settings_obj.llm_model_name:
                model_name = settings_obj.llm_model_name
        
        # Default if everything fails
        model_name = model_name or "gemini-3-flash-preview"

        # Fix: Sanitize model name (handle legacy underscores)
        if "gemini" in model_name and "_" in model_name:
            model_name = model_name.replace("_", "-")

        # Create LLM client
        from ..llm_client import LLMClient
        client = LLMClient(model_name=model_name)
        
        # Use generate_content directly for correction
        import google.generativeai as genai
        # Increase safety for corrections
        generation_config = genai.GenerationConfig(
            temperature=0.2,
            max_output_tokens=65536,
        )
        
        print(f"DEBUG Correction: Using model {model_name} for correction.")

        response = client.model.generate_content(
            correction_prompt,
            generation_config=generation_config,
            stream=True
        )
        
        # Collect streamed response
        updated_html = ""
        for chunk in response:
            if chunk.text:
                updated_html += chunk.text
        
        # Clean up the response
        updated_html = client._strip_markdown_wrappers(updated_html)
        
        # Save Masked Version first
        analysis.report_html_masked = updated_html
        
        # Repopulate with real data (Unmasking) for display
        # Load reverse mapping if exists
        report_display = updated_html
        if analysis.reverse_mapping_json:
            try:
                reverse_mapping = json.loads(analysis.reverse_mapping_json)
                report_display = masking.repopulate_report(updated_html, reverse_mapping)
            except Exception as e:
                print(f"Error repopulating correction: {e}")
        
        # Update the analysis in database
        analysis.report_html_display = report_display
        analysis.last_updated = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": f"Correzione applicata. Sezioni aggiornate: {', '.join(sections_list)}",
            "updated_sections": sections_list,
            "updated_html": report_display
        }
        
    except Exception as e:
        print(f"Error applying correction: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore nell'applicare la correzione: {str(e)}")

