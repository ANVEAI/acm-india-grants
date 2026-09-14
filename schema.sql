--
-- Schema of record for the ACM India Grants portal.
--
-- Structure ONLY. Every COPY block from the source dump has been removed:
-- APPLICATIONS, USERS (which carry MD5 password hashes), REVIEWS,
-- FINAL_APPROVALS and django_session all contain live data and applicant
-- personal information, which must not enter version control.
--
-- Regenerate with:  pg_dump --schema-only
-- Live data lives in Cloud SQL (instance stg-db, database student_travel_grant).
--
--
-- PostgreSQL database dump
--

-- Dumped from database version 17.5
-- Dumped by pg_dump version 17.5

-- Started on 2026-08-05 11:45:33

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 220 (class 1259 OID 21035)
-- Name: APPLICATIONS; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public."APPLICATIONS" (
    "ID" bigint NOT NULL,
    "PAPER_TITLE" character varying(255),
    "PAPER_DETAILS" text,
    "CONFERENCE_NAME" character varying(255) NOT NULL,
    "CONFERENCE_VENUE" character varying(255),
    "CONFERENCE_START_DATE" date,
    "CONFERENCE_END_DATE" date,
    "REGISTRATION_FEE" numeric(10,2),
    "TRAVEL_BUDGET" numeric(10,2) NOT NULL,
    "SUPERVISOR_NAME" character varying(255),
    "PAPER_FILE_PATH" character varying(500),
    "STATUS" character varying(50) DEFAULT 'SUBMITTED'::character varying,
    "TRACKING_CODE" character varying(32) DEFAULT upper("substring"(md5((random())::text), 1, 8)) NOT NULL,
    "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "UPDATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "EMAIL" character varying(255) NOT NULL,
    "APPLICANT_NAME" character varying(255) NOT NULL,
    "INSTITUTION_NAME" character varying(255) NOT NULL,
    "MOBILE_PHONE" character varying(50) NOT NULL,
    "POSTAL_ADDRESS" text NOT NULL,
    "CURRENT_DEGREE_TYPE" character varying(100),
    "CURRENT_DEGREE_PROGRAM" character varying(100),
    "BUDGET_JUSTIFICATION" text NOT NULL,
    "ACCEPTANCE_LETTER_PATH" character varying(500),
    "REVIEWED_ONCE" boolean DEFAULT false,
    "REVIEWED_AT" timestamp without time zone,
    "FACULTY_NAME" character varying(255),
    "FACULTY_EMAIL" character varying(255),
    "FACULTY_PHONE" character varying(50),
    "FACULTY_ADDRESS" text,
    "FACULTY_DESIGNATION" character varying(100),
    "CONFERENCE_WEBSITE" character varying(500),
    "PREVIOUS_GRANT" boolean DEFAULT false,
    "PREVIOUS_CONFERENCE_NAME" character varying(255),
    "PREVIOUS_CONFERENCE_DATES" character varying(255),
    "REJECTION_REASON" text,
    "ENROLMENT_TYPE" character varying(50),
    "PAPER_SUBMISSION_DEADLINE" date,
    "ACCEPTANCE_NOTIFICATION_DATE" date,
    "PAPER_TYPE" character varying(50),
    "NOTIFIED_AT" timestamp without time zone,
    "NOTIFIED_STATUS" character varying(50),
    "PROGRAM" character varying(20) DEFAULT 'TRAVEL'::character varying NOT NULL,
    CONSTRAINT "APPLICATIONS_travel_required_chk" CHECK (
        "PROGRAM" <> 'TRAVEL'::character varying OR (
            "PAPER_TITLE" IS NOT NULL AND "PAPER_DETAILS" IS NOT NULL AND
            "CONFERENCE_VENUE" IS NOT NULL AND "CONFERENCE_START_DATE" IS NOT NULL AND
            "CONFERENCE_END_DATE" IS NOT NULL AND "REGISTRATION_FEE" IS NOT NULL AND
            "SUPERVISOR_NAME" IS NOT NULL AND "CURRENT_DEGREE_TYPE" IS NOT NULL AND
            "CURRENT_DEGREE_PROGRAM" IS NOT NULL
        )
    )
);


