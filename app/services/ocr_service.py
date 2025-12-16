import os
from ..database import SessionLocal
from .. import models
from .. import ocr
from .. import llm_client

def process_ocr_background(document_id: int, file_path: str, mime_type: str):
    """
    Background task to process OCR for a document.
    Updates the document record in the database upon completion.
    """
    db = SessionLocal()
    try:
        doc = db.query(models.Document).filter(models.Document.id == document_id).first()
        if not doc:
            return
        original_filename = doc.original_filename
    finally:
        db.close()

    # Process OCR
    try:
        text, method = ocr.process_document(file_path, mime_type)
    except Exception as e:
        print(f"OCR Failed for {document_id}: {e}")
        return
    
    # Save text to file
    try:
        os.makedirs("outputs", exist_ok=True)
        file_id = os.path.splitext(os.path.basename(file_path))[0]
        txt_filename = f"{file_id}.txt"
        txt_path = os.path.join("outputs", txt_filename)
        
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        
        # Count tokens
        tokens = 0
        try:
            client = llm_client.LLMClient()
            tokens = client.count_tokens(text)
        except:
            pass
        
        # Update DB
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
        print(f"Error saving OCR output for {document_id}: {e}")
