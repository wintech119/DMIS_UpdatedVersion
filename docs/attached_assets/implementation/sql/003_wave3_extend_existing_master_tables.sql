-- Wave 3: Extend existing live master tables to align with v5.1

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15min';

-- 1) Tenant code uniqueness and expanded tenant types
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'tenant_tenant_code_key'
          AND conrelid = 'public.tenant'::regclass
    ) THEN
        ALTER TABLE public.tenant
            ADD CONSTRAINT tenant_tenant_code_key UNIQUE (tenant_code);
    END IF;
END $$;

ALTER TABLE public.tenant DROP CONSTRAINT IF EXISTS tenant_tenant_type_check;
ALTER TABLE public.tenant
    ADD CONSTRAINT tenant_tenant_type_check CHECK (
        tenant_type::text = ANY (
            ARRAY[
                'NATIONAL',
                'MILITARY',
                'SOCIAL_SERVICES',
                'PARISH',
                'NGO',
                'MINISTRY',
                'EXTERNAL',
                'INFRASTRUCTURE',
                'PUBLIC'
            ]::text[]
        )
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'tenant_tenant_type_fkey'
          AND conrelid = 'public.tenant'::regclass
    ) THEN
        ALTER TABLE public.tenant
            ADD CONSTRAINT tenant_tenant_type_fkey
            FOREIGN KEY (tenant_type) REFERENCES public.ref_tenant_type(tenant_type_code);
    END IF;
END $$;

-- 2) Phase domain expansion to include RECOVERY
ALTER TABLE public.event DROP CONSTRAINT IF EXISTS c_event_phase;
ALTER TABLE public.event
    ADD CONSTRAINT c_event_phase CHECK (
        current_phase::text = ANY (
            ARRAY['SURGE','STABILIZED','RECOVERY','BASELINE']::text[]
        )
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'event_current_phase_fkey'
          AND conrelid = 'public.event'::regclass
    ) THEN
        ALTER TABLE public.event
            ADD CONSTRAINT event_current_phase_fkey
            FOREIGN KEY (current_phase) REFERENCES public.ref_event_phase(phase_code);
    END IF;
END $$;

ALTER TABLE public.event_phase DROP CONSTRAINT IF EXISTS event_phase_phase_code_check;
ALTER TABLE public.event_phase
    ADD CONSTRAINT event_phase_phase_code_check CHECK (
        phase_code::text = ANY (
            ARRAY['SURGE','STABILIZED','RECOVERY','BASELINE']::text[]
        )
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'event_phase_phase_code_fkey'
          AND conrelid = 'public.event_phase'::regclass
    ) THEN
        ALTER TABLE public.event_phase
            ADD CONSTRAINT event_phase_phase_code_fkey
            FOREIGN KEY (phase_code) REFERENCES public.ref_event_phase(phase_code);
    END IF;
END $$;

ALTER TABLE public.event_phase_config DROP CONSTRAINT IF EXISTS c_phase_config_phase;
ALTER TABLE public.event_phase_config
    ADD CONSTRAINT c_phase_config_phase CHECK (
        phase::text = ANY (
            ARRAY['SURGE','STABILIZED','RECOVERY','BASELINE']::text[]
        )
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'event_phase_config_phase_fkey'
          AND conrelid = 'public.event_phase_config'::regclass
    ) THEN
        ALTER TABLE public.event_phase_config
            ADD CONSTRAINT event_phase_config_phase_fkey
            FOREIGN KEY (phase) REFERENCES public.ref_event_phase(phase_code);
    END IF;
END $$;

ALTER TABLE public.event_phase_history DROP CONSTRAINT IF EXISTS c_phase_history_from;
ALTER TABLE public.event_phase_history DROP CONSTRAINT IF EXISTS c_phase_history_to;
ALTER TABLE public.event_phase_history
    ADD CONSTRAINT c_phase_history_from CHECK (
        from_phase IS NULL OR from_phase::text = ANY (
            ARRAY['SURGE','STABILIZED','RECOVERY','BASELINE']::text[]
        )
    );
ALTER TABLE public.event_phase_history
    ADD CONSTRAINT c_phase_history_to CHECK (
        to_phase::text = ANY (
            ARRAY['SURGE','STABILIZED','RECOVERY','BASELINE']::text[]
        )
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'event_phase_history_to_fkey'
          AND conrelid = 'public.event_phase_history'::regclass
    ) THEN
        ALTER TABLE public.event_phase_history
            ADD CONSTRAINT event_phase_history_to_fkey
            FOREIGN KEY (to_phase) REFERENCES public.ref_event_phase(phase_code);
    END IF;
END $$;

