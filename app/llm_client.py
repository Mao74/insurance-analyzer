import google.generativeai as genai
from .masking import repopulate_report
from .config import settings

class LLMClient:
    def __init__(self, api_key: str = None, model_name: str = None):
        key = api_key or settings.GEMINI_API_KEY
        # Use REST transport - HTTP/2 gRPC is blocked by Google from this server IP
        genai.configure(api_key=key, transport='rest')

        # Model should always be provided from SystemSettings, fallback only for emergency
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
        reverse_mapping: dict = None,
        template_path: str = None
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
⚠️⚠️⚠️ ISTRUZIONI CRITICHE - LEGGERE ATTENTAMENTE ⚠️⚠️⚠️
═══════════════════════════════════════════════════════════════════════════════

🚨 URGENTE: DEVI RESTITUIRE IL TEMPLATE HTML COMPLETO!
🚨 L'OUTPUT DEVE INIZIARE CON: <!DOCTYPE html>
🚨 L'OUTPUT DEVE TERMINARE CON: </html>
🚨 NON restituire riassunti, note o testo semplice!

COSA DEVI FARE:
1. Prendi il template HTML fornito sopra INTEGRALMENTE
2. COMPILA SOLO i placeholder tra parentesi quadre [PLACEHOLDER]
3. NON rimuovere alcuna sezione, tab, tabella o elemento
4. Restituisci l'INTERO documento HTML dal DOCTYPE alla chiusura </html>

ERRORI FATALI DA EVITARE:
✗ NON restituire solo le "Note Tecniche" o un riassunto
✗ NON restituire testo in formato markdown (---, **, etc.)
✗ NON omettere i tab, le tabelle, i grafici, gli stili CSS
✗ NON restituire solo una porzione del template

ESEMPIO DI OUTPUT CORRETTO:
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    ... (tutto il CSS e head) ...
</head>
<body>
    ... (tutte le sezioni, tab, tabelle compilate) ...
</body>
</html>

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

🚨 RICORDA: RESTITUISCI L'INTERO HTML COMPLETO, NON UN RIASSUNTO! 🚨

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
            try:
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
                        
            except Exception as e:
                # 🚨 FALLBACK LOGIC: If model fails (403/404), try Gemini 3 Flash as fallback
                error_str = str(e).lower()
                if "403" in error_str or "404" in error_str or "not found" in error_str or "permission denied" in error_str:
                    print(f"WARNING: Model {self.model_name} failed ({e}). Falling back to 'gemini-3-flash-preview'...")
                    fallback_model = genai.GenerativeModel('gemini-3-flash-preview')
                    response = fallback_model.generate_content(
                        full_prompt,
                        generation_config=generation_config,
                        stream=True
                    )
                    report_masked = ""
                    chunk_count = 0
                    for chunk in response:
                        if chunk.text:
                            report_masked += chunk.text
                            chunk_count += 1
                    print(f"DEBUG: Fallback successful using gemini-3-flash-preview")
                else:
                    raise e  # Re-raise other errors
            
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

            # Find the end of the cover div
            # Look for the closing </div> after the pdf-cover div
            cover_content_start = template.find('<div class="pdf-cover"', cover_start)
            if cover_content_start == -1:
                # Try single quotes
                cover_content_start = template.find("<div class='pdf-cover'", cover_start)
            if cover_content_start == -1:
                return html

            # Find matching closing </div>
            # Simple approach: find the next </div> after the opening comment
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
                print("WARNING: Could not find end of PDF cover section")
                return html

            cover_section = template[cover_start:cover_end]

            # Try multiple methods to inject the cover page
            
            # Method 1: Find report-container with regex (handles quotes and extra attributes)
            report_container_pattern = re.compile(r'<div\s+class=["\']report-container["\']', re.IGNORECASE)
            match = report_container_pattern.search(html)
            if match:
                insert_pos = match.start()
                html = html[:insert_pos] + cover_section + "\n\n    " + html[insert_pos:]
                print(f"DEBUG: Reinjected PDF cover page before report-container")
                return html
            
            # Method 2: Find <body> tag with regex (handles attributes)
            body_pattern = re.compile(r'<body[^>]*>', re.IGNORECASE)
            body_match = body_pattern.search(html)
            if body_match:
                insert_pos = body_match.end()
                html = html[:insert_pos] + "\n" + cover_section + "\n" + html[insert_pos:]
                print(f"DEBUG: Reinjected PDF cover page after <body> tag")
                return html
            
            # Method 3: Find first <div after </head> or </style>
            head_end = html.lower().find('</head>')
            if head_end != -1:
                first_div = html.find('<div', head_end)
                if first_div != -1:
                    html = html[:first_div] + cover_section + "\n\n    " + html[first_div:]
                    print(f"DEBUG: Reinjected PDF cover page before first div after </head>")
                    return html
            
            # Method 4: Last resort - inject at the very beginning after doctype/html
            html_tag_match = re.search(r'<html[^>]*>', html, re.IGNORECASE)
            if html_tag_match:
                # Find </head> or first content
                head_end = html.find('</head>')
                if head_end != -1:
                    insert_pos = head_end + len('</head>')
                    html = html[:insert_pos] + "\n<body>\n" + cover_section + "\n" + html[insert_pos:]
                    print(f"DEBUG: Reinjected PDF cover page with new body tag")
                    return html
            
            print("WARNING: Could not find insertion point for PDF cover page (all methods failed)")
            return html

        except Exception as e:
            print(f"WARNING: Failed to reinject PDF cover page: {e}")
            import traceback
            traceback.print_exc()
            return html

