import fitz  # PyMuPDF
import pytesseract
import numpy as np
import os
from datetime import datetime

# Initialize predictors (load models once if possible, or lazy load)
# For MVP, lazy loading inside function or global init might be acceptable
# but doctr models are heavy. Let's load purely when needed or keep global if memory allows.
# For efficiency in MVP server, let's keep it global but wrap in try-except if user doesn't have it.

DOCTR_MODEL = None

def get_doctr_model():
    global DOCTR_MODEL
    if DOCTR_MODEL is None:
        try:
            # Using cpu by default for compatibility, use cuda:True if GPU available
            from doctr.models import ocr_predictor
            DOCTR_MODEL = ocr_predictor(det_arch='db_resnet50', reco_arch='crnn_vgg16_bn', pretrained=True)
        except Exception as e:
            print(f"Warning: could not load Doctr model or dependencies missing: {e}")
            return None
    return DOCTR_MODEL

def extract_native_text(file_path: str) -> str:
    """Extract text from PDF using PyMuPDF (native)."""
    text = ""
    try:
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
    except Exception as e:
        print(f"Error in extract_native_text: {e}")
    return text

def extract_with_tesseract(file_path: str) -> str:
    """Fallback OCR using Tesseract with rotation correction."""
    text = ""
    try:
        with fitz.open(file_path) as doc:
            for page in doc:
                # Render at optimal resolution (2x zoom = ~144 DPI) - sufficient for Italian OCR
                mat = fitz.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat)
                mode = "RGB" if pix.alpha == 0 else "RGBA"
                img_data = pix.samples
                from PIL import Image
                img = Image.frombytes(mode, [pix.width, pix.height], img_data)
                
                # OSD Rotation Detection (expensive, only if needed)
                try:
                    osd = pytesseract.image_to_osd(img)
                    # Parse rotation angle (e.g. "Rotate: 90")
                    rotation = 0
                    for line in osd.split("\n"):
                        if "Rotate:" in line:
                            rotation = int(line.split(":")[1].strip())
                            break
                    
                    if rotation != 0:
                        # print(f"Detected rotation: {rotation}")
                        img = img.rotate(-rotation, expand=True)
                except Exception as e:
                    # OSD can fail on pages with little text
                    print(f"OSD failed, skipping rotation: {e}")

                # Tesseract OCR
                page_text = pytesseract.image_to_string(img, lang='ita')
                text += page_text + "\n"
    except Exception as e:
        print(f"Error in extract_with_tesseract: {e}")
    return text

def extract_with_doctr(file_path: str) -> str:
    """OCR using Doctr (Converting PDF to images first for consistency)."""
    try:
        from doctr.io import DocumentFile
    except (ImportError, OSError) as e:
        raise RuntimeError(f"Doctr dependencies missing: {e}")

    model = get_doctr_model()
    if not model:
        raise RuntimeError("Doctr model not available")
    
    # Manually render PDF pages to images using PyMuPDF
    # This ensures we get high-resolution input (same as Tesseract fix)
    # and bypass potential system dependency issues with DocumentFile.from_pdf
    page_images = []
    try:
        with fitz.open(file_path) as doc:
            for page in doc:
                # 2.0 zoom = ~144 DPI (optimal balance for Speed/Accuracy on Italian text)
                mat = fitz.Matrix(2.0, 2.0) 
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to numpy array for Doctr
                # pix.samples is bytes, we need to shape it (h, w, 3)
                img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
                
                # Doctr expects RGB. If RGBA (n=4), drop alpha
                if pix.n == 4:
                    img_array = img_array[..., :3]
                
                page_images.append(img_array)
    except Exception as e:
        print(f"Error rendering PDF for Doctr: {e}")
        # If rendering fails, we can't do Doctr this way.
        raise e

    if not page_images:
        return ""

    # Pass list of numpy arrays to Doctr
    doc = DocumentFile.from_images(page_images)
    result = model(doc)
    text = ""
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    text += word.value + " "
                text += "\n"
    return text

def word_count(text: str) -> int:
    return len(text.split())

