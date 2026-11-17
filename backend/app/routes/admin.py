from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..security import require_role, current_user, hash_password, create_token
from ..services import run_escalation, audit, notify

admin = APIRouter(prefix="/admin", tags=["Admin"])
analytics_router = APIRouter(prefix="/analytics", tags=["Analytics"])
notif_router = APIRouter(prefix="/notifications", tags=["Notifications"])
ADMIN = require_role("admin")

@admin.get("/users")
def users(_=Depends(ADMIN), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    open_count = {}
    for c in db.query(models.Complaint).filter(models.Complaint.officer_id.isnot(None),
                                               models.Complaint.status.notin_(["Resolved", "Closed"])):
        open_count[c.officer_id] = open_count.get(c.officer_id, 0) + 1
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "level": u.level,
             "department": u.department.name if u.department else None, "department_id": u.department_id,
             "year": u.year, "section": u.section, "lab_numbers": u.lab_numbers,
             "notify_email": u.notify_email, "notify_name": u.notify_name,
             "is_active": u.is_active is not False,
             "locked": bool(u.locked_until and u.locked_until > now),
             "open_complaints": open_count.get(u.id, 0)}
            for u in db.query(models.User).order_by(models.User.id)]

def _staff(db, uid):
    """Any non-student account (departmental, HOD/Principal, admin) - students are not managed here."""
    u = db.get(models.User, uid)
    if not u or u.role == "student":
        raise HTTPException(404, "Staff user not found")
    return u

def _active_admins(db):
    return db.query(models.User).filter_by(role="admin").filter(models.User.is_active.isnot(False)).count()

def _class_incharge_dept(db):
    return db.query(models.Department).filter_by(name="Class Incharge").first()

def _class_incharge(db, year, section):
    """The one Class Incharge officer for (year, section), or None."""
    dept = _class_incharge_dept(db)
    if not dept:
        return None
    return db.query(models.User).filter_by(role="officer", department_id=dept.id, year=year, section=section).first()

@admin.get("/class-incharges")
def class_incharges(_=Depends(ADMIN), db: Session = Depends(get_db)):
    """Class -> Class Incharge mapping for every class/division (unassigned classes show null)."""
    out = []
    for year, sections in schemas.SECTIONS_BY_YEAR.items():
        for sec in sections:
            o = _class_incharge(db, year, sec)
            out.append({"year": year, "section": sec, "officer_id": o.id if o else None, "officer_name": o.name if o else None,
                        "email": o.email if o else None})
    return out

@admin.put("/class-incharges/{year}/{section}")
def set_class_incharge(year: str, section: str, data: schemas.ClassInchargeAssignIn, me=Depends(ADMIN), db: Session = Depends(get_db)):
    """Make an officer (Class Incharge department) responsible for one class/division."""
    section = section.upper()
    if section not in schemas.SECTIONS_BY_YEAR.get(year, []):
        raise HTTPException(422, f"{year} has no section {section}")
    dept = _class_incharge_dept(db)
    o = db.get(models.User, data.officer_id)
    if not o or o.role != "officer" or not dept or o.department_id != dept.id:
        raise HTTPException(404, "Class Incharge officer not found")
    old = _class_incharge(db, year, section)
    if old and old.id != o.id:
        old.year = old.section = None            # previous incharge of this class is now unassigned
    o.year, o.section = year, section
    db.flush()
    # open complaints of this class that were with the old incharge (or nobody) now go to the new one
    moved = 0
    rows = db.query(models.Complaint).join(models.User, models.Complaint.student_id == models.User.id).filter(
        models.User.year == year, models.User.section == section,
        models.Complaint.status.notin_(["Resolved", "Closed"]), models.Complaint.category.in_(["Teaching & Syllabus", "Classroom Infrastructure"])).all()
    for c in rows:
        if c.officer_id != o.id and (c.officer_id is None or (old and c.officer_id == old.id)):
            c.officer_id = o.id
            if c.status == "Submitted":
                c.status = "Assigned"
            db.add(models.StatusHistory(complaint_id=c.id, status=c.status, remarks=f"Class Incharge changed to {o.name}", changed_by=me.id))
            notify(db, o, f"Complaint {c.code} ({c.title}) of {year}-{section} was assigned to you")
            moved += 1
    audit(db, me.id, "CLASS_INCHARGE_SET", f"{year}-{section} -> {o.name}")
    db.commit()
    return {"message": f"{o.name} is now Class Incharge of {year}-{section}", "complaints_moved": moved}

