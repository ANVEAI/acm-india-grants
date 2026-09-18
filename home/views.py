from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection, transaction
from django.http import FileResponse, Http404
import os
import re
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.shortcuts import render, redirect
import logging
from django.contrib.auth.models import User
import hashlib
import requests
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.contrib import messages
from django.db import connection
from datetime import date
import json
from django.http import FileResponse, HttpResponseNotFound, HttpResponse, Http404, HttpResponseForbidden
from django.utils.safestring import mark_safe
from datetime import date, datetime
from django.views.decorators.http import require_GET, require_POST
from datetime import datetime, timedelta
from django.utils import timezone
from uuid import UUID
from decimal import Decimal
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.views.decorators.cache import never_cache
from functools import wraps

from home import permissions
from home import mailer, budget as acm_budget
from backend import rfg




def get_db_connection():
    return connection


logger = logging.getLogger('django')


# ============================================
# TIMESTAMP HELPERS
# ============================================
# The APPLICATIONS/REVIEWS/FINAL_APPROVALS timestamp columns are
# `timestamp without time zone` holding UTC, and raw SQL hands them back as
# naive datetimes. Django only localises *aware* values, so naive ones would
# render as UTC regardless of TIME_ZONE. Marking them aware lets Django display
# them in Asia/Kolkata. Nothing stored is modified.

IST = ZoneInfo("Asia/Kolkata")


def _as_utc_aware(value):
    """Tag a naive UTC datetime as aware so templates localise it to IST."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=dt_timezone.utc)
    return value


def _localise_row(row_dict, *keys):
    """Apply _as_utc_aware to the named keys of a dict, in place."""
    for key in keys:
        if key in row_dict:
            row_dict[key] = _as_utc_aware(row_dict[key])
    return row_dict


# ============================================
# NOTIFICATION PERMISSIONS
# ============================================
# Which statuses each role may communicate to the applicant. Reviewers restore
# what the old automatic "Under Review" email did, but manually; the final
# decision stays with the Chairman who made it.
#
# System Reviewer is deliberately absent: it is a user-administration role and
# takes no part in the review workflow (it cannot submit reviews either), so it
# sends no applicant email of any kind.
NOTIFY_PERMISSIONS = permissions.NOTIFY_PERMISSIONS

STATUS_DISPLAY = {
    "SUBMITTED": "Drafted",
    "Drafted": "Drafted",
    "Under Review": "Pending",
    "Pending": "Pending",
    "Accepted": "Approved",
    "Approved": "Approved",
    "APPROVED": "Approved",
    "Rejected": "Not Selected",
    "Not Selected": "Not Selected",
    "Archived": "Archived",
}


def get_status_display(status):
    if not status:
        return ""
    return STATUS_DISPLAY.get(status, status)


_REVIEWER_EVALUATIONS_READY = False


def ensure_reviewer_evaluations_table(cursor):
    """Safety net for databases that predate add_budget_management.sql.

    The schema is owned by that migration, applied to Cloud SQL the way every
    other schema change in this project is. This only creates the table when it
    is genuinely absent, so a fresh local database still works.

    It deliberately does nothing else. The version this replaces also reset a
    column default and ran two UPDATEs against APPLICATIONS on every call -- and
    it is called from the dashboard, the detail page, the evaluation save and
    the public tracking page. Audit fields were cleared and decision status
    rewritten on every page load, and it 500'd outright while DECISION_STATUS
    did not exist. Those backfills now live in the migration and run once.

    Guarded to run at most once per process: DDL per request takes a catalogue
    lock for no benefit.
    """
    global _REVIEWER_EVALUATIONS_READY
    if _REVIEWER_EVALUATIONS_READY:
        return

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS public."REVIEWER_EVALUATIONS" (
            "ID" bigserial PRIMARY KEY,
            "APPLICATION_ID" bigint NOT NULL,
            "USER_ID" bigint NOT NULL,
            "OPENED_AT" timestamp without time zone,
            "SUGGESTED_AMOUNT" numeric(12, 2),
            "COMMITTEE_EVALUATION_NOTES" text,
            "CREATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            "UPDATED_AT" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT "REVIEWER_EVALUATIONS_app_user_uniq" UNIQUE ("APPLICATION_ID", "USER_ID"),
            CONSTRAINT "REVIEWER_EVALUATIONS_user_fk" FOREIGN KEY ("USER_ID") REFERENCES "USERS"("ID") ON DELETE CASCADE,
            CONSTRAINT "REVIEWER_EVALUATIONS_app_fk" FOREIGN KEY ("APPLICATION_ID") REFERENCES "APPLICATIONS"("ID") ON DELETE CASCADE
        );
    """)
    cursor.execute('ALTER TABLE public."REVIEWER_EVALUATIONS" ADD COLUMN IF NOT EXISTS "DECISION_STATUS" character varying(50);')
    _REVIEWER_EVALUATIONS_READY = True


def get_user_application_status(
    raw_status,
    program,
    user_id=None,
    user_role=None,
    application_id=None,
    reviewer_opens_by_app=None,
    program_reviewers=None,
    cursor=None
):
    """Computes application status (Drafted, Pending, Approved, Not Selected, Archived)
    based on per-user reviewer open rules:
    - Approved / Accepted -> 'Approved' for everyone
    - Not Selected / Rejected -> 'Not Selected' for everyone
    - Archived -> 'Archived' for everyone
    - Otherwise:
      - If user is an active Reviewer for this program:
        - Shows 'Pending' if this reviewer has opened the application
        - Otherwise 'Drafted'
      - Non-reviewers (Chairman, Finance, Observer, Student, etc.):
        - Shows 'Pending' if all active reviewers for this program have opened the application
        - Otherwise 'Drafted'
    """
    if raw_status in ("Accepted", "Approved", "APPROVED"):
        return "Approved"
    if raw_status in ("Rejected", "Not Selected"):
        return "Not Selected"
    if raw_status == "Archived":
        return "Archived"

    assigned_revs = set()
    if program_reviewers is not None and program in program_reviewers:
        assigned_revs = program_reviewers[program]
    elif cursor is not None and program:
        cursor.execute("""
            SELECT upr."USER_ID"
            FROM "USER_PROGRAM_ROLES" upr
            JOIN "USERS" u ON u."ID" = upr."USER_ID"
            WHERE upr."PROGRAM" = %s AND upr."ROLE" = 'Reviewer' AND (u."STATUS" = 'Active' OR u."STATUS" IS NULL);
        """, [program])
        assigned_revs = set(r[0] for r in cursor.fetchall())

    opened_revs = set()
    if reviewer_opens_by_app is not None and application_id in reviewer_opens_by_app:
        opened_revs = reviewer_opens_by_app[application_id] & assigned_revs
    elif cursor is not None and application_id is not None:
        cursor.execute("""
            SELECT re."USER_ID"
            FROM "REVIEWER_EVALUATIONS" re
            WHERE re."APPLICATION_ID" = %s AND re."OPENED_AT" IS NOT NULL;
        """, [application_id])
        opened_revs = set(r[0] for r in cursor.fetchall()) & assigned_revs

    is_user_a_reviewer = (user_role == "Reviewer" and user_id is not None and user_id in assigned_revs)

    if is_user_a_reviewer:
        if user_id in opened_revs:
            return "Pending"
        return "Drafted"
    else:
        all_opened = (len(assigned_revs) > 0 and len(opened_revs) >= len(assigned_revs))
        if all_opened:
            return "Pending"
        return "Drafted"




def _program_of(app_id):
    """Programme of an application, or None if it does not exist.

    Rows predating the PROGRAM column read as Travel via the column default.
    """
    with connection.cursor() as cursor:
        cursor.execute('SELECT "PROGRAM" FROM "APPLICATIONS" WHERE "ID" = %s', [app_id])
        row = cursor.fetchone()
    if not row:
        return None
    return row[0] or permissions.PROGRAM_TRAVEL


def list_uploaded_documents(request):
    try:
        with connection.cursor() as cursor:
            query = '''
                SELECT "TITLE", "CATEGORY", "PDF_NAME", "UPLOADED_BY", "CREATED_AT", "UPDATED_AT","DOMAIN"
                FROM "DOCUMENTS_UPLOADED"
            '''
            cursor.execute(query)
            documents = cursor.fetchall()

            # Prepare data as a list of dictionaries
            documents_list = [
                {
                    'title': row[0],
                    'category': row[1],
                    'pdf_name': row[2],
                    'uploaded_by': row[3],
                    'created_at': row[4],
                    'updated_at': row[5],
                    'domain':row[6]
                }
                for row in documents
            ]
            return JsonResponse(documents_list, safe=False)  # Return JSON response

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    
def custom_login_required(view_func):
    @wraps(view_func)
    @never_cache
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        else:
            return redirect('login')  # Redirect to login page if not authenticated
    return _wrapped_view


@never_cache
def logout_view(request):
    logger.info(f"User  {request.user.username} is logging out.")
    print(f"INFO: User {request.user.username} is logging out.")

    auth_logout(request)  # Log the user out

    logger.info("User  logged out successfully.")
    print("INFO: User logged out successfully.")

    return redirect('login')  # Redirect to the login page or any other page


def help_page(request):
    return render(request, 'help.html')


@custom_login_required
def budget_management(request):
    finance_program = permissions.finance_program(request)
    is_finance_user = finance_program is not None

    # Non-Finance users get read-only access; unauthenticated or unknown users are blocked
    if not is_finance_user and not permissions.can_view_budget(request):
        return HttpResponseForbidden("You do not have permission to access this page.")

    if is_finance_user:
        program_label = permissions.PROGRAM_LABELS[finance_program]
        finance_role = permissions.ROLE_FINANCE

        if request.method == "POST":
            total_raw = request.POST.get("total_budget", "").strip()
            try:
                total = Decimal(total_raw)
                if not total.is_finite():
                    raise ValueError
            except (ArithmeticError, ValueError):
                messages.error(request, f"Enter a valid total {program_label} budget.")
                return redirect("budget_management")

            if total <= 0:
                messages.error(request, f"Total {program_label} budget must be greater than zero.")
                return redirect("budget_management")
            if total > Decimal("9999999999999"):
                messages.error(request, f"The total {program_label} budget exceeds the supported limit.")
                return redirect("budget_management")
            if total != total.to_integral_value():
                messages.error(request, f"Enter the total {program_label} budget in whole rupees.")
                return redirect("budget_management")

            editor_name = (
                request.session.get("user_name")
                or request.session.get("user_email")
                or finance_role
            )[:255]

            with transaction.atomic():
                with connection.cursor() as cursor:
                    acm_budget.lock_ledger(cursor)
                    if not acm_budget.table_exists(cursor):
                        return render(
                            request,
                            "budget_management.html",
                            {
                                "budget": {"schema_ready": False, "configured": False},
                                "program": finance_program,
                                "program_label": program_label,
                                "finance_role": finance_role,
                                "is_finance_user": True,
                            },
                            status=503)

                    minimum_total = acm_budget.minimum_total_for_current_approvals(
                        cursor, finance_program)
                    if total < minimum_total:
                        messages.error(
                            request,
                            "The %s budget cannot be reduced below %s because of existing approved grants."
                            % (program_label, acm_budget.format_money(minimum_total)))
                        return redirect("budget_management")

                    acm_budget.save_total(
                        cursor, finance_program, total, editor_name, timezone.now())

            messages.success(request, f"The {program_label} budget was updated successfully.")
            return redirect("budget_management")

        with connection.cursor() as cursor:
            budget_summary = acm_budget.summary(cursor, finance_program)
        if budget_summary.get("updated_at"):
            budget_summary["updated_at"] = _as_utc_aware(budget_summary["updated_at"])

        return render(request, "budget_management.html", {
            "budget": budget_summary,
            "program": finance_program,
            "program_label": program_label,
            "finance_role": finance_role,
            "is_finance_user": True,
        })

    # Non-Finance users: budget overview is now hosted directly on the dashboard
    if not is_finance_user:
        if not permissions.can_view_budget(request):
            return HttpResponseForbidden("You do not have permission to access this page.")
        return redirect("dashboard")


# Create your views here.


from django.shortcuts import render
from django.db import connection