def is_text_quality_good(text: str) -> bool:
    """
    Check if extracted text is readable (not garbled from rotation issues).
    Returns False if text appears to be from a rotated page.
    """
    if not text or len(text.strip()) < 20:
        return False
    
    # Count alphanumeric vs special characters
    alnum_count = sum(1 for c in text if c.isalnum())
    total_chars = len(text.replace(" ", "").replace("\n", ""))
    
    if total_chars == 0:
        return False
    
    alnum_ratio = alnum_count / total_chars
    
    # If less than 60% alphanumeric, likely garbled
    if alnum_ratio < 0.60:
        print(f"  Text quality check: low alnum ratio {alnum_ratio:.2f}")
        return False
    
    # Check for too many non-Italian/non-English characters
    # Garbled text often has lots of unusual character sequences
    words = text.split()
    if len(words) > 10:
        # Check if most "words" are very short (1-2 chars) - sign of garbled text
        short_words = sum(1 for w in words if len(w) <= 2)
        short_ratio = short_words / len(words)
        if short_ratio > 0.5:
            print(f"  Text quality check: too many short words {short_ratio:.2f}")
            return False
        
        # Check for repeated unusual patterns
        unusual_chars = sum(1 for c in text if c in "°''""«»§←→↑↓∈∉∪∩")
        if unusual_chars > len(text) * 0.05:
            print(f"  Text quality check: too many unusual chars")
            return False
    
    return True

def get_page_word_counts(file_path: str) -> list[tuple[int, str, int, bool]]:
    """
    Returns list of (word_count, text, rotation, is_quality_good) for each page.
    rotation: page rotation in degrees (0, 90, 180, 270)
    is_quality_good: True if text appears readable, False if likely garbled
    """
    page_data = []
    try:
        with fitz.open(file_path) as doc:
            for page_num, page in enumerate(doc):
                text = page.get_text()
                rotation = page.rotation  # 0, 90, 180, or 270
                quality_good = is_text_quality_good(text)
                
                if rotation != 0:
                    print(f"  Page {page_num + 1}: Detected rotation metadata: {rotation}°")
                if not quality_good:
                    print(f"  Page {page_num + 1}: Text quality check FAILED - will use OCR")
                
                page_data.append((word_count(text), text, rotation, quality_good))
    except Exception as e:
        print(f"Error getting page word counts: {e}")
    return page_data

def extract_images_from_page_ocr(page, page_num: int) -> str:
    """Extract images from a page and run OCR on them using Tesseract."""
    from PIL import Image
    text_parts = []
    
    try:
        images = page.get_images()
        for img_index, img in enumerate(images):
            xref = img[0]
            # Get image dimensions - skip small images (logos, icons)
            width = img[2]
            height = img[3]
            if width < 500 or height < 500:
                continue
                
            try:
                base_image = page.parent.extract_image(xref)
                image_bytes = base_image["image"]
                
                # Convert to PIL Image
                import io
                pil_image = Image.open(io.BytesIO(image_bytes))
                
                # Convert to RGB if needed
                if pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                
                # OSD Rotation Detection for embedded images (expensive, only if needed)
                try:
                    osd = pytesseract.image_to_osd(pil_image)
                    rotation = 0
                    for line in osd.split("\n"):
                        if "Rotate:" in line:
                            rotation = int(line.split(":")[1].strip())
                            break
                    if rotation != 0:
                        print(f"  Image {img_index} on page {page_num}: Detected rotation {rotation}°, correcting...")
                        pil_image = pil_image.rotate(-rotation, expand=True)
                except Exception as e:
                    # OSD can fail on images with little text
                    pass
                
                # Run Tesseract OCR on the image
                ocr_text = pytesseract.image_to_string(pil_image, lang='ita')
                if ocr_text.strip():
                    text_parts.append(ocr_text)
                    
            except Exception as e:
                print(f"Error extracting image {img_index} from page {page_num}: {e}")
                continue
                
    except Exception as e:
        print(f"Error processing images on page {page_num}: {e}")
    
    return "\n".join(text_parts)

# ============================================================================
# PHASE 2A: PARALLEL OCR IMPLEMENTATION (2 Workers)
# ============================================================================

