-- Add phase column to event table for supply replenishment module
-- This column tracks the event phase (SURGE, STABILIZED, or BASELINE)
-- which determines demand and planning windows

-- Add the phase column if it doesn't exist
ALTER TABLE public.event
ADD COLUMN IF NOT EXISTS current_phase VARCHAR(20) DEFAULT 'BASELINE';

-- Add a check constraint to ensure valid phase values
ALTER TABLE public.event
DROP CONSTRAINT IF EXISTS event_current_phase_check;

ALTER TABLE public.event
ADD CONSTRAINT event_current_phase_check
CHECK (current_phase IN ('SURGE', 'STABILIZED', 'BASELINE'));

-- Update any existing events to have a default phase
UPDATE public.event
SET current_phase = 'STABILIZED'
WHERE current_phase IS NULL;

-- Add a comment for documentation
COMMENT ON COLUMN public.event.current_phase IS
'Event phase for supply replenishment: SURGE (6hr demand), STABILIZED (72hr demand), or BASELINE (30 day demand)';

-- Verify the change
SELECT event_id, event_name, status_code, current_phase, declaration_date
FROM public.event
ORDER BY declaration_date DESC;
