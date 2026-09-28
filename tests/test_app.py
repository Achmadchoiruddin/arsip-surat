import os
import sys
import sqlite3
import tempfile
import zipfile
from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as archive_app
from app import app, classify_document, extract_metadata, get_db, parse_date
from werkzeug.security import check_password_hash, generate_password_hash


@pytest.fixture(autouse=True)
def disable_csrf_for_tests(monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)


def test_extract_metadata_finds_fields():
    text = """
    Nomor Surat: 001/DS/2026
    Tanggal: 25 September 2026
    Perihal: Undangan Rapat Desa
    Pengirim: Kepala Desa
    Tujuan: Kepala Seksi Pemerintahan
    """

    data = extract_metadata(text)

    assert data["nomor_surat"] == "001/DS/2026"
    assert data["tanggal"] == "2026-09-25"
    assert data["perihal"] == "Undangan Rapat Desa"
    assert data["pengirim"] == "Kepala Desa"
    assert data["tujuan"] == "Kepala Seksi Pemerintahan"


def test_parse_date_normalizes_indonesian_weekday_and_month():
    assert parse_date("Sabtu, 3 Oktober 2026") == "2026-10-03"


def test_upload_validation_checks_extension_and_file_signature():
    valid_pdf = FileStorage(stream=BytesIO(b"%PDF-1.7 document"), filename="surat.pdf")
    spoofed_pdf = FileStorage(stream=BytesIO(b"not a pdf"), filename="surat.pdf")
    unsupported = FileStorage(stream=BytesIO(b"%PDF-1.7 document"), filename="surat.exe")

    assert archive_app.is_supported_upload(valid_pdf)
    assert not archive_app.is_supported_upload(spoofed_pdf)
    assert not archive_app.is_supported_upload(unsupported)