def process_single_page(args: tuple) -> tuple:
    """
    Worker function for parallel processing of a single PDF page.
    This function is called by ProcessPoolExecutor for each page.
    
    Args:
        args: (file_path, page_num, wc, native_text, rotation, quality_good, pages_needing_ocr)
    
    Returns:
        (page_num, extracted_text)
    """
    file_path, page_num, wc, native_text, rotation, quality_good, pages_needing_ocr = args
    
    # If page doesn't need OCR, return native text immediately
    if page_num not in pages_needing_ocr:
        return (page_num, native_text)
    
    try:
        import fitz
        from PIL import Image
        import pytesseract
        
        with fitz.open(file_path) as doc:
            page = doc[page_num]
            
            # Try OCR on embedded images first
            ocr_text = extract_images_from_page_ocr(page, page_num)
            
            if word_count(ocr_text) > wc and is_text_quality_good(ocr_text):
                print(f"  [Worker] Page {page_num + 1}: Embedded image OCR extracted {word_count(ocr_text)} words")
                return (page_num, ocr_text)
            
            # Fallback: full page render + OCR
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom (144 DPI)
            pix = page.get_pixmap(matrix=mat)
            mode = "RGB" if pix.alpha == 0 else "RGBA"
            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # OSD only if rotation metadata is 0 (unknown)
            if rotation == 0:
                try:
                    osd = pytesseract.image_to_osd(img)
                    for line in osd.split("\n"):
                        if "Rotate:" in line:
                            detected_rotation = int(line.split(":")[1].strip())
                            if detected_rotation != 0:
                                img = img.rotate(-detected_rotation, expand=True)
                                print(f"  [Worker] Page {page_num + 1}: OSD detected rotation {detected_rotation}°")
                            break
                except:
                    pass  # OSD failed, continue without rotation
            elif rotation != 0:
                img = img.rotate(-rotation, expand=True)
            
            full_page_ocr = pytesseract.image_to_string(img, lang='ita')
            
            if word_count(full_page_ocr) > wc or is_text_quality_good(full_page_ocr):
                print(f"  [Worker] Page {page_num + 1}: Full-page OCR extracted {word_count(full_page_ocr)} words")
                return (page_num, full_page_ocr)
            else:
                print(f"  [Worker] Page {page_num + 1}: Kept native text ({wc} words)")
                return (page_num, native_text)
                
    except Exception as e:
        print(f"ERROR [Worker] Page {page_num + 1}: {e}")
        return (page_num, native_text)  # Fallback to native on error


def process_pdf_parallel(file_path: str, page_data: list, pages_needing_ocr: set, num_pages: int) -> str:
    """
    Process PDF with parallel OCR using max 2 workers (Phase 2A).
    
    Args:
        file_path: Path to PDF
        page_data: List of (wc, native_text, rotation, quality_good) for each page
        pages_needing_ocr: Set of page numbers that need OCR
        num_pages: Total pages
    
    Returns:
        Combined text from all pages
    """
    from concurrent.futures import ProcessPoolExecutor
    import psutil
    
    # Safety check #1: RAM >= 2GB
    try:
        mem = psutil.virtual_memory()
        available_gb = mem.available / (1024 ** 3)
        
        if available_gb < 2.0:
            print(f"⚠️ WARNING: Low RAM ({available_gb:.2f}GB < 2GB), falling back to sequential OCR")
            return process_pdf_sequential(file_path, page_data, pages_needing_ocr, num_pages)
    except Exception as e:
        print(f"⚠️ WARNING: Could not check RAM ({e}), falling back to sequential OCR")
        return process_pdf_sequential(file_path, page_data, pages_needing_ocr, num_pages)
    
    # Safety check #2: Only use parallel for files with >= 10 pages
    if num_pages < 10:
        print(f"ℹ️ INFO: File has only {num_pages} pages, using sequential OCR")
        return process_pdf_sequential(file_path, page_data, pages_needing_ocr, num_pages)
    
    print(f"🚀 PARALLEL OCR (2 workers): {num_pages} pages, {len(pages_needing_ocr)} need OCR | RAM: {available_gb:.2f}GB")
    
    # Prepare arguments for workers
    worker_args = [
        (file_path, page_num, wc, native_text, rotation, quality_good, pages_needing_ocr)
        for page_num, (wc, native_text, rotation, quality_good) in enumerate(page_data)
    ]
    
    # Process in parallel with max 2 workers
    try:
        with ProcessPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(process_single_page, worker_args))
        
        # Sort by page number and extract text
        results.sort(key=lambda x: x[0])
        combined_text = [text for _, text in results]
        
        print(f"✅ PARALLEL OCR completed successfully")
        return "\n".join(combined_text)
        
    except Exception as e:
        print(f"❌ ERROR: Parallel processing failed: {e}")
        print("FALLBACK: Using sequential OCR")
        return process_pdf_sequential(file_path, page_data, pages_needing_ocr, num_pages)



