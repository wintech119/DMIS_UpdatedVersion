--
-- PostgreSQL database dump
--

\restrict yygVar3AOxMLUhsEWJXVXixcm0OI8hDdIwITbt25DPlYZlJ5BD6ko6bCYUfbKXL

-- Dumped from database version 18.2
-- Dumped by pg_dump version 18.2

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: citext; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;


--
-- Name: EXTENSION citext; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION citext IS 'data type for case-insensitive character strings';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: log_event_phase_change(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.log_event_phase_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.current_phase IS DISTINCT FROM NEW.current_phase THEN
        INSERT INTO public.event_phase_history (
            event_id, from_phase, to_phase, changed_at, changed_by
        ) VALUES (
            NEW.event_id, OLD.current_phase, NEW.current_phase,
            COALESCE(NEW.phase_changed_at, NOW()),
            COALESCE(NEW.phase_changed_by, NEW.update_by_id)
        );
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.update_dtime := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


--
-- Name: update_warehouse_sync_status(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_warehouse_sync_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.last_sync_dtime IS NULL THEN
        NEW.sync_status := 'UNKNOWN';
    ELSIF NEW.last_sync_dtime > NOW() - INTERVAL '2 hours' THEN
        NEW.sync_status := 'ONLINE';
    ELSIF NEW.last_sync_dtime > NOW() - INTERVAL '6 hours' THEN
        NEW.sync_status := 'STALE';
    ELSE
        NEW.sync_status := 'OFFLINE';
    END IF;
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agency; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agency (
    agency_id integer NOT NULL,
    agency_name character varying(120) NOT NULL,
    address1_text character varying(255) NOT NULL,
    address2_text character varying(255),
    parish_code character(2) NOT NULL,
    contact_name character varying(50) NOT NULL,
    phone_no character varying(20) NOT NULL,
    email_text character varying(100),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    agency_type character varying(16) NOT NULL,
    ineligible_event_id integer,
    status_code character(1) NOT NULL,
    warehouse_id integer,
    CONSTRAINT agency_agency_name_check CHECK (((agency_name)::text = upper((agency_name)::text))),
    CONSTRAINT agency_contact_name_check CHECK (((contact_name)::text = upper((contact_name)::text))),
    CONSTRAINT c_agency_3 CHECK (((agency_type)::text = ANY (ARRAY[('DISTRIBUTOR'::character varying)::text, ('SHELTER'::character varying)::text]))),
    CONSTRAINT c_agency_5 CHECK (((((agency_type)::text = 'SHELTER'::text) AND (warehouse_id IS NULL)) OR (((agency_type)::text <> 'SHELTER'::text) AND (warehouse_id IS NOT NULL)))),
    CONSTRAINT c_agency_6 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar])))
);


--
-- Name: agency_account_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agency_account_request (
    request_id integer NOT NULL,
    agency_name character varying(120) NOT NULL,
    contact_name character varying(80) NOT NULL,
    contact_phone character varying(20) NOT NULL,
    contact_email public.citext NOT NULL,
    reason_text character varying(255) NOT NULL,
    agency_id integer,
    user_id integer,
    status_code character(1) NOT NULL,
    status_reason character varying(255),
    created_by_id integer NOT NULL,
    created_at timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by_id integer NOT NULL,
    updated_at timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_aar_status CHECK ((status_code = ANY (ARRAY['S'::bpchar, 'R'::bpchar, 'A'::bpchar, 'D'::bpchar])))
);


--
-- Name: agency_account_request_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agency_account_request_audit (
    audit_id integer NOT NULL,
    request_id integer NOT NULL,
    event_type character varying(24) NOT NULL,
    event_notes character varying(255),
    actor_user_id integer NOT NULL,
    event_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL
);


--
-- Name: agency_account_request_audit_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.agency_account_request_audit ALTER COLUMN audit_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.agency_account_request_audit_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: agency_account_request_request_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.agency_account_request ALTER COLUMN request_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.agency_account_request_request_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: agency_agency_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.agency ALTER COLUMN agency_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.agency_agency_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(150) NOT NULL
);


--
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group_permissions (
    id bigint NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


--
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_permission ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user (
    id integer NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    username character varying(150) NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL
);


--
-- Name: auth_user_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user_groups (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    group_id integer NOT NULL
);


--
-- Name: auth_user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user_groups ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user_user_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user_user_permissions (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_user_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user_user_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_user_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: batchlocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.batchlocation (
    inventory_id integer NOT NULL,
    location_id integer NOT NULL,
    batch_id integer NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL
);


--
-- Name: burn_rate_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.burn_rate_snapshot (
    snapshot_id integer NOT NULL,
    warehouse_id integer NOT NULL,
    item_id integer NOT NULL,
    event_id integer NOT NULL,
    event_phase character varying(15) NOT NULL,
    snapshot_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    demand_window_hours integer NOT NULL,
    fulfillment_count integer DEFAULT 0 NOT NULL,
    total_fulfilled_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    burn_rate numeric(10,4) NOT NULL,
    burn_rate_source character varying(20) NOT NULL,
    data_freshness_level character varying(10) NOT NULL,
    time_to_stockout_hours numeric(10,2),
    available_stock_at_calc numeric(15,2) NOT NULL,
    CONSTRAINT c_brs_freshness CHECK (((data_freshness_level)::text = ANY (ARRAY[('HIGH'::character varying)::text, ('MEDIUM'::character varying)::text, ('LOW'::character varying)::text]))),
    CONSTRAINT c_brs_phase CHECK (((event_phase)::text = ANY (ARRAY[('SURGE'::character varying)::text, ('STABILIZED'::character varying)::text, ('BASELINE'::character varying)::text]))),
    CONSTRAINT c_brs_source CHECK (((burn_rate_source)::text = ANY (ARRAY[('CALCULATED'::character varying)::text, ('BASELINE'::character varying)::text, ('ESTIMATED'::character varying)::text])))
);


--
-- Name: TABLE burn_rate_snapshot; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.burn_rate_snapshot IS 'Historical record of burn rate calculations for trending and analysis';


--
-- Name: burn_rate_snapshot_snapshot_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.burn_rate_snapshot ALTER COLUMN snapshot_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.burn_rate_snapshot_snapshot_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: country; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.country (
    country_id smallint NOT NULL,
    country_name public.citext NOT NULL,
    currency_code character varying(10) NOT NULL,
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT c_country_1 CHECK ((length((country_name)::text) <= 120)),
    CONSTRAINT c_country_2 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar])))
);


--
-- Name: currency; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.currency (
    currency_code character varying(10) NOT NULL,
    currency_name public.citext NOT NULL,
    currency_sign character varying(6) NOT NULL,
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT c_currency_1 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar]))),
    CONSTRAINT c_currency_1a CHECK ((length((currency_name)::text) <= 130))
);


--
-- Name: currency_rate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.currency_rate (
    currency_code character varying(3) NOT NULL,
    rate_to_jmd numeric(18,8) NOT NULL,
    source character varying(50) DEFAULT 'UNCONFIGURED'::character varying NOT NULL,
    rate_date date NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT c_currency_rate_code_upper CHECK (((currency_code)::text = upper((currency_code)::text))),
    CONSTRAINT c_currency_rate_positive CHECK ((rate_to_jmd > (0)::numeric))
);


--
-- Name: TABLE currency_rate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.currency_rate IS 'Cached exchange rates to JMD from Frankfurter.app (ECB-backed). Used for display-only currency conversion.';


--
-- Name: COLUMN currency_rate.currency_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.currency_rate.currency_code IS 'ISO 4217 currency code (uppercase), e.g., USD, EUR, GBP';


--
-- Name: COLUMN currency_rate.rate_to_jmd; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.currency_rate.rate_to_jmd IS 'Exchange rate: how many JMD for 1 unit of the currency';


--
-- Name: COLUMN currency_rate.source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.currency_rate.source IS 'Rate source identifier, default is FRANKFURTER_ECB';


--
-- Name: COLUMN currency_rate.rate_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.currency_rate.rate_date IS 'The date the rate applies to';


--
-- Name: COLUMN currency_rate.create_dtime; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.currency_rate.create_dtime IS 'Timestamp when the rate was cached';


--
-- Name: custodian; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.custodian (
    custodian_id integer NOT NULL,
    custodian_name character varying(120) DEFAULT 'OFFICE OF DISASTER PREPAREDNESS AND EMERGENCY MANAGEMENT (ODPEM)'::character varying NOT NULL,
    address1_text character varying(255) NOT NULL,
    address2_text character varying(255),
    parish_code character(2) NOT NULL,
    contact_name character varying(50) NOT NULL,
    phone_no character varying(20) NOT NULL,
    email_text character varying(100),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    tenant_id integer,
    CONSTRAINT c_custodian_1 CHECK (((custodian_name)::text = upper((custodian_name)::text))),
    CONSTRAINT c_custodian_3 CHECK (((contact_name)::text = upper((contact_name)::text)))
);


--
-- Name: COLUMN custodian.tenant_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.custodian.tenant_id IS 'FK to tenant for multi-tenancy migration. Custodian records will be migrated to tenant table.';


--
-- Name: custodian_custodian_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.custodian ALTER COLUMN custodian_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.custodian_custodian_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: data_sharing_agreement; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_sharing_agreement (
    agreement_id integer NOT NULL,
    from_tenant_id integer NOT NULL,
    to_tenant_id integer NOT NULL,
    data_category character varying(50) NOT NULL,
    permission_level character varying(20) DEFAULT 'READ'::character varying,
    effective_date date DEFAULT CURRENT_DATE NOT NULL,
    expiry_date date,
    agreement_notes text,
    status_code character(1) DEFAULT 'A'::bpchar NOT NULL,
    approved_by integer,
    approved_at timestamp(0) without time zone,
    create_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT data_sharing_agreement_data_category_check CHECK (((data_category)::text = ANY ((ARRAY['INVENTORY'::character varying, 'RELIEF_REQUESTS'::character varying, 'ALLOCATIONS'::character varying, 'BENEFICIARY'::character varying, 'DONATIONS'::character varying, 'FINANCIAL'::character varying, '3W_REPORTS'::character varying, 'DASHBOARD'::character varying])::text[]))),
    CONSTRAINT data_sharing_agreement_permission_level_check CHECK (((permission_level)::text = ANY ((ARRAY['READ'::character varying, 'CONTRIBUTE'::character varying, 'FULL'::character varying])::text[]))),
    CONSTRAINT data_sharing_agreement_status_code_check CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar, 'E'::bpchar])))
);


--
-- Name: TABLE data_sharing_agreement; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.data_sharing_agreement IS 'Cross-tenant data sharing permissions for multi-agency coordination';


--
-- Name: data_sharing_agreement_agreement_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_sharing_agreement_agreement_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_sharing_agreement_agreement_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_sharing_agreement_agreement_id_seq OWNED BY public.data_sharing_agreement.agreement_id;


--
-- Name: dbintake; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbintake (
    reliefpkg_id integer NOT NULL,
    inventory_id integer NOT NULL,
    intake_date date NOT NULL,
    comments_text character varying(255),
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone,
    verify_by_id character varying(20) NOT NULL,
    verify_dtime timestamp(0) without time zone,
    version_nbr integer NOT NULL,
    CONSTRAINT dbintake_intake_date_check CHECK ((intake_date <= CURRENT_DATE)),
    CONSTRAINT dbintake_status_code_check CHECK ((status_code = ANY (ARRAY['I'::bpchar, 'C'::bpchar, 'V'::bpchar])))
);


--
-- Name: dbintake_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dbintake_item (
    reliefpkg_id integer NOT NULL,
    inventory_id integer NOT NULL,
    item_id integer NOT NULL,
    usable_qty numeric(12,2) NOT NULL,
    location1_id integer,
    defective_qty numeric(12,2) NOT NULL,
    location2_id integer,
    expired_qty numeric(12,2) NOT NULL,
    location3_id integer,
    uom_code character varying(25) NOT NULL,
    status_code character(1) NOT NULL,
    comments_text character varying(255),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT dbintake_item_defective_qty_check CHECK ((defective_qty >= 0.00)),
    CONSTRAINT dbintake_item_expired_qty_check CHECK ((expired_qty >= 0.00)),
    CONSTRAINT dbintake_item_status_code_check CHECK ((status_code = ANY (ARRAY['P'::bpchar, 'V'::bpchar]))),
    CONSTRAINT dbintake_item_usable_qty_check CHECK ((usable_qty >= 0.00))
);