@custom_login_required
def dashboard(request):
    # --- User info from session ---
    user_name = request.session.get('user_name')
    user_email = request.session.get('user_email')
    user_role = request.session.get('user_role')
    user_id = request.session.get('user_id')

    # Programme roles determine the list. Finance is read-only and is confined
    # to the single programme associated with its reserved username.
    programs = permissions.visible_programs(request)

    # -------------------------
    # Applications list
    # -------------------------
    rows = []
    applications = []
    program_reviewers = {}
    reviewer_opens_by_app = {}

    if programs:
        with connection.cursor() as cursor:
            ensure_reviewer_evaluations_table(cursor)
            cursor.execute("""
                SELECT
                    "ID",
                    "TRACKING_CODE",
                    "APPLICANT_NAME",
                    "PAPER_TITLE",
                    "CONFERENCE_NAME",
                    "STATUS",
                    "PAPER_FILE_PATH",
                    "CREATED_AT",
                    "PROGRAM"
                FROM "APPLICATIONS"
                WHERE "PROGRAM" = ANY(%s)
                ORDER BY "CREATED_AT" DESC;
            """, [programs])
            rows = cursor.fetchall()

            # Load active reviewer IDs for the programs
            cursor.execute("""
                SELECT upr."PROGRAM", upr."USER_ID"
                FROM "USER_PROGRAM_ROLES" upr
                JOIN "USERS" u ON u."ID" = upr."USER_ID"
                WHERE upr."PROGRAM" = ANY(%s) AND upr."ROLE" = 'Reviewer' AND (u."STATUS" = 'Active' OR u."STATUS" IS NULL);
            """, [programs])
            for prog, uid in cursor.fetchall():
                program_reviewers.setdefault(prog, set()).add(uid)

            # Load opened reviewers for all applications
            cursor.execute("""
                SELECT re."APPLICATION_ID", re."USER_ID"
                FROM "REVIEWER_EVALUATIONS" re
                WHERE re."OPENED_AT" IS NOT NULL;
            """)
            for aid, uid in cursor.fetchall():
                reviewer_opens_by_app.setdefault(aid, set()).add(uid)

    for r in rows:
        app_id = r[0]
        raw_status = r[5]
        prog = r[8]
        user_status = get_user_application_status(
            raw_status=raw_status,
            program=prog,
            user_id=user_id,
            user_role=user_role,
            application_id=app_id,
            reviewer_opens_by_app=reviewer_opens_by_app,
            program_reviewers=program_reviewers,
        )
        applications.append({
            "id": r[0],
            "tracking_code": r[1],
            "applicant_name": r[2],
            "paper_title": r[3],
            "conference_name": r[4],
            "status": user_status,
            "status_display": user_status,
            "raw_status": raw_status,
            "paper_file_path": r[6],
            "created_at": r[7],
            "program": r[8],
            "program_label": permissions.PROGRAM_LABELS.get(r[8], r[8]),
        })

    total = len(applications)
    drafted = sum(1 for a in applications if a["status"] == "Drafted")
    pending = sum(1 for a in applications if a["status"] == "Pending")
    approved = sum(1 for a in applications if a["status"] == "Approved")
    not_selected = sum(1 for a in applications if a["status"] == "Not Selected")

    insights = {
        "total": total,
        "submitted": drafted,
        "drafted": drafted,
        "under_review": pending,
        "pending": pending,
        "approved": approved,
        "rejected": not_selected,
        "not_selected": not_selected,
    }

    # -------------------------
    # Profile image
    # -------------------------
    profile_image_url = None
    if user_name:
        image_name = f"avatar_{user_email}.jpg"
        image_path = os.path.join(settings.MEDIA_ROOT, 'profile', image_name)
        if os.path.exists(image_path):
            profile_image_url = f"/media/profile/{image_name}"

    # -------------------------
    # Budget overview (for users with can_view_budget)
    # -------------------------
    budgets = []
    if permissions.can_view_budget(request):
        with connection.cursor() as cursor:
            for prog in programs:
                summary = acm_budget.summary(cursor, prog)
                if summary.get("updated_at"):
                    summary["updated_at"] = _as_utc_aware(summary["updated_at"])
                budgets.append({
                    "program": prog,
                    "program_label": permissions.PROGRAM_LABELS.get(prog, prog),
                    "budget": summary,
                })

    return render(request, "dashboard.html", {
        "user_name": user_name,
        "user_email": user_email,
        "user_role": user_role,
        "applications": applications,
        "insights": insights,
        "profile_image_url": profile_image_url,
        "decide_programs": [pr for pr in programs if permissions.can_decide(request, pr)],
        "has_program_access": bool(programs),
        "show_program_column": len(programs) > 1,
        "budgets": budgets,
    })

# def application_details(request, app_id):
#     user_role = request.session.get('user_role')
#     user_id = request.session.get('user_id')
#     user_name = request.session.get('user_name')

#     with connection.cursor() as cursor:

#         # Reviewer opens first time → mark under review
#         if user_role == "Reviewer":
#             cursor.execute("""
#                 UPDATE "APPLICATIONS"
#                 SET
#                     "STATUS" = 'Under Review',
#                     "REVIEWED_ONCE" = TRUE,
#                     "REVIEWED_AT" = %s
#                 WHERE "ID" = %s
#                   AND "REVIEWED_ONCE" = FALSE;
#             """, [timezone.now(), app_id])

#         # Fetch application
#         cursor.execute("""
#             SELECT *
#             FROM "APPLICATIONS"
#             WHERE "ID" = %s;
#         """, [app_id])

#         row = cursor.fetchone()
#         if not row:
#             return render(request, "error.html", {"error": "Application not found"}, status=404)

#         colnames = [desc[0].lower() for desc in cursor.description]
#         application = dict(zip(colnames, row))

#         # Fetch reviews
#         cursor.execute("""
#             SELECT r."ID", r."RATING", r."FEEDBACK", r."CREATED_AT", u."NAME"
#             FROM "REVIEWS" r
#             JOIN "USERS" u ON r."USER_ID" = u."ID"
#             WHERE r."APPLICATION_ID" = %s
#             ORDER BY r."CREATED_AT" DESC;
#         """, [app_id])

#         reviews = [
#             {
#                 "id": r[0],
#                 "rating": r[1],
#                 "feedback": r[2],
#                 "created_at": r[3],
#                 "reviewer_name": r[4]
#             }
#             for r in cursor.fetchall()
#         ]

#         # User's own review
#         user_review = next(
#             (r for r in reviews if r["reviewer_name"] == user_name),
#             None
#         )

#         # Fetch final approval
#         cursor.execute("""
#             SELECT fa."APPROVED_AMOUNT",
#                    fa."FEEDBACK",
#                    fa."CREATED_AT",
#                    u."NAME"
#             FROM "FINAL_APPROVALS" fa
#             JOIN "USERS" u ON fa."CHAIRMAN_ID" = u."ID"
#             WHERE fa."APPLICATION_ID" = %s
#             LIMIT 1;
#         """, [app_id])

#         fa = cursor.fetchone()
#         final_approval = None
#         approved_amount = None

#         if fa:
#             final_approval = {
#                 "amount": fa[0],
#                 "feedback": fa[1],
#                 "created_at": fa[2],
#                 "chairman_name": fa[3],
#             }
#             approved_amount = fa[0]  # Pass to template

#     return render(request, "details.html", {
#         "application": application,
#         "reviews": reviews,
#         "user_review": user_review,
#         "final_approval": final_approval,
#         "approved_amount": approved_amount,
#         "user_role": user_role,
#     })

