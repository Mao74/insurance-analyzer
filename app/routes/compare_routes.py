"""
Compare routes for policy comparison functionality.
Handles upload of multiple documents and comparison analysis.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import os
import json
import re

from ..database import get_db
from ..auth import get_current_user
from .. import models
from .. import masking
from .. import llm_client

router = APIRouter(prefix="/compare", tags=["compare"])

# Upload directory
UPLOAD_DIR = "uploads"
EXTRACTED_DIR = "extracted"

class CompareStartRequest(BaseModel):
    document_ids: List[int]
    policy_type: str = "rc_generale"
    masking_data: Optional[dict] = None
    llm_model: str = "gemini-2.5-flash-preview-05-20"

class CompareStartResponse(BaseModel):
    analysis_id: int
    status: str
    message: str


@router.post("/upload")
async def upload_compare_documents(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user_data: dict = Depends(get_current_user)
):
    """
    Upload multiple documents for comparison.
    Returns list of document IDs.
    """
    from .upload_routes import process_upload_file
    
    document_ids = []
    
    for file in files:
        # Reuse existing upload logic
        doc_id = await process_upload_file(file, "confronto", db, user_data["id"])
        document_ids.append(doc_id)
    
    return {
        "document_ids": document_ids,
        "count": len(document_ids),
        "message": f"{len(document_ids)} documents uploaded successfully"
    }


@router.post("/start", response_model=CompareStartResponse)
async def start_comparison(
    payload: CompareStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_data: dict = Depends(get_current_user)
):
    """
    Start a comparison analysis on multiple documents.
    """
    if len(payload.document_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 documents required for comparison")
    
    if len(payload.document_ids) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 documents for comparison")
    
    # Verify all documents exist and belong to user
    for doc_id in payload.document_ids:
        doc = db.query(models.Document).filter(
            models.Document.id == doc_id,
            models.Document.user_id == user_data["id"]
        ).first()
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Create analysis record
    analysis = models.Analysis(
        source_document_ids=json.dumps(payload.document_ids),
        status=models.AnalysisStatus.ANALYZING,
        policy_type=payload.policy_type,
        prompt_level="confronto",  # Mark as comparison
        llm_model=payload.llm_model,
        created_at=datetime.utcnow()
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    
    # Prepare masking data
    sensitive_data = {}
    if payload.masking_data:
        md = payload.masking_data
        altri_raw = md.get('other', '')
        altri_list = []
        if altri_raw:
            altri_list = [x.strip() for x in re.split(r'[;\n]', altri_raw) if x.strip()]
        
        sensitive_data = {
            'numero_polizza': md.get('policyNumber', ''),
            'contraente': md.get('contractor', ''),
            'partita_iva': md.get('vat', ''),
            'codice_fiscale': md.get('fiscalCode', ''),
            'assicurato': md.get('insured', ''),
            'indirizzo': md.get('address', ''),
            'citta': md.get('city', ''),
            'cap': md.get('cap', ''),
            'altri': altri_list
        }
    
    # Run comparison in background
    background_tasks.add_task(
        comparison_pipeline,
        analysis.id,
        payload.document_ids,
        sensitive_data,
        payload.policy_type,
        payload.llm_model,
        user_data["id"]
    )
    
    return CompareStartResponse(
        analysis_id=analysis.id,
        status="processing",
        message="Comparison started. Poll GET /api/analysis/{id} for results."
    )


def comparison_pipeline(
    analysis_id: int,
    document_ids: List[int],
    sensitive_data: dict,
    policy_type: str,
    llm_model: str,
    user_id: int
):
    """
    Background task to process comparison.
    """
    from ..database import SessionLocal  # Import here to avoid circular
    db = SessionLocal()
    
    try:
        analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
        if not analysis:
            return
        
        # 1. Collect all document texts
        combined_texts = []
        for i, doc_id in enumerate(document_ids, 1):
            doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
            if doc and doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
                with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
                    text = f.read()
                combined_texts.append(f"=== DOCUMENTO {i}: {doc.original_filename} ===\n\n{text}")
        
        if len(combined_texts) < 2:
            analysis.status = models.AnalysisStatus.ERROR
            analysis.error_message = "Could not read texts from at least 2 documents"
            db.commit()
            return
        
        # Combine all texts
        full_text = "\n\n" + "="*60 + "\n\n".join(combined_texts)
        
        # 2. Apply masking if data provided
        reverse_mapping = {}
        is_skipped = not bool(sensitive_data) or all(not v for v in sensitive_data.values() if not isinstance(v, list))
        
        if not is_skipped:
            masked_text, replacements, reverse_mapping = masking.mask_document(full_text, sensitive_data)
        else:
            masked_text = full_text
            analysis.masking_skipped = True
        
        analysis.reverse_mapping_json = masking.serialize_mapping(reverse_mapping)
        
        # 3. Load prompt and template for comparison
        safe_policy_type = ''.join(c for c in policy_type if c.isalnum() or c in ('_', '-'))
        if not safe_policy_type:
            safe_policy_type = "rc_generale"
        
        prompt_path = f"prompts/confronto_polizze/{safe_policy_type}/prompt_confronto_{safe_policy_type}.txt"
        template_path = f"prompts/confronto_polizze/{safe_policy_type}/template_confronto_{safe_policy_type}.html"
        
        # Fallback to rc_generale if specific type not found
        if not os.path.exists(prompt_path):
            prompt_path = "prompts/confronto_polizze/rc_generale/prompt_confronto_rc.txt"
            template_path = "prompts/confronto_polizze/rc_generale/template_confronto_rc.html"
        
        print(f"DEBUG Compare: Using prompt: {prompt_path}")
        print(f"DEBUG Compare: Using template: {template_path}")
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        
        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
        
        # 4. Call LLM
        client = llm_client.LLMClient(model_name=llm_model)
        report_masked, report_display, input_tokens, output_tokens = client.analyze(
            document_text=masked_text,
            prompt_template=prompt_template,
            html_template=html_template,
            reverse_mapping=reverse_mapping if not is_skipped else None
        )
        
        # 5. Save results
        analysis.report_html_masked = report_masked
        analysis.report_html_display = report_display
        analysis.status = models.AnalysisStatus.COMPLETED
        analysis.completed_at = datetime.utcnow()
        analysis.total_tokens = input_tokens + output_tokens
        
        # 6. Update user token counters
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user:
            user.total_input_tokens = (user.total_input_tokens or 0) + input_tokens
            user.total_output_tokens = (user.total_output_tokens or 0) + output_tokens
            user.total_tokens_used = (user.total_tokens_used or 0) + input_tokens + output_tokens
        
        db.commit()
        print(f"Comparison {analysis_id} completed successfully")
        
    except Exception as e:
        print(f"Comparison pipeline error: {e}")
        import traceback
        traceback.print_exc()
        
        analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
        if analysis:
            analysis.status = models.AnalysisStatus.ERROR
            analysis.error_message = str(e)
            db.commit()
    finally:
        db.close()
