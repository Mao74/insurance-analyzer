import fitz  # PyMuPDF
import pytesseract
import numpy as np

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
                # Render at higher resolution (3x zoom = ~216 DPI) for better OCR
                mat = fitz.Matrix(3.0, 3.0)
                pix = page.get_pixmap(matrix=mat)
                mode = "RGB" if pix.alpha == 0 else "RGBA"
                img_data = pix.samples
                from PIL import Image
                img = Image.frombytes(mode, [pix.width, pix.height], img_data)
                
                # OSD Rotation Detection
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
                # 3.0 zoom = ~216 DPI (good balance for Speed/Accuracy)
                mat = fitz.Matrix(3.0, 3.0) 
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

def get_page_word_counts(file_path: str) -> list[tuple[int, str]]:
    """Returns list of (word_count, text) for each page."""
    page_data = []
    try:
        with fitz.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                page_data.append((word_count(text), text))
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

def process_pdf(file_path: str) -> tuple[str, str]:
    """
    Ritorna (testo_estratto, metodo_usato)
    metodo_usato: 'nativo' | 'ibrido' | 'ocr_doctr' | 'ocr_tesseract'
    
    Logica migliorata:
    1. Estrae testo nativo e conta parole per pagina
    2. Se media parole/pagina >= 50: PDF nativo
    3. Se media < 50: approccio ibrido (testo nativo + OCR su pagine povere)
    """
    MIN_WORDS_PER_PAGE = 50  # Soglia per considerare una pagina "ricca" di testo
    
    # Step 1: Analizza ogni pagina
    page_data = get_page_word_counts(file_path)
    
    if not page_data:
        # Fallback a Tesseract se non riusciamo a leggere il PDF
        print("Could not read PDF pages, falling back to Tesseract...")
        text_tess = extract_with_tesseract(file_path)
        return text_tess, 'ocr_tesseract'
    
    total_words = sum(wc for wc, _ in page_data)
    num_pages = len(page_data)
    avg_words_per_page = total_words / num_pages if num_pages > 0 else 0
    
    print(f"PDF Analysis: {num_pages} pages, {total_words} total words, {avg_words_per_page:.1f} avg words/page")
    
    # Count pages with low text content
    low_text_pages = [i for i, (wc, _) in enumerate(page_data) if wc < MIN_WORDS_PER_PAGE]
    
    # Step 2: Decide strategy
    if avg_words_per_page >= MIN_WORDS_PER_PAGE and len(low_text_pages) < num_pages * 0.3:
        # PDF nativo - più del 70% delle pagine ha testo sufficiente
        full_text = "\n".join(text for _, text in page_data)
        print(f"PDF classified as NATIVE ({len(low_text_pages)} low-text pages out of {num_pages})")
        return full_text, 'nativo'
    
    # Step 3: Approccio ibrido - estrai testo + OCR sulle pagine con poco testo
    print(f"PDF classified as HYBRID - {len(low_text_pages)} pages need OCR out of {num_pages}")
    
    combined_text = []
    
    try:
        with fitz.open(file_path) as doc:
            for page_num, (wc, native_text) in enumerate(page_data):
                if wc >= MIN_WORDS_PER_PAGE:
                    # Pagina con testo sufficiente - usa testo nativo
                    combined_text.append(native_text)
                else:
                    # Pagina con poco testo - prova OCR su immagini embedded
                    page = doc[page_num]
                    ocr_text = extract_images_from_page_ocr(page, page_num)
                    
                    if word_count(ocr_text) > word_count(native_text):
                        # OCR ha estratto più testo
                        combined_text.append(ocr_text)
                        print(f"  Page {page_num + 1}: OCR extracted {word_count(ocr_text)} words (native had {wc})")
                    else:
                        # Fallback: renderizza intera pagina e OCR
                        mat = fitz.Matrix(2.0, 2.0)  # 2x zoom
                        pix = page.get_pixmap(matrix=mat)
                        from PIL import Image
                        mode = "RGB" if pix.alpha == 0 else "RGBA"
                        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        full_page_ocr = pytesseract.image_to_string(img, lang='ita')
                        
                        if word_count(full_page_ocr) > wc:
                            combined_text.append(full_page_ocr)
                            print(f"  Page {page_num + 1}: Full-page OCR extracted {word_count(full_page_ocr)} words")
                        else:
                            combined_text.append(native_text)
                            print(f"  Page {page_num + 1}: Kept native text ({wc} words)")
    
    except Exception as e:
        print(f"Error in hybrid processing: {e}")
        # Fallback completo a Tesseract
        text_tess = extract_with_tesseract(file_path)
        return text_tess, 'ocr_tesseract'
    
    return "\n".join(combined_text), 'ibrido'

def extract_image_with_doctr(file_path: str) -> str:
    """OCR an image file using Doctr."""
    try:
        from doctr.io import DocumentFile
    except (ImportError, OSError) as e:
        raise RuntimeError(f"Doctr dependencies missing: {e}")

    model = get_doctr_model()
    if not model:
        raise RuntimeError("Doctr model not available")
    
    # Load image for Doctr
    doc = DocumentFile.from_images(file_path)
    result = model(doc)
    
    text = ""
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    text += word.value + " "
                text += "\n"
    return text

def process_image(file_path: str) -> tuple[str, str]:
    """Process an image file using Doctr (primary) then Tesseract."""
    # Step 1: Try Doctr (handles rotation and tables better)
    try:
        print("Processing image with Doctr...")
        text_doctr = extract_image_with_doctr(file_path)
        if text_doctr and word_count(text_doctr) > 5:
            return text_doctr, 'ocr_image_doctr'
    except Exception as e:
        print(f"Doctr image OCR failed (falling back to Tesseract): {e}")

    # Step 2: Fallback to Tesseract
    try:
        from PIL import Image
        print("Falling back to Tesseract for image...")
        img = Image.open(file_path)
        # Using pytesseract with PSM 1 (Automatic page segmentation with OSD) 
        # or 3 (Fully automatic page segmentation, but no OSD)
        # OSD (Orientation and Script Detection) is crucial for rotated text. --psm 1 or --psm 0+3
        try:
             # Try to detect orientation first? Tesseract OSD script
             # simpler: just use --psm 3 for now, standard fallback
             text = pytesseract.image_to_string(img, lang='ita', config='--psm 3')
        except:
             # retry default
             text = pytesseract.image_to_string(img, lang='ita')
             
        return text, 'ocr_image_tesseract'
    except Exception as e:
        print(f"Image OCR failed completely: {e}")
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