@admin.patch("/users/{uid}")
def update_staff(uid: int, data: schemas.UpdateStaffIn, me=Depends(ADMIN), db: Session = Depends(get_db)):
    """Edit a staff member's name / login email (and class, for a Class Incharge)."""
    u = _staff(db, uid)
    if data.department_id is not None and data.department_id != u.department_id:
        if u.role != "officer":
            raise HTTPException(422, "Only a departmental officer belongs to a department")
        dept = db.get(models.Department, data.department_id)
        if not dept:
            raise HTTPException(404, "Department not found")
        if u.department and u.department.name == "Class Incharge":
            u.year = u.section = None          # leaving Class Incharge: no longer owns a class
        u.department_id = dept.id
    if data.lab_numbers is not None:
        if not (u.department and u.department.name == "Lab Assistant"):
            raise HTTPException(422, "Only a Lab Assistant has lab numbers")
        u.lab_numbers = data.lab_numbers
    if data.email and data.email != u.email:
        if db.query(models.User).filter_by(email=data.email).first():
            raise HTTPException(409, "Email already registered")
        u.email = data.email
    if data.name and data.name.strip():
        u.name = data.name.strip()
    if data.year or data.section:
        db.flush()
        dept = _class_incharge_dept(db)
        if u.role != "officer" or not dept or u.department_id != dept.id:
            raise HTTPException(422, "Only a Class Incharge has a class")
        year, sec = data.year or u.year, (data.section or u.section or "").upper()
        if sec not in schemas.SECTIONS_BY_YEAR.get(year, []):
            raise HTTPException(422, f"{year} has no section {sec}")
        other = _class_incharge(db, year, sec)
        if other and other.id != u.id:
            raise HTTPException(409, f"{year}-{sec} already has a Class Incharge ({other.name})")
        u.year, u.section = year, sec
    audit(db, me.id, "STAFF_UPDATED", u.email)
    db.commit()
    return {"message": "Saved"}

@admin.post("/users/{uid}/reset-password")
def reset_password(uid: int, data: schemas.ResetPasswordIn, me=Depends(ADMIN), db: Session = Depends(get_db)):
    """Admin sets a new password for a staff account (also clears any lock)."""
    u = _staff(db, uid)
    u.password_hash = hash_password(data.new_password)
    u.failed_attempts, u.locked_until, u.otp_hash, u.otp_expires = 0, None, None, None
    audit(db, me.id, "PASSWORD_RESET_BY_ADMIN", u.email)
    db.commit()
    return {"message": f"Password updated for {u.name}"}

@admin.post("/users/{uid}/unlock")
def unlock(uid: int, me=Depends(ADMIN), db: Session = Depends(get_db)):
    u = _staff(db, uid)
    u.failed_attempts, u.locked_until = 0, None
    audit(db, me.id, "ACCOUNT_UNLOCKED", u.email)
    db.commit()
    return {"message": f"{u.name} unlocked"}

@admin.patch("/users/{uid}/active")
def set_active(uid: int, data: schemas.ActiveIn, me=Depends(ADMIN), db: Session = Depends(get_db)):
    """Enable / disable an account. A disabled account cannot log in and gets no new complaints, but its history stays."""
    u = _staff(db, uid)
    if not data.active:
        if u.id == me.id:
            raise HTTPException(409, "You cannot disable your own account")
        if u.role == "admin" and u.is_active is not False and _active_admins(db) <= 1:
            raise HTTPException(409, "At least one admin account must stay active")
    u.is_active = data.active
    audit(db, me.id, "ACCOUNT_ENABLED" if data.active else "ACCOUNT_DISABLED", u.email)
    db.commit()
    return {"message": f"{u.name} {'enabled' if data.active else 'disabled'}"}

