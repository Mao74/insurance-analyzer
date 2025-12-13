import google.generativeai as genai
from .masking import repopulate_report
from .config import settings

class LLMClient:
    def __init__(self, api_key: str = None, model_name: str = None):
        key = api_key or settings.GEMINI_API_KEY
        genai.configure(api_key=key)
        # User requested gemini-2.5-flash
        self.model_name = model_name or 'gemini-2.5-flash'
        self.model = genai.GenerativeModel(self.model_name)

    def count_tokens(self, text: str) -> int:
        try:
            return self.model.count_tokens(text).total_tokens
        except Exception as e:
            print(f"Error counting tokens: {e}")
            return 0
    
    def analyze(
        self, 
        document_text: str, 
        prompt_template: str, 
        html_template: str,
        reverse_mapping: dict = None
    ) -> tuple[str, str]:
        """
        Costruisce il prompt finale e chiama l'API.
        """
        full_prompt = f"""
{prompt_template}

---
DOCUMENTO DA ANALIZZARE:
---
{document_text}
---

TEMPLATE HTML DA COMPILARE (riempi i placeholder):
{html_template}
"""
        # Count input tokens for debugging
        try:
            input_tokens = self.model.count_tokens(full_prompt).total_tokens
            print(f"DEBUG: Input tokens: {input_tokens}")
        except Exception as e:
            print(f"DEBUG: Could not count input tokens: {e}")
            input_tokens = 0
        
        try:
            # Gemini 2.5 Flash supports up to 65536 output tokens
            # Increased from 8192 to handle large HTML reports
            generation_config = genai.GenerationConfig(
                temperature=0.3,  # Lower temp for more deterministic HTML output
                max_output_tokens=65536,  # Maximum for Gemini 2.5 Flash
            )
            
            print(f"DEBUG: Calling Gemini API with model {self.model_name}...")
            print(f"DEBUG: This may take several minutes for large documents...")
            
            # For large requests, we need to configure a longer timeout
            # Default gRPC timeout is too short for 60k+ token inputs
            import google.api_core.client_options as client_options
            from google.api_core import retry
            
            # Use generate_content with streaming for better timeout handling
            response = self.model.generate_content(
                full_prompt,
                generation_config=generation_config,
                stream=True  # Streaming prevents timeout on large responses
            )
            
            # Collect streamed response
            report_masked = ""
            chunk_count = 0
            for chunk in response:
                if chunk.text:
                    report_masked += chunk.text
                    chunk_count += 1
            
            print(f"DEBUG: Received {chunk_count} chunks, total length: {len(report_masked)} chars")
            
            # Check if response was empty
            if not report_masked:
                print("DEBUG: Empty response received from LLM")
                # Try to get feedback
                try:
                    if hasattr(response, 'prompt_feedback'):
                        print(f"DEBUG: Prompt feedback: {response.prompt_feedback}")
                except:
                    pass
                report_masked = "<p>Error: LLM returned empty response. Check server logs for details.</p>"
            else:
                # Strip markdown code block wrappers if present
                report_masked = self._strip_markdown_wrappers(report_masked)
                print(f"DEBUG: LLM Response processed. Final length: {len(report_masked)} chars")
                
        except Exception as e:
            print(f"LLM API Error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            report_masked = f"<p>Error generating analysis: {str(e)}</p>"
        
        # Ripopola con dati originali per visualizzazione
        if reverse_mapping:
            report_display = repopulate_report(report_masked, reverse_mapping)
        else:
            report_display = report_masked
        
        return report_masked, report_display
    
    def _strip_markdown_wrappers(self, text: str) -> str:
        """Remove markdown code block wrappers and any preamble text from LLM response."""
        text = text.strip()
        
        # If response contains ```html, extract only the HTML content
        if "```html" in text:
            start_idx = text.find("```html")
            # Find the newline after ```html
            newline_after = text.find("\n", start_idx)
            if newline_after != -1:
                text = text[newline_after + 1:]
            else:
                text = text[start_idx + 7:]  # len("```html") = 7
        elif "```" in text:
            # Generic code block
            start_idx = text.find("```")
            newline_after = text.find("\n", start_idx)
            if newline_after != -1:
                text = text[newline_after + 1:]
            else:
                text = text[start_idx + 3:]
        
        # Remove ending ```
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        
        return text.strip()
