ALTER TABLE analyses ADD COLUMN IF NOT EXISTS input_tokens INTEGER DEFAULT 0;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS output_tokens INTEGER DEFAULT 0;
UPDATE analyses 
SET input_tokens = COALESCE(total_tokens, 0) / 2, 
    output_tokens = COALESCE(total_tokens, 0) / 2 
WHERE input_tokens = 0 AND output_tokens = 0 AND total_tokens > 0;
