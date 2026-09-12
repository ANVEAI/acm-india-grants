# Student Travel Grant Portal — Handoff Document

**Last updated:** 2026-08-07
**Written for:** any engineer or LLM picking this project up cold.

---

## 1. What this is

A Django 5.1.7 web app for a **conference travel grant program** (originally sponsored/co-branded by ACM India-IARCS, per the form copy). Students submit an application with a paper, an acceptance letter, and budget details; a committee (Reviewer → Chairman) reviews and approves or rejects it; the applicant is emailed at each stage and can track status with a public tracking code — no account needed on their side.

**It is in active production use with real applicants and real data.** Treat the database as live, not a sandbox. As of 2026-08-07 there were 16 real applications.

**Live URL:** `https://stg-app-730778859721.asia-south1.run.app`
**No GitHub repo exists.** There is no `.git` anywhere in this tree — the code lives only in this local folder and is deployed by running `gcloud builds submit` directly from it. If you want version history or CI, you must set that up from scratch (`git init`, create a repo, push).

---

## 2. Where the code actually lives

```
C:\Users\hp\Downloads\studentTravelGrant\studentTravelGrant\   <- project root (manage.py is here)
```

There is an **outer** `C:\Users\hp\Downloads\studentTravelGrant\` wrapper folder containing only this project folder and a `Setup_Instructions.txt`. Don't confuse the two — always `cd` into the inner one.

Key files:
- `manage.py`, `studentTravelGrant_main/` — Django project config (settings, urls, wsgi/asgi)
- `home/` — the Django app containing almost all business logic (`views.py` is ~1200 lines: dashboard, application detail/review, notifications, export, tracking pages)
- `backend/` — login, application-submission endpoint, user CRUD
- `templates/` — server-rendered HTML (Bootstrap 5 + jQuery, no frontend framework)
- `student_travel_grant.sql` — the **schema of record**. There are no Django migrations for the business tables (see §5) — this SQL file plus a running Postgres instance is the actual schema.
- `Dockerfile`, `.dockerignore`, `.gcloudignore` — added during this engagement for Cloud Run deployment
- `HANDOFF.md` — this file

---

## 3. History of this engagement (chronological)

1. **Onboarding analysis** — read every file, documented architecture, found significant security and code-quality issues (see §8).
2. **GCP deployment, first attempt: Compute Engine VM.** Created a fresh GCP project `student-travel-grant-2026`, provisioned a VM (`stg-app`, e2-small, asia-south1), installed Postgres 17 + nginx + gunicorn locally on it, and set up HTTPS via a free `sslip.io` hostname + Let's Encrypt.
3. **That HTTPS hostname turned out to be blocked by the user's institutional (IIT Kanpur) network DNS filter** — sslip.io/nip.io-style dynamic-DNS domains are blocked by category on that network. This was the trigger for moving to Cloud Run instead (Cloud Run's `*.run.app` domains are not blocked).
4. **Migrated to Cloud Run** (see §4 for full architecture). The VM, its disk, its static IP, and its firewall rule were **fully deleted** afterward — there is no VM anymore, everything lives in the serverless stack.
5. **Multiple rounds of feature work and bug fixes**, requested as "external review" tickets, each deployed as a new container image tag (`v1` through `v10` at time of writing). Full list in §6.

---

## 4. Current architecture (Cloud Run)

**GCP Project:** `student-travel-grant-2026` (org `hello-org`, billing account `01DAB4-AA8203-54E40C`), region `asia-south1` (Mumbai — chosen because the data is India-specific: ₹ amounts, 10-digit mobile validation, IST timestamps).

| Component | Detail |
|---|---|
| Compute | Cloud Run service `stg-app`, `--allow-unauthenticated`, gen2 execution env, 1Gi/1cpu, min-instances=0, max-instances=4 |
| Container registry | Artifact Registry `asia-south1-docker.pkg.dev/student-travel-grant-2026/stg/app` |
| Database | Cloud SQL Postgres 17, instance `stg-db`, tier `db-f1-micro`, database `student_travel_grant`, user `stgapp`. Reached over the Cloud SQL unix socket `/cloudsql/student-travel-grant-2026:asia-south1:stg-db` |
| File storage | GCS bucket `student-travel-grant-2026-media`, **mounted into the container via GCSFuse** at `/mnt/media` (Cloud Run volume mount), with `MEDIA_ROOT=/mnt/media`. This is the load-bearing design decision — see §4.1 |
| Secrets | Secret Manager: `stg-db-password`, `stg-django-secret-key`, `stg-email-password` |
| Service account | `stg-run@student-travel-grant-2026.iam.gserviceaccount.com` — roles: `cloudsql.client`, `secretmanager.secretAccessor`, `storage.objectAdmin` (bucket-scoped) |
| Logging | stdout → Cloud Logging (settings.py routes Django's logger to a `StreamHandler`, not a file) |

### 4.1 Why GCSFuse instead of rewriting the upload code

The app's original code writes uploaded PDFs with raw Python `open(path, "wb+")` calls (in `backend/views.py` for paper/acceptance-letter uploads, `home/views.py` for profile photos) — it does **not** use Django's storage API. Cloud Run containers have no persistent local disk, so a naive lift-and-shift would silently lose every uploaded file on restart.

Rather than rewrite that file-I/O (higher risk on a live submission path), the GCS bucket is mounted as a Cloud Run volume at a local path, and `MEDIA_ROOT` points there. The existing `open()` calls work completely unmodified — they're writing into what looks like a normal directory but is actually GCSFuse talking to Cloud Storage.

**Practical implication:** if a future Cloud Run revision is deployed without the `--add-volume` / `--add-volume-mount` flags for the media bucket, uploads will **silently** start writing to the container's ephemeral filesystem instead of erroring — and vanish on next restart. Always carry those flags forward on redeploy (see §7).

### 4.2 Environment variables / secrets (how `settings.py` is configured)

`studentTravelGrant_main/settings.py` was made fully environment-driven during this engagement. Current Cloud Run env vars (non-secret):

```
DB_NAME=student_travel_grant
DB_USER=stgapp
DB_HOST=/cloudsql/student-travel-grant-2026:asia-south1:stg-db
DB_PORT=5432
MEDIA_ROOT=/mnt/media
ALLOWED_HOSTS=*
LOG_LEVEL=INFO
EMAIL_HOST_USER=wlone6156@gmail.com
DEFAULT_FROM_EMAIL=wlone6156@gmail.com
```

Secrets (`--set-secrets`, pulled from Secret Manager at container start):
```
DB_PASSWORD=stg-db-password:latest
SECRET_KEY=stg-django-secret-key:latest
EMAIL_HOST_PASSWORD=stg-email-password:latest
```

`DEBUG` defaults to `False` now (was `True` in the original code — this was a deliberate fix, see §8). Email is real Gmail SMTP and **does send live emails to real applicants** — confirmed working from Cloud Run.

---

## 5. Database — the single most important thing to understand

**There is no Django ORM usage for business data.** Zero models, zero `migrations/` folders for the `home` and `backend` apps. Every query in `views.py` is raw SQL via `django.db.connection.cursor()`, against tables with **UPPERCASE, double-quoted identifiers**: `"APPLICATIONS"`, `"USERS"`, `"REVIEWS"`, `"FINAL_APPROVALS"`.

This means:
- `python manage.py migrate` only creates Django's own tables (sessions, auth shadow users, admin log). It does **nothing** for the actual application schema.
- The schema is defined and evolved via **hand-written SQL files**, applied directly to Cloud SQL with `gcloud sql import sql`. There is no migration framework, no rollback, no version history beyond what's in this document and in `student_travel_grant.sql` (which is kept in sync as the schema-of-record, but is not itself executed automatically anywhere).
- **To change the schema:** write a `.sql` file, upload it to `gs://student-travel-grant-2026-media/_migration/<name>.sql`, run `gcloud sql import sql stg-db gs://.../_migration/<name>.sql --database=student_travel_grant --user=stgapp --project=student-travel-grant-2026`, then delete the migration file from the bucket afterward (keep the bucket clean — it's also where live uploads live). Mirror the change into `student_travel_grant.sql` so the file stays accurate for anyone restoring fresh.
- All schema changes made so far were done as **additive, nullable** `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements specifically so they never break the 16+ existing live rows. `NOT NULL` constraints were deliberately avoided for new columns since old rows predate them; "required" is enforced in application code (`submit_travel_grant` in `backend/views.py`) instead of the schema.

### 5.1 `"APPLICATIONS"` table — current full column list

Original columns (from the source dump): `ID, PAPER_TITLE, PAPER_DETAILS, CONFERENCE_NAME, CONFERENCE_VENUE, CONFERENCE_START_DATE, CONFERENCE_END_DATE, REGISTRATION_FEE, TRAVEL_BUDGET, SUPERVISOR_NAME, PAPER_FILE_PATH, STATUS, TRACKING_CODE, CREATED_AT, UPDATED_AT, EMAIL, APPLICANT_NAME, INSTITUTION_NAME, MOBILE_PHONE, POSTAL_ADDRESS, CURRENT_DEGREE_TYPE, CURRENT_DEGREE_PROGRAM, BUDGET_JUSTIFICATION, ACCEPTANCE_LETTER_PATH, REVIEWED_ONCE, REVIEWED_AT, FACULTY_NAME, FACULTY_EMAIL, FACULTY_PHONE, FACULTY_ADDRESS, FACULTY_DESIGNATION, CONFERENCE_WEBSITE, PREVIOUS_GRANT, PREVIOUS_CONFERENCE_NAME, PREVIOUS_CONFERENCE_DATES, REJECTION_REASON`

**Added during this engagement** (all nullable):
- `ENROLMENT_TYPE` varchar(50) — "Full Time" / "Part Time"
- `PAPER_SUBMISSION_DEADLINE` date
- `ACCEPTANCE_NOTIFICATION_DATE` date
- `PAPER_TYPE` varchar(50) — "Full Paper" / "Short Paper" / "Poster" / "Workshop Paper"
- `NOTIFIED_AT` timestamp without time zone
- `NOTIFIED_STATUS` varchar(50)

**`TRACKING_CODE` was widened from `varchar(20)` to `varchar(32)`** — the format `<conference-initials>-<ddmmyyHHMMSS>-<4 random chars>` overflowed 20 chars for any conference name with 3+ words, causing a 500 on submission. Fixed and verified.

`STATUS` is a free-text column (no CHECK constraint, no enum) with these values in practice: `SUBMITTED` → `Under Review` → `Accepted` | `Rejected`.

`NOTIFIED_STATUS` records **which** status the applicant was last emailed about (not just whether). The comparison `NOTIFIED_STATUS == STATUS` means "already notified of the *current* decision" — this correctly allows a fresh notification if status changes again after having been notified once (e.g. notified at Under Review, then later notified again at Accepted).

Other tables (`USERS`, `REVIEWS`, `FINAL_APPROVALS`) are unchanged from the original schema.

### 5.2 Seed / real users

Four accounts exist in `"USERS"`, all created before this engagement, password `12345678` (unsalted MD5 — see §8):

| Email | Role |
|---|---|
| chairman@example.com | Chairman |
| reviewer1@example.com | System Reviewer |
| reviewer2@example.com | Reviewer |
| k@example.com | Reviewer (status: Inactive, cannot log in) |

Roles: **Chairman** (final approve/reject, sets amount), **Reviewer** (submits ratings/feedback), **System Reviewer** (user administration only — add/edit users; does **not** participate in the review workflow and cannot submit reviews).

---

## 6. Deployment mechanics — how to ship a change

There is no CI/CD. Every deploy is manual, run from the project root:

```bash
# 1. Make code changes locally.
# 2. Build & push a new image tag (increment the version each time):
gcloud builds submit --tag asia-south1-docker.pkg.dev/student-travel-grant-2026/stg/app:vNN --project=student-travel-grant-2026