--
-- Name: distribution_package; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.distribution_package (
    id integer NOT NULL,
    package_number character varying(64) NOT NULL,
    recipient_agency_id integer NOT NULL,
    assigned_warehouse_id integer,
    event_id integer,
    status character varying(50) DEFAULT 'Draft'::character varying NOT NULL,
    is_partial boolean DEFAULT false NOT NULL,
    created_by character varying(200) NOT NULL,
    approved_by character varying(200),
    approved_at timestamp without time zone,
    dispatched_by character varying(200),
    dispatched_at timestamp without time zone,
    delivered_at timestamp without time zone,
    notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: distribution_package_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.distribution_package_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: distribution_package_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.distribution_package_id_seq OWNED BY public.distribution_package.id;


--
-- Name: distribution_package_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.distribution_package_item (
    id integer NOT NULL,
    package_id integer NOT NULL,
    item_id integer NOT NULL,
    quantity numeric(12,2) NOT NULL,
    notes text
);


--
-- Name: distribution_package_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.distribution_package_item_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: distribution_package_item_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.distribution_package_item_id_seq OWNED BY public.distribution_package_item.id;


--
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


--
-- Name: dnintake; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dnintake (
    donation_id integer NOT NULL,
    inventory_id integer NOT NULL,
    intake_date date NOT NULL,
    comments_text character varying(255),
    status_code character(1) DEFAULT 'I'::bpchar NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone,
    verify_by_id character varying(20) NOT NULL,
    verify_dtime timestamp(0) without time zone,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_dnintake_1 CHECK ((intake_date <= CURRENT_DATE)),
    CONSTRAINT c_dnintake_2 CHECK ((status_code = ANY (ARRAY['I'::bpchar, 'C'::bpchar, 'V'::bpchar])))
);


--
-- Name: TABLE dnintake; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.dnintake IS 'Donation intake records - tracks when donations are received at warehouses';


--
-- Name: COLUMN dnintake.donation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake.donation_id IS 'FK to donation being received';


--
-- Name: COLUMN dnintake.inventory_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake.inventory_id IS 'FK to warehouse where donation is received (warehouse_id)';


--
-- Name: COLUMN dnintake.intake_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake.intake_date IS 'Date donation was received at warehouse';


--
-- Name: COLUMN dnintake.comments_text; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake.comments_text IS 'Optional comments about the intake';


--
-- Name: COLUMN dnintake.status_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake.status_code IS 'I=Incomplete, C=Completed, V=Verified';


--
-- Name: dnintake_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dnintake_item (
    donation_id integer NOT NULL,
    inventory_id integer NOT NULL,
    item_id integer NOT NULL,
    batch_no character varying(20) NOT NULL,
    batch_date date,
    expiry_date date,
    uom_code character varying(25) NOT NULL,
    avg_unit_value numeric(10,2) NOT NULL,
    usable_qty numeric(12,2) DEFAULT 0.00 NOT NULL,
    defective_qty numeric(12,2) DEFAULT 0.00 NOT NULL,
    expired_qty numeric(12,2) DEFAULT 0.00 NOT NULL,
    ext_item_cost numeric(12,2) DEFAULT 0.00 NOT NULL,
    status_code character(1) DEFAULT 'P'::bpchar NOT NULL,
    comments_text character varying(255),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_dnintake_item_1a CHECK (((batch_no)::text = upper((batch_no)::text))),
    CONSTRAINT c_dnintake_item_1b CHECK ((batch_date <= CURRENT_DATE)),
    CONSTRAINT c_dnintake_item_1c CHECK ((expiry_date >= batch_date)),
    CONSTRAINT c_dnintake_item_1d CHECK ((avg_unit_value > 0.00)),
    CONSTRAINT c_dnintake_item_1e CHECK ((ext_item_cost = (((COALESCE(usable_qty, (0)::numeric) + COALESCE(defective_qty, (0)::numeric)) + COALESCE(expired_qty, (0)::numeric)) * avg_unit_value))),
    CONSTRAINT c_dnintake_item_2 CHECK ((usable_qty >= 0.00)),
    CONSTRAINT c_dnintake_item_3 CHECK ((defective_qty >= 0.00)),
    CONSTRAINT c_dnintake_item_4 CHECK ((expired_qty >= 0.00)),
    CONSTRAINT c_dnintake_item_5 CHECK ((status_code = ANY (ARRAY['P'::bpchar, 'V'::bpchar])))
);


--
-- Name: TABLE dnintake_item; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.dnintake_item IS 'Donation intake items - batch-level tracking of items received in donation intakes';


--
-- Name: COLUMN dnintake_item.donation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.donation_id IS 'FK to donation via dnintake';


--
-- Name: COLUMN dnintake_item.inventory_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.inventory_id IS 'FK to warehouse via dnintake';


--
-- Name: COLUMN dnintake_item.item_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.item_id IS 'FK to item via donation_item';


--
-- Name: COLUMN dnintake_item.batch_no; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.batch_no IS 'Manufacturer batch number or item code if none exists';


--
-- Name: COLUMN dnintake_item.batch_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.batch_date IS 'Manufacturing/batch date';


--
-- Name: COLUMN dnintake_item.expiry_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.expiry_date IS 'Expiry date (must be >= batch_date)';


--
-- Name: COLUMN dnintake_item.uom_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.uom_code IS 'Unit of measure for quantities';


--
-- Name: COLUMN dnintake_item.avg_unit_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.avg_unit_value IS 'Average value per unit (must be > 0)';


--
-- Name: COLUMN dnintake_item.usable_qty; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.usable_qty IS 'Quantity of usable/good items';


--
-- Name: COLUMN dnintake_item.defective_qty; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.defective_qty IS 'Quantity of defective items';


--
-- Name: COLUMN dnintake_item.expired_qty; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.expired_qty IS 'Quantity of expired items';


--
-- Name: COLUMN dnintake_item.ext_item_cost; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.ext_item_cost IS 'Extended cost: (usable + defective + expired) * avg_unit_value';


--
-- Name: COLUMN dnintake_item.status_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.dnintake_item.status_code IS 'P=Pending verification, V=Verified';


--
-- Name: donation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.donation (
    donation_id integer NOT NULL,
    donor_id integer NOT NULL,
    donation_desc text NOT NULL,
    origin_country_id smallint NOT NULL,
    origin_address1_text character varying(255),
    origin_address2_text character varying(255),
    event_id integer NOT NULL,
    custodian_id integer NOT NULL,
    received_date date NOT NULL,
    tot_item_cost numeric(12,2) NOT NULL,
    storage_cost numeric(12,2) NOT NULL,
    haulage_cost numeric(12,2) NOT NULL,
    other_cost numeric(12,2) NOT NULL,
    other_cost_desc character varying(255),
    status_code character(1) DEFAULT 'E'::bpchar NOT NULL,
    comments_text text,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    verify_by_id character varying(20),
    verify_dtime timestamp(0) without time zone,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_donation_1 CHECK ((received_date <= CURRENT_DATE)),
    CONSTRAINT c_donation_2 CHECK ((tot_item_cost >= 0.00)),
    CONSTRAINT c_donation_2a CHECK ((storage_cost >= 0.00)),
    CONSTRAINT c_donation_2b CHECK ((haulage_cost >= 0.00)),
    CONSTRAINT c_donation_2c CHECK ((other_cost >= 0.00)),
    CONSTRAINT c_donation_3 CHECK ((status_code = ANY (ARRAY['E'::bpchar, 'V'::bpchar, 'P'::bpchar])))
);


--
-- Name: TABLE donation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.donation IS 'Donations received from donors for disaster relief';


--
-- Name: COLUMN donation.donation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.donation_id IS 'Primary key - auto-generated identity';


--
-- Name: COLUMN donation.donor_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.donor_id IS 'FK to donor who made the donation';


--
-- Name: COLUMN donation.donation_desc; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.donation_desc IS 'Description of the donation';


--
-- Name: COLUMN donation.origin_country_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.origin_country_id IS 'Country of origin for the donation';


--
-- Name: COLUMN donation.event_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.event_id IS 'Event this donation is associated with (ADHOC for general)';


--
-- Name: COLUMN donation.custodian_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.custodian_id IS 'Agency that collected/holds the donation';


--
-- Name: COLUMN donation.received_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.received_date IS 'Date donation was received';


--
-- Name: COLUMN donation.tot_item_cost; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.tot_item_cost IS 'Total value of all items/funds donated';


--
-- Name: COLUMN donation.storage_cost; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.storage_cost IS 'Warehousing/storage costs';


--
-- Name: COLUMN donation.haulage_cost; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.haulage_cost IS 'Transportation/shipping costs';


--
-- Name: COLUMN donation.other_cost; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.other_cost IS 'Miscellaneous other costs';


--
-- Name: COLUMN donation.other_cost_desc; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.other_cost_desc IS 'Description of other costs';


--
-- Name: COLUMN donation.status_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation.status_code IS 'E=Entered, V=Verified, P=Processed';


--
-- Name: donation_doc; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.donation_doc (
    document_id integer NOT NULL,
    donation_id integer NOT NULL,
    document_type character varying(40) NOT NULL,
    document_desc character varying(255) NOT NULL,
    file_name character varying(80) NOT NULL,
    file_type character varying(30) NOT NULL,
    file_size character varying(20),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT c_donation_doc_1 CHECK (((file_type)::text = ANY (ARRAY[('application/pdf'::character varying)::text, ('image/jpeg'::character varying)::text])))
);


--
-- Name: TABLE donation_doc; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.donation_doc IS 'Document attachments for donations (receipts, manifests, delivery notices)';


--
-- Name: COLUMN donation_doc.document_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation_doc.document_id IS 'Primary key - auto-generated document identifier';


--
-- Name: COLUMN donation_doc.donation_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation_doc.donation_id IS 'Foreign key to donation table';


--
-- Name: COLUMN donation_doc.document_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation_doc.document_type IS 'Type of document (Receipt, Manifest, Bill of materials, Delivery notice, etc.)';


--
-- Name: COLUMN donation_doc.document_desc; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation_doc.document_desc IS 'Description of document purpose and content';


--
-- Name: COLUMN donation_doc.file_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation_doc.file_name IS 'Original name of the uploaded file';


--
-- Name: COLUMN donation_doc.file_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation_doc.file_type IS 'MIME type of file (application/pdf or image/jpeg)';


--
-- Name: COLUMN donation_doc.file_size; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation_doc.file_size IS 'Size of file in MB';


--
-- Name: COLUMN donation_doc.version_nbr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.donation_doc.version_nbr IS 'Optimistic locking version number';


--
-- Name: donation_doc_document_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.donation_doc ALTER COLUMN document_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.donation_doc_document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: donation_donation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.donation ALTER COLUMN donation_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.donation_donation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: donation_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.donation_item (
    donation_id integer NOT NULL,
    item_id integer NOT NULL,
    donation_type character(5) NOT NULL,
    item_qty numeric(9,2) NOT NULL,
    item_cost numeric(10,2) NOT NULL,
    uom_code character varying(25),
    currency_code character varying(10),
    location_name text NOT NULL,
    status_code character(1) DEFAULT 'V'::bpchar NOT NULL,
    comments_text text,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    verify_by_id character varying(20),
    verify_dtime timestamp(0) without time zone,
    version_nbr integer NOT NULL,
    CONSTRAINT c_donation_item_0 CHECK ((donation_type = ANY (ARRAY['GOODS'::bpchar, 'FUNDS'::bpchar]))),
    CONSTRAINT c_donation_item_1a CHECK ((item_qty >= 0.00)),
    CONSTRAINT c_donation_item_1b CHECK ((item_cost >= 0.00)),
    CONSTRAINT c_donation_item_2 CHECK ((status_code = ANY (ARRAY['P'::bpchar, 'V'::bpchar]))),
    CONSTRAINT c_donation_item_type_fields CHECK ((((donation_type = 'GOODS'::bpchar) AND (uom_code IS NOT NULL) AND (currency_code IS NULL)) OR ((donation_type = 'FUNDS'::bpchar) AND (currency_code IS NOT NULL) AND (uom_code IS NULL))))
);


--
-- Name: donor; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.donor (
    donor_id integer NOT NULL,
    donor_name character varying(255) NOT NULL,
    org_type_desc character varying(30),
    address1_text character varying(255) NOT NULL,
    address2_text character varying(255),
    country_id smallint DEFAULT 388 NOT NULL,
    phone_no character varying(20) NOT NULL,
    email_text character varying(100),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    donor_code character varying(16) NOT NULL,
    CONSTRAINT c_donor_1 CHECK (((donor_code)::text = upper((donor_code)::text))),
    CONSTRAINT c_donor_2 CHECK (((donor_name)::text = upper((donor_name)::text))),
    CONSTRAINT donor_donor_name_check CHECK (((donor_name)::text = upper((donor_name)::text)))
);


--
-- Name: donor_donor_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.donor ALTER COLUMN donor_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.donor_donor_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event (
    event_id integer NOT NULL,
    event_type character varying(16) NOT NULL,
    start_date date NOT NULL,
    event_name character varying(60) NOT NULL,
    event_desc character varying(255) NOT NULL,
    impact_desc text NOT NULL,
    status_code character(1) NOT NULL,
    closed_date date,
    reason_desc character varying(255),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    current_phase character varying(15) DEFAULT 'BASELINE'::character varying NOT NULL,
    phase_changed_at timestamp(0) without time zone,
    phase_changed_by character varying(20),
    CONSTRAINT c_event_1 CHECK (((event_type)::text = ANY (ARRAY[('STORM'::character varying)::text, ('HURRICANE'::character varying)::text, ('TORNADO'::character varying)::text, ('FLOOD'::character varying)::text, ('TSUNAMI'::character varying)::text, ('FIRE'::character varying)::text, ('EARTHQUAKE'::character varying)::text, ('WAR'::character varying)::text, ('EPIDEMIC'::character varying)::text, ('ADHOC'::character varying)::text]))),
    CONSTRAINT c_event_2 CHECK ((start_date <= CURRENT_DATE)),
    CONSTRAINT c_event_3 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'C'::bpchar]))),
    CONSTRAINT c_event_4a CHECK ((((status_code = 'A'::bpchar) AND (closed_date IS NULL)) OR ((status_code = 'C'::bpchar) AND (closed_date IS NOT NULL)))),
    CONSTRAINT c_event_4b CHECK ((((reason_desc IS NULL) AND (closed_date IS NULL)) OR ((reason_desc IS NOT NULL) AND (closed_date IS NOT NULL)))),
    CONSTRAINT c_event_phase CHECK (((current_phase)::text = ANY (ARRAY[('SURGE'::character varying)::text, ('STABILIZED'::character varying)::text, ('BASELINE'::character varying)::text])))
);


--
-- Name: COLUMN event.current_phase; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event.current_phase IS 'Current operational phase: SURGE (0-72h), STABILIZED (post-surge), BASELINE (normal)';


--
-- Name: COLUMN event.phase_changed_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event.phase_changed_at IS 'Timestamp when phase was last changed';


--
-- Name: COLUMN event.phase_changed_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event.phase_changed_by IS 'User who changed the phase';


--
-- Name: event_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.event ALTER COLUMN event_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.event_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: event_phase; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_phase (
    phase_id integer NOT NULL,
    event_id integer NOT NULL,
    phase_code character varying(20) NOT NULL,
    demand_window_hours integer NOT NULL,
    planning_window_hours integer NOT NULL,
    buffer_multiplier numeric(3,2) DEFAULT 1.25,
    auto_transition_hours integer,
    started_at timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    started_by integer,
    ended_at timestamp(0) without time zone,
    ended_by integer,
    transition_reason text,
    is_current boolean DEFAULT true,
    create_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT event_phase_phase_code_check CHECK (((phase_code)::text = ANY ((ARRAY['SURGE'::character varying, 'STABILIZED'::character varying, 'BASELINE'::character varying])::text[])))
);


--
-- Name: TABLE event_phase; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.event_phase IS 'Event phase tracking for Supply Replenishment burn rate calculations';


--
-- Name: COLUMN event_phase.phase_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event_phase.phase_code IS 'SURGE (0-72h), STABILIZED (72h-7d), BASELINE (ongoing)';


--
-- Name: COLUMN event_phase.demand_window_hours; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event_phase.demand_window_hours IS 'Lookback window for burn rate calculation';


--
-- Name: COLUMN event_phase.planning_window_hours; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event_phase.planning_window_hours IS 'Forward planning horizon';


--
-- Name: event_phase_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_phase_config (
    config_id integer NOT NULL,
    event_id integer NOT NULL,
    phase character varying(15) NOT NULL,
    demand_window_hours integer NOT NULL,
    planning_window_hours integer NOT NULL,
    safety_buffer_pct numeric(5,2) DEFAULT 25.00 NOT NULL,
    safety_factor numeric(4,2) DEFAULT 1.25 NOT NULL,
    freshness_threshold_hours integer DEFAULT 2 NOT NULL,
    stale_threshold_hours integer DEFAULT 6 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_phase_config_demand CHECK ((demand_window_hours > 0)),
    CONSTRAINT c_phase_config_phase CHECK (((phase)::text = ANY (ARRAY[('SURGE'::character varying)::text, ('STABILIZED'::character varying)::text, ('BASELINE'::character varying)::text]))),
    CONSTRAINT c_phase_config_planning CHECK ((planning_window_hours > 0)),
    CONSTRAINT c_phase_config_safety_buffer CHECK (((safety_buffer_pct >= (0)::numeric) AND (safety_buffer_pct <= (100)::numeric))),
    CONSTRAINT c_phase_config_safety_factor CHECK ((safety_factor >= 1.00))
);


--
-- Name: TABLE event_phase_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.event_phase_config IS 'Phase-specific configuration parameters for each disaster event';


--
-- Name: COLUMN event_phase_config.demand_window_hours; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event_phase_config.demand_window_hours IS 'Lookback period for burn rate calculation (SURGE=6, STABILIZED=72, BASELINE=720)';


--
-- Name: COLUMN event_phase_config.planning_window_hours; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event_phase_config.planning_window_hours IS 'Time horizon for stock requirements (SURGE=72, STABILIZED=168, BASELINE=720)';


--
-- Name: COLUMN event_phase_config.safety_buffer_pct; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.event_phase_config.safety_buffer_pct IS 'Percentage buffer added to lead time trigger (SURGE=50, STABILIZED=25, BASELINE=10)';


--
-- Name: event_phase_config_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.event_phase_config ALTER COLUMN config_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.event_phase_config_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: event_phase_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_phase_history (
    history_id integer NOT NULL,
    event_id integer NOT NULL,
    from_phase character varying(15),
    to_phase character varying(15) NOT NULL,
    changed_at timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    changed_by character varying(20) NOT NULL,
    reason_text character varying(255),
    CONSTRAINT c_phase_history_from CHECK (((from_phase IS NULL) OR ((from_phase)::text = ANY (ARRAY[('SURGE'::character varying)::text, ('STABILIZED'::character varying)::text, ('BASELINE'::character varying)::text])))),
    CONSTRAINT c_phase_history_to CHECK (((to_phase)::text = ANY (ARRAY[('SURGE'::character varying)::text, ('STABILIZED'::character varying)::text, ('BASELINE'::character varying)::text])))
);


--
-- Name: TABLE event_phase_history; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.event_phase_history IS 'Audit trail of event phase transitions';


--
-- Name: event_phase_history_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.event_phase_history ALTER COLUMN history_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.event_phase_history_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: event_phase_phase_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.event_phase_phase_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: event_phase_phase_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.event_phase_phase_id_seq OWNED BY public.event_phase.phase_id;


--
-- Name: hadr_aid_movement_staging; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hadr_aid_movement_staging (
    staging_id integer NOT NULL,
    category_code character varying(30) NOT NULL,
    item_desc text NOT NULL,
    unit_label character varying(25),
    warehouse_code character varying(10) NOT NULL,
    movement_date date NOT NULL,
    movement_type character(1) NOT NULL,
    qty numeric(12,2) NOT NULL,
    unit_cost_usd numeric(12,2),
    total_cost_usd numeric(14,2),
    source_sheet character varying(64),
    source_row_nbr integer,
    source_col_idx integer,
    comments_text text,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT c_hadr_move_type CHECK ((movement_type = ANY (ARRAY['R'::bpchar, 'I'::bpchar])))
);


--
-- Name: hadr_aid_movement_staging_staging_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.hadr_aid_movement_staging ALTER COLUMN staging_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.hadr_aid_movement_staging_staging_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: inventory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory (
    inventory_id integer NOT NULL,
    item_id integer NOT NULL,
    usable_qty numeric(12,2) NOT NULL,
    reserved_qty numeric(12,2) NOT NULL,
    defective_qty numeric(12,2) NOT NULL,
    expired_qty numeric(12,2) NOT NULL,
    uom_code character varying(25) NOT NULL,
    last_verified_by character varying(20),
    last_verified_date date,
    status_code character(1) NOT NULL,
    comments_text text,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    reorder_qty numeric(12,2) DEFAULT 0.00 NOT NULL,
    CONSTRAINT c_inventory_1 CHECK ((usable_qty >= 0.00)),
    CONSTRAINT c_inventory_2 CHECK ((reserved_qty <= usable_qty)),
    CONSTRAINT c_inventory_3 CHECK ((defective_qty >= 0.00)),
    CONSTRAINT c_inventory_4 CHECK ((expired_qty >= 0.00)),
    CONSTRAINT c_inventory_5 CHECK ((reorder_qty >= 0.00)),
    CONSTRAINT c_inventory_6 CHECK ((((last_verified_by IS NULL) AND (last_verified_date IS NULL)) OR ((last_verified_by IS NOT NULL) AND (last_verified_date IS NOT NULL)))),
    CONSTRAINT c_inventory_7 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'U'::bpchar])))
);


--
-- Name: item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item (
    item_id integer NOT NULL,
    item_code character varying(16) NOT NULL,
    item_name character varying(60) NOT NULL,
    sku_code character varying(30) NOT NULL,
    category_id integer NOT NULL,
    item_desc public.citext NOT NULL,
    reorder_qty numeric(12,2) NOT NULL,
    default_uom_code character varying(25) NOT NULL,
    units_size_vary_flag boolean DEFAULT false NOT NULL,
    usage_desc text,
    storage_desc text,
    is_batched_flag boolean DEFAULT true NOT NULL,
    can_expire_flag boolean DEFAULT false NOT NULL,
    issuance_order character varying(20) DEFAULT 'FIFO'::character varying NOT NULL,
    comments_text text,
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    baseline_burn_rate numeric(10,4) DEFAULT 0.0000,
    min_stock_threshold numeric(12,2) DEFAULT 0.00,
    criticality_level character varying(10) DEFAULT 'NORMAL'::character varying,
    CONSTRAINT c_item_1a CHECK (((item_code)::text = upper((item_code)::text))),
    CONSTRAINT c_item_1b CHECK (((item_name)::text = upper((item_name)::text))),
    CONSTRAINT c_item_1c CHECK (((sku_code)::text = upper((sku_code)::text))),
    CONSTRAINT c_item_1d CHECK ((reorder_qty > 0.00)),
    CONSTRAINT c_item_3 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar]))),
    CONSTRAINT c_item_baseline_burn CHECK ((baseline_burn_rate >= 0.0000)),
    CONSTRAINT c_item_criticality CHECK (((criticality_level)::text = ANY (ARRAY[('CRITICAL'::character varying)::text, ('HIGH'::character varying)::text, ('NORMAL'::character varying)::text, ('LOW'::character varying)::text]))),
    CONSTRAINT c_item_min_threshold CHECK ((min_stock_threshold >= 0.00))
);


--
-- Name: COLUMN item.baseline_burn_rate; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.item.baseline_burn_rate IS 'Default burn rate (units/hour) used when no recent fulfillment data exists';


--
-- Name: COLUMN item.min_stock_threshold; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.item.min_stock_threshold IS 'Item-level minimum threshold; overrides warehouse default if set';


--
-- Name: COLUMN item.criticality_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.item.criticality_level IS 'Item criticality for prioritization: CRITICAL, HIGH, NORMAL, LOW';


--
-- Name: item_location; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_location (
    inventory_id integer NOT NULL,
    item_id integer NOT NULL,
    location_id integer NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL
);


