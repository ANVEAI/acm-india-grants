-- Local development seed. NOT for production.
-- schema.sql creates structure but no rows, so a fresh database has no accounts.
-- Passwords are MD5 because that is what backend/views.py:login_view compares
-- against -- weak, pre-existing, and another reason these are local-only.
--
-- All three passwords are: LocalDev123

INSERT INTO public."USERS" ("NAME","USERNAME","EMAIL","MOBILE_NO","ROLE","PASSWORD","STATUS","CREATED_AT")
VALUES
  ('Local Admin',  'localadmin',  'admin@example.invalid',  '0000000000',
   'System Reviewer', '1a809d7fa5939c3c70b57a0c1b9a7750', 'Active', CURRENT_TIMESTAMP),
  ('Travel Chair', 'travelchair', 'travel@example.invalid', '0000000000',
   'Chairman',        '1a809d7fa5939c3c70b57a0c1b9a7750', 'Active', CURRENT_TIMESTAMP),
  ('RFG Chair',    'rfgchair',    'rfg@example.invalid',    '0000000000',
   'Chairman',        '1a809d7fa5939c3c70b57a0c1b9a7750', 'Active', CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;

-- USERS.ROLE only carries the global System Reviewer flag. Review access lives
-- in USER_PROGRAM_ROLES, so grant that separately.
INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID","PROGRAM","ROLE")
SELECT "ID", 'TRAVEL', 'Chairman' FROM public."USERS" WHERE "EMAIL" = 'travel@example.invalid'
ON CONFLICT ("USER_ID","PROGRAM") DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

INSERT INTO public."USER_PROGRAM_ROLES" ("USER_ID","PROGRAM","ROLE")
SELECT "ID", 'RFG', 'Chairman' FROM public."USERS" WHERE "EMAIL" = 'rfg@example.invalid'
ON CONFLICT ("USER_ID","PROGRAM") DO UPDATE SET "ROLE" = EXCLUDED."ROLE";

-- The System Reviewer deliberately gets no programme row: it views everything
-- but cannot review, decide or notify. See home/permissions.py.