@admin.delete("/users/{uid}")
def delete_user(uid: int, data: schemas.DeleteUserIn = None, me=Depends(ADMIN), db: Session = Depends(get_db)):
    """Permanently remove a staff account. Its open complaints must be handed to another officer
    (reassign_to) first; closed ones simply lose their officer link. Disable is the gentler option."""
    u = _staff(db, uid)
    if u.id == me.id:
        raise HTTPException(409, "You cannot delete your own account")
    if u.role == "admin" and u.is_active is not False and _active_admins(db) <= 1:
        raise HTTPException(409, "At least one admin account must stay active")
    mine = db.query(models.Complaint).filter_by(officer_id=u.id).all()
    open_ = [c for c in mine if c.status not in ("Resolved", "Closed")]
    target = None
    if open_:
        rid = data.reassign_to if data else None
        target = db.get(models.User, rid) if rid else None
        if not target or target.role != "officer" or target.id == u.id or target.is_active is False:
            raise HTTPException(409, f"{u.name} has {len(open_)} open complaint(s). Choose another active officer to take them over (reassign_to), or disable the account instead")
    for c in mine:
        if c in open_:
            c.officer_id = target.id
            db.add(models.StatusHistory(complaint_id=c.id, status=c.status, remarks=f"Reassigned to {target.name} (previous officer's account removed)", changed_by=me.id))
            notify(db, target, f"Complaint {c.code} ({c.title}) was assigned to you")
        else:
            c.officer_id = None
    db.query(models.StatusHistory).filter_by(changed_by=u.id).update({"changed_by": None})
    db.query(models.Escalation).filter_by(to_user_id=u.id).delete()
    db.query(models.Notification).filter_by(user_id=u.id).delete()
    audit(db, me.id, "USER_DELETED", f"{u.email} ({u.role})")
    db.delete(u)
    db.commit()
    return {"message": f"{u.name} deleted", "complaints_moved": len(open_)}

@admin.post("/users/{uid}/impersonate")
def impersonate(uid: int, me=Depends(ADMIN), db: Session = Depends(get_db)):
    """Open a staff member's own dashboard as the admin (short 30 min session, recorded in the audit log)."""
    u = _staff(db, uid)
    if u.role == "admin":
        raise HTTPException(422, "Use a departmental / HOD / Principal account")
    if u.is_active is False:
        raise HTTPException(409, "Enable this account first")
    audit(db, me.id, "ADMIN_VIEW_AS", u.email); db.commit()
    return {"access_token": create_token(u.id, u.role, minutes=30, act_by=me.id), "token_type": "bearer",
            "role": u.role, "name": u.name, "level": u.level,
            "department": u.department.name if u.department else None}

@admin.post("/users", status_code=201)
def create_user(data: schemas.CreateUserIn, me=Depends(ADMIN), db: Session = Depends(get_db)):
    if db.query(models.User).filter_by(email=data.email).first():
        raise HTTPException(409, "Email already registered")
    dept = db.get(models.Department, data.department_id or 0)
    if data.role == "officer" and not dept:
        raise HTTPException(422, "Officer needs a valid department_id")
    if data.role == "authority" and data.level not in (1, 2):
        raise HTTPException(422, "Authority level must be 1 (HOD) or 2 (Principal)")
    if data.role == "officer" and dept and dept.name == "Class Incharge" and not (data.year and data.section):
        raise HTTPException(422, "A Class Incharge needs a year and section (which class they coordinate)")
    if data.role == "officer" and dept and dept.name == "Class Incharge":
        if data.section not in schemas.SECTIONS_BY_YEAR.get(data.year, []):
            raise HTTPException(422, f"{data.year} has no section {data.section}")
        if _class_incharge(db, data.year, data.section):
            raise HTTPException(409, f"{data.year}-{data.section} already has a Class Incharge. Use 'Class Incharges' panel to change it")
    if data.role == "officer" and dept and dept.name == "Lab Assistant" and not data.lab_numbers:
        raise HTTPException(422, "A Lab Assistant needs lab_numbers (which lab(s) they're in charge of, e.g. '1,2,3')")
    u = models.User(name=data.name.strip(), email=data.email, password_hash=hash_password(data.password), role=data.role,
                    department_id=data.department_id if data.role == "officer" else None,
                    level=data.level if data.role == "authority" else 0,
                    year=data.year if data.role == "officer" else None,
                    section=data.section if data.role == "officer" else None,
                    lab_numbers=data.lab_numbers if data.role == "officer" else None,
                    notify_email=(data.notify_email or "").strip() or None,
                    notify_name=(data.notify_name or "").strip() or None)
    db.add(u); audit(db, me.id, "USER_CREATED", f"{data.email} as {data.role}"); db.commit()
    return {"id": u.id}

