"""Fix 1: submitting the declaration must not strand citizens (13,759 failed
submissions in the logs; record saved, citizen told 'error', retry says 'duplicate')."""
import time


def test_failure_after_save_still_gives_citizen_their_number(A, db, submit, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("pdf engine down")
    monkeypatch.setattr(A, "generate_acknowledgment", boom)
    r = submit("9111111111")
    assert r.status_code == 200
    db.execute("SELECT application_no FROM applications WHERE mobile='9111111111'")
    app_no = db.fetchone()[0]
    assert app_no in r.get_data(as_text=True)


def test_retry_shows_existing_application_number(db, make_app, submit):
    make_app("9222222222", app_no="SSP26777777")
    r = submit("9222222222")
    assert "SSP26777777" in r.get_data(as_text=True)
    db.execute("SELECT count(*) FROM applications WHERE mobile='9222222222'")
    assert db.fetchone()[0] == 1


def test_sms_does_not_block_the_response(A, monkeypatch, submit):
    monkeypatch.setattr(A.requests, "post", lambda *a, **k: time.sleep(1.5))
    t = time.time()
    submit("9333333333")
    assert time.time() - t < 0.8


def test_hot_lookup_columns_are_indexed(db):
    db.execute("SELECT indexdef FROM pg_indexes WHERE tablename IN ('applications','otps')")
    defs = " ".join(r[0] for r in db.fetchall())
    assert "(mobile)" in defs and "(status, submitted_at)" in defs
