from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import asyncio
from ..llm_client import LLMClient
from ..config import settings

router = APIRouter()

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = []

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
