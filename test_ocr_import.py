#!/usr/bin/env python
"""Test script to verify OCR imports work correctly"""

try:
    from app.ocr import append_debug_log, process_document
    print("OK - Import successful!")

    # Test append_debug_log
    append_debug_log("Test message - datetime import works!")
    print("OK - append_debug_log works!")

    print("OK - All imports and functions working correctly")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