# 3. Deploy it (Cloud Run remembers previously-set env vars/secrets/volumes across
#    `gcloud run deploy` calls that only change --image, so a bare image swap is
#    usually enough for a code-only change):
gcloud run deploy stg-app --project=student-travel-grant-2026 --region=asia-south1 --image=asia-south1-docker.pkg.dev/student-travel-grant-2026/stg/app:vNN
```

If you ever need to redeploy from scratch (new project, disaster recovery), the **full** command needs all the flags — see §4 for the exact volume/secret/env-var wiring, or grep this document's history in memory. The bucket mount and Cloud SQL connection flags are not optional; a plain image swap without them will break media uploads and DB connectivity respectively (but a plain image swap when the *service already has those settings* correctly carries them forward — the risk is only on a from-scratch `gcloud run deploy`).

`requirements.txt` includes `gunicorn`, `whitenoise` (static files), `psycopg2-binary`, and `openpyxl` (used for the xlsx export feature, was previously an unused dependency).

As of this writing the image tag is **`v10`**.

### 6.1 Testing changes safely against a live database

This database has real applicants. The pattern used throughout this engagement:
- Prefer testing **validation-failure paths** (they reject before writing anything) over full successful submissions.
- When a full submission is needed to verify something, use an obviously-fake applicant name/email, then **delete that specific row afterward** by matching on tracking code + applicant name (never a bulk delete).
- **Be extremely careful with anything that sends email** (`notify_applicant`, `submit_travel_grant`, `reject_application`-adjacent paths). These send real emails to real people. Test notification-permission logic against *already-notified* applications where possible so nothing is actually sent, or accept that a real email will go out and account for it. One such live email was sent by mistake during this engagement while verifying a permissions fix — it could not be recalled, and the `NOTIFIED_STATUS` was correctly left set to reflect the real state, not rolled back.
- Never touch `"USERS"` rows other than the 4 known seed accounts without asking.

---

## 7. Feature/fix log (what's been built, in order)

1. **Initial deployment to Cloud Run** — Dockerfile, env-driven settings, GCSFuse media mount, Cloud SQL migration from the earlier VM's Postgres, DEBUG→False, logging→stdout, `wsgi.py`/`asgi.py` fixed (they referenced a nonexistent `soilMoisture_main.settings` module — leftover from a template/fork this project was based on).
2. **Working "Remember Me" login checkbox** — was previously non-functional (checkbox existed, backend ignored it). Implemented with `django.contrib.sessions` — later extended to a 2-year cookie duration per client request. Also fixed a related session/cookie bug around concurrent role switching.
3. **Real client + server-side form validation** on `/travel-grant-form` — the form previously had almost no validation; users could submit blank/garbage data. Added field-level required validation, an ordering rule (submission deadline ≤ acceptance date), postal code / phone format checks, etc.
4. **New application fields**: Enrolment Type, Paper Submission Deadline, Acceptance Notification Date, Paper Type — added to form, validation, DB, review UI, and the export.
5. **Dedicated post-submission success screen** replacing the old inline "form redisplays with a small note" behavior.
6. **Draft-decision / manual-notification workflow.** Previously, some status transitions triggered automatic emails to applicants immediately. This was changed so:
   - Marking a decision (Under Review / Accepted / Rejected) no longer auto-emails.
   - A separate explicit "Notify Applicant" action (in `home/views.py`, `notify_applicant`) sends the email.
   - **Permission matrix** (final state, after a follow-up correction): **Chairman** can notify any of Under Review / Accepted / Rejected. **Reviewer** can only notify "Under Review". **System Reviewer cannot send any notification** (explicitly removed after initially being included by mistake — it's a user-admin role, not a review-workflow role).
   - Duplicate-send protection via `NOTIFIED_STATUS` (see §5.1).
7. **Excel/CSV export** of all applications (`home/views.py`, `export_applications` view + `/applications/export/` route), using `openpyxl` and Python's `csv` module. Available to any logged-in user (Reviewer/System Reviewer/Chairman) — this was a deliberate client choice, not a gap; see §8 for the caveat.
8. **Timezone fix (IST)** — timestamps (`created_at`, `notified_at`, `reviewed_at`, etc.) were being displayed and exported in UTC, not IST, causing confusion since the app is India-only. `TIME_ZONE` set to `Asia/Kolkata` in settings, `USE_TZ=True` confirmed, and all display/export code paths verified to render IST consistently. **Database storage remains UTC** (Django/Postgres best practice) — only the presentation layer changed.
9. **`dd-mm-yyyy` date format enforcement** on the "Conference Dates" field (shown conditionally when a user indicates they previously availed the grant) — added a placeholder showing the expected format and both client- and server-side format validation.
10. **Fixed a pre-existing bug**: certain review-page code paths (`application_details_by_tracking` and related) were 500ing on legitimate lookups due to an unhandled edge case — found and fixed incidentally while working on the above.
11. **Fixed a pre-existing bug**: a failed submission could leave an incomplete/orphaned record in the database (partial writes not wrapped in a transaction) — found and fixed incidentally.
12. **Removed System Reviewer's notification permission** (most recent change, item 6 above) — a follow-up correction after the client clarified only Chairman + Reviewer should send notifications.

---

## 8. Known issues — NOT yet fixed (deliberate, client-acknowledged)

These were identified in the original onboarding analysis and **intentionally left in place** because the client chose to deploy/operate as-is rather than remediate immediately. Anyone continuing this work should know they exist:

- **Passwords are unsalted MD5**, stored directly in the `"USERS"` table (not Django's auth system, which is only used as a thin session/login shim alongside the custom table). All seed accounts share the password `12345678`.
- **No CSRF protection on some legacy internal endpoints** originally (largely mitigated by this engagement's work, but worth re-auditing if extending auth-adjacent code).
- **`ALLOWED_HOSTS=*`** in production — acceptable for a Cloud Run service with no custom domain, but should be tightened if a custom domain is ever added.
- **Export is available to all logged-in roles**, including plain Reviewers — meaning any Reviewer can download the full applicant PII dataset (names, emails, phone numbers, addresses, paper details) as xlsx/csv. This was a deliberate client decision, not an oversight — flagged explicitly during the work and accepted.
- **No rate limiting or bot protection** on the public application-submission form or the public tracking-lookup endpoint.
- No automated tests exist anywhere in this codebase.

---

## 9. Quick reference — things a new session will likely need

- **Project root:** `C:\Users\hp\Downloads\studentTravelGrant\studentTravelGrant`
- **Live URL:** `https://stg-app-730778859721.asia-south1.run.app`
- **GCP project:** `student-travel-grant-2026`, region `asia-south1`
- **Deploy:** `gcloud builds submit --tag ...` then `gcloud run deploy stg-app --image ...`
- **DB access:** via Cloud SQL, no direct psql shell set up by default — use `gcloud sql connect stg-db --user=stgapp --database=student_travel_grant` (will prompt for the password, which is in Secret Manager as `stg-db-password`) or apply changes via the `gcloud sql import sql` migration-file pattern in §5.
- **Schema of record:** `student_travel_grant.sql` in the project root (kept manually in sync — not auto-applied).
- **No git repo exists.** No CI/CD. No automated tests.
- **The database has real, live applicant data.** Always test destructively-adjacent changes with extreme care (see §6.1).
- **Media/uploads live in GCS**, mounted via GCSFuse — never assume local filesystem writes persist on Cloud Run outside that mount.

