"""Adds 9 sample complaints dated 14, 15 and 16 Nov 2026 so you can try the Admin date filter + summary.

  python add_demo_data.py            add the demo complaints (safe to run once)
  python add_demo_data.py --remove   delete them again (all titles start with "[DEMO]")

Then log in as Admin (Staff Login), set From date = 14-11-2026 and To date = 16-11-2026.
"""
import sys
from datetime import datetime, timedelta
from app.database import SessionLocal, Base, engine
from app import models

Base.metadata.create_all(engine)
db = SessionLocal()

if "--remove" in sys.argv:
    ids = [c.id for c in db.query(models.Complaint).filter(models.Complaint.title.like("[DEMO]%"))]
    db.query(models.StatusHistory).filter(models.StatusHistory.complaint_id.in_(ids)).delete(synchronize_session=False)
    db.query(models.Escalation).filter(models.Escalation.complaint_id.in_(ids)).delete(synchronize_session=False)
    db.query(models.Complaint).filter(models.Complaint.id.in_(ids)).delete(synchronize_session=False)
    db.commit(); print(f"Removed {len(ids)} demo complaints"); sys.exit()

if db.query(models.Complaint).filter(models.Complaint.title.like("[DEMO]%")).count():
    sys.exit("Demo complaints already exist. Run with --remove first if you want to add them again.")

student = db.query(models.User).filter_by(role="student").order_by(models.User.id).first()
office = {"Exams & Marks": "Exam Coordinator", "Timetable & Attendance": "Timetable Coordinator",
          "Projects & Placements": "Project Placement Cell", "Other": "Admin Desk"}
hod = db.query(models.User).filter_by(role="authority", level=1).first()
principal = db.query(models.User).filter_by(role="authority", level=2).first()
now = datetime.utcnow()

def officer(category):
    d = db.query(models.Department).filter_by(name=office[category]).first()
    return db.query(models.User).filter_by(role="officer", department_id=d.id).first()

# (day of Nov 2026, hour UTC, category, status, escalation level, overdue?)
ROWS = [
    (14, 6, "Exams & Marks",          "Resolved",    0, False),
    (14, 7, "Timetable & Attendance", "In Progress", 0, False),
    (14, 8, "Other",                  "Assigned",    0, False),
    (15, 6, "Projects & Placements",  "Closed",      0, False),
    (15, 7, "Exams & Marks",          "Escalated",   1, False),
    (15, 8, "Timetable & Attendance", "In Progress", 0, False),
    (15, 9, "Other",                  "Resolved",    0, False),
    (16, 6, "Projects & Placements",  "Assigned",    0, False),
    (16, 7, "Exams & Marks",          "Escalated",   2, True),
]
for n, (day, hr, cat, status, lvl, overdue) in enumerate(ROWS, 1):
    created = datetime(2026, 11, day, hr, 0)
    done = status in ("Resolved", "Closed")
    boss = principal if lvl == 2 else hod
    c = models.Complaint(title=f"[DEMO] {cat} problem {n}", description=f"Sample complaint {n} for testing the admin summary ({cat}).",
        category=cat, priority="Medium", confidence=0.9, sentiment="Neutral", keywords="", status=status, escalation_level=lvl,
        sla_due=(now - timedelta(days=1)) if overdue else (now + timedelta(days=1)), student_id=student.id, officer_id=officer(cat).id,
        created_at=created, resolved_at=created + timedelta(hours=5) if done else None)
    db.add(c); db.flush()
    c.code = f"CMP-2026-{c.id:05d}"
    db.add(models.StatusHistory(complaint_id=c.id, status="Submitted", remarks="Demo complaint", changed_at=created))
    if status != "Assigned":
        db.add(models.StatusHistory(complaint_id=c.id, status=status, remarks="Escalated: deadline missed" if lvl else "Demo update",
                                    changed_at=created + timedelta(hours=2)))
    if lvl:
        db.add(models.Escalation(complaint_id=c.id, to_level=lvl, to_user_id=boss.id, reason="Deadline missed", at=created + timedelta(hours=2)))
db.commit(); print("Added 9 demo complaints (14-16 Nov 2026).")