--
-- Name: item_new_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.item ALTER COLUMN item_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.item_new_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: itembatch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.itembatch (
    batch_id integer NOT NULL,
    inventory_id integer NOT NULL,
    item_id integer NOT NULL,
    batch_no character varying(20),
    batch_date date,
    expiry_date date,
    usable_qty numeric(15,4) NOT NULL,
    reserved_qty numeric(15,4) DEFAULT 0 NOT NULL,
    defective_qty numeric(15,4) DEFAULT 0 NOT NULL,
    expired_qty numeric(15,4) DEFAULT 0 NOT NULL,
    uom_code character varying(25) NOT NULL,
    size_spec character varying(30),
    avg_unit_value numeric(10,2) DEFAULT 0.00 NOT NULL,
    last_verified_by character varying(20),
    last_verified_date date,
    status_code character(1) NOT NULL,
    comments_text text,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_itembatch_1 CHECK (((batch_no)::text = upper((batch_no)::text))),
    CONSTRAINT c_itembatch_2a CHECK ((usable_qty >= 0.00)),
    CONSTRAINT c_itembatch_2b CHECK (((reserved_qty <= usable_qty) AND (reserved_qty >= 0.00))),
    CONSTRAINT c_itembatch_2c CHECK ((defective_qty >= 0.00)),
    CONSTRAINT c_itembatch_2d CHECK ((expired_qty >= 0.00)),
    CONSTRAINT c_itembatch_3 CHECK ((avg_unit_value >= 0.00)),
    CONSTRAINT c_itembatch_5 CHECK ((((last_verified_by IS NULL) AND (last_verified_date IS NULL)) OR ((last_verified_by IS NOT NULL) AND (last_verified_date IS NOT NULL)))),
    CONSTRAINT c_itembatch_6 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'U'::bpchar])))
);


--
-- Name: itembatch_batch_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.itembatch ALTER COLUMN batch_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.itembatch_batch_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: itemcatg; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.itemcatg (
    category_id integer NOT NULL,
    category_code character varying(30) NOT NULL,
    category_desc character varying(60) NOT NULL,
    comments_text text,
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    category_type character(5) DEFAULT 'GOODS'::bpchar NOT NULL,
    CONSTRAINT c_itemcatg_0 CHECK ((category_type = ANY (ARRAY['GOODS'::bpchar, 'FUNDS'::bpchar]))),
    CONSTRAINT c_itemcatg_1 CHECK (((category_code)::text = upper((category_code)::text))),
    CONSTRAINT c_itemcatg_2 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar])))
);


--
-- Name: TABLE itemcatg; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.itemcatg IS 'Item Category master data table - defines categories for relief items';


--
-- Name: COLUMN itemcatg.category_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.itemcatg.category_id IS 'Primary key - auto-generated category identifier';


--
-- Name: COLUMN itemcatg.category_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.itemcatg.category_code IS 'Unique category code (uppercase) - business key';


--
-- Name: COLUMN itemcatg.category_desc; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.itemcatg.category_desc IS 'Description of the item category';


--
-- Name: COLUMN itemcatg.comments_text; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.itemcatg.comments_text IS 'Additional comments or notes about this category';


--
-- Name: COLUMN itemcatg.status_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.itemcatg.status_code IS 'Status: A=Active, I=Inactive';


--
-- Name: COLUMN itemcatg.version_nbr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.itemcatg.version_nbr IS 'Optimistic locking version number';


--
-- Name: itemcatg_category_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.itemcatg ALTER COLUMN category_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.itemcatg_category_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: itemcostdef; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.itemcostdef (
    cost_id integer NOT NULL,
    cost_name public.citext NOT NULL,
    cost_desc character varying(255) NOT NULL,
    cost_type character(16) NOT NULL,
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT c_itemcostdef_1 CHECK ((length((cost_name)::text) <= 50)),
    CONSTRAINT c_itemcostdef_2 CHECK ((cost_type = ANY (ARRAY['PURCHASE'::bpchar, 'ADDITIONAL'::bpchar]))),
    CONSTRAINT c_itemcostdef_3 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar])))
);


--
-- Name: itemcostdef_cost_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.itemcostdef ALTER COLUMN cost_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.itemcostdef_cost_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: lead_time_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lead_time_config (
    config_id integer NOT NULL,
    horizon character varying(1) NOT NULL,
    from_warehouse_id integer,
    to_warehouse_id integer,
    supplier_id integer,
    lead_time_hours integer NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    effective_from date DEFAULT CURRENT_DATE NOT NULL,
    effective_to date,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_ltc_a_warehouses CHECK (((((horizon)::text = 'A'::text) AND (from_warehouse_id IS NOT NULL) AND (to_warehouse_id IS NOT NULL)) OR ((horizon)::text <> 'A'::text))),
    CONSTRAINT c_ltc_c_supplier CHECK (((((horizon)::text = 'C'::text) AND (is_default OR (supplier_id IS NOT NULL))) OR ((horizon)::text <> 'C'::text))),
    CONSTRAINT c_ltc_horizon CHECK (((horizon)::text = ANY (ARRAY[('A'::character varying)::text, ('B'::character varying)::text, ('C'::character varying)::text]))),
    CONSTRAINT c_ltc_lead_time CHECK ((lead_time_hours > 0))
);


--
-- Name: TABLE lead_time_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.lead_time_config IS 'Configurable lead times for Three Horizons: A (warehouse routes), B (donations), C (suppliers)';


--
-- Name: lead_time_config_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.lead_time_config ALTER COLUMN config_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.lead_time_config_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: location; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.location (
    location_id integer NOT NULL,
    inventory_id integer NOT NULL,
    location_desc character varying(255) NOT NULL,
    status_code character(1) NOT NULL,
    comments_text character varying(255),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT location_status_code_check CHECK ((status_code = ANY (ARRAY['O'::bpchar, 'C'::bpchar])))
);


--
-- Name: location_location_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.location ALTER COLUMN location_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.location_location_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: needs_list; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.needs_list (
    needs_list_id integer NOT NULL,
    needs_list_no character varying(30) NOT NULL,
    event_id integer NOT NULL,
    warehouse_id integer NOT NULL,
    event_phase character varying(15) NOT NULL,
    calculation_dtime timestamp(0) without time zone NOT NULL,
    demand_window_hours integer NOT NULL,
    planning_window_hours integer NOT NULL,
    safety_factor numeric(4,2) NOT NULL,
    data_freshness_level character varying(10) DEFAULT 'HIGH'::character varying NOT NULL,
    status_code character varying(20) DEFAULT 'DRAFT'::character varying NOT NULL,
    total_gap_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    total_estimated_value numeric(15,2) DEFAULT 0.00,
    submitted_at timestamp(0) without time zone,
    submitted_by character varying(20),
    under_review_at timestamp(0) without time zone,
    under_review_by character varying(20),
    reviewed_at timestamp(0) without time zone,
    reviewed_by character varying(20),
    approved_at timestamp(0) without time zone,
    approved_by character varying(20),
    rejected_at timestamp(0) without time zone,
    rejected_by character varying(20),
    rejection_reason character varying(255),
    returned_at timestamp(0) without time zone,
    returned_by character varying(20),
    returned_reason character varying(255),
    cancelled_at timestamp(0) without time zone,
    cancelled_by character varying(20),
    superseded_by_id integer,
    notes_text text,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_needs_list_freshness CHECK (((data_freshness_level)::text = ANY (ARRAY[('HIGH'::character varying)::text, ('MEDIUM'::character varying)::text, ('LOW'::character varying)::text]))),
    CONSTRAINT c_needs_list_gap CHECK ((total_gap_qty >= 0.00)),
    CONSTRAINT c_needs_list_phase CHECK (((event_phase)::text = ANY (ARRAY[('SURGE'::character varying)::text, ('STABILIZED'::character varying)::text, ('BASELINE'::character varying)::text]))),
    CONSTRAINT c_needs_list_status CHECK (((status_code)::text = ANY (ARRAY[('DRAFT'::character varying)::text, ('PENDING_APPROVAL'::character varying)::text, ('UNDER_REVIEW'::character varying)::text, ('APPROVED'::character varying)::text, ('REJECTED'::character varying)::text, ('RETURNED'::character varying)::text, ('IN_PROGRESS'::character varying)::text, ('FULFILLED'::character varying)::text, ('CANCELLED'::character varying)::text, ('SUPERSEDED'::character varying)::text])))
);


--
-- Name: TABLE needs_list; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.needs_list IS 'Supply Replenishment needs list header - EP-02';


--
-- Name: COLUMN needs_list.needs_list_no; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.needs_list.needs_list_no IS 'Unique identifier: NL-{EVENT_ID}-{WAREHOUSE_ID}-{YYYYMMDD}-{SEQ}';


--
-- Name: COLUMN needs_list.data_freshness_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.needs_list.data_freshness_level IS 'Overall data confidence at calculation time: HIGH, MEDIUM, LOW';


--
-- Name: COLUMN needs_list.superseded_by_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.needs_list.superseded_by_id IS 'If status=SUPERSEDED, points to the newer needs list';


--
-- Name: needs_list_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.needs_list_audit (
    audit_id integer NOT NULL,
    needs_list_id integer NOT NULL,
    needs_list_item_id integer,
    action_type character varying(30) NOT NULL,
    field_name character varying(50),
    old_value text,
    new_value text,
    reason_code character varying(50),
    notes_text character varying(500),
    actor_user_id character varying(20) NOT NULL,
    action_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT c_nla_action CHECK (((action_type)::text = ANY (ARRAY[('CREATED'::character varying)::text, ('SUBMITTED'::character varying)::text, ('APPROVED'::character varying)::text, ('REJECTED'::character varying)::text, ('RETURNED'::character varying)::text, ('QUANTITY_ADJUSTED'::character varying)::text, ('STATUS_CHANGED'::character varying)::text, ('HORIZON_CHANGED'::character varying)::text, ('SUPERSEDED'::character varying)::text, ('CANCELLED'::character varying)::text, ('FULFILLED'::character varying)::text, ('COMMENT_ADDED'::character varying)::text])))
);


--
-- Name: TABLE needs_list_audit; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.needs_list_audit IS 'Immutable audit trail for all needs list actions';


--
-- Name: needs_list_audit_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.needs_list_audit ALTER COLUMN audit_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.needs_list_audit_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: needs_list_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.needs_list_item (
    needs_list_item_id integer NOT NULL,
    needs_list_id integer NOT NULL,
    item_id integer NOT NULL,
    uom_code character varying(25) NOT NULL,
    burn_rate numeric(10,4) DEFAULT 0.0000 NOT NULL,
    burn_rate_source character varying(20) DEFAULT 'CALCULATED'::character varying NOT NULL,
    available_stock numeric(15,2) DEFAULT 0.00 NOT NULL,
    reserved_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    inbound_transfer_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    inbound_donation_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    inbound_procurement_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    required_qty numeric(15,2) NOT NULL,
    coverage_qty numeric(15,2) NOT NULL,
    gap_qty numeric(15,2) NOT NULL,
    time_to_stockout_hours numeric(10,2),
    severity_level character varying(10) DEFAULT 'OK'::character varying NOT NULL,
    horizon_a_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    horizon_a_source_warehouse_id integer,
    horizon_b_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    horizon_c_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    adjusted_qty numeric(15,2),
    adjustment_reason character varying(50),
    adjustment_notes character varying(255),
    adjusted_by character varying(20),
    adjusted_at timestamp(0) without time zone,
    fulfilled_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    fulfillment_status character varying(20) DEFAULT 'PENDING'::character varying NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_nli_adjustment_reason CHECK (((adjustment_reason IS NULL) OR ((adjustment_reason)::text = ANY (ARRAY[('DEMAND_ADJUSTED'::character varying)::text, ('PARTIAL_COVERAGE'::character varying)::text, ('PRIORITY_CHANGE'::character varying)::text, ('BUDGET_CONSTRAINT'::character varying)::text, ('SUPPLIER_LIMIT'::character varying)::text, ('OTHER'::character varying)::text])))),
    CONSTRAINT c_nli_burn_rate CHECK ((burn_rate >= 0.0000)),
    CONSTRAINT c_nli_burn_source CHECK (((burn_rate_source)::text = ANY (ARRAY[('CALCULATED'::character varying)::text, ('BASELINE'::character varying)::text, ('MANUAL'::character varying)::text, ('ESTIMATED'::character varying)::text]))),
    CONSTRAINT c_nli_fulfillment_status CHECK (((fulfillment_status)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('PARTIAL'::character varying)::text, ('FULFILLED'::character varying)::text, ('CANCELLED'::character varying)::text]))),
    CONSTRAINT c_nli_horizons CHECK (((horizon_a_qty >= 0.00) AND (horizon_b_qty >= 0.00) AND (horizon_c_qty >= 0.00))),
    CONSTRAINT c_nli_quantities CHECK (((available_stock >= 0.00) AND (reserved_qty >= 0.00) AND (inbound_transfer_qty >= 0.00) AND (inbound_donation_qty >= 0.00) AND (inbound_procurement_qty >= 0.00))),
    CONSTRAINT c_nli_severity CHECK (((severity_level)::text = ANY (ARRAY[('CRITICAL'::character varying)::text, ('WARNING'::character varying)::text, ('WATCH'::character varying)::text, ('OK'::character varying)::text])))
);


--
-- Name: TABLE needs_list_item; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.needs_list_item IS 'Supply Replenishment needs list line items with Three Horizons logic';


--
-- Name: COLUMN needs_list_item.burn_rate_source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.needs_list_item.burn_rate_source IS 'How burn rate was determined: CALCULATED (from fulfillments), BASELINE (item default), MANUAL, ESTIMATED (stale data)';


--
-- Name: COLUMN needs_list_item.severity_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.needs_list_item.severity_level IS 'CRITICAL (<8h), WARNING (8-24h), WATCH (24-72h), OK (>72h)';


--
-- Name: needs_list_item_needs_list_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.needs_list_item ALTER COLUMN needs_list_item_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.needs_list_item_needs_list_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: needs_list_needs_list_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.needs_list ALTER COLUMN needs_list_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.needs_list_needs_list_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: needs_list_workflow_metadata; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.needs_list_workflow_metadata (
    needs_list_id integer NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notification; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification (
    id integer NOT NULL,
    user_id integer NOT NULL,
    warehouse_id integer,
    reliefrqst_id integer,
    title character varying(200) NOT NULL,
    message text NOT NULL,
    type character varying(50) NOT NULL,
    status character varying(20) DEFAULT 'unread'::character varying NOT NULL,
    link_url character varying(500),
    payload text,
    is_archived boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: notification_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notification_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notification_id_seq OWNED BY public.notification.id;


--
-- Name: parish; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parish (
    parish_code character(2) NOT NULL,
    parish_name character varying(40) NOT NULL,
    CONSTRAINT parish_parish_code_check CHECK (((parish_code ~ similar_to_escape('[0-9]*'::text)) AND (((parish_code)::integer >= 1) AND ((parish_code)::integer <= 14))))
);


--
-- Name: permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.permission (
    perm_id integer NOT NULL,
    resource character varying(40) NOT NULL,
    action character varying(32) NOT NULL,
    create_by_id character varying(20) DEFAULT 'system'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT now() NOT NULL,
    update_by_id character varying(20) DEFAULT 'system'::character varying NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT now() NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL
);


--
-- Name: permission_perm_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.permission ALTER COLUMN perm_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.permission_perm_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: procurement; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.procurement (
    procurement_id integer NOT NULL,
    procurement_no character varying(30) NOT NULL,
    needs_list_id integer,
    event_id integer NOT NULL,
    target_warehouse_id integer NOT NULL,
    supplier_id integer,
    procurement_method character varying(25) NOT NULL,
    po_number character varying(50),
    total_value numeric(15,2) DEFAULT 0.00 NOT NULL,
    currency_code character varying(10) DEFAULT 'JMD'::character varying NOT NULL,
    status_code character varying(20) DEFAULT 'DRAFT'::character varying NOT NULL,
    approved_at timestamp(0) without time zone,
    approved_by character varying(20),
    approval_threshold_tier character varying(10),
    shipped_at timestamp(0) without time zone,
    expected_arrival timestamp(0) without time zone,
    received_at timestamp(0) without time zone,
    received_by character varying(20),
    notes_text text,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_proc_method CHECK (((procurement_method)::text = ANY (ARRAY[('EMERGENCY_DIRECT'::character varying)::text, ('SINGLE_SOURCE'::character varying)::text, ('RFQ'::character varying)::text, ('RESTRICTED_BIDDING'::character varying)::text, ('OPEN_TENDER'::character varying)::text, ('FRAMEWORK'::character varying)::text]))),
    CONSTRAINT c_proc_status CHECK (((status_code)::text = ANY (ARRAY[('DRAFT'::character varying)::text, ('PENDING_APPROVAL'::character varying)::text, ('APPROVED'::character varying)::text, ('REJECTED'::character varying)::text, ('ORDERED'::character varying)::text, ('SHIPPED'::character varying)::text, ('PARTIAL_RECEIVED'::character varying)::text, ('RECEIVED'::character varying)::text, ('CANCELLED'::character varying)::text]))),
    CONSTRAINT c_proc_tier CHECK (((approval_threshold_tier IS NULL) OR ((approval_threshold_tier)::text = ANY (ARRAY[('TIER_1'::character varying)::text, ('TIER_2'::character varying)::text, ('TIER_3'::character varying)::text, ('EMERGENCY'::character varying)::text]))))
);


--
-- Name: TABLE procurement; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.procurement IS 'Procurement orders generated from Horizon C needs list items';


--
-- Name: COLUMN procurement.approval_threshold_tier; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.procurement.approval_threshold_tier IS 'GOJ procurement tier based on value thresholds';


--
-- Name: procurement_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.procurement_item (
    procurement_item_id integer NOT NULL,
    procurement_id integer NOT NULL,
    item_id integer NOT NULL,
    needs_list_item_id integer,
    ordered_qty numeric(15,2) NOT NULL,
    unit_price numeric(12,2),
    line_total numeric(15,2),
    uom_code character varying(25) NOT NULL,
    received_qty numeric(15,2) DEFAULT 0.00 NOT NULL,
    status_code character varying(20) DEFAULT 'PENDING'::character varying NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_pi_qty CHECK ((ordered_qty > 0.00)),
    CONSTRAINT c_pi_received CHECK (((received_qty >= 0.00) AND (received_qty <= ordered_qty))),
    CONSTRAINT c_pi_status CHECK (((status_code)::text = ANY (ARRAY[('PENDING'::character varying)::text, ('PARTIAL'::character varying)::text, ('RECEIVED'::character varying)::text, ('CANCELLED'::character varying)::text])))
);


--
-- Name: TABLE procurement_item; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.procurement_item IS 'Line items within a procurement order';


--
-- Name: procurement_item_procurement_item_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.procurement_item ALTER COLUMN procurement_item_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.procurement_item_procurement_item_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: procurement_procurement_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.procurement ALTER COLUMN procurement_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.procurement_procurement_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: relief_request_fulfillment_lock; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.relief_request_fulfillment_lock (
    reliefrqst_id integer NOT NULL,
    fulfiller_user_id integer NOT NULL,
    fulfiller_email character varying(100) NOT NULL,
    acquired_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone,
    CONSTRAINT chk_expires_after_acquired CHECK (((expires_at IS NULL) OR (expires_at > acquired_at)))
);


--
-- Name: TABLE relief_request_fulfillment_lock; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.relief_request_fulfillment_lock IS 'Tracks which user is currently preparing/packaging a relief request to ensure single fulfiller';


--
-- Name: COLUMN relief_request_fulfillment_lock.expires_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.relief_request_fulfillment_lock.expires_at IS 'Optional expiry time for automatic lock release';


--
-- Name: reliefpkg; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reliefpkg (
    reliefpkg_id integer NOT NULL,
    to_inventory_id integer NOT NULL,
    reliefrqst_id integer NOT NULL,
    start_date date DEFAULT CURRENT_DATE NOT NULL,
    dispatch_dtime timestamp(0) without time zone,
    transport_mode character varying(255),
    comments_text character varying(255),
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone,
    verify_by_id character varying(20),
    verify_dtime timestamp(0) without time zone,
    version_nbr integer NOT NULL,
    received_by_id character varying(20),
    received_dtime timestamp(0) without time zone,
    agency_id integer NOT NULL,
    tracking_no character(7) NOT NULL,
    eligible_event_id integer,
    CONSTRAINT c_reliefpkg_2 CHECK ((((dispatch_dtime IS NULL) AND (status_code <> 'D'::bpchar)) OR ((dispatch_dtime IS NOT NULL) AND (status_code = 'D'::bpchar)))),
    CONSTRAINT c_reliefpkg_3 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'P'::bpchar, 'C'::bpchar, 'V'::bpchar, 'D'::bpchar, 'R'::bpchar]))),
    CONSTRAINT reliefpkg_start_date_check CHECK ((start_date <= CURRENT_DATE))
);


