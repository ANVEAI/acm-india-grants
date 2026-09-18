"""Bring the USERS table to the portal's canonical account list.

Run deliberately, never on application start: on Cloud Run a startup hook fires
once per gunicorn worker and again for every cold container, which is no place
for something that can delete accounts.

    python manage.py seed_users                   # add/update the 13, delete nothing
    python manage.py seed_users --delete-others   # also remove everyone else
    python manage.py seed_users --dry-run ...     # report only, change nothing

Two properties of the schema shape this command:

  * USERS.USERNAME carries no unique constraint, so ON CONFLICT is unavailable.
    Each account is matched with an explicit SELECT, then inserted or updated.
  * REVIEWS.USER_ID and FINAL_APPROVALS.CHAIRMAN_ID are ON DELETE CASCADE to
    USERS, so removing an account destroys the reviews it wrote and the
    approvals it signed. --delete-others reports those counts before acting.
"""

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from home import permissions

# md5("12345678"). Unsalted MD5 is what backend/views.py:login_view compares
# against; seeding the same weak scheme the portal already uses beats
# introducing a second one that could not log in.
PASSWORD_MD5 = "25d55ad283aa400af464c76d713c07ad"

TRAVEL = permissions.PROGRAM_TRAVEL
RFG = permissions.PROGRAM_RFG

CHAIRMAN = permissions.ROLE_CHAIRMAN
REVIEWER = permissions.ROLE_REVIEWER
OBSERVER = permissions.ROLE_OBSERVER
FINANCE = permissions.ROLE_FINANCE

# USERS.ROLE is the account type, not the workflow role. Only two values mean
# anything: "System Reviewer" for user administration, and the legacy "Reviewer"
# for an ordinary account. Real authority comes from the programme role, which is
# why every account below except the administrator is a Standard account.
SYSTEM = permissions.SYSTEM_REVIEWER
STANDARD = permissions.STANDARD_ACCOUNT_ROLE

# The single source of truth. Order matters only where these rows are created
# fresh -- /profile/ lists users by ID -- so Travel is grouped ahead of RFG.
SEED_USERS = [
    # name,                  username,         email,                        account,  travel,   rfg
    ("System Reviewer",      "systemreviewer", "systemreviewer@example.com", SYSTEM,   None,     None),

    ("Travel Chair",         "tg-chair",       "tgchair@example.com",        STANDARD, CHAIRMAN, None),
    ("Travel Reviewer 1",    "tg-reviewer1",   "tgreviewer1@example.com",    STANDARD, REVIEWER, None),
    ("Travel Reviewer 2",    "tg-reviewer2",   "tgreviewer2@example.com",    STANDARD, REVIEWER, None),
    ("Travel Reviewer 3",    "tg-reviewer3",   "tgreviewer3@example.com",    STANDARD, REVIEWER, None),
    # tg-finance / rfg-finance are reserved usernames: permissions.finance_program()
    # grants Finance powers only when the username, the Standard account type, an
    # Active status and the Finance programme role all line up.
    ("Travel Grant Finance", "tg-finance",     "tgfinance@example.com",      STANDARD, FINANCE,  None),
    ("Travel Observer",      "tg-observer",    "tgobserver@example.com",     STANDARD, OBSERVER, None),

    ("RFG Chair",            "rfg-chair",      "rfgchair@example.com",       STANDARD, None,     CHAIRMAN),
    ("RFG Reviewer 1",       "rfg-reviewer1",  "rfgreviewer1@example.com",   STANDARD, None,     REVIEWER),
    ("RFG Reviewer 2",       "rfg-reviewer2",  "rfgreviewer2@example.com",   STANDARD, None,     REVIEWER),
    ("RFG Reviewer 3",       "rfg-reviewer3",  "rfgreviewer3@example.com",   STANDARD, None,     REVIEWER),
    ("RFG Finance",          "rfg-finance",    "rfgfinance@example.com",     STANDARD, None,     FINANCE),
    ("RFG Observer",         "rfg-observer",   "rfgobserver@example.com",    STANDARD, None,     OBSERVER),
]

SEED_USERNAMES = [u[1] for u in SEED_USERS]