@custom_login_required
def application_details(request, app_id):
    user_role = request.session.get('user_role')
    user_id = request.session.get('user_id')
    user_name = request.session.get('user_name')

    # Which programme is this application in? Decides both whether the user may
    # see it at all and which role of theirs applies.
    with connection.cursor() as cursor:
        cursor.execute('SELECT "PROGRAM" FROM "APPLICATIONS" WHERE "ID" = %s', [app_id])
        program_row = cursor.fetchone()

    if not program_row:
        return render(request, "404.html", {"message": "Application not found"}, status=404)

    program = program_row[0] or permissions.PROGRAM_TRAVEL

    if not permissions.can_view(request, program):
        messages.error(
            request,
            "You do not have access to %s applications."
            % permissions.PROGRAM_LABELS.get(program, program))
        return redirect('dashboard')

    with connection.cursor() as cursor:
        ensure_reviewer_evaluations_table(cursor)

        is_reviewer = (permissions.role_for(request, program) == permissions.ROLE_REVIEWER)
        if is_reviewer and user_id:
            now_dt = timezone.now()
            cursor.execute("""
                INSERT INTO "REVIEWER_EVALUATIONS" ("APPLICATION_ID", "USER_ID", "OPENED_AT")
                VALUES (%s, %s, %s)
                ON CONFLICT ("APPLICATION_ID", "USER_ID")
                DO UPDATE SET "OPENED_AT" = COALESCE("REVIEWER_EVALUATIONS"."OPENED_AT", EXCLUDED."OPENED_AT");
            """, [app_id, user_id, now_dt])

            # Check if all active assigned reviewers for this program have opened
            cursor.execute("""
                SELECT upr."USER_ID"
                FROM "USER_PROGRAM_ROLES" upr
                JOIN "USERS" u ON u."ID" = upr."USER_ID"
                WHERE upr."PROGRAM" = %s AND upr."ROLE" = 'Reviewer' AND (u."STATUS" = 'Active' OR u."STATUS" IS NULL);
            """, [program])
            assigned_revs = set(r[0] for r in cursor.fetchall())

            cursor.execute("""
                SELECT re."USER_ID"
                FROM "REVIEWER_EVALUATIONS" re
                WHERE re."APPLICATION_ID" = %s AND re."OPENED_AT" IS NOT NULL;
            """, [app_id])
            opened_revs = set(r[0] for r in cursor.fetchall()) & assigned_revs

            if len(assigned_revs) > 0 and len(opened_revs) >= len(assigned_revs):
                cursor.execute("""
                    UPDATE "APPLICATIONS"
                    SET
                        "STATUS" = CASE WHEN "STATUS" IN ('SUBMITTED', 'Drafted') THEN 'Under Review' ELSE "STATUS" END,
                        "DECISION_STATUS" = CASE
                            WHEN "DECISION_STATUS" IN ('SUBMITTED', 'Drafted', '') OR "DECISION_STATUS" IS NULL THEN 'Pending'
                            ELSE "DECISION_STATUS"
                        END,
                        "REVIEWED_ONCE" = TRUE,
                        "REVIEWED_AT" = COALESCE("REVIEWED_AT", %s)
                    WHERE "ID" = %s
                      AND "STATUS" NOT IN ('Accepted', 'Approved', 'Rejected');
                """, [now_dt, app_id])

        # Fetch application
        cursor.execute("""
            SELECT *
            FROM "APPLICATIONS"
            WHERE "ID" = %s;
        """, [app_id])

        row = cursor.fetchone()
        if not row:
            return render(request, "error.html", {"error": "Application not found"}, status=404)

        colnames = [desc[0].lower() for desc in cursor.description]
        application = dict(zip(colnames, row))

        # Resolve status display per user
        computed_status = get_user_application_status(
            raw_status=application.get("status"),
            program=program,
            user_id=user_id,
            user_role=user_role,
            application_id=app_id,
            cursor=cursor
        )
        application["status"] = computed_status
        application["status_display"] = computed_status
        application["notified_status_display"] = get_status_display(application.get("notified_status"))

        # Resolve Decision Status for Budget Details section:
        cursor.execute("""
            SELECT COUNT(*) FROM "FINAL_APPROVALS" WHERE "APPLICATION_ID" = %s
        """, [app_id])
        has_fa_record = cursor.fetchone()[0] > 0

        raw_app_status = row[colnames.index("status")] if "status" in colnames else application.get("status")
        db_decision_status = row[colnames.index("decision_status")] if "decision_status" in colnames else application.get("decision_status")
        budget_edited_by = application.get("budget_edited_by") or ""
        is_chairman_budget_edit = "Chairman" in budget_edited_by

        if has_fa_record or raw_app_status in ("Accepted", "Approved", "APPROVED"):
            application["decision_status"] = "Approved"
        elif raw_app_status in ("Rejected", "Not Selected"):
            application["decision_status"] = "Not Selected"
        elif is_chairman_budget_edit and db_decision_status in ("Approved", "Rejected", "Not Selected", "Pending", "Drafted"):
            application["decision_status"] = get_status_display(db_decision_status)
        else:
            # Chairman has not decided yet.
            # Decision Status in Budget Details depends strictly on whether all reviewers opened:
            cursor.execute("""
                SELECT upr."USER_ID"
                FROM "USER_PROGRAM_ROLES" upr
                JOIN "USERS" u ON u."ID" = upr."USER_ID"
                WHERE upr."PROGRAM" = %s AND upr."ROLE" = 'Reviewer' AND (u."STATUS" = 'Active' OR u."STATUS" IS NULL);
            """, [program])
            all_assigned_revs = set(r[0] for r in cursor.fetchall())

            cursor.execute("""
                SELECT re."USER_ID"
                FROM "REVIEWER_EVALUATIONS" re
                WHERE re."APPLICATION_ID" = %s AND re."OPENED_AT" IS NOT NULL;
            """, [app_id])
            all_opened_revs = set(r[0] for r in cursor.fetchall()) & all_assigned_revs

            if len(all_assigned_revs) > 0 and len(all_opened_revs) >= len(all_assigned_revs):
                application["decision_status"] = "Pending"
                if db_decision_status != 'Pending' and raw_app_status not in ("Accepted", "Approved", "Rejected"):
                    cursor.execute("""
                        UPDATE "APPLICATIONS"
                        SET "DECISION_STATUS" = 'Pending',
                            "STATUS" = CASE WHEN "STATUS" IN ('SUBMITTED', 'Drafted') THEN 'Under Review' ELSE "STATUS" END
                        WHERE "ID" = %s;
                    """, [app_id])
            else:
                application["decision_status"] = "Drafted"
                if db_decision_status != 'Drafted' and raw_app_status not in ("Accepted", "Approved", "Rejected"):
                    cursor.execute("""
                        UPDATE "APPLICATIONS"
                        SET "DECISION_STATUS" = 'Drafted'
                        WHERE "ID" = %s;
                    """, [app_id])


        _localise_row(
            application,
            'created_at', 'updated_at', 'reviewed_at', 'notified_at',
            'budget_edited_at')

        # RFG-specific fields live in a child row; Travel applications have none.
        rfg_detail = None
        if program == permissions.PROGRAM_RFG:
            cursor.execute('SELECT * FROM "RFG_DETAILS" WHERE "APPLICATION_ID" = %s', [app_id])
            detail_row = cursor.fetchone()
            if detail_row:
                detail_cols = [d[0].lower() for d in cursor.description]
                rfg_detail = dict(zip(detail_cols, detail_row))
                rfg_detail["scheme_label"] = rfg.SCHEME_LABELS.get(
                    rfg_detail.get("scheme"), rfg_detail.get("scheme"))

        # Fetch evaluations for all active reviewers assigned to this program
        cursor.execute("""
            SELECT
                u."ID",
                u."NAME",
                u."EMAIL",
                re."OPENED_AT",
                re."SUGGESTED_AMOUNT",
                re."COMMITTEE_EVALUATION_NOTES",
                re."UPDATED_AT",
                re."DECISION_STATUS"
            FROM "USERS" u
            JOIN "USER_PROGRAM_ROLES" upr ON u."ID" = upr."USER_ID"
            LEFT JOIN "REVIEWER_EVALUATIONS" re
                ON re."USER_ID" = u."ID" AND re."APPLICATION_ID" = %s
            WHERE upr."PROGRAM" = %s AND upr."ROLE" = 'Reviewer' AND (u."STATUS" = 'Active' OR u."STATUS" IS NULL)
            ORDER BY u."ID" ASC;
        """, [app_id, program])
        reviewer_evaluations = [
            {
                "user_id": r[0],
                "name": r[1],
                "email": r[2],
                "opened_at": _as_utc_aware(r[3]),
                "suggested_amount": r[4],
                "committee_evaluation_notes": r[5],
                "updated_at": _as_utc_aware(r[6]),
                "decision_status": get_status_display(r[7]) if r[7] else None,
                "is_current_user": (r[0] == user_id),
            }
            for r in cursor.fetchall()
        ]
        current_user_eval = next(
            (re for re in reviewer_evaluations if re["is_current_user"]),
            None
        )

        # Fetch reviews
        cursor.execute("""
            SELECT r."ID", r."RATING", r."FEEDBACK", r."CREATED_AT", u."NAME", r."USER_ID"
            FROM "REVIEWS" r
            JOIN "USERS" u ON r."USER_ID" = u."ID"
            WHERE r."APPLICATION_ID" = %s
            ORDER BY r."CREATED_AT" DESC;
        """, [app_id])

        reviews = [
            {
                "id": r[0],
                "rating": r[1],
                "feedback": r[2],
                "created_at": _as_utc_aware(r[3]),
                "reviewer_name": r[4],
                "user_id": r[5],
            }
            for r in cursor.fetchall()
        ]

        # User's own review
        user_review = next(
            (r for r in reviews if (user_id and r.get("user_id") == user_id) or r["reviewer_name"] == user_name),
            None
        )

        # Fetch final approval
        cursor.execute("""
            SELECT fa."APPROVED_AMOUNT",
               fa."FEEDBACK",
               fa."CREATED_AT",
               u."NAME"
            FROM "FINAL_APPROVALS" fa
            JOIN "USERS" u ON fa."CHAIRMAN_ID" = u."ID"
            WHERE fa."APPLICATION_ID" = %s
            LIMIT 1;
        """, [app_id])

        fa = cursor.fetchone()
        final_approval = None
        approved_amount = None

        if fa and application.get("status") in ("Accepted", "Approved"):
            final_approval = {
                "amount": fa[0],
                "feedback": fa[1],
                "created_at": _as_utc_aware(fa[2]),
                "chairman_name": fa[3],
            }
            approved_amount = fa[0]  # Pass to template

        cursor.execute("""
            SELECT COUNT(*) FROM "FINAL_APPROVALS" WHERE "APPLICATION_ID" = %s
        """, [app_id])
        has_fa_record = cursor.fetchone()[0] > 0
        is_already_approved = has_fa_record or (application.get("status") in ("Accepted", "Approved")) or (application.get("decision_status") == "Approved")
        is_rejected = (application.get("status") in ("Rejected", "Not Selected")) or (application.get("decision_status") in ("Rejected", "Not Selected"))
        can_edit_budget = permissions.can_edit_budget(request, program)
        can_decide = permissions.can_decide(request, program)
        can_edit_budget_details = can_edit_budget and can_decide and (is_already_approved or is_rejected)

        if is_already_approved:
            for rev in reviewer_evaluations:
                rev["decision_status"] = "Approved By Chairman"

    return render(request, "details.html", {
        "application": application,
        "reviews": reviews,
        "user_review": user_review,
        "final_approval": final_approval,
        "approved_amount": approved_amount,
        "is_already_approved": is_already_approved,
        "is_rejected": is_rejected,
        "can_edit_budget_details": can_edit_budget_details,
        "user_role": user_role,
        "program": program,
        "program_label": permissions.PROGRAM_LABELS.get(program, program),
        "rfg_detail": rfg_detail,
        "rfg_cap": rfg.RFG_APPROVAL_CAP,
        "is_observer": permissions.is_observer(request, program),
        "can_review": permissions.can_review(request, program),
        "can_edit_budget": can_edit_budget,
        "can_decide": can_decide,
        "can_notify": permissions.can_notify(request, program,
                                             application.get("status"),
                                             application.get("notified_status")),
        "reviewer_evaluations": reviewer_evaluations,
        "current_user_eval": current_user_eval,
        "is_reviewer": is_reviewer,
        "is_student": False,
    })



@custom_login_required
@require_POST
def update_budget_details(request, app_id):
    """Update committee evaluation fields in Budget Details."""
    program = _program_of(app_id)
    if program is None:
        return render(request, "404.html", {"message": "Application not found"}, status=404)

    if not permissions.can_edit_budget(request, program):
        return HttpResponseForbidden("You do not have permission to edit budget details.")

    decision_status = request.POST.get("decision_status", "").strip()
    approved_support_amount_raw = request.POST.get("approved_support_amount", "").strip()
    committee_evaluation_notes = request.POST.get("committee_evaluation_notes", "").strip()

    VALID_DECISION_STATUSES = ("Drafted", "Pending", "Approved", "Rejected", "Not Selected")
    if decision_status and decision_status not in VALID_DECISION_STATUSES:
        messages.error(request, "Invalid decision status selected.")
        return redirect("application_details", app_id=app_id)

    approved_support_amount = None
    if approved_support_amount_raw:
        try:
            approved_support_amount = Decimal(approved_support_amount_raw)
            if not approved_support_amount.is_finite() or approved_support_amount < 0:
                raise ValueError
        except (ArithmeticError, ValueError):
            messages.error(request, "Approved support amount must be a valid non-negative number.")
            return redirect("application_details", app_id=app_id)
        if approved_support_amount > Decimal("9999999999999.99"):
            messages.error(request, "Approved support amount exceeds the supported limit.")
            return redirect("application_details", app_id=app_id)
        if approved_support_amount.normalize().as_tuple().exponent < -2:
            messages.error(request, "Approved support amount can have at most two decimal places.")
            return redirect("application_details", app_id=app_id)

    editor_name = (
        request.session.get("user_name")
        or request.session.get("user_email")
        or "Unknown user"
    )
    editor_role = permissions.role_for(request, program)
    editor_label = f"{editor_name} ({editor_role})"[:255]

    edited_at = timezone.now()
    with transaction.atomic():
        with connection.cursor() as cursor:
            acm_budget.lock_ledger(cursor)
            cursor.execute(
                'SELECT "STATUS", "DECISION_STATUS", "TRAVEL_BUDGET" FROM "APPLICATIONS" WHERE "ID" = %s FOR UPDATE',
                [app_id])
            app_row = cursor.fetchone()
            if not app_row:
                messages.error(request, "Application not found.")
                return redirect("dashboard")
            current_status, current_decision, travel_budget = app_row[0], app_row[1], app_row[2]
            requested_budget = Decimal(str(travel_budget or 0))

            cursor.execute(
                'SELECT COUNT(*) FROM "FINAL_APPROVALS" WHERE "APPLICATION_ID" = %s',
                [app_id])
            has_final_approval = cursor.fetchone()[0] > 0
            is_approved = (current_status in ("Accepted", "Approved") or has_final_approval)
            is_rejected = (current_status in ("Rejected", "Not Selected") or current_decision in ("Rejected", "Not Selected"))

            if not (is_approved or is_rejected):
                messages.error(
                    request,
                    "Initial approval must be completed through the Review and Final Approval workflow before Budget Details can be edited."
                )
                return redirect("application_details", app_id=app_id)

            if decision_status in ("Drafted", "Pending", "Rejected", "Not Selected"):
                if not permissions.can_decide(request, program):
                    messages.error(request, "Only the Chairman can change the decision status.")
                    return redirect("application_details", app_id=app_id)

                # When changed to Rejected/Not Selected/Pending/Drafted, approved amount must be empty
                approved_support_amount = None
                new_app_status = {
                    "Drafted": "SUBMITTED",
                    "Pending": "Under Review",
                    "Rejected": "Rejected",
                    "Not Selected": "Rejected",
                }.get(decision_status, current_status)
                db_decision_status = "Rejected" if decision_status == "Not Selected" else decision_status

                clear_rejection = (decision_status in ("Drafted", "Pending"))
                cursor.execute("""
                    UPDATE "APPLICATIONS"
                    SET "STATUS" = %s,
                        "DECISION_STATUS" = %s,
                        "APPROVED_SUPPORT_AMOUNT" = NULL,
                        "COMMITTEE_EVALUATION_NOTES" = %s,
                        "REJECTION_REASON" = CASE WHEN %s THEN NULL ELSE "REJECTION_REASON" END,
                        "BUDGET_EDITED_BY" = %s,
                        "BUDGET_EDITED_AT" = %s,
                        "UPDATED_AT" = %s
                    WHERE "ID" = %s
                """, [
                    new_app_status,
                    db_decision_status,
                    committee_evaluation_notes,
                    clear_rejection,
                    editor_label,
                    edited_at,
                    edited_at,
                    app_id,
                ])

                # Delete from FINAL_APPROVALS so approval state is completely cleared
                cursor.execute("""
                    DELETE FROM "FINAL_APPROVALS"
                    WHERE "APPLICATION_ID" = %s
                """, [app_id])

                messages.success(
                    request,
                    f"Application status changed to {get_status_display(decision_status)}. Approved support amount has been cleared."
                )
                return redirect("application_details", app_id=app_id)

            elif decision_status == "Approved":
                if not permissions.can_decide(request, program):
                    messages.error(request, "Only the Chairman can approve an application.")
                    return redirect("application_details", app_id=app_id)

                if approved_support_amount is None:
                    messages.error(request, "Approved support amount is required when status is Approved.")
                    return redirect("application_details", app_id=app_id)

                if approved_support_amount <= 0:
                    messages.error(request, "Approved support amount must be greater than zero.")
                    return redirect("application_details", app_id=app_id)

                if approved_support_amount > requested_budget:
                    messages.error(
                        request,
                        f"Approved support amount (₹{approved_support_amount:,.2f}) cannot exceed the amount requested by the student (₹{requested_budget:,.2f})."
                    )
                    return redirect("application_details", app_id=app_id)

                if program == permissions.PROGRAM_TRAVEL and approved_support_amount > Decimal("100000"):
                    messages.error(request, "Travel Grant approvals cannot exceed Rs. 1,00,000.")
                    return redirect("application_details", app_id=app_id)

                if (program == permissions.PROGRAM_RFG
                        and approved_support_amount > Decimal(str(rfg.RFG_APPROVAL_CAP))):
                    messages.error(
                        request,
                        "Research Facilitation Grant approvals cannot exceed Rs. %s."
                        % f"{rfg.RFG_APPROVAL_CAP:,}")
                    return redirect("application_details", app_id=app_id)

                total_budget = acm_budget.load_total(
                    cursor, program, for_update=True)
                if total_budget is not None:
                    available = acm_budget.available_for(
                        cursor,
                        total_budget,
                        program,
                        exclude_application_id=app_id)
                    if approved_support_amount > available:
                        messages.error(
                            request,
                            "Approved amount cannot exceed the available %s budget of %s."
                            % (
                                permissions.PROGRAM_LABELS.get(program, program),
                                acm_budget.format_money(max(available, Decimal("0"))),
                            ))
                        return redirect("application_details", app_id=app_id)

                cursor.execute("""
                    UPDATE "APPLICATIONS"
                    SET "STATUS" = 'Accepted',
                        "DECISION_STATUS" = 'Approved',
                        "APPROVED_SUPPORT_AMOUNT" = %s,
                        "COMMITTEE_EVALUATION_NOTES" = %s,
                        "REJECTION_REASON" = NULL,
                        "BUDGET_EDITED_BY" = %s,
                        "BUDGET_EDITED_AT" = %s,
                        "UPDATED_AT" = %s
                    WHERE "ID" = %s
                """, [
                    approved_support_amount,
                    committee_evaluation_notes,
                    editor_label,
                    edited_at,
                    edited_at,
                    app_id,
                ])

                cursor.execute("""
                    UPDATE "FINAL_APPROVALS"
                    SET "APPROVED_AMOUNT" = %s
                    WHERE "APPLICATION_ID" = %s
                """, [approved_support_amount, app_id])

                if cursor.rowcount == 0:
                    cursor.execute("""
                        SELECT u."ID" FROM "USERS" u
                        JOIN "USER_PROGRAM_ROLES" up ON up."USER_ID" = u."ID"
                        WHERE up."PROGRAM" = %s AND up."ROLE" = 'Chairman'
                        LIMIT 1
                    """, [program])
                    chair_row = cursor.fetchone()
                    chairman_id = request.session.get("user_id") or (chair_row[0] if chair_row else None)

                    cursor.execute("""
                        INSERT INTO "FINAL_APPROVALS"
                        ("APPLICATION_ID", "CHAIRMAN_ID", "APPROVED_AMOUNT", "FEEDBACK")
                        VALUES (%s, %s, %s, %s)
                    """, [app_id, chairman_id, approved_support_amount, committee_evaluation_notes or "Approved via Budget Details"])

                messages.success(
                    request,
                    f"Budget details updated. Approved amount set to ₹{approved_support_amount:,.2f}."
                )
                return redirect("application_details", app_id=app_id)

            else:
                cursor.execute("""
                    UPDATE "APPLICATIONS"
                    SET "COMMITTEE_EVALUATION_NOTES" = %s,
                        "BUDGET_EDITED_BY" = %s,
                        "BUDGET_EDITED_AT" = %s,
                        "UPDATED_AT" = %s
                    WHERE "ID" = %s
                """, [
                    committee_evaluation_notes,
                    editor_label,
                    edited_at,
                    edited_at,
                    app_id,
                ])
                messages.success(request, "Budget details updated successfully.")
                return redirect("application_details", app_id=app_id)


