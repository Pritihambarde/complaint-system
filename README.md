# AI Complaint Classification & Escalation System

**CSE Department, Mahatma Gandhi Mission's College of Engineering, Nanded**

Students write a complaint in plain words. The system **classifies** it with NLP, sets its **priority**, **routes** it to the right coordinator, and **auto-escalates** it (Departmental → HOD → Principal) if the deadline is missed.

---

## Contents

1. [Features](#1-features)
2. [Tech stack](#2-tech-stack)
3. [Folder structure](#3-folder-structure)
4. [Run it on your computer](#4-run-it-on-your-computer)
5. [Configuration (.env)](#5-configuration-env)
6. [Databases (SQL + MongoDB)](#6-databases-sql--mongodb)
7. [Roles, accounts and who handles what](#7-roles-accounts-and-who-handles-what)
8. [Complaint lifecycle, deadlines and escalation](#8-complaint-lifecycle-deadlines-and-escalation)
9. [Admin dashboard guide](#9-admin-dashboard-guide)
10. [Email alerts](#10-email-alerts)
11. [Evidence photo / PDF upload](#11-evidence-photo--pdf-upload)
12. [Tests](#12-tests)
13. [Deployment, step by step](#13-deployment-step-by-step)
14. [Security checklist](#14-security-checklist)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Features

**Accounts and security**
- College-domain registration, bcrypt password hashing, JWT login with expiry, role checks on every API
- Account lockout (5 failed attempts → locked for 15 minutes)
- Forgot / reset password with a 6-digit OTP sent by email
- Separate **Student** and **Staff** login portals (a student cannot log in on the staff portal and the reverse)
- Rate limiting and a full audit log

**AI**
- TF-IDF + Logistic Regression decides the complaint **category**
- Hybrid **priority** (the model plus safety keyword rules)
- Sentiment, explainable key terms, spam / abuse filter, duplicate detection
- Low-confidence triage: below 35% confidence, the complaint goes to the Admin Desk

**Complaint handling**
- Anonymous option, evidence upload (JPG / PNG / PDF), status history, rating, reopen within 7 days
- Lab complaints must state the lab number (1–10); it decides which Lab Assistant receives them
- Automatic **escalation** by a background scheduler, with full history
- In-app notifications and real email alerts

**Admin**
- Analytics, date + status + search filters, reassigning complaints
- Create / disable / unlock / delete staff accounts, reset passwords, "view as" a staff dashboard
- Audit log table (who did what, and when)

---

## 2. Tech stack

| Part | Technology |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy |
| Frontend | One HTML file (`frontend/index.html`) served by the backend |
| AI | scikit-learn (TF-IDF + Logistic Regression), joblib |
| Photo check | CLIP model (`torch`, `transformers`), optional |
| SQL database | SQLite by default (MySQL / PostgreSQL via `DATABASE_URL`) |
| NoSQL database | MongoDB (copy of the audit log) |
| Email | SMTP (Gmail App Password) |

---

## 3. Folder structure

```
complaint-system-project/
├── backend/
│   ├── app/
│   │   ├── main.py          app start-up, scheduler, serves the frontend
│   │   ├── models.py        database tables
│   │   ├── schemas.py       input checks (email format, password rule)
│   │   ├── security.py      password hashing, tokens, role checks
│   │   ├── services.py      notifications, audit log, escalation engine
│   │   ├── seed.py          creates departments and first accounts
│   │   ├── ml.py            loads the model and classifies a complaint
│   │   ├── image_check.py   evidence photo checks
│   │   ├── mongo.py         MongoDB connection
│   │   └── routes/          auth.py, complaints.py, admin.py
│   ├── tests/               automated tests
│   ├── requirements.txt
│   ├── .env.example         sample settings (copy to .env)
│   ├── send_test_email.py   checks that email works
│   └── add_demo_data.py     adds sample complaints for testing
├── frontend/                index.html, logo, campus image
├── ml/                      dataset, training script, model.joblib
├── docs/                    report and viva answers
├── run.bat / run.sh         one-click start (Windows / Mac-Linux)
└── README.md
```

---

## 4. Run it on your computer

**Windows**
```
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app
```

**Mac / Linux**
```
./run.sh
```

Open **http://127.0.0.1:8000**.

- On the first start the AI model trains itself if the saved one does not match your scikit-learn version (a few seconds).
- If port 8000 is busy, add `--port 8001`.
- Copy `backend/.env.example` to `backend/.env` and fill it in (see section 5). Never share or upload `.env`.

---

## 5. Configuration (.env)

Create `backend/.env`. All settings are optional for a local demo.

| Setting | Meaning | Example |
|---|---|---|
| `DATABASE_URL` | SQL database. Leave empty for SQLite (`backend/complaints.db`) | `sqlite:///./complaints.db` |
| `MONGO_URL` | MongoDB connection string (audit log copy) | `mongodb+srv://user:pass@cluster/...` |
| `MONGO_DB` | MongoDB database name | `complaints_system` |
| `COLLEGE_DOMAIN` | Allowed email domain | `mgmcen.ac.in` |
| `SECRET_KEY` | Long random string that signs login tokens | see below |
| `SLA_SCALE` | Shrinks deadlines for a live demo (`1` = real) | `1` |
| `ESCALATION_INTERVAL` | Seconds between escalation checks (`0` = off) | `60` |
| `DEBUG_OTP` | `1` shows the OTP on screen (demo only) | `0` in production |
| `DEBUG_ERRORS` | `1` shows detailed server errors | `0` in production |
| `SMTP_HOST` / `SMTP_PORT` | Mail server | `smtp.gmail.com` / `587` |
| `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | Mailbox and its **App Password** | |
| `APP_URL` | Public address of the site | `https://yourapp.onrender.com` |
| `IMAGE_RELEVANCE` | `clip` = check pictures, `off` = only real / not blank | `clip` |

Generate a secret key:
```
python -c "import secrets; print(secrets.token_hex(32))"
```

> A password that contains `@`, `#`, `/` or `:` must be URL-encoded inside `MONGO_URL` (`@` becomes `%40`). Letters and numbers only avoids this.

---

## 6. Databases (SQL + MongoDB)

| Database | Stores | Why |
|---|---|---|
| **SQL** (SQLite, MySQL or PostgreSQL) | Users, complaints, departments, notifications, status history, escalations, audit log | Data with relationships |
| **MongoDB** | A copy of the audit log (`complaints_system` → `audit_logs`) | Append-only events with a flexible shape |

- The audit log is always saved in SQL, so the admin table always works. MongoDB is a bonus copy.
- The app runs fine when MongoDB is not reachable. It then skips MongoDB for 60 seconds at a time.
- View SQLite with *DB Browser for SQLite*, and MongoDB with *MongoDB Compass*.
- In MongoDB Atlas, allow your computer or server under **Network Access**.

---

## 7. Roles, accounts and who handles what

| Role | Login portal | What they do |
|---|---|---|
| Student | Student Login | Submit and track complaints |
| Officer (departmental staff) | Staff Login | Handle complaints assigned to their office |
| HOD (Level 1) / Principal (Level 2) | Staff Login | Receive escalated complaints |
| Admin | Staff Login | Manage everything |

Students register themselves with their college email in the form `s23_surname_firstname@mgmcen.ac.in` (`s22`, `s24`, `s25` also work). Staff, HOD and Principal **cannot** self-register. The Admin creates them (Admin dashboard → Create staff account).

### Which office gets which category

| Category (decided by the AI) | Goes to |
|---|---|
| Lab & Equipment | Lab Assistant, chosen by lab number |
| Classroom Infrastructure | Class Incharge of the student's own year + section |
| Teaching & Syllabus | Class Incharge |
| Timetable & Attendance | Timetable Coordinator (all go to Ms Dumne) |
| Exams & Marks | Exam Coordinator |
| Projects & Placements | Project Placement Cell |
| Other / AI unsure (below 35%) | Admin Desk |
| Ragging & Harassment | **HOD directly**, always Critical |

### Staff in the starting data (`backend/app/seed.py`)

All emails end with `@mgmcen.ac.in`.

| Office | Login (before the `@`) |
|---|---|
| Lab Assistants (labs 1–3, 4–6, 7–8, 9–10) | `sangnor_suresh_nilkanthrao`, `prashant_kishanrao_deshmukh`, `nirmale_pooja_kour_surjeet_singh`, `vaidya_madhav` |
| Class Incharge SY A / B / C | `k_p_people`, `s_s_wagre`, `m_h_khan` |
| Class Incharge TY A / B / C | `p_s_bihade`, `d_b_aghor`, `sayed_ateeq_b` |
| Class Incharge BTech A / B | `m_r_chennoji`, `m_g_shelke` |
| Project Placement Cell | `nitu_l_pariyal` (BTech A), `wahi_g_s` (BTech B), `s_i_titre` (everyone else) |
| Exam Coordinator | `v_s_jadhav` |
| Timetable Coordinator | `dumne_rs` (receives all), `m_n_bhandare`, `d_s_naik` |
| Departmental Coordinator | `m_y_joshi` |
| Admin Desk | `admindesk` |
| HOD (Level 1) | `a_m_rajurkar` |
| Principal (Level 2) | `principal` |
| Admin | `admin` |

### First-run passwords

These accounts are created only when the database is empty. The passwords are set in `backend/app/seed.py`.

| Account | Password |
|---|---|
| Admin (`admin@…`) | `Admin@123` |
| Demo student (`s25_demo_student@…`) | `Student@123` |
| Staff in the table above | the `STAFF_PASSWORD` value in `seed.py` |
| Admin Desk and Principal | `Officer@123` |

> **Change every one of these passwords right after the first login**, and disable the demo student. Use Admin dashboard → Departmental accounts → reset password. Do not leave default passwords on a live site.

---

## 8. Complaint lifecycle, deadlines and escalation

**Statuses:** Submitted → Assigned → In Progress → Resolved → Closed. Also Query (lab), Reopened and Escalated.

**Deadlines**

| Priority | Time to solve |
|---|---|
| Low | 3 days |
| Medium | 2 days |
| High | 1 day |
| Critical | 1 day |

**Escalation.** A background job runs every `ESCALATION_INTERVAL` seconds (60 by default). It moves an open complaint whose deadline has passed one level up:

```
Officer  →  HOD (Level 1)  →  Principal (Level 2)
```

- Each escalation sets the status to *Escalated*, records the history, writes `AUTO_ESCALATE` to the audit log, and notifies the HOD / Principal, the office staff and the student.
- Ragging and Harassment complaints **start** at the HOD and can escalate to the Principal.
- The check only runs while the server is running. If the server was off, overdue complaints stay un-escalated until it is on again, or until the admin presses **Run escalation check now**.

**Live demo of escalation**
```
set SLA_SCALE=0.0005
set ESCALATION_INTERVAL=15
python -m uvicorn app.main:app
```
Submit a Critical complaint (for example, a lab problem containing the word "unsafe") and leave it unresolved. About a minute later it moves to the HOD, then to the Principal.

---

## 9. Admin dashboard guide

Log in through **Staff Login** with the admin account.

**Analytics card.** Shows Total, Pending, Resolved, **Escalated**, Overdue, average resolution time and average rating. *Escalated* counts every complaint that has been escalated, including ones that were later moved to In Progress or Resolved, and ones sent straight to the HOD. The **Run escalation check now** button escalates all overdue complaints immediately and reports how many.

**All complaints card**
- Filters: From date, To date (by the day the complaint was **submitted**), Status, Search.
- Choosing **Status = Escalated** lists every complaint that was ever escalated and shows a count line, for example "Escalated complaints in the selected dates: 12".
- The Summary box above the table follows the dates (not the Status or Search boxes).
- *Overdue* means the deadline has passed and the complaint is not Resolved or Closed.

**Audit log table.** Columns: Time, Who, Action, Detail.
- *Who* shows `Name (role)`. `System` means an automatic action, such as an escalation. `Deleted user` means the account was removed but the history was kept.
- Common actions: `LOGIN`, `ACCOUNT_LOCKED`, `OTP_REQUESTED`, `PASSWORD_RESET`, `AUTO_ESCALATE`, `REASSIGN`, `USER_CREATED`, `ACCOUNT_DISABLED`, `ADMIN_VIEW_AS`.
- Your own admin login also appears here, which is normal.

**Other cards.** Create staff account, Class Incharges, and Departmental accounts (reset password, unlock, disable, delete, set the alert email, open a staff dashboard as admin).

---

## 10. Email alerts

Staff do not need to be logged in to be told about a complaint. A mail is sent when a complaint is assigned, reopened, or escalated after a missed deadline.

1. Real addresses are listed in `REAL_CONTACTS` in `backend/app/seed.py`, or set in Admin → Users → set / change.
2. Fill `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` (and `SMTP_FROM`) in `backend/.env`.
   - Gmail needs 2-Step Verification and an **App Password** (Google Account → Security → App passwords).
3. Test it from the `backend` folder:
   ```
   python send_test_email.py your_address@example.com
   ```
   It prints `[EMAIL sent -> …]`, or the exact error from the mail server.

Until SMTP is filled in, mails are only printed in the server window. People without a real address get in-app alerts only. Password-reset OTPs also use email, so email must work when `DEBUG_OTP=0`.

---

## 11. Evidence photo / PDF upload

Students can attach a photo or PDF. The server checks it before saving the complaint:
- It must be a real, readable JPG, PNG or PDF (not damaged, not tiny, up to 5 MB).
- Blank images and blank PDFs are rejected.
- The picture must match the problem type. A Lab & Equipment complaint only accepts computer-lab pictures, and Classroom Infrastructure accepts projector, fan, light, bench and similar. Ragging and Other only get the real / not-blank checks.

Relevance uses the free CLIP model (`backend/app/image_check.py`). The first start downloads about 600 MB and needs about 2 GB of RAM. Set `IMAGE_RELEVANCE=off` in `.env` to keep only the real / not-blank checks. If the model is not installed, uploads are refused with a clear message.

---

## 12. Tests

```
cd backend
python -m pytest tests
```

---

## 13. Deployment, step by step

The project is **one web service**: the same FastAPI server serves the API and `frontend/index.html`.

### Before you choose a host

- **Memory.** `torch` and `transformers` need about 2 GB RAM. For a small server, set `IMAGE_RELEVANCE=off` and remove `torch` and `transformers` from `requirements.txt`, then test photo upload.
- **Persistence.** SQLite and the `uploads/` folder are lost on every redeploy on free hosts. Use a persistent disk (or a hosted database).
- **One process only.** The scheduler runs inside the app and SQLite does not suit several workers.
- **Sleeping.** A free plan that sleeps stops the escalation job. Use a paid plan, or ping `/health` every few minutes.

### Step 1: Secure the project

1. Never put real passwords in files you upload. Create new ones if they were ever shared: MongoDB password, Gmail App Password, `SECRET_KEY`.
2. Put these lines in a `.gitignore` file in the project root:
   ```
   backend/.env
   backend/venv/
   backend/complaints.db
   backend/uploads/
   __pycache__/
   ```
3. Set `DEBUG_OTP=0` and `DEBUG_ERRORS=0`.

### Step 2: Put the code on GitHub (private)

1. On github.com create a **Private** repository named `complaint-system`, with no README, .gitignore or license added.
2. In the project folder:
   ```
   git init
   git add .
   git status
   ```
   Check the list: `backend/.env`, `complaints.db` and `uploads` must **not** appear (`backend/.env.example` is fine).
3. Then:
   ```
   git commit -m "Complaint system"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/complaint-system.git
   git push -u origin main
   ```
4. Later changes: `git add .`, `git commit -m "message"`, `git push`.

### Step 3: Deploy on Render (example)

1. At render.com choose **New → Web Service** and pick the repository.
2. Add the environment variable `PYTHON_VERSION=3.11.9`.
3. **Build command:**
   ```
   pip install -r backend/requirements.txt
   ```
4. **Start command** (run from `backend`; the symlink keeps uploads on the disk):
   ```
   cd backend && mkdir -p /var/data/uploads && ln -sfn /var/data/uploads uploads && uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
5. Pick a plan with at least 2 GB RAM if you keep `torch`, and add a **persistent disk** mounted at `/var/data`.
6. Add the environment variables:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | `sqlite:////var/data/complaints.db` |
   | `SECRET_KEY` | your own random key |
   | `MONGO_URL`, `MONGO_DB` | your MongoDB Atlas string, `complaints_system` |
   | `COLLEGE_DOMAIN` | `mgmcen.ac.in` |
   | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | your mail settings |
   | `APP_URL` | your Render address |
   | `DEBUG_OTP`, `DEBUG_ERRORS` | `0` |
   | `SLA_SCALE`, `ESCALATION_INTERVAL` | `1`, `60` |
   | `IMAGE_RELEVANCE` | `clip` or `off` |

7. Click **Create Web Service** and wait for the build.
8. In MongoDB Atlas → Network Access, allow the host (on Render use `0.0.0.0/0`).

### Step 4: After it is live

1. Open `https://YOUR-APP/health`. It should show `{"status":"ok"}`.
2. **Change all default passwords** (section 7) and disable the demo student.
3. Test: register a student, submit a complaint, check the email alert and the OTP mail, press **Run escalation check now**, and confirm the audit log fills in.

### Alternative: a college server (Ubuntu)

1. Install Python 3.11 and git, clone the repository, create a virtual environment in `backend`, and run `pip install -r requirements.txt`.
2. Put the settings from section 5 in `backend/.env`.
3. Run `uvicorn app.main:app --host 127.0.0.1 --port 8000` as a **systemd** service.
4. Put **nginx** in front as a reverse proxy and add HTTPS with **certbot**.
5. Back up `complaints.db` and `uploads/` regularly.

---

## 14. Security checklist

- [ ] `backend/.env` is never uploaded (it is in `.gitignore`)
- [ ] New `SECRET_KEY`, MongoDB password and Gmail App Password
- [ ] `DEBUG_OTP=0` and `DEBUG_ERRORS=0`
- [ ] All first-run passwords changed; demo student disabled
- [ ] Repository is **Private**
- [ ] HTTPS is on (automatic on Render)
- [ ] Database and `uploads/` are backed up
- [ ] Email works (`python send_test_email.py`)

---

## 15. Troubleshooting

| Problem | Cause and fix |
|---|---|
| **Escalated shows 0** | The escalation check has not run. Press **Run escalation check now**, or make sure the server stays running. Complaints are only escalated after their deadline passes. |
| **Admin login fails** | Use **Staff Login**, not Student Login. Check the email and password. After 5 failures the account is locked for 15 minutes (admin can unlock it). |
| **"Student accounts cannot log in here"** | You are on the Staff portal. Use Student Login. |
| **No email arrives** | Run `python send_test_email.py`. A "Username and Password not accepted" error means a wrong App Password. Check the spam folder. |
| **Audit log says "Could not load"** | Log in as admin again. The table comes from SQL, so MongoDB being off does not break it. |
| **"Mongo audit copy skipped"** in the server window | MongoDB is unreachable (wrong string or password, or your IP is not allowed in Atlas). The app still works. |
| **Port 8000 busy** | Add `--port 8001` to the start command. |
| **Photo upload refused** | The CLIP model is not installed or has not finished downloading. Install the requirements, or set `IMAGE_RELEVANCE=off`. |
| **Data disappears after redeploy** | The database and uploads are on temporary storage. Add a persistent disk and point `DATABASE_URL` at it. |
| **A new student cannot register** | The email must be `s23_surname_firstname@mgmcen.ac.in` (year prefix `s22`–`s25`) and the password must meet the strength rule (8–64 characters with upper, lower, digit and special). |