---

## 10. RFG integration (added 2026-08-21)

The portal now serves **two programmes**: Travel Support and the ACM India
**Research Facilitation Grant (RFG)**.

### Architecture: one spine, one child table

`APPLICATIONS` remains the single spine. A `PROGRAM` column (`TRAVEL` | `RFG`,
default `TRAVEL`) discriminates rows; RFG-only fields live in **`RFG_DETAILS`**
(1:1, real FK, cascade delete).

A separate `RFG_APPLICATIONS` table was deliberately **rejected**: uploads are named
`{APPLICATIONS.ID}_paper_{ts}.pdf` in one shared directory, so a second ID sequence
would collide, and `REVIEWS.APPLICATION_ID` / `FINAL_APPROVALS.APPLICATION_ID`
would have become ambiguous across two tables.

### The one non-additive schema change

Nine Travel-only columns had `NOT NULL` dropped (`PAPER_TITLE`, `PAPER_DETAILS`,
`CONFERENCE_VENUE`, `CONFERENCE_START_DATE`, `CONFERENCE_END_DATE`,
`REGISTRATION_FEE`, `SUPERVISOR_NAME`, `CURRENT_DEGREE_TYPE`,
`CURRENT_DEGREE_PROGRAM`) — an invitation-only RFG application has no paper, and a
paper-charges one has no venue or event dates.