@custom_login_required
@require_POST
def save_reviewer_evaluation(request, app_id):
    """Save reviewer's committee evaluation notes and suggested support amount."""
    user_id = request.session.get('user_id')
    user_role = request.session.get('user_role')
    program = _program_of(app_id)
    if program is None:
        return render(request, "404.html", {"message": "Application not found"}, status=404)

    if not permissions.can_review(request, program):
        return HttpResponseForbidden("You do not have permission to submit reviewer evaluations.")

    with connection.cursor() as cursor:
        ensure_reviewer_evaluations_table(cursor)
        cursor.execute('SELECT "TRAVEL_BUDGET", "STATUS" FROM "APPLICATIONS" WHERE "ID" = %s', [app_id])
        app_row = cursor.fetchone()
        if not app_row:
            messages.error(request, "Application not found.")
            return redirect("dashboard")

        requested_budget = Decimal(str(app_row[0] or 0))
        current_status = app_row[1]

        if current_status in ("Accepted", "Approved", "Rejected", "Not Selected"):
            messages.error(request, "This application has already been finalized.")
            return redirect("application_details", app_id=app_id)

        decision_status = request.POST.get("decision_status", "").strip()
        suggested_amount_raw = request.POST.get("suggested_amount", "").strip()
        committee_evaluation_notes = request.POST.get("committee_evaluation_notes", "").strip()

        VALID_REVIEWER_DECISION_STATUSES = ("Not Selected", "Approved", "Drafted", "Pending", "Rejected")
        if not decision_status or decision_status not in VALID_REVIEWER_DECISION_STATUSES:
            messages.error(request, "Please select a valid decision status.")
            return redirect("application_details", app_id=app_id)

        suggested_amount = None
        if decision_status in ("Not Selected", "Rejected"):
            suggested_amount = None
        elif suggested_amount_raw:
            try:
                suggested_amount = Decimal(suggested_amount_raw)
                if not suggested_amount.is_finite() or suggested_amount <= 0:
                    raise ValueError
            except (ArithmeticError, ValueError):
                messages.error(request, "Suggested support amount must be a valid positive number.")
                return redirect("application_details", app_id=app_id)

            if suggested_amount.normalize().as_tuple().exponent < -2:
                messages.error(request, "Suggested support amount can have at most two decimal places.")
                return redirect("application_details", app_id=app_id)

            if suggested_amount > requested_budget:
                messages.error(
                    request,
                    f"Suggested support amount (₹{suggested_amount:,.2f}) cannot exceed the amount requested by the student (₹{requested_budget:,.2f})."
                )
                return redirect("application_details", app_id=app_id)


        now = timezone.now()
        db_decision_status = "Rejected" if decision_status == "Not Selected" else decision_status

        cursor.execute("""
            INSERT INTO "REVIEWER_EVALUATIONS"
            ("APPLICATION_ID", "USER_ID", "OPENED_AT", "SUGGESTED_AMOUNT", "COMMITTEE_EVALUATION_NOTES", "DECISION_STATUS", "UPDATED_AT")
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ("APPLICATION_ID", "USER_ID")
            DO UPDATE SET
                "SUGGESTED_AMOUNT" = EXCLUDED."SUGGESTED_AMOUNT",
                "COMMITTEE_EVALUATION_NOTES" = EXCLUDED."COMMITTEE_EVALUATION_NOTES",
                "DECISION_STATUS" = EXCLUDED."DECISION_STATUS",
                "OPENED_AT" = COALESCE("REVIEWER_EVALUATIONS"."OPENED_AT", EXCLUDED."OPENED_AT"),
                "UPDATED_AT" = EXCLUDED."UPDATED_AT";
        """, [app_id, user_id, now, suggested_amount, committee_evaluation_notes, decision_status, now])

        # Ensure that if all reviewers have opened, application status is Under Review and decision status is Pending (if not yet decided by Chairman)
        cursor.execute("""
            SELECT upr."USER_ID"
            FROM "USER_PROGRAM_ROLES" upr
            JOIN "USERS" u ON u."ID" = upr."USER_ID"
            WHERE upr."PROGRAM" = %s AND upr."ROLE" = 'Reviewer' AND (u."STATUS" = 'Active' OR u."STATUS" IS NULL);
        """, [program])
        assigned_revs = set(r[0] for r in cursor.fetchall())

        cursor.execute("""
            SELECT re."USER_ID"
            FROM "REVIEWER_EVALUATIONS" re
            WHERE re."APPLICATION_ID" = %s AND re."OPENED_AT" IS NOT NULL;
        """, [app_id])
        opened_revs = set(r[0] for r in cursor.fetchall()) & assigned_revs

        if len(assigned_revs) > 0 and len(opened_revs) >= len(assigned_revs):
            cursor.execute("""
                UPDATE "APPLICATIONS"
                SET
                    "STATUS" = CASE WHEN "STATUS" IN ('SUBMITTED', 'Drafted') THEN 'Under Review' ELSE "STATUS" END,
                    "DECISION_STATUS" = CASE
                        WHEN "DECISION_STATUS" IN ('SUBMITTED', 'Drafted', '') OR "DECISION_STATUS" IS NULL THEN 'Pending'
                        ELSE "DECISION_STATUS"
                    END,
                    "REVIEWED_ONCE" = TRUE,
                    "REVIEWED_AT" = COALESCE("REVIEWED_AT", %s)
                WHERE "ID" = %s
                  AND "STATUS" NOT IN ('Accepted', 'Approved', 'Rejected');
            """, [now, app_id])


    messages.success(request, "Your recommendation and decision status have been saved.")
    return redirect("application_details", app_id=app_id)


@csrf_exempt
@custom_login_required
def submit_review(request, app_id):
    print("---- submit_review called ----")

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({"error": "Please login again"}, status=401)

    user_email = request.session.get('user_email')
    user_role = request.session.get('user_role')

    if not user_email:
        return JsonResponse({"error": "Session expired, please login again"}, status=401)

    program = _program_of(app_id)
    if program is None:
        return JsonResponse({"error": "Application not found"}, status=404)

    # Scoped to the application's programme: a Travel reviewer cannot review an
    # RFG application, and Observers cannot review at all.
    if not permissions.can_review(request, program):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    rating = request.POST.get("rating")
    feedback = request.POST.get("feedback")

    if not rating:
        return JsonResponse({"error": "Rating required"}, status=400)

    try:
        with connection.cursor() as cursor:
            # --- Resolve USER_ID safely ---
            cursor.execute("""
                SELECT "ID"
                FROM "USERS"
                WHERE "EMAIL" = %s
                LIMIT 1
            """, [user_email])

            row = cursor.fetchone()
            print("User row:", row)

            if not row:
                return JsonResponse({"error": "User not found"}, status=404)

            user_id = row[0]

            # --- Check existing review ---
            cursor.execute("""
                SELECT "ID"
                FROM "REVIEWS"
                WHERE "APPLICATION_ID"=%s AND "USER_ID"=%s
            """, [app_id, user_id])

            existing = cursor.fetchone()

            if existing:
                cursor.execute("""
                    UPDATE "REVIEWS"
                    SET "RATING"=%s, "FEEDBACK"=%s, "CREATED_AT"=CURRENT_TIMESTAMP
                    WHERE "ID"=%s
                """, [rating, feedback, existing[0]])
            else:
                cursor.execute("""
                    INSERT INTO "REVIEWS"
                    ("APPLICATION_ID","USER_ID","RATING","FEEDBACK")
                    VALUES (%s,%s,%s,%s)
                """, [app_id, user_id, rating, feedback])

        messages.success(request, "Review submitted successfully")
        return redirect('application_details', app_id=app_id)

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception("Error submitting review")
        return JsonResponse({"error": "Internal server error"}, status=500)