@admin.patch("/users/{uid}/notify-email")
def set_notify_email(uid: int, data: schemas.NotifyEmailIn, me=Depends(ADMIN), db: Session = Depends(get_db)):
    """Set (or clear) the REAL mailbox that a person's complaint alerts are emailed to."""
    import re
    u = db.get(models.User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    addr = (data.notify_email or "").strip()
    if addr and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", addr):
        raise HTTPException(422, "Enter a valid email address")
    u.notify_email = addr or None
    u.notify_name = (data.notify_name or "").strip() or None
    audit(db, me.id, "ALERT_EMAIL_SET", f"{u.email} -> {addr or 'off'}")
    db.commit()
    return {"message": "Saved"}

@admin.get("/officers")
def officers(_=Depends(ADMIN), db: Session = Depends(get_db)):
    rows = db.query(models.User).filter_by(role="officer").all()
    def label(o):
        dept = o.department.name if o.department else ""
        if dept == "Class Incharge" and o.year:
            return f"{o.name} ({o.year}-{o.section})"
        if dept == "Lab Assistant" and o.lab_numbers:
            return f"{o.name} (Labs {o.lab_numbers})"
        return o.name
    return [{"id": o.id, "name": label(o), "department": o.department.name if o.department else None,
             "year": o.year, "section": o.section, "lab_numbers": o.lab_numbers} for o in rows]

@admin.get("/departments")
def departments(_=Depends(ADMIN), db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name} for d in db.query(models.Department)]

@admin.post("/complaints/{cid}/assign")
def assign(cid: int, data: schemas.AssignIn, me=Depends(ADMIN), db: Session = Depends(get_db)):
    c, o = db.get(models.Complaint, cid), db.get(models.User, data.officer_id)
    if not c or not o or o.role != "officer":
        raise HTTPException(404, "Complaint or officer not found")
    c.officer_id = o.id
    if c.status == "Submitted":
        c.status = "Assigned"
    db.add(models.StatusHistory(complaint_id=c.id, status=c.status, remarks=f"Manually assigned to {o.name} by admin", changed_by=me.id))
    audit(db, me.id, "REASSIGN", f"{c.code} -> {o.name}")
    notify(db, o, f"Complaint {c.code} was assigned to you by admin")
    db.commit()
    return {"message": "Assigned"}

@admin.post("/run-escalation")
def trigger_escalation(me=Depends(ADMIN), db: Session = Depends(get_db)):
    return {"escalated": run_escalation(db)}

@admin.get("/audit")
def audit_log(limit: int = 300, _=Depends(ADMIN), db: Session = Depends(get_db)):
    """Latest audit entries (newest first) from the SQL audit_logs table."""
    limit = max(1, min(limit, 1000))
    rows = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(limit).all()
    names = {u.id: f"{u.name} ({u.role})" for u in db.query(models.User).all()}
    return [{"id": r.id, "user_id": r.user_id, "user": names.get(r.user_id, "System" if r.user_id is None else "Deleted user"),
             "action": r.action, "detail": r.detail or "", "at": r.at.isoformat() if r.at else None} for r in rows]

@analytics_router.get("")
def analytics(_=Depends(require_role("admin", "authority")), db: Session = Depends(get_db)):
    cs = db.query(models.Complaint).all()
    count = lambda key: {k: sum(1 for c in cs if getattr(c, key) == k) for k in sorted({getattr(c, key) for c in cs}, key=str)}
    done = [(c.resolved_at - c.created_at).total_seconds() / 3600 for c in cs if c.resolved_at]
    rated = [c.rating for c in cs if c.rating]
    open_ = [c for c in cs if c.status not in ("Resolved", "Closed")]
    return {"total": len(cs), "pending": len(open_), "resolved": len(cs) - len(open_),
            "escalated": sum(1 for c in cs if c.escalation_level > 0 or c.status == "Escalated"),
            "overdue": sum(1 for c in open_ if c.sla_due and c.sla_due < datetime.utcnow()),
            "avg_resolution_hours": round(sum(done) / len(done), 2) if done else None,
            "avg_rating": round(sum(rated) / len(rated), 2) if rated else None,
            "by_category": count("category"), "by_priority": count("priority"), "by_status": count("status"),
            "hotspots": sorted([{"code": c.code, "title": c.title, "reports": c.duplicate_count + 1}
                                for c in cs if c.duplicate_count], key=lambda x: -x["reports"])[:5]}

@notif_router.get("")
def my_notifications(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(models.Notification).filter_by(user_id=user.id).order_by(models.Notification.id.desc()).limit(30).all()
    return [{"id": n.id, "message": n.message, "is_read": n.is_read, "at": n.created_at.isoformat()} for n in rows]

@notif_router.post("/read")
def mark_read(user=Depends(current_user), db: Session = Depends(get_db)):
    db.query(models.Notification).filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.commit()
    return {"ok": True}