**The guarantee moved rather than disappeared:** `APPLICATIONS_travel_required_chk`
re-imposes all nine for `PROGRAM = 'TRAVEL'` rows. Inserting a Travel row with a
null `PAPER_TITLE` is still rejected by the database. Do not drop that constraint.

### Permissions are programme-scoped

`USER_PROGRAM_ROLES` (`USER_ID`, `PROGRAM`, `ROLE`) holds at most one role per
user per programme: `Chairman` | `Reviewer` | `Observer`. `USERS.ROLE` is
**unchanged** and still carries the global `System Reviewer` user-administration
capability, which is not a programme role.

`home/permissions.py` is the single source of truth — `can_view`, `can_review`,
`can_decide`, `can_notify`, `visible_programs`. There are **no** global
`user_role == "Chairman"` checks left in the workflow views.

`program_roles()` reads `USER_PROGRAM_ROLES` **from the database on every request**
(cached on the request object only). There is deliberately **no fallback to the
legacy `USERS.ROLE`** — falling back would silently re-grant access to someone whose
programme role had just been revoked. The practical payoff: a role change made in
`/profile/` applies on that user's next page load, with no re-login. That matters
here because "Remember me" sessions last two years, so a session-cached role could
otherwise outlive the change by a very long time.

**System Reviewer sees every programme, read-only.** It administers users and needs
oversight of the whole system, so `visible_programs()` and `can_view()` return
everything for it — but it holds no row in `USER_PROGRAM_ROLES`, and `can_review` /
`can_decide` / `can_notify` all key on `role_for()`, which returns `None` for it. So
it can open any application and export, and is refused (403) on review, approval,
rejection and notification. Verified at the view layer, not just in templates.