ALTER TABLE public."APPLICATIONS" OWNER TO postgres;

--
-- TOC entry 219 (class 1259 OID 21034)
-- Name: APPLICATIONS_ID_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public."APPLICATIONS_ID_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public."APPLICATIONS_ID_seq" OWNER TO postgres;

--
-- TOC entry 4940 (class 0 OID 0)
-- Dependencies: 219
-- Name: APPLICATIONS_ID_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public."APPLICATIONS_ID_seq" OWNED BY public."APPLICATIONS"."ID";


--
-- Name: RFG_DETAILS; Type: TABLE; Schema: public; Owner: postgres
-- Research Facilitation Grant fields, 1:1 with an APPLICATIONS row.
--

CREATE TABLE public."RFG_DETAILS" (
    "ID" bigint NOT NULL,
    "APPLICATION_ID" bigint NOT NULL,
    "SCHEME" character varying(30) NOT NULL,
    "CORRESPONDENCE_EMAIL" character varying(255),
    "DEPARTMENTS" text,
    "AFFILIATION_STATUS" character varying(100),
    "STUDENT_TYPE" character varying(50),
    "FACULTY_CONTACT_NAME" character varying(255),
    "FACULTY_CONTACT_EMAIL" character varying(255),
    "PREVIOUS_RFG" boolean DEFAULT false,
    "PREVIOUS_RFG_DETAILS" text,
    "PAPER_AUTHORS" text,
    "PUBLICATION_VENUE_URL" character varying(500),
    "PAPER_PDF_URL" character varying(500),
    "CHARGES_DOC_PATH" character varying(500),
    "EVENT_URL" character varying(500),
    "INVITATION_LETTER_PATH" character varying(500),
    "ORGANIZER_NAME" character varying(255),
    "ORGANIZER_AFFILIATION" character varying(255),
    "ORGANIZER_EMAIL" character varying(255),
    "GRANT_HEADS" text,
    "AMOUNT_BREAKDOWN" text,
    "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "RFG_DETAILS_scheme_chk"
        CHECK (("SCHEME")::text = ANY (ARRAY['OPEN_ACCESS'::text, 'EXTRA_PAGE'::text, 'INVITATION'::text]))
);

ALTER TABLE public."RFG_DETAILS" OWNER TO postgres;

--
-- Name: USER_PROGRAM_ROLES; Type: TABLE; Schema: public; Owner: postgres
-- Programme-scoped roles. USERS.ROLE is unchanged and still carries the global
-- 'System Reviewer' user-administration capability, which is not a programme role.
--

CREATE TABLE public."USER_PROGRAM_ROLES" (
    "ID" bigint NOT NULL,
    "USER_ID" bigint NOT NULL,
    "PROGRAM" character varying(20) NOT NULL,
    "ROLE" character varying(30) NOT NULL,
    "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "USER_PROGRAM_ROLES_program_chk"
        CHECK (("PROGRAM")::text = ANY (ARRAY['TRAVEL'::text, 'RFG'::text])),
    CONSTRAINT "USER_PROGRAM_ROLES_role_chk"
        CHECK (("ROLE")::text = ANY (ARRAY['Chairman'::text, 'Reviewer'::text, 'Observer'::text]))
);

ALTER TABLE public."USER_PROGRAM_ROLES" OWNER TO postgres;

