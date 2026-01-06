"""
Compare routes for policy comparison functionality.
Handles upload of multiple documents and comparison analysis.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import os
import json
import re

from ..database import get_db
from .auth_routes import get_current_user
from .. import models
from .. import masking
from .. import llm_client

router = APIRouter(tags=["compare"])

# Upload directory
UPLOAD_DIR = "uploads"
EXTRACTED_DIR = "extracted"

class CompareStartRequest(BaseModel):
    document_ids: List[int] = [] # Legacy support
    grouped_document_ids: Optional[List[List[int]]] = None # New structure: [[1,2], [3]]
    policy_type: str = "rc_generale"
    masking_data: Optional[dict] = None
    llm_model: str = "gemini-3-flash-preview"

class CompareStartResponse(BaseModel):
    analysis_id: int
    status: str
    message: str

class CompareAnalysisResponse(BaseModel):
    analysis_id: int
    status: str
    policy_type: str
    analysis_level: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    report_html: Optional[str] = None
    report_html_masked: Optional[str] = None
    error: Optional[str] = None
    title: Optional[str] = None


@router.post("/upload")
async def upload_compare_documents(
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload multiple documents for comparison.
    Returns list of document IDs.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
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


@router.get("/{analysis_id}", response_model=CompareAnalysisResponse)
async def get_comparison_analysis(
    request: Request,
    analysis_id: int,
    db: Session = Depends(get_db)
):
    """
    Get comparison analysis status and result.
    This endpoint is used by the frontend for polling.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()

    if not analysis:
        raise HTTPException(status_code=404, detail="Comparison analysis not found")

    # Verify it's a comparison
    if analysis.prompt_level != "confronto":
        raise HTTPException(status_code=400, detail="Not a comparison analysis")

    # Verify ownership - comparisons have document_id = NULL, so check source_document_ids
    if analysis.source_document_ids:
        try:
            doc_ids = json.loads(analysis.source_document_ids)
            # Handle grouped structure [[1,2], [3]] or flat [1,2,3]
            if isinstance(doc_ids[0], list):
                doc_ids = [item for sublist in doc_ids for item in sublist]

            # Check if any of the documents belong to this user
            doc = db.query(models.Document).filter(
                models.Document.id.in_(doc_ids),
                models.Document.user_id == user_data["id"]
            ).first()

            if not doc:
                raise HTTPException(status_code=403, detail="Access denied")
        except (json.JSONDecodeError, IndexError, TypeError):
            raise HTTPException(status_code=403, detail="Access denied")
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    return CompareAnalysisResponse(
        analysis_id=analysis.id,
        status=analysis.status.value if analysis.status else "unknown",
        policy_type=analysis.policy_type or "",
        analysis_level=analysis.prompt_level or "",
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        report_html=analysis.report_html_display,
        report_html_masked=analysis.report_html_masked,
        error=analysis.error_message,
        title=analysis.title
    )