--
-- Name: reliefpkg_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reliefpkg_item (
    reliefpkg_id integer NOT NULL,
    fr_inventory_id integer NOT NULL,
    batch_id integer NOT NULL,
    item_id integer NOT NULL,
    item_qty numeric(15,4) NOT NULL,
    uom_code character varying(25) NOT NULL,
    reason_text character varying(255),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_reliefpkg_item_1 CHECK ((item_qty >= 0.00))
);


--
-- Name: reliefpkg_reliefpkg_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.reliefpkg ALTER COLUMN reliefpkg_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.reliefpkg_reliefpkg_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: reliefrqst; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reliefrqst (
    reliefrqst_id integer NOT NULL,
    agency_id integer NOT NULL,
    request_date date NOT NULL,
    urgency_ind character(1) NOT NULL,
    status_code smallint DEFAULT 0 NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    review_by_id character varying(20),
    review_dtime timestamp(0) without time zone,
    action_by_id character varying(20),
    action_dtime timestamp(0) without time zone,
    version_nbr integer NOT NULL,
    eligible_event_id integer,
    rqst_notes_text text,
    review_notes_text text,
    tracking_no character varying(7) DEFAULT upper(substr(replace((gen_random_uuid())::text, '-'::text, ''::text), 1, 7)) NOT NULL,
    status_reason_desc character varying(255),
    receive_by_id character varying(20),
    receive_dtime timestamp(0) without time zone,
    CONSTRAINT c_reliefrqst_1 CHECK ((request_date <= CURRENT_DATE)),
    CONSTRAINT c_reliefrqst_2 CHECK ((urgency_ind = ANY (ARRAY['L'::bpchar, 'M'::bpchar, 'H'::bpchar, 'C'::bpchar]))),
    CONSTRAINT c_reliefrqst_3 CHECK (((status_reason_desc IS NOT NULL) OR ((status_reason_desc IS NULL) AND (status_code <> ALL (ARRAY[4, 6, 8]))))),
    CONSTRAINT c_reliefrqst_4a CHECK ((((review_by_id IS NULL) AND (status_code < 2)) OR ((review_by_id IS NOT NULL) AND (status_code >= 2)))),
    CONSTRAINT c_reliefrqst_4b CHECK ((((review_by_id IS NULL) AND (review_dtime IS NULL)) OR ((review_by_id IS NOT NULL) AND (review_dtime IS NOT NULL)))),
    CONSTRAINT c_reliefrqst_5a CHECK ((((action_by_id IS NULL) AND (status_code < 4)) OR ((action_by_id IS NOT NULL) AND (status_code >= 4)))),
    CONSTRAINT c_reliefrqst_5b CHECK ((((action_by_id IS NULL) AND (action_dtime IS NULL)) OR ((action_by_id IS NOT NULL) AND (action_dtime IS NOT NULL)))),
    CONSTRAINT c_reliefrqst_6a CHECK ((((receive_by_id IS NULL) AND (status_code <> 9)) OR ((receive_by_id IS NOT NULL) AND (status_code = 9)))),
    CONSTRAINT c_reliefrqst_6b CHECK ((((receive_by_id IS NULL) AND (receive_dtime IS NULL)) OR ((receive_by_id IS NOT NULL) AND (receive_dtime IS NOT NULL))))
);


--
-- Name: reliefrqst_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reliefrqst_item (
    reliefrqst_id integer NOT NULL,
    item_id integer NOT NULL,
    request_qty numeric(12,2) NOT NULL,
    issue_qty numeric(12,2) DEFAULT 0.00 NOT NULL,
    urgency_ind character(1) NOT NULL,
    rqst_reason_desc character varying(255),
    required_by_date date,
    status_code character(1) DEFAULT 'R'::bpchar NOT NULL,
    status_reason_desc character varying(255),
    action_by_id character varying(20),
    action_dtime timestamp(0) without time zone,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_reliefrqst_item_1 CHECK ((request_qty > 0.00)),
    CONSTRAINT c_reliefrqst_item_2a CHECK ((((status_code = ANY (ARRAY['R'::bpchar, 'U'::bpchar, 'W'::bpchar, 'D'::bpchar])) AND (issue_qty = (0)::numeric)) OR ((status_code = ANY (ARRAY['P'::bpchar, 'L'::bpchar])) AND (issue_qty < request_qty)) OR ((status_code = 'F'::bpchar) AND (issue_qty = request_qty)))),
    CONSTRAINT c_reliefrqst_item_3 CHECK ((urgency_ind = ANY (ARRAY['L'::bpchar, 'M'::bpchar, 'H'::bpchar, 'C'::bpchar]))),
    CONSTRAINT c_reliefrqst_item_4 CHECK (((urgency_ind = ANY (ARRAY['L'::bpchar, 'M'::bpchar, 'C'::bpchar])) OR ((urgency_ind = 'H'::bpchar) AND (rqst_reason_desc IS NOT NULL) AND (TRIM(BOTH FROM rqst_reason_desc) <> ''::text)))),
    CONSTRAINT c_reliefrqst_item_5 CHECK (((required_by_date IS NOT NULL) OR ((required_by_date IS NULL) AND (urgency_ind = ANY (ARRAY['L'::bpchar, 'M'::bpchar]))))),
    CONSTRAINT c_reliefrqst_item_6a CHECK ((status_code = ANY (ARRAY['R'::bpchar, 'U'::bpchar, 'W'::bpchar, 'D'::bpchar, 'P'::bpchar, 'L'::bpchar, 'F'::bpchar]))),
    CONSTRAINT c_reliefrqst_item_6b CHECK (((status_reason_desc IS NOT NULL) OR ((status_reason_desc IS NULL) AND (status_code <> ALL (ARRAY['D'::bpchar, 'L'::bpchar]))))),
    CONSTRAINT c_reliefrqst_item_7 CHECK ((((action_by_id IS NULL) AND (status_code = 'R'::bpchar)) OR ((action_by_id IS NOT NULL) AND (status_code <> 'R'::bpchar)))),
    CONSTRAINT c_reliefrqst_item_8 CHECK ((((action_by_id IS NULL) AND (action_dtime IS NULL)) OR ((action_by_id IS NOT NULL) AND (action_dtime IS NOT NULL))))
);


--
-- Name: reliefrqst_reliefrqst_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.reliefrqst ALTER COLUMN reliefrqst_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.reliefrqst_reliefrqst_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: reliefrqst_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reliefrqst_status (
    status_code smallint NOT NULL,
    status_desc character varying(30) NOT NULL,
    is_active_flag boolean DEFAULT true NOT NULL,
    reason_rqrd_flag boolean DEFAULT false NOT NULL
);


--
-- Name: reliefrqstitem_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reliefrqstitem_status (
    status_code character(1) NOT NULL,
    status_desc character varying(30) NOT NULL,
    item_qty_rule character(2) NOT NULL,
    active_flag boolean DEFAULT true NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT c_reliefrqstitem_status_2 CHECK ((item_qty_rule = ANY (ARRAY['EZ'::bpchar, 'GZ'::bpchar, 'ER'::bpchar])))
);


--
-- Name: role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role (
    id integer NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: role_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.role_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.role_id_seq OWNED BY public.role.id;


--
-- Name: role_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_permission (
    role_id integer NOT NULL,
    perm_id integer NOT NULL,
    scope_json jsonb,
    create_by_id character varying(20) DEFAULT 'system'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT now() NOT NULL,
    update_by_id character varying(20) DEFAULT 'system'::character varying NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT now() NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL
);


--
-- Name: rtintake; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rtintake (
    xfreturn_id integer NOT NULL,
    inventory_id integer NOT NULL,
    intake_date date NOT NULL,
    comments_text character varying(255),
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone,
    verify_by_id character varying(20) NOT NULL,
    verify_dtime timestamp(0) without time zone,
    version_nbr integer NOT NULL,
    CONSTRAINT rtintake_intake_date_check CHECK ((intake_date <= CURRENT_DATE)),
    CONSTRAINT rtintake_status_code_check CHECK ((status_code = ANY (ARRAY['I'::bpchar, 'C'::bpchar, 'V'::bpchar])))
);


--
-- Name: rtintake_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rtintake_item (
    xfreturn_id integer NOT NULL,
    inventory_id integer NOT NULL,
    item_id integer NOT NULL,
    usable_qty numeric(12,2) NOT NULL,
    location1_id integer,
    defective_qty numeric(12,2) NOT NULL,
    location2_id integer,
    expired_qty numeric(12,2) NOT NULL,
    location3_id integer,
    uom_code character varying(25) NOT NULL,
    status_code character(1) NOT NULL,
    comments_text character varying(255),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT rtintake_item_defective_qty_check CHECK ((defective_qty >= 0.00)),
    CONSTRAINT rtintake_item_expired_qty_check CHECK ((expired_qty >= 0.00)),
    CONSTRAINT rtintake_item_status_code_check CHECK ((status_code = ANY (ARRAY['P'::bpchar, 'V'::bpchar]))),
    CONSTRAINT rtintake_item_usable_qty_check CHECK ((usable_qty >= 0.00))
);


--
-- Name: supplier; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.supplier (
    supplier_id integer NOT NULL,
    supplier_code character varying(20) NOT NULL,
    supplier_name character varying(120) NOT NULL,
    contact_name character varying(80),
    phone_no character varying(20),
    email_text character varying(100),
    address_text character varying(255),
    parish_code character(2),
    country_id integer,
    default_lead_time_days integer DEFAULT 14,
    is_framework_supplier boolean DEFAULT false,
    framework_contract_no character varying(50),
    framework_expiry_date date,
    status_code character(1) DEFAULT 'A'::bpchar NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT c_supplier_code_upper CHECK (((supplier_code)::text = upper((supplier_code)::text))),
    CONSTRAINT c_supplier_status CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar])))
);


--
-- Name: TABLE supplier; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.supplier IS 'Supplier/vendor master for Horizon C procurement';


--
-- Name: COLUMN supplier.is_framework_supplier; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.supplier.is_framework_supplier IS 'TRUE if supplier has a pre-negotiated framework agreement';


--
-- Name: supplier_supplier_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.supplier ALTER COLUMN supplier_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.supplier_supplier_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: tenant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant (
    tenant_id integer NOT NULL,
    tenant_code character varying(20) NOT NULL,
    tenant_name character varying(120) NOT NULL,
    tenant_type character varying(20) NOT NULL,
    parent_tenant_id integer,
    address1_text character varying(255),
    address2_text character varying(255),
    parish_code character(2),
    contact_name character varying(50),
    phone_no character varying(20),
    email_text character varying(100),
    data_scope character varying(50) DEFAULT 'OWN_DATA'::character varying,
    pii_access character varying(20) DEFAULT 'NONE'::character varying,
    offline_required boolean DEFAULT false,
    mobile_priority character varying(10) DEFAULT 'LOW'::character varying,
    status_code character(1) DEFAULT 'A'::bpchar NOT NULL,
    create_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT tenant_code_upper CHECK (((tenant_code)::text = upper((tenant_code)::text))),
    CONSTRAINT tenant_data_scope_check CHECK (((data_scope)::text = ANY ((ARRAY['OWN_DATA'::character varying, 'PARISH_DATA'::character varying, 'REGIONAL_DATA'::character varying, 'NATIONAL_DATA'::character varying])::text[]))),
    CONSTRAINT tenant_mobile_priority_check CHECK (((mobile_priority)::text = ANY ((ARRAY['CRITICAL'::character varying, 'HIGH'::character varying, 'MEDIUM'::character varying, 'LOW'::character varying])::text[]))),
    CONSTRAINT tenant_name_upper CHECK (((tenant_name)::text = upper((tenant_name)::text))),
    CONSTRAINT tenant_pii_access_check CHECK (((pii_access)::text = ANY ((ARRAY['NONE'::character varying, 'AGGREGATED'::character varying, 'LIMITED'::character varying, 'MASKED'::character varying, 'FULL'::character varying])::text[]))),
    CONSTRAINT tenant_status_code_check CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar]))),
    CONSTRAINT tenant_tenant_type_check CHECK (((tenant_type)::text = ANY ((ARRAY['NATIONAL'::character varying, 'MILITARY'::character varying, 'PARISH'::character varying, 'MINISTRY'::character varying, 'EXTERNAL'::character varying, 'INFRASTRUCTURE'::character varying, 'PUBLIC'::character varying])::text[])))
);


--
-- Name: TABLE tenant; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tenant IS 'Canonical organization registry for multi-tenancy. Supersedes custodian for organizational identity.';


--
-- Name: COLUMN tenant.tenant_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tenant.tenant_type IS 'NATIONAL=ODPEM/NDRMC, MILITARY=JDF/JCF, PARISH=Municipal Corps, MINISTRY=Govt ministries, EXTERNAL=NGOs, INFRASTRUCTURE=Utilities, PUBLIC=Dashboard access';


--
-- Name: COLUMN tenant.data_scope; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tenant.data_scope IS 'Data visibility scope: OWN_DATA (own org only), PARISH_DATA (parish-wide), NATIONAL_DATA (all parishes)';


--
-- Name: tenant_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_config (
    config_id integer NOT NULL,
    tenant_id integer NOT NULL,
    config_key character varying(50) NOT NULL,
    config_value text NOT NULL,
    config_type character varying(20) DEFAULT 'STRING'::character varying,
    effective_date date DEFAULT CURRENT_DATE NOT NULL,
    expiry_date date,
    description text,
    create_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    CONSTRAINT tenant_config_config_type_check CHECK (((config_type)::text = ANY ((ARRAY['STRING'::character varying, 'INTEGER'::character varying, 'DECIMAL'::character varying, 'BOOLEAN'::character varying, 'JSON'::character varying])::text[])))
);


--
-- Name: TABLE tenant_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tenant_config IS 'Tenant-specific configuration overrides (approval thresholds, phase parameters, etc.)';


--
-- Name: tenant_config_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tenant_config_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tenant_config_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tenant_config_config_id_seq OWNED BY public.tenant_config.config_id;


--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tenant_tenant_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tenant_tenant_id_seq OWNED BY public.tenant.tenant_id;


--
-- Name: tenant_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_user (
    tenant_id integer NOT NULL,
    user_id integer NOT NULL,
    is_primary_tenant boolean DEFAULT true,
    access_level character varying(20) DEFAULT 'STANDARD'::character varying,
    assigned_at timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP,
    assigned_by integer,
    status_code character(1) DEFAULT 'A'::bpchar NOT NULL,
    create_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT tenant_user_access_level_check CHECK (((access_level)::text = ANY ((ARRAY['ADMIN'::character varying, 'FULL'::character varying, 'STANDARD'::character varying, 'LIMITED'::character varying, 'READ_ONLY'::character varying])::text[]))),
    CONSTRAINT tenant_user_status_code_check CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar])))
);


--
-- Name: TABLE tenant_user; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tenant_user IS 'Maps users to tenants with access levels. Users may belong to multiple tenants.';


--
-- Name: COLUMN tenant_user.access_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.tenant_user.access_level IS 'From DMIS Access Matrix: ADMIN, FULL, STANDARD, LIMITED, READ_ONLY';


--
-- Name: tenant_warehouse; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_warehouse (
    tenant_id integer NOT NULL,
    warehouse_id integer NOT NULL,
    ownership_type character varying(20) DEFAULT 'OWNED'::character varying,
    access_level character varying(20) DEFAULT 'FULL'::character varying,
    effective_date date DEFAULT CURRENT_DATE NOT NULL,
    expiry_date date,
    create_by_id character varying(20) DEFAULT 'SYSTEM'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT tenant_warehouse_access_level_check CHECK (((access_level)::text = ANY ((ARRAY['FULL'::character varying, 'STANDARD'::character varying, 'LIMITED'::character varying, 'READ_ONLY'::character varying])::text[]))),
    CONSTRAINT tenant_warehouse_ownership_type_check CHECK (((ownership_type)::text = ANY ((ARRAY['OWNED'::character varying, 'SHARED'::character varying, 'ALLOCATED'::character varying, 'PARTNER'::character varying])::text[])))
);


--
-- Name: TABLE tenant_warehouse; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.tenant_warehouse IS 'Maps warehouses to tenants. Supports shared warehouse model.';


--
-- Name: transaction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transaction (
    id integer NOT NULL,
    item_id integer,
    ttype character varying(8) NOT NULL,
    qty numeric(12,2) NOT NULL,
    warehouse_id integer,
    donor_id integer,
    event_id integer,
    expiry_date date,
    notes text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    created_by character varying(200)
);