--
-- TOC entry 222 (class 1259 OID 21054)
-- Name: FINAL_APPROVALS; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public."FINAL_APPROVALS" (
    "ID" bigint NOT NULL,
    "APPLICATION_ID" bigint NOT NULL,
    "CHAIRMAN_ID" bigint NOT NULL,
    "APPROVED_AMOUNT" numeric(15,2) NOT NULL,
    "FEEDBACK" text,
    "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public."FINAL_APPROVALS" OWNER TO postgres;

--
-- TOC entry 221 (class 1259 OID 21053)
-- Name: FINAL_APPROVALS_ID_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public."FINAL_APPROVALS_ID_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public."FINAL_APPROVALS_ID_seq" OWNER TO postgres;

--
-- TOC entry 4941 (class 0 OID 0)
-- Dependencies: 221
-- Name: FINAL_APPROVALS_ID_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public."FINAL_APPROVALS_ID_seq" OWNED BY public."FINAL_APPROVALS"."ID";


--
-- TOC entry 224 (class 1259 OID 21069)
-- Name: REVIEWS; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public."REVIEWS" (
    "ID" bigint NOT NULL,
    "APPLICATION_ID" bigint NOT NULL,
    "USER_ID" bigint NOT NULL,
    "RATING" integer NOT NULL,
    "FEEDBACK" text,
    "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public."REVIEWS" OWNER TO postgres;

--
-- TOC entry 223 (class 1259 OID 21068)
-- Name: REVIEWS_ID_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public."REVIEWS_ID_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public."REVIEWS_ID_seq" OWNER TO postgres;

--
-- TOC entry 4942 (class 0 OID 0)
-- Dependencies: 223
-- Name: REVIEWS_ID_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public."REVIEWS_ID_seq" OWNED BY public."REVIEWS"."ID";


--
-- TOC entry 218 (class 1259 OID 21023)
-- Name: USERS; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public."USERS" (
    "ID" bigint NOT NULL,
    "NAME" character varying(100) NOT NULL,
    "EMAIL" character varying(150) NOT NULL,
    "MOBILE_NO" character varying(15),
    "PHOTO" character varying(255),
    "PASSWORD" character varying(64) NOT NULL,
    "ROLE" character varying(50) NOT NULL,
    "USERNAME" character varying(64) NOT NULL,
    "STATUS" character varying(20) DEFAULT 'Active'::character varying NOT NULL,
    "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "UPDATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public."USERS" OWNER TO postgres;

--
-- TOC entry 217 (class 1259 OID 21022)
-- Name: USERS_ID_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public."USERS_ID_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public."USERS_ID_seq" OWNER TO postgres;

--
-- TOC entry 4943 (class 0 OID 0)
-- Dependencies: 217
-- Name: USERS_ID_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public."USERS_ID_seq" OWNED BY public."USERS"."ID";


--
-- TOC entry 232 (class 1259 OID 21108)
-- Name: auth_group; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(150) NOT NULL
);


ALTER TABLE public.auth_group OWNER TO postgres;

--
-- TOC entry 231 (class 1259 OID 21107)
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
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
-- TOC entry 234 (class 1259 OID 21116)
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_group_permissions (
    id bigint NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


ALTER TABLE public.auth_group_permissions OWNER TO postgres;

--
-- TOC entry 233 (class 1259 OID 21115)
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
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
-- TOC entry 230 (class 1259 OID 21102)
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


ALTER TABLE public.auth_permission OWNER TO postgres;

--
-- TOC entry 229 (class 1259 OID 21101)
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
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
-- TOC entry 236 (class 1259 OID 21122)
-- Name: auth_user; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.auth_user OWNER TO postgres;

--
-- TOC entry 238 (class 1259 OID 21130)
-- Name: auth_user_groups; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_user_groups (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    group_id integer NOT NULL
);


ALTER TABLE public.auth_user_groups OWNER TO postgres;

--
-- TOC entry 237 (class 1259 OID 21129)
-- Name: auth_user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
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
-- TOC entry 235 (class 1259 OID 21121)
-- Name: auth_user_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
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
-- TOC entry 240 (class 1259 OID 21136)
-- Name: auth_user_user_permissions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.auth_user_user_permissions (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    permission_id integer NOT NULL
);


ALTER TABLE public.auth_user_user_permissions OWNER TO postgres;

--
-- TOC entry 239 (class 1259 OID 21135)
-- Name: auth_user_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
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
-- TOC entry 242 (class 1259 OID 21194)
-- Name: django_admin_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.django_admin_log (
    id integer NOT NULL,
    action_time timestamp with time zone NOT NULL,
    object_id text,
    object_repr character varying(200) NOT NULL,
    action_flag smallint NOT NULL,
    change_message text NOT NULL,
    content_type_id integer,
    user_id integer NOT NULL,
    CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0))
);


ALTER TABLE public.django_admin_log OWNER TO postgres;

--
-- TOC entry 241 (class 1259 OID 21193)
-- Name: django_admin_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.django_admin_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_admin_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 228 (class 1259 OID 21094)
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


ALTER TABLE public.django_content_type OWNER TO postgres;

--
-- TOC entry 227 (class 1259 OID 21093)
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
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
-- TOC entry 226 (class 1259 OID 21086)
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


ALTER TABLE public.django_migrations OWNER TO postgres;

--
-- TOC entry 225 (class 1259 OID 21085)
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
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
-- TOC entry 243 (class 1259 OID 21222)
-- Name: django_session; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


ALTER TABLE public.django_session OWNER TO postgres;

--
-- TOC entry 4679 (class 2604 OID 21038)
-- Name: APPLICATIONS ID; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."APPLICATIONS" ALTER COLUMN "ID" SET DEFAULT nextval('public."APPLICATIONS_ID_seq"'::regclass);


--
-- TOC entry 4686 (class 2604 OID 21057)
-- Name: FINAL_APPROVALS ID; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."FINAL_APPROVALS" ALTER COLUMN "ID" SET DEFAULT nextval('public."FINAL_APPROVALS_ID_seq"'::regclass);


--
-- TOC entry 4688 (class 2604 OID 21072)
-- Name: REVIEWS ID; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."REVIEWS" ALTER COLUMN "ID" SET DEFAULT nextval('public."REVIEWS_ID_seq"'::regclass);


--
-- TOC entry 4675 (class 2604 OID 21026)
-- Name: USERS ID; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."USERS" ALTER COLUMN "ID" SET DEFAULT nextval('public."USERS_ID_seq"'::regclass);


--
-- TOC entry 4911 (class 0 OID 21035)
-- Dependencies: 220
-- Data for Name: APPLICATIONS; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4913 (class 0 OID 21054)
-- Dependencies: 222
-- Data for Name: FINAL_APPROVALS; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4915 (class 0 OID 21069)
-- Dependencies: 224
-- Data for Name: REVIEWS; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4909 (class 0 OID 21023)
-- Dependencies: 218
-- Data for Name: USERS; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4923 (class 0 OID 21108)
-- Dependencies: 232
-- Data for Name: auth_group; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4925 (class 0 OID 21116)
-- Dependencies: 234
-- Data for Name: auth_group_permissions; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4921 (class 0 OID 21102)
-- Dependencies: 230
-- Data for Name: auth_permission; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4927 (class 0 OID 21122)
-- Dependencies: 236
-- Data for Name: auth_user; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4929 (class 0 OID 21130)
-- Dependencies: 238
-- Data for Name: auth_user_groups; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4931 (class 0 OID 21136)
-- Dependencies: 240
-- Data for Name: auth_user_user_permissions; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4933 (class 0 OID 21194)
-- Dependencies: 242
-- Data for Name: django_admin_log; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4919 (class 0 OID 21094)
-- Dependencies: 228
-- Data for Name: django_content_type; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4917 (class 0 OID 21086)
-- Dependencies: 226
-- Data for Name: django_migrations; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4934 (class 0 OID 21222)
-- Dependencies: 243
-- Data for Name: django_session; Type: TABLE DATA; Schema: public; Owner: postgres
--


--
-- TOC entry 4944 (class 0 OID 0)
-- Dependencies: 219
-- Name: APPLICATIONS_ID_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public."APPLICATIONS_ID_seq"', 42, true);


--
-- TOC entry 4945 (class 0 OID 0)
-- Dependencies: 221
-- Name: FINAL_APPROVALS_ID_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public."FINAL_APPROVALS_ID_seq"', 9, true);


--
-- TOC entry 4946 (class 0 OID 0)
-- Dependencies: 223
-- Name: REVIEWS_ID_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public."REVIEWS_ID_seq"', 14, true);


--
-- TOC entry 4947 (class 0 OID 0)
-- Dependencies: 217
-- Name: USERS_ID_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public."USERS_ID_seq"', 4, true);


--
-- TOC entry 4948 (class 0 OID 0)
-- Dependencies: 231
-- Name: auth_group_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.auth_group_id_seq', 1, false);


--
-- TOC entry 4949 (class 0 OID 0)
-- Dependencies: 233
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.auth_group_permissions_id_seq', 1, false);


--
-- TOC entry 4950 (class 0 OID 0)
-- Dependencies: 229
-- Name: auth_permission_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.auth_permission_id_seq', 24, true);


--
-- TOC entry 4951 (class 0 OID 0)
-- Dependencies: 237
-- Name: auth_user_groups_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.auth_user_groups_id_seq', 1, false);


--
-- TOC entry 4952 (class 0 OID 0)
-- Dependencies: 235
-- Name: auth_user_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.auth_user_id_seq', 4, true);


--
-- TOC entry 4953 (class 0 OID 0)
-- Dependencies: 239
-- Name: auth_user_user_permissions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.auth_user_user_permissions_id_seq', 1, false);


--
-- TOC entry 4954 (class 0 OID 0)
-- Dependencies: 241
-- Name: django_admin_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.django_admin_log_id_seq', 1, false);


--
-- TOC entry 4955 (class 0 OID 0)
-- Dependencies: 227
-- Name: django_content_type_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.django_content_type_id_seq', 6, true);


--
-- TOC entry 4956 (class 0 OID 0)
-- Dependencies: 225
-- Name: django_migrations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.django_migrations_id_seq', 18, true);


--
-- TOC entry 4694 (class 2606 OID 21050)
-- Name: APPLICATIONS APPLICATIONS_TRACKING_CODE_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."APPLICATIONS"
    ADD CONSTRAINT "APPLICATIONS_TRACKING_CODE_key" UNIQUE ("TRACKING_CODE");


--
-- TOC entry 4696 (class 2606 OID 21048)
-- Name: APPLICATIONS APPLICATIONS_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."APPLICATIONS"
    ADD CONSTRAINT "APPLICATIONS_pkey" PRIMARY KEY ("ID");


--
-- TOC entry 4700 (class 2606 OID 21062)
-- Name: FINAL_APPROVALS FINAL_APPROVALS_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."FINAL_APPROVALS"
    ADD CONSTRAINT "FINAL_APPROVALS_pkey" PRIMARY KEY ("ID");


--
-- TOC entry 4702 (class 2606 OID 21079)
-- Name: REVIEWS REVIEWS_APPLICATION_ID_USER_ID_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."REVIEWS"
    ADD CONSTRAINT "REVIEWS_APPLICATION_ID_USER_ID_key" UNIQUE ("APPLICATION_ID", "USER_ID");


--
-- TOC entry 4704 (class 2606 OID 21077)
-- Name: REVIEWS REVIEWS_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."REVIEWS"
    ADD CONSTRAINT "REVIEWS_pkey" PRIMARY KEY ("ID");


--
-- TOC entry 4692 (class 2606 OID 21033)
-- Name: USERS USERS_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."USERS"
    ADD CONSTRAINT "USERS_pkey" PRIMARY KEY ("ID");


--
-- TOC entry 4718 (class 2606 OID 21220)
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- TOC entry 4723 (class 2606 OID 21151)
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- TOC entry 4726 (class 2606 OID 21120)
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- TOC entry 4720 (class 2606 OID 21112)
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- TOC entry 4713 (class 2606 OID 21142)
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- TOC entry 4715 (class 2606 OID 21106)
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- TOC entry 4734 (class 2606 OID 21134)
-- Name: auth_user_groups auth_user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_pkey PRIMARY KEY (id);


--
-- TOC entry 4737 (class 2606 OID 21166)
-- Name: auth_user_groups auth_user_groups_user_id_group_id_94350c0c_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_group_id_94350c0c_uniq UNIQUE (user_id, group_id);


--
-- TOC entry 4728 (class 2606 OID 21126)
-- Name: auth_user auth_user_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_pkey PRIMARY KEY (id);


--
-- TOC entry 4740 (class 2606 OID 21140)
-- Name: auth_user_user_permissions auth_user_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_pkey PRIMARY KEY (id);


--
-- TOC entry 4743 (class 2606 OID 21180)
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_permission_id_14a6b632_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_permission_id_14a6b632_uniq UNIQUE (user_id, permission_id);


--
-- TOC entry 4731 (class 2606 OID 21215)
-- Name: auth_user auth_user_username_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_username_key UNIQUE (username);


--
-- TOC entry 4746 (class 2606 OID 21201)
-- Name: django_admin_log django_admin_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_pkey PRIMARY KEY (id);


--
-- TOC entry 4708 (class 2606 OID 21100)
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- TOC entry 4710 (class 2606 OID 21098)
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- TOC entry 4706 (class 2606 OID 21092)
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- TOC entry 4750 (class 2606 OID 21228)
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- TOC entry 4697 (class 1259 OID 21051)
-- Name: IDX_APPLICATIONS_STATUS; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX "IDX_APPLICATIONS_STATUS" ON public."APPLICATIONS" USING btree ("STATUS");


--
-- TOC entry 4698 (class 1259 OID 21052)
-- Name: IDX_APPLICATIONS_TRACKING_CODE; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX "IDX_APPLICATIONS_TRACKING_CODE" ON public."APPLICATIONS" USING btree ("TRACKING_CODE");


--
-- TOC entry 4716 (class 1259 OID 21221)
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- TOC entry 4721 (class 1259 OID 21162)
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- TOC entry 4724 (class 1259 OID 21163)
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- TOC entry 4711 (class 1259 OID 21148)
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- TOC entry 4732 (class 1259 OID 21178)
-- Name: auth_user_groups_group_id_97559544; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_groups_group_id_97559544 ON public.auth_user_groups USING btree (group_id);


--
-- TOC entry 4735 (class 1259 OID 21177)
-- Name: auth_user_groups_user_id_6a12ed8b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_groups_user_id_6a12ed8b ON public.auth_user_groups USING btree (user_id);


--
-- TOC entry 4738 (class 1259 OID 21192)
-- Name: auth_user_user_permissions_permission_id_1fbb5f2c; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_user_permissions_permission_id_1fbb5f2c ON public.auth_user_user_permissions USING btree (permission_id);


--
-- TOC entry 4741 (class 1259 OID 21191)
-- Name: auth_user_user_permissions_user_id_a95ead1b; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_user_permissions_user_id_a95ead1b ON public.auth_user_user_permissions USING btree (user_id);


--
-- TOC entry 4729 (class 1259 OID 21216)
-- Name: auth_user_username_6821ab7c_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX auth_user_username_6821ab7c_like ON public.auth_user USING btree (username varchar_pattern_ops);


--
-- TOC entry 4744 (class 1259 OID 21212)
-- Name: django_admin_log_content_type_id_c4bce8eb; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id);


