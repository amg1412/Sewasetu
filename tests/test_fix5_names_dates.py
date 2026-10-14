"""Fix 5: names were cut to 20 BYTES (an Assamese name became ~7 letters) and dates
were read month-first although the form says DD/MM/YYYY; every validation failure
said 'Something went wrong'."""
import datetime
from conftest import citizen_login


def stored(db, mobile):
    db.execute("SELECT applicant_name, dob FROM applications WHERE mobile=%s", (mobile,))
    return db.fetchone()


def test_assamese_name_is_stored_in_full(db, submit):
    name = "প্ৰণৱ কুমাৰ দাস"
    submit("9700000001", applicant_name=name)
    assert stored(db, "9700000001")[0] == name


def test_hindi_and_long_latin_names_are_stored_in_full(db, submit):
    submit("9700000002", applicant_name="रामेश्वर प्रसाद यादव")
    assert stored(db, "9700000002")[0] == "रामेश्वर प्रसाद यादव"
    long_name = "Bhubaneswar Chandrasekhar Venkataraman Iyer"       # 43 chars
    submit("9700000003", applicant_name=long_name)
    assert stored(db, "9700000003")[0] == long_name


def test_stored_name_reads_back_in_the_admin_panel(client, submit):
    submit("9700000004", applicant_name="মিনতি হাজৰিকা")
    client.post("/admin", data={"username": "admin", "password": "test-admin-pass"})
    html = client.get("/admin/applications").get_data(as_text=True)
    assert "মিনতি হাজৰিকা" in html


def test_dates_are_day_first(db, submit):
    submit("9700000005", dob="05/03/1950")            # 5 March, not 3 May
    assert stored(db, "9700000005")[1] == datetime.date(1950, 3, 5)


def test_month_first_date_is_refused_with_a_clear_message(db, submit):
    html = submit("9700000006", dob="03/25/1950").get_data(as_text=True)
    assert "DD/MM/YYYY" in html
    assert stored(db, "9700000006") is None


def test_every_validation_failure_names_the_problem(db, submit):
    cases = {"applicant_name": "name", "village": "village", "bank_account": "bank",
             "dob": "date of birth", "block": "block"}
    for field, word in cases.items():
        html = submit("9700000007", **{field: ""}).get_data(as_text=True)
        assert "Something went wrong" not in html, field
        assert word in html.lower(), field
    assert stored(db, "9700000007") is None


def test_underage_message_still_explains_eligibility(submit):
    html = submit("9700000008", dob="01/01/2000").get_data(as_text=True)
    assert "60" in html


def test_bad_mobile_and_bad_login_are_explained(client, make_app):
    html = client.post("/apply", data={"mobile": "12345"}).get_data(as_text=True)
    assert "10-digit" in html and "Something went wrong" not in html
    make_app("9700000009")
    html = client.post("/status", data={"mobile": "9700000009", "password": "nope"}
                       ).get_data(as_text=True)
    assert "DDMMYYYY" in html and "Something went wrong" not in html
