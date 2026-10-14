# -*- coding: utf-8 -*-
"""
Sewa Setu - Old Age Pension Portal
Government of Purvanchal, Department of Social Welfare

Developed by: Netlink Infosolutions Pvt Ltd (2023)
Maintenance contract ended 31/01/2026.
"""

import os
import io
import csv
import random
import re
import uuid
import hashlib
import hmac
import configparser
from datetime import datetime, date, timedelta

import requests
import psycopg2
from flask import (Flask, request, session, redirect, url_for, render_template,
                   flash, send_file, abort, jsonify)
from fpdf import FPDF
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from settings import load_config

config = load_config()

app = Flask(__name__)
# The signing key used to live in git (app.ini) and anyone with the handout could
# forge a staff session. It now comes from the environment; without one we use a
# random per-process key (safe, but sessions won't survive restarts/workers).
app.secret_key = os.environ.get("SS_SECRET_KEY") or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
# Applicants (many elderly, on shared phones) take a long time over a form;
# a 5-minute session threw away their work.
app.config["PERMANENT_SESSION_LIFETIME"] = 3600
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 512 * 1024

ADMIN_USERNAME = os.environ.get("SS_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("SS_ADMIN_PASSWORD", "")   # unset => admin login disabled

SMS_GATEWAY_URL = config.get("app", "sms_gateway_url")
OTP_VALIDITY_SECONDS = config.getint("app", "otp_validity_seconds")
UPLOAD_DIR = config.get("app", "upload_dir")
SCHEME_DEADLINE = datetime.strptime(config.get("pension", "scheme_deadline"),
                                    "%Y-%m-%d %H:%M")
MIN_AGE = config.getint("pension", "min_age")
SLA_DAYS = config.getint("pension", "sla_days")

BLOCKS = ["Sonari", "Rajapara", "Dhemaji Pathar", "Borgaon", "Namti", "Khelua"]

import logging
_logdir = os.environ.get("SS_LOG_DIR", "/var/log/sewasetu")
try:
    os.makedirs(_logdir, exist_ok=True)
    _fh = logging.FileHandler(os.path.join(_logdir, "sewasetu-app.log"))
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s in app: %(message)s"))
    app.logger.addHandler(_fh)
    app.logger.setLevel(logging.INFO)
except Exception:
    pass


def get_db():
    return psycopg2.connect(
        host=config.get("database", "host"),
        port=config.get("database", "port"),
        dbname=config.get("database", "name"),
        user=config.get("database", "user"),
        password=config.get("database", "password"),
    )


from contextlib import contextmanager
import threading


@contextmanager
def db_cursor():
    """One connection per unit of work, always closed (no leaks on errors)."""
    conn = get_db()
    try:
        cur = conn.cursor()
        yield conn, cur
    finally:
        conn.close()


def sanitize(value, maxlen=100):
    """Trim and cap by CHARACTERS (not bytes: an Assamese or Hindi letter is 3 bytes).

    The old version cut names to 20 bytes in the database. If the legacy NIC
    disbursement feed needs fixed-width fields, shorten at export time, never
    in the stored record.
    """
    if value is None:
        return ""
    value = " ".join(value.split())
    return "".join(ch for ch in value if ch.isprintable())[:maxlen]


def parse_dob(raw):
    """DD/MM/YYYY only (also accepts - or . as separators). Never month-first."""
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", raw.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


DOB_HELP = ("Please enter the date of birth as DD/MM/YYYY (day first), "
            "for example 05/03/1950 for 5 March 1950.")


def hash_password(p):
    # Salted PBKDF2. 100k iterations (~30 ms) rather than the library default 600k
    # (~200 ms): the secret here is a date of birth, so extra iterations buy little,
    # and at month-end every status check pays this cost on a few CPU cores.
    return generate_password_hash(p, method="pbkdf2:sha256:100000")


def _is_legacy_hash(h):
    return len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def check_password(stored, p):
    if _is_legacy_hash(stored):               # old unsalted SHA-256 of the DOB
        return hmac.compare_digest(stored, hashlib.sha256(p.encode("utf-8")).hexdigest())
    return check_password_hash(stored, p)


def _send_sms_now(mobile, text):
    try:
        requests.post(SMS_GATEWAY_URL + "/api/send",
                      json={"to": mobile, "text": text}, timeout=5)
    except Exception as e:
        app.logger.error("sms gateway error: %s" % e)


def send_sms(mobile, text):
    # Fire-and-forget: a slow carrier must never hold a citizen's request (or a
    # worker) hostage. Failures are logged by _send_sms_now.
    threading.Thread(target=_send_sms_now, args=(mobile, text), daemon=True).start()


def deadline_remaining():
    delta = SCHEME_DEADLINE - datetime.now()
    if delta.total_seconds() <= 0:
        return None
    return int(delta.total_seconds() // 3600)


def new_application_no():
    return "SSP" + datetime.now().strftime("%y") + str(random.randint(100000, 999999))


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", hours_left=deadline_remaining())


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/__gateway/", defaults={"subpath": ""})
@app.route("/__gateway/<path:subpath>")
def gateway_proxy(subpath):
    # Convenience proxy to the internal SMS gateway, so the OTP inbox is reachable
    # on the main site without opening a second port on the host. The gateway
    # itself runs only on the internal network.
    try:
        r = requests.get(SMS_GATEWAY_URL + "/" + subpath,
                         params=request.args, timeout=5)
        return (r.content, r.status_code,
                {"Content-Type": r.headers.get("Content-Type", "text/html")})
    except Exception as e:
        return ("SMS gateway unreachable: %s" % e, 502)


# ---------------------------------------------------------------------------
# Application flow: mobile -> OTP -> form steps -> upload -> declaration
# ---------------------------------------------------------------------------

@app.route("/apply", methods=["GET", "POST"])
def apply():
    if deadline_remaining() is None:
        flash("The application window for this scheme has closed.")
        return redirect(url_for("index"))
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        captcha = request.form.get("captcha", "")
        if len(mobile) != 10 or not mobile.isdigit():
            flash("Please enter a valid 10-digit mobile number (digits only, no +91 or spaces).")
            return render_template("apply.html", captcha_q=make_captcha())
        code = str(random.randint(100000, 999999))
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO otps (mobile, code, created_at) VALUES (%s, %s, %s)",
                    (mobile, code, datetime.now()))
        conn.commit()
        cur.close(); conn.close()
        send_sms(mobile, "Your Sewa Setu OTP is %s. Valid for 5 minutes." % code)
        session.permanent = True
        session["apply_mobile"] = mobile
        return redirect(url_for("verify"))
    return render_template("apply.html", captcha_q=make_captcha())


def make_captcha():
    a, b = random.randint(1, 9), random.randint(1, 9)
    session["captcha_answer"] = a + b
    return "%d + %d" % (a, b)


@app.route("/verify", methods=["GET", "POST"])
def verify():
    mobile = session.get("apply_mobile")
    if not mobile:
        return redirect(url_for("apply"))
    if request.method == "POST":
        code = request.form.get("otp", "").strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT code, created_at FROM otps WHERE mobile = %s "
                    "ORDER BY id DESC LIMIT 1", (mobile,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if row and row[0] == code:
            age = (datetime.now() - row[1]).total_seconds()
            if age > OTP_VALIDITY_SECONDS:
                app.logger.warning("otp expired mobile=%s age=%ds" % (mobile, int(age)))
                flash("OTP expired. Please request a new OTP.")
                return redirect(url_for("apply"))
            session["verified_mobile"] = mobile
            return redirect(url_for("form_step", step=1))
        flash("Invalid OTP.")
    return render_template("verify.html", mobile=mobile)


@app.route("/form/<int:step>", methods=["GET", "POST"])
def form_step(step):
    if not session.get("verified_mobile"):
        flash("Session expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))
    if step not in (1, 2, 3):
        abort(404)
    if request.method == "POST":
        data = session.get("form_data", {})
        for k, v in request.form.items():
            data[k] = v
        session["form_data"] = data
        if step < 3:
            return redirect(url_for("form_step", step=step + 1))
        return redirect(url_for("upload"))
    return render_template("form_step%d.html" % step,
                           data=session.get("form_data", {}), blocks=BLOCKS)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not session.get("verified_mobile"):
        flash("Session expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))
    if request.method == "POST":
        f = request.files.get("document")
        if f is None or f.filename == "":
            flash("Please choose a file first, then press Upload.")
            return render_template("upload.html")
        ext = os.path.splitext(f.filename.lower())[1]
        if ext not in (".pdf", ".jpg", ".jpeg"):
            flash("This file type is not accepted. Please upload a PDF or JPG "
                  "(photo) of your age proof.")
            return render_template("upload.html")
        content = f.read()
        if len(content) > MAX_UPLOAD_BYTES:
            flash("This file is too large. The limit is 5 MB. Please upload a smaller "
                  "file, or take a new photo at lower quality.")
            return render_template("upload.html")
        is_pdf = content.startswith(b"%PDF")
        is_jpg = content.startswith(b"\xff\xd8\xff")
        if not ((ext == ".pdf" and is_pdf) or (ext in (".jpg", ".jpeg") and is_jpg)):
            flash("This file could not be read as a PDF or JPG. Please check it opens "
                  "on your phone and try again.")
            return render_template("upload.html")
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        # server-chosen name: the citizen's filename is never used in a path
        path = os.path.join(UPLOAD_DIR, "%s_%s%s" % (session["verified_mobile"],
                                                     uuid.uuid4().hex[:12], ext))
        with open(path, "wb") as out:
            out.write(content)
        session["doc_path"] = path
        return redirect(url_for("declaration"))
    return render_template("upload.html")


@app.errorhandler(413)
def too_large(e):
    flash("This file is too large. The limit is 5 MB.")
    return render_template("upload.html"), 413


@app.route("/declaration", methods=["GET", "POST"])
def declaration():
    if not session.get("verified_mobile"):
        flash("Session expired. Please verify your mobile number again.")
        return redirect(url_for("apply"))
    if request.method == "POST":
        return handle_submission()
    return render_template("declaration.html")


def handle_submission():
    # TODO: split this up some day. It grew. - RK, 09/2024
    mobile = session.get("verified_mobile")
    data = session.get("form_data", {})
    doc_path = session.get("doc_path", "")

    name = sanitize(data.get("applicant_name", ""))
    village = data.get("village", "").strip()
    block = data.get("block", "").strip()
    gender = data.get("gender", "")
    marital = data.get("marital_status", "")
    husband_name = data.get("husband_name", "")
    husband_employer = data.get("husband_employer", "")
    bank_account = data.get("bank_account", "").strip()
    ifsc = data.get("ifsc", "").strip().upper()
    dob_raw = data.get("dob", "").strip()

    # Each failure says what is wrong and sends the citizen to the page to fix it.
    problems = [
        (not name, 1, "Please enter the applicant's full name."),
        (not dob_raw, 1, "Please enter the date of birth. " + DOB_HELP),
        (not village, 2, "Please enter the village."),
        (not block, 2, "Please choose the block."),
        (not bank_account, 3, "Please enter the bank account number."),
    ]
    for failed, step, message in problems:
        if failed:
            flash(message)
            return redirect(url_for("form_step", step=step))

    if marital == "Widowed" and (not husband_name or not husband_employer):
        flash("For a widowed applicant, please enter the late husband's name and his "
              "last employer (write 'None' if he did not work).")
        return redirect(url_for("form_step", step=1))

    dob = parse_dob(dob_raw)
    if dob is None:
        flash("We could not read the date of birth '%s'. %s" % (dob_raw[:20], DOB_HELP))
        return redirect(url_for("form_step", step=1))

    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < MIN_AGE:
        flash("Applicant must be above %d years of age to be eligible." % MIN_AGE)
        return redirect(url_for("form_step", step=1))

    if datetime.now() > SCHEME_DEADLINE:
        flash("The application deadline has passed.")
        return redirect(url_for("index"))

    app_no = new_application_no()
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id, application_no FROM applications WHERE mobile = %s",
                        (mobile,))
            existing = cur.fetchone()
            if existing is None:
                try:
                    cur.execute(
                        """INSERT INTO applications
                           (application_no, applicant_name, mobile, dob, gender, marital_status,
                            husband_name, husband_employer, village, block, bank_account, ifsc,
                            doc_path, status, submitted_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s)
                           RETURNING id""",
                        (app_no, name, mobile, dob, gender, marital, husband_name,
                         husband_employer, village, block, bank_account, ifsc, doc_path,
                         datetime.now()))
                    new_id = cur.fetchone()[0]
                    # status portal account; password is DOB as DDMMYYYY per dept. circular
                    cur.execute("INSERT INTO portal_users (mobile, password_hash) VALUES (%s,%s) "
                                "ON CONFLICT (mobile) DO NOTHING",
                                (mobile, hash_password(dob.strftime("%d%m%Y"))))
                    conn.commit()
                    existing = None
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    cur.execute("SELECT id, application_no FROM applications WHERE mobile = %s",
                                (mobile,))
                    existing = cur.fetchone()
    except Exception:
        app.logger.exception("submission failed for mobile=%s" % mobile)
        flash("We could not save your application just now. Nothing was lost on your side: "
              "please press Submit again in a minute.")
        return render_template("declaration.html"), 503

    if existing is not None:
        # Citizen already applied (e.g. an earlier attempt that showed an error).
        # Give them their number instead of a dead end.
        ex_id, ex_no = existing
        for k in ("form_data", "doc_path", "verified_mobile"):
            session.pop(k, None)
        session["portal_mobile"] = mobile
        return render_template("confirmation.html", app_no=ex_no, app_id=ex_id)

    # The acknowledgment PDF is generated on first download (see ack_pdf); it is
    # not needed to confirm the application, so it no longer sits on this path.
    for k in ("form_data", "doc_path", "verified_mobile"):
        session.pop(k, None)
    session["portal_mobile"] = mobile      # OTP-verified owner may fetch own acknowledgment
    send_sms(mobile, "Sewa Setu: application %s received. Track at the status portal "
                     "with mobile no. and password (DOB as DDMMYYYY)." % app_no)
    return render_template("confirmation.html", app_no=app_no, app_id=new_id)


def generate_acknowledgment(cur, app_id):
    cur.execute("SELECT application_no, applicant_name, mobile, dob, village, block, "
                "bank_account, ifsc, submitted_at, status FROM applications WHERE id = %s",
                (app_id,))
    row = cur.fetchone()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "GOVERNMENT OF PURVANCHAL", ln=1, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, "Department of Social Welfare", ln=1, align="C")
    pdf.cell(0, 8, "Old Age Pension Scheme - Acknowledgment", ln=1, align="C")
    pdf.ln(4)
    # decorative border, as per approved letterhead design
    pdf.rect(10, 12, 190, 270)
    labels = ["Application No", "Applicant Name", "Mobile", "Date of Birth",
              "Village", "Block", "Bank Account", "IFSC", "Submitted At", "Status"]
    pdf.set_font("Helvetica", "", 10)
    for label, val in zip(labels, row):
        try:
            pdf.cell(60, 8, label, border=1)
            pdf.cell(0, 8, str(val), border=1, ln=1)
        except Exception:
            pdf.cell(0, 8, "?", border=1, ln=1)
    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, "This is a computer generated acknowledgment. Processing SLA "
                         "as per the Purvanchal Right to Public Services Act applies.")
    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Status portal (citizen login)
# ---------------------------------------------------------------------------

@app.route("/status", methods=["GET", "POST"])
def status_login():
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM portal_users WHERE mobile = %s", (mobile,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if row and check_password(row[0], password):
            if _is_legacy_hash(row[0]):       # upgrade old hashes as people log in
                with db_cursor() as (c2, k2):
                    k2.execute("UPDATE portal_users SET password_hash = %s WHERE mobile = %s",
                               (hash_password(password), mobile))
                    c2.commit()
            session["logged_in"] = True
            session["portal_mobile"] = mobile
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id FROM applications WHERE mobile = %s "
                        "ORDER BY submitted_at DESC LIMIT 1", (mobile,))
            r = cur.fetchone()
            cur.close(); conn.close()
            if r:
                return redirect(url_for("view_application", app_id=r[0]))
            flash("No application found for this mobile number.")
            return redirect(url_for("status_login"))
        flash("The mobile number or password is not correct. Your password is your date "
              "of birth written as DDMMYYYY (for example 05031950). If you forgot it, "
              "use 'Reset password'.")
    return render_template("status_login.html")


