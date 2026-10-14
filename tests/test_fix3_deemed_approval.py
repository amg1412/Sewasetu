"""Fix 3: the nightly deemed-approval job has crashed since March (it reads
config/settings.ini, which was renamed app.ini). Overdue applications stay PENDING
although the RTPS Act says they stand approved."""
import os, subprocess, sys
from conftest import ROOT, HOST, PWD, TESTDB

SCRIPT = os.path.join(ROOT, "app", "scripts", "deemed_approval.py")


def run(*args):
    env = dict(os.environ, SS_DB_HOST=HOST, SS_DB_NAME=TESTDB, SS_DB_PASSWORD=PWD,
               SS_SMS_URL="http://127.0.0.1:9")   # gateway down: must not matter
    return subprocess.run([sys.executable, SCRIPT, *args], env=env,
                          capture_output=True, text=True, timeout=60)


def status(db, mobile):
    db.execute("SELECT status, decided_by FROM applications WHERE mobile=%s", (mobile,))
    return db.fetchone()


def test_job_runs_and_approves_only_overdue_applications(db, make_app):
    make_app("9500000001", days_ago=20)
    make_app("9500000002", days_ago=3)
    r = run()
    assert r.returncode == 0, r.stderr
    assert status(db, "9500000001") == ("DEEMED_APPROVED", "RTPS-AUTO")
    assert status(db, "9500000002")[0] == "PENDING"


def test_dry_run_counts_but_changes_nothing(db, make_app):
    make_app("9500000003", days_ago=40)
    r = run("--dry-run")
    assert r.returncode == 0, r.stderr
    assert "1" in r.stdout and "dry" in r.stdout.lower()
    assert status(db, "9500000003")[0] == "PENDING"


def test_job_fails_loudly_when_database_unreachable():
    env = dict(os.environ, SS_DB_HOST="127.0.0.1", SS_DB_PORT="9")
    r = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True)
    assert r.returncode != 0          # cron / monitoring can see the failure
