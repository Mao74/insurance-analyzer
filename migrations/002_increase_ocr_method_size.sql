-- Migration: Increase ocr_method column size
-- Date: 2026-01-04
-- Reason: Fix VARCHAR(20) truncation issue for values like "processing_page_X_of_Y"

-- Increase column size from 20 to 100 characters
ALTER TABLE documents ALTER COLUMN ocr_method TYPE VARCHAR(100);

-- Verify change
SELECT column_name, data_type, character_maximum_length 
FROM information_schema.columns 
WHERE table_name = 'documents' AND column_name = 'ocr_method';