-- 3) Supplier compliance fields (TRN/TCC) and optional tenant scope
ALTER TABLE public.supplier
    ADD COLUMN IF NOT EXISTS trn_no character varying(30),
    ADD COLUMN IF NOT EXISTS tcc_no character varying(30),
    ADD COLUMN IF NOT EXISTS tenant_id integer,
    ADD COLUMN IF NOT EXISTS is_global boolean DEFAULT true NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'supplier_tenant_id_fkey'
          AND conrelid = 'public.supplier'::regclass
    ) THEN
        ALTER TABLE public.supplier
            ADD CONSTRAINT supplier_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id);
    END IF;
END $$;

ALTER TABLE public.supplier DROP CONSTRAINT IF EXISTS supplier_scope_check;
ALTER TABLE public.supplier
    ADD CONSTRAINT supplier_scope_check CHECK (
        (is_global = true AND tenant_id IS NULL) OR
        (is_global = false AND tenant_id IS NOT NULL)
    );

-- 4) Horizon-B donor lead-time support
ALTER TABLE public.lead_time_config
    ADD COLUMN IF NOT EXISTS donor_id integer;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'lead_time_config_donor_id_fkey'
          AND conrelid = 'public.lead_time_config'::regclass
    ) THEN
        ALTER TABLE public.lead_time_config
            ADD CONSTRAINT lead_time_config_donor_id_fkey FOREIGN KEY (donor_id) REFERENCES public.donor(donor_id);
    END IF;
END $$;

ALTER TABLE public.lead_time_config DROP CONSTRAINT IF EXISTS c_ltc_c_supplier;
ALTER TABLE public.lead_time_config DROP CONSTRAINT IF EXISTS c_ltc_b_donor;
ALTER TABLE public.lead_time_config
    ADD CONSTRAINT c_ltc_b_donor CHECK (
        ((horizon::text = 'B'::text) AND (is_default OR donor_id IS NOT NULL)) OR
        (horizon::text <> 'B'::text)
    );
ALTER TABLE public.lead_time_config
    ADD CONSTRAINT c_ltc_c_supplier CHECK (
        ((horizon::text = 'C'::text) AND (is_default OR supplier_id IS NOT NULL)) OR
        (horizon::text <> 'C'::text)
    );

-- 5) Needs list status compatibility with canonical values
ALTER TABLE public.needs_list DROP CONSTRAINT IF EXISTS c_needs_list_status;
ALTER TABLE public.needs_list
    ADD CONSTRAINT c_needs_list_status CHECK (
        status_code::text = ANY (
            ARRAY[
                'DRAFT',
                'MODIFIED',
                'SUBMITTED',
                'PENDING_APPROVAL',
                'UNDER_REVIEW',
                'APPROVED',
                'REJECTED',
                'RETURNED',
                'IN_PROGRESS',
                'FULFILLED',
                'CANCELLED',
                'SUPERSEDED'
            ]::text[]
        )
    );

-- 6) Procurement method/status compatibility with canonical values
ALTER TABLE public.procurement DROP CONSTRAINT IF EXISTS c_proc_method;
ALTER TABLE public.procurement
    ADD CONSTRAINT c_proc_method CHECK (
        procurement_method::text = ANY (
            ARRAY[
                'EMERGENCY_DIRECT_PURCHASE',
                'FRAMEWORK_CALLOFF',
                'COMPETITIVE_QUOTATION',
                'OPEN_TENDER',
                -- legacy compatibility window
                'EMERGENCY_DIRECT',
                'SINGLE_SOURCE',
                'RFQ',
                'RESTRICTED_BIDDING',
                'FRAMEWORK'
            ]::text[]
        )
    );

ALTER TABLE public.procurement DROP CONSTRAINT IF EXISTS c_proc_status;
ALTER TABLE public.procurement
    ADD CONSTRAINT c_proc_status CHECK (
        status_code::text = ANY (
            ARRAY[
                'DRAFT',
                'PENDING_APPROVAL',
                'APPROVED',
                'REJECTED',
                'ORDERED',
                'SHIPPED',
                'IN_TRANSIT',
                'PARTIALLY_RECEIVED',
                'PARTIAL_RECEIVED',
                'RECEIVED',
                'CLOSED',
                'CANCELLED'
            ]::text[]
        )
    );

-- 7) Agency priority support for allocation engine
ALTER TABLE public.agency
    ADD COLUMN IF NOT EXISTS agency_priority integer;

ALTER TABLE public.agency DROP CONSTRAINT IF EXISTS agency_priority_check;
ALTER TABLE public.agency
    ADD CONSTRAINT agency_priority_check CHECK (agency_priority IS NULL OR agency_priority BETWEEN 1 AND 10);

COMMIT;
