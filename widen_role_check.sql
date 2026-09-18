-- USER_PROGRAM_ROLES."ROLE" must admit 'Finance'.
--
-- Databases created before the Finance role keep the original three-value CHECK
-- (Chairman, Reviewer, Observer) and reject the tg-finance / rfg-finance
-- assignments that `manage.py seed_users` makes. schema.sql already declares the
-- four-value version, so a freshly built database is fine; this is only for
-- databases that predate it.
--
-- budget_management_schema.sql also widens the constraint, but it mutates user
-- rows at the same time. This file does the constraint and nothing else.
--
-- Idempotent.

ALTER TABLE public."USER_PROGRAM_ROLES"
    DROP CONSTRAINT IF EXISTS "USER_PROGRAM_ROLES_role_chk";

ALTER TABLE public."USER_PROGRAM_ROLES"
    ADD CONSTRAINT "USER_PROGRAM_ROLES_role_chk"
    CHECK ("ROLE" IN ('Chairman', 'Reviewer', 'Observer', 'Finance'));
