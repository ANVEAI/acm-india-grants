-- Budget management + reviewer evaluations: schema for commits b195806..821b622.
--
-- Those commits shipped code that reads five new APPLICATIONS columns and three
-- new tables, but the schema was never applied to Cloud SQL. The code carried a
-- runtime bootstrap instead, which ran DDL and data UPDATEs on every request --
-- including the public tracking page -- and 500'd because it tried to set a
-- default on a column that did not exist. This file is that schema, applied
-- once, so the runtime bootstrap no longer has to be the migration path.
--
-- Idempotent: safe to re-run.

BEGIN;

-- ---------------------------------------------------------------------------
-- APPLICATIONS: five columns the new workflow writes to.
-- DECISION_STATUS is NOT NULL with a default, so existing rows adopt 'Drafted'.
-- ---------------------------------------------------------------------------
ALTER TABLE public."APPLICATIONS"
    ADD COLUMN IF NOT EXISTS "DECISION_STATUS" character varying(50) NOT NULL DEFAULT 'Drafted',
    ADD COLUMN IF NOT EXISTS "BUDGET_EDITED_BY" character varying(255),
    ADD COLUMN IF NOT EXISTS "BUDGET_EDITED_AT" timestamp without time zone,
    ADD COLUMN IF NOT EXISTS "APPROVED_SUPPORT_AMOUNT" numeric,
    ADD COLUMN IF NOT EXISTS "COMMITTEE_EVALUATION_NOTES" text;

-- ---------------------------------------------------------------------------
-- PROGRAM_BUDGETS: one row per programme, holding the allocation.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."PROGRAM_BUDGETS" (
    "PROGRAM" character varying(20) NOT NULL,
    "TOTAL_BUDGET" numeric(15,2) NOT NULL,
    "UPDATED_BY" character varying(255) NOT NULL,
    "UPDATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "PROGRAM_BUDGETS_program_chk" CHECK ("PROGRAM" IN ('TRAVEL', 'RFG')),
    CONSTRAINT "PROGRAM_BUDGETS_total_nonnegative_chk" CHECK ("TOTAL_BUDGET" >= 0),
    CONSTRAINT "PROGRAM_BUDGETS_pkey" PRIMARY KEY ("PROGRAM")
);

-- ---------------------------------------------------------------------------
-- REVIEWER_EVALUATIONS: one row per (application, reviewer).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."REVIEWER_EVALUATIONS" (
    "ID" bigserial PRIMARY KEY,
    "APPLICATION_ID" bigint NOT NULL,
    "USER_ID" bigint NOT NULL,
    "OPENED_AT" timestamp without time zone,
    "SUGGESTED_AMOUNT" numeric(12, 2),
    "COMMITTEE_EVALUATION_NOTES" text,
    "DECISION_STATUS" character varying(50),
    "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "UPDATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "REVIEWER_EVALUATIONS_app_user_uniq" UNIQUE ("APPLICATION_ID", "USER_ID"),
    CONSTRAINT "REVIEWER_EVALUATIONS_user_fk" FOREIGN KEY ("USER_ID")
        REFERENCES public."USERS"("ID") ON DELETE CASCADE,
    CONSTRAINT "REVIEWER_EVALUATIONS_app_fk" FOREIGN KEY ("APPLICATION_ID")
        REFERENCES public."APPLICATIONS"("ID") ON DELETE CASCADE
);
ALTER TABLE public."REVIEWER_EVALUATIONS"
    ADD COLUMN IF NOT EXISTS "DECISION_STATUS" character varying(50);

-- ---------------------------------------------------------------------------
-- DOCUMENTS_UPLOADED: read by list_uploaded_documents() for the help page.
-- The code only ever SELECTs from it, and nothing in this repository defines
-- it, so the columns below are exactly the ones that query names. Creating it
-- empty makes the help page render an empty list instead of relying on the
-- surrounding try/except to swallow a missing-table error.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."DOCUMENTS_UPLOADED" (
    "ID" bigserial PRIMARY KEY,
    "TITLE" character varying(255),
    "CATEGORY" character varying(100),
    "PDF_NAME" character varying(500),
    "DOMAIN" character varying(100),
    "UPLOADED_BY" character varying(255),
    "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "UPDATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS "IDX_REVIEWER_EVALUATIONS_APPLICATION_ID"
    ON public."REVIEWER_EVALUATIONS" USING btree ("APPLICATION_ID");

-- ---------------------------------------------------------------------------
-- One-shot backfills, lifted out of ensure_reviewer_evaluations_table() where
-- they were re-running on every page load. Both are no-ops on a first apply
-- (the columns are new, so BUDGET_EDITED_BY is NULL and DECISION_STATUS is
-- 'Drafted' everywhere); they are kept here so the intent survives the move.
-- ---------------------------------------------------------------------------
UPDATE public."APPLICATIONS"
   SET "BUDGET_EDITED_BY" = NULL, "BUDGET_EDITED_AT" = NULL
 WHERE "BUDGET_EDITED_BY" LIKE '%Reviewer%';

UPDATE public."APPLICATIONS"
   SET "DECISION_STATUS" = 'Pending'
 WHERE "STATUS" = 'Under Review'
   AND "DECISION_STATUS" NOT IN ('Pending', 'Drafted')
   AND ("BUDGET_EDITED_BY" IS NULL OR "BUDGET_EDITED_BY" NOT LIKE '%Chairman%');

COMMIT;