@router.post("/start", response_model=CompareStartResponse)
async def start_comparison(
    request: Request,
    payload: CompareStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Start a comparison analysis on multiple documents.
    Supports grouping: multiple files can be treated as a single entity (Policy + Appendix).
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Normalize input to grouped structure
    groups = []
    
    if payload.grouped_document_ids:
        groups = payload.grouped_document_ids
    elif payload.document_ids:
        # Legacy fallback: treat each doc as separate group
        groups = [[doc_id] for doc_id in payload.document_ids]
    
    if len(groups) < 2:
        raise HTTPException(status_code=400, detail="At least 2 comparison groups required")
    
    if len(groups) > 6:
        raise HTTPException(status_code=400, detail="Maximum 6 comparison groups allowed")
    
    # Flatten IDs for verification
    all_doc_ids = [doc_id for group in groups for doc_id in group]
    
    if not all_doc_ids:
        raise HTTPException(status_code=400, detail="No documents provided")

    found_docs = db.query(models.Document).filter(
        models.Document.id.in_(all_doc_ids),
        models.Document.user_id == user_data["id"]
    ).all()
    
    if len(found_docs) != len(set(all_doc_ids)):
        found_ids = {d.id for d in found_docs}
        missing = set(all_doc_ids) - found_ids
        raise HTTPException(status_code=404, detail=f"Documents not found or access denied: {missing}")
    
    # Create analysis record
    # source_document_ids field (Text) can store the full JSON structure
    analysis = models.Analysis(
        source_document_ids=json.dumps(groups),
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
        groups,
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
    grouped_document_ids: List[List[int]],
    sensitive_data: dict,
    policy_type: str,
    llm_model: str,
    user_id: int
):
    """
    Background task to process comparison.
    Merges texts within each group before comparison.
    """
    from ..database import SessionLocal  # Import here to avoid circular
    db = SessionLocal()
    
    try:
        analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
        if not analysis:
            return
        
        # 1. Collect and merge texts for each group
        combined_group_texts = []
        
        for i, group in enumerate(grouped_document_ids, 1):
            group_texts = []
            group_filenames = []
            
            for doc_id in group:
                doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
                if doc and doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
                    with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
                        text = f.read()
                    group_texts.append(f"--- FILE: {doc.original_filename} ---\n{text}")
                    group_filenames.append(doc.original_filename)
            
            if group_texts:
                merged_text = "\n\n".join(group_texts)
                file_list = ", ".join(group_filenames)
                combined_group_texts.append(f"=== DOCUMENTO {i} (Files: {file_list}) ===\n\n{merged_text}")
        
        if len(combined_group_texts) < 2:
            analysis.status = models.AnalysisStatus.ERROR
            analysis.error_message = "Could not read texts from at least 2 comparison groups"
            db.commit()
            return
        
        # Combine all texts
        full_text = "\n\n" + "="*60 + "\n\n".join(combined_group_texts)
        
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
            reverse_mapping=reverse_mapping if not is_skipped else None,
            template_path=template_path
        )
        
        # 5. Save results
        analysis.report_html_masked = report_masked
        analysis.report_html_display = report_display
        analysis.status = models.AnalysisStatus.COMPLETED
        analysis.completed_at = datetime.utcnow()
        analysis.total_tokens = input_tokens + output_tokens
        analysis.input_tokens = input_tokens  # Store input tokens separately
        analysis.output_tokens = output_tokens  # Store output tokens separately
        
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


# Additional endpoints for Compare (reusing Analysis logic)

class UpdateContentRequest(BaseModel):
    html_content: str

@router.post("/{analysis_id}/content")
async def update_compare_content(
    analysis_id: int,
    payload: UpdateContentRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Update comparison report HTML content (for user edits)"""
    # Use same auth pattern as update_analysis_content
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()

    if not analysis:
        raise HTTPException(status_code=404, detail="Comparison analysis not found")

    # Verify it's a comparison (prompt_level = "confronto")
    if analysis.prompt_level != "confronto":
        raise HTTPException(status_code=400, detail="Not a comparison analysis")

    # Check if html_content is valid
    if not payload.html_content or len(payload.html_content) < 100:
        raise HTTPException(status_code=400, detail="Invalid HTML content")

    analysis.report_html_display = payload.html_content
    analysis.last_updated = datetime.utcnow()
    db.commit()

    return {"status": "success", "message": "Comparison report updated"}


class SaveRequest(BaseModel):
    title: Optional[str] = None

@router.post("/{analysis_id}/save")
async def save_comparison(
    request: Request,
    analysis_id: int,
    payload: SaveRequest,
    db: Session = Depends(get_db)
):
    """Mark comparison analysis as saved (archive)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    print(f"DEBUG Archive Compare: Saving analysis {analysis_id}, title={payload.title}")

    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()

    if not analysis:
        print(f"ERROR Archive Compare: Analysis {analysis_id} not found")
        raise HTTPException(status_code=404, detail="Comparison analysis not found")

    # Verify it's a comparison
    if analysis.prompt_level != "confronto":
        raise HTTPException(status_code=400, detail="Not a comparison analysis")

    try:
        analysis.is_saved = True
        if payload.title:
            analysis.title = payload.title
        analysis.last_updated = datetime.utcnow()
        db.commit()
        db.refresh(analysis)

        print(f"SUCCESS Archive Compare: Analysis {analysis_id} saved with title '{analysis.title}', is_saved={analysis.is_saved}")

        return {"status": "success", "message": "Comparison saved to archive"}
    except Exception as e:
        db.rollback()
        print(f"ERROR Archive Compare: Database commit failed - {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save comparison: {str(e)}")

