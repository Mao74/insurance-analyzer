import os
import json
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, masking, llm_client
from ..config import settings
from typing import Optional, List

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/masking", response_class=HTMLResponse)
async def masking_page(request: Request, ids: str, db: Session = Depends(get_db)):
    # Parse IDs
    try:
        doc_ids = [int(id_str) for id_str in ids.split(",") if id_str.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document IDs")
        
    if not doc_ids:
        raise HTTPException(status_code=400, detail="No documents specified")

    # Fetch documents
    docs = db.query(models.Document).filter(models.Document.id.in_(doc_ids)).all()
    if not docs:
         raise HTTPException(status_code=404, detail="Documents not found")
    
    # Sort docs to maintain order if possible, or just use DB order. 
    # db.query(..).filter(..in_..) does not guarantee order. 
    # Let's reorder them based on input list
    docs_map = {d.id: d for d in docs}
    ordered_docs = [docs_map[d_id] for d_id in doc_ids if d_id in docs_map]
    
    combined_text = ""
    total_tokens = 0
    
    combined_text = ""
    total_tokens = 0
    all_ready = True
    
    for doc in ordered_docs:
        # Check if text exists or is pending
        if not doc.extracted_text_path or not os.path.exists(doc.extracted_text_path):
            all_ready = False
            break
            
        with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
            content = f.read()
            combined_text += f"\n\n--- DOCUMENTO: {doc.original_filename} ---\n\n"
            combined_text += content
            total_tokens += doc.token_count or 0 # Handle None if old docs
            
    if not all_ready:
        return templates.TemplateResponse("ocr_pending.html", {
            "request": request,
            "user": request.session.get("user")
        })
    
    # Truncate text for display to prevent 504/Crash on huge files
    # The full text is on disk and will be used for analysis.
    
    documents_data = []
    
    for doc in ordered_docs:
        content = ""
        if doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
             with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
                 content = f.read()
        
        documents_data.append({
            "id": doc.id,
            "filename": doc.original_filename,
            "text": content,
            "tokens": doc.token_count or 0
        })



    # Determine default policy type from first doc
    default_policy_type = "rc_generale"
    if ordered_docs and ordered_docs[0].ramo:
        default_policy_type = ordered_docs[0].ramo

    return templates.TemplateResponse("masking.html", {
        "request": request,
        "user": request.session.get("user"),
        "document_ids": ids,
        "extracted_text": combined_text.strip(), # Keep for legacy/combined view if needed
        "documents_data": documents_data, # New structure
        "filenames": [d.original_filename for d in ordered_docs],
        "total_tokens": total_tokens,
        "default_policy_type": default_policy_type
    })

@router.get("/masking/{document_id}")
async def masking_page_legacy(document_id: int):
    """Compatibility route for cached JS or single file access"""
    return RedirectResponse(url=f"/masking?ids={document_id}")

@router.post("/analysis/start")
async def start_analysis(
    request: Request,
    background_tasks: BackgroundTasks,
    document_ids: str = Form(...),
    skip_masking: Optional[str] = Form(None),
    numero_polizza: Optional[str] = Form(None),
    contraente: Optional[str] = Form(None),
    partita_iva: Optional[str] = Form(None),
    codice_fiscale: Optional[str] = Form(None),
    assicurato: Optional[str] = Form(None),
    altri: Optional[str] = Form(None),
    analysis_level: str = Form("base"),
    policy_type: str = Form("rc_generale"),
    llm_model: str = Form("gemini-2.5-flash"),
    db: Session = Depends(get_db)
):
    # Parse IDs
    try:
        doc_ids_list = [int(id_str) for id_str in document_ids.split(",") if id_str.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid IDs")

    docs = db.query(models.Document).filter(models.Document.id.in_(doc_ids_list)).all()
    if not docs:
        raise HTTPException(status_code=404, detail="Documents not found")
        
    docs_map = {d.id: d for d in docs}
    ordered_docs = [docs_map[d_id] for d_id in doc_ids_list if d_id in docs_map]

    # Create Analysis record immediately with QUEUED status
    # We need to store sensitive data temporarily to pass to background task
    # For MVP, we can pass it as arguments to the background function.
    
    # Use first document ID for naming or UUID
    primary_doc = ordered_docs[0]
    
    # Define skipped flag EARLY
    is_skipped = skip_masking == "true"
    
    analysis = models.Analysis(
        document_id=primary_doc.id, 
        source_document_ids=json.dumps(doc_ids_list),
        status=models.AnalysisStatus.ANALYZING, # or QUEUED
        policy_type=policy_type,
        prompt_level=analysis_level,
        llm_model=llm_model,
        masking_skipped=is_skipped,
        # masked_text_path will be set in background
        # total_tokens will be set in background
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    
    sensitive_data = {
        'numero_polizza': numero_polizza or '',
        'contraente': contraente or '',
        'partita_iva': partita_iva or '',
        'codice_fiscale': codice_fiscale or '',
        'assicurato': assicurato or '',
        'altri': [x.strip() for x in (altri or '').split('\n') if x.strip()]
    }

    # Process everything in background
    background_tasks.add_task(
        full_analysis_pipeline, 
        analysis.id, 
        doc_ids_list,
        sensitive_data,
        is_skipped,
        analysis_level,
        policy_type,
        llm_model
    )

    return RedirectResponse(url=f"/report/{analysis.id}", status_code=303)

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
        
        # Update tokens early
        analysis.total_tokens = total_tokens
        db.commit()

        # 2. Masking
        masked_text = original_text
        reverse_mapping = {}
        
        if not is_skipped:
            masked_text, _, reverse_mapping = masking.mask_document(original_text, sensitive_data)
            
        # 3. Save Masked Text
        primary_doc = ordered_docs[0]
        masked_filename = f"{primary_doc.stored_filename}.combined.masked.txt"
        masked_path = os.path.join("outputs", masked_filename)
        with open(masked_path, "w", encoding="utf-8") as f:
            f.write(masked_text)
            
        analysis.masked_text_path = masked_path
        analysis.reverse_mapping_json = masking.serialize_mapping(reverse_mapping)
        db.commit()

        # 4. LLM Analysis
        # Ensure policy_type is valid path safe
        safe_policy_type = ''.join(c for c in policy_type if c.isalnum() or c in ('_', '-'))
        if not safe_policy_type: safe_policy_type = "rc_generale"

        prompt_path = f"prompts/{safe_policy_type}/{analysis_level}.txt"
        if not os.path.exists(prompt_path):
             prompt_path = f"prompts/{safe_policy_type}/base.txt"
             
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        
        # Load template matching analysis level
        template_path = f"prompts/{safe_policy_type}/template_{analysis_level}.html"
        if not os.path.exists(template_path):
            # Fallback to generic template.html if specific one doesn't exist
            template_path = f"prompts/{safe_policy_type}/template.html"
            if not os.path.exists(template_path):
                template_path = f"prompts/{safe_policy_type}/Template.html"  # Handle case sensitivity
        
        print(f"DEBUG: Using prompt: {prompt_path}")
        print(f"DEBUG: Using template: {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
        
        client = llm_client.LLMClient()
        report_masked, report_display = client.analyze(
            document_text=masked_text,
            prompt_template=prompt_template,
            html_template=html_template,
            reverse_mapping=reverse_mapping if not is_skipped else None
        )
        
        # 5. Complete (Inside Try)
        analysis.report_html_masked = report_masked
        analysis.report_html_display = report_display
        analysis.status = models.AnalysisStatus.COMPLETED
        analysis.completed_at = datetime.utcnow()
        db.commit()
        
        print(f"DEBUG: Analysis Completed. Report Size: {len(report_display or '')} chars.")
        print(f"DEBUG: Report Content Preview: {(report_display or '')[:200]}")
        
    except Exception as e:
        print(f"Analysis Pipeline Error: {e}")
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


@router.get("/report/{analysis_id}", response_class=HTMLResponse)
async def view_report(request: Request, analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    return templates.TemplateResponse("report.html", {
        "request": request,
        "user": request.session.get("user"),
        "analysis": analysis
    })

@router.get("/report/{analysis_id}/content", response_class=HTMLResponse)
async def report_content(analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis or not analysis.report_html_display:
        return Response("Report content not available", status_code=404)
    return HTMLResponse(content=analysis.report_html_display)

@router.get("/report/{analysis_id}/download")
async def download_report(analysis_id: int, format: str = "html", db: Session = Depends(get_db)):
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    if format == "html":
        return Response(
            content=analysis.report_html_display,
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename=report_{analysis_id}.html"}
        )
    elif format == "html_masked":
        return Response(
            content=analysis.report_html_masked,
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename=report_{analysis_id}_masked.html"}
        )
    elif format == "pdf":
        try:
            from xhtml2pdf import pisa
            from io import BytesIO
            
            buffer = BytesIO()
            pisa_status = pisa.CreatePDF(analysis.report_html_display, dest=buffer)
            
            if pisa_status.err:
               return Response(f"PDF Generation Error", status_code=500)
               
            pdf_bytes = buffer.getvalue()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=report_{analysis_id}.pdf"}
            )
        except Exception as e:
            return Response(f"PDF Generation failed: {str(e)}", status_code=500)
            
    return Response("Invalid format", status_code=400)

@router.delete("/analysis/{analysis_id}")
async def delete_analysis(request: Request, analysis_id: int, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Unauthorized")

    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    # Verify ownership (via document)
    if analysis.document.user_id != user_data["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        # Delete files
        if analysis.masked_text_path and os.path.exists(analysis.masked_text_path):
            try:
                os.remove(analysis.masked_text_path)
            except Exception as e:
                print(f"Error removing file: {e}")
                
        db.delete(analysis)
        db.commit()
        return JSONResponse({"status": "success", "message": "Analysis deleted"})
        
    except Exception as e:
        print(f"DELETE ERROR: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
