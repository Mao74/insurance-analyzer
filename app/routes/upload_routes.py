import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from ..database import get_db
from .. import models, ocr, llm_client
from ..config import settings
try:
    import magic
    HAVE_MAGIC = True
except ImportError:
    HAVE_MAGIC = False
except Exception:
    # On Windows, missing DLLs can cause other exceptions
    HAVE_MAGIC = False

router = APIRouter()

# Response Models
class DocumentResponse(BaseModel):
    id: int
    filename: str
    ramo: str
    ocr_method: Optional[str]
    token_count: int
    uploaded_at: datetime
    status: str  # "processing" | "ready" | "error"

    class Config:
        from_attributes = True

class DocumentTextResponse(BaseModel):
    id: int
    filename: str
    text: str
    token_count: int

class UploadResponse(BaseModel):
    status: str
    document_ids: List[int]
    message: str

# Routes

@router.get("/", response_model=List[DocumentResponse])
async def list_documents(
    request: Request,
    db: Session = Depends(get_db)
):
    """List all documents for the current user"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    documents = db.query(models.Document).filter(
        models.Document.user_id == user_data["id"]
    ).order_by(models.Document.uploaded_at.desc()).all()
    
    result = []
    for doc in documents:
        # Determine status
        if doc.ocr_method == "processing":
            status = "processing"
        elif doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
            status = "ready"
        else:
            status = "error"
        
        result.append(DocumentResponse(
            id=doc.id,
            filename=doc.original_filename,
            ramo=doc.ramo,
            ocr_method=doc.ocr_method,
            token_count=doc.token_count or 0,
            uploaded_at=doc.uploaded_at,
            status=status
        ))
    
    return result

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    request: Request,
    document_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific document by ID"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    doc = db.query(models.Document).filter(
        models.Document.id == document_id,
        models.Document.user_id == user_data["id"]
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Determine status
    if doc.ocr_method == "processing":
        status = "processing"
    elif doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
        status = "ready"
    else:
        status = "error"
    
    return DocumentResponse(
        id=doc.id,
        filename=doc.original_filename,
        ramo=doc.ramo,
        ocr_method=doc.ocr_method,
        token_count=doc.token_count or 0,
        uploaded_at=doc.uploaded_at,
        status=status
    )

@router.get("/{document_id}/text", response_model=DocumentTextResponse)
async def get_document_text(
    request: Request,
    document_id: int,
    db: Session = Depends(get_db)
):
    """Get the extracted text of a document"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    doc = db.query(models.Document).filter(
        models.Document.id == document_id,
        models.Document.user_id == user_data["id"]
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if not doc.extracted_text_path or not os.path.exists(doc.extracted_text_path):
        raise HTTPException(status_code=404, detail="Text not yet extracted")
    
    with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
        text = f.read()
    
    return DocumentTextResponse(
        id=doc.id,
        filename=doc.original_filename,
        text=text,
        token_count=doc.token_count or 0
    )

@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    ramo: str = Form("rc_generale"),
    db: Session = Depends(get_db)
):
    """Upload one or more PDF documents"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    processed_docs = []
    
    for file in files:
        # Validate MIME type
        await file.seek(0)
        mime = "application/octet-stream"
        
        if HAVE_MAGIC:
            try:
                header = await file.read(2048)
                mime = magic.from_buffer(header, mime=True)
            except Exception as e:
                print(f"Magic error: {e}")
                mime = "unknown"
        
        await file.seek(0)
        
        # Fallback to extension if magic failed or not available
        if mime == "unknown" or mime == "application/octet-stream" or not HAVE_MAGIC:
            if file.filename.lower().endswith(".pdf"):
                mime = "application/pdf"
        
        if mime != "application/pdf" and not mime.startswith("image/"):
            print(f"Skipping file {file.filename}, invalid mime: {mime}")
            # Optional: handle error differently, but for now continue
            # Or raise 400 if strict
            # Let's be lenient if it looks like a PDF
            if not file.filename.lower().endswith(".pdf"):
                continue
        
        # Save file
        file_id = str(uuid.uuid4())
        ext = os.path.splitext(file.filename)[1]
        stored_filename = f"{file_id}{ext}"
        upload_path = os.path.join("uploads", stored_filename)
        
        # Ensure uploads directory exists
        os.makedirs("uploads", exist_ok=True)
        
        # Async write
        with open(upload_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):
                buffer.write(content)
        
        # Create DB record
        document = models.Document(
            user_id=user_data["id"],
            original_filename=file.filename,
            stored_filename=stored_filename,
            ramo=ramo,
            ocr_method="processing",
            extracted_text_path=None
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        processed_docs.append(document.id)
        
        # Schedule OCR in background
        background_tasks.add_task(process_ocr_background, document.id, upload_path, mime)
    
    if not processed_docs:
        raise HTTPException(status_code=400, detail="No valid PDF files uploaded")
    
    return UploadResponse(
        status="success",
        document_ids=processed_docs,
        message=f"{len(processed_docs)} file(s) uploaded. OCR processing in background."
    )

@router.delete("/{document_id}")
async def delete_document(
    request: Request,
    document_id: int,
    db: Session = Depends(get_db)
):
    """Delete a document"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    doc = db.query(models.Document).filter(
        models.Document.id == document_id,
        models.Document.user_id == user_data["id"]
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Delete files
    if doc.stored_filename:
        upload_path = os.path.join("uploads", doc.stored_filename)
        if os.path.exists(upload_path):
            os.remove(upload_path)
    
    if doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
        os.remove(doc.extracted_text_path)
    
    db.delete(doc)
    db.commit()
    
    return {"message": "Document deleted successfully"}


from ..services.ocr_service import process_ocr_background


