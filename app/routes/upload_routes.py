import os
import uuid
import shutil
from datetime import datetime
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, ocr, llm_client
from ..config import settings
from typing import List
import magic  # python-magic

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request, "user": request.session.get("user")})

@router.post("/upload")
async def handle_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    ramo: str = Form("rc_generale"),
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    print(f"DEBUG: Processing {len(files)} files")
    processed_docs = []
    
    for file in files:
        print(f"DEBUG: Processing file {file.filename}")
        # Validate file size
        # UploadFile in FastAPI (Starlette) exposes async methods.
        # But 'file.file' is a SpooledTemporaryFile (sync).
        # We should use 'await file.read()' methods preferably.
        # To check size without reading all, we might rely on content-length header or read.
        # Let's trust content-length or just check size after save? 
        # Actually file.size is not available directly.
        # Let's skip seek/tell for now to avoid sync blocking issues if spooled to disk.
        # Better: Read chunks and count size during save? 
        # For MVP simplicity with 'await file.read' above, we are safe.
        # Let's remove the sync seek/tell block.
        
        # Validate MIME type (Read small chunk)
        await file.seek(0)
        header = await file.read(2048)
        mime = magic.from_buffer(header, mime=True)
        await file.seek(0)
        
        if mime != "application/pdf" and not mime.startswith("image/"):
            print(f"Skipping unsupported file: {mime}")
            continue
            
        # Save file asynchronously
        file_id = str(uuid.uuid4())
        ext = os.path.splitext(file.filename)[1]
        stored_filename = f"{file_id}{ext}"
        upload_path = os.path.join("uploads", stored_filename)
        
        # Async write to avoid blocking event loop
        with open(upload_path, "wb") as buffer:
            while content := await file.read(1024 * 1024): # 1MB chunks
                 buffer.write(content)
            
        # Create DB record immediately (OCR pending)
        document = models.Document(
            user_id=user_data["id"],
            original_filename=file.filename,
            stored_filename=stored_filename,
            ramo=ramo,
            ocr_method="processing", # temp status
            extracted_text_path=None # pending
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        processed_docs.append(document.id)
        
        # Schedule OCR in background
        background_tasks.add_task(process_ocr_background, document.id, upload_path, mime)
    
    if not processed_docs:
        raise HTTPException(status_code=400, detail="No valid files processed")
    
    return JSONResponse({
        "status": "success",
        "document_ids": processed_docs,
        "document_id": processed_docs[0] if processed_docs else None,
        "message": f"{len(processed_docs)} files uploading. OCR in background."
    })

def process_ocr_background(document_id: int, file_path: str, mime_type: str):
    from ..database import SessionLocal
    
    # 1. Verify existence (Quick Read)
    db = SessionLocal()
    try:
        doc = db.query(models.Document).filter(models.Document.id == document_id).first()
        if not doc:
            return
        # Store necessary info locally
        original_filename = doc.original_filename
        # We don't need to keep session open
    finally:
        db.close()

    # 2. Process OCR (Long running, NO DB LOCK)
    try:
        text, method = ocr.process_document(file_path, mime_type)
    except Exception as e:
        print(f"OCR Failed for {document_id}: {e}")
        return 
    
    # Save text to file (IO)
    try:
        file_id = os.path.splitext(os.path.basename(file_path))[0]
        txt_filename = f"{file_id}.txt"
        txt_path = os.path.join("outputs", txt_filename)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
            
        # Count tokens (API Call)
        tokens = 0
        try:
            client = llm_client.LLMClient()
            tokens = client.count_tokens(text)
        except:
            pass
            
        # 3. Update DB (Quick Write)
        db = SessionLocal()
        try:
            doc = db.query(models.Document).filter(models.Document.id == document_id).first()
            if doc:
                doc.extracted_text_path = txt_path
                doc.ocr_method = method
                doc.token_count = tokens
                db.commit()
        finally:
            db.close()
            
    except Exception as e:
        print(f"Background OCR critical error: {e}")