--
-- TOC entry 4747 (class 1259 OID 21213)
-- Name: django_admin_log_user_id_c564eba6; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id);


--
-- TOC entry 4748 (class 1259 OID 21230)
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- TOC entry 4751 (class 1259 OID 21229)
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- TOC entry 4752 (class 2606 OID 21063)
-- Name: FINAL_APPROVALS FINAL_APPROVALS_CHAIRMAN_ID_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."FINAL_APPROVALS"
    ADD CONSTRAINT "FINAL_APPROVALS_CHAIRMAN_ID_fkey" FOREIGN KEY ("CHAIRMAN_ID") REFERENCES public."USERS"("ID") ON DELETE CASCADE;


--
-- TOC entry 4753 (class 2606 OID 21080)
-- Name: REVIEWS REVIEWS_USER_ID_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public."REVIEWS"
    ADD CONSTRAINT "REVIEWS_USER_ID_fkey" FOREIGN KEY ("USER_ID") REFERENCES public."USERS"("ID") ON DELETE CASCADE;


--
-- TOC entry 4755 (class 2606 OID 21157)
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4756 (class 2606 OID 21152)
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4754 (class 2606 OID 21143)
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4757 (class 2606 OID 21172)
-- Name: auth_user_groups auth_user_groups_group_id_97559544_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_group_id_97559544_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4758 (class 2606 OID 21167)
-- Name: auth_user_groups auth_user_groups_user_id_6a12ed8b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_6a12ed8b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4759 (class 2606 OID 21186)
-- Name: auth_user_user_permissions auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4760 (class 2606 OID 21181)
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4761 (class 2606 OID 21202)
-- Name: django_admin_log django_admin_log_content_type_id_c4bce8eb_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- TOC entry 4762 (class 2606 OID 21207)
-- Name: django_admin_log django_admin_log_user_id_c564eba6_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_user_id_c564eba6_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


