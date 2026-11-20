<h1 align="center">📣 AI Complaint Classification & Escalation System</h1>

<p align="center">
  <b>CSE Department, Mahatma Gandhi Mission's College of Engineering, Nanded</b>
</p>

<p align="center">
  Students write a complaint in plain words. The system classifies it with NLP, sets its priority, routes it to the right coordinator, and auto-escalates it (Departmental → HOD → Principal) if the deadline is missed.
</p>

<p align="center">
  <a href="https://complaint-system-jpab.onrender.com"><img src="https://img.shields.io/badge/🌐%20Live%20Demo-Open%20Site-000000?style=for-the-badge" /></a>
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/AI-scikit--learn-F7931E?style=for-the-badge&logo=scikitlearn&logoColor=white" />
  <img src="https://img.shields.io/badge/SQL-SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" />
  <img src="https://img.shields.io/badge/NoSQL-MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white" />
  <img src="https://img.shields.io/badge/Deployed%20on-Render-46E3B7?style=for-the-badge&logo=render&logoColor=black" />
</p>

---

## 🌐 Live Demo

**👉 [https://complaint-system-jpab.onrender.com](https://complaint-system-jpab.onrender.com)**

> ⏳ The site runs on a free Render plan, so the **first load may take about a minute** while the server wakes up.

**Try it:** open **Student Login**, register with an email like `s25_yourname_first@mgmcen.ac.in`, then submit a complaint such as "The projector in the lab is not working" and watch it get classified, prioritized, and routed.

---

## 📑 Contents

1. [Features](#-1-features)
2. [Tech stack](#️-2-tech-stack)
3. [Folder structure](#-3-folder-structure)
4. [Run it on your computer](#-4-run-it-on-your-computer)
5. [Configuration (.env)](#️-5-configuration-env)
6. [Databases (SQL + MongoDB)](#️-6-databases-sql--mongodb)
7. [Roles, accounts and who handles what](#-7-roles-accounts-and-who-handles-what)
8. [Complaint lifecycle, deadlines and escalation](#-8-complaint-lifecycle-deadlines-and-escalation)
9. [Admin dashboard guide](#-9-admin-dashboard-guide)
10. [Email alerts](#-10-email-alerts)
11. [Evidence photo / PDF upload](#-11-evidence-photo--pdf-upload)
12. [Tests](#-12-tests)
13. [Deployment, step by step](#-13-deployment-step-by-step)
14. [Security checklist](#-14-security-checklist)
15. [Troubleshooting](#-15-troubleshooting)

---

## ✨ 1. Features

**🔐 Accounts and security**
- College-domain registration, bcrypt password hashing, JWT login with expiry, role checks on every API
- Account lockout (5 failed attempts → locked for 15 minutes)
- Forgot / reset password with a 6-digit OTP sent by email
- Separate Student and Staff login portals (a student cannot log in on the staff portal and the reverse)
- Rate limiting and a full audit log

**🤖 AI**
- TF-IDF + Logistic Regression decides the complaint category
- Hybrid priority (the model plus safety keyword rules)
- Sentiment, explainable key terms, spam / abuse filter, duplicate detection
- Low-confidence triage: below 35% confidence, the complaint goes to the Admin Desk

**📋 Complaint handling**
- Anonymous option, evidence upload (JPG / PNG / PDF), status history, rating, reopen within 7 days
- Lab complaints must state the lab number (1–10); it decides which Lab Assistant receives them
- Automatic escalation by a background scheduler, with full history
- In-app notifications and real email alerts

**🛡️ Admin**
- Analytics, date + status + search filters, reassigning complaints
- Create / disable / unlock / delete staff accounts, reset passwords, "view as" a staff dashboard
- Audit log table (who did what, and when)

---

## 🛠️ 2. Tech stack

| Part | Technology |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy |
| Frontend | One HTML file (`frontend/index.html`) served by the backend |
| AI | scikit-learn (TF-IDF + Logistic Regression), joblib |
| Photo check | CLIP model (torch, transformers), optional |
| SQL database | SQLite by default (MySQL / PostgreSQL via `DATABASE_URL`) |
| NoSQL database | MongoDB (copy of the audit log) |
| Email | SMTP (Gmail App Password) |

---

## 📁 3. Folder structure

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

## 💻 4. Run it on your computer

**Windows**
```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app
```

**Mac / Linux**
```bash
./run.sh
```

Open **http://127.0.0.1:8000**.

- On the first start the AI model trains itself if the saved one does not match your scikit-learn version (a few seconds).
- If port 8000 is busy, add `--port 8001`.
- Copy `backend/.env.example` to `backend/.env` and fill it in (see section 5). **Never share or upload `.env`.**

---

## ⚙️ 5. Configuration (.env)

Create `backend/.env`. All settings are optional for a local demo.

| Setting | Meaning | Example |
|---|---|---|
| `DATABASE_URL` | SQL database. Leave empty for SQLite (`backend/complaints.db`) | `sqlite:///./complaints.db` |
| `MONGO_URL` | MongoDB connection string (audit log copy) | `mongodb+srv://user:pass@cluster/...` |
| `MONGO_DB` | MongoDB database name | `complaints_system` |
| `COLLEGE_DOMAIN` | Allowed email domain | `mgmcen.ac.in` |
| `SECRET_KEY` | Long random string that signs login tokens | see below |
| `SLA_SCALE` | Shrinks deadlines for a live demo (1 = real) | `1` |
| `ESCALATION_INTERVAL` | Seconds between escalation checks (0 = off) | `60` |
| `DEBUG_OTP` | `1` shows the OTP on screen (demo only) | `0` in production |
| `DEBUG_ERRORS` | `1` shows detailed server errors | `0` in production |
| `SMTP_HOST` / `SMTP_PORT` | Mail server | `smtp.gmail.com` / `587` |
| `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | Mailbox and its App Password | |
| `APP_URL` | Public address of the site | `https://complaint-system-jpab.onrender.com` |
| `IMAGE_RELEVANCE` | `clip` = check pictures, `off` = only real / not blank | `clip` |

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> A password that contains `@`, `#`, `/` or
