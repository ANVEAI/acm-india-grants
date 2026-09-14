-- Apply this file to an existing database before deploying the budget feature.
-- Safe to run more than once. Existing application and approval rows are not changed.

CREATE TABLE IF NOT EXISTS public."ACM_BUDGET" (
    "ID" smallint DEFAULT 1 NOT NULL,
    "TOTAL_BUDGET" numeric(15,2) NOT NULL,
    "UPDATED_BY" character varying(255) NOT NULL,
    "UPDATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT "ACM_BUDGET_single_row_chk" CHECK ("ID" = 1),
    CONSTRAINT "ACM_BUDGET_total_nonnegative_chk" CHECK ("TOTAL_BUDGET" >= 0),
    CONSTRAINT "ACM_BUDGET_pkey" PRIMARY KEY ("ID")
);
