import os
import json
from datetime import datetime
from playwright.async_api import async_playwright
from fastapi import APIRouter, Request, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, masking, llm_client
from ..config import settings
from typing import Optional, List, Dict

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/masking", response_class=HTMLResponse)
async def masking_page(request: Request, ids: str, db: Session = Depends(get_db)):
    # Parse IDs
    try:
        doc_ids = [int(id_str) for id_str in ids.split(",") if id_str.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid document IDs")
        
    if not doc_ids:
        raise HTTPException(status_code=400, detail="No documents specified")

    # Fetch documents
    docs = db.query(models.Document).filter(models.Document.id.in_(doc_ids)).all()
    if not docs:
         raise HTTPException(status_code=404, detail="Documents not found")
    
    # Sort docs to maintain order if possible, or just use DB order. 
    # db.query(..).filter(..in_..) does not guarantee order. 
    # Let's reorder them based on input list
    docs_map = {d.id: d for d in docs}
    ordered_docs = [docs_map[d_id] for d_id in doc_ids if d_id in docs_map]
    
    combined_text = ""
    total_tokens = 0
    
    combined_text = ""
    total_tokens = 0
    all_ready = True
    
    for doc in ordered_docs:
        # Check if text exists or is pending
        if not doc.extracted_text_path or not os.path.exists(doc.extracted_text_path):
            all_ready = False
            break
            
        with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
            content = f.read()
            combined_text += f"\n\n--- DOCUMENTO: {doc.original_filename} ---\n\n"
            combined_text += content
            total_tokens += doc.token_count or 0 # Handle None if old docs
            
    if not all_ready:
        return templates.TemplateResponse("ocr_pending.html", {
            "request": request,
            "user": request.session.get("user")
        })
    
    # Truncate text for display to prevent 504/Crash on huge files
    # The full text is on disk and will be used for analysis.
    
    documents_data = []
    
    for doc in ordered_docs:
        content = ""
        if doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
             with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
                 content = f.read()
        
        documents_data.append({
            "id": doc.id,
            "filename": doc.original_filename,
            "text": content,
            "tokens": doc.token_count or 0
        })



    # Determine default policy type from first doc
    default_policy_type = "rc_generale"
    if ordered_docs and ordered_docs[0].ramo:
        default_policy_type = ordered_docs[0].ramo

    return templates.TemplateResponse("masking.html", {
        "request": request,
        "user": request.session.get("user"),
        "document_ids": ids,
        "extracted_text": combined_text.strip(), # Keep for legacy/combined view if needed
        "documents_data": documents_data, # New structure
        "filenames": [d.original_filename for d in ordered_docs],
        "total_tokens": total_tokens,
        "default_policy_type": default_policy_type
    })

@router.get("/masking/{document_id}")
async def masking_page_legacy(document_id: int):
    """Compatibility route for cached JS or single file access"""
    return RedirectResponse(url=f"/masking?ids={document_id}")

@router.post("/analysis/start")
async def start_analysis(
    request: Request,
    background_tasks: BackgroundTasks,
    document_ids: str = Form(...),
    skip_masking: Optional[str] = Form(None),
    numero_polizza: Optional[str] = Form(None),
    contraente: Optional[str] = Form(None),
    partita_iva: Optional[str] = Form(None),
    codice_fiscale: Optional[str] = Form(None),
    assicurato: Optional[str] = Form(None),
    altri: Optional[str] = Form(None),
    analysis_level: str = Form("base"),
    policy_type: str = Form("rc_generale"),
    llm_model: str = Form("gemini-2.5-flash"),
    db: Session = Depends(get_db)
):
    # Parse IDs
    try:
        doc_ids_list = [int(id_str) for id_str in document_ids.split(",") if id_str.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid IDs")

    docs = db.query(models.Document).filter(models.Document.id.in_(doc_ids_list)).all()
    if not docs:
        raise HTTPException(status_code=404, detail="Documents not found")
        
    docs_map = {d.id: d for d in docs}
    ordered_docs = [docs_map[d_id] for d_id in doc_ids_list if d_id in docs_map]

    # Create Analysis record immediately with QUEUED status
    # We need to store sensitive data temporarily to pass to background task
    # For MVP, we can pass it as arguments to the background function.
    
    # Use first document ID for naming or UUID
    primary_doc = ordered_docs[0]
    
    # Define skipped flag EARLY
    is_skipped = skip_masking == "true"
    
    analysis = models.Analysis(
        document_id=primary_doc.id, 
        source_document_ids=json.dumps(doc_ids_list),
        status=models.AnalysisStatus.ANALYZING, # or QUEUED
        policy_type=policy_type,
        prompt_level=analysis_level,
        llm_model=llm_model,
        masking_skipped=is_skipped,
        # masked_text_path will be set in background
        # total_tokens will be set in background
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    
    sensitive_data = {
        'numero_polizza': numero_polizza or '',
        'contraente': contraente or '',
        'partita_iva': partita_iva or '',
        'codice_fiscale': codice_fiscale or '',
        'assicurato': assicurato or '',
        'altri': [x.strip() for x in (altri or '').split('\n') if x.strip()]
    }

    # Process everything in background
    background_tasks.add_task(
        full_analysis_pipeline, 
        analysis.id, 
        doc_ids_list,
        sensitive_data,
        is_skipped,
        analysis_level,
        policy_type,
        llm_model
    )

    return RedirectResponse(url=f"/report/{analysis.id}", status_code=303)

def full_analysis_pipeline(
    analysis_id: int, 
    doc_ids_list: List[int], 
    sensitive_data: dict, 
    is_skipped: bool, 
    analysis_level: str, 
    policy_type: str,
    llm_model: str
):
    from ..database import SessionLocal
    db = SessionLocal()
    
    try:
        analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
        if not analysis:
            return

        # 1. Combine Text
        docs = db.query(models.Document).filter(models.Document.id.in_(doc_ids_list)).all()
        docs_map = {d.id: d for d in docs}
        ordered_docs = [docs_map[d_id] for d_id in doc_ids_list if d_id in docs_map]
        
        original_text = ""
        total_tokens = 0
        
        for doc in ordered_docs:
            if doc.extracted_text_path and os.path.exists(doc.extracted_text_path):
                with open(doc.extracted_text_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    original_text += f"\n\n--- DOCUMENTO: {doc.original_filename} ---\n\n"
                    original_text += content
                total_tokens += doc.token_count or 0
        
        original_text = original_text.strip()
        
        # Update tokens early
        analysis.total_tokens = total_tokens
        db.commit()

        # 2. Masking
        masked_text = original_text
        reverse_mapping = {}
        
        if not is_skipped:
            masked_text, _, reverse_mapping = masking.mask_document(original_text, sensitive_data)
            
        # 3. Save Masked Text
        primary_doc = ordered_docs[0]
        masked_filename = f"{primary_doc.stored_filename}.combined.masked.txt"
        masked_path = os.path.join("outputs", masked_filename)
        with open(masked_path, "w", encoding="utf-8") as f:
            f.write(masked_text)
            
        analysis.masked_text_path = masked_path
        analysis.reverse_mapping_json = masking.serialize_mapping(reverse_mapping)
        db.commit()

        # 4. LLM Analysis
        # Ensure policy_type is valid path safe
        safe_policy_type = ''.join(c for c in policy_type if c.isalnum() or c in ('_', '-'))
        if not safe_policy_type: safe_policy_type = "rc_generale"

        prompt_path = f"prompts/{safe_policy_type}/{analysis_level}.txt"
        if not os.path.exists(prompt_path):
             prompt_path = f"prompts/{safe_policy_type}/base.txt"
             
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        
        # Load template matching analysis level
        template_path = f"prompts/{safe_policy_type}/template_{analysis_level}.html"
        if not os.path.exists(template_path):
            # Fallback to generic template.html if specific one doesn't exist
            template_path = f"prompts/{safe_policy_type}/template.html"
            if not os.path.exists(template_path):
                template_path = f"prompts/{safe_policy_type}/Template.html"  # Handle case sensitivity
        
        print(f"DEBUG: Using prompt: {prompt_path}")
        print(f"DEBUG: Using template: {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
        
        client = llm_client.LLMClient()
        report_masked, report_display = client.analyze(
            document_text=masked_text,
            prompt_template=prompt_template,
            html_template=html_template,
            reverse_mapping=reverse_mapping if not is_skipped else None
        )
        
        # 5. Complete (Inside Try)
        analysis.report_html_masked = report_masked
        analysis.report_html_display = report_display
        analysis.status = models.AnalysisStatus.COMPLETED
        analysis.completed_at = datetime.utcnow()
        db.commit()
        
        print(f"DEBUG: Analysis Completed. Report Size: {len(report_display or '')} chars.")


        print(f"DEBUG: Report Content Preview: {(report_display or '')[:200]}")
        
    except Exception as e:
        print(f"Analysis Pipeline Error: {e}")
        if analysis:
            analysis.status = models.AnalysisStatus.ERROR
            analysis.error_message = str(e)
            try:
                db.commit()
            except:
                pass
    finally:
        db.close()
        print(f"DEBUG: Background Analysis Task Finished. ID={analysis_id}")


@router.get("/report/{analysis_id}", response_class=HTMLResponse)
async def view_report(request: Request, analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    return templates.TemplateResponse("report.html", {
        "request": request,
        "user": request.session.get("user"),
        "analysis": analysis,
        "timestamp": int(datetime.utcnow().timestamp())
    })

@router.get("/report/{analysis_id}/content", response_class=HTMLResponse)
async def report_content(analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis or not analysis.report_html_display:
        return Response("Report content not available", status_code=404)
    
    html = analysis.report_html_display
    
    # Inject Edit Toolbar if not present (Backward compatibility + Feature enhancement)
    if "id=\"edit-toolbar\"" not in html:
        toolbar_html = f"""
        <style>
            @media print {{
                #edit-toolbar {{ display: none !important; }}
                .tabs {{ display: none !important; }}
                .tab-content {{ display: block !important; page-break-after: always; }}
                .tab-content:last-child {{ page-break-after: auto; }}
                .report-container {{ box-shadow: none !important; border: none !important; }}
                body {{ background: white !important; }}
            }}
        </style>
        
        <div id="edit-toolbar" style="position: fixed; bottom: 20px; right: 20px; z-index: 9999; display: flex; gap: 10px; background: rgba(255,255,255,0.95); padding: 12px 16px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); border: 1px solid #e5e7eb;">
            <a href="/report/{analysis_id}/download-pdf" 
               onclick="const el=this; el.innerHTML='⏳ Generazione...'; el.style.opacity='0.7'; el.style.pointerEvents='none'; setTimeout(function(){{ el.innerHTML='📥 PDF'; el.style.opacity='1'; el.style.pointerEvents='auto'; }}, 8000);"
               style="background: #db2777; color: white; text-decoration: none; padding: 10px 18px; border-radius: 6px; font-weight: 600; font-family: sans-serif; font-size: 14px; display: inline-flex; align-items: center; cursor: pointer;">
                📥 PDF
            </a>
            <button id="btn-print" onclick="printReport()" style="background: #7c3aed; color: white; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; font-weight: 600; font-family: sans-serif; font-size: 14px;">
                🖨️ Stampa
            </button>
            <button id="btn-edit" onclick="toggleEditMode()" style="background: #2563eb; color: white; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; font-weight: 600; font-family: sans-serif; font-size: 14px;">
                ✏️ Modifica
            </button>
            <button id="btn-save" onclick="saveContent()" style="background: #16a34a; color: white; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; font-weight: 600; font-family: sans-serif; font-size: 14px; display: none;">
                💾 Salva
            </button>
            <button id="btn-cancel" onclick="cancelEdit()" style="background: #dc2626; color: white; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; font-weight: 600; font-family: sans-serif; font-size: 14px; display: none;">
                ❌ Annulla
            </button>
        </div>

        <script>
            let isEditMode = false;
            let originalContentBackup = "";
            const analysisId = {analysis_id};
            
            function printReport() {{
                // Force all tabs visible before printing
                var tabs = document.querySelectorAll('.tab-content');
                var originalDisplay = [];
                for (var i = 0; i < tabs.length; i++) {{
                    originalDisplay[i] = tabs[i].style.display;
                    tabs[i].style.display = 'block';
                }}
                
                // Print
                window.print();
                
                // Restore original display after a delay (print dialog is async)
                setTimeout(function() {{
                    for (var j = 0; j < tabs.length; j++) {{
                        tabs[j].style.display = originalDisplay[j] || '';
                    }}
                }}, 1000);
            }}

            function toggleEditMode() {{
                isEditMode = !isEditMode;
                const container = document.querySelector('.report-container') || document.body;
                const btnEdit = document.getElementById('btn-edit');
                const btnSave = document.getElementById('btn-save');
                const btnCancel = document.getElementById('btn-cancel');
                const btnPrint = document.getElementById('btn-print');

                if (isEditMode) {{
                    originalContentBackup = container.innerHTML; // Backup for Cancel
                    container.contentEditable = "true";
                    container.style.outline = "2px dashed #93c5fd";
                    container.style.padding = "10px";
                    btnEdit.style.display = "none";
                    btnSave.style.display = "inline-block";
                    btnCancel.style.display = "inline-block";
                    btnPrint.style.display = "none";
                    
                    document.querySelectorAll('a').forEach(a => a.style.pointerEvents = 'none');
                }} else {{
                    exitEditMode();
                }}
            }}

            function exitEditMode() {{
                isEditMode = false;
                const container = document.querySelector('.report-container') || document.body;
                container.contentEditable = "false";
                container.style.outline = "none";
                container.style.padding = "";
                document.getElementById('btn-edit').style.display = "inline-block";
                document.getElementById('btn-save').style.display = "none";
                document.getElementById('btn-cancel').style.display = "none";
                document.getElementById('btn-print').style.display = "inline-block";
                document.querySelectorAll('a').forEach(a => a.style.pointerEvents = 'auto');
            }}

            function cancelEdit() {{
                if (confirm("Annullare le modifiche non salvate?")) {{
                    const container = document.querySelector('.report-container') || document.body;
                    container.innerHTML = originalContentBackup;
                    exitEditMode();
                }}
            }}

            async function saveContent() {{
                const btnSave = document.getElementById('btn-save');
                btnSave.innerText = "Salvataggio...";
                btnSave.disabled = true;

                const container = document.querySelector('.report-container') || document.body;
                
                // 1. Prepare for saving: Remove edit artifacts
                container.contentEditable = "false";
                container.style.outline = "none";
                const toolbars = document.querySelectorAll('#edit-toolbar');
                toolbars.forEach(t => t.remove()); // Remove toolbar to not save it (backend reinjects it)

                // 2. Capture FULL document (Head + Body + Styles)
                const fullHtml = document.documentElement.outerHTML;
                
                try {{
                    const res = await fetch(`/analysis/${{analysisId}}/content?t=${{Date.now()}}`, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'text/html; charset=utf-8' }},
                        body: fullHtml 
                    }});
                    
                    if (res.ok) {{
                        alert("Modifiche salvate con successo!");
                        window.location.reload(); // Reload to get fresh state with re-injected toolbar
                    }} else {{
                        alert("Errore nel salvataggio via server.");
                        window.location.reload();
                    }}
                }} catch (e) {{
                    alert("Errore di connessione: " + e);
                    window.location.reload();
                }}
            }}
        </script>
        """
        # Append to body
        if "</body>" in html:
            html = html.replace("</body>", f"{toolbar_html}</body>")
        else:
            html += toolbar_html
            
    return HTMLResponse(content=html)

@router.get("/report/{analysis_id}/download")
async def download_report(analysis_id: int, format: str = "html", db: Session = Depends(get_db)):
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    if format == "html":
        return Response(
            content=analysis.report_html_display,
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename=report_{analysis_id}.html"}
        )
    elif format == "html_masked":
        return Response(
            content=analysis.report_html_masked,
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename=report_{analysis_id}_masked.html"}
        )
    elif format == "pdf":
        try:
            import re
            from xhtml2pdf import pisa
            from io import BytesIO
            from bs4 import BeautifulSoup
            
            html_content = analysis.report_html_display
            
            # Replace CSS var() with fallback values
            css_var_map = {
                '--primary': '#2563eb', '--primary-dark': '#1d4ed8',
                '--secondary': '#64748b', '--success': '#16a34a',
                '--danger': '#dc2626', '--warning': '#f59e0b',
                '--background': '#f8fafc', '--surface': '#ffffff',
                '--text': '#1e293b', '--text-light': '#64748b',
                '--border': '#e2e8f0', '--border-subtle': '#f1f5f9',
            }
            def replace_var(match):
                var_name = match.group(1)
                fallback = match.group(3) if match.group(3) else None
                return css_var_map.get(var_name, fallback or '#000000')
            html_content = re.sub(r'var\(\s*(--[\w-]+)\s*(,\s*([^)]+))?\)', replace_var, html_content)
            
            # Strip @font-face rules (xhtml2pdf can't load external fonts on Windows)
            html_content = re.sub(r'@font-face\s*\{[^}]*\}', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            html_content = re.sub(r'<link[^>]*fonts\.googleapis\.com[^>]*>', '', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'<link[^>]*fonts\.gstatic\.com[^>]*>', '', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'@import\s+url\([^)]*fonts[^)]*\)\s*;?', '', html_content, flags=re.IGNORECASE)
            
            # Strip gradients (xhtml2pdf doesn't support linear-gradient)
            html_content = re.sub(r'background:\s*linear-gradient\([^;]+\);?', 'background: #ffffff;', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'background-image:\s*linear-gradient\([^;]+\);?', '', html_content, flags=re.IGNORECASE)
            
            # Use BeautifulSoup to manipulate DOM
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Force all tab-content to display: block
            for tab in soup.find_all(class_='tab-content'):
                tab['style'] = tab.get('style', '') + '; display: block !important;'
            
            # Remove tab navigation (useless in PDF)
            for tabs in soup.find_all(class_='tabs'):
                tabs.decompose()
            
            # Remove edit toolbar if present
            for toolbar in soup.find_all(id='edit-toolbar'):
                toolbar.decompose()
                
            # Remove print buttons
            for btn in soup.find_all(class_='print-btn'):
                btn.decompose()
            
            # Inject print-safe CSS
            print_css = """
            <style>
                body { background: white !important; font-family: Arial, sans-serif !important; }
                .report-container { box-shadow: none !important; border: none !important; max-width: 100% !important; }
                .tab-content { display: block !important; page-break-inside: avoid; margin-bottom: 20px; }
                .info-grid, .summary-grid { page-break-inside: avoid; }
                table { page-break-inside: avoid; }
                .highlight-box { background: #fffbeb !important; border: 1px solid #f59e0b !important; }
                .alert-high { background: #fef2f2 !important; border-left: 4px solid #dc2626 !important; }
                .alert-medium { background: #fffbeb !important; border-left: 4px solid #f59e0b !important; }
                .alert-low { background: #f0fdf4 !important; border-left: 4px solid #16a34a !important; }
            </style>
            """
            if soup.head:
                soup.head.append(BeautifulSoup(print_css, 'html.parser'))
            
            html_content = str(soup)
            
            buffer = BytesIO()
            pisa_status = pisa.CreatePDF(html_content, dest=buffer)
            
            if pisa_status.err:
               return Response(f"PDF Generation Error", status_code=500)
               
            pdf_bytes = buffer.getvalue()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=report_{analysis_id}.pdf"}
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(f"PDF Generation failed: {str(e)}", status_code=500)
            
    return Response("Invalid format", status_code=400)

@router.delete("/analysis/{analysis_id}")
async def delete_analysis(request: Request, analysis_id: int, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Unauthorized")

    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    # Verify ownership (via document)
    if analysis.document.user_id != user_data["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        # Delete files
        if analysis.masked_text_path and os.path.exists(analysis.masked_text_path):
            try:
                os.remove(analysis.masked_text_path)
            except Exception as e:
                print(f"Error removing file: {e}")
                
        db.delete(analysis)
        db.commit()
        return JSONResponse({"status": "success", "message": "Analysis deleted"})
        
    except Exception as e:
        print(f"DELETE ERROR: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.post("/download-custom-pdf")
async def download_custom_pdf(request: Request):
    """
    Generates a PDF from the provided HTML content.
    Used for 'Edit Mode' where the user modifies the report in the browser.
    """
    import re
    
    try:
        # Get raw body as bytes, then decode
        body = await request.body()
        html_content = body.decode('utf-8')
        
        if not html_content:
             raise HTTPException(status_code=400, detail="Empty HTML content")

        # Replace CSS var() with fallback values (xhtml2pdf doesn't support CSS variables)
        css_var_map = {
            '--primary': '#2563eb',
            '--primary-dark': '#1d4ed8',
            '--secondary': '#64748b',
            '--success': '#16a34a',
            '--danger': '#dc2626',
            '--warning': '#f59e0b',
            '--background': '#f8fafc',
            '--surface': '#ffffff',
            '--text': '#1e293b',
            '--text-light': '#64748b',
            '--border': '#e2e8f0',
            '--border-subtle': '#f1f5f9',
        }
        
        # Replace var(--name) or var(--name, fallback) patterns
        def replace_var(match):
            var_name = match.group(1)
            fallback = match.group(3) if match.group(3) else None
            return css_var_map.get(var_name, fallback or '#000000')
        
        html_content = re.sub(r'var\(\s*(--[\w-]+)\s*(,\s*([^)]+))?\)', replace_var, html_content)

        # Strip @font-face rules (xhtml2pdf can't load external fonts on Windows - permission issues)
        html_content = re.sub(r'@font-face\s*\{[^}]*\}', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        
        # Strip Google Fonts link tags
        html_content = re.sub(r'<link[^>]*fonts\.googleapis\.com[^>]*>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<link[^>]*fonts\.gstatic\.com[^>]*>', '', html_content, flags=re.IGNORECASE)
        
        # Strip @import for fonts
        html_content = re.sub(r'@import\s+url\([^)]*fonts[^)]*\)\s*;?', '', html_content, flags=re.IGNORECASE)

        from xhtml2pdf import pisa
        from io import BytesIO
        
        buffer = BytesIO()
        
        pisa_status = pisa.CreatePDF(html_content, dest=buffer)
        
        if pisa_status.err:
           return Response(f"PDF Generation Error", status_code=500)
           
        pdf_bytes = buffer.getvalue()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=custom_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"}
        )
    except Exception as e:
        print(f"Custom PDF Error: {e}")
        return Response(f"PDF Generation failed: {str(e)}", status_code=500)

@router.post("/analysis/{analysis_id}/save")
async def save_analysis(
    analysis_id: int, 
    request: Request,
    title: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")
            
        analysis.title = title
        analysis.is_saved = True
        analysis.last_updated = datetime.utcnow()
        db.commit()
        
        return JSONResponse({"status": "success", "message": "Report saved successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@router.post("/analysis/{analysis_id}/rename")
async def rename_analysis(
    analysis_id: int, 
    request: Request,
    title: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")
            
        analysis.title = title
        analysis.last_updated = datetime.utcnow()
        db.commit()
        
        return JSONResponse({"status": "success", "message": "Report renamed successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@router.post("/analysis/{analysis_id}/content")
async def update_analysis_content(
    analysis_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Updates the HTML content of the report (persistence for Edit Mode).
    Expects raw HTML body.
    """
    try:
        body = await request.body()
        html_content = body.decode('utf-8')
        
        print(f"DEBUG: Saving content for analysis {analysis_id}. Length: {len(html_content)}")
        
        analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
        if not analysis:
            print("DEBUG: Analysis not found!")
            raise HTTPException(status_code=404, detail="Analysis not found")
            
        analysis.report_html_display = html_content
        analysis.last_updated = datetime.utcnow()
        db.commit()
        print("DEBUG: Commit successful.")
        
        return JSONResponse({"status": "success", "message": "Content updated"})
    except Exception as e:
        db.rollback()
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


from playwright.sync_api import sync_playwright

@router.get("/report/{analysis_id}/download-pdf")
def download_report_pdf(analysis_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Generates a high-quality PDF using Playwright (Chromium) - Synchronous Version for Windows Compatibility.
    """
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Use the display version (user edited) if available, otherwise masked
    html_content = analysis.report_html_display or analysis.report_html_masked
    if not html_content:
        raise HTTPException(status_code=404, detail="Report content not ready")

    filename = f"PoliSight_Report_{analysis_id}.pdf"
    if analysis.title:
        safe_title = "".join([c for c in analysis.title if c.isalnum() or c in (' ', '-', '_')]).strip()
        filename = f"{safe_title}.pdf"

    # Base URL using request.base_url
    base_url = str(request.base_url)

    # Use sync_playwright (runs in threadpool via FastAPI)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()


        # Inject <base> tag for relative links
        if "<head>" in html_content:
            html_content = html_content.replace("<head>", f'<head><base href="{base_url}">')
        else:
            html_content = f'<base href="{base_url}">' + html_content

        # Set content with base_url
        page.set_content(html_content, wait_until="networkidle")

        # Inject Print CSS optimizations
        page.add_style_tag(content="""
            @page { margin: 15mm 10mm; size: A4; }
            body { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
            
            /* Force all tabs visible */
            .tab-content { display: block !important; opacity: 1 !important; visibility: visible !important; height: auto !important; margin-bottom: 20px; border-bottom: 1px dashed #e2e8f0; }
            
            /* Hide UI elements */
            .tabs, .header-navigation, #edit-toolbar, .print-btn, .btn, button, .navbar { display: none !important; }
            
            /* Avoid breaking cards and keep headers with content */
            h1, h2, h3, h4, h5, h6 { page-break-after: avoid; break-after: avoid; }
            .card, .section, .clause-card, .edu-card, .example-card, .alert-box { page-break-inside: avoid; break-inside: avoid; margin-bottom: 15px; }
            
            /* Fix Tables overflow and overlap */
            table { width: 100% !important; border-collapse: collapse; margin-bottom: 10px; }
            td, th { 
                padding: 6px 4px; 
                font-size: 9pt; 
                vertical-align: top; 
                line-height: 1.4;
                word-wrap: break-word;
                overflow-wrap: break-word;
                border: 1px solid #e2e8f0; /* adds clarity */
            }
            
            /* Specific fix for numeric/money columns to prevent wrapping midsentence if possible, but allow if needed */
            td.numeric { white-space: nowrap; }
            
            /* Reset container width for print */
            .report-container { max-width: 100% !important; width: 100% !important; border: none !important; box-shadow: none !important; margin: 0 !important; padding: 0 !important; }
            
            /* Better font rendering */
            body { -webkit-font-smoothing: antialiased; }
            
            /* Hide empty chart containers if any */
            canvas { max-width: 100%; }
        """)

        # Disable Chart.js animations
        page.evaluate("() => { if(window.Chart) { Chart.defaults.animation = false; } }")
        
        # Security wait
        page.wait_for_timeout(1000)

        pdf_data = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "15mm", "bottom": "15mm", "left": "10mm", "right": "10mm"}
        )

        browser.close()

    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

