-- Align needs_list.status_code with Product Backlog v3.2 FR02.93.
-- Execution sub-stages remain in needs_list_workflow_metadata and
-- needs_list_execution_link instead of the backlog-level status column.

ALTER TABLE public.needs_list
DROP CONSTRAINT IF EXISTS c_needs_list_status;

UPDATE public.needs_list
SET status_code = CASE status_code
    WHEN 'PENDING' THEN 'SUBMITTED'
    WHEN 'PENDING_APPROVAL' THEN 'SUBMITTED'
    WHEN 'UNDER_REVIEW' THEN 'SUBMITTED'
    WHEN 'RETURNED' THEN 'MODIFIED'
    WHEN 'ESCALATED' THEN 'SUBMITTED'
    WHEN 'IN_PREPARATION' THEN 'IN_PROGRESS'
    WHEN 'DISPATCHED' THEN 'IN_PROGRESS'
    WHEN 'RECEIVED' THEN 'IN_PROGRESS'
    WHEN 'COMPLETED' THEN 'FULFILLED'
    WHEN 'CANCELLED' THEN 'REJECTED'
    ELSE status_code
END
WHERE status_code IN (
    'PENDING',
    'PENDING_APPROVAL',
    'UNDER_REVIEW',
    'RETURNED',
    'ESCALATED',
    'IN_PREPARATION',
    'DISPATCHED',
    'RECEIVED',
    'COMPLETED',
    'CANCELLED'
);

ALTER TABLE public.needs_list
ADD CONSTRAINT c_needs_list_status CHECK (
    status_code IN (
        'DRAFT',
        'MODIFIED',
        'SUBMITTED',
        'APPROVED',
        'REJECTED',
        'IN_PROGRESS',
        'FULFILLED',
        'SUPERSEDED'
    )
);