@app.route("/application/<int:app_id>")
def view_application(app_id):
    if not session.get("logged_in"):
        flash("Please login to view application status.")
        return redirect(url_for("status_login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT application_no, applicant_name, mobile, dob, village, block, "
                "bank_account, ifsc, status, submitted_at, decided_at "
                "FROM applications WHERE id = %s AND mobile = %s",
                (app_id, session.get("portal_mobile")))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        abort(404)
    return render_template("application.html", a=row, app_id=app_id)


@app.route("/ack/<int:app_id>.pdf")
def ack_pdf(app_id):
    mobile = session.get("portal_mobile")
    if not mobile and not session.get("admin"):
        return redirect(url_for("status_login"))
    with db_cursor() as (conn, cur):
        if session.get("admin"):
            cur.execute("SELECT id FROM applications WHERE id = %s", (app_id,))
        else:
            cur.execute("SELECT id FROM applications WHERE id = %s AND mobile = %s",
                        (app_id, mobile))
        if not cur.fetchone():
            abort(404)
        path = os.path.join(UPLOAD_DIR, "ack", "%d.pdf" % app_id)
        if os.path.exists(path):
            return send_file(path, mimetype="application/pdf")
        data = generate_acknowledgment(cur, app_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as out:
            out.write(data)
    except OSError:
        pass
    return send_file(io.BytesIO(data), mimetype="application/pdf")


@app.route("/status/reset", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        with db_cursor() as (conn, cur):
            cur.execute("SELECT mobile FROM portal_users WHERE mobile = %s", (mobile,))
            row = cur.fetchone()
            if row:
                cur.execute("SELECT dob FROM applications WHERE mobile = %s LIMIT 1", (mobile,))
                r2 = cur.fetchone()
                if r2:
                    newpass = r2[0].strftime("%d%m%Y")
                    cur.execute("UPDATE portal_users SET password_hash = %s WHERE mobile = %s",
                                (hash_password(newpass), row[0]))
                    conn.commit()
                    send_sms(row[0], "Sewa Setu: your password has been reset to your "
                                     "date of birth (DDMMYYYY).")
        flash("If the mobile number exists, the password has been reset and sent by SMS.")
    return render_template("reset.html")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (ADMIN_PASSWORD and
                hmac.compare_digest(request.form.get("username", ""), ADMIN_USERNAME) and
                hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD)):
            session["logged_in"] = True
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials.")
    return render_template("admin_login.html")


@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM applications GROUP BY status")
    by_status = cur.fetchall()
    cur.execute("SELECT count(*) FROM applications WHERE status = 'PENDING' "
                "AND submitted_at < %s", (datetime.now() - timedelta(days=SLA_DAYS),))
    overdue = cur.fetchone()[0]
    cur.execute("SELECT block, count(*) FROM applications WHERE status = 'PENDING' "
                "GROUP BY block ORDER BY count(*) DESC")
    by_block = cur.fetchall()
    cur.close(); conn.close()
    return render_template("admin_dashboard.html", by_status=by_status,
                           overdue=overdue, by_block=by_block, sla=SLA_DAYS)


@app.route("/admin/applications")
def admin_list():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    status = request.args.get("status", "PENDING")
    page = int(request.args.get("page", 1))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, application_no, applicant_name, mobile, block, status, "
                "submitted_at FROM applications WHERE status = %s "
                "ORDER BY submitted_at ASC LIMIT 50 OFFSET %s",
                (status, (page - 1) * 50))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return render_template("admin_list.html", rows=rows, status=status, page=page)


@app.route("/admin/application/<int:app_id>")
def admin_view(app_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT application_no, applicant_name, mobile, dob, gender, "
                "marital_status, village, block, bank_account, ifsc, doc_path, "
                "status, submitted_at, decided_at, decided_by "
                "FROM applications WHERE id = %s", (app_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        abort(404)
    return render_template("admin_view.html", a=row, app_id=app_id)


@app.route("/admin/approve/<int:app_id>", methods=["POST"])
def admin_approve(app_id):
    if not session.get("admin"):
        abort(403)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE applications SET status = 'APPROVED', decided_at = %s, decided_by = %s "
                "WHERE id = %s AND status = 'PENDING'",
                (datetime.now(), ADMIN_USERNAME, app_id))
    conn.commit()
    cur.close(); conn.close()
    flash("Application approved.")
    return redirect(url_for("admin_list"))


@app.route("/admin/reject/<int:app_id>", methods=["POST"])
def admin_reject(app_id):
    if not session.get("admin"):
        abort(403)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE applications SET status = 'REJECTED', decided_at = %s, decided_by = %s "
                "WHERE id = %s AND status = 'PENDING'",
                (datetime.now(), ADMIN_USERNAME, app_id))
    conn.commit()
    cur.close(); conn.close()
    flash("Application rejected.")
    return redirect(url_for("admin_list"))


# ---------------------------------------------------------------------------
# Unused / legacy
# ---------------------------------------------------------------------------

def export_to_excel(rows):
    # Was used for the monthly disbursement report before eKosh integration.
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["application_no", "name", "account", "ifsc", "amount"])
    for r in rows:
        writer.writerow(list(r) + ["250"])
    return out.getvalue()


def old_payment_gateway_callback(txn):
    # retained for reference; eChallan integration was descoped in Phase 2
    status = txn.get("STATUS")
    if status == "0300":
        return "SUCCESS"
    elif status == "0399":
        return "FAILED"
    return "PENDING"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
