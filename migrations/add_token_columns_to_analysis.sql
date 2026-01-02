-- Migration: Add input_tokens and output_tokens columns to analyses table
-- Date: 2025-12-31
-- Description: Add separate token tracking for input and output to enable cost analytics

-- Add input_tokens column (default 0 for existing records)
ALTER TABLE analyses
ADD COLUMN IF NOT EXISTS input_tokens INTEGER DEFAULT 0;

-- Add output_tokens column (default 0 for existing records)
ALTER TABLE analyses
ADD COLUMN IF NOT EXISTS output_tokens INTEGER DEFAULT 0;

-- Update existing records: estimate input/output split from total_tokens
-- Assuming 50/50 split for existing records (conservative estimate)
UPDATE analyses
SET
    input_tokens = COALESCE(total_tokens, 0) / 2,
    output_tokens = COALESCE(total_tokens, 0) / 2
WHERE input_tokens = 0 AND output_tokens = 0 AND total_tokens > 0;

-- Verify migration
SELECT
    COUNT(*) as total_analyses,
    SUM(CASE WHEN input_tokens > 0 OR output_tokens > 0 THEN 1 ELSE 0 END) as with_token_data
FROM analyses;
