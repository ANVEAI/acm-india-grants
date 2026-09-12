import os
import re
import json
import time
import hashlib
import logging
import random
import random
from decimal import Decimal
from datetime import datetime, timedelta, date
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import (
    JsonResponse, FileResponse, Http404, HttpResponse, HttpResponseNotFound
)
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.core.files.storage import FileSystemStorage
from django.db import connection, transaction

from home import permissions
from backend import rfg


logger = logging.getLogger("django")


# ============================================================
# DATABASE CONNECTION (THE ONLY ONE USED)
# ============================================================

def admin_api_login_required(view_func):
    """Guard for the administration APIs below.

    These predate the current login flow and were reachable by anyone. They
    answer in JSON, so an unauthenticated caller gets 403 rather than a
    redirect to the login page.
    """
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Authentication required"}, status=403)
        return view_func(request, *args, **kwargs)
    _wrapped.__name__ = view_func.__name__
    return _wrapped


def get_db_connection():
    return connection 

# ============================================================
# JSON HELPERS
# ============================================================
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return json.JSONEncoder.default(self, obj)


def json_response(data, status=200):
    """
    Fixed JSON response helper function
    """
    return JsonResponse(data, status=status, safe=False, json_dumps_params={'ensure_ascii': False})
# ============================================================
# TIME HELPERS
# ============================================================
def get_ist_timestamp():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# LOGIN VIEW
# ============================================================
def login_view(request):
    logger.info("Rendering login page or handling login request")

    if request.method == "POST":
        email = request.POST.get('email')
        password = request.POST.get('password')

        if not email or not password:
            return render(request, 'login.html', {"error": "Email and password are required"})

        hashed_password = hashlib.md5(password.encode()).hexdigest()

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT "NAME","ROLE","EMAIL","ID"
                FROM "USERS"
                WHERE "EMAIL"=%s AND "PASSWORD"=%s
                AND "STATUS"='Active'
                LIMIT 1
            """, [email, hashed_password])

            user = cursor.fetchone()

            if user:
                user_name, user_role, user_email, user_id = user

                # Optionally, create/get Django auth user
                user_obj, created = User.objects.get_or_create(
                    username=email,
                    defaults={"first_name": user_name, "email": user_email}
                )

                auth_login(request, user_obj)  # log in Django user

                # Written AFTER auth_login on purpose: login() flushes the session
                # when a different user was previously authenticated in it, which
                # would silently wipe these four keys and leave an authenticated
                # session with no role.
                request.session['user_name'] = user_name
                request.session['user_role'] = user_role
                request.session['user_email'] = user_email
                request.session['user_id'] = user_id

                # "Remember me" keeps the session alive across browser restarts.
                # Unticked, set_expiry(0) makes it a browser-session cookie while
                # the stored session still honours SESSION_COOKIE_AGE.
                if request.POST.get('remember'):
                    request.session.set_expiry(settings.REMEMBER_ME_SESSION_AGE)
                else:
                    request.session.set_expiry(0)

                logger.info(f"User {user_name} logged in successfully")

                # Redirect to home/dashboard
                return redirect('dashboard')

            # Invalid credentials
            return render(request, 'login.html', {"error": "Invalid email or password"})

        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return render(request, 'login.html', {"error": "Internal server error"})

        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    # GET request
    return render(request, 'login.html', {"error": None})


# ============================================================
# UPDATE USER (ADMIN)
# ============================================================
@admin_api_login_required
def update_user_admin(request):
    user_list = []
    selected_user = None

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT "ID","NAME","EMAIL" FROM "USERS" ORDER BY "ID"')
    user_list = cursor.fetchall()

    # FETCH USER DETAILS
    if request.method == 'GET' and 'user_id' in request.GET:
        user_id = request.GET['user_id']
        cursor.execute("""
            SELECT "ID","NAME","EMAIL","MOBILE_NO","DESIGNATION","ROLE"
            FROM "USERS" WHERE "ID"=%s
        """, [user_id])

        row = cursor.fetchone()
        if row:
            selected_user = {
                'id': row[0],
                'name': row[1],
                'email': row[2],
                'mobile_no': row[3],
                'designation': row[4],
                'role': row[5]
            }

    # UPDATE USER
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        name = request.POST.get('name')
        email = request.POST.get('email')
        mobile = request.POST.get('mobile_no')
        designation = request.POST.get('designation')
        role = request.POST.get('role')
        password = request.POST.get('password')

        update_fields = [
            ('"NAME"', name),
            ('"EMAIL"', email),
            ('"MOBILE_NO"', mobile),
            ('"DESIGNATION"', designation),
            ('"ROLE"', role)
        ]

        if password:
            md5_pass = hashlib.md5(password.encode()).hexdigest()
            update_fields.append(('"PASSWORD"', md5_pass))

        set_clause = ", ".join([f"{col}=%s" for col, _ in update_fields])
        values = [val for _, val in update_fields]
        values.append(user_id)

        cursor.execute(f"""
            UPDATE "USERS" SET {set_clause}, "UPDATED_AT"=CURRENT_TIMESTAMP WHERE "ID"=%s
        """, values)
        conn.commit()

        messages.success(request, "User updated successfully.")
        return redirect(f'/api/admin/update-user?user_id={user_id}')

    cursor.close()
    conn.close()

    return render(request, "updateuser.html", {
        "users": user_list,
        "selected_user": selected_user
    })


# ============================================================
# ADD USER
# ============================================================
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"png", "jpg", "jpeg"}


@admin_api_login_required
def submit_add_user(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    name = request.POST.get("name")
    designation = request.POST.get("designation")
    email = request.POST.get("email")
    mobile_no = request.POST.get("mobile_no")
    role = request.POST.get("role")
    password = request.POST.get("password")
    username = request.POST.get("username")
    photo = request.FILES.get("photo")

    if photo and not allowed_file(photo.name):
        return JsonResponse({"detail": "Invalid file type"}, status=400)

    upload_folder = os.path.join(settings.MEDIA_ROOT, "profile")
    original_filename = None

    if photo:
        # Use consistent naming: avatar_{username}.jpg
        original_filename = f"avatar_{username}.jpg"
        image_path = os.path.join(upload_folder, original_filename)
        
        # Create profile folder if it doesn't exist
        os.makedirs(upload_folder, exist_ok=True)
        
        # Delete existing photo if it exists
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
                logger.info(f"Deleted old profile photo: {image_path}")
            except Exception as e:
                logger.error(f"Error deleting old profile photo: {str(e)}")
        
        # Save new photo
        with open(image_path, 'wb') as f:
            for chunk in photo.chunks():
                f.write(chunk)

    md5_password = hashlib.md5(password.encode()).hexdigest()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO "USERS"
            ("NAME","DESIGNATION","EMAIL","MOBILE_NO","PHOTO","PASSWORD","ROLE","USERNAME")
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, [name, designation, email, mobile_no, original_filename,
              md5_password, role, username])

        conn.commit()

        messages.success(request, "User created successfully")
        return JsonResponse({"detail": "User created successfully"}, status=201)

    except psycopg2.IntegrityError:
        return JsonResponse({"detail": "Email or username already exists"}, status=400)

    except Exception as e:
        return JsonResponse({"detail": str(e)}, status=500)

    finally:
        cursor.close()
        conn.close()


ALLOWED_EXTENSIONS = ['.pdf']

def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


# Uploads were previously unvalidated on a public endpoint: any file type, any
# size. Travel keeps the 10 MB its form has always advertised; RFG uses the 1 MB
# its own form specifies.
TRAVEL_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def send_submission_email(subject, message, recipient_list, context=""):
    """Send a submission-related email without ever failing the submission.

    Returns True if it went out. Failures are logged rather than raised: the
    application row is already committed at this point, so a mail outage must
    not turn a successful submission into a 500 for the applicant.
    """
    from django.core.mail import send_mail as _send_mail
    from django.conf import settings as _settings

    if not recipient_list:
        return False
    try:
        sent = _send_mail(
            subject=subject,
            message=message,
            from_email=_settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
        )
    except Exception:
        logger.exception("Submission email failed (%s) to %s", context, recipient_list)
        return False

    if not sent:
        logger.error("Submission email not sent (%s) to %s", context, recipient_list)
    return bool(sent)


def travel_chairman_emails():
    """Active Travel chairmen, by programme role.

    Reads USER_PROGRAM_ROLES, not the legacy USERS.ROLE: a chairman appointed
    through the admin UI has ROLE='Reviewer' with a TRAVEL/Chairman programme
    role, and the old query would have skipped them entirely -- while still
    mailing someone whose Travel access had been revoked.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT u."EMAIL"
            FROM "USERS" u
            JOIN "USER_PROGRAM_ROLES" r ON r."USER_ID" = u."ID"
            WHERE r."PROGRAM" = 'TRAVEL' AND r."ROLE" = 'Chairman'
              AND u."STATUS" = 'Active'
        """)
        return [row[0] for row in cursor.fetchall() if row[0]]


def validate_upload(uploaded, label, max_bytes, errors, field):
    """PDF-only, size-capped. Records into `errors` rather than raising."""
    if uploaded is None:
        errors[field] = f"{label} is required"
        return

    if not allowed_file(uploaded.name or ""):
        errors[field] = f"{label} must be a PDF"
        return

    content_type = (getattr(uploaded, "content_type", "") or "").lower()
    if content_type and content_type != "application/pdf":
        errors[field] = f"{label} must be a PDF"
        return

    if uploaded.size and uploaded.size > max_bytes:
        errors[field] = f"{label} must be {max_bytes // (1024 * 1024)} MB or smaller"

import uuid
from datetime import datetime
from django.core.mail import send_mail
from django.conf import settings
import os, uuid, traceback
from datetime import datetime
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage

@csrf_exempt
def submit_travel_grant(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request method"}, status=405)

    try:
        import random
        import string
        from datetime import datetime

        def generate_tracking_code(conference_name, cursor, prefix=""):
            """<prefix><initials>-<ddmmyyHHMMSS>-<4 random>, unique.

            RFG codes carry an "RFG-" prefix so the programme is obvious from
            the code alone. Longest possible code is 26 chars; the column is
            varchar(32). Travel codes are unchanged.
            """
            words = conference_name.split()
            short_name = "".join([w[0] for w in words[:4]]).upper()
            short_name = short_name if short_name else "CONF"

            while True:
                timestamp = datetime.now().strftime("%d%m%y%H%M%S")
                rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
                code = f"{prefix}{short_name}-{timestamp}-{rand_part}"

                cursor.execute("""
                    SELECT 1 FROM "APPLICATIONS" WHERE "TRACKING_CODE"=%s
                """, [code])

                if not cursor.fetchone():
                    return code

        data = request.POST
        files = request.FILES

        # ==================================================================
        # RESEARCH FACILITATION GRANT
        # Handled here and returned early, so the Travel path below stays
        # exactly as it was.
        # ==================================================================
        program = (data.get("program") or "TRAVEL").strip().upper()
        if program not in ("TRAVEL", "RFG"):
            return JsonResponse({
                "status": "error",
                "message": "Please correct the highlighted fields.",
                "errors": {"program": "Choose a grant type"},
            }, status=400)

        if program == "RFG":
            shared_required = {
                "email": "Email",
                "applicant_name": "Applicant name",
                "institution_name": "Institution",
            }
            errors = {
                field: f"{label} is required"
                for field, label in shared_required.items()
                if not (data.get(field) or "").strip()
            }

            rfg_errors, scheme = rfg.validate(data, files, validate_upload)
            errors.update(rfg_errors)

            if errors:
                return JsonResponse({
                    "status": "error",
                    "message": "Please correct the highlighted fields.",
                    "errors": errors,
                }, status=400)

            spine = rfg.spine_values(data, scheme)
            detail = rfg.detail_values(data, scheme)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

            is_paper = scheme in rfg.PAPER_SCHEMES
            pending_uploads = (
                [("rfg_acceptance_letter", "letters", "letter"),
                 ("rfg_charges_doc", "rfg_charges", "charges")]
                if is_paper else
                [("rfg_invitation_letter", "rfg_invitations", "invitation")]
            )

            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO "APPLICATIONS"
                    ("PROGRAM","EMAIL","APPLICANT_NAME","INSTITUTION_NAME",
                     "MOBILE_PHONE","POSTAL_ADDRESS",
                     "CONFERENCE_NAME","CONFERENCE_VENUE",
                     "CONFERENCE_START_DATE","CONFERENCE_END_DATE","CONFERENCE_WEBSITE",
                     "PAPER_TITLE","TRAVEL_BUDGET","BUDGET_JUSTIFICATION")
                    VALUES ('RFG',%s,%s,%s,'','',%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING "ID";
                """, [
                    (data.get("email") or "").strip(),
                    (data.get("applicant_name") or "").strip(),
                    (data.get("institution_name") or "").strip(),
                    spine["conference_name"], spine["conference_venue"],
                    spine["conference_start_date"], spine["conference_end_date"],
                    spine["conference_website"], spine["paper_title"],
                    spine["travel_budget"], spine["budget_justification"],
                ])
                application_id = cursor.fetchone()[0]

                tracking_code = generate_tracking_code(
                    rfg.tracking_prefix_source(data, scheme), cursor, prefix="RFG-")
                cursor.execute(
                    'UPDATE "APPLICATIONS" SET "TRACKING_CODE"=%s WHERE "ID"=%s',
                    [tracking_code, application_id])

                # Files are written inside the transaction: if the DB work fails
                # we are left with unreferenced objects in the bucket rather
                # than a half-written application.
                saved = {}
                for field, folder, kind in pending_uploads:
                    upload = files.get(field)
                    ext = os.path.splitext(upload.name)[1] or ".pdf"
                    rel = os.path.join(
                        folder, f"{application_id}_{kind}_{timestamp}{ext}")
                    os.makedirs(os.path.join(settings.MEDIA_ROOT, folder), exist_ok=True)
                    with open(os.path.join(settings.MEDIA_ROOT, rel), "wb+") as fh:
                        for chunk in upload.chunks():
                            fh.write(chunk)
                    saved[field] = rel

                if "rfg_acceptance_letter" in saved:
                    cursor.execute(
                        'UPDATE "APPLICATIONS" SET "ACCEPTANCE_LETTER_PATH"=%s WHERE "ID"=%s',
                        [saved["rfg_acceptance_letter"], application_id])

                cursor.execute("""
                    INSERT INTO "RFG_DETAILS"
                    ("APPLICATION_ID","SCHEME","CORRESPONDENCE_EMAIL","DEPARTMENTS",
                     "AFFILIATION_STATUS","STUDENT_TYPE",
                     "FACULTY_CONTACT_NAME","FACULTY_CONTACT_EMAIL",
                     "PREVIOUS_RFG","PREVIOUS_RFG_DETAILS",
                     "PAPER_AUTHORS","PUBLICATION_VENUE_URL","PAPER_PDF_URL",
                     "CHARGES_DOC_PATH","EVENT_URL","INVITATION_LETTER_PATH",
                     "ORGANIZER_NAME","ORGANIZER_AFFILIATION","ORGANIZER_EMAIL",
                     "GRANT_HEADS","AMOUNT_BREAKDOWN")
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, [
                    application_id, detail["scheme"], detail["correspondence_email"],
                    detail["departments"], detail["affiliation_status"],
                    detail["student_type"], detail["faculty_contact_name"],
                    detail["faculty_contact_email"], detail["previous_rfg"],
                    detail["previous_rfg_details"], detail["paper_authors"],
                    detail["publication_venue_url"], detail["paper_pdf_url"],
                    saved.get("rfg_charges_doc"), detail["event_url"],
                    saved.get("rfg_invitation_letter"), detail["organizer_name"],
                    detail["organizer_affiliation"], detail["organizer_email"],
                    detail["grant_heads"], detail["amount_breakdown"],
                ])

            # ---- notifications (outside the transaction) ----
            applicant_email = (data.get("email") or "").strip()
            applicant_name = (data.get("applicant_name") or "").strip()
            scheme_label = rfg.SCHEME_LABELS.get(scheme, scheme)

            send_submission_email(
                subject="Research Facilitation Grant Application Submitted",
                message=f"""
Dear {applicant_name},

Your Research Facilitation Grant application has been submitted successfully.

Tracking Code: {tracking_code}
Scheme: {scheme_label}
Amount Requested: Rs. {spine['travel_budget']:.0f}

Please keep this tracking code for future reference.

Regards,
ACM India Research Facilitation Grant Committee
""",
                recipient_list=[applicant_email],
                context="RFG applicant confirmation",
            )

            # RFG chairmen only -- programme-scoped, so Travel chairmen are not
            # copied on RFG applications.
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT u."EMAIL"
                    FROM "USERS" u
                    JOIN "USER_PROGRAM_ROLES" r ON r."USER_ID" = u."ID"
                    WHERE r."PROGRAM" = 'RFG' AND r."ROLE" = 'Chairman'
                      AND u."STATUS" = 'Active'
                """)
                chairman_emails = [row[0] for row in cursor.fetchall() if row[0]]

            if chairman_emails:
                send_submission_email(
                    subject="New Research Facilitation Grant Application Received",
                    message=f"""
A new Research Facilitation Grant application has been submitted.

Applicant: {applicant_name}
Email: {applicant_email}
Tracking Code: {tracking_code}
Scheme: {scheme_label}
Amount Requested: Rs. {spine['travel_budget']:.0f}

Please review it in the system.
""",
                    recipient_list=chairman_emails,
                    context="RFG chairman copy",
                )

            return JsonResponse({"status": "success", "tracking_code": tracking_code})

        # --- Validation ---
        # This endpoint is public and csrf_exempt, so the checks in
        # travel_grant_form.html are advisory only; these are the enforcing ones.
        # postal_address, faculty_phone, faculty_address and faculty_designation
        # are deliberately absent below: they are optional.
        REQUIRED_FIELDS = {
            "email": "Email",
            "applicant_name": "Applicant name",
            "institution_name": "Institution",
            "mobile_phone": "Mobile phone",
            "enrolment_type": "Enrolment type",
            "current_degree_type": "Degree type",
            "current_degree_program": "Degree program",
            "faculty_name": "Faculty name",
            "faculty_email": "Faculty email",
            "conference_name": "Conference name",
            "conference_website": "Conference website",
            "conference_start_date": "Start date",
            "conference_end_date": "End date",
            "conference_location": "Conference location",
            "paper_submission_deadline": "Paper submission deadline",
            "acceptance_notification_date": "Acceptance notification date",
            "paper_type": "Paper type",
            "paper_title": "Paper title",
            "requested_amount": "Amount",
            "registration_fee": "Registration fee",
            "budget_justification": "Justification",
            "previous_grant": "Previous grant answer",
        }

        errors = {}

        for field, label in REQUIRED_FIELDS.items():
            if not (data.get(field) or "").strip():
                errors[field] = f"{label} is required"

        for field, label in (("paper_file", "Paper file"),
                             ("acceptance_letter", "Acceptance letter")):
            validate_upload(files.get(field), label,
                            TRAVEL_MAX_UPLOAD_BYTES, errors, field)

        # Conditional: the previous conference dates only matter when the
        # applicant says they have had a grant before. Must be a real dd-mm-yyyy
        # date — the regex pins the shape (strptime's %d/%m would also accept
        # 1-2-2023) and strptime then rejects impossible dates like 31-02-2023.
        if (data.get("previous_grant") or "").strip() == "Yes":
            previous_dates = (data.get("previous_conference_dates") or "").strip()
            if not previous_dates:
                errors["previous_conference_dates"] = "Previous conference dates are required"
            elif not re.fullmatch(r"\d{2}-\d{2}-\d{4}", previous_dates):
                errors["previous_conference_dates"] = (
                    "Enter the date as dd-mm-yyyy (e.g. 15-01-2023)")
            else:
                try:
                    datetime.strptime(previous_dates, "%d-%m-%Y")
                except ValueError:
                    errors["previous_conference_dates"] = (
                        "That date does not exist. Use dd-mm-yyyy (e.g. 15-01-2023)")

        # Check numerics before float() below, so a non-numeric value cannot
        # escape as a ValueError and reach the applicant as a 500.
        for field, label in (("registration_fee", "Registration fee"),
                             ("requested_amount", "Amount")):
            raw = (data.get(field) or "").strip()
            if raw and field not in errors:
                try:
                    if float(raw) < 0:
                        errors[field] = f"{label} cannot be negative"
                except ValueError:
                    errors[field] = f"{label} must be a number"

        # Both date columns are NOT NULL, and nothing previously stopped an end
        # date that precedes the start date.
        parsed_dates = {}
        for field, label in (("conference_start_date", "Start date"),
                             ("conference_end_date", "End date"),
                             ("paper_submission_deadline", "Paper submission deadline"),
                             ("acceptance_notification_date", "Acceptance notification date")):
            raw = (data.get(field) or "").strip()
            if raw and field not in errors:
                try:
                    parsed_dates[field] = datetime.strptime(raw, "%Y-%m-%d").date()
                except ValueError:
                    errors[field] = f"{label} must be a valid date (YYYY-MM-DD)"

        if ("conference_start_date" in parsed_dates and "conference_end_date" in parsed_dates
                and parsed_dates["conference_end_date"] < parsed_dates["conference_start_date"]):
            errors["conference_end_date"] = "End date cannot be before the start date"

        if ("paper_submission_deadline" in parsed_dates
                and "acceptance_notification_date" in parsed_dates
                and parsed_dates["acceptance_notification_date"]
                    < parsed_dates["paper_submission_deadline"]):
            errors["acceptance_notification_date"] = (
                "Acceptance date cannot be before the submission deadline")

        if errors:
            return JsonResponse({
                "status": "error",
                "message": "Please correct the highlighted fields.",
                "errors": errors,
            }, status=400)

        # --- Extract form fields ---
        email = data.get("email") or ""
        applicant_name = data.get("applicant_name") or ""
        institution_name = data.get("institution_name") or ""
        mobile_phone = data.get("mobile_phone") or ""
        postal_address = data.get("postal_address") or ""
        enrolment_type = data.get("enrolment_type") or ""
        current_degree_type = data.get("current_degree_type") or "Other"
        current_degree_program = data.get("current_degree_program") or "Other"

        faculty_name = data.get("faculty_name") or "Not Provided"
        faculty_email = data.get("faculty_email") or ""
        faculty_phone = data.get("faculty_phone") or ""
        faculty_address = data.get("faculty_address") or ""
        faculty_designation = data.get("faculty_designation") or "Other"

        conference_name = data.get("conference_name") or ""
        conference_website = data.get("conference_website") or ""
        conference_start_date = data.get("conference_start_date") or None
        conference_end_date = data.get("conference_end_date") or None
        conference_venue = data.get("conference_location") or ""
        paper_submission_deadline = data.get("paper_submission_deadline") or None
        acceptance_notification_date = data.get("acceptance_notification_date") or None
        paper_type = data.get("paper_type") or ""

        registration_fee = float(data.get("registration_fee") or 0.0)
        requested_amount = float(data.get("requested_amount") or 0.0)

        paper_title = data.get("paper_title") or "No Title"
        paper_details = data.get("paper_details") or "No details provided"
        budget_justification = data.get("budget_justification") or ""

        previous_grant = data.get("previous_grant") == "Yes"
        previous_conference_name = data.get("previous_conference_name") or ""
        previous_conference_dates = data.get("previous_conference_dates") or ""

        supervisor_name = faculty_name

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        paper_file_path = None
        acceptance_letter_path = None

        if files.get("paper_file"):
            paper_file = files["paper_file"]
            ext = os.path.splitext(paper_file.name)[1]
            paper_file_path = (paper_file, ext)

        if files.get("acceptance_letter"):
            letter_file = files["acceptance_letter"]
            ext = os.path.splitext(letter_file.name)[1]
            acceptance_letter_path = (letter_file, ext)

        # --- DB INSERT ---
        # Everything below runs in one transaction. Previously the INSERT
        # committed immediately, so a failure in the tracking-code UPDATE or a
        # file write left a half-written application in the table.
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("""
            INSERT INTO "APPLICATIONS"
            ("EMAIL","APPLICANT_NAME","INSTITUTION_NAME","MOBILE_PHONE","POSTAL_ADDRESS",
             "ENROLMENT_TYPE","CURRENT_DEGREE_TYPE","CURRENT_DEGREE_PROGRAM",
             "CONFERENCE_NAME","CONFERENCE_VENUE","CONFERENCE_START_DATE","CONFERENCE_END_DATE",
             "CONFERENCE_WEBSITE","SUPERVISOR_NAME",
             "FACULTY_EMAIL","FACULTY_PHONE","FACULTY_ADDRESS","FACULTY_DESIGNATION",
             "PAPER_SUBMISSION_DEADLINE","ACCEPTANCE_NOTIFICATION_DATE","PAPER_TYPE",
             "PAPER_TITLE","PAPER_DETAILS","REGISTRATION_FEE","TRAVEL_BUDGET","BUDGET_JUSTIFICATION",
             "PREVIOUS_GRANT","PREVIOUS_CONFERENCE_NAME","PREVIOUS_CONFERENCE_DATES")
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING "ID";
            """, [
                email, applicant_name, institution_name, mobile_phone, postal_address,
                enrolment_type, current_degree_type, current_degree_program,
                conference_name, conference_venue, conference_start_date, conference_end_date,
                conference_website, supervisor_name,
                faculty_email, faculty_phone, faculty_address, faculty_designation,
                paper_submission_deadline, acceptance_notification_date, paper_type,
                paper_title, paper_details, registration_fee, requested_amount,
                budget_justification, previous_grant,
                previous_conference_name, previous_conference_dates
            ])

            application_id = cursor.fetchone()[0]

            # ✅ NEW TRACKING CODE
            tracking_code = generate_tracking_code(conference_name, cursor)

            cursor.execute("""
                UPDATE "APPLICATIONS" SET "TRACKING_CODE"=%s WHERE "ID"=%s
            """, [tracking_code, application_id])

            # --- FILE SAVING ---
            if paper_file_path:
                paper_file, ext = paper_file_path
                paper_name = f"{application_id}_paper_{timestamp}{ext}"
                paper_dir = os.path.join(settings.MEDIA_ROOT, "papers")
                os.makedirs(paper_dir, exist_ok=True)
                paper_path = os.path.join("papers", paper_name)

                with open(os.path.join(settings.MEDIA_ROOT, paper_path), "wb+") as f:
                    for chunk in paper_file.chunks():
                        f.write(chunk)

                cursor.execute("""
                    UPDATE "APPLICATIONS" SET "PAPER_FILE_PATH"=%s WHERE "ID"=%s
                """, [paper_path, application_id])

            if acceptance_letter_path:
                letter_file, ext = acceptance_letter_path
                letter_name = f"{application_id}_letter_{timestamp}{ext}"
                letter_dir = os.path.join(settings.MEDIA_ROOT, "letters")
                os.makedirs(letter_dir, exist_ok=True)
                letter_path = os.path.join("letters", letter_name)

                with open(os.path.join(settings.MEDIA_ROOT, letter_path), "wb+") as f:
                    for chunk in letter_file.chunks():
                        f.write(chunk)

                cursor.execute("""
                    UPDATE "APPLICATIONS" SET "ACCEPTANCE_LETTER_PATH"=%s WHERE "ID"=%s
                """, [letter_path, application_id])

        # ================= EMAIL NOTIFICATIONS =================

        send_submission_email(
            subject="Travel Grant Application Submitted",
            message=f"""
Dear {applicant_name},

Your Travel Grant application has been submitted successfully.

Tracking Code: {tracking_code}
Paper Title: {paper_title}
Conference: {conference_name}

Please keep this tracking code for future reference.

Regards,
Student Travel Grant Committee
""",
            recipient_list=[email],
            context="Travel applicant confirmation",
        )

        chairman_emails = travel_chairman_emails()

        if chairman_emails:
            send_submission_email(
                subject="New Travel Grant Application Received",
                message=f"""
A new Travel Grant application has been submitted.

Applicant: {applicant_name}
Email: {email}
Enrolment Type: {enrolment_type}
Tracking Code: {tracking_code}
Paper Title: {paper_title}
Paper Type: {paper_type}
Conference: {conference_name}

Please review it in the system.
""",
                recipient_list=chairman_emails,
                context="Travel chairman copy",
            )

        return JsonResponse({"status": "success", "tracking_code": tracking_code})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