--
-- Name: transaction_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.transaction_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transaction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.transaction_id_seq OWNED BY public.transaction.id;


--
-- Name: transfer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transfer (
    transfer_id integer NOT NULL,
    fr_inventory_id integer NOT NULL,
    to_inventory_id integer NOT NULL,
    eligible_event_id integer,
    transfer_date date DEFAULT CURRENT_DATE NOT NULL,
    reason_text character varying(255),
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone,
    verify_by_id character varying(20) NOT NULL,
    verify_dtime timestamp(0) without time zone,
    version_nbr integer NOT NULL,
    dispatched_at timestamp(0) without time zone,
    dispatched_by character varying(20),
    expected_arrival timestamp(0) without time zone,
    received_at timestamp(0) without time zone,
    received_by character varying(20),
    needs_list_id integer,
    CONSTRAINT c_transfer_1 CHECK ((transfer_date <= CURRENT_DATE)),
    CONSTRAINT c_transfer_2 CHECK ((status_code = ANY (ARRAY['D'::bpchar, 'C'::bpchar, 'V'::bpchar, 'P'::bpchar])))
);


--
-- Name: COLUMN transfer.dispatched_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transfer.dispatched_at IS 'Timestamp when transfer was physically dispatched';


--
-- Name: COLUMN transfer.expected_arrival; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transfer.expected_arrival IS 'Estimated arrival time at destination warehouse';


--
-- Name: COLUMN transfer.received_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transfer.received_at IS 'Timestamp when transfer was received at destination';


--
-- Name: COLUMN transfer.needs_list_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.transfer.needs_list_id IS 'FK to needs_list if this transfer was generated from a needs list';


--
-- Name: transfer_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transfer_item (
    transfer_id integer NOT NULL,
    item_id integer NOT NULL,
    batch_id integer NOT NULL,
    inventory_id integer NOT NULL,
    item_qty numeric(10,2) NOT NULL,
    uom_code character varying(10) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone,
    version_nbr integer DEFAULT 1 NOT NULL,
    reason_text character varying(255),
    CONSTRAINT c_transfer_item_1 CHECK ((item_qty > (0)::numeric))
);


--
-- Name: transfer_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.transfer_request (
    id integer NOT NULL,
    from_warehouse_id integer NOT NULL,
    to_warehouse_id integer NOT NULL,
    item_id integer NOT NULL,
    quantity numeric(12,2) NOT NULL,
    status character varying(20) DEFAULT 'PENDING'::character varying NOT NULL,
    requested_by integer,
    requested_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    reviewed_by integer,
    reviewed_at timestamp without time zone,
    notes text
);


--
-- Name: transfer_request_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.transfer_request_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transfer_request_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.transfer_request_id_seq OWNED BY public.transfer_request.id;


--
-- Name: transfer_transfer_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.transfer ALTER COLUMN transfer_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.transfer_transfer_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: unitofmeasure; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unitofmeasure (
    uom_code character varying(25) NOT NULL,
    uom_desc character varying(60) NOT NULL,
    comments_text text,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    status_code character(1) DEFAULT 'A'::bpchar NOT NULL,
    CONSTRAINT c_unitofmeasure_1 CHECK (((uom_code)::text = upper((uom_code)::text))),
    CONSTRAINT c_unitofmeasure_2 CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar])))
);


--
-- Name: user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."user" (
    user_id integer NOT NULL,
    email character varying(200) NOT NULL,
    password_hash character varying(256) NOT NULL,
    first_name character varying(100),
    last_name character varying(100),
    full_name character varying(200),
    is_active boolean DEFAULT true NOT NULL,
    organization character varying(200),
    job_title character varying(200),
    phone character varying(50),
    timezone character varying(50) DEFAULT 'America/Jamaica'::character varying NOT NULL,
    language character varying(10) DEFAULT 'en'::character varying NOT NULL,
    notification_preferences text,
    assigned_warehouse_id integer,
    last_login_at timestamp without time zone,
    create_dtime timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_dtime timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    username character varying(60),
    password_algo character varying(20) DEFAULT 'argon2id'::character varying NOT NULL,
    mfa_enabled boolean DEFAULT false NOT NULL,
    mfa_secret character varying(64),
    failed_login_count smallint DEFAULT 0 NOT NULL,
    lock_until_at timestamp(0) without time zone,
    password_changed_at timestamp(0) without time zone,
    agency_id integer,
    status_code character(1) DEFAULT 'A'::bpchar NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL,
    user_name character varying(20) NOT NULL,
    login_count integer DEFAULT 0 NOT NULL,
    CONSTRAINT c_user_status_code CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar, 'L'::bpchar])))
);


--
-- Name: user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_id_seq OWNED BY public."user".user_id;


--
-- Name: user_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_role (
    user_id integer NOT NULL,
    role_id integer NOT NULL,
    assigned_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    assigned_by integer,
    create_by_id character varying(20) DEFAULT 'system'::character varying NOT NULL,
    create_dtime timestamp(0) without time zone DEFAULT now() NOT NULL,
    update_by_id character varying(20) DEFAULT 'system'::character varying NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT now() NOT NULL,
    version_nbr integer DEFAULT 1 NOT NULL
);


--
-- Name: user_warehouse; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_warehouse (
    user_id integer NOT NULL,
    warehouse_id integer NOT NULL,
    assigned_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    assigned_by integer
);


--
-- Name: v_inbound_stock; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_inbound_stock AS
 SELECT t.to_inventory_id AS warehouse_id,
    ti.item_id,
    'TRANSFER'::text AS source_type,
    sum(ti.item_qty) AS inbound_qty,
    t.expected_arrival,
    t.transfer_id AS source_id
   FROM (public.transfer t
     JOIN public.transfer_item ti ON ((t.transfer_id = ti.transfer_id)))
  WHERE ((t.status_code = 'D'::bpchar) AND (t.received_at IS NULL))
  GROUP BY t.to_inventory_id, ti.item_id, t.expected_arrival, t.transfer_id
UNION ALL
 SELECT dni.inventory_id AS warehouse_id,
    di.item_id,
    'DONATION'::text AS source_type,
    sum(di.item_qty) AS inbound_qty,
    NULL::timestamp without time zone AS expected_arrival,
    d.donation_id AS source_id
   FROM ((public.donation d
     JOIN public.donation_item di ON ((d.donation_id = di.donation_id)))
     JOIN public.dnintake dni ON ((d.donation_id = dni.donation_id)))
  WHERE ((d.status_code = 'V'::bpchar) AND (dni.status_code <> 'V'::bpchar))
  GROUP BY dni.inventory_id, di.item_id, d.donation_id
UNION ALL
 SELECT p.target_warehouse_id AS warehouse_id,
    pi.item_id,
    'PROCUREMENT'::text AS source_type,
    sum((pi.ordered_qty - pi.received_qty)) AS inbound_qty,
    p.expected_arrival,
    p.procurement_id AS source_id
   FROM (public.procurement p
     JOIN public.procurement_item pi ON ((p.procurement_id = pi.procurement_id)))
  WHERE (((p.status_code)::text = 'SHIPPED'::text) AND ((pi.status_code)::text <> 'RECEIVED'::text))
  GROUP BY p.target_warehouse_id, pi.item_id, p.expected_arrival, p.procurement_id;


--
-- Name: VIEW v_inbound_stock; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_inbound_stock IS 'Confirmed inbound stock meeting strict definition: DISPATCHED transfers, VERIFIED donations, SHIPPED procurement';


--
-- Name: v_status4reliefrqst_action; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_status4reliefrqst_action AS
 SELECT status_code,
    status_desc,
    reason_rqrd_flag
   FROM public.reliefrqst_status
  WHERE ((status_code = ANY (ARRAY[4, 5, 6, 7, 8])) AND (is_active_flag = true));


--
-- Name: v_status4reliefrqst_create; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_status4reliefrqst_create AS
 SELECT status_code,
    status_desc,
    reason_rqrd_flag
   FROM public.reliefrqst_status
  WHERE ((status_code = ANY (ARRAY[0, 1, 2, 3])) AND (is_active_flag = true));


--
-- Name: v_status4reliefrqst_processed; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_status4reliefrqst_processed AS
 SELECT status_code,
    status_desc,
    reason_rqrd_flag
   FROM public.reliefrqst_status
  WHERE ((status_code = ANY (ARRAY[4, 6, 7, 8])) AND (is_active_flag = true));


--
-- Name: warehouse; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.warehouse (
    warehouse_id integer NOT NULL,
    warehouse_name text NOT NULL,
    warehouse_type character varying(10) NOT NULL,
    address1_text character varying(255) NOT NULL,
    address2_text character varying(255),
    parish_code character(2) NOT NULL,
    contact_name character varying(50) NOT NULL,
    phone_no character varying(20) NOT NULL,
    email_text character varying(100),
    custodian_id integer NOT NULL,
    status_code character(1) NOT NULL,
    reason_desc character varying(255),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    min_stock_threshold numeric(12,2) DEFAULT 0.00 NOT NULL,
    last_sync_dtime timestamp(0) without time zone,
    sync_status character varying(10) DEFAULT 'UNKNOWN'::character varying,
    tenant_id integer,
    CONSTRAINT c_warehouse_min_threshold CHECK ((min_stock_threshold >= 0.00)),
    CONSTRAINT c_warehouse_sync_status CHECK (((sync_status)::text = ANY (ARRAY[('ONLINE'::character varying)::text, ('STALE'::character varying)::text, ('OFFLINE'::character varying)::text, ('UNKNOWN'::character varying)::text]))),
    CONSTRAINT warehouse_check CHECK ((((reason_desc IS NULL) AND (status_code = 'A'::bpchar)) OR ((reason_desc IS NOT NULL) AND (status_code = 'I'::bpchar)))),
    CONSTRAINT warehouse_contact_name_check CHECK (((contact_name)::text = upper((contact_name)::text))),
    CONSTRAINT warehouse_status_code_check CHECK ((status_code = ANY (ARRAY['A'::bpchar, 'I'::bpchar]))),
    CONSTRAINT warehouse_warehouse_type_check CHECK (((warehouse_type)::text = ANY (ARRAY[('MAIN-HUB'::character varying)::text, ('SUB-HUB'::character varying)::text])))
);


--
-- Name: COLUMN warehouse.min_stock_threshold; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.warehouse.min_stock_threshold IS 'Default minimum stock threshold for this warehouse; surplus = available - threshold';


--
-- Name: COLUMN warehouse.last_sync_dtime; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.warehouse.last_sync_dtime IS 'Last time inventory data was synchronized from this warehouse';


--
-- Name: COLUMN warehouse.sync_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.warehouse.sync_status IS 'Data freshness status: ONLINE (<2h), STALE (2-6h), OFFLINE (>6h), UNKNOWN';


--
-- Name: COLUMN warehouse.tenant_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.warehouse.tenant_id IS 'Direct FK to tenant for multi-tenancy queries. Derived from custodian.tenant_id during migration.';


--
-- Name: v_stock_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_stock_status AS
 SELECT w.warehouse_id,
    w.warehouse_name,
    w.warehouse_type,
    i.item_id,
    i.item_code,
    i.item_name,
    i.criticality_level,
    COALESCE(inv.usable_qty, (0)::numeric) AS available_stock,
    COALESCE(inv.reserved_qty, (0)::numeric) AS reserved_qty,
    COALESCE(i.min_stock_threshold, w.min_stock_threshold, (0)::numeric) AS min_threshold,
    (COALESCE(inv.usable_qty, (0)::numeric) - COALESCE(i.min_stock_threshold, w.min_stock_threshold, (0)::numeric)) AS surplus_qty,
    w.last_sync_dtime,
    w.sync_status,
        CASE
            WHEN (w.last_sync_dtime IS NULL) THEN 'UNKNOWN'::text
            WHEN (w.last_sync_dtime > (now() - '02:00:00'::interval)) THEN 'HIGH'::text
            WHEN (w.last_sync_dtime > (now() - '06:00:00'::interval)) THEN 'MEDIUM'::text
            ELSE 'LOW'::text
        END AS data_freshness
   FROM ((public.warehouse w
     CROSS JOIN public.item i)
     LEFT JOIN public.inventory inv ON (((inv.item_id = i.item_id) AND (inv.inventory_id = w.warehouse_id))))
  WHERE ((w.status_code = 'A'::bpchar) AND (i.status_code = 'A'::bpchar));


--
-- Name: VIEW v_stock_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_stock_status IS 'Real-time stock status by warehouse and item with freshness indicators';


--
-- Name: warehouse_sync_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.warehouse_sync_log (
    sync_id integer NOT NULL,
    warehouse_id integer NOT NULL,
    sync_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    sync_type character varying(20) DEFAULT 'AUTO'::character varying NOT NULL,
    sync_status character varying(10) NOT NULL,
    items_synced integer DEFAULT 0 NOT NULL,
    error_message text,
    triggered_by character varying(20),
    CONSTRAINT c_wsl_status CHECK (((sync_status)::text = ANY (ARRAY[('SUCCESS'::character varying)::text, ('PARTIAL'::character varying)::text, ('FAILED'::character varying)::text]))),
    CONSTRAINT c_wsl_type CHECK (((sync_type)::text = ANY (ARRAY[('AUTO'::character varying)::text, ('MANUAL'::character varying)::text, ('SCHEDULED'::character varying)::text])))
);


--
-- Name: TABLE warehouse_sync_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.warehouse_sync_log IS 'Log of warehouse data synchronization events for freshness tracking';


--
-- Name: warehouse_sync_log_sync_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.warehouse_sync_log ALTER COLUMN sync_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.warehouse_sync_log_sync_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: warehouse_sync_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.warehouse_sync_status (
    warehouse_id integer NOT NULL,
    last_sync_at timestamp(0) without time zone,
    sync_status character varying(20) DEFAULT 'UNKNOWN'::character varying,
    freshness_level character varying(10) DEFAULT 'UNKNOWN'::character varying,
    items_synced integer,
    sync_errors text,
    last_online_at timestamp(0) without time zone,
    create_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_dtime timestamp(0) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT warehouse_sync_status_freshness_level_check CHECK (((freshness_level)::text = ANY ((ARRAY['HIGH'::character varying, 'MEDIUM'::character varying, 'LOW'::character varying, 'STALE'::character varying, 'UNKNOWN'::character varying])::text[]))),
    CONSTRAINT warehouse_sync_status_sync_status_check CHECK (((sync_status)::text = ANY ((ARRAY['ONLINE'::character varying, 'SYNCING'::character varying, 'STALE'::character varying, 'OFFLINE'::character varying, 'UNKNOWN'::character varying])::text[])))
);


--
-- Name: TABLE warehouse_sync_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.warehouse_sync_status IS 'Tracks warehouse data freshness for offline/mobile sync scenarios';


--
-- Name: warehouse_warehouse_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.warehouse ALTER COLUMN warehouse_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.warehouse_warehouse_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: xfreturn; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.xfreturn (
    xfreturn_id integer NOT NULL,
    fr_inventory_id integer NOT NULL,
    to_inventory_id integer NOT NULL,
    return_date date DEFAULT CURRENT_DATE NOT NULL,
    reason_text character varying(255),
    status_code character(1) NOT NULL,
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone,
    verify_by_id character varying(20) NOT NULL,
    verify_dtime timestamp(0) without time zone,
    version_nbr integer NOT NULL,
    CONSTRAINT xfreturn_return_date_check CHECK ((return_date <= CURRENT_DATE)),
    CONSTRAINT xfreturn_status_code_check CHECK ((status_code = ANY (ARRAY['D'::bpchar, 'C'::bpchar, 'V'::bpchar])))
);


--
-- Name: xfreturn_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.xfreturn_item (
    xfreturn_id integer NOT NULL,
    inventory_id integer NOT NULL,
    item_id integer NOT NULL,
    usable_qty numeric(12,2) NOT NULL,
    defective_qty numeric(12,2) NOT NULL,
    expired_qty numeric(12,2) NOT NULL,
    uom_code character varying(25) NOT NULL,
    reason_text character varying(255),
    create_by_id character varying(20) NOT NULL,
    create_dtime timestamp(0) without time zone NOT NULL,
    update_by_id character varying(20) NOT NULL,
    update_dtime timestamp(0) without time zone NOT NULL,
    version_nbr integer NOT NULL,
    CONSTRAINT xfreturn_item_defective_qty_check CHECK ((defective_qty >= 0.00)),
    CONSTRAINT xfreturn_item_expired_qty_check CHECK ((expired_qty >= 0.00)),
    CONSTRAINT xfreturn_item_usable_qty_check CHECK ((usable_qty >= 0.00))
);


--
-- Name: xfreturn_xfreturn_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.xfreturn_xfreturn_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: xfreturn_xfreturn_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.xfreturn_xfreturn_id_seq OWNED BY public.xfreturn.xfreturn_id;


--
-- Name: data_sharing_agreement agreement_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sharing_agreement ALTER COLUMN agreement_id SET DEFAULT nextval('public.data_sharing_agreement_agreement_id_seq'::regclass);


--
-- Name: distribution_package id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package ALTER COLUMN id SET DEFAULT nextval('public.distribution_package_id_seq'::regclass);


--
-- Name: distribution_package_item id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package_item ALTER COLUMN id SET DEFAULT nextval('public.distribution_package_item_id_seq'::regclass);


--
-- Name: event_phase phase_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase ALTER COLUMN phase_id SET DEFAULT nextval('public.event_phase_phase_id_seq'::regclass);


--
-- Name: notification id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification ALTER COLUMN id SET DEFAULT nextval('public.notification_id_seq'::regclass);


--
-- Name: role id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role ALTER COLUMN id SET DEFAULT nextval('public.role_id_seq'::regclass);


--
-- Name: tenant tenant_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant ALTER COLUMN tenant_id SET DEFAULT nextval('public.tenant_tenant_id_seq'::regclass);


--
-- Name: tenant_config config_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_config ALTER COLUMN config_id SET DEFAULT nextval('public.tenant_config_config_id_seq'::regclass);


--
-- Name: transaction id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction ALTER COLUMN id SET DEFAULT nextval('public.transaction_id_seq'::regclass);


--
-- Name: transfer_request id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_request ALTER COLUMN id SET DEFAULT nextval('public.transfer_request_id_seq'::regclass);


--
-- Name: user user_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."user" ALTER COLUMN user_id SET DEFAULT nextval('public.user_id_seq'::regclass);


--
-- Name: xfreturn xfreturn_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xfreturn ALTER COLUMN xfreturn_id SET DEFAULT nextval('public.xfreturn_xfreturn_id_seq'::regclass);


