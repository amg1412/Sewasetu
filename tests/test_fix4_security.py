"""Fix 4: any citizen could read any other citizen's record (name, DOB, bank
account), approve applications, read OTPs, take over the admin with a published
password, or inject SQL. Sequential ids + DOB passwords made it a phone-book."""
import types
from flask.sessions import SecureCookieSessionInterface
from conftest import citizen_login, sha


def two_citizens(make_app):
    a = make_app("9600000001", name="Alice A", dob="1950-03-15")
    b = make_app("9600000002", name="Bob B", dob="1948-07-09")
    return a, b


def test_citizen_can_view_own_application(client, make_app):
    a, b = two_citizens(make_app)
    citizen_login(client, "9600000001", "15031950")
    r = client.get("/application/%d" % a)
    assert r.status_code == 200 and "Alice A" in r.get_data(as_text=True)


def test_citizen_cannot_view_someone_elses_application(client, make_app):
    a, b = two_citizens(make_app)
    citizen_login(client, "9600000001", "15031950")
    r = client.get("/application/%d" % b)
    assert r.status_code in (403, 404)
    assert "Bob B" not in r.get_data(as_text=True)


def test_citizen_cannot_download_someone_elses_acknowledgment(client, make_app):
    a, b = two_citizens(make_app)
    citizen_login(client, "9600000001", "15031950")
    assert client.get("/ack/%d.pdf" % b).status_code in (403, 404)


def test_citizen_session_cannot_approve_or_reject(client, make_app, db):
    a, b = two_citizens(make_app)
    citizen_login(client, "9600000001", "15031950")
    assert client.post("/admin/approve/%d" % b).status_code == 403
    assert client.post("/admin/reject/%d" % b).status_code == 403
    db.execute("SELECT status FROM applications WHERE id=%s", (b,))
    assert db.fetchone()[0] == "PENDING"


def test_published_admin_password_no_longer_works(client):
    r = client.post("/admin", data={"username": "admin", "password": "sewasetu@123"})
    assert r.status_code == 200          # login page again, not a redirect
    assert client.get("/admin/dashboard").status_code == 302


def test_configured_admin_password_works(client, db):
    r = client.post("/admin", data={"username": "admin", "password": "test-admin-pass"})
    assert r.status_code == 302
    assert client.get("/admin/dashboard").status_code == 200


def test_sql_injection_in_password_reset_is_inert(client, make_app, db):
    a, b = two_citizens(make_app)
    db.execute("UPDATE portal_users SET password_hash=%s WHERE mobile='9600000001'", (sha("secret-pass"),))
    client.post("/status/reset", data={"mobile": "x' OR mobile='9600000001"})
    db.execute("SELECT password_hash FROM portal_users WHERE mobile='9600000001'")
    assert db.fetchone()[0] == sha("secret-pass")      # not reset to DOB
    assert client.post("/status/reset", data={"mobile": "'"}).status_code == 200


def test_legacy_password_hash_is_upgraded_on_login(client, make_app, db):
    two_citizens(make_app)
    citizen_login(client, "9600000001", "15031950")
    db.execute("SELECT password_hash FROM portal_users WHERE mobile='9600000001'")
    stored = db.fetchone()[0]
    assert stored != sha("15031950") and ":" in stored and len(stored) > 64
    client.get("/status")      # and the new hash still logs the same citizen in
    c2 = client.application.test_client()
    assert citizen_login(c2, "9600000001", "15031950").status_code == 302


def test_leaked_secret_key_cannot_forge_an_admin_session(client):
    leaked = types.SimpleNamespace(secret_key="ssp-prod-key-2023-donotshare")
    cookie = SecureCookieSessionInterface().get_signing_serializer(leaked).dumps(
        {"admin": True, "logged_in": True})
    client.set_cookie("localhost", "session", cookie)
    assert client.get("/admin/dashboard").status_code == 302