-- Completed on 2026-08-05 11:45:34

--
-- PostgreSQL database dump complete
--


--
-- RFG-era objects that never reached this file.
--
-- USER_PROGRAM_ROLES and RFG_DETAILS were added by a migration applied directly
-- to Cloud SQL. Their CREATE TABLE and CHECK constraints were mirrored into the
-- schema of record, but their primary keys, unique constraints, foreign keys,
-- identity sequences and indexes were not. A database built from this file alone
-- was missing all of them, which silently breaks:
--   - programme-role assignment in the admin UI, because set_program_role uses
--     ON CONFLICT ("USER_ID","PROGRAM") and that needs the unique constraint;
--   - any insert into either table, because "ID" had no sequence default;
--   - cascade deletes from APPLICATIONS and USERS.
--
-- Reconstructed from the live database and verified against it. Written to be
-- safely re-runnable, so a database already built from the incomplete file can
-- be repaired by applying just this section.
--

CREATE SEQUENCE IF NOT EXISTS public."USER_PROGRAM_ROLES_ID_seq"
    AS bigint START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public."USER_PROGRAM_ROLES_ID_seq"
    OWNED BY public."USER_PROGRAM_ROLES"."ID";
ALTER TABLE ONLY public."USER_PROGRAM_ROLES"
    ALTER COLUMN "ID" SET DEFAULT nextval('public."USER_PROGRAM_ROLES_ID_seq"'::regclass);

