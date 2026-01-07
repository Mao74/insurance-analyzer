# Worker function for parallel OCR - insert before process_pdf()

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


def process_pdf_sequential(file_path: str, page_data: list, pages_needing_ocr: set, num_pages: int) -> str:
    """
    Sequential OCR processing (original implementation).
    This is a fallback when parallel is not safe/beneficial.
    """
    print(f"📄 SEQUENTIAL OCR: {num_pages} pages, {len(pages_needing_ocr)} need OCR")
    combined_text = []
    
    try:
        with fitz.open(file_path) as doc:
            for page_num, (wc, native_text, rotation, quality_good) in enumerate(page_data):
                # Use native text if page doesn't need OCR
                if page_num not in pages_needing_ocr:
                    combined_text.append(native_text)
                    continue
                
                # Page needs OCR - existing hybrid logic
                page = doc[page_num]
                
                # Try embedded images first
                ocr_text = extract_images_from_page_ocr(page, page_num)
                
                if word_count(ocr_text) > wc and is_text_quality_good(ocr_text):
                    combined_text.append(ocr_text)
                    print(f"  Page {page_num + 1}: Embedded image OCR extracted {word_count(ocr_text)} words")
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
                    
                    full_page_ocr = pytesseract.image_to_string(img, lang='ita')
                    
                    if word_count(full_page_ocr) > wc or is_text_quality_good(full_page_ocr):
                        combined_text.append(full_page_ocr)
                        print(f"  Page {page_num + 1}: Full-page OCR extracted {word_count(full_page_ocr)} words")
                    else:
                        combined_text.append(native_text)
                        print(f"  Page {page_num + 1}: Kept native text ({wc} words) - OCR didn't improve")
        
        return "\n".join(combined_text)
        
    except Exception as e:
        print(f"Error in sequential processing: {e}")
        text_tess = extract_with_tesseract(file_path)
        return text_tess
