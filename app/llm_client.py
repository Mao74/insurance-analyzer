import google.generativeai as genai
from .masking import repopulate_report
from .config import settings

class LLMClient:
    def __init__(self, api_key: str = None, model_name: str = None):
        key = api_key or settings.GEMINI_API_KEY
        genai.configure(api_key=key)
        # User requested gemini-3-flash-preview
        self.model_name = model_name or 'gemini-3-flash-preview'
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
    ) -> tuple[str, str, int, int]:
        """
        Costruisce il prompt finale e chiama l'API.
        Returns: (report_masked, report_display, input_tokens, output_tokens)
        """
        full_prompt = f"""
{prompt_template}

---
DOCUMENTO DA ANALIZZARE:
---
{document_text}
---

TEMPLATE HTML DA COMPILARE:
{html_template}

═══════════════════════════════════════════════════════════════════════════════
ISTRUZIONI CRITICHE PER IL TEMPLATE:
═══════════════════════════════════════════════════════════════════════════════

1. NON MODIFICARE LA STRUTTURA del template HTML in alcun modo
2. NON aggiungere, rimuovere o riordinare i TAB
3. NON cambiare il titolo, sottotitolo o intestazioni principali
4. COMPILARE SOLO i placeholder tra parentesi quadre [PLACEHOLDER]
5. Mantenere TUTTI gli elementi esistenti (tab, sezioni, tabelle)
6. Restituire il template HTML compilato INTEGRALMENTE

ERRORI DA EVITARE:
✗ Rimuovere tab esistenti
✗ Cambiare l'ordine dei tab
✗ Modificare titoli e intestazioni fisse
✗ Aggiungere nuove sezioni non presenti nel template

═══════════════════════════════════════════════════════════════════════════════
⚠️  ISTRUZIONE CRITICA PER DATI SENSIBILI MASCHERATI:
═══════════════════════════════════════════════════════════════════════════════

Nel documento potresti trovare placeholder di mascheramento come:
- [CONTRAENTE_XXX]
- [POLIZZA_XXX]
- [PIVA_XXX]
- [CF_XXX]
- [ASSICURATO_XXX]
- [INDIRIZZO_XXX]
- [DATO_OSCURATO_X]

REGOLA FONDAMENTALE:
Quando trovi questi placeholder nel documento, DEVI COPIARLI ESATTAMENTE nel report finale.
NON sostituirli con dati dedotti, NON interpretarli, NON cercare di indovinare i valori originali.
Se il documento contiene [CONTRAENTE_XXX], il report DEVE contenere [CONTRAENTE_XXX].

✓ CORRETTO: "Contraente: [CONTRAENTE_XXX]"
✗ SBAGLIATO: "Contraente: Mario Rossi" (anche se deducibile dal contesto)

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
            
            # Count output tokens
            try:
                output_tokens = self.model.count_tokens(report_masked).total_tokens
                print(f"DEBUG: Output tokens: {output_tokens}")
            except Exception as e:
                print(f"DEBUG: Could not count output tokens: {e}")
                output_tokens = 0
            
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

                # Fix: Reinject <script> section if LLM omitted it
                if "<script>" not in report_masked and template_path:
                    report_masked = self._fix_missing_scripts(report_masked, template_path)

        except Exception as e:
            print(f"LLM API Error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            report_masked = f"<p>Error generating analysis: {str(e)}</p>"
            output_tokens = 0
        
        # Ripopola con dati originali per visualizzazione
        if reverse_mapping:
            report_display = repopulate_report(report_masked, reverse_mapping)
        else:
            report_display = report_masked
        
        return report_masked, report_display, input_tokens, output_tokens
    
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

    def _fix_missing_scripts(self, html: str, template_path: str) -> str:
        """Reinject <script> sections from template if LLM omitted them."""
        try:
            # Read original template
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()

            # Extract all <script>...</script> blocks from template
            script_start = template.find("<script>")
            if script_start == -1:
                return html  # No scripts in template

            script_end = template.rfind("</script>") + len("</script>")
            if script_end == -1:
                return html

            scripts_section = template[script_start:script_end]

            # Inject before closing </body> or </html>
            if "</body>" in html:
                html = html.replace("</body>", f"{scripts_section}\n</body>")
            elif "</html>" in html:
                html = html.replace("</html>", f"{scripts_section}\n</html>")
            else:
                html += f"\n{scripts_section}"

            print(f"DEBUG: Reinjected {scripts_section.count('<script>')} script blocks from template")
            return html

        except Exception as e:
            print(f"WARNING: Failed to reinject scripts: {e}")
            return html