**Assigning roles is done in `/profile/`, not in SQL.** Both the add-user form and
each row of the user table carry a Travel select and an RFG select, set
independently; an empty value clears access. The legacy Account Type field now only
distinguishes a standard account from a System Reviewer.

Two traps worth knowing about, both hit in practice:

- A `<form>` placed directly inside `<tr>` is invalid HTML. The parser hoists it out
  and drops later rows' `<form>` tags, so **every row submitted the first row's
  values**. The per-user forms now live *after* the table, wired up by the HTML
  `form="urow{{ u.id }}"` attribute on each control.
- Anything that answers "who is the chairman" must join `USER_PROGRAM_ROLES`. A
  chairman appointed through the UI has `USERS.ROLE = 'Reviewer'`, so the old
  `WHERE "ROLE"='Chairman'` query silently skipped them — see
  `backend/views.travel_chairman_emails()`.

### Other RFG facts

- **RFG approval is capped at ₹60,000** (`backend/rfg.RFG_APPROVAL_CAP`), enforced
  server-side. Applicants may *request* more — the applicant-facing form never
  mentions a cap. Travel keeps its fixed ₹60k/₹1,00k dropdown.
- **Tracking codes** for RFG carry an `RFG-` prefix (26 chars max, column is
  `varchar(32)`). Travel codes are unchanged.
