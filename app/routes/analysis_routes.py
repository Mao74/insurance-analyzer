import os
import json
from datetime import datetime
from playwright.sync_api import sync_playwright
from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict
from ..database import get_db
from .. import models, masking, llm_client
from ..config import settings

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

class StartAnalysisRequest(BaseModel):
    document_ids: List[int]
    policy_type: str = "rc_generale"  # incendio | rc_generale | trasporti
    analysis_level: str = "cliente"  # cliente | compagnia
    masking_data: Optional[MaskingData] = None
    skip_masking: bool = False
    llm_model: str = "gemini-2.5-flash"

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
    
    query = db.query(models.Analysis).join(models.Document).filter(
        models.Document.user_id == user_data["id"]
    )
    
    if saved_only:
        query = query.filter(models.Analysis.is_saved == True)
    
    analyses = query.order_by(models.Analysis.created_at.desc()).limit(50).all()
    
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
    
    # Create Analysis record
    analysis = models.Analysis(
        document_id=primary_doc.id,
        source_document_ids=json.dumps(payload.document_ids),
        status=models.AnalysisStatus.ANALYZING,
        policy_type=payload.policy_type,
        prompt_level=payload.analysis_level,
        llm_model=payload.llm_model,
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
        sensitive_data = {
            'numero_polizza': md.get_numero_polizza(),
            'contraente': md.get_contraente(),
            'partita_iva': md.get_partita_iva(),
            'codice_fiscale': md.get_codice_fiscale(),
            'assicurato': md.get_assicurato(),
            'altri': [x.strip() for x in altri_raw.split('\n') if x.strip()] if altri_raw else []
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
        payload.llm_model
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
    filename = f"PoliSight_Report_{analysis_id}{suffix}.html"
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
    filename = f"PoliSight_Report_{analysis_id}{suffix}.pdf"
    if analysis.title:
        safe_title = "".join([c for c in analysis.title if c.isalnum() or c in (' ', '-', '_')]).strip()
        filename = f"{safe_title}{suffix}.pdf"
    
    base_url = str(request.base_url)
    
    # Use Playwright for PDF generation
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        
        # Inject base tag
        if "<head>" in html_content:
            html_content = html_content.replace("<head>", f'<head><base href="{base_url}">')
        else:
            html_content = f'<base href="{base_url}">' + html_content
        
        page.set_content(html_content, wait_until="networkidle")
        
        # Print CSS
        page.add_style_tag(content="""
            @page { margin: 15mm 10mm; size: A4; }
            body { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
            .tab-content { display: block !important; opacity: 1 !important; visibility: visible !important; height: auto !important; margin-bottom: 20px; }
            .tabs, .header-navigation, #edit-toolbar, .print-btn, .btn, button, .navbar { display: none !important; }
            h1, h2, h3, h4, h5, h6 { page-break-after: avoid; break-after: avoid; }
            .card, .section { page-break-inside: avoid; break-inside: avoid; }
            table { width: 100% !important; border-collapse: collapse; }
            td, th { padding: 6px 4px; font-size: 9pt; vertical-align: top; word-wrap: break-word; border: 1px solid #e2e8f0; }
            .report-container { max-width: 100% !important; width: 100% !important; border: none !important; box-shadow: none !important; }
        """)
        
        page.evaluate("() => { if(window.Chart) { Chart.defaults.animation = false; } }")
        page.wait_for_timeout(1000)
        
        pdf_data = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "15mm", "bottom": "15mm", "left": "10mm", "right": "10mm"}
        )
        
        browser.close()
    
    return Response(
        content=pdf_data,
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

@router.post("/{analysis_id}/save")
async def save_analysis(
    request: Request,
    analysis_id: int,
    title: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Mark analysis as saved (archive)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    analysis.is_saved = True
    if title:
        analysis.title = title
    analysis.last_updated = datetime.utcnow()
    db.commit()
    
    return {"status": "success", "message": "Analysis saved to archive"}

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


# Background Analysis Pipeline (unchanged core logic)

def full_analysis_pipeline(
    analysis_id: int,
    doc_ids_list: List[int],
    sensitive_data: dict,
    is_skipped: bool,
    analysis_level: str,
    policy_type: str,
    llm_model: str
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
        
        prompt_path = f"prompts/{safe_policy_type}/{analysis_level}.txt"
        if not os.path.exists(prompt_path):
            prompt_path = f"prompts/{safe_policy_type}/base.txt"
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        
        template_path = f"prompts/{safe_policy_type}/template_{analysis_level}.html"
        if not os.path.exists(template_path):
            template_path = f"prompts/{safe_policy_type}/template.html"
            if not os.path.exists(template_path):
                template_path = f"prompts/{safe_policy_type}/Template.html"
        
        print(f"DEBUG: Using prompt: {prompt_path}")
        print(f"DEBUG: Using template: {template_path}")
        
        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
        
        client = llm_client.LLMClient(model_name=llm_model)
        report_masked, report_display = client.analyze(
            document_text=masked_text,
            prompt_template=prompt_template,
            html_template=html_template,
            reverse_mapping=reverse_mapping if not is_skipped else None
        )
        
        # 5. Complete
        analysis.report_html_masked = report_masked
        analysis.report_html_display = report_display
        analysis.status = models.AnalysisStatus.COMPLETED
        analysis.completed_at = datetime.utcnow()
        db.commit()
        
        print(f"DEBUG: Analysis {analysis_id} completed. Report size: {len(report_display or '')} chars.")
        
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