--
-- Name: agency_account_request_audit agency_account_request_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_account_request_audit
    ADD CONSTRAINT agency_account_request_audit_pkey PRIMARY KEY (audit_id);


--
-- Name: agency_account_request agency_account_request_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_account_request
    ADD CONSTRAINT agency_account_request_pkey PRIMARY KEY (request_id);


--
-- Name: agency agency_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency
    ADD CONSTRAINT agency_pkey PRIMARY KEY (agency_id);


--
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- Name: auth_user_groups auth_user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_pkey PRIMARY KEY (id);


--
-- Name: auth_user_groups auth_user_groups_user_id_group_id_94350c0c_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_group_id_94350c0c_uniq UNIQUE (user_id, group_id);


--
-- Name: auth_user auth_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_pkey PRIMARY KEY (id);


--
-- Name: auth_user_user_permissions auth_user_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_permission_id_14a6b632_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_permission_id_14a6b632_uniq UNIQUE (user_id, permission_id);


--
-- Name: auth_user auth_user_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_username_key UNIQUE (username);


--
-- Name: burn_rate_snapshot burn_rate_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.burn_rate_snapshot
    ADD CONSTRAINT burn_rate_snapshot_pkey PRIMARY KEY (snapshot_id);


--
-- Name: country country_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.country
    ADD CONSTRAINT country_pkey PRIMARY KEY (country_id);


--
-- Name: data_sharing_agreement data_sharing_agreement_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sharing_agreement
    ADD CONSTRAINT data_sharing_agreement_pkey PRIMARY KEY (agreement_id);


--
-- Name: dbintake_item dbintake_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake_item
    ADD CONSTRAINT dbintake_item_pkey PRIMARY KEY (reliefpkg_id, inventory_id, item_id);


--
-- Name: dbintake dbintake_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake
    ADD CONSTRAINT dbintake_pkey PRIMARY KEY (reliefpkg_id, inventory_id);


--
-- Name: distribution_package_item distribution_package_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package_item
    ADD CONSTRAINT distribution_package_item_pkey PRIMARY KEY (id);


--
-- Name: distribution_package distribution_package_package_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package
    ADD CONSTRAINT distribution_package_package_number_key UNIQUE (package_number);


--
-- Name: distribution_package distribution_package_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package
    ADD CONSTRAINT distribution_package_pkey PRIMARY KEY (id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- Name: donor donor_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donor
    ADD CONSTRAINT donor_pkey PRIMARY KEY (donor_id);


--
-- Name: event_phase_config event_phase_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase_config
    ADD CONSTRAINT event_phase_config_pkey PRIMARY KEY (config_id);


--
-- Name: event_phase_history event_phase_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase_history
    ADD CONSTRAINT event_phase_history_pkey PRIMARY KEY (history_id);


--
-- Name: event_phase event_phase_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase
    ADD CONSTRAINT event_phase_pkey PRIMARY KEY (phase_id);


--
-- Name: item_location item_location_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_location
    ADD CONSTRAINT item_location_pkey PRIMARY KEY (item_id, location_id);


--
-- Name: lead_time_config lead_time_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_time_config
    ADD CONSTRAINT lead_time_config_pkey PRIMARY KEY (config_id);


--
-- Name: location location_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location
    ADD CONSTRAINT location_pkey PRIMARY KEY (location_id);


--
-- Name: needs_list_audit needs_list_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_audit
    ADD CONSTRAINT needs_list_audit_pkey PRIMARY KEY (audit_id);


--
-- Name: needs_list_item needs_list_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_item
    ADD CONSTRAINT needs_list_item_pkey PRIMARY KEY (needs_list_item_id);


--
-- Name: needs_list needs_list_needs_list_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list
    ADD CONSTRAINT needs_list_needs_list_no_key UNIQUE (needs_list_no);


--
-- Name: needs_list needs_list_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list
    ADD CONSTRAINT needs_list_pkey PRIMARY KEY (needs_list_id);


--
-- Name: needs_list_workflow_metadata needs_list_workflow_metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_workflow_metadata
    ADD CONSTRAINT needs_list_workflow_metadata_pkey PRIMARY KEY (needs_list_id);


--
-- Name: notification notification_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_pkey PRIMARY KEY (id);


--
-- Name: parish parish_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parish
    ADD CONSTRAINT parish_pkey PRIMARY KEY (parish_code);


--
-- Name: permission permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permission
    ADD CONSTRAINT permission_pkey PRIMARY KEY (perm_id);


--
-- Name: itemcostdef pk_adnlitemcost; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.itemcostdef
    ADD CONSTRAINT pk_adnlitemcost PRIMARY KEY (cost_id);


--
-- Name: batchlocation pk_batchlocation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batchlocation
    ADD CONSTRAINT pk_batchlocation PRIMARY KEY (inventory_id, location_id, batch_id);


--
-- Name: currency pk_currency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.currency
    ADD CONSTRAINT pk_currency PRIMARY KEY (currency_code);


--
-- Name: currency_rate pk_currency_rate; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.currency_rate
    ADD CONSTRAINT pk_currency_rate PRIMARY KEY (currency_code, rate_date);


--
-- Name: custodian pk_custodian; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custodian
    ADD CONSTRAINT pk_custodian PRIMARY KEY (custodian_id);


--
-- Name: dnintake pk_dnintake; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dnintake
    ADD CONSTRAINT pk_dnintake PRIMARY KEY (donation_id, inventory_id);


--
-- Name: dnintake_item pk_dnintake_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dnintake_item
    ADD CONSTRAINT pk_dnintake_item PRIMARY KEY (donation_id, inventory_id, item_id, batch_no);


--
-- Name: donation pk_donation; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation
    ADD CONSTRAINT pk_donation PRIMARY KEY (donation_id);


--
-- Name: donation_doc pk_donation_doc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation_doc
    ADD CONSTRAINT pk_donation_doc PRIMARY KEY (document_id);


--
-- Name: donation_item pk_donation_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation_item
    ADD CONSTRAINT pk_donation_item PRIMARY KEY (donation_id, item_id);


--
-- Name: event pk_event; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT pk_event PRIMARY KEY (event_id);


--
-- Name: hadr_aid_movement_staging pk_hadr_aid_movement_staging; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hadr_aid_movement_staging
    ADD CONSTRAINT pk_hadr_aid_movement_staging PRIMARY KEY (staging_id);


--
-- Name: inventory pk_inventory; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT pk_inventory PRIMARY KEY (inventory_id, item_id);


--
-- Name: item pk_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT pk_item PRIMARY KEY (item_id);


--
-- Name: itembatch pk_itembatch; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.itembatch
    ADD CONSTRAINT pk_itembatch PRIMARY KEY (batch_id);


--
-- Name: itemcatg pk_itemcatg; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.itemcatg
    ADD CONSTRAINT pk_itemcatg PRIMARY KEY (category_id);


--
-- Name: reliefpkg_item pk_reliefpkg_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg_item
    ADD CONSTRAINT pk_reliefpkg_item PRIMARY KEY (reliefpkg_id, fr_inventory_id, batch_id, item_id);


--
-- Name: reliefrqst pk_reliefrqst; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst
    ADD CONSTRAINT pk_reliefrqst PRIMARY KEY (reliefrqst_id);


--
-- Name: reliefrqst_item pk_reliefrqst_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst_item
    ADD CONSTRAINT pk_reliefrqst_item PRIMARY KEY (reliefrqst_id, item_id);


--
-- Name: reliefrqst_status pk_reliefrqst_status; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst_status
    ADD CONSTRAINT pk_reliefrqst_status PRIMARY KEY (status_code);


--
-- Name: reliefrqstitem_status pk_reliefrqstitem_status; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqstitem_status
    ADD CONSTRAINT pk_reliefrqstitem_status PRIMARY KEY (status_code);


--
-- Name: role_permission pk_role_permission; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT pk_role_permission PRIMARY KEY (role_id, perm_id);


--
-- Name: rtintake pk_rtintake; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake
    ADD CONSTRAINT pk_rtintake PRIMARY KEY (xfreturn_id, inventory_id);


--
-- Name: rtintake_item pk_rtintake_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake_item
    ADD CONSTRAINT pk_rtintake_item PRIMARY KEY (xfreturn_id, inventory_id, item_id);


--
-- Name: transfer pk_transfer; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer
    ADD CONSTRAINT pk_transfer PRIMARY KEY (transfer_id);


--
-- Name: transfer_item pk_transfer_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_item
    ADD CONSTRAINT pk_transfer_item PRIMARY KEY (transfer_id, item_id, batch_id);


--
-- Name: unitofmeasure pk_unitofmeasure; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unitofmeasure
    ADD CONSTRAINT pk_unitofmeasure PRIMARY KEY (uom_code);


--
-- Name: xfreturn_item pk_xfreturn_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xfreturn_item
    ADD CONSTRAINT pk_xfreturn_item PRIMARY KEY (xfreturn_id, inventory_id, item_id);


--
-- Name: procurement_item procurement_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement_item
    ADD CONSTRAINT procurement_item_pkey PRIMARY KEY (procurement_item_id);


--
-- Name: procurement procurement_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement
    ADD CONSTRAINT procurement_pkey PRIMARY KEY (procurement_id);


--
-- Name: procurement procurement_procurement_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement
    ADD CONSTRAINT procurement_procurement_no_key UNIQUE (procurement_no);


--
-- Name: relief_request_fulfillment_lock relief_request_fulfillment_lock_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relief_request_fulfillment_lock
    ADD CONSTRAINT relief_request_fulfillment_lock_pkey PRIMARY KEY (reliefrqst_id);


--
-- Name: reliefpkg reliefpkg_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg
    ADD CONSTRAINT reliefpkg_pkey PRIMARY KEY (reliefpkg_id);


--
-- Name: role role_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_code_key UNIQUE (code);


--
-- Name: role role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_pkey PRIMARY KEY (id);


--
-- Name: supplier supplier_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier
    ADD CONSTRAINT supplier_pkey PRIMARY KEY (supplier_id);


--
-- Name: supplier supplier_supplier_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier
    ADD CONSTRAINT supplier_supplier_code_key UNIQUE (supplier_code);


--
-- Name: tenant_config tenant_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_config
    ADD CONSTRAINT tenant_config_pkey PRIMARY KEY (config_id);


--
-- Name: tenant_config tenant_config_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_config
    ADD CONSTRAINT tenant_config_unique UNIQUE (tenant_id, config_key, effective_date);


--
-- Name: tenant tenant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_pkey PRIMARY KEY (tenant_id);


--
-- Name: tenant_user tenant_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_user
    ADD CONSTRAINT tenant_user_pkey PRIMARY KEY (tenant_id, user_id);


--
-- Name: tenant_warehouse tenant_warehouse_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_warehouse
    ADD CONSTRAINT tenant_warehouse_pkey PRIMARY KEY (tenant_id, warehouse_id);


--
-- Name: transaction transaction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_pkey PRIMARY KEY (id);


--
-- Name: transfer_request transfer_request_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_request
    ADD CONSTRAINT transfer_request_pkey PRIMARY KEY (id);


--
-- Name: agency uk_agency_1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency
    ADD CONSTRAINT uk_agency_1 UNIQUE (agency_name);


--
-- Name: currency uk_currency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.currency
    ADD CONSTRAINT uk_currency UNIQUE (currency_name);


--
-- Name: custodian uk_custodian_1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custodian
    ADD CONSTRAINT uk_custodian_1 UNIQUE (custodian_name);


--
-- Name: donor uk_donor_1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donor
    ADD CONSTRAINT uk_donor_1 UNIQUE (donor_name);


--
-- Name: item uk_item_1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT uk_item_1 UNIQUE (item_code);


--
-- Name: item uk_item_2; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT uk_item_2 UNIQUE (item_name);


--
-- Name: item uk_item_3; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT uk_item_3 UNIQUE (sku_code);


--
-- Name: itemcatg uk_itemcatg_1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.itemcatg
    ADD CONSTRAINT uk_itemcatg_1 UNIQUE (category_code);


--
-- Name: itemcostdef uk_itemcostdef_1; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.itemcostdef
    ADD CONSTRAINT uk_itemcostdef_1 UNIQUE (cost_name);


--
-- Name: event_phase_config uq_event_phase; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase_config
    ADD CONSTRAINT uq_event_phase UNIQUE (event_id, phase);


--
-- Name: needs_list_item uq_needs_list_item; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_item
    ADD CONSTRAINT uq_needs_list_item UNIQUE (needs_list_id, item_id);


--
-- Name: permission uq_permission_resource_action; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.permission
    ADD CONSTRAINT uq_permission_resource_action UNIQUE (resource, action);


--
-- Name: user user_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_email_key UNIQUE (email);


--
-- Name: user user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_pkey PRIMARY KEY (user_id);


--
-- Name: user_role user_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_pkey PRIMARY KEY (user_id, role_id);


--
-- Name: user_warehouse user_warehouse_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_warehouse
    ADD CONSTRAINT user_warehouse_pkey PRIMARY KEY (user_id, warehouse_id);


--
-- Name: warehouse warehouse_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouse
    ADD CONSTRAINT warehouse_pkey PRIMARY KEY (warehouse_id);


--
-- Name: warehouse_sync_log warehouse_sync_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouse_sync_log
    ADD CONSTRAINT warehouse_sync_log_pkey PRIMARY KEY (sync_id);


--
-- Name: warehouse_sync_status warehouse_sync_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouse_sync_status
    ADD CONSTRAINT warehouse_sync_status_pkey PRIMARY KEY (warehouse_id);


--
-- Name: xfreturn xfreturn_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xfreturn
    ADD CONSTRAINT xfreturn_pkey PRIMARY KEY (xfreturn_id);


--
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- Name: auth_user_groups_group_id_97559544; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_groups_group_id_97559544 ON public.auth_user_groups USING btree (group_id);


--
-- Name: auth_user_groups_user_id_6a12ed8b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_groups_user_id_6a12ed8b ON public.auth_user_groups USING btree (user_id);


--
-- Name: auth_user_user_permissions_permission_id_1fbb5f2c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_user_permissions_permission_id_1fbb5f2c ON public.auth_user_user_permissions USING btree (permission_id);


--
-- Name: auth_user_user_permissions_user_id_a95ead1b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_user_permissions_user_id_a95ead1b ON public.auth_user_user_permissions USING btree (user_id);


--
-- Name: auth_user_username_6821ab7c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_username_6821ab7c_like ON public.auth_user USING btree (username varchar_pattern_ops);


--
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- Name: dk_aar_audit_req_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_aar_audit_req_time ON public.agency_account_request_audit USING btree (request_id, event_dtime);


--
-- Name: dk_aar_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_aar_status_created ON public.agency_account_request USING btree (status_code, created_at);


--
-- Name: dk_batchlocation_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_batchlocation_1 ON public.batchlocation USING btree (batch_id, location_id);


--
-- Name: dk_country; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_country ON public.country USING btree (currency_code);


--
-- Name: dk_dbintake_item_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_dbintake_item_1 ON public.dbintake_item USING btree (inventory_id, item_id);


--
-- Name: dk_dbintake_item_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_dbintake_item_2 ON public.dbintake_item USING btree (item_id);


--
-- Name: dk_dnintake_item_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_dnintake_item_1 ON public.dnintake_item USING btree (inventory_id, item_id);


--
-- Name: dk_dnintake_item_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_dnintake_item_2 ON public.dnintake_item USING btree (item_id);


--
-- Name: dk_inventory_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_inventory_1 ON public.inventory USING btree (item_id);


--
-- Name: dk_item_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_item_1 ON public.item USING btree (item_desc);


--
-- Name: dk_item_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_item_2 ON public.item USING btree (category_id);


--
-- Name: dk_item_3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_item_3 ON public.item USING btree (sku_code);


--
-- Name: dk_item_location_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_item_location_1 ON public.item_location USING btree (inventory_id, location_id);


--
-- Name: dk_itembatch_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_itembatch_1 ON public.itembatch USING btree (item_id, inventory_id);


--
-- Name: dk_itembatch_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_itembatch_2 ON public.itembatch USING btree (batch_no, inventory_id);


--
-- Name: dk_itembatch_3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_itembatch_3 ON public.itembatch USING btree (item_id, expiry_date) WHERE ((status_code = 'A'::bpchar) AND (expiry_date IS NOT NULL));


--
-- Name: dk_itembatch_4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_itembatch_4 ON public.itembatch USING btree (item_id, batch_date) WHERE (status_code = 'A'::bpchar);


--
-- Name: dk_location_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_location_1 ON public.location USING btree (inventory_id);


--
-- Name: dk_reliefpkg_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefpkg_1 ON public.reliefpkg USING btree (start_date);


--
-- Name: dk_reliefpkg_3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefpkg_3 ON public.reliefpkg USING btree (to_inventory_id);


--
-- Name: dk_reliefpkg_item_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefpkg_item_1 ON public.reliefpkg_item USING btree (fr_inventory_id, item_id);


--
-- Name: dk_reliefpkg_item_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefpkg_item_2 ON public.reliefpkg_item USING btree (item_id);


--
-- Name: dk_reliefpkg_item_3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefpkg_item_3 ON public.reliefpkg_item USING btree (batch_id);


--
-- Name: dk_reliefrqst_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefrqst_1 ON public.reliefrqst USING btree (agency_id, request_date);


--
-- Name: dk_reliefrqst_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefrqst_2 ON public.reliefrqst USING btree (request_date, status_code);


--
-- Name: dk_reliefrqst_3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefrqst_3 ON public.reliefrqst USING btree (status_code, urgency_ind);


--
-- Name: dk_reliefrqst_item_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_reliefrqst_item_2 ON public.reliefrqst_item USING btree (item_id, urgency_ind);


--
-- Name: dk_rtintake_item_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_rtintake_item_1 ON public.rtintake_item USING btree (inventory_id, item_id);


--
-- Name: dk_rtintake_item_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_rtintake_item_2 ON public.rtintake_item USING btree (item_id);


--
-- Name: dk_transfer_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_transfer_1 ON public.transfer USING btree (transfer_date);


--
-- Name: dk_transfer_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_transfer_2 ON public.transfer USING btree (fr_inventory_id);


--
-- Name: dk_transfer_3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_transfer_3 ON public.transfer USING btree (to_inventory_id);


--
-- Name: dk_user_agency_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_user_agency_id ON public."user" USING btree (agency_id);


--
-- Name: dk_xfreturn_1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_xfreturn_1 ON public.xfreturn USING btree (return_date);


--
-- Name: dk_xfreturn_2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_xfreturn_2 ON public.xfreturn USING btree (fr_inventory_id);


--
-- Name: dk_xfreturn_3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dk_xfreturn_3 ON public.xfreturn USING btree (to_inventory_id);


--
-- Name: idx_brs_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_brs_event ON public.burn_rate_snapshot USING btree (event_id);


--
-- Name: idx_brs_snapshot_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_brs_snapshot_date ON public.burn_rate_snapshot USING btree (snapshot_dtime);


--
-- Name: idx_brs_warehouse_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_brs_warehouse_item ON public.burn_rate_snapshot USING btree (warehouse_id, item_id);


--
-- Name: idx_currency_rate_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_currency_rate_code ON public.currency_rate USING btree (currency_code);


--
-- Name: idx_currency_rate_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_currency_rate_date ON public.currency_rate USING btree (rate_date DESC);


--
-- Name: idx_custodian_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_custodian_tenant ON public.custodian USING btree (tenant_id) WHERE (tenant_id IS NOT NULL);


--
-- Name: idx_data_sharing_from; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_sharing_from ON public.data_sharing_agreement USING btree (from_tenant_id);


--
-- Name: idx_data_sharing_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_sharing_to ON public.data_sharing_agreement USING btree (to_tenant_id);


--
-- Name: idx_distribution_package_agency; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distribution_package_agency ON public.distribution_package USING btree (recipient_agency_id);


--
-- Name: idx_distribution_package_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distribution_package_event ON public.distribution_package USING btree (event_id);


--
-- Name: idx_distribution_package_item_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distribution_package_item_item ON public.distribution_package_item USING btree (item_id);


--
-- Name: idx_distribution_package_item_package; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distribution_package_item_package ON public.distribution_package_item USING btree (package_id);


--
-- Name: idx_distribution_package_warehouse; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distribution_package_warehouse ON public.distribution_package USING btree (assigned_warehouse_id);


--
-- Name: idx_donation_doc_donation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_donation_doc_donation_id ON public.donation_doc USING btree (donation_id);


--
-- Name: idx_donation_doc_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_donation_doc_type ON public.donation_doc USING btree (document_type);


--
-- Name: idx_donation_status_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_donation_status_event ON public.donation USING btree (status_code, event_id);


--
-- Name: idx_event_phase_current; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_phase_current ON public.event_phase USING btree (is_current) WHERE (is_current = true);


--
-- Name: idx_event_phase_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_phase_event ON public.event_phase USING btree (event_id);


--
-- Name: idx_fulfillment_lock_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fulfillment_lock_expires ON public.relief_request_fulfillment_lock USING btree (expires_at) WHERE (expires_at IS NOT NULL);


--
-- Name: idx_fulfillment_lock_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fulfillment_lock_user ON public.relief_request_fulfillment_lock USING btree (fulfiller_user_id);


--
-- Name: idx_inventory_item_warehouse; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inventory_item_warehouse ON public.inventory USING btree (item_id);


--
-- Name: idx_itembatch_tst_safe_wh; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_itembatch_tst_safe_wh ON public.itembatch USING btree (inventory_id) WHERE ((inventory_id = ANY (ARRAY[1, 2, 3])) AND ((create_by_id)::text = 'TST_OP_SAFE'::text));


--
-- Name: idx_itemcatg_status_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_itemcatg_status_code ON public.itemcatg USING btree (status_code);


--
-- Name: idx_itemcostdef_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_itemcostdef_status ON public.itemcostdef USING btree (status_code);


--
-- Name: idx_itemcostdef_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_itemcostdef_type ON public.itemcostdef USING btree (cost_type);


--
-- Name: idx_ltc_default_per_horizon; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_ltc_default_per_horizon ON public.lead_time_config USING btree (horizon) WHERE (is_default = true);


--
-- Name: idx_needs_list_calc_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_needs_list_calc_date ON public.needs_list USING btree (calculation_dtime);


--
-- Name: idx_needs_list_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_needs_list_event ON public.needs_list USING btree (event_id);


--
-- Name: idx_needs_list_item_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_needs_list_item_item ON public.needs_list_item USING btree (item_id);


--
-- Name: idx_needs_list_item_needs_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_needs_list_item_needs_list ON public.needs_list_item USING btree (needs_list_id);


--
-- Name: idx_needs_list_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_needs_list_status ON public.needs_list USING btree (status_code);


--
-- Name: idx_needs_list_warehouse; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_needs_list_warehouse ON public.needs_list USING btree (warehouse_id);


--
-- Name: idx_nla_action_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nla_action_date ON public.needs_list_audit USING btree (action_dtime);


--
-- Name: idx_nla_needs_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nla_needs_list ON public.needs_list_audit USING btree (needs_list_id);


--
-- Name: idx_nli_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nli_item ON public.needs_list_item USING btree (item_id);


--
-- Name: idx_nli_needs_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nli_needs_list ON public.needs_list_item USING btree (needs_list_id);


--
-- Name: idx_nli_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nli_severity ON public.needs_list_item USING btree (severity_level);


--
-- Name: idx_notification_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_user_status ON public.notification USING btree (user_id, status, created_at);


--
-- Name: idx_notification_warehouse; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notification_warehouse ON public.notification USING btree (warehouse_id, created_at);


--
-- Name: idx_pi_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pi_item ON public.procurement_item USING btree (item_id);


--
-- Name: idx_pi_procurement; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pi_procurement ON public.procurement_item USING btree (procurement_id);


--
-- Name: idx_proc_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_proc_event ON public.procurement USING btree (event_id);


--
-- Name: idx_proc_needs_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_proc_needs_list ON public.procurement USING btree (needs_list_id);


--
-- Name: idx_proc_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_proc_status ON public.procurement USING btree (status_code);


--
-- Name: idx_proc_warehouse; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_proc_warehouse ON public.procurement USING btree (target_warehouse_id);


--
-- Name: idx_role_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_role_code ON public.role USING btree (code);


--
-- Name: idx_tenant_code_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_tenant_code_unique ON public.tenant USING btree (tenant_code);


--
-- Name: idx_tenant_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_status ON public.tenant USING btree (status_code);


--
-- Name: idx_tenant_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_type ON public.tenant USING btree (tenant_type);


--
-- Name: idx_tenant_user_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_user_user ON public.tenant_user USING btree (user_id);


--
-- Name: idx_tenant_warehouse_warehouse; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_warehouse_warehouse ON public.tenant_warehouse USING btree (warehouse_id);


--
-- Name: idx_transfer_item_batch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transfer_item_batch ON public.transfer_item USING btree (inventory_id, batch_id);


--
-- Name: idx_transfer_item_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transfer_item_item ON public.transfer_item USING btree (item_id);


--
-- Name: idx_transfer_status_dest; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_transfer_status_dest ON public.transfer USING btree (status_code, to_inventory_id);


--
-- Name: idx_warehouse_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_warehouse_tenant ON public.warehouse USING btree (tenant_id) WHERE (tenant_id IS NOT NULL);


--
-- Name: idx_wsl_sync_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wsl_sync_date ON public.warehouse_sync_log USING btree (sync_dtime);


--
-- Name: idx_wsl_warehouse; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wsl_warehouse ON public.warehouse_sync_log USING btree (warehouse_id);


--
-- Name: ix_role_permission_perm_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permission_perm_id ON public.role_permission USING btree (perm_id);


--
-- Name: ix_role_permission_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_permission_role_id ON public.role_permission USING btree (role_id);


--
-- Name: ix_user_role_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_role_role_id ON public.user_role USING btree (role_id);


--
-- Name: ix_user_role_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_role_user_id ON public.user_role USING btree (user_id);


--
-- Name: uk_aar_active_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_aar_active_email ON public.agency_account_request USING btree (lower((contact_email)::text)) WHERE (status_code = ANY (ARRAY['S'::bpchar, 'R'::bpchar]));


--
-- Name: uk_country; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_country ON public.country USING btree (country_name);


--
-- Name: uk_inventory_1; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_inventory_1 ON public.inventory USING btree (item_id, inventory_id) WHERE (usable_qty > 0.00);


--
-- Name: uk_itembatch_1; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_itembatch_1 ON public.itembatch USING btree (inventory_id, batch_no, item_id);


--
-- Name: uk_itembatch_inventory_batch; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_itembatch_inventory_batch ON public.itembatch USING btree (inventory_id, batch_id);


--
-- Name: uk_itembatch_inventory_batch_item; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_itembatch_inventory_batch_item ON public.itembatch USING btree (inventory_id, batch_id, item_id);


--
-- Name: uk_user_username; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uk_user_username ON public."user" USING btree (username);


--
-- Name: agency_account_request trg_aar_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_aar_set_updated_at BEFORE UPDATE ON public.agency_account_request FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: event trg_event_phase_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_event_phase_change AFTER UPDATE OF current_phase ON public.event FOR EACH ROW EXECUTE FUNCTION public.log_event_phase_change();


--
-- Name: needs_list_item trg_needs_list_item_update_dtime; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_needs_list_item_update_dtime BEFORE UPDATE ON public.needs_list_item FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: needs_list trg_needs_list_update_dtime; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_needs_list_update_dtime BEFORE UPDATE ON public.needs_list FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: tenant_config trg_tenant_config_update_dtime; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_tenant_config_update_dtime BEFORE UPDATE ON public.tenant_config FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: tenant trg_tenant_update_dtime; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_tenant_update_dtime BEFORE UPDATE ON public.tenant FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: user trg_user_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_user_set_updated_at BEFORE UPDATE ON public."user" FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: warehouse trg_warehouse_sync_status; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_warehouse_sync_status BEFORE INSERT OR UPDATE OF last_sync_dtime ON public.warehouse FOR EACH ROW EXECUTE FUNCTION public.update_warehouse_sync_status();


--
-- Name: agency agency_ineligible_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency
    ADD CONSTRAINT agency_ineligible_event_id_fkey FOREIGN KEY (ineligible_event_id) REFERENCES public.event(event_id);


--
-- Name: agency agency_parish_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency
    ADD CONSTRAINT agency_parish_code_fkey FOREIGN KEY (parish_code) REFERENCES public.parish(parish_code);


--
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_groups auth_user_groups_group_id_97559544_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_group_id_97559544_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_groups auth_user_groups_user_id_6a12ed8b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_6a12ed8b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_user_permissions auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: burn_rate_snapshot burn_rate_snapshot_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.burn_rate_snapshot
    ADD CONSTRAINT burn_rate_snapshot_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: burn_rate_snapshot burn_rate_snapshot_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.burn_rate_snapshot
    ADD CONSTRAINT burn_rate_snapshot_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: burn_rate_snapshot burn_rate_snapshot_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.burn_rate_snapshot
    ADD CONSTRAINT burn_rate_snapshot_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: custodian custodian_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custodian
    ADD CONSTRAINT custodian_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id);