@csrf_exempt
@custom_login_required
def submit_final_approval(request, app_id):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    user_role = request.session.get('user_role')
    user_id = request.session.get('user_id')
    user_email = request.session.get('user_email')
    
    program = _program_of(app_id)
    if program is None:
        return JsonResponse({"error": "Application not found"}, status=404)

    if not permissions.can_decide(request, program):
        return JsonResponse({"error": "Only the Chairman can provide final approval"},
                            status=403)
    
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            acm_budget.lock_ledger(cursor)

            if not user_id and user_email:
                cursor.execute('SELECT "ID" FROM "USERS" WHERE "EMAIL" = %s LIMIT 1', [user_email])
                urow = cursor.fetchone()
                if urow:
                    user_id = urow[0]
            elif user_id and not user_email:
                cursor.execute('SELECT "EMAIL" FROM "USERS" WHERE "ID" = %s LIMIT 1', [user_id])
                urow = cursor.fetchone()
                if urow:
                    user_email = urow[0]

            cursor.execute(
                'SELECT "STATUS", "TRAVEL_BUDGET" FROM "APPLICATIONS" WHERE "ID" = %s FOR UPDATE',
                [app_id])
            status_row = cursor.fetchone()
            if not status_row:
                return JsonResponse({"error": "Application not found"}, status=404)
            if status_row[0] in ("Accepted", "Approved"):
                messages.info(request, "This application has already been approved.")
                return redirect('application_details', app_id=app_id)
            if status_row[0] in ("Rejected", "Not Selected"):
                messages.error(request, "A rejected application cannot be approved.")
                return redirect('application_details', app_id=app_id)

            # Enforce Case 1 workflow: Chairman must complete and submit the Review/Rating Form first
            cursor.execute("""
                SELECT COUNT(*) FROM "REVIEWS"
                WHERE "APPLICATION_ID" = %s AND "USER_ID" = %s
            """, [app_id, user_id])
            if cursor.fetchone()[0] == 0:
                messages.error(
                    request,
                    "You must complete and submit the Review/Rating Form before providing final approval."
                )
                return redirect('application_details', app_id=app_id)

            requested_budget = Decimal(str(status_row[1] or 0))

            amount = request.POST.get("amount")
            feedback = request.POST.get("feedback")

            if not amount:
                return JsonResponse({"error": "Amount is required"}, status=400)

            try:
                amount_value = Decimal(amount)
                if not amount_value.is_finite():
                    raise ValueError
            except (ArithmeticError, TypeError, ValueError):
                messages.error(request, "Approved amount must be a number.")
                return redirect('application_details', app_id=app_id)

            if amount_value <= 0:
                messages.error(request, "Approved amount must be greater than zero.")
                return redirect('application_details', app_id=app_id)

            if amount_value > requested_budget:
                messages.error(
                    request,
                    f"Approved support amount (₹{amount_value:,.2f}) cannot exceed the amount requested by the student (₹{requested_budget:,.2f})."
                )
                return redirect('application_details', app_id=app_id)

            if amount_value > Decimal("9999999999999.99"):
                messages.error(request, "Approved amount exceeds the supported limit.")
                return redirect('application_details', app_id=app_id)
            if amount_value.normalize().as_tuple().exponent < -2:
                messages.error(request, "Approved amount can have at most two decimal places.")
                return redirect('application_details', app_id=app_id)

            if (program == permissions.PROGRAM_TRAVEL
                    and amount_value > Decimal("100000")):
                messages.error(
                    request,
                    "Travel Grant approvals cannot exceed Rs. 1,00,000.")
                return redirect('application_details', app_id=app_id)

            # RFG is capped. Applicants may request more (the applicant-facing
            # form never states a cap), but approval cannot exceed it. Enforced
            # here rather than only in the template, because this endpoint is
            # csrf_exempt and reachable directly.
            if (program == permissions.PROGRAM_RFG
                    and amount_value > Decimal(str(rfg.RFG_APPROVAL_CAP))):
                messages.error(
                    request,
                    "Research Facilitation Grant approvals cannot exceed Rs. %s."
                    % f"{rfg.RFG_APPROVAL_CAP:,}")
                return redirect('application_details', app_id=app_id)

            total_budget = acm_budget.load_total(
                cursor, program, for_update=True)
            if total_budget is not None:
                available = acm_budget.available_for(
                    cursor,
                    total_budget,
                    program,
                    exclude_application_id=app_id)
                if amount_value > available:
                    messages.error(
                        request,
                        "This approval exceeds the available %s budget of %s."
                        % (
                            permissions.PROGRAM_LABELS.get(program, program),
                            acm_budget.format_money(max(available, Decimal("0"))),
                        ))
                    return redirect('application_details', app_id=app_id)

            # Insert approval
            cursor.execute("""
                INSERT INTO "FINAL_APPROVALS"
                ("APPLICATION_ID", "CHAIRMAN_ID", "APPROVED_AMOUNT", "FEEDBACK")
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING;
            """, [app_id, user_id, amount_value, feedback])
            
            # Update status
            cursor.execute("""
                UPDATE "APPLICATIONS"
                SET "STATUS" = 'Accepted',
                    "DECISION_STATUS" = 'Approved',
                    "APPROVED_SUPPORT_AMOUNT" = %s
                WHERE "ID" = %s
            """, [amount_value, app_id])

        messages.success(
            request,
            f"Application approved with ₹{amount}. The applicant has NOT been notified yet — "
            f"use 'Notify Applicant' below to send the decision.")
        return redirect('application_details', app_id=app_id)

    except Exception as e:
        logger.error(f"Error submitting final approval: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@custom_login_required
def notify_applicant(request, app_id):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    user_role = request.session.get('user_role')

    program = _program_of(app_id)
    if program is None:
        messages.error(request, "Application not found.")
        return redirect('dashboard')

    program_role = permissions.role_for(request, program)
    if program_role not in NOTIFY_PERMISSIONS:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT "EMAIL", "APPLICANT_NAME", "CONFERENCE_NAME", "TRACKING_CODE",
                       "PAPER_TITLE", "STATUS", "REJECTION_REASON", "NOTIFIED_STATUS"
                FROM "APPLICATIONS"
                WHERE "ID" = %s
            """, [app_id])

            row = cursor.fetchone()
            if not row:
                messages.error(request, "Application not found.")
                return redirect('dashboard')

            (email, name, conference, tracking_code,
             paper_title, status, rejection_reason, notified_status) = row

            if status not in ("Under Review", "Pending", "Accepted", "Approved", "Rejected", "Not Selected"):
                messages.error(
                    request, "There is no decision to communicate for this application yet.")
                return redirect('application_details', app_id=app_id)

            # Reviewers may announce that review has started; only the Chairman
            # communicates the final decision.
            if status not in NOTIFY_PERMISSIONS.get(program_role, set()):
                messages.error(
                    request,
                    f"Only the Chairman can notify the applicant of a '{get_status_display(status)}' decision.")
                return redirect('application_details', app_id=app_id)

            # Guard against a second send for the same decision. Comparing against
            # the status rather than a bare timestamp means a later decision can
            # still be notified.
            if notified_status == status or (notified_status and get_status_display(notified_status) == get_status_display(status)):
                messages.info(request, "The applicant has already been notified of this decision.")
                return redirect('application_details', app_id=app_id)

            if not email:
                messages.error(request, "This application has no email address on file.")
                return redirect('application_details', app_id=app_id)

            # Wording differs per programme: an RFG applicant should not be told
            # their "Travel Grant" was approved.
            is_rfg = program == permissions.PROGRAM_RFG
            program_name = "Research Facilitation Grant" if is_rfg else "Travel Grant"
            committee = ("ACM India Research Facilitation Grant Committee" if is_rfg
                         else "Student Travel Grant Committee")
            venue_label = "Conference/Event" if is_rfg else "Conference"
            subject_line = f"Paper Title: {paper_title}" if paper_title else ""

            if status in ("Accepted", "Approved"):
                cursor.execute("""
                    SELECT "APPROVED_AMOUNT" FROM "FINAL_APPROVALS"
                    WHERE "APPLICATION_ID" = %s
                    ORDER BY "CREATED_AT" DESC LIMIT 1
                """, [app_id])
                amount_row = cursor.fetchone()
                amount_line = f"\nApproved Amount: Rs. {amount_row[0]}" if amount_row else ""

                subject = f"{program_name} Approved"
                body = f"""
Dear {name},

Your {program_name} application has been approved.

Tracking Code: {tracking_code}
{subject_line}
{venue_label}: {conference}{amount_line}

Please login to view full details.

Regards,
{committee}
"""
            elif status in ("Rejected", "Not Selected"):
                subject = f"Your {program_name} Application has been Not Selected"
                body = f"""
Dear {name},

We regret to inform you that your {program_name} application relating to
"{conference}" has not been selected.

Tracking Code: {tracking_code}
{subject_line}

Reason:
{rejection_reason or "No reason provided."}

You can view details in your application dashboard.

Regards,
{committee}
"""
            else:  # Under Review / Pending
                subject = f"Your {program_name} Application is Pending"
                body = f"""
Dear {name},

Your {program_name} application relating to "{conference}" is now pending review
by our committee.

Tracking Code: {tracking_code}
{subject_line}

You will be notified once the review process is complete or if any further action
is required.

Thank you for your submission.

Regards,
{committee}
"""

            mailer.send(subject, body, [email], fail_silently=False)

            # Recorded only after the mail actually went out.
            cursor.execute("""
                UPDATE "APPLICATIONS"
                SET "NOTIFIED_AT" = %s, "NOTIFIED_STATUS" = %s
                WHERE "ID" = %s
            """, [timezone.now(), status, app_id])

        messages.success(request, f"Applicant notified: {get_status_display(status)}")
        return redirect('application_details', app_id=app_id)

    except Exception as e:
        logger.error(f"Notification error: {e}")
        messages.error(request, "The notification email could not be sent. Please try again.")
        return redirect('application_details', app_id=app_id)


@csrf_exempt
@custom_login_required
def reject_application(request, app_id):
    from django.core.mail import send_mail
    from django.conf import settings
    import logging

    logger = logging.getLogger(__name__)

    user_role = request.session.get('user_role')

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    program = _program_of(app_id)
    if program is None:
        messages.error(request, "Application not found.")
        return redirect('dashboard')

    if not permissions.can_decide(request, program):
        messages.error(request, "Only the Chairman can reject applications.")
        return redirect('application_details', app_id=app_id)

    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Rejection reason is required.")
        return redirect('application_details', app_id=app_id)

    try:
        with connection.cursor() as cursor:
            # Fetch applicant info
            cursor.execute("""
                SELECT "EMAIL", "APPLICANT_NAME", "CONFERENCE_NAME"
                FROM "APPLICATIONS"
                WHERE "ID" = %s
            """, [app_id])

            row = cursor.fetchone()
            if not row:
                messages.error(request, "Application not found.")
                return redirect('dashboard')

            applicant_email, applicant_name, conference_name = row

            # Update application status
            cursor.execute("""
                UPDATE "APPLICATIONS"
                SET "STATUS" = 'Rejected',
                    "DECISION_STATUS" = 'Rejected',
                    "APPROVED_SUPPORT_AMOUNT" = NULL,
                    "REJECTION_REASON" = %s
                WHERE "ID" = %s
            """, [reason, app_id])

            cursor.execute("""
                DELETE FROM "FINAL_APPROVALS"
                WHERE "APPLICATION_ID" = %s
            """, [app_id])

        # The decision is held as a draft: no email goes out here. The Chairman
        # sends it explicitly from the application page via notify_applicant.
        messages.success(
            request,
            f"Application #{app_id} marked as Not Selected. The applicant has NOT been notified yet — "
            f"use 'Notify Applicant' on the application page to send the decision.")

        return redirect('dashboard')

    except Exception as e:
        logger.exception(f"Error rejecting application {app_id}")
        messages.error(request, "An error occurred while rejecting the application.")
        return redirect('dashboard')


def travel_grant_form(request):
    if request.method == "POST":
        # Here you can handle the POST request,
        # for example send the data to your API or save in DB
        data = request.POST
        files = request.FILES
        # print(data, files)  # for testing
        return render(request, "form_submitted.html")

    # Passed through so the size hints, the browser-side check and the server
    # all quote the same number.
    return render(request, "travel_grant_form.html", {
        "max_upload_mb": settings.MAX_UPLOAD_BYTES // (1024 * 1024),
        "max_upload_total_mb": settings.MAX_UPLOAD_TOTAL_BYTES // (1024 * 1024),
    })


from django.contrib.auth.hashers import check_password, make_password

@custom_login_required
def profile_update(request):
    """User profile page - update profile, password, add/update users (System Reviewer)"""
    email = request.user.email
    profile_message = None
    password_message = None
    add_user_message = None
    add_user_errors = {}
    add_user_values = {}
    update_user_message = None

    user_role = request.session.get('user_role')
    user_id = request.session.get('user_id')
    username = request.session.get('user_name')
    print("DEBUG: User Role =", user_role, "User ID =", user_id, "Username =", username)

    # Fetch user details
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT "ID", "NAME", "EMAIL", "MOBILE_NO", "PHOTO", "PASSWORD", "USERNAME", "ROLE", "STATUS"
            FROM "USERS"
            WHERE "EMAIL" = %s
        """, [email])
        row = cursor.fetchone()

    if not row:
        profile_message = "User not found!"
        return render(request, 'profile.html', {'profile_message': profile_message})

    profile_user = {
        'id': row[0],
        'name': row[1],
        'email': row[2],
        'mobile_no': row[3],
        'photo': row[4],
        'password': row[5],  # MD5 hash
        'username': row[6],
        'role': row[7],
        'status': row[8],
    }
    print("DEBUG: Profile User =", profile_user)

    try:
        # ================= PROFILE UPDATE =================
        if request.method == "POST" and request.POST.get("update_profile") == "1":
            new_name = request.POST.get('name', '').strip()
            new_mobile = request.POST.get('phone_number', '').strip()
            print("DEBUG: Update Profile POST received", new_name, new_mobile)

            # Handle profile image
            if 'profile_image' in request.FILES:
                profile_image = request.FILES['profile_image']
                profile_folder = os.path.join(settings.MEDIA_ROOT, 'profile')
                os.makedirs(profile_folder, exist_ok=True)

                image_name = f"avatar_{profile_user['username']}.jpg"
                image_path = os.path.join(profile_folder, image_name)

                if os.path.exists(image_path):
                    os.remove(image_path)

                with open(image_path, 'wb') as f:
                    for chunk in profile_image.chunks():
                        f.write(chunk)

                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE "USERS"
                        SET "PHOTO" = %s, "UPDATED_AT" = CURRENT_TIMESTAMP
                        WHERE "ID" = %s
                    """, [f"profile/{image_name}", profile_user['id']])
                print("DEBUG: Profile image updated to", image_name)

            if new_name or new_mobile:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE "USERS"
                        SET "NAME" = %s,
                            "MOBILE_NO" = %s,
                            "UPDATED_AT" = CURRENT_TIMESTAMP
                        WHERE "ID" = %s
                    """, [new_name or profile_user['name'], new_mobile or profile_user['mobile_no'], profile_user['id']])
                profile_message = "Profile updated successfully!"
                print("DEBUG: Profile updated with name/mobile")

        # ================= PASSWORD CHANGE =================
        if request.method == "POST" and request.POST.get("change_password") == "1":
            old_password = request.POST.get('old_password', '').strip()
            new_password = request.POST.get('new_password', '').strip()
            confirm_password = request.POST.get('confirm_password', '').strip()
            print("DEBUG: Change password POST received")

            if not (old_password and new_password and confirm_password):
                password_message = "Please fill all password fields!"
            elif new_password != confirm_password:
                password_message = "New password and confirm password do not match!"
            else:
                old_password_hash = hashlib.md5(old_password.encode()).hexdigest()
                if old_password_hash != profile_user['password']:
                    password_message = "Old password is incorrect!"
                else:
                    new_password_hash = hashlib.md5(new_password.encode()).hexdigest()
                    with connection.cursor() as cursor:
                        cursor.execute("""
                            UPDATE "USERS"
                            SET "PASSWORD" = %s,
                                "UPDATED_AT" = CURRENT_TIMESTAMP
                            WHERE "ID" = %s
                        """, [new_password_hash, profile_user['id']])
                    password_message = "Password updated successfully!"
                    print("DEBUG: Password updated for user", profile_user['username'])

        # ================= ADD NEW USER (System Reviewer only) =================
        if user_role == "System Reviewer" and request.method == "POST" and request.POST.get("add_user") == "1":
            new_name = request.POST.get('new_name', '').strip()
            new_username = request.POST.get('new_username', '').strip()
            new_email = request.POST.get('new_email', '').strip()
            new_mobile = request.POST.get('new_mobile', '').strip()
            new_role = request.POST.get('new_role', '').strip()
            new_travel_role = request.POST.get('new_travel_role', '').strip()
            new_rfg_role = request.POST.get('new_rfg_role', '').strip()
            new_password = request.POST.get('new_password', '').strip()
            new_photo = request.FILES.get('new_photo')
            print("DEBUG: Add user POST received", new_username, new_email, new_role)

            # Preserve non-sensitive values only after a failed submission. The
            # form remains completely empty on its initial load.
            add_user_values = {
                'new_name': new_name,
                'new_username': new_username,
                'new_email': new_email,
                'new_mobile': new_mobile,
                'new_role': new_role,
                'new_travel_role': new_travel_role,
                'new_rfg_role': new_rfg_role,
            }

            if not new_name:
                add_user_errors['new_name'] = "Name is required."
            elif len(new_name) < 2:
                add_user_errors['new_name'] = "Name must contain at least 2 characters."
            elif len(new_name) > 100:
                add_user_errors['new_name'] = "Name cannot exceed 100 characters."
            elif (not any(char.isalnum() for char in new_name) or
                  not all(char.isalnum() or char in " .'-" for char in new_name)):
                add_user_errors['new_name'] = "Use letters, numbers, spaces, apostrophes, periods or hyphens only."

            if not new_username:
                add_user_errors['new_username'] = "Username is required."
            elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,62}[A-Za-z0-9]", new_username):
                add_user_errors['new_username'] = (
                    "Use 3-64 letters, numbers, periods, underscores or hyphens; "
                    "start and end with a letter or number."
                )

            if not new_email:
                add_user_errors['new_email'] = "Email is required."
            elif len(new_email) > 150:
                add_user_errors['new_email'] = "Email cannot exceed 150 characters."
            else:
                try:
                    validate_email(new_email)
                except ValidationError:
                    add_user_errors['new_email'] = "Enter a valid email address."

            if new_mobile and not re.fullmatch(r"\d{10}", new_mobile):
                add_user_errors['new_mobile'] = "Phone number must contain exactly 10 digits."

            valid_account_roles = {
                permissions.STANDARD_ACCOUNT_ROLE,
                permissions.SYSTEM_REVIEWER,
            }
            if new_role not in valid_account_roles:
                add_user_errors['new_role'] = "Select a valid account type."

            valid_program_roles = {
                "NONE",
                permissions.ROLE_REVIEWER,
                permissions.ROLE_CHAIRMAN,
                permissions.ROLE_OBSERVER,
                permissions.ROLE_FINANCE,
            }
            if new_travel_role not in valid_program_roles:
                add_user_errors['new_travel_role'] = "Select Travel Support access."
            if new_rfg_role not in valid_program_roles:
                add_user_errors['new_rfg_role'] = "Select Research Facilitation Grant access."

            expected_finance_program = permissions.FINANCE_ACCOUNTS.get(new_username)
            assigned_finance_programs = {
                program for program, role in (
                    (permissions.PROGRAM_TRAVEL, new_travel_role),
                    (permissions.PROGRAM_RFG, new_rfg_role),
                ) if role == permissions.ROLE_FINANCE
            }

            if expected_finance_program is not None:
                if new_role != permissions.STANDARD_ACCOUNT_ROLE:
                    add_user_errors['new_role'] = (
                        "Finance users must use the Standard account type."
                    )
                if expected_finance_program == permissions.PROGRAM_TRAVEL:
                    if new_travel_role != permissions.ROLE_FINANCE:
                        add_user_errors['new_travel_role'] = (
                            "tg-finance must have Finance access for Travel Support."
                        )
                    if new_rfg_role != "NONE":
                        add_user_errors['new_rfg_role'] = (
                            "tg-finance cannot access Research Facilitation Grant applications."
                        )
                else:
                    if new_rfg_role != permissions.ROLE_FINANCE:
                        add_user_errors['new_rfg_role'] = (
                            "rfg-finance must have Finance access for Research Facilitation Grant."
                        )
                    if new_travel_role != "NONE":
                        add_user_errors['new_travel_role'] = (
                            "rfg-finance cannot access Travel Support applications."
                        )
            elif assigned_finance_programs:
                add_user_errors['new_username'] = (
                    "Finance access is reserved for tg-finance or rfg-finance."
                )

            if not new_password:
                add_user_errors['new_password'] = "Password is required."

            if new_photo:
                allowed_photo_types = {
                    '.jpg': ('image/jpeg', 'JPEG'),
                    '.jpeg': ('image/jpeg', 'JPEG'),
                    '.png': ('image/png', 'PNG'),
                    '.gif': ('image/gif', 'GIF'),
                    '.webp': ('image/webp', 'WEBP'),
                }
                extension = os.path.splitext(new_photo.name)[1].lower()
                expected = allowed_photo_types.get(extension)
                header = new_photo.read(16)
                new_photo.seek(0)
                detected_format = None
                if header.startswith(b'\xff\xd8\xff'):
                    detected_format = 'JPEG'
                elif header.startswith(b'\x89PNG\r\n\x1a\n'):
                    detected_format = 'PNG'
                elif header.startswith((b'GIF87a', b'GIF89a')):
                    detected_format = 'GIF'
                elif len(header) >= 12 and header[:4] == b'RIFF' and header[8:12] == b'WEBP':
                    detected_format = 'WEBP'

                if not expected or new_photo.content_type != expected[0] or detected_format != expected[1]:
                    add_user_errors['new_photo'] = "Upload a valid JPG, PNG, GIF or WebP image."
                elif new_photo.size > settings.MAX_UPLOAD_BYTES:
                    max_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
                    add_user_errors['new_photo'] = f"Photo size cannot exceed {max_mb} MB."

            if 'new_username' not in add_user_errors or 'new_email' not in add_user_errors:
                with connection.cursor() as cursor:
                    if 'new_username' not in add_user_errors:
                        cursor.execute("""
                            SELECT 1 FROM "USERS"
                            WHERE LOWER("USERNAME") = LOWER(%s)
                            LIMIT 1
                        """, [new_username])
                        if cursor.fetchone():
                            add_user_errors['new_username'] = "That username is already in use."

                    if 'new_email' not in add_user_errors:
                        cursor.execute("""
                            SELECT 1 FROM "USERS"
                            WHERE LOWER("EMAIL") = LOWER(%s)
                            LIMIT 1
                        """, [new_email])
                        if cursor.fetchone():
                            add_user_errors['new_email'] = "That email address is already in use."

            if not add_user_errors:
                new_password_hash = hashlib.md5(new_password.encode()).hexdigest()
                photo_path = None

                if new_photo:
                    photo_folder = os.path.join(settings.MEDIA_ROOT, 'profile')
                    os.makedirs(photo_folder, exist_ok=True)
                    photo_name = f"avatar_{new_username}.jpg"
                    photo_path = os.path.join(photo_folder, photo_name)
                    with open(photo_path, 'wb') as f:
                        for chunk in new_photo.chunks():
                            f.write(chunk)
                    photo_path = f"profile/{photo_name}"

                with connection.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO "USERS" ("NAME","USERNAME","EMAIL","MOBILE_NO","ROLE","PASSWORD","PHOTO","STATUS","CREATED_AT")
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'Active',CURRENT_TIMESTAMP)
                        RETURNING "ID"
                    """, [new_name, new_username, new_email, new_mobile or None, new_role, new_password_hash, photo_path])
                    new_user_id = cursor.fetchone()[0]

                # Finance is a programme role on a standard account, just like
                # the other programme-scoped access levels.
                permissions.set_program_role(
                    new_user_id, permissions.PROGRAM_TRAVEL,
                    '' if new_travel_role == 'NONE' else new_travel_role)
                permissions.set_program_role(
                    new_user_id, permissions.PROGRAM_RFG,
                    '' if new_rfg_role == 'NONE' else new_rfg_role)

                add_user_message = f"User {new_username} added successfully!"
                add_user_values = {}
                print("DEBUG: New user added:", new_username)

        # ================= UPDATE EXISTING USER (System Reviewer only) =================
        if user_role == "System Reviewer" and request.method == "POST" and request.POST.get("update_user_id"):
            update_user_id = request.POST.get("update_user_id")
            update_name = request.POST.get("update_name", '').strip()
            update_username = request.POST.get("update_username", '').strip()
            update_email = request.POST.get("update_email", '').strip()
            update_mobile = request.POST.get("update_mobile", '').strip()
            update_status = request.POST.get("update_status", '').strip()
            update_password = request.POST.get("update_password", '').strip()
            update_travel_role = (
                request.POST.get('update_travel_role') or '').strip()
            update_rfg_role = (
                request.POST.get('update_rfg_role') or '').strip()
            print("DEBUG: Update user POST received", update_user_id)

            if not (update_name and update_username and update_email):
                raise ValueError("Name, username and email are required.")
            if len(update_name) > 100:
                raise ValueError("Name cannot exceed 100 characters.")
            if len(update_username) > 64:
                raise ValueError("Username cannot exceed 64 characters.")
            if len(update_email) > 150:
                raise ValueError("Email cannot exceed 150 characters.")
            try:
                validate_email(update_email)
            except ValidationError as exc:
                raise ValueError("Enter a valid email address.") from exc

            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT "EMAIL", "ROLE", "USERNAME"
                        FROM "USERS"
                        WHERE "ID" = %s
                    """, [update_user_id])
                    current_user = cursor.fetchone()

                    if not current_user:
                        raise ValueError("The selected user no longer exists.")

                    current_email, current_role, current_username = current_user
                    current_program_roles = permissions.load_program_roles(
                        update_user_id)
                    current_is_finance = permissions.ROLE_FINANCE in (
                        current_program_roles.values())
                    if current_is_finance and update_username != current_username:
                        raise ValueError(
                            "Finance usernames are fixed and cannot be changed.")

                    expected_finance_program = permissions.FINANCE_ACCOUNTS.get(
                        update_username)
                    assigned_finance_programs = {
                        program for program, role in (
                            (permissions.PROGRAM_TRAVEL, update_travel_role),
                            (permissions.PROGRAM_RFG, update_rfg_role),
                        ) if role == permissions.ROLE_FINANCE
                    }
                    if expected_finance_program is not None:
                        if current_role != permissions.STANDARD_ACCOUNT_ROLE:
                            raise ValueError(
                                "Finance users must use the Standard account type.")
                        expected_roles = {
                            permissions.PROGRAM_TRAVEL: (
                                permissions.ROLE_FINANCE
                                if expected_finance_program == permissions.PROGRAM_TRAVEL
                                else ''),
                            permissions.PROGRAM_RFG: (
                                permissions.ROLE_FINANCE
                                if expected_finance_program == permissions.PROGRAM_RFG
                                else ''),
                        }
                        if (update_travel_role != expected_roles[permissions.PROGRAM_TRAVEL]
                                or update_rfg_role != expected_roles[permissions.PROGRAM_RFG]):
                            raise ValueError(
                                "%s must have Finance access only for its assigned programme."
                                % update_username)
                    elif assigned_finance_programs:
                        raise ValueError(
                            "Finance access is reserved for tg-finance or rfg-finance.")

                    cursor.execute("""
                        SELECT "ID"
                        FROM "USERS"
                        WHERE "ID" <> %s AND LOWER("USERNAME") = LOWER(%s)
                        LIMIT 1
                    """, [update_user_id, update_username])
                    if cursor.fetchone():
                        raise ValueError("That username is already in use.")

                    cursor.execute("""
                        SELECT "ID"
                        FROM "USERS"
                        WHERE "ID" <> %s AND LOWER("EMAIL") = LOWER(%s)
                        LIMIT 1
                    """, [update_user_id, update_email])
                    if cursor.fetchone():
                        raise ValueError("That email address is already in use.")

                    auth_user = User.objects.filter(username=current_email).first()
                    if auth_user is None:
                        auth_user = User.objects.filter(email=current_email).first()

                    if (auth_user is not None and
                            User.objects.exclude(pk=auth_user.pk)
                            .filter(username__iexact=update_email).exists()):
                        raise ValueError("That email address is already used by a login account.")

                    fields_to_update = [
                        '"NAME" = %s',
                        '"USERNAME" = %s',
                        '"EMAIL" = %s',
                    ]
                    values = [update_name, update_username, update_email]

                    if update_mobile:
                        fields_to_update.append('"MOBILE_NO" = %s')
                        values.append(update_mobile)

                    if update_status:
                        fields_to_update.append('"STATUS" = %s')
                        values.append(update_status)

                    if update_password:
                        password_hash = hashlib.md5(update_password.encode()).hexdigest()
                        fields_to_update.append('"PASSWORD" = %s')
                        values.append(password_hash)

                    values.append(update_user_id)
                    query = f'UPDATE "USERS" SET {", ".join(fields_to_update)}, "UPDATED_AT" = CURRENT_TIMESTAMP WHERE "ID" = %s'
                    cursor.execute(query, values)

                # Django authentication uses the email address as its username.
                # Keep that login record aligned with the application USERS row.
                if auth_user is not None:
                    auth_user.username = update_email
                    auth_user.email = update_email
                    auth_user.first_name = update_name
                    auth_user.save(update_fields=["username", "email", "first_name"])

                permissions.set_program_role(
                    update_user_id, permissions.PROGRAM_TRAVEL,
                    update_travel_role)
                permissions.set_program_role(
                    update_user_id, permissions.PROGRAM_RFG,
                    update_rfg_role)

            # If the System Reviewer edited their own identifiers, keep this
            # active request/session usable without requiring an immediate logout.
            if str(update_user_id) == str(user_id):
                request.session['user_name'] = update_name
                request.session['user_email'] = update_email
                request.user.username = update_email
                request.user.email = update_email
                request.user.first_name = update_name
                profile_user.update({
                    'name': update_name,
                    'username': update_username,
                    'email': update_email,
                })

            update_user_message = f"User ID {update_user_id} updated successfully!"
            print("DEBUG: User updated:", update_user_id)

    except Exception as e:
        profile_message = f"Error: {str(e)}"
        print("DEBUG: Exception occurred:", e)

    # ================= PROFILE IMAGE URL =================
    profile_image_url = None
    profile_folder = os.path.join(settings.MEDIA_ROOT, 'profile')
    image_name = f"avatar_{profile_user['username']}.jpg"
    image_path = os.path.join(profile_folder, image_name)
    if os.path.exists(image_path):
        timestamp = int(os.path.getmtime(image_path))
        profile_image_url = f"/media/profile/{image_name}?v={timestamp}"

    # ================= FETCH ALL USERS (System Reviewer only) =================
    all_users = []
    if user_role == "System Reviewer":
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT "ID","NAME","USERNAME","EMAIL","MOBILE_NO","ROLE","STATUS"
                FROM "USERS"
                ORDER BY "ID" ASC
            """)
            rows = cursor.fetchall()

        assigned = permissions.all_program_roles()
        all_users = [
            {
                "id": u[0],
                "name": u[1],
                "username": u[2],
                "email": u[3],
                "mobile_no": u[4],
                "role": u[5],
                "status": u[6],
                "travel_role": assigned.get(u[0], {}).get(permissions.PROGRAM_TRAVEL, ""),
                "rfg_role": assigned.get(u[0], {}).get(permissions.PROGRAM_RFG, ""),
            }
            for u in rows
        ]
        print("DEBUG: All users fetched for System Reviewer:", all_users)

    return render(request, 'profile.html', {
        'profile_user': profile_user,
        'profile_image_url': profile_image_url,
        'profile_message': profile_message,
        'password_message': password_message,
        'add_user_message': add_user_message,
        'add_user_errors': add_user_errors,
        'add_user_values': add_user_values,
        'add_user_photo_max_bytes': settings.MAX_UPLOAD_BYTES,
        'add_user_photo_max_mb': settings.MAX_UPLOAD_BYTES // (1024 * 1024),
        'update_user_message': update_user_message,
        'user_role': user_role,
        'all_users': all_users,
        'program_role_choices': [permissions.ROLE_REVIEWER,
                                 permissions.ROLE_CHAIRMAN,
                                 permissions.ROLE_OBSERVER,
                                 permissions.ROLE_FINANCE],
    })














# ============================================
# EXPORT
# ============================================

# (column, header) in the order they appear in the export.
EXPORT_COLUMNS = [
    ("PROGRAM", "Programme"),
    ("TRACKING_CODE", "Tracking Code"),
    ("STATUS", "Status"),
    ("CREATED_AT", "Submitted On"),
    ("APPLICANT_NAME", "Applicant Name"),
    ("EMAIL", "Email"),
    ("MOBILE_PHONE", "Mobile Phone"),
    ("INSTITUTION_NAME", "Institution"),
    ("POSTAL_ADDRESS", "Postal Address"),
    ("ENROLMENT_TYPE", "Enrolment Type"),
    ("CURRENT_DEGREE_TYPE", "Degree Type"),
    ("CURRENT_DEGREE_PROGRAM", "Degree Program"),
    ("SUPERVISOR_NAME", "Supervisor Name"),
    ("FACULTY_EMAIL", "Supervisor Email"),
    ("FACULTY_PHONE", "Supervisor Phone"),
    ("FACULTY_ADDRESS", "Supervisor Address"),
    ("FACULTY_DESIGNATION", "Supervisor Designation"),
    ("CONFERENCE_NAME", "Conference Name"),
    ("CONFERENCE_VENUE", "Conference Venue"),
    ("CONFERENCE_WEBSITE", "Conference Website"),
    ("CONFERENCE_START_DATE", "Conference Start"),
    ("CONFERENCE_END_DATE", "Conference End"),
    ("PAPER_SUBMISSION_DEADLINE", "Paper Submission Deadline"),
    ("ACCEPTANCE_NOTIFICATION_DATE", "Acceptance Notification Date"),
    ("PAPER_TYPE", "Paper Type"),
    ("PAPER_TITLE", "Paper Title"),
    ("PAPER_DETAILS", "Paper Details"),
    ("REGISTRATION_FEE", "Registration Fee"),
    ("TRAVEL_BUDGET", "Requested Amount"),
    ("BUDGET_JUSTIFICATION", "Budget Justification"),
    ("PREVIOUS_GRANT", "Previous Grant"),
    ("PREVIOUS_CONFERENCE_NAME", "Previous Conference"),
    ("PREVIOUS_CONFERENCE_DATES", "Previous Conference Dates"),
    ("REJECTION_REASON", "Rejection Reason"),
    ("REVIEWED_AT", "First Reviewed At"),
    ("NOTIFIED_STATUS", "Applicant Notified Of"),
    ("NOTIFIED_AT", "Notified At"),
]

# RFG_DETAILS columns, joined in for RFG rows (blank for Travel).
EXPORT_RFG_COLUMNS = [
    ("SCHEME", "RFG Scheme"),
    ("CORRESPONDENCE_EMAIL", "RFG Preferred Email"),
    ("DEPARTMENTS", "RFG Department(s)"),
    ("AFFILIATION_STATUS", "RFG Affiliation Status"),
    ("STUDENT_TYPE", "RFG Student Type"),
    ("FACULTY_CONTACT_NAME", "RFG Faculty Contact"),
    ("FACULTY_CONTACT_EMAIL", "RFG Faculty Email"),
    ("PREVIOUS_RFG", "RFG Availed Before"),
    ("PREVIOUS_RFG_DETAILS", "RFG Previous Details"),
    ("PAPER_AUTHORS", "RFG Paper Authors"),
    ("PUBLICATION_VENUE_URL", "RFG Venue URL"),
    ("PAPER_PDF_URL", "RFG Paper PDF URL"),
    ("ORGANIZER_NAME", "RFG Organizer"),
    ("ORGANIZER_AFFILIATION", "RFG Organizer Affiliation"),
    ("ORGANIZER_EMAIL", "RFG Organizer Email"),
    ("GRANT_HEADS", "RFG Grant Heads"),
    ("AMOUNT_BREAKDOWN", "RFG Amount Breakup"),
]

EXPORT_EXTRA_HEADERS = ["Approved Amount", "Review Count", "Average Rating"]


def _fetch_export_rows(status=None, programs=None):
    """Application rows plus their approval/review roll-ups, newest first.

    `programs` restricts the result to the caller's programmes; an empty list
    yields nothing, which is correct for a user with no programme role.
    """
    if programs is not None and not programs:
        return []

    select_cols = ", ".join(
        [f'a."{col}"' for col, _ in EXPORT_COLUMNS]
        + [f'rd."{col}"' for col, _ in EXPORT_RFG_COLUMNS]
    )

    sql = f"""
        SELECT {select_cols},
               fa."APPROVED_AMOUNT",
               COALESCE(r.review_count, 0),
               r.avg_rating
        FROM "APPLICATIONS" a
        LEFT JOIN LATERAL (
            SELECT "APPROVED_AMOUNT" FROM "FINAL_APPROVALS"
            WHERE "APPLICATION_ID" = a."ID"
            ORDER BY "CREATED_AT" DESC LIMIT 1
        ) fa ON TRUE
        LEFT JOIN "RFG_DETAILS" rd ON rd."APPLICATION_ID" = a."ID"
        LEFT JOIN (
            SELECT "APPLICATION_ID",
                   COUNT(*) AS review_count,
                   ROUND(AVG("RATING")::numeric, 2) AS avg_rating
            FROM "REVIEWS" GROUP BY "APPLICATION_ID"
        ) r ON r."APPLICATION_ID" = a."ID"
    """
    clauses, params = [], []
    if programs is not None:
        clauses.append('a."PROGRAM" = ANY(%s)')
        params.append(programs)
    if status:
        if status in ("Drafted", "SUBMITTED"):
            clauses.append('a."STATUS" IN (\'SUBMITTED\', \'Drafted\')')
        elif status in ("Pending", "Under Review"):
            clauses.append('a."STATUS" IN (\'Under Review\', \'Pending\')')
        elif status in ("Approved", "Accepted", "APPROVED"):
            clauses.append('a."STATUS" IN (\'Accepted\', \'Approved\', \'APPROVED\')')
        elif status in ("Not Selected", "Rejected"):
            clauses.append('a."STATUS" IN (\'Rejected\', \'Not Selected\')')
        else:
            clauses.append('a."STATUS" = %s')
            params.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += ' ORDER BY a."CREATED_AT" DESC'

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def _clean_cell(value):
    """Flatten DB types into something a spreadsheet cell accepts.

    Timestamps are stored naive-UTC, so they are converted to IST here to match
    what the application displays. Plain dates (conference dates, deadlines)
    carry no time and are written through unchanged — shifting them by 5h30m
    would move them to the wrong day.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return _as_utc_aware(value).astimezone(IST).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str) and value in STATUS_DISPLAY:
        return STATUS_DISPLAY[value]
    return value


