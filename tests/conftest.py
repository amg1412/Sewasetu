"""Test harness: runs the real Flask app against an isolated Postgres database
(sewasetu_test, built from app/schema.sql). Never touches production data.

    createdb ... ; SS_DB_HOST=localhost pytest tests/
"""
import os, sys, tempfile, hashlib, datetime, pytest, psycopg2

HOST = os.environ.get("SS_DB_HOST", "localhost")
PWD = os.environ.get("SS_DB_PASSWORD", "sewasetu123")
USER = "sewasetu"
TESTDB = "sewasetu_test"
os.environ.update(SS_DB_HOST=HOST, SS_DB_NAME=TESTDB, SS_DB_PASSWORD=PWD,
                  SS_LOG_DIR=tempfile.mkdtemp(), SS_UPLOAD_DIR=tempfile.mkdtemp(),
                  SS_ADMIN_PASSWORD="test-admin-pass")
# NOTE: SS_SECRET_KEY deliberately NOT set (see test_fix4 forged-cookie test).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))


def _connect(dbname):
    return psycopg2.connect(host=HOST, dbname=dbname, user=USER, password=PWD)


@pytest.fixture(scope="session", autouse=True)
def _database():
    c = _connect("postgres"); c.autocommit = True
    cur = c.cursor()
    cur.execute("DROP DATABASE IF EXISTS %s" % TESTDB)
    cur.execute("CREATE DATABASE %s OWNER %s" % (TESTDB, USER))
    c.close()
    c = _connect(TESTDB); c.autocommit = True
    c.cursor().execute(open(os.path.join(ROOT, "app", "schema.sql")).read())
    c.close()


@pytest.fixture()
def A(monkeypatch):
    import app as module
    monkeypatch.setattr(module, "SCHEME_DEADLINE", datetime.datetime(2099, 1, 1))
    monkeypatch.setattr(module.requests, "post", lambda *a, **k: None)
    return module


@pytest.fixture()
def client(A):
    return A.app.test_client()


@pytest.fixture()
def db():
    c = _connect(TESTDB); c.autocommit = True
    cur = c.cursor()
    cur.execute("TRUNCATE applications, portal_users, otps RESTART IDENTITY")
    yield cur
    c.close()


def sha(p):
    return hashlib.sha256(p.encode()).hexdigest()


@pytest.fixture()
def make_app(db):
    """Insert a citizen the way the legacy system stored them (SHA-256 of DOB)."""
    def _make(mobile="9000000001", name="Test Citizen", dob="1950-03-15",
              status="PENDING", days_ago=0, app_no=None):
        sub = datetime.datetime.now() - datetime.timedelta(days=days_ago)
        app_no = app_no or "SSP26%06d" % (int(mobile) % 1000000)
        db.execute("""INSERT INTO applications (application_no, applicant_name, mobile, dob,
            gender, marital_status, village, block, bank_account, ifsc, status, submitted_at)
            VALUES (%s,%s,%s,%s,'Male','Married','Vill','Sonari','111122223333','SBIN0001234',%s,%s)
            RETURNING id""", (app_no, name, mobile, dob, status, sub))
        i = db.fetchone()[0]
        d = datetime.date.fromisoformat(dob)
        db.execute("INSERT INTO portal_users VALUES (%s,%s)", (mobile, sha(d.strftime("%d%m%Y"))))
        return i
    return _make


FORM = dict(applicant_name="Ramesh Kumar", dob="15/03/1950", gender="Male",
            marital_status="Married", village="Milanpur", block="Sonari",
            bank_account="123456789012", ifsc="sbin0001234")


@pytest.fixture()
def submit(client):
    """Drive the final step as an OTP-verified citizen with the given form data."""
    def _submit(mobile="9111111111", **over):
        with client.session_transaction() as s:
            s["verified_mobile"] = mobile
            s["form_data"] = dict(FORM, **over)
            s["doc_path"] = ""
        return client.post("/declaration", follow_redirects=True)
    return _submit


def citizen_login(client, mobile, password):
    return client.post("/status", data={"mobile": mobile, "password": password})
