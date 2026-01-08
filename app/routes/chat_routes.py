from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Any
import os
import asyncio
from sqlalchemy.orm import Session
from ..llm_client import LLMClient
from ..config import settings
from ..database import get_db
from .. import models
from ..masking import mask_document

router = APIRouter()

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = []

class ChatContextRequest(BaseModel):
    document_ids: List[int]
    masking_data: dict

@router.post("/context/prepare")
async def prepare_chat_context(
    payload: ChatContextRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Prepare masked context for chat from uploaded documents.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not payload.document_ids:
        raise HTTPException(status_code=400, detail="No documents provided")

    full_context_text = ""
    filenames = []

    for i, doc_id in enumerate(payload.document_ids, 1):
        doc = db.query(models.Document).filter(
            models.Document.id == doc_id,
            models.Document.user_id == user_data["id"]
        ).first()

        if not doc or not doc.extracted_text_path or not os.path.exists(doc.extracted_text_path):
            continue

        filenames.append(doc.original_filename)
        
        # Read text
        try:
            with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            
            # Map frontend keys (camelCase) to masking module keys (snake_case)
            mapping_keys = {
                'policyNumber': 'numero_polizza',
                'contractor': 'contraente',
                'vat': 'partita_iva',
                'fiscalCode': 'codice_fiscale',
                'insured': 'assicurato',
                'address': 'indirizzo',
                'city': 'citta',
                'cap': 'cap',
                'other': 'altri'
            }
            
            backend_masking_data = {}
            for fe_key, be_key in mapping_keys.items():
                if fe_key in payload.masking_data:
                    backend_masking_data[be_key] = payload.masking_data[fe_key]
            
            # Apply Masking
            masked_text, _, _ = mask_document(raw_text, backend_masking_data)
            
            full_context_text += f"\n\n--- DOCUMENTO MASCHERATO {i} ---\n{masked_text}"
            
        except Exception as e:
            print(f"Error reading doc {doc_id}: {e}")
            continue

    if not full_context_text:
        raise HTTPException(status_code=400, detail="Could not extract text from documents")

    return {
        "context": full_context_text,
        "filename": ", ".join(filenames) if len(filenames) < 3 else f"{len(filenames)} Documenti"
    }

@router.post("/stream")
async def chat_stream(payload: ChatRequest):
    """
    Stream chat response using Gemini.
    Enforces domain restriction via system prompt.
    """
    try:
        # Load system prompt
        prompt_path = os.path.join("prompts", "chat", "system_prompt.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                system_instruction = f.read()
        else:
            # Fallback if file missing
            system_instruction = "Sei un assistente assicurativo. Rispondi solo a domande pertinenti."

        # Initialize Client (uses default or configured model from env/settings)
        # Note: LLMClient logic we updated earlier handles reading SystemSettings if we passed None,
        # but here we might want to be explicit or let it handle it.
        # Ideally, we instantiate LLMClient and use its underlying model.
        
        # We need to construct the full history for the LLM
        # Gemini API supports specific history structure or we can just append to prompt
        # For simplicity with LLMClient (which is designed for document analysis),
        # we might need to extend it or interact with genai directly here.
        
        # Let's inspect LLMClient capabilities or use genai directly for chat.
        # Since LLMClient is wrapper, let's look at `gemini-3-flash-preview` support.
        
        # Construct the full prompt context
        messages = [f"System: {system_instruction}"]
        for msg in payload.history:
            role = "User" if msg.role == "user" else "Assistant"
            messages.append(f"{role}: {msg.content}")
        messages.append(f"User: {payload.message}")
        messages.append("Assistant:")
        
        full_prompt = "\n\n".join(messages)

        client = LLMClient() 
        # We need a streaming method. LLMClient has `analyze` which uses `generate_content(stream=True)`.
        # We can reuse the model instance from client.
        
        async def generate():
            try:
                response = client.model.generate_content(full_prompt, stream=True)
                for chunk in response:
                    if chunk.text:
                        yield chunk.text
            except Exception as e:
                yield f"Error: {str(e)}"

        return StreamingResponse(generate(), media_type="text/plain")

    except Exception as e:
        print(f"Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