@custom_login_required
def export_applications(request):
    """Download all applications as .xlsx (default) or .csv."""
    export_format = (request.GET.get("format") or "xlsx").lower()
    status = (request.GET.get("status") or "").strip() or None

    try:
        rows = _fetch_export_rows(status, permissions.visible_programs(request))
    except Exception:
        logger.exception("Export query failed")
        messages.error(request, "The export could not be generated. Please try again.")
        return redirect('dashboard')

    headers = ([header for _, header in EXPORT_COLUMNS]
               + [header for _, header in EXPORT_RFG_COLUMNS]
               + EXPORT_EXTRA_HEADERS)
    filename = f"travel_grant_applications_{datetime.now().strftime('%Y%m%d')}"

    if export_format == "csv":
        import csv

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        # BOM so Excel opens UTF-8 (names, ₹) correctly on Windows.
        response.write("﻿")

        writer = csv.writer(response)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_clean_cell(v) for v in row])
        return response

    # Default: xlsx via openpyxl (already pinned in requirements.txt).
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Applications"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", start_color="4F46E5")
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    for row in rows:
        sheet.append([_clean_cell(v) for v in row])

    # Readable widths without letting long free-text columns run away.
    for index, header in enumerate(headers, start=1):
        longest = max(
            [len(str(header))] +
            [len(str(_clean_cell(row[index - 1]))) for row in rows] or [0]
        )
        sheet.column_dimensions[get_column_letter(index)].width = min(max(longest + 2, 12), 45)

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    workbook.save(response)
    return response