CREATE SEQUENCE IF NOT EXISTS public."RFG_DETAILS_ID_seq"
    AS bigint START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public."RFG_DETAILS_ID_seq"
    OWNED BY public."RFG_DETAILS"."ID";
ALTER TABLE ONLY public."RFG_DETAILS"
    ALTER COLUMN "ID" SET DEFAULT nextval('public."RFG_DETAILS_ID_seq"'::regclass);

DO $rfg$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'USER_PROGRAM_ROLES_pkey') THEN
        ALTER TABLE ONLY public."USER_PROGRAM_ROLES"
            ADD CONSTRAINT "USER_PROGRAM_ROLES_pkey" PRIMARY KEY ("ID");
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'USER_PROGRAM_ROLES_user_program_key') THEN
        ALTER TABLE ONLY public."USER_PROGRAM_ROLES"
            ADD CONSTRAINT "USER_PROGRAM_ROLES_user_program_key" UNIQUE ("USER_ID", "PROGRAM");
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'USER_PROGRAM_ROLES_USER_ID_fkey') THEN
        ALTER TABLE ONLY public."USER_PROGRAM_ROLES"
            ADD CONSTRAINT "USER_PROGRAM_ROLES_USER_ID_fkey"
            FOREIGN KEY ("USER_ID") REFERENCES public."USERS"("ID") ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'RFG_DETAILS_pkey') THEN
        ALTER TABLE ONLY public."RFG_DETAILS"
            ADD CONSTRAINT "RFG_DETAILS_pkey" PRIMARY KEY ("ID");
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'RFG_DETAILS_APPLICATION_ID_key') THEN
        ALTER TABLE ONLY public."RFG_DETAILS"
            ADD CONSTRAINT "RFG_DETAILS_APPLICATION_ID_key" UNIQUE ("APPLICATION_ID");
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'RFG_DETAILS_APPLICATION_ID_fkey') THEN
        ALTER TABLE ONLY public."RFG_DETAILS"
            ADD CONSTRAINT "RFG_DETAILS_APPLICATION_ID_fkey"
            FOREIGN KEY ("APPLICATION_ID") REFERENCES public."APPLICATIONS"("ID") ON DELETE CASCADE;
    END IF;
END
$rfg$;

CREATE INDEX IF NOT EXISTS "IDX_APPLICATIONS_PROGRAM"
    ON public."APPLICATIONS" USING btree ("PROGRAM");
CREATE INDEX IF NOT EXISTS "IDX_USER_PROGRAM_ROLES_USER_ID"
    ON public."USER_PROGRAM_ROLES" USING btree ("USER_ID");
CREATE INDEX IF NOT EXISTS "IDX_RFG_DETAILS_APPLICATION_ID"
    ON public."RFG_DETAILS" USING btree ("APPLICATION_ID");
