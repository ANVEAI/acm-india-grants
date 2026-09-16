-- Local development seed. NOT for production.
-- schema.sql creates structure but no rows, so a fresh database has no accounts.
-- Passwords are MD5 because that is what backend/views.py:login_view compares
-- against -- weak, pre-existing, and another reason these are local-only.
--
-- All local account passwords are: LocalDev123

INSERT INTO public."USERS" ("NAME","USERNAME","EMAIL","MOBILE_NO","ROLE","PASSWORD","STATUS","CREATED_AT")
VALUES
  ('Local Admin',  'localadmin',  'admin@example.invalid',  '0000000000',
   'System Reviewer', '1a809d7fa5939c3c70b57a0c1b9a7750', 'Active', CURRENT_TIMESTAMP),
  ('Travel Chair', 'travelchair', 'travel@example.invalid', '0000000000',
   'Chairman',        '1a809d7fa5939c3c70b57a0c1b9a7750', 'Active', CURRENT_TIMESTAMP),
  ('RFG Chair',    'rfgchair',    'rfg@example.invalid',    '0000000000',
   'Chairman',        '1a809d7fa5939c3c70b57a0c1b9a7750', 'Active', CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;

-- Programme Finance users are Standard accounts (stored as USERS.ROLE =
-- 'Reviewer'). Finance itself is assigned below as a programme role.
INSERT INTO public."USERS"
    ("NAME","USERNAME","EMAIL","MOBILE_NO","ROLE","PASSWORD","STATUS","CREATED_AT")
SELECT 'Travel Grant Finance', 'tg-finance', 'tg-finance@example.invalid',
       '0000000000', 'Reviewer',
       '1a809d7fa5939c3c70b57a0c1b9a7750', 'Active', CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM public."USERS" WHERE "USERNAME" = 'tg-finance'
);

INSERT INTO public."USERS"
    ("NAME","USERNAME","EMAIL","MOBILE_NO","ROLE","PASSWORD","STATUS","CREATED_AT")
SELECT 'RFG Finance', 'rfg-finance', 'rfg-finance@example.invalid',
       '0000000000', 'Reviewer',
       '1a809d7fa5939c3c70b57a0c1b9a7750', 'Active', CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM public."USERS" WHERE "USERNAME" = 'rfg-finance'
);

-- Normalize rows created by the previous local Finance implementation.
UPDATE public."USERS"
SET "ROLE" = 'Reviewer', "UPDATED_AT" = CURRENT_TIMESTAMP
WHERE "USERNAME" IN ('tg-finance', 'rfg-finance');

-- All workflow access, including Finance, lives in USER_PROGRAM_ROLES.
INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID","PROGRAM","ROLE")
SELECT "ID", 'TRAVEL', 'Chairman' FROM public."USERS" WHERE "EMAIL" = 'travel@example.invalid'
ON CONFLICT ("USER_ID","PROGRAM") DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID","PROGRAM","ROLE")
SELECT "ID", 'RFG', 'Chairman' FROM public."USERS" WHERE "EMAIL" = 'rfg@example.invalid'
ON CONFLICT ("USER_ID","PROGRAM") DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

DELETE FROM public."USER_PROGRAM_ROLES" roles
USING public."USERS" users
WHERE roles."USER_ID" = users."ID"
  AND ((users."USERNAME" = 'tg-finance' AND roles."PROGRAM" <> 'TRAVEL')
    OR (users."USERNAME" = 'rfg-finance' AND roles."PROGRAM" <> 'RFG'));

INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID","PROGRAM","ROLE")
SELECT "ID", 'TRAVEL', 'Finance' FROM public."USERS" WHERE "USERNAME" = 'tg-finance'
ON CONFLICT ("USER_ID","PROGRAM") DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID","PROGRAM","ROLE")
SELECT "ID", 'RFG', 'Finance' FROM public."USERS" WHERE "USERNAME" = 'rfg-finance'
ON CONFLICT ("USER_ID","PROGRAM") DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

-- The System Reviewer deliberately gets no programme row: it views everything
-- but cannot review, decide or notify. See home/permissions.py.
