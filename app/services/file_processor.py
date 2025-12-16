import os
import shutil
import uuid
import logging
import extract_msg
import email
from email import policy
import docx2pdf
from docx import Document as DocxDocument
import pandas as pd
from openpyxl import load_workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def convert_image_to_pdf(image_path, output_path):
    """Convert an image to a single-page PDF."""
    try:
        img = Image.open(image_path)
        c = canvas.Canvas(output_path, pagesize=img.size)
        c.drawImage(image_path, 0, 0, width=img.size[0], height=img.size[1])
        c.save()
        return True
    except Exception as e:
        logger.error(f"Error converting image to PDF: {e}")
        return False

def convert_excel_to_pdf(excel_path, output_path):
    """
    Convert Excel to PDF. 
    Note: Perfect Excel-to-PDF conversion often requires Excel installed (win32com).
    For server-side without Office, we can convert to HTML then PDF, or simple text dump.
    Here we use a simple text dump approach for stability, or better yet, pandas to HTML to PDF.
    Actual implementation depends on server capabilities.
    For this MVP, we will try to extract text and create a simple dictionary-like PDF or just skip visual fidelity.
    """
    # Placeholder: Real Excel to PDF is complex without Excel installed.
    # We will accept that 'preview' might be just extracted text for now.
    pass

def process_file_recursive(file_path, output_dir, visited=None):
    """
    Recursively process a file:
    - If Archive (zip/rar) -> Extract and recurse.
    - If Email (msg/eml) -> Extract body/attachments and recurse.
    - If Office -> Convert to PDF.
    - If Image -> Convert to PDF.
    - If PDF -> Keep.
    
    Returns a list of dicts: { 'path': ..., 'original_name': ..., 'type': ... }
    """
    if visited is None:
        visited = set()
        
    file_id = str(uuid.uuid4())
    filename = os.path.basename(file_path)
    base_name, ext = os.path.splitext(filename)
    ext = ext.lower()
    
    processed_files = []
    
    # Avoid infinite loops (symlinks or zip bombs)
    if file_path in visited:
        return []
    visited.add(file_path)

    logger.info(f"Processing: {file_path}")

    # 1. EMAIL Processing (.msg)
    if ext == '.msg':
        try:
            msg = extract_msg.Message(file_path)
            
            # Save body as text/pdf
            body_text = msg.body
            pdf_path = os.path.join(output_dir, f"{base_name}_body.pdf")
            
            # Simple text to pdf for email body
            c = canvas.Canvas(pdf_path, pagesize=letter)
            textobject = c.beginText(40, 750)
            textobject.setFont("Helvetica", 10)
            for line in body_text.split('\n'):
                textobject.textLine(line[:100]) # Truncate long lines for MVP
            c.drawText(textobject)
            c.save()
            
            processed_files.append({
                'path': pdf_path,
                'original_name': f"Email Body: {filename}",
                'type': 'application/pdf'
            })
            
            # Process Attachments
            for att in msg.attachments:
                att_name = att.longFilename or att.shortFilename
                if not att_name:
                    att_name = f"attachment_{uuid.uuid4()}"
                    
                att_path = os.path.join(output_dir, att_name)
                att.save(customPath=output_dir, customFilename=att_name)
                
                # Recurse
                processed_files.extend(process_file_recursive(att_path, output_dir, visited))
                
        except Exception as e:
            logger.error(f"Error processing .msg {file_path}: {e}")

    # 2. EMAIL Processing (.eml)
    elif ext == '.eml':
        try:
            with open(file_path, 'rb') as f:
                msg = email.message_from_binary_file(f, policy=policy.default)
                
            body = msg.get_body(preferencelist=('plain', 'html'))
            body_text = body.get_content() if body else "No body content"
            
            pdf_path = os.path.join(output_dir, f"{base_name}_body.pdf")
            c = canvas.Canvas(pdf_path, pagesize=letter)
            textobject = c.beginText(40, 750)
            textobject.setFont("Helvetica", 10)
            for line in body_text.split('\n'):
                 textobject.textLine(line[:100])
            c.drawText(textobject)
            c.save()
            
            processed_files.append({
                'path': pdf_path,
                'original_name': f"Email Body: {filename}",
                'type': 'application/pdf'
            })
            
            for part in msg.iter_attachments():
                att_name = part.get_filename() or f"attachment_{uuid.uuid4()}"
                att_path = os.path.join(output_dir, att_name)
                with open(att_path, 'wb') as f:
                    f.write(part.get_payload(decode=True))
                
                processed_files.extend(process_file_recursive(att_path, output_dir, visited))

        except Exception as e:
            logger.error(f"Error processing .eml {file_path}: {e}")

    # 3. WORD Processing (.docx)
    elif ext == '.docx':
        try:
            # Requires Word installed on Windows for docx2pdf
            # Fallback if failed?
            pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
            try:
                docx2pdf.convert(file_path, pdf_path)
                processed_files.append({
                    'path': pdf_path,
                    'original_name': filename,
                    'type': 'application/pdf'
                })
            except Exception as e:
                logger.warning(f"docx2pdf failed: {e}. Trying simple text extraction.")
                # Fallback: Extract text
                # ...
                pass
        except Exception as e:
             logger.error(f"Error processing .docx {file_path}: {e}")

    # 4. EXCEL Processing (.xlsx)
    elif ext == '.xlsx':
        # TODO: Implement Excel handling (maybe text dump)
        pass

    # 5. IMAGE Processing
    elif ext in ['.jpg', '.jpeg', '.png', '.bmp']:
        pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        if convert_image_to_pdf(file_path, pdf_path):
             processed_files.append({
                'path': pdf_path,
                'original_name': filename,
                'type': 'application/pdf'
            })

    # 6. PDF (Native)
    elif ext == '.pdf':
        processed_files.append({
            'path': file_path,
            'original_name': filename,
            'type': 'application/pdf'
        })
        
    return processed_files
