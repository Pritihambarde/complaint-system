import os, tempfile
_db = tempfile.mktemp(suffix=".db")
os.environ.update(DATABASE_URL=f"sqlite:///{_db}", ESCALATION_INTERVAL="0", SLA_SCALE="1", DEBUG_OTP="1", ACADEMIC_YEAR_START="2026", IMAGE_RELEVANCE="off")

from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import models

import pytest
from app import services

c = TestClient(app)

@pytest.fixture(autouse=True)
def _reset_rate_limit():
    services._hits.clear()
D = "@mgmcen.ac.in"

def photo_bytes(kind="photo", fmt="PNG", size=(320, 240)):
    """A generated test picture: 'photo' has real detail, 'blank' is one flat colour."""
    import io, random
    from PIL import Image
    im = Image.new("RGB", size, (255, 255, 255))
    if kind == "photo":
        rnd = random.Random(1)
        im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size[0] * size[1])])
    b = io.BytesIO(); im.save(b, fmt); return b.getvalue()

def login(email, pw):
    r = c.post("/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}

def submit(h, desc, title="Problem report", category="Other", **kw):
    return c.post("/complaints", data={"title": title, "description": desc, "category": category, **kw}, headers=h)

def reg(**over):
    body = {"name": "Rahul", "email": "s25_patil_rahul" + D, "password": "Student@123", "section": "A"}
    body.update(over)
    return c.post("/auth/register", json=body)

def test_register_validation():
    assert c.post("/auth/register", json={"name": "A", "email": "x@gmail.com", "password": "weak", "section": "A"}).status_code == 422
    assert reg(password="weakpass").status_code == 422
    assert reg(email="rahul" + D).status_code == 422              # not the s23_surname_firstname pattern
    assert reg(email="s21_patil_rahul" + D).status_code == 422    # s21 has already graduated - no active class
    assert reg(email="s26_patil_rahul" + D).status_code == 422    # s26 is this year's freshers (FY) - not in this system yet
    assert reg(email="s23_gaikwad_om" + D, section="C").status_code == 422   # s23 = BTech, which only has A/B, not C
    assert reg().status_code == 201     # s25 = SY, section A
    assert reg().status_code == 409

def test_full_flow_and_rbac():
    s = login("s25_patil_rahul" + D, "Student@123")
    r = submit(s, "Senior students are threatening us in the hostel at night and forcing us to do their work", category="Ragging & Harassment").json()
    assert r["category"] == "Ragging & Harassment" and r["priority"] == "Critical" and r["assigned_to"] == "HOD"
    assert r["code"].startswith("CMP-") and r["keywords"]
    o = login("a_m_rajurkar" + D, "Mgm@123")
    assert len(c.get("/complaints/assigned", headers=o).json()) == 1
    assert c.patch(f"/complaints/{r['id']}/status", json={"status": "In Progress", "remarks": "Meeting today"}, headers=o).json()["status"] == "In Progress"
    lib = login("sangnor_suresh_nilkanthrao" + D, "Mgm@123")
    assert c.patch(f"/complaints/{r['id']}/status", json={"status": "Resolved", "remarks": "Done"}, headers=lib).status_code == 403
    assert c.get("/complaints/assigned", headers=s).status_code == 403
    assert c.get("/analytics", headers=s).status_code == 403
    assert c.get("/complaints/my").status_code == 401
    n = c.get("/notifications", headers=s).json()
    assert any("In Progress" in x["message"] for x in n)

def test_validation_and_spam():
    s = login("s25_patil_rahul" + D, "Student@123")
    assert submit(s, "too short").status_code == 422
    assert submit(s, "asdfgh qwrtyp zxcvbn mnbvcx lkjhgf poiuyt").status_code == 422      # gibberish
    assert submit(s, "This teacher is a stupid idiot and nobody likes the class").status_code == 422
    bad = c.post("/complaints", data={"title": "Hello there", "description": "x" * 30}, files={"file": ("a.exe", b"MZ")}, headers=s)
    assert bad.status_code == 422
    fake = c.post("/complaints", data={"title": "Hello there", "description": "The CS lab has very few systems for our course"}, files={"file": ("a.pdf", b"not a pdf")}, headers=s)
    assert fake.status_code == 422

def test_anonymous_and_attachment():
    s = login("s25_patil_rahul" + D, "Student@123")
    r = c.post("/complaints", data={"title": "Lab computers problem", "description": "Computers in the CS lab are not working and the lab systems keep hanging", "anonymous": "true", "category": "Lab & Equipment", "lab_number": "1"},
               files={"file": ("p.png", photo_bytes())}, headers=s)
    assert r.status_code == 201, r.text
    o = login("sangnor_suresh_nilkanthrao" + D, "Mgm@123")
    seen = c.get("/complaints/assigned", headers=o).json()[0]
    assert seen["student_name"] == "Anonymous"
    assert c.get(f"/complaints/{seen['id']}/attachment", headers=o).status_code == 200
    assert c.get(f"/complaints/{seen['id']}/attachment", headers=login("v_s_jadhav" + D, "Mgm@123")).status_code == 404

def test_duplicates_feedback_reopen():
    s2 = None
    c.post("/auth/register", json={"name": "Sneha", "email": "s24_shinde_sneha" + D, "password": "Student@123", "section": "A"})
    s1, s2 = login("s25_patil_rahul" + D, "Student@123"), login("s24_shinde_sneha" + D, "Student@123")
    a = submit(s1, "Faculty is not completing the Data Structures syllabus and lectures are not conducted", category="Teaching & Syllabus").json()
    b = submit(s2, "The Data Structures faculty is not completing the syllabus and no lectures are conducted", category="Teaching & Syllabus").json()
    assert b["duplicate_of"] == a["id"]
    w = login("k_p_people" + D, "Mgm@123")   # Rahul is SY-A, so it's routed to the SY-A coordinator
    c.patch(f"/complaints/{a['id']}/status", json={"status": "Resolved", "remarks": "Done"}, headers=w)
    assert c.post(f"/complaints/{a['id']}/feedback", json={"rating": 9}, headers=s1).status_code == 422
    assert c.post(f"/complaints/{a['id']}/feedback", json={"rating": 4, "comment": "ok"}, headers=s1).json()["rating"] == 4
    assert c.post(f"/complaints/{a['id']}/reopen", headers=s1).json()["status"] == "Reopened"
    assert c.post(f"/complaints/{b['id']}/feedback", json={"rating": 3}, headers=s2).status_code == 400   # not resolved

def test_escalation_chain():
    s = login("s25_patil_rahul" + D, "Student@123")
    r = submit(s, "Semester result is not declared and my exam marks are missing from the portal", category="Exams & Marks").json()
    adm = login("admin" + D, "Admin@123")
    for level, who in [(1, "HOD"), (2, "Principal")]:
        with SessionLocal() as db:
            db.get(models.Complaint, r["id"]).sla_due = datetime.utcnow() - timedelta(hours=1); db.commit()
        assert c.post("/admin/run-escalation", headers=adm).json()["escalated"] == 1
        d = [x for x in c.get("/complaints/my", headers=s).json() if x["id"] == r["id"]][0]
        assert d["status"] == "Escalated" and d["escalation_level"] == level
    with SessionLocal() as db:
        db.get(models.Complaint, r["id"]).sla_due = datetime.utcnow() - timedelta(hours=1); db.commit()
    assert c.post("/admin/run-escalation", headers=adm).json()["escalated"] == 0        # already at top
    p = login("principal" + D, "Officer@123")
    assert any(x["id"] == r["id"] for x in c.get("/complaints/assigned", headers=p).json())
    assert c.patch(f"/complaints/{r['id']}/status", json={"status": "Resolved", "remarks": "Marks corrected"}, headers=p).status_code == 200
    stats = c.get("/analytics", headers=adm).json()
    assert stats["total"] >= 4 and stats["escalated"] >= 1 and stats["by_category"]

def test_admin_and_lockout_and_reset():
    adm = login("admin" + D, "Admin@123")
    assert c.get("/admin/audit", headers=adm).json()
    assert c.post("/admin/users", json={"name": "New HOD", "email": "hod2" + D, "password": "Strong@123", "role": "authority", "level": 1}, headers=adm).status_code == 201
    for _ in range(5):
        c.post("/auth/login", data={"username": "s24_shinde_sneha" + D, "password": "wrong"})
    assert c.post("/auth/login", data={"username": "s24_shinde_sneha" + D, "password": "Student@123"}).status_code == 423
    otp = c.post("/auth/forgot", json={"email": "s24_shinde_sneha" + D}).json()["debug_otp"]
    assert c.post("/auth/reset", json={"email": "s24_shinde_sneha" + D, "otp": "000000", "new_password": "Newpass@123"}).status_code == 400
    assert c.post("/auth/reset", json={"email": "s24_shinde_sneha" + D, "otp": otp, "new_password": "Newpass@123"}).status_code == 200
    login("s24_shinde_sneha" + D, "Newpass@123")

def test_frontend_served():
    assert c.get("/").status_code == 200 and c.get("/health").json()["status"] == "ok"


# ---------- deadlines, HOD escalation, email alerts ----------
def test_deadline_days_per_priority():
    assert services.SLA_HOURS["Low"] == 72 and services.SLA_HOURS["Medium"] == 48
    assert services.SLA_HOURS["High"] == 24 and services.SLA_HOURS["Critical"] == 24

def test_timetable_complaint_emails_real_address_and_escalates_to_hod(monkeypatch):
    sent = []
    monkeypatch.setattr(services, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    s = login("s25_patil_rahul" + D, "Student@123")
    r = c.post("/complaints", data={"title": "Timetable clash", "category": "Timetable & Attendance",
               "description": "Our timetable has two subjects at the same time on Tuesday and nobody can attend both"}, headers=s)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    # mail goes to the REAL address in "Name <address>" form, never to the placeholder login address
    targets = [t for t, _, _ in sent]
    assert "Ms Dumne Rakhi Shivajirao <dumne_rs@mgmcen.ac.in>" in targets
    assert not any("r_s_dumne" in t for t in targets)
    login("dumne_rs" + D, "Mgm@123")                    # her login email is now the real address
    assert any("before" in b for _, _, b in sent)       # mail states the deadline

    # deadline missed -> escalated to the HOD, who is told
    db = SessionLocal()
    cm = db.get(models.Complaint, cid)
    cm.sla_due = datetime.utcnow() - timedelta(minutes=1); db.commit()
    assert services.run_escalation(db) >= 1
    db.refresh(cm)
    assert cm.escalation_level == 1 and cm.status == "Escalated"
    db.close()
    hod = login("a_m_rajurkar" + D, "Mgm@123")
    assert any(x["id"] == cid for x in c.get("/complaints/assigned", headers=hod).json())

def test_admin_can_set_alert_email():
    a = login("admin" + D, "Admin@123")
    uid = next(u["id"] for u in c.get("/admin/users", headers=a).json() if u["email"] == "a_m_rajurkar" + D)
    assert c.patch(f"/admin/users/{uid}/notify-email", json={"notify_email": "bad"}, headers=a).status_code == 422
    assert c.patch(f"/admin/users/{uid}/notify-email", json={"notify_email": "hod.test@mgmcen.ac.in", "notify_name": "Dr. A. M. Rajurkar"}, headers=a).status_code == 200


def test_lab_complaint_needs_lab_number_and_routes_by_it():
    s = login("s25_patil_rahul" + D, "Student@123")
    base = {"title": "Lab systems problem", "category": "Lab & Equipment",
            "description": "Computers in the lab are not starting and the systems keep hanging during practicals"}
    r = c.post("/complaints", data=base, headers=s)
    assert r.status_code == 422 and "lab number" in r.json()["detail"].lower()
    assert c.post("/complaints", data={**base, "lab_number": "11"}, headers=s).status_code == 422
    r = c.post("/complaints", data={**base, "lab_number": "5"}, headers=s)
    assert r.status_code == 201, r.text
    assert r.json()["lab_number"] == 5 and r.json()["assigned_to"] == "Prashant Kishanrao Deshmukh"   # labs 4,5,6
    # non-lab complaints don't need (and ignore) a lab number
    r = c.post("/complaints", data={"title": "Timetable clash again", "category": "Timetable & Attendance", "lab_number": "3",
               "description": "Our timetable has two subjects at the same time on Wednesday and nobody can attend both"}, headers=s)
    assert r.status_code == 201 and r.json()["lab_number"] is None


def test_wrong_problem_type_is_blocked():
    s = login("s25_patil_rahul" + D, "Student@123")
    lab_text = "Computers in the lab are not working, system does not start and software is missing"
    # lab issue filed under Classroom Infrastructure -> rejected, tells the student the right type
    r = submit(s, lab_text, category="Classroom Infrastructure")
    assert r.status_code == 422 and "Lab & Equipment" in r.json()["detail"]
    assert submit(s, lab_text, category="Teaching & Syllabus").status_code == 422
    # live-check endpoint used by the form
    chk = c.post("/complaints/check-category", data={"title": "Lab problem", "description": lab_text}, headers=s).json()
    assert chk["suggested"] == "Lab & Equipment"
    # same text under the right type goes through
    assert submit(s, lab_text, category="Lab & Equipment", lab_number="2").status_code == 201
    # vague text never blocks
    assert c.post("/complaints/check-category", data={"title": "x", "description": "short"}, headers=s).json()["suggested"] is None


def test_blank_and_bad_pictures_rejected():
    s = login("s25_patil_rahul" + D, "Student@123")
    data = {"title": "Lab computers problem", "description": "Computers in the CS lab are not working and the lab systems keep hanging",
            "category": "Lab & Equipment", "lab_number": "1"}
    for name, blob in [("blank.png", photo_bytes("blank")), ("tiny.png", photo_bytes("photo", size=(40, 40))),
                       ("empty.png", b""), ("fake.png", b"\x89PNG\r\n" + b"0" * 50)]:
        r = c.post("/complaints", data=data, files={"file": (name, blob)}, headers=s)
        assert r.status_code == 422, (name, r.text)
        assert "Attachment" in r.json()["detail"] or "File" in r.json()["detail"], (name, r.text)

def test_picture_must_match_problem_type(monkeypatch):
    from app import image_check
    monkeypatch.setenv("IMAGE_RELEVANCE", "clip")
    s = login("s25_patil_rahul" + D, "Student@123")
    data = {"title": "Lab computers problem", "description": "Computers in the CS lab are not working and the lab systems keep hanging",
            "category": "Lab & Equipment", "lab_number": "1"}
    scores = {"lab": 0.02, "classroom": 0.03, "documents": 0.05, "unrelated": 0.90}      # e.g. a selfie
    monkeypatch.setattr(image_check, "group_scores", lambda img: scores)
    r = c.post("/complaints", data=data, files={"file": ("a.png", photo_bytes())}, headers=s)
    assert r.status_code == 422 and "lab or computer" in r.json()["detail"], r.text
    scores.update(lab=0.80, unrelated=0.12)                                                  # e.g. a keyboard / mouse
    r = c.post("/complaints", data=data, files={"file": ("a.png", photo_bytes())}, headers=s)
    assert r.status_code == 201, r.text


def test_admin_manages_departmental_accounts():
    a = login("admin" + D, "Admin@123")
    users = c.get("/admin/users", headers=a).json()
    by = {u["email"]: u for u in users}
    assert by["admin" + D]["is_active"] is True and "open_complaints" in by["admin" + D]
    # a non-admin cannot use any of it
    s = login("s25_patil_rahul" + D, "Student@123")
    exam = by["v_s_jadhav" + D]["id"]
    assert c.post(f"/admin/users/{exam}/reset-password", json={"new_password": "Newpass@123"}, headers=s).status_code == 403
    # reset password: weak rejected, strong works, old password stops working
    assert c.post(f"/admin/users/{exam}/reset-password", json={"new_password": "weak"}, headers=a).status_code == 422
    assert c.post(f"/admin/users/{exam}/reset-password", json={"new_password": "Newpass@123"}, headers=a).status_code == 200
    assert c.post("/auth/login", data={"username": "v_s_jadhav" + D, "password": "Mgm@123"}).status_code == 401
    login("v_s_jadhav" + D, "Newpass@123")
    # lock then unlock
    for _ in range(5):
        c.post("/auth/login", data={"username": "v_s_jadhav" + D, "password": "bad"})
    assert next(u for u in c.get("/admin/users", headers=a).json() if u["id"] == exam)["locked"] is True
    assert c.post(f"/admin/users/{exam}/unlock", headers=a).status_code == 200
    login("v_s_jadhav" + D, "Newpass@123")
    # disable blocks login (and an already issued token); enable restores it
    tok = login("v_s_jadhav" + D, "Newpass@123")
    assert c.patch(f"/admin/users/{exam}/active", json={"active": False}, headers=a).status_code == 200
    assert c.post("/auth/login", data={"username": "v_s_jadhav" + D, "password": "Newpass@123"}).status_code == 403
    assert c.get("/auth/me", headers=tok).status_code == 401
    assert c.patch(f"/admin/users/{exam}/active", json={"active": True}, headers=a).status_code == 200
    login("v_s_jadhav" + D, "Newpass@123")
    # edit: change department
    labs = next(d["id"] for d in c.get("/admin/departments", headers=a).json() if d["name"] == "Timetable Coordinator")
    assert c.patch(f"/admin/users/{exam}", json={"department_id": labs}, headers=a).status_code == 200
    assert next(u for u in c.get("/admin/users", headers=a).json() if u["id"] == exam)["department"] == "Timetable Coordinator"


def test_admin_view_as_and_guards_and_delete():
    a = login("admin" + D, "Admin@123")
    users = {u["email"]: u for u in c.get("/admin/users", headers=a).json()}
    me_id, hod = users["admin" + D]["id"], users["a_m_rajurkar" + D]["id"]
    # view as HOD: token works as the HOD, and is not an admin session
    r = c.post(f"/admin/users/{hod}/impersonate", headers=a)
    assert r.status_code == 200 and r.json()["role"] == "authority"
    vh = {"Authorization": "Bearer " + r.json()["access_token"]}
    assert c.get("/auth/me", headers=vh).json()["email"] == "a_m_rajurkar" + D
    assert c.get("/admin/users", headers=vh).status_code == 403
    assert c.post(f"/admin/users/{me_id}/impersonate", headers=a).status_code == 422      # not for admins
    # guards: cannot disable/delete yourself or the last admin
    assert c.patch(f"/admin/users/{me_id}/active", json={"active": False}, headers=a).status_code == 409
    assert c.delete(f"/admin/users/{me_id}", headers=a).status_code == 409
    # students are not managed here
    sid = next(u["id"] for u in c.get("/admin/users", headers=a).json() if u["role"] == "student")
    assert c.delete(f"/admin/users/{sid}", headers=a).status_code == 404
    # delete a departmental account with no complaints
    assert c.post("/admin/users", json={"name": "Temp Officer", "email": "temp_officer" + D, "password": "Strong@123", "role": "officer",
                                        "department_id": next(d["id"] for d in c.get("/admin/departments", headers=a).json() if d["name"] == "Exam Coordinator")}, headers=a).status_code == 201
    tid = next(u["id"] for u in c.get("/admin/users", headers=a).json() if u["email"] == "temp_officer" + D)
    assert c.delete(f"/admin/users/{tid}", headers=a).status_code == 200
    assert c.post("/auth/login", data={"username": "temp_officer" + D, "password": "Strong@123"}).status_code == 401


def test_delete_officer_with_open_complaints_needs_reassign():
    a = login("admin" + D, "Admin@123")
    s = login("s25_patil_rahul" + D, "Student@123")
    cid = submit(s, "The final exam marks were entered wrongly for my paper and need a recheck please", category="Exams & Marks").json()
    users = c.get("/admin/users", headers=a).json()
    owner = next(u for u in users if u["open_complaints"] and u["role"] == "officer")
    other = next(u for u in users if u["role"] == "officer" and u["id"] != owner["id"])
    assert c.delete(f"/admin/users/{owner['id']}", headers=a).status_code == 409
    r = c.request("DELETE", f"/admin/users/{owner['id']}", json={"reassign_to": other["id"]}, headers=a)
    assert r.status_code == 200 and r.json()["complaints_moved"] >= 1


def test_portal_separation_and_mandatory_remark():
    a = c.post("/auth/login", data={"username": "admin@mgmcen.ac.in", "password": "Admin@123", "portal": "student"})
    assert a.status_code == 403
    assert c.post("/auth/login", data={"username": "admin@mgmcen.ac.in", "password": "Admin@123", "portal": "staff"}).status_code == 200
    assert c.post("/auth/login", data={"username": "s25_demo_student@mgmcen.ac.in", "password": "Student@123", "portal": "staff"}).status_code == 403
    assert c.post("/auth/login", data={"username": "s25_demo_student@mgmcen.ac.in", "password": "Student@123", "portal": "student"}).status_code == 200
    from app import schemas
    for bad in ({"status": "Resolved"}, {"status": "Resolved", "remarks": "   "}):
        try:
            schemas.StatusUpdateIn(**bad); assert False
        except ValueError:
            pass


def test_audit_log_visible_without_mongodb():
    a = login("admin@mgmcen.ac.in", "Admin@123")
    login("s25_demo_student@mgmcen.ac.in", "Student@123")
    rows = c.get("/admin/audit", headers=a).json()
    assert any(r["action"] == "LOGIN" and "Demo Student" in r["user"] for r in rows)
    assert all({"user", "action", "detail", "at"} <= set(r) for r in rows)
    s = login("s25_demo_student@mgmcen.ac.in", "Student@123")
    assert c.get("/admin/audit", headers=s).status_code == 403