- **Uploads are now validated for both programmes**: PDF only, Travel ≤10 MB,
  RFG ≤1 MB. Previously nothing was enforced on this public endpoint.
- RFG validation and field mapping live in **`backend/rfg.py`**, not in
  `submit_travel_grant`. The view branches on `program` and returns early for RFG,
  so the Travel path is byte-identical to before.
- The unified form is one page: 3 shared fields (email, name, institution) →
  programme selector → branch. **The JS validator skips any field failing
  `:visible`**, so both programme trees keep their `required` attributes in markup
  and nothing needs toggling per branch.

### Email behaviour

**Submission emails never fail a submission.** Both programmes go through
`backend/views.send_submission_email()`, which uses `fail_silently=True` and
**logs** any failure. The row is already committed by the time we send, so raising
here used to show a 500 to an applicant whose application had actually succeeded —
and they resubmitted. Because the failure is swallowed, the log line is the only
signal: grep Cloud Logging for `Submission email`.

**The manual notification is the opposite** and deliberately so. `notify_applicant`
keeps `fail_silently=False`: a human clicked "Notify", they need to know if it
didn't go, and `NOTIFIED_STATUS` is written *only after* the mail is away.

### Test environment

Cloud Run service **`stg-app-rfgtest`** → database `stg_rfg_test`, bucket
`student-travel-grant-2026-test-media`. It is a *separate service*, not a tagged
revision, so a test env var can never leak into production's service config, and it
uses `EMAIL_BACKEND=console` so no test can email a real applicant.

Test SQL scripts begin with a `current_database() <> 'stg_rfg_test'` guard that
aborts if pointed at production. Tests are assertions that `RAISE` on failure — a
failed `gcloud sql import sql` **is** a failed test.
