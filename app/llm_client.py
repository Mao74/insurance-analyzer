import requests
import json
import os
from .masking import repopulate_report
from .config import settings

class LLMClient:
    def __init__(self, api_key: str = None, model_name: str = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        # Use gemini-3-flash-preview as requested
        self.model_name = model_name or 'gemini-3-flash-preview'
        
        # Proxy Configuration
        self.proxy_url = "https://gemini-proxy.molinari-maurizio.workers.dev"
        self.proxy_secret = "ins-lab-gemini-2025-xK9mP3nQ7vL2"

    def generate_content(self, prompt: str, stream: bool = False) -> str:
        """
        Generic method to generate content via Proxy.
        Returns the generated text string.
        (Streaming is currently not supported by proxy logic, argument kept for compatibility but ignored)
        """
        try:
            headers = {
                "Content-Type": "application/json",
                "X-Proxy-Secret": self.proxy_secret,
                "X-Gemini-Key": self.api_key,
                "X-Gemini-Model": self.model_name
            }
            
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 65536
                }
            }
            
            response = requests.post(
                self.proxy_url,
                headers=headers,
                json=payload,
                timeout=300
            )
            
            if response.status_code != 200:
                raise Exception(f"Proxy Error: {response.status_code} - {response.text}")
                
            response_json = response.json()
            if 'candidates' in response_json and len(response_json['candidates']) > 0:
                candidate = response_json['candidates'][0]
                if 'content' in candidate and 'parts' in candidate['content']:
                    return candidate['content']['parts'][0]['text']
            
            return ""
            
        except Exception as e:
            print(f"Generate Content Error: {e}")
            raise e

    def count_tokens(self, text: str) -> int:
        # Estimation: ~4 chars per token for rough count since we dropped the SDK
        # This is a fallback estimation to avoid SDK dependency
        try:
            return len(text) // 4
        except Exception as e:
            print(f"Error counting tokens: {e}")
            return 0
    
    def analyze(
        self,
        document_text: str,
        prompt_template: str,
        html_template: str,
        reverse_mapping: dict = None,
        template_path: str = None
    ) -> tuple[str, str, int, int]:
        """
        Costruisce il prompt finale e chiama l'API via Proxy.
        Returns: (report_masked, report_display, input_tokens, output_tokens)
        """
        full_prompt = f"""
═══════════════════════════════════════════════════════════════════════════════
⚠️⚠️⚠️ ISTRUZIONI CRITICHE - FORMATO DI OUTPUT OBBLIGATORIO ⚠️⚠️⚠️
═══════════════════════════════════════════════════════════════════════════════

SEI UN MOTORE DI COMPILAZIONE HTML. IL TUO UNICO SCOPO È COMPILARE IL TEMPLATE FORNITO.
NON DEVI SCRIVERE NESSIN ALTRO TESTO. NON DEVI FARE RIASSUNTI.

🚨 REGOLE INDEROGABILI:
1. L'OUTPUT DEVE ESSERE ESCLUSIVAMENTE CODICE HTML VALIDO.
2. L'OUTPUT DEVE INIZIARE CON: <!DOCTYPE html>
3. L'OUTPUT DEVE TERMINARE CON: </html>
4. DEVI USARE IL TEMPLATE HTML FORNITO SOTTO E RIEMPIRLO CON I DATI DEL DOCUMENTO.
5. NON CAMBIARE LA STRUTTURA DEL TEMPLATE. NON RIMUOVERE CSS O SCRIPT.

---
CONTESTO DELL'ANALISI (System Prompt):
{prompt_template}
---

TEMPLATE HTML DA COMPILARE (Userai questo scheletro):
{html_template}

---
DOCUMENTO DA ANALIZZARE (Estrai i dati da qui per riempire il template):
{document_text}
---

═══════════════════════════════════════════════════════════════════════════════
⚠️  RICORDA: OUTPUT HTML COMPLETO ⚠️
═══════════════════════════════════════════════════════════════════════════════

1. Mantieni UTTE le sezioni del template.
2. Se trovi placeholder di mascheramento nel documento (es. [CONTRAENTE_XXX]), COPIALI ESATTAMENTE.
3. NON aggiungere commenti markdown (```html ... ```). SOLO IL CODICE PURO.
4. INIZIA ORA CON <!DOCTYPE html>
"""
        # Count input tokens for debugging (approximated)
        input_tokens = len(full_prompt) // 4
        print(f"DEBUG: Input tokens (approx): {input_tokens}")
        
        report_masked = ""
        output_tokens = 0
        
        try:
            # Re-use generate_content for consistency
            print(f"DEBUG: Calling Gemini Proxy with model: {self.model_name}")
            report_masked = self.generate_content(full_prompt)
            print(f"DEBUG: Received response, length: {len(report_masked)} chars")
            
            # Check if response was empty
            if not report_masked:
                print("DEBUG: Empty response received from LLM via Proxy")
                report_masked = "<p>Error: LLM returned empty response. Check server logs for details.</p>"
            else:
                # Strip markdown code block wrappers if present
                report_masked = self._strip_markdown_wrappers(report_masked)
                print(f"DEBUG: LLM Response processed. Final length: {len(report_masked)} chars")

                # CRITICAL: Validate that the response is actually HTML, not plain text
                is_valid_html = self._validate_html_output(report_masked)
                if not is_valid_html:
                    print("ERROR: LLM returned plain text/markdown instead of HTML template!")
                    print(f"DEBUG: First 500 chars of response: {report_masked[:500]}")
                    # Create an error message HTML instead
                    report_masked = f"""<!DOCTYPE html>
<html lang="it">
<head><meta charset="UTF-8"><title>Errore Generazione</title>
<style>body{{font-family:sans-serif;padding:40px;}}h1{{color:#dc2626;}}.error-box{{background:#fef2f2;border:2px solid #dc2626;padding:20px;border-radius:8px;margin:20px 0;}}.raw-output{{background:#f1f5f9;padding:15px;border-radius:4px;white-space:pre-wrap;max-height:400px;overflow:auto;font-size:12px;}}</style>
</head>
<body>
<h1>⚠️ Errore nella Generazione del Report</h1>
<div class="error-box">
<p><strong>L'LLM non ha generato il template HTML correttamente.</strong></p>
<p>Invece di compilare il template HTML con i dati della polizza, ha restituito un riassunto testuale.</p>
<p>Questo può accadere quando il documento è troppo grande o l'LLM non segue le istruzioni.</p>
</div>
<h2>Output ricevuto dall'LLM:</h2>
<div class="raw-output">{report_masked[:5000]}</div>
<p><strong>Suggerimento:</strong> Prova a rilanciare l'analisi o riduci la dimensione del documento.</p>
</body>
</html>"""

                # Fix: Reinject <script> section if LLM omitted it
                if "<script>" not in report_masked and template_path:
                    report_masked = self._fix_missing_scripts(report_masked, template_path)

                # Fix: Reinject PDF cover page if LLM omitted it
                if 'class="pdf-cover"' not in report_masked and template_path:
                    report_masked = self._fix_missing_cover(report_masked, template_path)

        except Exception as e:
            print(f"LLM API Error (Proxy): {type(e).__name__}: {str(e)}")
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
    
    def _validate_html_output(self, text: str) -> bool:
        """Check if the LLM output is valid HTML, not plain text or markdown."""
        text_lower = text.lower().strip()
        
        # Check for HTML markers
        has_doctype = '<!doctype html>' in text_lower or '<!doctype' in text_lower
        has_html_tag = '<html' in text_lower
        has_head = '<head' in text_lower
        has_body = '<body' in text_lower
        has_closing_html = '</html>' in text_lower
        
        # Check for markdown indicators (signs of wrong output)
        starts_with_markdown = text.strip().startswith('---') or text.strip().startswith('# ') or text.strip().startswith('**')
        
        # Valid if has HTML structure and doesn't start with markdown
        if starts_with_markdown:
            return False
        
        # STRICT VALIDATION: Must have closing tags to ensure completion
        has_closing_body = '</body>' in text_lower
        has_closing_html = '</html>' in text_lower
        
        # Must have at least one closing tag to be considered "finished"
        if not (has_closing_body or has_closing_html):
            print("VALIDATION ERROR: HTML output is truncated (missing </body> or </html>)")
            return False
        
        # Require DOCTYPE + html tag to ensure it's a full document, not a fragment
        if has_doctype and has_html_tag:
            return True
            
        # If we have body and closing html, it's probably fine even without doctype (for fragments)
        if has_body and has_closing_html:
            return True
            
        return False
    
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

    def _fix_missing_cover(self, html: str, template_path: str) -> str:
        """Reinject PDF cover page from template if LLM omitted it."""
        import re
        
        try:
            # Read original template
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()

            # Extract PDF cover page section
            cover_start_marker = '<!-- PDF COVER PAGE'
            cover_start = template.find(cover_start_marker)
            if cover_start == -1:
                return html  # No cover page in template
            
            # Simple fallback for cover end if complex parsing fails
            # Assumes cover page div is well structured in template
            cover_end_marker = '<!-- END PDF COVER PAGE -->' # Hypothetical marker, using div logic usually
            
            # Re-using strict div counting logic from before
            cover_content_start = template.find('<div class="pdf-cover"', cover_start)
            if cover_content_start == -1:
                 cover_content_start = template.find("<div class='pdf-cover'", cover_start)
            if cover_content_start == -1:
                return html

            # Find matching closing </div>
            temp_pos = cover_content_start
            div_count = 1
            cover_end = -1

            while div_count > 0 and temp_pos < len(template):
                next_open = template.find("<div", temp_pos + 1)
                next_close = template.find("</div>", temp_pos + 1)

                if next_close == -1:
                    break

                if next_open != -1 and next_open < next_close:
                    div_count += 1
                    temp_pos = next_open
                else:
                    div_count -= 1
                    temp_pos = next_close
                    if div_count == 0:
                        cover_end = next_close + len("</div>")
                        break

            if cover_end == -1:
                return html

            cover_section = template[cover_start:cover_end]

            # Inject
            match = re.search(r'<div\s+class=["\']report-container["\']', html, re.IGNORECASE)
            if match:
                insert_pos = match.start()
                html = html[:insert_pos] + cover_section + "\n\n    " + html[insert_pos:]
                return html
            
            body_match = re.search(r'<body[^>]*>', html, re.IGNORECASE)
            if body_match:
                insert_pos = body_match.end()
                html = html[:insert_pos] + "\n" + cover_section + "\n" + html[insert_pos:]
                return html

            return html

        except Exception as e:
            print(f"WARNING: Failed to reinject PDF cover page: {e}")
            return html
