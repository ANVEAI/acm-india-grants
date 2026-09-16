-- Apply this file to an existing database before deploying the programme
-- Finance budget feature. Safe to run more than once. Existing applications,
-- approvals, and legacy budget rows are not changed. The two reserved Finance
-- users are normalized to standard accounts with a programme Finance role.

CREATE TABLE IF NOT EXISTS public."PROGRAM_BUDGETS" (
    "PROGRAM" character varying(20) NOT NULL,
    "TOTAL_BUDGET" numeric(15,2) NOT NULL,
    "UPDATED_BY" character varying(255) NOT NULL,
    "UPDATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "PROGRAM_BUDGETS_program_chk" CHECK ("PROGRAM" IN ('TRAVEL', 'RFG')),
    CONSTRAINT "PROGRAM_BUDGETS_total_nonnegative_chk" CHECK ("TOTAL_BUDGET" >= 0),
    CONSTRAINT "PROGRAM_BUDGETS_pkey" PRIMARY KEY ("PROGRAM")
);

-- Preserve any allocation configured through the previous ACM-wide screen.
-- Each programme used half of that total, so migrate those halves only when a
-- programme-specific value has not already been configured.
DO $$
BEGIN
    IF to_regclass('public."ACM_BUDGET"') IS NOT NULL THEN
        INSERT INTO public."PROGRAM_BUDGETS"
            ("PROGRAM", "TOTAL_BUDGET", "UPDATED_BY", "UPDATED_AT")
        SELECT migrated."PROGRAM", legacy."TOTAL_BUDGET" / 2,
               legacy."UPDATED_BY", legacy."UPDATED_AT"
        FROM public."ACM_BUDGET" legacy
        CROSS JOIN (VALUES ('TRAVEL'), ('RFG')) AS migrated("PROGRAM")
        WHERE legacy."ID" = 1
        ON CONFLICT ("PROGRAM") DO NOTHING;
    END IF;
END $$;

-- Finance belongs in USER_PROGRAM_ROLES; it is not a global account type.
-- Replacing the CHECK is safe to repeat and preserves all existing role rows.
ALTER TABLE public."USER_PROGRAM_ROLES"
    DROP CONSTRAINT IF EXISTS "USER_PROGRAM_ROLES_role_chk";
ALTER TABLE public."USER_PROGRAM_ROLES"
    ADD CONSTRAINT "USER_PROGRAM_ROLES_role_chk"
    CHECK ("ROLE" IN ('Chairman', 'Reviewer', 'Observer', 'Finance'));

-- Upgrade accounts created by the earlier implementation. In this application
-- USERS.ROLE='Reviewer' is the stored value for a Standard account.
UPDATE public."USERS"
SET "ROLE" = 'Reviewer', "UPDATED_AT" = CURRENT_TIMESTAMP
WHERE "USERNAME" IN ('tg-finance', 'rfg-finance')
  AND "ROLE" <> 'Reviewer';

-- A Finance account is deliberately limited to one programme, even if an old
-- or manually-created row assigned it access elsewhere.
DELETE FROM public."USER_PROGRAM_ROLES" roles
USING public."USERS" users
WHERE roles."USER_ID" = users."ID"
  AND ((users."USERNAME" = 'tg-finance' AND roles."PROGRAM" <> 'TRAVEL')
    OR (users."USERNAME" = 'rfg-finance' AND roles."PROGRAM" <> 'RFG'));

INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID", "PROGRAM", "ROLE")
SELECT "ID", 'TRAVEL', 'Finance'
FROM public."USERS"
WHERE "USERNAME" = 'tg-finance'
ON CONFLICT ("USER_ID", "PROGRAM")
DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID", "PROGRAM", "ROLE")
SELECT "ID", 'RFG', 'Finance'
FROM public."USERS"
WHERE "USERNAME" = 'rfg-finance'
ON CONFLICT ("USER_ID", "PROGRAM")
DO UPDATE SET "ROLE" = EXCLUDED."ROLE";