--
-- Name: data_sharing_agreement data_sharing_agreement_approved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sharing_agreement
    ADD CONSTRAINT data_sharing_agreement_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public."user"(user_id);


--
-- Name: data_sharing_agreement data_sharing_agreement_from_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sharing_agreement
    ADD CONSTRAINT data_sharing_agreement_from_tenant_id_fkey FOREIGN KEY (from_tenant_id) REFERENCES public.tenant(tenant_id);


--
-- Name: data_sharing_agreement data_sharing_agreement_to_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_sharing_agreement
    ADD CONSTRAINT data_sharing_agreement_to_tenant_id_fkey FOREIGN KEY (to_tenant_id) REFERENCES public.tenant(tenant_id);


--
-- Name: dbintake_item dbintake_item_location1_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake_item
    ADD CONSTRAINT dbintake_item_location1_id_fkey FOREIGN KEY (location1_id) REFERENCES public.location(location_id);


--
-- Name: dbintake_item dbintake_item_location2_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake_item
    ADD CONSTRAINT dbintake_item_location2_id_fkey FOREIGN KEY (location2_id) REFERENCES public.location(location_id);


--
-- Name: dbintake_item dbintake_item_location3_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake_item
    ADD CONSTRAINT dbintake_item_location3_id_fkey FOREIGN KEY (location3_id) REFERENCES public.location(location_id);


--
-- Name: dbintake_item dbintake_item_reliefpkg_id_inventory_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake_item
    ADD CONSTRAINT dbintake_item_reliefpkg_id_inventory_id_fkey FOREIGN KEY (reliefpkg_id, inventory_id) REFERENCES public.dbintake(reliefpkg_id, inventory_id);


--
-- Name: dbintake_item dbintake_item_uom_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake_item
    ADD CONSTRAINT dbintake_item_uom_code_fkey FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: dbintake dbintake_reliefpkg_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake
    ADD CONSTRAINT dbintake_reliefpkg_id_fkey FOREIGN KEY (reliefpkg_id) REFERENCES public.reliefpkg(reliefpkg_id);