# --------------------------------------------------------
# ADD NEW USER
# --------------------------------------------------------
@csrf_exempt
@admin_api_login_required
def add_user(request):
    try:
        name = request.POST.get("name")
        email = request.POST.get("email")
        username = request.POST.get("username")
        mobile_no = request.POST.get("mobile_no")
        designation = request.POST.get("designation")
        role = request.POST.get("role")
        password = request.POST.get("password")

        hashed_password = hashlib.sha256(password.encode()).hexdigest()

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO "USERS" 
            ("NAME", "EMAIL", "MOBILE_NO", "DESIGNATION", "PASSWORD", "ROLE", "USERNAME")
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (name, email, mobile_no, designation, hashed_password, role, username))

        conn.commit()
        cursor.close()
        conn.close()

        return JsonResponse({"status": "success"}, status=201)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


# --------------------------------------------------------
# GET USER BY ID (FOR EDIT MODAL)
# --------------------------------------------------------
@admin_api_login_required
def get_user(request):
    user_id = request.GET.get("id")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                "ID", "NAME", "EMAIL", "MOBILE_NO", "DESIGNATION",
                "ROLE", "USERNAME"
            FROM "USERS"
            WHERE "ID" = %s
        """, (user_id,))

        r = cursor.fetchone()

        cursor.close()
        conn.close()

        if not r:
            return JsonResponse({"error": "User not found"}, status=404)

        return JsonResponse({
            "id": r[0],
            "name": r[1],
            "email": r[2],
            "mobile_no": r[3],
            "designation": r[4],
            "role": r[5],
            "username": r[6]
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# --------------------------------------------------------
# UPDATE USER
# --------------------------------------------------------
@csrf_exempt
@admin_api_login_required
def update_user(request):
    try:
        user_id = request.POST.get("id")
        name = request.POST.get("name")
        mobile_no = request.POST.get("mobile_no")
        designation = request.POST.get("designation")
        role = request.POST.get("role")

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE "USERS"
            SET "NAME" = %s, "MOBILE_NO" = %s, "DESIGNATION" = %s,
                "ROLE" = %s, "UPDATED_AT" = CURRENT_TIMESTAMP
            WHERE "ID" = %s
        """, (name, mobile_no, designation, role, user_id))

        conn.commit()
        cursor.close()
        conn.close()

        return JsonResponse({"status": "updated"})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


# --------------------------------------------------------
# ACTIVATE / DEACTIVATE USER
# (since USERS table has no "IS_ACTIVE", we toggle ROLE to "INACTIVE")
# --------------------------------------------------------
@admin_api_login_required
def toggle_user(request):
    user_id = request.GET.get("id")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get current role
        cursor.execute("""SELECT "ROLE" FROM "USERS" WHERE "ID" = %s""", (user_id,))
        row = cursor.fetchone()

        if not row:
            return JsonResponse({"error": "User not found"}, status=404)

        current_role = row[0]

        # Toggle role
        new_role = "INACTIVE" if current_role != "INACTIVE" else "USER"

        cursor.execute("""
            UPDATE "USERS"
            SET "ROLE" = %s, "UPDATED_AT" = CURRENT_TIMESTAMP
            WHERE "ID" = %s
        """, (new_role, user_id))

        conn.commit()
        cursor.close()
        conn.close()

        return JsonResponse({"status": "toggled", "new_role": new_role})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)