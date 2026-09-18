-- Canonical user accounts, as SQL.
--
-- This mirrors `python manage.py seed_users` for environments where running a
-- management command is inconvenient (a psql shell, or gcloud sql import sql).
-- The command is the primary path; keep the two in step.
--
-- Passwords are unsalted MD5 because that is what backend/views.py:login_view
-- compares against. All accounts are created with the password 12345678.
-- Re-running does NOT reset passwords: only newly created rows get one, so an
-- account whose holder has changed their password keeps it.
--
-- Idempotent. USERS.USERNAME has no unique constraint, hence WHERE NOT EXISTS
-- rather than ON CONFLICT.

BEGIN;

CREATE TEMP TABLE _seed_users (
    ord      int,
    name     text,
    username text,
    email    text,
    account  text,   -- USERS.ROLE: account type, not workflow role
    travel   text,   -- USER_PROGRAM_ROLES role for TRAVEL, NULL = no access
    rfg      text    -- USER_PROGRAM_ROLES role for RFG,    NULL = no access
) ON COMMIT DROP;

-- Travel grouped ahead of RFG: /profile/ lists users by ID, so on a fresh
-- database the insert order below is the order they appear in.
INSERT INTO _seed_users VALUES
    ( 1, 'System Reviewer',      'systemreviewer', 'systemreviewer@example.com', 'System Reviewer', NULL,       NULL),

    ( 2, 'Travel Chair',         'tg-chair',       'tgchair@example.com',        'Reviewer',        'Chairman', NULL),
    ( 3, 'Travel Reviewer 1',    'tg-reviewer1',   'tgreviewer1@example.com',    'Reviewer',        'Reviewer', NULL),
    ( 4, 'Travel Reviewer 2',    'tg-reviewer2',   'tgreviewer2@example.com',    'Reviewer',        'Reviewer', NULL),
    ( 5, 'Travel Reviewer 3',    'tg-reviewer3',   'tgreviewer3@example.com',    'Reviewer',        'Reviewer', NULL),
    -- tg-finance / rfg-finance are reserved usernames: permissions.finance_program()
    -- grants Finance powers only when username, Standard account type, Active
    -- status and the Finance programme role all line up.
    ( 6, 'Travel Grant Finance', 'tg-finance',     'tgfinance@example.com',      'Reviewer',        'Finance',  NULL),
    ( 7, 'Travel Observer',      'tg-observer',    'tgobserver@example.com',     'Reviewer',        'Observer', NULL),

    ( 8, 'RFG Chair',            'rfg-chair',      'rfgchair@example.com',       'Reviewer',        NULL, 'Chairman'),
    ( 9, 'RFG Reviewer 1',       'rfg-reviewer1',  'rfgreviewer1@example.com',   'Reviewer',        NULL, 'Reviewer'),
    (10, 'RFG Reviewer 2',       'rfg-reviewer2',  'rfgreviewer2@example.com',   'Reviewer',        NULL, 'Reviewer'),
    (11, 'RFG Reviewer 3',       'rfg-reviewer3',  'rfgreviewer3@example.com',   'Reviewer',        NULL, 'Reviewer'),
    (12, 'RFG Finance',          'rfg-finance',    'rfgfinance@example.com',     'Reviewer',        NULL, 'Finance'),
    (13, 'RFG Observer',         'rfg-observer',   'rfgobserver@example.com',    'Reviewer',        NULL, 'Observer');

-- Create the ones that are missing, in list order.
INSERT INTO public."USERS"
    ("NAME","USERNAME","EMAIL","MOBILE_NO","ROLE","PASSWORD","STATUS","CREATED_AT","UPDATED_AT")
SELECT s.name, s.username, s.email, NULL, s.account,
       '25d55ad283aa400af464c76d713c07ad',   -- md5('12345678')
       'Active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
  FROM _seed_users s
 WHERE NOT EXISTS (SELECT 1 FROM public."USERS" u WHERE u."USERNAME" = s.username)
 ORDER BY s.ord;

-- Bring existing ones into line. PASSWORD is deliberately not listed.
UPDATE public."USERS" u
   SET "NAME"       = s.name,
       "EMAIL"      = s.email,
       "ROLE"       = s.account,
       "MOBILE_NO"  = NULL,
       "STATUS"     = 'Active',
       "UPDATED_AT" = CURRENT_TIMESTAMP
  FROM _seed_users s
 WHERE u."USERNAME" = s.username;

-- Remove access to a programme this account should have none in.
DELETE FROM public."USER_PROGRAM_ROLES" r
 USING public."USERS" u, _seed_users s
 WHERE r."USER_ID" = u."ID"
   AND u."USERNAME" = s.username
   AND ((r."PROGRAM" = 'TRAVEL' AND s.travel IS NULL)
     OR (r."PROGRAM" = 'RFG'    AND s.rfg    IS NULL));

INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID","PROGRAM","ROLE")
SELECT u."ID", 'TRAVEL', s.travel
  FROM public."USERS" u JOIN _seed_users s ON u."USERNAME" = s.username
 WHERE s.travel IS NOT NULL
ON CONFLICT ("USER_ID","PROGRAM") DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID","PROGRAM","ROLE")
SELECT u."ID", 'RFG', s.rfg
  FROM public."USERS" u JOIN _seed_users s ON u."USERNAME" = s.username
 WHERE s.rfg IS NOT NULL
ON CONFLICT ("USER_ID","PROGRAM") DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

-- ---------------------------------------------------------------------------
-- Removing everyone else is NOT done here. It cascades: REVIEWS.USER_ID and
-- FINAL_APPROVALS.CHAIRMAN_ID are ON DELETE CASCADE, so deleting an account
-- destroys the reviews it wrote and the approvals it signed.
--
-- Use the management command, which reports those counts before acting:
--     python manage.py seed_users --dry-run --delete-others
--     python manage.py seed_users --delete-others
--
-- If you must do it in SQL, this is the statement -- read the line above first:
--
-- DELETE FROM public."USERS"
--  WHERE "USERNAME" NOT IN (SELECT username FROM _seed_users);
-- ---------------------------------------------------------------------------

COMMIT;
