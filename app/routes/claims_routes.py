from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request, BackgroundTasks
from typing import List, Optional
from sqlalchemy.orm import Session
import shutil
import os
import uuid
import json
import logging
from ..database import get_db
from .. import models
from ..services.file_processor import process_file_recursive

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/upload")
async def upload_claims_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Upload and process heterogeneous files for Claims Analysis.
    Recursively unpacks emails and converts everything to PDF.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")

    upload_batch_id = str(uuid.uuid4())
    upload_dir = os.path.join("uploads", "claims", upload_batch_id)
    os.makedirs(upload_dir, exist_ok=True)
    
    processed_documents = []

    for file in files:
        # Save temp original file
        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process recursively (Convert to PDF / Extract Attachments)
        # Returns list of {path, original_name, type}
        results = process_file_recursive(file_path, upload_dir)
        
        for res in results:
            # Create DB records for the FINAL converted PDFs
            # We treat these as the actual documents to be analyzed/masked
            stored_filename = os.path.basename(res['path'])
            relative_path = os.path.relpath(res['path'], "uploads")
            
            document = models.Document(
                user_id=user_data["id"],
                original_filename=res['original_name'],
                stored_filename=stored_filename, # This is valid for retrieval
                ramo="sinistri",  # Special branch
                ocr_method="processing",
                extracted_text_path=None # OCR will fill this
            )
            db.add(document)
            db.commit()
            db.refresh(document)
            
            processed_documents.append(document.id)
            
            # Trigger OCR (Standard pipeline)
            from ..services.ocr_service import process_ocr_background
            
            # Use 'application/pdf' as we converted everything to PDF
            background_tasks.add_task(process_ocr_background, document.id, res['path'], 'application/pdf')
    
    return {
        "status": "success",
        "message": f"Processed {len(files)} files into {len(processed_documents)} items",
        "document_ids": processed_documents
    }