class Command(BaseCommand):
    help = "Seed the portal's canonical user accounts and their programme access."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete-others", action="store_true",
            help="Remove every user not in the canonical list. This cascades: "
                 "their reviews and approvals go with them.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change and roll back without writing.")

    def handle(self, *args, **options):
        delete_others = options["delete_others"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing will be written\n"))

        created = updated = unchanged = removed = 0

        # One transaction for the whole run, so a failure half way through cannot
        # leave a database with some accounts seeded and others not.
        with transaction.atomic():
            with connection.cursor() as cursor:
                for name, username, email, account, travel, rfg in SEED_USERS:
                    outcome = self._apply_user(
                        cursor, name, username, email, account, travel, rfg)
                    if outcome == "created":
                        created += 1
                        self.stdout.write(self.style.SUCCESS("  + created  %s" % username))
                    elif outcome == "updated":
                        updated += 1
                        self.stdout.write("  ~ updated  %s" % username)
                    else:
                        unchanged += 1
                        self.stdout.write("    ok       %s" % username)

                if delete_others:
                    removed = self._delete_others(cursor)

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(
            "%d created, %d updated, %d already correct, %d removed."
            % (created, updated, unchanged, removed))
        if dry_run:
            self.stdout.write(self.style.WARNING("Rolled back - no changes were written."))
        elif created:
            self.stdout.write("New accounts have the password 12345678.")

    # ------------------------------------------------------------------
    def _apply_user(self, cursor, name, username, email, account, travel, rfg):
        """Insert or update one account, then set both programme roles."""
        cursor.execute(
            'SELECT "ID", "NAME", "EMAIL", "ROLE", "STATUS", "MOBILE_NO" '
            'FROM "USERS" WHERE "USERNAME" = %s', [username])
        row = cursor.fetchone()

        if row is None:
            cursor.execute("""
                INSERT INTO "USERS"
                    ("NAME","USERNAME","EMAIL","MOBILE_NO","ROLE","PASSWORD",
                     "STATUS","CREATED_AT","UPDATED_AT")
                VALUES (%s,%s,%s,NULL,%s,%s,'Active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                RETURNING "ID"
            """, [name, username, email, account, PASSWORD_MD5])
            user_id = cursor.fetchone()[0]
            outcome = "created"
        else:
            user_id = row[0]
            # The password is deliberately absent from this UPDATE. "12345678
            # initially" means at creation; re-running must not undo a password
            # the holder has since changed.
            already_correct = (row[1] == name and row[2] == email
                               and row[3] == account and row[4] == "Active"
                               and row[5] is None)
            if already_correct:
                outcome = "unchanged"
            else:
                cursor.execute("""
                    UPDATE "USERS"
                       SET "NAME" = %s, "EMAIL" = %s, "ROLE" = %s,
                           "MOBILE_NO" = NULL, "STATUS" = 'Active',
                           "UPDATED_AT" = CURRENT_TIMESTAMP
                     WHERE "ID" = %s
                """, [name, email, account, user_id])
                outcome = "updated"

        # set_program_role validates the value and treats "" as "clear access",
        # so this also removes a stray row for the programme this account should
        # have nothing in.
        before = permissions.all_program_roles().get(user_id, {})
        permissions.set_program_role(user_id, TRAVEL, travel or "")
        permissions.set_program_role(user_id, RFG, rfg or "")

        after = {}
        if travel:
            after[TRAVEL] = travel
        if rfg:
            after[RFG] = rfg
        if outcome == "unchanged" and before != after:
            outcome = "updated"

        return outcome

    # ------------------------------------------------------------------
    def _delete_others(self, cursor):
        """Remove users outside the canonical list, reporting the cascade first."""
        cursor.execute("""
            SELECT u."ID", u."USERNAME", u."EMAIL",
                   (SELECT count(*) FROM "REVIEWS" r WHERE r."USER_ID" = u."ID"),
                   (SELECT count(*) FROM "FINAL_APPROVALS" f WHERE f."CHAIRMAN_ID" = u."ID")
              FROM "USERS" u
             WHERE u."USERNAME" <> ALL(%s)
             ORDER BY u."ID"
        """, [SEED_USERNAMES])
        victims = cursor.fetchall()

        if not victims:
            self.stdout.write("\n  no other users to remove")
            return 0

        self.stdout.write(self.style.WARNING("\n  removing %d user(s):" % len(victims)))
        lost_reviews = lost_approvals = 0
        for _uid, username, email, reviews, approvals in victims:
            lost_reviews += reviews
            lost_approvals += approvals
            self.stdout.write(
                "  - %-20s %-32s %d review(s), %d approval(s) cascade"
                % (username, email, reviews, approvals))

        cursor.execute('DELETE FROM "USERS" WHERE "USERNAME" <> ALL(%s)', [SEED_USERNAMES])
        if lost_reviews or lost_approvals:
            self.stdout.write(self.style.WARNING(
                "  cascade removed %d review(s) and %d approval(s)"
                % (lost_reviews, lost_approvals)))
        return len(victims)