def append_debug_log(msg: str):
    """Write to a debug log file for real-time tracking"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    with open("ocr_debug.log", "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")

def process_pdf_sequential(file_path: str, page_data: list, pages_needing_ocr: set, num_pages: int) -> str:
    """
    Sequential OCR processing (original implementation).
    This is a fallback when parallel is not safe/beneficial.
    """
    msg = f"📄 SEQUENTIAL OCR STARTED: {num_pages} pages, {len(pages_needing_ocr)} need OCR"
    print(msg)
    append_debug_log(msg)
    
    combined_text = []
    
    try:
        with fitz.open(file_path) as doc:
            for page_num, (wc, native_text, rotation, quality_good) in enumerate(page_data):
                # Use native text if page doesn't need OCR
                if page_num not in pages_needing_ocr:
                    combined_text.append(native_text)
                    continue
                
                # Page needs OCR - existing hybrid logic
                append_debug_log(f"Process Page {page_num+1} - Start OCR")
                page = doc[page_num]
                
                # Try embedded images first
                ocr_text = extract_images_from_page_ocr(page, page_num)
                
                if word_count(ocr_text) > wc and is_text_quality_good(ocr_text):
                    combined_text.append(ocr_text)
                    print(f"  Page {page_num + 1}: Embedded image OCR extracted {word_count(ocr_text)} words")
                    append_debug_log(f"Process Page {page_num+1} - Embedded Image OCR Success ({word_count(ocr_text)} words)")
                else:
                    # Full page render + OCR
                    mat = fitz.Matrix(2.0, 2.0)
                    pix = page.get_pixmap(matrix=mat)
                    from PIL import Image
                    mode = "RGB" if pix.alpha == 0 else "RGBA"
                    img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # OSD rotation detection (only if metadata rotation is 0)
                    if rotation == 0:
                        try:
                            osd = pytesseract.image_to_osd(img)
                            detected_rotation = 0
                            for line in osd.split("\n"):
                                if "Rotate:" in line:
                                    detected_rotation = int(line.split(":")[1].strip())
                                    break
                            if detected_rotation != 0:
                                print(f"  Page {page_num + 1}: OSD detected rotation {detected_rotation}°, correcting...")
                                img = img.rotate(-detected_rotation, expand=True)
                        except Exception as e:
                            print(f"  Page {page_num + 1}: OSD failed: {e}")
                    
                    append_debug_log(f"Process Page {page_num+1} - Full Page Tesseract Start")
                    full_page_ocr = pytesseract.image_to_string(img, lang='ita')
                    append_debug_log(f"Process Page {page_num+1} - Full Page Tesseract End")
                    
                    if word_count(full_page_ocr) > wc or is_text_quality_good(full_page_ocr):
                        combined_text.append(full_page_ocr)
                        print(f"  Page {page_num + 1}: Full-page OCR extracted {word_count(full_page_ocr)} words")
                    else:
                        combined_text.append(native_text)
                        print(f"  Page {page_num + 1}: Kept native text ({wc} words) - OCR didn't improve")
        
        append_debug_log(f"SEQUENTIAL OCR FINISHED")
        return "\n".join(combined_text)
        
    except Exception as e:
        err_msg = f"Error in sequential processing: {e}"
        print(err_msg)
        append_debug_log(err_msg)

        text_tess = extract_with_tesseract(file_path)
        return text_tess

# ============================================================================

def process_pdf(file_path: str) -> tuple[str, str]:
    """
    Ritorna (testo_estratto, metodo_usato)
    metodo_usato: 'nativo' | 'ibrido' | 'ocr_doctr' | 'ocr_tesseract'
    
    Logica migliorata:
    1. Estrae testo nativo e conta parole per pagina
    2. Verifica qualità testo e rotazione pagine
    3. Se media parole/pagina >= 50 E tutte le pagine hanno buona qualità: PDF nativo
    4. Altrimenti: approccio ibrido (testo nativo + OCR su pagine problematiche)
    """
    MIN_WORDS_PER_PAGE = 50  # Soglia per considerare una pagina "ricca" di testo
    
    # Step 1: Analizza ogni pagina (ora restituisce 4 elementi)
    page_data = get_page_word_counts(file_path)
    
    if not page_data:
        # Fallback a Tesseract se non riusciamo a leggere il PDF
        print("Could not read PDF pages, falling back to Tesseract...")
        text_tess = extract_with_tesseract(file_path)
        return text_tess, 'ocr_tesseract'
    
    total_words = sum(wc for wc, _, _, _ in page_data)
    num_pages = len(page_data)
    avg_words_per_page = total_words / num_pages if num_pages > 0 else 0
    
    print(f"PDF Analysis: {num_pages} pages, {total_words} total words, {avg_words_per_page:.1f} avg words/page")
    
    # Count pages that need OCR (low text OR poor quality OR rotated)
    pages_needing_ocr = []
    for i, (wc, _, rotation, quality_good) in enumerate(page_data):
        needs_ocr = False
        reasons = []
        
        if wc < MIN_WORDS_PER_PAGE:
            needs_ocr = True
            reasons.append(f"low words ({wc})")
        if not quality_good:
            needs_ocr = True
            reasons.append("poor quality")
        if rotation != 0:
            needs_ocr = True
            reasons.append(f"rotated {rotation}°")
        
        if needs_ocr:
            pages_needing_ocr.append(i)
            print(f"  Page {i + 1} needs OCR: {', '.join(reasons)}")
    
    # Step 2: Decide strategy
    if len(pages_needing_ocr) == 0 and avg_words_per_page >= MIN_WORDS_PER_PAGE:
        # PDF nativo - tutte le pagine sono OK
        full_text = "\n".join(text for _, text, _, _ in page_data)
        print(f"PDF classified as NATIVE (all pages OK)")
        return full_text, 'nativo'
    
    # Step 3: Approccio ibrido - usa PARALLEL OCR (Phase 2A)
    print(f"PDF classified as HYBRID - {len(pages_needing_ocr)} pages need OCR out of {num_pages}")
    
    # ⚠️ WINDOWS FIX: Disable parallel processing on Windows to avoid spawn issues
    if os.name == 'nt':
        print("ℹ️ Windows detected: Using SEQUENTIAL OCR to avoid multiprocessing spawn issues")
        text = process_pdf_sequential(file_path, page_data, pages_needing_ocr, num_pages)
        return text, 'ibrido'

    # Call parallel OCR (auto-falls back to sequential if RAM low or file small)
    combined_text = process_pdf_parallel(file_path, page_data, pages_needing_ocr, num_pages)
    
    return combined_text, 'ibrido'

# Doctr removed for VPS stability - use Tesseract only

def process_image(file_path: str) -> tuple[str, str]:
    """Process an image file using Tesseract OCR."""
    # Doctr disabled for VPS stability - Tesseract only
    try:
        from PIL import Image
        print("Processing image with Tesseract...")
        img = Image.open(file_path)
        # Using pytesseract with PSM 3 (Fully automatic page segmentation)
        try:
             text = pytesseract.image_to_string(img, lang='ita', config='--psm 3')
        except Exception:
             # Retry with default config
             text = pytesseract.image_to_string(img, lang='ita')
             
        return text, 'ocr_image_tesseract'
    except Exception as e:
        print(f"Image OCR failed: {e}")
        return "", 'error'

def process_document(file_path: str, mime_type: str = "application/pdf") -> tuple[str, str]:
    """
    Dispatcher per elaborare PDF o Immagini.
    """
    if "pdf" in mime_type.lower():
        return process_pdf(file_path)
    elif "image" in mime_type.lower():
        return process_image(file_path)
    else:
        # Fallback to PDF logic or error
        return process_pdf(file_path)