@custom_login_required
def admin_page(request):
    return render(request, 'admin_page.html')

def add_asset_user(request):
    return render(request, 'user/add_asset_users.html')


@custom_login_required
def add_asset_user(request):
    return render(request, 'user/add_asset_users.html')

# @custom_login_required
def add_user(request):  
    logger.info(f"User  '{request.user.username}' accessed add user page.")  
    return render(request, 'user/adduser.html')  


@custom_login_required
def add_user(request):
    return render(request,'add_user.html')

def allowed_file(filename, file_type):
    # Check if the file type is allowed
    allowed_extensions = {'png', 'jpg', 'jpeg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


# ============================================
# TRACKING PAGE AND API
# ============================================

def home(request):
    """Display tracking page where user can enter tracking code"""
    return render(request, "index.html")


@csrf_exempt
def get_application_by_tracking_code(request):
    """API endpoint to fetch application details by tracking code"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            tracking_code = data.get("tracking_code", "").strip()
            
            print(f"\n{'='*60}")
            print(f"GET_APPLICATION_BY_TRACKING_CODE API CALLED")
            print(f"Request Data: {data}")
            print(f"Tracking Code: {tracking_code}")
            print(f"{'='*60}\n")
            
            if not tracking_code:
                print("ERROR: Tracking code is empty")
                return JsonResponse({"error": "Tracking code is required"}, status=400)
            
            with connection.cursor() as cursor:
                # Fetch application by tracking code
                cursor.execute("""
                    SELECT "ID", "TRACKING_CODE"
                    FROM "APPLICATIONS"
                    WHERE "TRACKING_CODE" = %s
                    LIMIT 1;
                """, [tracking_code])
                
                row = cursor.fetchone()
                
                print(f"Query Result: {row}")
                print(f"Row Type: {type(row)}")
                
                if not row:
                    print(f"ERROR: Application not found for tracking code: {tracking_code}")
                    return JsonResponse({"error": "Application not found"}, status=404)
                
                app_id, tracking_code_db = row
                print(f"Found Application - ID: {app_id}, Tracking Code: {tracking_code_db}")
                print(f"{'='*60}\n")
                
                # Applicants have no accounts, so this must be the PUBLIC
                # detail route, keyed by tracking code. /application/<id>/ is
                # the reviewer view and requires a programme role.
                return JsonResponse({
                    "success": True,
                    "app_id": str(app_id),
                    "redirect_url": f"/application-details/{tracking_code_db}/"
                })
        
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON - {str(e)}")
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error fetching application: {str(e)}")
            print(f"ERROR: Exception - {str(e)}")
            print(f"{'='*60}\n")
            return JsonResponse({"error": "Server error"}, status=500)
    
    return JsonResponse({"error": "Method not allowed"}, status=405)


def application_details_by_tracking(request, tracking_code):
    """Display application details by tracking code - Accessible without login"""
    try:
        print(f"\n{'='*60}")
        print(f"APPLICATION_DETAILS_BY_TRACKING VIEW CALLED")
        print(f"Tracking Code: {tracking_code}")
        print(f"{'='*60}\n")
        
        with connection.cursor() as cursor:
            ensure_reviewer_evaluations_table(cursor)
            # Fetch application by tracking code
            cursor.execute("""
                SELECT *
                FROM "APPLICATIONS"
                WHERE "TRACKING_CODE" = %s
                LIMIT 1;
            """, [tracking_code])
            
            # Lowercased to match application_details: details.html looks up
            # application.travel_budget etc., and the `default` filter resolves
            # its argument strictly, so uppercase keys raise instead of
            # rendering blank. This page 500'd for every valid tracking code.
            colnames = [desc[0].lower() for desc in cursor.description]
            row = cursor.fetchone()

            print(f"Column Names: {colnames}")
            print(f"Row Data: {row}")
            print(f"Row Type: {type(row)}")
            if row:
                print(f"Row Length: {len(row)}")
            
            if not row:
                print(f"ERROR: No application found for tracking code: {tracking_code}")
                print(f"{'='*60}\n")
                return render(request, "404.html", {"message": "Application not found"}, status=404)
            
            application = dict(zip(colnames, row))
            program = application.get('program') or permissions.PROGRAM_TRAVEL

            # Resolve status display for student
            computed_status = get_user_application_status(
                raw_status=application.get("status"),
                program=program,
                user_id=None,
                user_role=None,
                application_id=application.get("id"),
                cursor=cursor
            )
            application["status"] = computed_status
            application["status_display"] = computed_status
            application["notified_status_display"] = get_status_display(application.get("notified_status"))
            _localise_row(application, 'created_at', 'updated_at', 'reviewed_at', 'notified_at')

            # Same programme awareness as the authenticated detail view, so an
            # RFG applicant tracking their own application sees it labelled and
            # laid out as RFG rather than as an empty Travel form.
            rfg_detail = None
            if program == permissions.PROGRAM_RFG:
                cursor.execute(
                    'SELECT * FROM "RFG_DETAILS" WHERE "APPLICATION_ID" = %s',
                    [application.get('id')])
                detail_row = cursor.fetchone()
                if detail_row:
                    detail_cols = [d[0].lower() for d in cursor.description]
                    rfg_detail = dict(zip(detail_cols, detail_row))
                    rfg_detail["scheme_label"] = rfg.SCHEME_LABELS.get(
                        rfg_detail.get("scheme"), rfg_detail.get("scheme"))

            print(f"Application Dictionary:")
            for key, value in application.items():
                print(f"  {key}: {value} (Type: {type(value)})")
            print(f"{'='*60}\n")
            
            return render(request, "details.html", {
                "application": application,
                "program": program,
                "program_label": permissions.PROGRAM_LABELS.get(program, program),
                "rfg_detail": rfg_detail,
                "is_student": True,
            })
    
    except Exception as e:
        logger.error(f"Error fetching application details: {str(e)}")
        print(f"ERROR: Exception - {str(e)}")
        print(f"{'='*60}\n")
        return render(request, "error.html", {"error": str(e)}, status=500)


@csrf_exempt
def get_application_details_api(request):
    """API endpoint to fetch application details by tracking code - Accessible without login"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            tracking_code = data.get("tracking_code", "").strip()
            
            print(f"\n{'='*60}")
            print(f"GET_APPLICATION_DETAILS_API CALLED")
            print(f"Request Data: {data}")
            print(f"Tracking Code: {tracking_code}")
            print(f"{'='*60}\n")
            
            if not tracking_code:
                print("ERROR: Tracking code is empty")
                return JsonResponse({"error": "Tracking code is required"}, status=400)
            
            with connection.cursor() as cursor:
                # Fetch full application by tracking code
                cursor.execute("""
                    SELECT *
                    FROM "APPLICATIONS"
                    WHERE "TRACKING_CODE" = %s
                    LIMIT 1;
                """, [tracking_code])
                
                colnames = [desc[0] for desc in cursor.description]
                row = cursor.fetchone()
                
                print(f"Query Result: {row}")
                print(f"Column Names: {colnames}")
                
                if not row:
                    print(f"ERROR: Application not found for tracking code: {tracking_code}")
                    return JsonResponse({"error": "Application not found"}, status=404)
                
                application = dict(zip(colnames, row))
                
                # Convert non-serializable types to strings
                serializable_app = {}
                for key, value in application.items():
                    if isinstance(value, (datetime, date)):
                        serializable_app[key] = str(value)
                    elif isinstance(value, Decimal):
                        serializable_app[key] = float(value)
                    elif isinstance(value, UUID):
                        serializable_app[key] = str(value)
                    else:
                        serializable_app[key] = value
                
                print(f"SUCCESS: Application found")
                print(f"{'='*60}\n")
                
                return JsonResponse({
                    "success": True,
                    "application": serializable_app
                })
        
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON - {str(e)}")
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        except Exception as e:
            logger.error(f"Error fetching application: {str(e)}")
            print(f"ERROR: Exception - {str(e)}")
            print(f"{'='*60}\n")
            return JsonResponse({"error": "Server error"}, status=500)
    
    return JsonResponse({"error": "Method not allowed"}, status=405)