def test_upload_route_rejects_spoofed_pdf_without_saving(monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = "petugas"
        session["role"] = "petugas"

    response = client.post(
        "/upload",
        data={"document": (BytesIO(b"not a PDF"), "forged.pdf", "application/pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert response.location.endswith("/upload")
    assert list(tmp_path.iterdir()) == []


def test_csrf_rejects_post_without_token(monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    client = app.test_client()
    response = client.post("/login", data={"username": "admin", "password": "admin123"})

    assert response.status_code == 400


def test_classify_document_matches_keyword():
    text = "Undangan rapat desa untuk seluruh perangkat desa"
    assert classify_document(text) == "Surat Undangan"

    text = "Surat keterangan domisili warga"
    assert classify_document(text) == "Surat Keterangan"

    text = "Nota dinas dan administrasi internal desa"
    assert classify_document(text) == "Surat Administrasi Lainnya"


def test_ocr_language_prefers_indonesian_when_installed(monkeypatch):
    monkeypatch.setattr(archive_app.pytesseract, "get_languages", lambda config="": ["eng", "ind", "osd"])
    assert archive_app.get_ocr_languages() == "ind+eng"

    monkeypatch.setattr(archive_app.pytesseract, "get_languages", lambda config="": ["eng", "osd"])
    assert archive_app.get_ocr_languages() == "eng"


def test_archive_filters_by_category_and_date_range():
    archive_ids = []
    with app.app_context():
        db = get_db()
        for date, subject, category in (
            ("2026-01-15", "FILTER_MATCH_ARCHIVE", "Surat Undangan"),
            ("2026-02-15", "FILTER_DATE_MISS", "Surat Undangan"),
            ("2026-01-20", "FILTER_CATEGORY_MISS", "Surat Keterangan"),
        ):
            cursor = db.execute(
                "INSERT INTO archives (tanggal, perihal, kategori) VALUES (?, ?, ?)",
                (date, subject, category),
            )
            archive_ids.append(cursor.lastrowid)
        db.commit()

    try:
        client = app.test_client()
        with client.session_transaction() as session:
            session["user"] = "petugas"
            session["role"] = "petugas"
        response = client.get(
            "/archives?category=Surat+Undangan&start_date=2026-01-01&end_date=2026-01-31"
        )

        assert response.status_code == 200
        assert b"FILTER_MATCH_ARCHIVE" in response.data
        assert b"FILTER_DATE_MISS" not in response.data
        assert b"FILTER_CATEGORY_MISS" not in response.data
    finally:
        with app.app_context():
            get_db().executemany("DELETE FROM archives WHERE id = ?", [(item_id,) for item_id in archive_ids])
            get_db().commit()


def test_report_export_returns_excel_workbook():
    archive_id = None
    with app.app_context():
        db = get_db()
        cursor = db.execute(
            "INSERT INTO archives (tanggal, perihal, kategori) VALUES (?, ?, ?)",
            ("2026-03-10", "EXPORT_TEST_ARCHIVE", "Surat Undangan"),
        )
        archive_id = cursor.lastrowid
        db.commit()

    try:
        client = app.test_client()
        with client.session_transaction() as session:
            session["user"] = "admin"
            session["role"] = "admin"
        response = client.get(
            "/reports/export?start_date=2026-03-01&end_date=2026-03-31"
        )

        assert response.status_code == 200
        assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert response.data.startswith(b"PK")
        assert "laporan_arsip.xlsx" in response.headers["Content-Disposition"]
    finally:
        if archive_id is not None:
            with app.app_context():
                get_db().execute("DELETE FROM archives WHERE id = ?", (archive_id,))
                get_db().commit()


def test_login_verifies_password_hash_and_sets_role(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (username TEXT, password_hash TEXT, role TEXT, is_active INTEGER DEFAULT 1)")
    db.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?)",
        ("test-admin", generate_password_hash("test-password"), "admin", 1),
    )
    db.commit()
    monkeypatch.setattr(archive_app, "get_db", lambda: db)

    try:
        client = app.test_client()
        response = client.post(
            "/login", data={"username": "test-admin", "password": "test-password"}
        )

        assert response.status_code == 302
        with client.session_transaction() as session:
            assert session["user"] == "test-admin"
            assert session["role"] == "admin"
        stored_hash = db.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("test-admin",)
        ).fetchone()[0]
        assert stored_hash != "test-password"

        changed_password = "changed-password-2026"
        change_response = client.post(
            "/change-password",
            data={
                "current_password": "test-password",
                "new_password": changed_password,
                "confirm_password": changed_password,
            },
        )
        assert change_response.status_code == 302
        updated_hash = db.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("test-admin",)
        ).fetchone()[0]
        assert check_password_hash(updated_hash, changed_password)

        old_password_response = client.post(
            "/login", data={"username": "test-admin", "password": "test-password"}
        )
        assert old_password_response.status_code == 200
        new_password_response = client.post(
            "/login", data={"username": "test-admin", "password": changed_password}
        )
        assert new_password_response.status_code == 302
    finally:
        db.close()


def test_delete_archive_moves_record_to_trash_and_keeps_upload():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=app.config["UPLOAD_FOLDER"], suffix=".png", delete=False) as upload:
        upload_path = upload.name

    archive_id = None
    try:
        with app.app_context():
            db = get_db()
            cursor = db.execute(
                """
                INSERT INTO archives (
                    nomor_surat, tanggal, perihal, pengirim, tujuan, kategori,
                    file_name, file_path, extracted_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("TEST-DELETE", "", "Arsip uji hapus", "", "", "Uji", os.path.basename(upload_path), upload_path, ""),
            )
            archive_id = cursor.lastrowid
            db.commit()

        client = app.test_client()
        with client.session_transaction() as session:
            session["user"] = "petugas"
            session["role"] = "petugas"

        response = client.post(f"/archive/{archive_id}/delete")

        assert response.status_code == 302
        with app.app_context():
            trashed_record = get_db().execute(
                "SELECT deleted_at FROM archives WHERE id = ?", (archive_id,)
            ).fetchone()
            assert trashed_record is not None
            assert trashed_record["deleted_at"] is not None
            activity = get_db().execute(
                "SELECT action, username FROM activity_logs WHERE archive_id = ? ORDER BY id DESC LIMIT 1",
                (archive_id,),
            ).fetchone()
            assert tuple(activity) == ("trash", "petugas")
        assert os.path.exists(upload_path)
    finally:
        if archive_id is not None:
            with app.app_context():
                get_db().execute("DELETE FROM activity_logs WHERE archive_id = ?", (archive_id,))
                get_db().execute("DELETE FROM archives WHERE id = ?", (archive_id,))
                get_db().commit()
        if os.path.exists(upload_path):
            os.remove(upload_path)


def test_archive_can_be_restored_and_permanently_purged():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=app.config["UPLOAD_FOLDER"], suffix=".pdf", delete=False) as upload:
        upload_path = upload.name

    archive_id = None
    try:
        with app.app_context():
            db = get_db()
            cursor = db.execute(
                """
                INSERT INTO archives (
                    nomor_surat, tanggal, perihal, kategori, file_name, file_path, extracted_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("TEST-TRASH", "2026-09-26", "Arsip uji pulihkan", "Uji", os.path.basename(upload_path), upload_path, ""),
            )
            archive_id = cursor.lastrowid
            db.commit()

        staff_client = app.test_client()
        with staff_client.session_transaction() as session:
            session["user"] = "petugas"
            session["role"] = "petugas"
        assert staff_client.post(f"/archive/{archive_id}/delete").status_code == 302
        assert b"Arsip uji pulihkan" not in staff_client.get("/archives").data
        assert os.path.exists(upload_path)
        assert staff_client.get("/archives/trash").status_code == 302

        admin_client = app.test_client()
        with admin_client.session_transaction() as session:
            session["user"] = "admin"
            session["role"] = "admin"
        trash_response = admin_client.get("/archives/trash")
        assert trash_response.status_code == 200
        assert b"TEST-TRASH" in trash_response.data

        restore_response = admin_client.post(f"/archive/{archive_id}/restore")
        assert restore_response.status_code == 302
        with app.app_context():
            restored = get_db().execute(
                "SELECT deleted_at FROM archives WHERE id = ?", (archive_id,)
            ).fetchone()
            assert restored["deleted_at"] is None
        assert os.path.exists(upload_path)

        assert staff_client.post(f"/archive/{archive_id}/delete").status_code == 302
        purge_response = admin_client.post(f"/archive/{archive_id}/purge")
        assert purge_response.status_code == 302
        with app.app_context():
            assert get_db().execute(
                "SELECT id FROM archives WHERE id = ?", (archive_id,)
            ).fetchone() is None
        assert not os.path.exists(upload_path)
    finally:
        if archive_id is not None:
            with app.app_context():
                get_db().execute("DELETE FROM activity_logs WHERE archive_id = ?", (archive_id,))
                get_db().execute("DELETE FROM archives WHERE id = ?", (archive_id,))
                get_db().commit()
        if os.path.exists(upload_path):
            os.remove(upload_path)


def test_reset_archives_moves_all_active_records_to_trash(monkeypatch):
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=app.config["UPLOAD_FOLDER"], suffix=".png", delete=False) as upload:
        upload_path = upload.name

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE archives (id INTEGER PRIMARY KEY, file_path TEXT, deleted_at TEXT)")
    db.execute("CREATE TABLE activity_logs (id INTEGER PRIMARY KEY, username TEXT, action TEXT, details TEXT, archive_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    db.execute("CREATE TABLE users (username TEXT, role TEXT, is_active INTEGER)")
    db.executemany("INSERT INTO users VALUES (?, ?, ?)", [("admin", "admin", 1), ("petugas", "petugas", 1)])
    db.execute("INSERT INTO archives (file_path) VALUES (?)", (upload_path,))
    db.commit()
    monkeypatch.setattr(archive_app, "get_db", lambda: db)

    try:
        client = app.test_client()
        with client.session_transaction() as session:
            session["user"] = "petugas"
        denied_response = client.post("/archives/reset")
        assert denied_response.status_code == 302
        assert db.execute("SELECT COUNT(*) FROM archives").fetchone()[0] == 1
        assert os.path.exists(upload_path)

        with client.session_transaction() as session:
            session["user"] = "admin"
            session["role"] = "admin"
        reset_response = client.post("/archives/reset")

        assert reset_response.status_code == 302
        assert db.execute("SELECT COUNT(*) FROM archives WHERE deleted_at IS NULL").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM archives WHERE deleted_at IS NOT NULL").fetchone()[0] == 1
        assert os.path.exists(upload_path)
        assert db.execute("SELECT action FROM activity_logs").fetchone()[0] == "reset"
    finally:
        db.close()
        if os.path.exists(upload_path):
            os.remove(upload_path)


def test_admin_can_view_activity_and_download_backup(monkeypatch, tmp_path):
    database_path = tmp_path / "archive.db"
    upload_folder = tmp_path / "uploads"
    upload_folder.mkdir()
    document_path = upload_folder / "backup_fixture.pdf"
    document_path.write_bytes(b"test archive document")

    db = sqlite3.connect(database_path)
    db.execute(
        "CREATE TABLE activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, details TEXT, archive_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    db.execute(
        "CREATE TABLE archives (id INTEGER PRIMARY KEY, nomor_surat TEXT, tanggal TEXT, perihal TEXT, pengirim TEXT, tujuan TEXT, kategori TEXT, file_name TEXT, file_path TEXT, extracted_text TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT)"
    )
    db.execute("CREATE TABLE users (username TEXT, role TEXT, is_active INTEGER)")
    db.executemany("INSERT INTO users VALUES (?, ?, ?)", [("admin", "admin", 1), ("petugas", "petugas", 1)])
    db.execute(
        "INSERT INTO archives (file_path, file_name, nomor_surat) VALUES (?, ?, ?)",
        (str(document_path), document_path.name, "BACKUP-TEST"),
    )
    db.commit()
    db.close()
    monkeypatch.setitem(app.config, "DATABASE", str(database_path))
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(upload_folder))

    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = "petugas"
        session["role"] = "petugas"
    assert client.get("/admin/activity").status_code == 302
    assert client.get("/admin/backup").status_code == 302

    with client.session_transaction() as session:
        session["user"] = "admin"
        session["role"] = "admin"
    activity_response = client.get("/admin/activity")
    backup_response = client.get("/admin/backup")

    assert activity_response.status_code == 200
    assert b"backup" in activity_response.data
    assert backup_response.status_code == 200
    assert backup_response.mimetype == "application/zip"
    with zipfile.ZipFile(BytesIO(backup_response.data)) as backup:
        assert "archive.db" in backup.namelist()
        assert "uploads/backup_fixture.pdf" in backup.namelist()


def test_admin_can_restore_database_from_backup(monkeypatch, tmp_path):
    database_path = tmp_path / "archive.db"
    target_db_path = tmp_path / "restored_target.db"
    upload_folder = tmp_path / "uploads"
    upload_folder.mkdir()

    source_db = sqlite3.connect(tmp_path / "backup_source.db")
    source_db.execute(
        "CREATE TABLE archives (id INTEGER PRIMARY KEY, nomor_surat TEXT, file_name TEXT, file_path TEXT, deleted_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    source_db.execute(
        "CREATE TABLE activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, details TEXT, archive_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    source_db.execute(
        "CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT, is_active INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    source_db.execute(
        "INSERT INTO archives (nomor_surat, file_name, file_path, deleted_at) VALUES (?, ?, ?, ?)",
        ("RESTORE-777", "restored.pdf", str(upload_folder / "restored.pdf"), None),
    )
    source_db.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
        ("admin", generate_password_hash("admin-pass"), "admin", 1),
    )
    source_db.commit()
    source_db.close()

    restored_document = upload_folder / "restored.pdf"
    restored_document.write_bytes(b"restored content")

    backup_zip = tmp_path / "backup.zip"
    with zipfile.ZipFile(backup_zip, "w", zipfile.ZIP_DEFLATED) as archive_zip:
        archive_zip.write(tmp_path / "backup_source.db", "archive.db")
        archive_zip.write(restored_document, "uploads/restored.pdf")

    target_db = sqlite3.connect(target_db_path)
    target_db.execute(
        "CREATE TABLE archives (id INTEGER PRIMARY KEY, nomor_surat TEXT, file_name TEXT, file_path TEXT, deleted_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    target_db.execute(
        "CREATE TABLE activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, details TEXT, archive_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    target_db.execute(
        "CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT, is_active INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    target_db.execute(
        "INSERT INTO archives (nomor_surat, file_name, file_path, deleted_at) VALUES (?, ?, ?, ?)",
        ("CURRENT", "current.pdf", str(upload_folder / "current.pdf"), None),
    )
    target_db.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, ?)",
        ("admin", generate_password_hash("admin-pass"), "admin", 1),
    )
    target_db.commit()
    target_db.close()

    monkeypatch.setitem(app.config, "DATABASE", str(target_db_path))
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(upload_folder))

    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = "admin"
        session["role"] = "admin"

    response = client.post(
        "/admin/backup/restore",
        data={"backup_file": (BytesIO(backup_zip.read_bytes()), "backup.zip")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    with sqlite3.connect(target_db_path) as restored_conn:
        rows = restored_conn.execute("SELECT nomor_surat FROM archives ORDER BY id").fetchall()
        assert rows[0][0] == "RESTORE-777"
    assert (upload_folder / "restored.pdf").exists()


def test_admin_manages_users_and_disabled_user_session_is_invalidated(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT, is_active INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    db.execute(
        "CREATE TABLE activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT, details TEXT, archive_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    db.execute(
        "CREATE TABLE archives (id INTEGER PRIMARY KEY, nomor_surat TEXT, tanggal TEXT, perihal TEXT, pengirim TEXT, tujuan TEXT, kategori TEXT, file_name TEXT, file_path TEXT, extracted_text TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT)"
    )
    db.execute(
        "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
        ("admin", generate_password_hash("admin-password"), "admin"),
    )
    db.commit()
    monkeypatch.setattr(archive_app, "get_db", lambda: db)

    try:
        admin_client = app.test_client()
        with admin_client.session_transaction() as session:
            session["user"] = "admin"
            session["role"] = "admin"
        assert admin_client.get("/admin/users").status_code == 200

        create_response = admin_client.post(
            "/admin/users",
            data={"username": "operator", "password": "operator-password-2026", "role": "petugas"},
        )
        assert create_response.status_code == 302
        created_user = db.execute(
            "SELECT role, is_active, password_hash FROM users WHERE username = 'operator'"
        ).fetchone()
        assert created_user["role"] == "petugas"
        assert created_user["is_active"] == 1
        assert check_password_hash(created_user["password_hash"], "operator-password-2026")

        staff_client = app.test_client()
        with staff_client.session_transaction() as session:
            session["user"] = "operator"
            session["role"] = "petugas"
        assert staff_client.get("/admin/users").status_code == 302
        assert staff_client.get("/dashboard").status_code == 200

        reset_response = admin_client.post(
            "/admin/users/operator/password",
            data={"password": "reset-password-2026"},
        )
        assert reset_response.status_code == 302
        assert check_password_hash(
            db.execute("SELECT password_hash FROM users WHERE username = 'operator'").fetchone()[0],
            "reset-password-2026",
        )

        self_update = admin_client.post(
            "/admin/users/admin/update", data={"role": "petugas", "is_active": "0"}
        )
        assert self_update.status_code == 302
        assert db.execute(
            "SELECT role, is_active FROM users WHERE username = 'admin'"
        ).fetchone()[:] == ("admin", 1)

        disable_response = admin_client.post(
            "/admin/users/operator/update", data={"role": "petugas", "is_active": "0"}
        )
        assert disable_response.status_code == 302
        assert staff_client.get("/dashboard").status_code == 302
        with staff_client.session_transaction() as session:
            assert "user" not in session

        actions = {
            row[0] for row in db.execute("SELECT action FROM activity_logs").fetchall()
        }
        assert {"user_create", "user_update", "user_password_reset"}.issubset(actions)
    finally:
        db.close()