--
-- Name: distribution_package distribution_package_assigned_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package
    ADD CONSTRAINT distribution_package_assigned_warehouse_id_fkey FOREIGN KEY (assigned_warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: distribution_package distribution_package_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package
    ADD CONSTRAINT distribution_package_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: distribution_package_item distribution_package_item_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package_item
    ADD CONSTRAINT distribution_package_item_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: distribution_package_item distribution_package_item_package_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package_item
    ADD CONSTRAINT distribution_package_item_package_id_fkey FOREIGN KEY (package_id) REFERENCES public.distribution_package(id) ON DELETE CASCADE;


--
-- Name: distribution_package distribution_package_recipient_agency_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distribution_package
    ADD CONSTRAINT distribution_package_recipient_agency_id_fkey FOREIGN KEY (recipient_agency_id) REFERENCES public.agency(agency_id);


--
-- Name: donor donor_country_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donor
    ADD CONSTRAINT donor_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.country(country_id);


--
-- Name: event_phase_config event_phase_config_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase_config
    ADD CONSTRAINT event_phase_config_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: event_phase event_phase_ended_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase
    ADD CONSTRAINT event_phase_ended_by_fkey FOREIGN KEY (ended_by) REFERENCES public."user"(user_id);


--
-- Name: event_phase event_phase_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase
    ADD CONSTRAINT event_phase_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: event_phase_history event_phase_history_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase_history
    ADD CONSTRAINT event_phase_history_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: event_phase event_phase_started_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_phase
    ADD CONSTRAINT event_phase_started_by_fkey FOREIGN KEY (started_by) REFERENCES public."user"(user_id);


--
-- Name: agency_account_request_audit fk_aar_actor; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_account_request_audit
    ADD CONSTRAINT fk_aar_actor FOREIGN KEY (actor_user_id) REFERENCES public."user"(user_id);


--
-- Name: agency_account_request fk_aar_agency; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_account_request
    ADD CONSTRAINT fk_aar_agency FOREIGN KEY (agency_id) REFERENCES public.agency(agency_id);


--
-- Name: agency_account_request_audit fk_aar_audit_req; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_account_request_audit
    ADD CONSTRAINT fk_aar_audit_req FOREIGN KEY (request_id) REFERENCES public.agency_account_request(request_id);


--
-- Name: agency_account_request fk_aar_created_by; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_account_request
    ADD CONSTRAINT fk_aar_created_by FOREIGN KEY (created_by_id) REFERENCES public."user"(user_id);


--
-- Name: agency_account_request fk_aar_updated_by; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_account_request
    ADD CONSTRAINT fk_aar_updated_by FOREIGN KEY (updated_by_id) REFERENCES public."user"(user_id);


--
-- Name: agency_account_request fk_aar_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency_account_request
    ADD CONSTRAINT fk_aar_user FOREIGN KEY (user_id) REFERENCES public."user"(user_id);


--
-- Name: agency fk_agency_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agency
    ADD CONSTRAINT fk_agency_warehouse FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: batchlocation fk_batchlocation_inventory; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batchlocation
    ADD CONSTRAINT fk_batchlocation_inventory FOREIGN KEY (inventory_id, batch_id) REFERENCES public.itembatch(inventory_id, batch_id);


--
-- Name: batchlocation fk_batchlocation_itembatch; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batchlocation
    ADD CONSTRAINT fk_batchlocation_itembatch FOREIGN KEY (batch_id) REFERENCES public.itembatch(batch_id);


--
-- Name: batchlocation fk_batchlocation_location; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batchlocation
    ADD CONSTRAINT fk_batchlocation_location FOREIGN KEY (location_id) REFERENCES public.location(location_id);


--
-- Name: batchlocation fk_batchlocation_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.batchlocation
    ADD CONSTRAINT fk_batchlocation_warehouse FOREIGN KEY (inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: country fk_country_currency; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.country
    ADD CONSTRAINT fk_country_currency FOREIGN KEY (currency_code) REFERENCES public.currency(currency_code);


--
-- Name: custodian fk_custodian_parish; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.custodian
    ADD CONSTRAINT fk_custodian_parish FOREIGN KEY (parish_code) REFERENCES public.parish(parish_code);


--
-- Name: dbintake fk_dbintake_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dbintake
    ADD CONSTRAINT fk_dbintake_warehouse FOREIGN KEY (inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: dnintake fk_dnintake_donation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dnintake
    ADD CONSTRAINT fk_dnintake_donation FOREIGN KEY (donation_id) REFERENCES public.donation(donation_id);


--
-- Name: dnintake_item fk_dnintake_item_donation_item; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dnintake_item
    ADD CONSTRAINT fk_dnintake_item_donation_item FOREIGN KEY (donation_id, item_id) REFERENCES public.donation_item(donation_id, item_id);


--
-- Name: dnintake_item fk_dnintake_item_intake; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dnintake_item
    ADD CONSTRAINT fk_dnintake_item_intake FOREIGN KEY (donation_id, inventory_id) REFERENCES public.dnintake(donation_id, inventory_id);


--
-- Name: dnintake_item fk_dnintake_item_unitofmeasure; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dnintake_item
    ADD CONSTRAINT fk_dnintake_item_unitofmeasure FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: dnintake fk_dnintake_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dnintake
    ADD CONSTRAINT fk_dnintake_warehouse FOREIGN KEY (inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: donation fk_donation_country; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation
    ADD CONSTRAINT fk_donation_country FOREIGN KEY (origin_country_id) REFERENCES public.country(country_id);


--
-- Name: donation fk_donation_custodian; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation
    ADD CONSTRAINT fk_donation_custodian FOREIGN KEY (custodian_id) REFERENCES public.custodian(custodian_id);


--
-- Name: donation_doc fk_donation_doc_donation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation_doc
    ADD CONSTRAINT fk_donation_doc_donation FOREIGN KEY (donation_id) REFERENCES public.donation(donation_id);


--
-- Name: donation fk_donation_donor; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation
    ADD CONSTRAINT fk_donation_donor FOREIGN KEY (donor_id) REFERENCES public.donor(donor_id);


--
-- Name: donation fk_donation_event; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation
    ADD CONSTRAINT fk_donation_event FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: donation_item fk_donation_item_currency; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation_item
    ADD CONSTRAINT fk_donation_item_currency FOREIGN KEY (currency_code) REFERENCES public.currency(currency_code);


--
-- Name: donation_item fk_donation_item_donation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation_item
    ADD CONSTRAINT fk_donation_item_donation FOREIGN KEY (donation_id) REFERENCES public.donation(donation_id);


--
-- Name: donation_item fk_donation_item_item; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation_item
    ADD CONSTRAINT fk_donation_item_item FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: donation_item fk_donation_item_unitofmeasure; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.donation_item
    ADD CONSTRAINT fk_donation_item_unitofmeasure FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: inventory fk_inventory_item; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT fk_inventory_item FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: inventory fk_inventory_unitofmeasure; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT fk_inventory_unitofmeasure FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: inventory fk_inventory_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT fk_inventory_warehouse FOREIGN KEY (inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: item fk_item_itemcatg; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT fk_item_itemcatg FOREIGN KEY (category_id) REFERENCES public.itemcatg(category_id);


--
-- Name: item_location fk_item_location_inventory; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_location
    ADD CONSTRAINT fk_item_location_inventory FOREIGN KEY (inventory_id, item_id) REFERENCES public.inventory(inventory_id, item_id);


--
-- Name: item fk_item_unitofmeasure; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT fk_item_unitofmeasure FOREIGN KEY (default_uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: itembatch fk_itembatch_item; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.itembatch
    ADD CONSTRAINT fk_itembatch_item FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: itembatch fk_itembatch_unitofmeasure; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.itembatch
    ADD CONSTRAINT fk_itembatch_unitofmeasure FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: itembatch fk_itembatch_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.itembatch
    ADD CONSTRAINT fk_itembatch_warehouse FOREIGN KEY (inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: location fk_location_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.location
    ADD CONSTRAINT fk_location_warehouse FOREIGN KEY (inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: procurement fk_procurement_supplier; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement
    ADD CONSTRAINT fk_procurement_supplier FOREIGN KEY (supplier_id) REFERENCES public.supplier(supplier_id);


--
-- Name: reliefpkg fk_reliefpkg_agency; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg
    ADD CONSTRAINT fk_reliefpkg_agency FOREIGN KEY (agency_id) REFERENCES public.agency(agency_id);


--
-- Name: reliefpkg fk_reliefpkg_event; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg
    ADD CONSTRAINT fk_reliefpkg_event FOREIGN KEY (eligible_event_id) REFERENCES public.event(event_id);


--
-- Name: reliefpkg_item fk_reliefpkg_item_itembatch; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg_item
    ADD CONSTRAINT fk_reliefpkg_item_itembatch FOREIGN KEY (fr_inventory_id, batch_id, item_id) REFERENCES public.itembatch(inventory_id, batch_id, item_id);


--
-- Name: reliefpkg_item fk_reliefpkg_item_reliefpkg; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg_item
    ADD CONSTRAINT fk_reliefpkg_item_reliefpkg FOREIGN KEY (reliefpkg_id) REFERENCES public.reliefpkg(reliefpkg_id);


--
-- Name: reliefpkg_item fk_reliefpkg_item_unitofmeasure; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg_item
    ADD CONSTRAINT fk_reliefpkg_item_unitofmeasure FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: reliefpkg fk_reliefpkg_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg
    ADD CONSTRAINT fk_reliefpkg_warehouse FOREIGN KEY (to_inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: reliefrqst fk_reliefrqst_agency; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst
    ADD CONSTRAINT fk_reliefrqst_agency FOREIGN KEY (agency_id) REFERENCES public.agency(agency_id);


--
-- Name: reliefrqst fk_reliefrqst_event; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst
    ADD CONSTRAINT fk_reliefrqst_event FOREIGN KEY (eligible_event_id) REFERENCES public.event(event_id);


--
-- Name: reliefrqst_item fk_reliefrqst_item_item; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst_item
    ADD CONSTRAINT fk_reliefrqst_item_item FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: reliefrqst_item fk_reliefrqst_item_reliefrqst; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst_item
    ADD CONSTRAINT fk_reliefrqst_item_reliefrqst FOREIGN KEY (reliefrqst_id) REFERENCES public.reliefrqst(reliefrqst_id);


--
-- Name: reliefrqst_item fk_reliefrqst_item_reliefrqstitem_status; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst_item
    ADD CONSTRAINT fk_reliefrqst_item_reliefrqstitem_status FOREIGN KEY (status_code) REFERENCES public.reliefrqstitem_status(status_code);


--
-- Name: reliefrqst fk_reliefrqst_reliefrqst_status; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefrqst
    ADD CONSTRAINT fk_reliefrqst_reliefrqst_status FOREIGN KEY (status_code) REFERENCES public.reliefrqst_status(status_code);


--
-- Name: role_permission fk_role_permission_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT fk_role_permission_perm FOREIGN KEY (perm_id) REFERENCES public.permission(perm_id);


--
-- Name: role_permission fk_role_permission_role; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT fk_role_permission_role FOREIGN KEY (role_id) REFERENCES public.role(id);


--
-- Name: rtintake_item fk_rtintake_item_intake; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake_item
    ADD CONSTRAINT fk_rtintake_item_intake FOREIGN KEY (xfreturn_id, inventory_id) REFERENCES public.rtintake(xfreturn_id, inventory_id);


--
-- Name: rtintake fk_rtintake_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake
    ADD CONSTRAINT fk_rtintake_warehouse FOREIGN KEY (inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: transfer fk_transfer_event; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer
    ADD CONSTRAINT fk_transfer_event FOREIGN KEY (eligible_event_id) REFERENCES public.event(event_id);


--
-- Name: transfer_item fk_transfer_item_batch; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_item
    ADD CONSTRAINT fk_transfer_item_batch FOREIGN KEY (inventory_id, batch_id) REFERENCES public.itembatch(inventory_id, batch_id);


--
-- Name: transfer_item fk_transfer_item_inventory; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_item
    ADD CONSTRAINT fk_transfer_item_inventory FOREIGN KEY (inventory_id, item_id) REFERENCES public.inventory(inventory_id, item_id);


--
-- Name: transfer_item fk_transfer_item_item; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_item
    ADD CONSTRAINT fk_transfer_item_item FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: transfer_item fk_transfer_item_transfer; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_item
    ADD CONSTRAINT fk_transfer_item_transfer FOREIGN KEY (transfer_id) REFERENCES public.transfer(transfer_id) ON DELETE CASCADE;


--
-- Name: transfer_item fk_transfer_item_uom; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_item
    ADD CONSTRAINT fk_transfer_item_uom FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: transfer fk_transfer_needs_list; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer
    ADD CONSTRAINT fk_transfer_needs_list FOREIGN KEY (needs_list_id) REFERENCES public.needs_list(needs_list_id);


--
-- Name: transfer fk_transfer_warehouse1; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer
    ADD CONSTRAINT fk_transfer_warehouse1 FOREIGN KEY (fr_inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: transfer fk_transfer_warehouse2; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer
    ADD CONSTRAINT fk_transfer_warehouse2 FOREIGN KEY (to_inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: xfreturn fk_xfreturn_fr_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xfreturn
    ADD CONSTRAINT fk_xfreturn_fr_warehouse FOREIGN KEY (fr_inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: xfreturn_item fk_xfreturn_item_inventory; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xfreturn_item
    ADD CONSTRAINT fk_xfreturn_item_inventory FOREIGN KEY (inventory_id, item_id) REFERENCES public.inventory(inventory_id, item_id);


--
-- Name: xfreturn fk_xfreturn_to_warehouse; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xfreturn
    ADD CONSTRAINT fk_xfreturn_to_warehouse FOREIGN KEY (to_inventory_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: item_location item_location_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_location
    ADD CONSTRAINT item_location_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.location(location_id);


--
-- Name: lead_time_config lead_time_config_from_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_time_config
    ADD CONSTRAINT lead_time_config_from_warehouse_id_fkey FOREIGN KEY (from_warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: lead_time_config lead_time_config_supplier_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_time_config
    ADD CONSTRAINT lead_time_config_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.supplier(supplier_id);


--
-- Name: lead_time_config lead_time_config_to_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_time_config
    ADD CONSTRAINT lead_time_config_to_warehouse_id_fkey FOREIGN KEY (to_warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: needs_list_audit needs_list_audit_needs_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_audit
    ADD CONSTRAINT needs_list_audit_needs_list_id_fkey FOREIGN KEY (needs_list_id) REFERENCES public.needs_list(needs_list_id);


--
-- Name: needs_list_audit needs_list_audit_needs_list_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_audit
    ADD CONSTRAINT needs_list_audit_needs_list_item_id_fkey FOREIGN KEY (needs_list_item_id) REFERENCES public.needs_list_item(needs_list_item_id);


--
-- Name: needs_list needs_list_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list
    ADD CONSTRAINT needs_list_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: needs_list_item needs_list_item_horizon_a_source_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_item
    ADD CONSTRAINT needs_list_item_horizon_a_source_warehouse_id_fkey FOREIGN KEY (horizon_a_source_warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: needs_list_item needs_list_item_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_item
    ADD CONSTRAINT needs_list_item_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: needs_list_item needs_list_item_needs_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_item
    ADD CONSTRAINT needs_list_item_needs_list_id_fkey FOREIGN KEY (needs_list_id) REFERENCES public.needs_list(needs_list_id) ON DELETE CASCADE;


--
-- Name: needs_list needs_list_superseded_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list
    ADD CONSTRAINT needs_list_superseded_by_id_fkey FOREIGN KEY (superseded_by_id) REFERENCES public.needs_list(needs_list_id);


--
-- Name: needs_list needs_list_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list
    ADD CONSTRAINT needs_list_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: needs_list_workflow_metadata needs_list_workflow_metadata_needs_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.needs_list_workflow_metadata
    ADD CONSTRAINT needs_list_workflow_metadata_needs_list_id_fkey FOREIGN KEY (needs_list_id) REFERENCES public.needs_list(needs_list_id) ON DELETE CASCADE;


--
-- Name: notification notification_reliefrqst_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_reliefrqst_id_fkey FOREIGN KEY (reliefrqst_id) REFERENCES public.reliefrqst(reliefrqst_id);


--
-- Name: notification notification_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(user_id);


--
-- Name: notification notification_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: procurement procurement_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement
    ADD CONSTRAINT procurement_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: procurement_item procurement_item_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement_item
    ADD CONSTRAINT procurement_item_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: procurement_item procurement_item_needs_list_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement_item
    ADD CONSTRAINT procurement_item_needs_list_item_id_fkey FOREIGN KEY (needs_list_item_id) REFERENCES public.needs_list_item(needs_list_item_id);


--
-- Name: procurement_item procurement_item_procurement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement_item
    ADD CONSTRAINT procurement_item_procurement_id_fkey FOREIGN KEY (procurement_id) REFERENCES public.procurement(procurement_id) ON DELETE CASCADE;


--
-- Name: procurement procurement_needs_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement
    ADD CONSTRAINT procurement_needs_list_id_fkey FOREIGN KEY (needs_list_id) REFERENCES public.needs_list(needs_list_id);


--
-- Name: procurement procurement_target_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.procurement
    ADD CONSTRAINT procurement_target_warehouse_id_fkey FOREIGN KEY (target_warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: relief_request_fulfillment_lock relief_request_fulfillment_lock_fulfiller_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relief_request_fulfillment_lock
    ADD CONSTRAINT relief_request_fulfillment_lock_fulfiller_user_id_fkey FOREIGN KEY (fulfiller_user_id) REFERENCES public."user"(user_id) ON DELETE CASCADE;


--
-- Name: relief_request_fulfillment_lock relief_request_fulfillment_lock_reliefrqst_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relief_request_fulfillment_lock
    ADD CONSTRAINT relief_request_fulfillment_lock_reliefrqst_id_fkey FOREIGN KEY (reliefrqst_id) REFERENCES public.reliefrqst(reliefrqst_id) ON DELETE CASCADE;


--
-- Name: reliefpkg reliefpkg_reliefrqst_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reliefpkg
    ADD CONSTRAINT reliefpkg_reliefrqst_id_fkey FOREIGN KEY (reliefrqst_id) REFERENCES public.reliefrqst(reliefrqst_id);


--
-- Name: rtintake_item rtintake_item_location1_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake_item
    ADD CONSTRAINT rtintake_item_location1_id_fkey FOREIGN KEY (location1_id) REFERENCES public.location(location_id);


--
-- Name: rtintake_item rtintake_item_location2_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake_item
    ADD CONSTRAINT rtintake_item_location2_id_fkey FOREIGN KEY (location2_id) REFERENCES public.location(location_id);


--
-- Name: rtintake_item rtintake_item_location3_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake_item
    ADD CONSTRAINT rtintake_item_location3_id_fkey FOREIGN KEY (location3_id) REFERENCES public.location(location_id);


--
-- Name: rtintake_item rtintake_item_uom_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake_item
    ADD CONSTRAINT rtintake_item_uom_code_fkey FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: rtintake rtintake_xfreturn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rtintake
    ADD CONSTRAINT rtintake_xfreturn_id_fkey FOREIGN KEY (xfreturn_id) REFERENCES public.xfreturn(xfreturn_id);


--
-- Name: supplier supplier_country_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.supplier
    ADD CONSTRAINT supplier_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.country(country_id);


--
-- Name: tenant_config tenant_config_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_config
    ADD CONSTRAINT tenant_config_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: tenant tenant_parent_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_parent_tenant_id_fkey FOREIGN KEY (parent_tenant_id) REFERENCES public.tenant(tenant_id);


--
-- Name: tenant tenant_parish_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_parish_code_fkey FOREIGN KEY (parish_code) REFERENCES public.parish(parish_code);


--
-- Name: tenant_user tenant_user_assigned_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_user
    ADD CONSTRAINT tenant_user_assigned_by_fkey FOREIGN KEY (assigned_by) REFERENCES public."user"(user_id);


--
-- Name: tenant_user tenant_user_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_user
    ADD CONSTRAINT tenant_user_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: tenant_user tenant_user_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_user
    ADD CONSTRAINT tenant_user_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(user_id) ON DELETE CASCADE;


--
-- Name: tenant_warehouse tenant_warehouse_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_warehouse
    ADD CONSTRAINT tenant_warehouse_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: tenant_warehouse tenant_warehouse_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_warehouse
    ADD CONSTRAINT tenant_warehouse_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id) ON DELETE CASCADE;


--
-- Name: transaction transaction_donor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_donor_id_fkey FOREIGN KEY (donor_id) REFERENCES public.donor(donor_id);


--
-- Name: transaction transaction_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(event_id);


--
-- Name: transaction transaction_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: transaction transaction_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transaction
    ADD CONSTRAINT transaction_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: transfer_request transfer_request_from_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_request
    ADD CONSTRAINT transfer_request_from_warehouse_id_fkey FOREIGN KEY (from_warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: transfer_request transfer_request_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_request
    ADD CONSTRAINT transfer_request_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(item_id);


--
-- Name: transfer_request transfer_request_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_request
    ADD CONSTRAINT transfer_request_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public."user"(user_id);


--
-- Name: transfer_request transfer_request_reviewed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_request
    ADD CONSTRAINT transfer_request_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public."user"(user_id);


--
-- Name: transfer_request transfer_request_to_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.transfer_request
    ADD CONSTRAINT transfer_request_to_warehouse_id_fkey FOREIGN KEY (to_warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: user user_agency_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_agency_id_fkey FOREIGN KEY (agency_id) REFERENCES public.agency(agency_id);


--
-- Name: user user_assigned_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_assigned_warehouse_id_fkey FOREIGN KEY (assigned_warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: user_role user_role_assigned_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_assigned_by_fkey FOREIGN KEY (assigned_by) REFERENCES public."user"(user_id);


--
-- Name: user_role user_role_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id) ON DELETE CASCADE;


--
-- Name: user_role user_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(user_id) ON DELETE CASCADE;


--
-- Name: user_warehouse user_warehouse_assigned_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_warehouse
    ADD CONSTRAINT user_warehouse_assigned_by_fkey FOREIGN KEY (assigned_by) REFERENCES public."user"(user_id);


--
-- Name: user_warehouse user_warehouse_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_warehouse
    ADD CONSTRAINT user_warehouse_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(user_id) ON DELETE CASCADE;


--
-- Name: user_warehouse user_warehouse_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_warehouse
    ADD CONSTRAINT user_warehouse_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id) ON DELETE CASCADE;


--
-- Name: warehouse warehouse_custodian_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouse
    ADD CONSTRAINT warehouse_custodian_id_fkey FOREIGN KEY (custodian_id) REFERENCES public.custodian(custodian_id);


--
-- Name: warehouse warehouse_parish_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouse
    ADD CONSTRAINT warehouse_parish_code_fkey FOREIGN KEY (parish_code) REFERENCES public.parish(parish_code);


--
-- Name: warehouse_sync_log warehouse_sync_log_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouse_sync_log
    ADD CONSTRAINT warehouse_sync_log_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: warehouse_sync_status warehouse_sync_status_warehouse_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouse_sync_status
    ADD CONSTRAINT warehouse_sync_status_warehouse_id_fkey FOREIGN KEY (warehouse_id) REFERENCES public.warehouse(warehouse_id);


--
-- Name: warehouse warehouse_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warehouse
    ADD CONSTRAINT warehouse_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id);


--
-- Name: xfreturn_item xfreturn_item_uom_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xfreturn_item
    ADD CONSTRAINT xfreturn_item_uom_code_fkey FOREIGN KEY (uom_code) REFERENCES public.unitofmeasure(uom_code);


--
-- Name: xfreturn_item xfreturn_item_xfreturn_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.xfreturn_item
    ADD CONSTRAINT xfreturn_item_xfreturn_id_fkey FOREIGN KEY (xfreturn_id) REFERENCES public.xfreturn(xfreturn_id);


--
-- PostgreSQL database dump complete
--

\unrestrict yygVar3AOxMLUhsEWJXVXixcm0OI8hDdIwITbt25DPlYZlJ5BD6ko6bCYUfbKXL

