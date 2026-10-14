"""Fix 2: the upload step rejected most citizens with the cryptic 'ERR_VAL_47'.
The page promises JPG or PDF up to 5 MB; the code accepted PDF up to 100 KB."""
import io, os

PDF = b"%PDF-1.4\n" + b"x" * 1000
JPG = b"\xff\xd8\xff\xe0" + b"x" * 1000


def _login(client, mobile="9444444444"):
    with client.session_transaction() as s:
        s["verified_mobile"] = mobile


def _up(client, name, data):
    return client.post("/upload", data={"document": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def test_photo_taken_on_a_phone_is_accepted(client):
    _login(client)
    r = _up(client, "birth-cert.jpg", JPG + b"y" * 900_000)   # ~0.9 MB phone photo
    assert r.status_code == 302 and "/declaration" in r.headers["Location"]


def test_pdf_larger_than_100kb_is_accepted(client):
    _login(client)
    r = _up(client, "AgeProof.PDF", PDF + b"y" * 2_000_000)
    assert r.status_code == 302


def test_wrong_type_gets_a_plain_message_not_an_error_code(client):
    _login(client)
    text = _up(client, "scan.exe", b"MZ" + b"x" * 100).get_data(as_text=True)
    assert "ERR_VAL" not in text
    assert "PDF" in text and "JPG" in text


def test_too_big_file_says_the_limit(client):
    _login(client)
    text = _up(client, "big.pdf", PDF + b"y" * (5 * 1024 * 1024 + 10)).get_data(as_text=True)
    assert "ERR_VAL" not in text and "5 MB" in text


def test_no_file_chosen_says_so(client):
    _login(client)
    r = client.post("/upload", data={}, content_type="multipart/form-data")
    text = r.get_data(as_text=True)
    assert "ERR_VAL" not in text and "choose" in text.lower()


def test_hostile_filename_cannot_escape_upload_dir(A, client):
    _login(client)
    _up(client, "../../../tmp/evil.pdf", PDF)
    with client.session_transaction() as s:
        path = os.path.realpath(s["doc_path"])
    assert path.startswith(os.path.realpath(A.UPLOAD_DIR) + os.sep)


def test_session_survives_a_slow_form_filler(A):
    # elderly applicants take far longer than 5 minutes over a form
    assert A.app.permanent_session_lifetime.total_seconds() >= 1800
