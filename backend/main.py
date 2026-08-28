"""
SCMS — Siddhant Student Council Management System
Enhanced backend for Student Council 2026-27.

Highlights
----------
- FastAPI + SQLite
- Role-based access control
- Official 21/08/2026 council roster seeded from the selection report
- Team workspaces for every council lead
- Team members, goals, tasks, meetings, announcements, documents,
  approvals, notifications and audit logs
- Dashboard statistics
- CSV exports
- PDF/source-document linking
- Optional SMTP email notifications
- Serves the existing frontend when ./frontend exists
- Designed to migrate an existing SCMS v3 database without losing data
"""

import csv
import hashlib
import io
import os
import secrets
import sqlite3
import re

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # SQLite-only local mode remains available
    psycopg2 = None
    RealDictCursor = None
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SCMS_DB", BASE_DIR / "scms_v4.db"))
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
FRONTEND_DIR = Path(os.getenv("SCMS_FRONTEND", BASE_DIR / "frontend"))
DOCUMENTS_DIR = Path(os.getenv("SCMS_DOCUMENTS", BASE_DIR / "documents"))
COUNCIL_PDF = Path(
    os.getenv(
        "SCMS_COUNCIL_PDF",
        DOCUMENTS_DIR / "Student_Council_2026-27_Selection_Report.pdf",
    )
)

APP_TITLE = "Siddhant Student Council Management System"
APP_VERSION = "4.1.0"

DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

# Tokens are intentionally in-memory, matching the previous SCMS architecture.
sessions: dict[str, int] = {}

ROLES = {
    "faculty_coordinator": "Faculty Coordinator",
    "president": "President",
    "vice_president": "Vice President",
    "general_secretary": "General Secretary",
    "joint_secretary": "Joint Secretary",
    "treasurer": "Treasurer",
    "cultural_secretary": "Cultural Secretary",
    "sports_secretary": "Sports Secretary",
    "technical_secretary": "Technical Secretary",
    "social_responsibility_secretary": "Social Responsibility Secretary",
    "pr_media_secretary": "PR & Media Secretary",
    "student_welfare_representative": "Student Welfare Secretary",
    "womens_representative": "Women's Representative",
    "placement_training_representative": "Training & Placement Representative",
    "committee_member": "Committee Member",
    "administrator": "System Administrator",
}

TEAM_ROLE_TO_KEY = {
    "cultural_secretary": "cultural",
    "sports_secretary": "sports",
    "technical_secretary": "technical",
    "social_responsibility_secretary": "social_responsibility",
    "pr_media_secretary": "pr_media",
    "student_welfare_representative": "student_welfare",
    "womens_representative": "womens",
    "placement_training_representative": "training_placement",
}

EXECUTIVE_ROLES = {
    "faculty_coordinator",
    "president",
    "vice_president",
    "general_secretary",
    "joint_secretary",
    "administrator",
}

FINANCE_ROLES = {"faculty_coordinator", "president", "general_secretary", "treasurer"}
WELFARE_ROLES = {"faculty_coordinator", "president", "student_welfare_representative"}
MEDIA_ROLES = {"faculty_coordinator", "president", "general_secretary", "pr_media_secretary"}

# ============================================================
# OFFICIAL COUNCIL DATA — FROM THE 21/08/2026 SELECTION REPORT
# ============================================================

OFFICIAL_COUNCIL = [
    # Main executive council
    dict(
        name="Rupali Tagunde", email="rupali.tagunde@scms.local",
        role="president", class_name="TE", branch="AIML", portfolio="Student Council",
    ),
    dict(
        name="Purnima Patra", email="purnima.patra@scms.local",
        role="vice_president", class_name="TE", branch="JOT", portfolio="Student Council",
    ),
    dict(
        name="Kiran Prasad", email="kiran.prasad@scms.local",
        role="general_secretary", class_name="TE", branch="COMP", portfolio="Student Council",
    ),
    dict(
        name="Kajal Bodke", email="kajal.bodke@scms.local",
        role="joint_secretary", class_name="TE", branch="E&TC", portfolio="Student Council",
    ),
    dict(
        name="Vedant Aware", email="vedant.aware@scms.local",
        role="joint_secretary", class_name="SE", branch="AIML", portfolio="Student Council",
    ),
    dict(
        name="Tushar Gawali", email="tushar.gawali@scms.local",
        role="treasurer", class_name="SE", branch="ELECT", portfolio="Finance",
    ),
    # Team leads
    dict(
        name="Aryan Pentewar", email="aryan.pentewar@scms.local",
        role="cultural_secretary", class_name="TE", branch="COMP", portfolio="Cultural",
    ),
    dict(
        name="Prachi Dinkar", email="prachi.dinkar@scms.local",
        role="sports_secretary", class_name="TE", branch="IT", portfolio="Sports",
    ),
    dict(
        name="Samiksha Harap", email="samiksha.harap@scms.local",
        role="technical_secretary", class_name="TE", branch="ECE", portfolio="Technical",
    ),
    dict(
        name="Anzar Sayyad", email="anzar.sayyad@scms.local",
        role="social_responsibility_secretary", class_name="SE", branch="E&TC",
        portfolio="Social Responsibility",
    ),
    dict(
        name="Karishma Savalekar", email="karishma.savalekar@scms.local",
        role="pr_media_secretary", class_name="TE", branch="E&TC",
        portfolio="PR & Media",
    ),
    dict(
        name="Aryan Shirpute", email="aryan.shirpute@scms.local",
        role="student_welfare_representative", class_name="SE", branch="IOT",
        portfolio="Student Welfare",
    ),
    dict(
        name="Likhitha Teppda", email="likhitha.teppda@scms.local",
        role="womens_representative", class_name="TE", branch="COMP",
        portfolio="Women's Representative",
    ),
    dict(
        name="Bhavesh Mahajan", email="bhavesh.mahajan@scms.local",
        role="placement_training_representative", class_name="TE", branch="E&TC",
        portfolio="Training & Placement",
    ),
    # Faculty coordinators
    dict(
        name="Ajeet Mahatme", email="ajeet.mahatme@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="Accounts Department", faculty=True,
    ),
    dict(
        name="Rushikesh More", email="rushikesh.more@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="First Year Department", faculty=True,
    ),
    dict(
        name="Gopinath Kalokhe", email="gopinath.kalokhe@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="Sports Department", faculty=True,
    ),
    dict(
        name="Swati Deshmukh", email="swati.deshmukh@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="Electronics & Tele-Communication Engineering", faculty=True,
    ),
    dict(
        name="Mayur Kadam", email="mayur.kadam@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="Diploma Mechanical Department", faculty=True,
    ),
    dict(
        name="Shreyash Ghanvat", email="shreyash.ghanvat@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="Civil Engineering Department", faculty=True,
    ),
    dict(
        name="Rajesh Mahamuni", email="rajesh.mahamuni@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="Computer Engineering Department", faculty=True,
    ),
    dict(
        name="Vaibhav Munde", email="vaibhav.munde@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="Mechanical Engineering Department", faculty=True,
    ),
    dict(
        name="Nilima Patil", email="nilima.patil@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="First Year Department", faculty=True,
    ),
    dict(
        name="Richa Nighote", email="richa.nighote@scms.local",
        role="faculty_coordinator", class_name="", branch="",
        portfolio="TNP Department", faculty=True,
    ),
    # Committee members
    dict(name="Aachal Baviskar", email="aachal.baviskar@scms.local", role="committee_member", class_name="SE", branch="Mech", portfolio="Executive Committee"),
    dict(name="Sandhya Kolpe", email="sandhya.kolpe@scms.local", role="committee_member", class_name="SE", branch="Mech", portfolio="Executive Committee"),
    dict(name="Prachi Tarale", email="prachi.tarale@scms.local", role="committee_member", class_name="SE", branch="Comp", portfolio="Cultural"),
    dict(name="Sakshi Yadav", email="sakshi.yadav@scms.local", role="committee_member", class_name="SE", branch="AIDS", portfolio="Cultural"),
    dict(name="Chandrakant Shinde", email="chandrakant.shinde@scms.local", role="committee_member", class_name="SE", branch="IOT", portfolio="Cultural"),
    dict(name="Ronic Vasane", email="ronic.vasane@scms.local", role="committee_member", class_name="SE", branch="AIDS", portfolio="Cultural"),
    dict(name="Pratik Galande", email="pratik.galande@scms.local", role="committee_member", class_name="SE", branch="COMP", portfolio="Cultural"),
    dict(name="Abhijeet Nimbalkar", email="abhijeet.nimbalkar@scms.local", role="committee_member", class_name="SE", branch="COMP", portfolio="Sports"),
    dict(name="Pragati Sarnaik", email="pragati.sarnaik@scms.local", role="committee_member", class_name="SE", branch="AIML", portfolio="Sports"),
    dict(name="Pranav Avate", email="pranav.avate@scms.local", role="committee_member", class_name="SE", branch="AIML", portfolio="Sports"),
    dict(name="Ajay Kadam", email="ajay.kadam@scms.local", role="committee_member", class_name="SE", branch="ELECT", portfolio="Sports"),
    dict(name="Ansari Faizan", email="ansari.faizan@scms.local", role="committee_member", class_name="SE", branch="AIDS", portfolio="Sports"),
    dict(name="Tarunay Yewale", email="tarunay.yewale@scms.local", role="committee_member", class_name="SE", branch="AIDS", portfolio="Technical"),
    dict(name="Ankita Suryavanshi", email="ankita.suryavanshi@scms.local", role="committee_member", class_name="TE", branch="AIDS", portfolio="Technical"),
    dict(name="Rohan Patil", email="rohan.patil@scms.local", role="committee_member", class_name="SE", branch="CYB", portfolio="Technical"),
    dict(name="Shubham Giram", email="shubham.giram@scms.local", role="committee_member", class_name="SE", branch="COMP", portfolio="Technical"),
    dict(name="Harhkumar Rajput", email="harhkumar.rajput@scms.local", role="committee_member", class_name="SE", branch="AIDS", portfolio="Technical"),
    dict(name="Mohit Chandanmathe", email="mohit.chandanmathe@scms.local", role="committee_member", class_name="TE", branch="ENCE", portfolio="Social Responsibility"),
    dict(name="Gaurav Dhormare", email="gaurav.dhormare@scms.local", role="committee_member", class_name="BE", branch="CIVIL", portfolio="Social Responsibility"),
    dict(name="Krishna Dixit", email="krishna.dixit@scms.local", role="committee_member", class_name="SE", branch="MECH", portfolio="Social Responsibility"),
    dict(name="Shivam Prajapati", email="shivam.prajapati@scms.local", role="committee_member", class_name="TE", branch="AIDS", portfolio="Social Responsibility"),
    dict(name="Dnyaneshwari Birajdar", email="dnyaneshwari.birajdar@scms.local", role="committee_member", class_name="SE", branch="AIML", portfolio="Social Responsibility"),
    dict(name="Savan Doiphode", email="savan.doiphode@scms.local", role="committee_member", class_name="SE", branch="AIML", portfolio="PR & Media"),
    dict(name="Harshvardhan Bhalerao", email="harshvardhan.bhalerao@scms.local", role="committee_member", class_name="SE", branch="E&TC", portfolio="PR & Media"),
    dict(name="Vaibhav Aaglave", email="vaibhav.aaglave@scms.local", role="committee_member", class_name="SE", branch="AIML", portfolio="PR & Media"),
    dict(name="Dashrath Koli", email="dashrath.koli@scms.local", role="committee_member", class_name="SE", branch="ENCE", portfolio="PR & Media"),
    dict(name="Siddhi Londhe", email="siddhi.londhe@scms.local", role="committee_member", class_name="SE", branch="AIDS", portfolio="PR & Media"),
    dict(name="Sarthak Misal", email="sarthak.misal@scms.local", role="committee_member", class_name="SE", branch="Comp", portfolio="Student Welfare"),
    dict(name="Darshan Patil", email="darshan.patil@scms.local", role="committee_member", class_name="SE", branch="ENCE", portfolio="Student Welfare"),
    dict(name="Vishal Aswar", email="vishal.aswar@scms.local", role="committee_member", class_name="SE", branch="E&TC", portfolio="Student Welfare"),
    dict(name="Sankashti Jagdambe", email="sankashti.jagdambe@scms.local", role="committee_member", class_name="SE", branch="E&TC", portfolio="Student Welfare"),
    dict(name="Anil Rathod", email="anil.rathod@scms.local", role="committee_member", class_name="SE", branch="COMP", portfolio="Student Welfare"),
    dict(name="Payal Pimple", email="payal.pimple@scms.local", role="committee_member", class_name="SE", branch="AIML", portfolio="Women's Representative"),
    dict(name="Pratidnya Talekar", email="pratidnya.talekar@scms.local", role="committee_member", class_name="TE", branch="E&TC", portfolio="Women's Representative"),
    dict(name="Rutuja Bhaval", email="rutuja.bhaval@scms.local", role="committee_member", class_name="SE", branch="AIDS", portfolio="Women's Representative"),
    dict(name="Aishwarya Bhosale", email="aishwarya.bhosale@scms.local", role="committee_member", class_name="SE", branch="IT", portfolio="Women's Representative"),
    dict(name="Ruksana Khan", email="ruksana.khan@scms.local", role="committee_member", class_name="SE", branch="COMP", portfolio="Training & Placement"),
    dict(name="Shruti Supekar", email="shruti.supekar@scms.local", role="committee_member", class_name="TE", branch="Comp", portfolio="Training & Placement"),
    dict(name="Ganesh Harel", email="ganesh.harel@scms.local", role="committee_member", class_name="TE", branch="IOT", portfolio="Training & Placement"),
    dict(name="Pranali Ghogare", email="pranali.ghogare@scms.local", role="committee_member", class_name="SE", branch="AIML", portfolio="Training & Placement"),
    dict(name="Kaushik Gunkar", email="kaushik.gunkar@scms.local", role="committee_member", class_name="TE", branch="AIDS", portfolio="Training & Placement"),
    dict(name="Snehal Aade", email="snehal.aade@scms.local", role="committee_member", class_name="SE", branch="IT", portfolio="Training & Placement"),
]

TEAMS = [
    dict(
        slug="cultural", name="Cultural Team", lead_name="Aryan Pentewar",
        lead_role="cultural_secretary", faculty_name="Rushikesh More",
        faculty_portfolio="First Year Department", description="Cultural events, celebrations, stage programmes and student engagement.",
    ),
    dict(
        slug="sports", name="Sports Team", lead_name="Prachi Dinkar",
        lead_role="sports_secretary", faculty_name="Gopinath Kalokhe",
        faculty_portfolio="Sports Department", description="Sports tournaments, player coordination, practices and athletics.",
    ),
    dict(
        slug="technical", name="Technical Team", lead_name="Samiksha Harap",
        lead_role="technical_secretary", faculty_name="Swati Deshmukh",
        faculty_portfolio="Electronics & Tele-Communication Engineering", description="Technical events, innovation, hackathons, workshops and technology initiatives.",
    ),
    dict(
        slug="social-responsibility", name="Social Responsibility Team", lead_name="Anzar Sayyad",
        lead_role="social_responsibility_secretary", faculty_name="Mayur Kadam",
        faculty_portfolio="Diploma Mechanical Department", description="Community service, outreach, awareness drives and social initiatives.",
    ),
    dict(
        slug="pr-media", name="PR & Media Team", lead_name="Karishma Savalekar",
        lead_role="pr_media_secretary", faculty_name="Shreyash Ghanvat",
        faculty_portfolio="Civil Engineering Department", description="Public relations, media, social channels, posters, coverage and communications.",
    ),
    dict(
        slug="student-welfare", name="Student Welfare Team", lead_name="Aryan Shirpute",
        lead_role="student_welfare_representative", faculty_name="Rajesh Mahamuni",
        faculty_portfolio="Computer Engineering Department", description="Student concerns, support systems, grievance handling and welfare programmes.",
    ),
    dict(
        slug="womens", name="Women's Representative Team", lead_name="Likhitha Teppda",
        lead_role="womens_representative", faculty_name="Vaibhav Munde",
        faculty_portfolio="Mechanical Engineering Department", description="Women's representation, inclusion, support and student initiatives.",
    ),
    dict(
        slug="training-placement", name="Training & Placement Team", lead_name="Bhavesh Mahajan",
        lead_role="placement_training_representative", faculty_name="Richa Nighote",
        faculty_portfolio="TNP Department", description="Training, placements, career programmes and employability activities.",
    ),
]

EXECUTIVE_TEAM_MEMBERS = ["Aachal Baviskar", "Sandhya Kolpe"]


# ============================================================
# APP + DB
# ============================================================

app = FastAPI(
    title=APP_TITLE,
    description="Full Student Council operations platform for AY 2026-27.",
    version=APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hp(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PostgresCursorCompat:
    """Small SQLite-like cursor adapter so the existing SCMS API can run on Supabase Postgres."""
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        self._cursor.execute(sql, params or ())
        if sql.lstrip().lower().startswith("insert into "):
            m = re.search(r"insert\s+into\s+([a-zA-Z_][\w]*)", sql, re.I)
            if m:
                try:
                    self._cursor.execute(
                        "select currval(pg_get_serial_sequence(%s, 'id')) as id",
                        (m.group(1),),
                    )
                    row = self._cursor.fetchone()
                    self.lastrowid = row["id"] if row else None
                except Exception:
                    self._cursor.connection.rollback()
                    # The INSERT may already be committed only after the caller's commit;
                    # reset the cursor state and let the caller continue.
                    self.lastrowid = None
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        self._cursor.close()


class PostgresConnectionCompat:
    def __init__(self, url):
        if psycopg2 is None:
            raise RuntimeError("psycopg2-binary is required when DATABASE_URL is set.")
        self._conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
        self._conn.autocommit = False

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        return PostgresCursorCompat(cur).execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_db():
    if DATABASE_URL:
        return PostgresConnectionCompat(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def execute_script(conn: sqlite3.Connection, sql: str) -> None:
    conn.executescript(sql)


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# ============================================================
# DATABASE INITIALIZATION / MIGRATION
# ============================================================

@app.on_event("startup")
def startup() -> None:
    # Supabase Postgres is provisioned separately through the project migration.
    # Skip the SQLite schema/seed routine when DATABASE_URL is configured.
    if DATABASE_URL:
        conn = get_db()
        conn.close()
        return

    conn = get_db()

    execute_script(conn, """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,
        portfolio TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        class_name TEXT DEFAULT '',
        branch TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        lead_user_id INTEGER,
        faculty_coordinator_id INTEGER,
        description TEXT DEFAULT '',
        source_page INTEGER,
        source_note TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(lead_user_id) REFERENCES users(id),
        FOREIGN KEY(faculty_coordinator_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS team_budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL UNIQUE,
        fiscal_year TEXT DEFAULT '2026-27',
        allocated_amount REAL DEFAULT 0,
        notes TEXT DEFAULT '',
        updated_by INTEGER,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
        FOREIGN KEY(updated_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS budget_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        amount REAL NOT NULL,
        transaction_type TEXT DEFAULT 'Expense',
        status TEXT DEFAULT 'Approved',
        reference TEXT DEFAULT '',
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS team_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        position TEXT DEFAULT 'Committee Member',
        is_lead INTEGER DEFAULT 0,
        joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(team_id, user_id),
        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        priority TEXT DEFAULT 'Medium',
        category TEXT DEFAULT 'General',
        assigned_to INTEGER,
        assigned_by INTEGER,
        team_id INTEGER,
        status TEXT DEFAULT 'Pending',
        due_date TEXT DEFAULT '',
        due_time TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        comments TEXT DEFAULT '',
        FOREIGN KEY(assigned_to) REFERENCES users(id),
        FOREIGN KEY(assigned_by) REFERENCES users(id),
        FOREIGN KEY(team_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        date TEXT NOT NULL,
        start_time TEXT DEFAULT '',
        end_time TEXT DEFAULT '',
        location TEXT DEFAULT '',
        event_type TEXT DEFAULT 'General',
        priority TEXT DEFAULT 'Normal',
        description TEXT DEFAULT '',
        organizer TEXT DEFAULT '',
        capacity INTEGER DEFAULT 0,
        team_id INTEGER,
        status TEXT DEFAULT 'Proposed',
        budget_allocated REAL DEFAULT 0,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT DEFAULT '',
        location TEXT DEFAULT '',
        meeting_type TEXT DEFAULT 'Regular',
        agenda TEXT DEFAULT '',
        minutes TEXT DEFAULT '',
        action_items TEXT DEFAULT '',
        team_id INTEGER,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS finances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        amount REAL NOT NULL,
        type TEXT DEFAULT 'Operations',
        priority TEXT DEFAULT 'Normal',
        status TEXT DEFAULT 'Pending',
        requested_by INTEGER,
        approved_by INTEGER,
        team_id INTEGER,
        vendor TEXT DEFAULT '',
        justification TEXT DEFAULT '',
        receipt_url TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(requested_by) REFERENCES users(id),
        FOREIGN KEY(approved_by) REFERENCES users(id),
        FOREIGN KEY(team_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS grievances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        description TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        department TEXT DEFAULT '',
        contact_preference TEXT DEFAULT 'Portal notification',
        is_anonymous INTEGER DEFAULT 0,
        follow_up_allowed INTEGER DEFAULT 1,
        priority TEXT DEFAULT 'Normal',
        status TEXT DEFAULT 'Open',
        created_by INTEGER,
        assigned_to INTEGER,
        resolution_notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(created_by) REFERENCES users(id),
        FOREIGN KEY(assigned_to) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        audience TEXT DEFAULT 'Council',
        team_id INTEGER,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        owner_id INTEGER,
        target_date TEXT DEFAULT '',
        status TEXT DEFAULT 'Planned',
        progress INTEGER DEFAULT 0,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(owner_id) REFERENCES users(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        file_url TEXT NOT NULL,
        document_type TEXT DEFAULT 'Reference',
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        approval_type TEXT DEFAULT 'General',
        requested_by INTEGER,
        reviewed_by INTEGER,
        status TEXT DEFAULT 'Pending',
        review_notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(requested_by) REFERENCES users(id),
        FOREIGN KEY(reviewed_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        kind TEXT DEFAULT 'info',
        is_read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id INTEGER,
        details TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(actor_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS council_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)

    # Migrate older SCMS v3 DBs in place.
    migrations = {
        "users": [
            ("class_name", "TEXT DEFAULT ''"),
            ("branch", "TEXT DEFAULT ''"),
            ("created_at", "TEXT"),
        ],
        "tasks": [
            ("category", "TEXT DEFAULT 'General'"),
            ("team_id", "INTEGER"),
            ("due_time", "TEXT DEFAULT ''"),
            ("updated_at", "TEXT"),
        ],
        "events": [
            ("start_time", "TEXT DEFAULT ''"),
            ("end_time", "TEXT DEFAULT ''"),
            ("event_type", "TEXT DEFAULT 'General'"),
            ("priority", "TEXT DEFAULT 'Normal'"),
            ("organizer", "TEXT DEFAULT ''"),
            ("capacity", "INTEGER DEFAULT 0"),
            ("team_id", "INTEGER"),
            ("created_by", "INTEGER"),
            ("created_at", "TEXT"),
        ],
        "meetings": [
            ("time", "TEXT DEFAULT ''"),
            ("location", "TEXT DEFAULT ''"),
            ("meeting_type", "TEXT DEFAULT 'Regular'"),
            ("team_id", "INTEGER"),
            ("created_at", "TEXT"),
        ],
        "finances": [
            ("priority", "TEXT DEFAULT 'Normal'"),
            ("team_id", "INTEGER"),
            ("vendor", "TEXT DEFAULT ''"),
            ("justification", "TEXT DEFAULT ''"),
            ("updated_at", "TEXT"),
        ],
        "grievances": [
            ("category", "TEXT DEFAULT 'General'"),
            ("department", "TEXT DEFAULT ''"),
            ("contact_preference", "TEXT DEFAULT 'Portal notification'"),
            ("follow_up_allowed", "INTEGER DEFAULT 1"),
            ("assigned_to", "INTEGER"),
            ("updated_at", "TEXT"),
        ],
        "announcements": [
            ("audience", "TEXT DEFAULT 'Council'"),
            ("team_id", "INTEGER"),
        ],
    }
    for table, cols in migrations.items():
        for col, definition in cols:
            add_column_if_missing(conn, table, col, definition)

    conn.execute("""
        INSERT OR REPLACE INTO council_meta(key,value)
        VALUES ('council_year','2026-27')
    """)
    conn.execute("""
        INSERT OR REPLACE INTO council_meta(key,value)
        VALUES ('selection_report_date','2026-08-21')
    """)
    conn.execute("""
        INSERT OR REPLACE INTO council_meta(key,value)
        VALUES ('selection_report_url','/documents/Student_Council_2026-27_Selection_Report.pdf')
    """)

    # Seed users and upgrade passwords/metadata only when missing.
    for person in OFFICIAL_COUNCIL:
        existing = conn.execute(
            "SELECT id FROM users WHERE email=?",
            (person["email"],),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE users SET name=?, role=?, portfolio=?, class_name=?, branch=?, is_active=1
                WHERE id=?
                """,
                (
                    person["name"],
                    person["role"],
                    person.get("portfolio", ""),
                    person.get("class_name", ""),
                    person.get("branch", ""),
                    existing["id"],
                ),
            )
        else:
            default_password = "admin123" if person["role"] == "faculty_coordinator" else "student123"
            conn.execute(
                """
                INSERT INTO users(name,email,password,role,portfolio,class_name,branch,is_active,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    person["name"],
                    person["email"],
                    hp(default_password),
                    person["role"],
                    person.get("portfolio", ""),
                    person.get("class_name", ""),
                    person.get("branch", ""),
                    1,
                    now_iso(),
                ),
            )

    conn.commit()

    # Team creation and membership.
    for team in TEAMS:
        lead = conn.execute(
            "SELECT id FROM users WHERE name=? AND is_active=1 ORDER BY id LIMIT 1",
            (team["lead_name"],),
        ).fetchone()
        faculty = conn.execute(
            "SELECT id FROM users WHERE name=? AND role='faculty_coordinator' LIMIT 1",
            (team["faculty_name"],),
        ).fetchone()
        if not lead:
            continue

        conn.execute("""
            INSERT INTO teams(slug,name,lead_user_id,faculty_coordinator_id,description,source_page,source_note)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name,
                lead_user_id=excluded.lead_user_id,
                faculty_coordinator_id=excluded.faculty_coordinator_id,
                description=excluded.description,
                source_page=excluded.source_page,
                source_note=excluded.source_note
        """, (
            team["slug"],
            team["name"],
            lead["id"],
            faculty["id"] if faculty else None,
            team["description"],
            1,
            "Official Student Council Selection Committee Report dated 21/08/2026.",
        ))

        team_row = conn.execute(
            "SELECT id FROM teams WHERE slug=?",
            (team["slug"],),
        ).fetchone()
        team_id = team_row["id"]

        conn.execute("""
            INSERT OR IGNORE INTO team_members(team_id,user_id,position,is_lead)
            VALUES(?,?,?,?)
        """, (team_id, lead["id"], ROLES.get(team["lead_role"], team["lead_role"]), 1))

        if faculty:
            conn.execute("""
                INSERT OR IGNORE INTO team_members(team_id,user_id,position,is_lead)
                VALUES(?,?,?,?)
            """, (team_id, faculty["id"], "Faculty Coordinator", 0))

        for person in OFFICIAL_COUNCIL:
            if person.get("portfolio") == team["name"].replace(" Team", "") and person["role"] == "committee_member":
                member = conn.execute(
                    "SELECT id FROM users WHERE email=?",
                    (person["email"],),
                ).fetchone()
                if member:
                    conn.execute("""
                        INSERT OR IGNORE INTO team_members(team_id,user_id,position,is_lead)
                        VALUES(?,?,?,?)
                    """, (team_id, member["id"], "Committee Member", 0))

    # Executive committee team.
    conn.execute("""
        INSERT OR IGNORE INTO teams(
            slug,name,description,source_page,source_note
        ) VALUES(?,?,?,?,?)
    """, (
        "executive-council",
        "Executive Council",
        "President, Vice President, General Secretary, Joint Secretaries, Treasurer and executive committee members.",
        1,
        "Official Student Council Selection Committee Report dated 21/08/2026.",
    ))
    executive_team = conn.execute(
        "SELECT id FROM teams WHERE slug='executive-council'"
    ).fetchone()["id"]
    for person_name in [
        "Rupali Tagunde", "Purnima Patra", "Kiran Prasad", "Kajal Bodke",
        "Vedant Aware", "Tushar Gawali", *EXECUTIVE_TEAM_MEMBERS
    ]:
        person = conn.execute(
            "SELECT id, role FROM users WHERE name=? LIMIT 1",
            (person_name,),
        ).fetchone()
        if person:
            conn.execute("""
                INSERT OR IGNORE INTO team_members(team_id,user_id,position,is_lead)
                VALUES(?,?,?,?)
            """, (
                executive_team,
                person["id"],
                ROLES.get(person["role"], "Executive Council Member"),
                1 if person["role"] in {"president", "vice_president", "general_secretary"} else 0,
            ))

    # Ensure every official team has an independent budget ledger.
    for team_row in conn.execute("SELECT id FROM teams").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO team_budgets(team_id,fiscal_year,allocated_amount,notes,updated_at) VALUES(?,?,?,?,?)",
            (team_row["id"], "2026-27", 0.0, "Set the annual allocation from the Finance/Executive workspace.", now_iso()),
        )

    # Reference document record.
    if COUNCIL_PDF.exists():
        exists = conn.execute(
            "SELECT id FROM documents WHERE title=? AND file_url=?",
            ("Official Student Council 2026-27 Selection Report", "/documents/Student_Council_2026-27_Selection_Report.pdf"),
        ).fetchone()
        if not exists:
            conn.execute("""
                INSERT INTO documents(title,description,file_url,document_type,created_at)
                VALUES(?,?,?,?,?)
            """, (
                "Official Student Council 2026-27 Selection Report",
                "Selection Committee Report dated 21/08/2026.",
                "/documents/Student_Council_2026-27_Selection_Report.pdf",
                "Official Reference",
                now_iso(),
            ))

    # Initial announcement.
    if not conn.execute("SELECT 1 FROM announcements LIMIT 1").fetchone():
        president = conn.execute(
            "SELECT id FROM users WHERE email='rupali.tagunde@scms.local'"
        ).fetchone()
        conn.execute("""
            INSERT INTO announcements(title,content,audience,created_by,created_at)
            VALUES(?,?,?,?,?)
        """, (
            "Student Council 2026-27 is Live",
            "The Student Council Management System is now connected to the official 21/08/2026 council selection report.",
            "Council",
            president["id"] if president else None,
            now_iso(),
        ))

    conn.commit()
    conn.close()


# ============================================================
# AUTH + RBAC
# ============================================================

def auth(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token.")

    token = authorization.removeprefix("Bearer ").strip()
    user_id = sessions.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

    conn = get_db()
    row = conn.execute("""
        SELECT id,name,email,role,portfolio,phone,class_name,branch,is_active
        FROM users
        WHERE id=? AND is_active=1
    """, (user_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="User account is inactive.")

    user = dict(row)
    user["role_name"] = ROLES.get(user["role"], user["role"])
    return user


def require_roles(*allowed_roles: str):
    def checker(user: dict[str, Any] = Depends(auth)):
        if user["role"] not in set(allowed_roles) and user["role"] != "faculty_coordinator":
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}",
            )
        return user
    return checker


def write_audit(
    actor_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    details: str = "",
) -> None:
    conn = get_db()
    conn.execute("""
        INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,details,created_at)
        VALUES(?,?,?,?,?,?)
    """, (actor_id, action, entity_type, entity_id, details, now_iso()))
    conn.commit()
    conn.close()


def send_notification(user_id: int, title: str, message: str, kind: str = "info") -> None:
    conn = get_db()
    conn.execute("""
        INSERT INTO notifications(user_id,title,message,kind,created_at)
        VALUES(?,?,?,?,?)
    """, (user_id, title, message, kind, now_iso()))
    conn.commit()
    conn.close()


# ============================================================
# PYDANTIC MODELS
# ============================================================

class LoginReq(BaseModel):
    email: str
    password: str


class PasswordUpdate(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class TaskReq(BaseModel):
    title: str
    description: str = ""
    priority: str = "Medium"
    category: str = "General"
    assigned_to: int
    team_id: Optional[int] = None
    due_date: str = ""
    due_time: str = ""


class StatusUpdate(BaseModel):
    status: str
    extra_notes: str = ""


class EventReq(BaseModel):
    title: str
    date: str
    start_time: str = ""
    end_time: str = ""
    location: str = ""
    event_type: str = "General"
    priority: str = "Normal"
    description: str = ""
    organizer: str = ""
    capacity: int = 0
    team_id: Optional[int] = None
    budget_allocated: float = 0.0


class MeetingReq(BaseModel):
    title: str
    date: str
    time: str = ""
    location: str = ""
    meeting_type: str = "Regular"
    agenda: str = ""
    team_id: Optional[int] = None


class FinanceReq(BaseModel):
    title: str
    amount: float = Field(gt=0)
    type: str = "Operations"
    priority: str = "Normal"
    team_id: Optional[int] = None
    vendor: str = ""
    justification: str = ""
    receipt_url: str = ""


class GrievanceReq(BaseModel):
    subject: str
    description: str
    category: str = "General"
    department: str = ""
    contact_preference: str = "Portal notification"
    is_anonymous: bool = False
    follow_up_allowed: bool = True
    priority: str = "Normal"


class AnnouncementReq(BaseModel):
    title: str
    content: str
    audience: str = "Council"
    team_id: Optional[int] = None


class GoalReq(BaseModel):
    team_id: int
    title: str
    description: str = ""
    owner_id: Optional[int] = None
    target_date: str = ""


class GoalProgressReq(BaseModel):
    progress: int = Field(ge=0, le=100)
    status: str = "In Progress"


class DocumentReq(BaseModel):
    team_id: Optional[int] = None
    title: str
    description: str = ""
    file_url: str
    document_type: str = "Reference"


class ApprovalReq(BaseModel):
    team_id: Optional[int] = None
    title: str
    description: str = ""
    approval_type: str = "General"


class ApprovalDecision(BaseModel):
    status: str
    review_notes: str = ""


class TeamBudgetUpdate(BaseModel):
    allocated_amount: float = Field(ge=0)
    fiscal_year: str = "2026-27"
    notes: Optional[str] = ""


class BudgetTransactionReq(BaseModel):
    title: str
    amount: float = Field(gt=0)
    transaction_type: str = "Expense"
    status: str = "Approved"
    reference: Optional[str] = ""


# ============================================================
# HEALTH / FRONTEND / OFFICIAL DOCUMENT
# ============================================================

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": APP_TITLE,
        "version": APP_VERSION,
        "council_year": "2026-27",
        "selection_report_date": "2026-08-21",
        "pdf_available": COUNCIL_PDF.exists(),
    }


@app.get("/api/council-source")
def council_source(_: dict = Depends(auth)) -> dict[str, Any]:
    return {
        "title": "Official Student Council 2026-27 Selection Committee Report",
        "date": "21/08/2026",
        "url": "/documents/Student_Council_2026-27_Selection_Report.pdf",
        "available": COUNCIL_PDF.exists(),
        "description": "Official reference used to seed council roles and team structure.",
    }


if COUNCIL_PDF.exists():
    app.mount("/documents", StaticFiles(directory=str(DOCUMENTS_DIR)), name="documents")


@app.get("/api/council-pdf")
def council_pdf() -> FileResponse:
    if not COUNCIL_PDF.exists():
        raise HTTPException(
            status_code=404,
            detail="Council PDF not found. Put the report in ./documents/Student_Council_2026-27_Selection_Report.pdf",
        )
    return FileResponse(
        COUNCIL_PDF,
        media_type="application/pdf",
        filename="Student_Council_2026-27_Selection_Report.pdf",
    )


# ============================================================
# AUTH ROUTES
# ============================================================

@app.post("/api/login")
def login(payload: LoginReq):
    conn = get_db()
    row = conn.execute("""
        SELECT id,name,email,role,portfolio,class_name,branch,is_active
        FROM users
        WHERE email=? AND password=?
    """, (payload.email.strip().lower(), hp(payload.password))).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Account is disabled.")

    token = secrets.token_urlsafe(32)
    sessions[token] = row["id"]
    user = dict(row)
    user["role_name"] = ROLES.get(user["role"], user["role"])

    write_audit(user["id"], "login", "auth", user["id"])
    return {"token": token, "user": user}


@app.post("/api/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    user_id = sessions.pop(token, None)
    if user_id:
        write_audit(user_id, "logout", "auth", user_id)
    return {"message": "Logged out successfully."}


@app.get("/api/me")
def me(user: dict = Depends(auth)):
    return user


@app.patch("/api/me/password")
def update_password(payload: PasswordUpdate, user: dict = Depends(auth)):
    conn = get_db()
    valid = conn.execute(
        "SELECT 1 FROM users WHERE id=? AND password=?",
        (user["id"], hp(payload.old_password)),
    ).fetchone()
    if not valid:
        conn.close()
        raise HTTPException(status_code=400, detail="Old password incorrect.")
    conn.execute(
        "UPDATE users SET password=? WHERE id=?",
        (hp(payload.new_password), user["id"]),
    )
    conn.commit()
    conn.close()
    write_audit(user["id"], "password_change", "user", user["id"])
    return {"message": "Password updated successfully."}


# ============================================================
# DASHBOARD
# ============================================================

@app.get("/api/stats")
def dashboard_stats(user: dict = Depends(auth)):
    conn = get_db()

    if user["role"] in EXECUTIVE_ROLES:
        task_where = ""
        task_args: tuple[Any, ...] = ()
    else:
        task_where = "WHERE t.assigned_to=? OR t.assigned_by=?"
        task_args = (user["id"], user["id"])

    task_rows = conn.execute(
        f"SELECT t.status,t.priority FROM tasks t {task_where}",
        task_args,
    ).fetchall()

    stats = {
        "total_tasks": len(task_rows),
        "pending_tasks": sum(1 for r in task_rows if r["status"] == "Pending"),
        "in_progress_tasks": sum(1 for r in task_rows if r["status"] == "In Progress"),
        "completed_tasks": sum(1 for r in task_rows if r["status"] == "Completed"),
        "overdue_tasks": 0,
        "active_events": conn.execute(
            "SELECT COUNT(*) FROM events WHERE status != 'Completed'"
        ).fetchone()[0],
        "upcoming_events": conn.execute(
            "SELECT COUNT(*) FROM events WHERE date >= date('now')"
        ).fetchone()[0],
        "open_grievances": conn.execute(
            "SELECT COUNT(*) FROM grievances WHERE status='Open'"
        ).fetchone()[0],
        "pending_approvals": conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE status='Pending'"
        ).fetchone()[0],
        "total_members": conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_active=1"
        ).fetchone()[0],
        "total_teams": conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0],
        "unread_notifications": conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
            (user["id"],),
        ).fetchone()[0],
    }

    # Overdue task calculation stays Python-side for SQLite portability.
    today = date.today().isoformat()
    stats["overdue_tasks"] = conn.execute(
        f"""
        SELECT COUNT(*) FROM tasks t
        WHERE t.due_date <> ''
          AND t.due_date < ?
          AND t.status != 'Completed'
          AND {("(t.assigned_to=? OR t.assigned_by=?)" if task_args else "1=1")}
        """,
        ((today, user["id"], user["id"]) if task_args else (today,)),
    ).fetchone()[0]

    conn.close()
    return stats


# ============================================================
# DIRECTORY
# ============================================================

@app.get("/api/users")
def users_directory(
    q: str = Query(default=""),
    role: str = Query(default=""),
    team_id: Optional[int] = Query(default=None),
    user: dict = Depends(auth),
):
    conn = get_db()
    sql = """
        SELECT DISTINCT u.id,u.name,u.email,u.role,u.portfolio,
               u.class_name,u.branch,u.phone,u.is_active
        FROM users u
        LEFT JOIN team_members tm ON tm.user_id=u.id
        WHERE u.is_active=1
    """
    args: list[Any] = []

    if q:
        sql += " AND (u.name LIKE ? OR u.email LIKE ? OR u.portfolio LIKE ?)"
        like = f"%{q}%"
        args.extend([like, like, like])

    if role:
        sql += " AND u.role=?"
        args.append(role)

    if team_id:
        sql += " AND tm.team_id=?"
        args.append(team_id)

    sql += " ORDER BY CASE u.role WHEN 'president' THEN 1 WHEN 'vice_president' THEN 2 WHEN 'general_secretary' THEN 3 WHEN 'joint_secretary' THEN 4 ELSE 20 END, u.name"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# TEAM WORKSPACES
# ============================================================

def team_access(conn: sqlite3.Connection, team_id: int, user: dict[str, Any]) -> bool:
    if user["role"] == "faculty_coordinator" or user["role"] in EXECUTIVE_ROLES:
        return True
    row = conn.execute(
        "SELECT 1 FROM team_members WHERE team_id=? AND user_id=?",
        (team_id, user["id"]),
    ).fetchone()
    return bool(row)


@app.get("/api/teams")
def list_teams(user: dict = Depends(auth)):
    conn = get_db()
    rows = conn.execute("""
        SELECT t.id,t.slug,t.name,t.description,t.source_page,
               t.lead_user_id,t.faculty_coordinator_id,
               lead.name AS lead_name,
               faculty.name AS faculty_name,
               COUNT(tm.id) AS member_count
        FROM teams t
        LEFT JOIN users lead ON lead.id=t.lead_user_id
        LEFT JOIN users faculty ON faculty.id=t.faculty_coordinator_id
        LEFT JOIN team_members tm ON tm.team_id=t.id
        GROUP BY t.id
        ORDER BY CASE WHEN t.slug='executive-council' THEN 0 ELSE 1 END,t.name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/teams/{team_id}")
def get_team(team_id: int, user: dict = Depends(auth)):
    conn = get_db()
    team = conn.execute("""
        SELECT t.*, lead.name AS lead_name, lead.email AS lead_email,
               faculty.name AS faculty_name, faculty.email AS faculty_email
        FROM teams t
        LEFT JOIN users lead ON lead.id=t.lead_user_id
        LEFT JOIN users faculty ON faculty.id=t.faculty_coordinator_id
        WHERE t.id=?
    """, (team_id,)).fetchone()
    if not team:
        conn.close()
        raise HTTPException(status_code=404, detail="Team not found.")

    members = conn.execute("""
        SELECT u.id,u.name,u.email,u.role,u.portfolio,u.class_name,u.branch,
               tm.position,tm.is_lead
        FROM team_members tm
        JOIN users u ON u.id=tm.user_id
        WHERE tm.team_id=?
        ORDER BY tm.is_lead DESC,u.name
    """, (team_id,)).fetchall()

    team_dict = dict(team)
    team_dict["members"] = [dict(r) for r in members]
    team_dict["member_count"] = len(members)

    conn.close()
    return team_dict


@app.get("/api/teams/{team_id}/dashboard")
def team_dashboard(team_id: int, user: dict = Depends(auth)):
    conn = get_db()
    team = conn.execute("SELECT id,name,lead_user_id,faculty_coordinator_id FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        conn.close(); raise HTTPException(status_code=404, detail="Team not found.")
    if not team_access(conn, team_id, user):
        conn.close(); raise HTTPException(status_code=403, detail="You do not have access to this team workspace.")

    budget = conn.execute("""
        SELECT COALESCE(tb.allocated_amount,0) AS allocated_amount,
               COALESCE((SELECT SUM(bt.amount) FROM budget_transactions bt WHERE bt.team_id=tb.team_id AND bt.status='Approved'),0) AS ledger_used,
               COALESCE((SELECT SUM(f.amount) FROM finances f WHERE f.team_id=tb.team_id AND f.status='Approved'),0) AS approved_finance_used,
               COALESCE((SELECT SUM(f.amount) FROM finances f WHERE f.team_id=tb.team_id AND f.status='Pending'),0) AS pending_requests,
               tb.fiscal_year,tb.notes,tb.updated_at
        FROM team_budgets tb WHERE tb.team_id=?
    """, (team_id,)).fetchone()
    if budget:
        allocated=float(budget["allocated_amount"] or 0)
        used=float(budget["ledger_used"] or 0)+float(budget["approved_finance_used"] or 0)
        pending=float(budget["pending_requests"] or 0)
        remaining=allocated-used
        utilization=round((used/allocated*100),1) if allocated else 0
        budget_dict={"allocated":allocated,"used":used,"remaining":remaining,"pending_requests":pending,"utilization":utilization,"fiscal_year":budget["fiscal_year"],"notes":budget["notes"],"updated_at":budget["updated_at"]}
    else:
        budget_dict={"allocated":0,"used":0,"remaining":0,"pending_requests":0,"utilization":0,"fiscal_year":"2026-27","notes":"","updated_at":None}

    counts={
        "members": conn.execute("SELECT COUNT(*) FROM team_members WHERE team_id=?", (team_id,)).fetchone()[0],
        "open_tasks": conn.execute("SELECT COUNT(*) FROM tasks WHERE team_id=? AND status!='Completed'", (team_id,)).fetchone()[0],
        "completed_tasks": conn.execute("SELECT COUNT(*) FROM tasks WHERE team_id=? AND status='Completed'", (team_id,)).fetchone()[0],
        "events": conn.execute("SELECT COUNT(*) FROM events WHERE team_id=? AND status!='Completed'", (team_id,)).fetchone()[0],
        "meetings": conn.execute("SELECT COUNT(*) FROM meetings WHERE team_id=?", (team_id,)).fetchone()[0],
        "goals": conn.execute("SELECT COUNT(*) FROM goals WHERE team_id=?", (team_id,)).fetchone()[0],
        "pending_approvals": conn.execute("SELECT COUNT(*) FROM approvals WHERE team_id=? AND status='Pending'", (team_id,)).fetchone()[0],
        "announcements": conn.execute("SELECT COUNT(*) FROM announcements WHERE team_id=?", (team_id,)).fetchone()[0],
    }
    conn.close()
    return {"team":dict(team),"budget":budget_dict,"counts":counts}

@app.patch("/api/teams/{team_id}/budget")
def update_team_budget(team_id: int, payload: TeamBudgetUpdate = Body(...), user: dict = Depends(require_roles(
    "president","vice_president","general_secretary","joint_secretary","treasurer","faculty_coordinator"
))):
    conn=get_db()
    if not conn.execute("SELECT 1 FROM teams WHERE id=?",(team_id,)).fetchone():
        conn.close(); raise HTTPException(status_code=404, detail="Team not found.")
    conn.execute("""
        INSERT INTO team_budgets(team_id,fiscal_year,allocated_amount,notes,updated_by,updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(team_id) DO UPDATE SET
          fiscal_year=excluded.fiscal_year,
          allocated_amount=excluded.allocated_amount,
          notes=excluded.notes,
          updated_by=excluded.updated_by,
          updated_at=excluded.updated_at
    """,(team_id,payload.fiscal_year,payload.allocated_amount,payload.notes,user["id"],now_iso()))
    conn.commit(); conn.close()
    write_audit(user["id"],"update","team_budget",team_id,f"Allocated ₹{payload.allocated_amount:,.2f} for FY {payload.fiscal_year}")
    return {"message":"Team budget updated","allocated_amount":payload.allocated_amount,"fiscal_year":payload.fiscal_year}

@app.post("/api/teams/{team_id}/budget/transactions")
def create_budget_transaction(team_id:int,payload:BudgetTransactionReq=Body(...),user:dict=Depends(auth)):
    conn=get_db()
    if not conn.execute("SELECT 1 FROM teams WHERE id=?",(team_id,)).fetchone():
        conn.close(); raise HTTPException(status_code=404, detail="Team not found.")
    if not team_access(conn,team_id,user):
        conn.close(); raise HTTPException(status_code=403, detail="You do not have access to this team budget.")
    if user["role"] not in EXECUTIVE_ROLES and user["role"] not in {"treasurer","faculty_coordinator"}:
        lead=conn.execute("SELECT lead_user_id FROM teams WHERE id=?",(team_id,)).fetchone()
        if not lead or lead["lead_user_id"]!=user["id"]:
            conn.close(); raise HTTPException(status_code=403, detail="Only the team lead or authorized finance roles can record an expense.")
    budget=conn.execute("SELECT allocated_amount FROM team_budgets WHERE team_id=?",(team_id,)).fetchone()
    allocated=float(budget["allocated_amount"] if budget else 0)
    used=float(conn.execute("SELECT COALESCE(SUM(amount),0) FROM budget_transactions WHERE team_id=? AND status='Approved'",(team_id,)).fetchone()[0])
    approved_fin=float(conn.execute("SELECT COALESCE(SUM(amount),0) FROM finances WHERE team_id=? AND status='Approved'",(team_id,)).fetchone()[0])
    if payload.status=="Approved" and used+approved_fin+payload.amount>allocated and allocated>0:
        conn.close(); raise HTTPException(status_code=400, detail="Expense exceeds the allocated team budget.")
    conn.execute("INSERT INTO budget_transactions(team_id,title,amount,transaction_type,status,reference,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",(team_id,payload.title,payload.amount,payload.transaction_type,payload.status,payload.reference,user["id"],now_iso()))
    conn.commit(); conn.close()
    write_audit(user["id"],"create","budget_transaction",None,payload.title)
    return {"message":"Budget transaction recorded"}

@app.get("/api/teams/{team_id}/budget/transactions")
def get_budget_transactions(team_id:int,user:dict=Depends(auth)):
    conn=get_db()
    if not team_access(conn,team_id,user):
        conn.close(); raise HTTPException(status_code=403, detail="You do not have access to this team budget.")
    rows=conn.execute("SELECT bt.*,u.name as created_by_name FROM budget_transactions bt LEFT JOIN users u ON u.id=bt.created_by WHERE bt.team_id=? ORDER BY bt.id DESC",(team_id,)).fetchall()
    conn.close(); return [dict(r) for r in rows]

@app.get("/api/my-team")
def get_my_team(user: dict = Depends(auth)):
    conn = get_db()
    row = conn.execute("""
        SELECT t.id
        FROM teams t
        JOIN team_members tm ON tm.team_id=t.id
        WHERE tm.user_id=?
        ORDER BY CASE WHEN t.slug='executive-council' THEN 0 ELSE 1 END
        LIMIT 1
    """, (user["id"],)).fetchone()
    conn.close()

    if not row:
        return None

    return get_team(row["id"], user)


@app.post("/api/teams/{team_id}/members/{user_id}")
def add_team_member(team_id: int, user_id: int, user: dict = Depends(require_roles(
    "president", "vice_president", "general_secretary", "joint_secretary", "faculty_coordinator"
))):
    conn = get_db()
    if not conn.execute("SELECT 1 FROM teams WHERE id=?", (team_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Team not found.")
    if not conn.execute("SELECT 1 FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")
    conn.execute("""
        INSERT OR IGNORE INTO team_members(team_id,user_id,position,is_lead)
        VALUES(?,?,?,0)
    """, (team_id, user_id, "Committee Member"))
    conn.commit()
    conn.close()
    write_audit(user["id"], "add_member", "team", team_id, f"user={user_id}")
    return {"message": "Member added to team."}


@app.delete("/api/teams/{team_id}/members/{user_id}")
def remove_team_member(team_id: int, user_id: int, user: dict = Depends(require_roles(
    "president", "general_secretary", "joint_secretary", "faculty_coordinator"
))):
    conn = get_db()
    conn.execute(
        "DELETE FROM team_members WHERE team_id=? AND user_id=? AND is_lead=0",
        (team_id, user_id),
    )
    conn.commit()
    conn.close()
    write_audit(user["id"], "remove_member", "team", team_id, f"user={user_id}")
    return {"message": "Member removed from team."}


# ============================================================
# TASKS
# ============================================================

@app.get("/api/tasks")
def get_tasks(
    team_id: Optional[int] = None,
    status: Optional[str] = None,
    user: dict = Depends(auth),
):
    conn = get_db()
    sql = """
        SELECT t.*, assigned.name AS assigned_name, assigner.name AS assigner_name,
               tm.name AS team_name
        FROM tasks t
        LEFT JOIN users assigned ON assigned.id=t.assigned_to
        LEFT JOIN users assigner ON assigner.id=t.assigned_by
        LEFT JOIN teams tm ON tm.id=t.team_id
        WHERE 1=1
    """
    args: list[Any] = []

    if user["role"] not in EXECUTIVE_ROLES:
        sql += " AND (t.assigned_to=? OR t.assigned_by=?)"
        args.extend([user["id"], user["id"]])

    if team_id:
        sql += " AND t.team_id=?"
        args.append(team_id)

    if status:
        sql += " AND t.status=?"
        args.append(status)

    sql += " ORDER BY t.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/tasks")
def create_task(
    payload: TaskReq,
    background: BackgroundTasks,
    user: dict = Depends(auth),
):
    if user["role"] == "committee_member":
        raise HTTPException(status_code=403, detail="Committee members cannot assign tasks.")

    conn = get_db()

    if payload.team_id is not None and not team_access(conn, payload.team_id, user):
        conn.close()
        raise HTTPException(status_code=403, detail="You do not belong to or manage this team.")

    assignee = conn.execute(
        "SELECT id,name,email FROM users WHERE id=? AND is_active=1",
        (payload.assigned_to,),
    ).fetchone()
    if not assignee:
        conn.close()
        raise HTTPException(status_code=404, detail="Assignee not found.")

    cur = conn.execute("""
        INSERT INTO tasks(
            title,description,priority,category,assigned_to,assigned_by,
            team_id,status,due_date,due_time,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        payload.title.strip(),
        payload.description,
        payload.priority,
        payload.category,
        payload.assigned_to,
        user["id"],
        payload.team_id,
        "Pending",
        payload.due_date,
        payload.due_time,
        now_iso(),
        now_iso(),
    ))
    task_id = cur.lastrowid
    conn.commit()
    conn.close()

    send_notification(
        assignee["id"],
        "New Council Task",
        f"You were assigned: {payload.title}. Due: {payload.due_date or 'No deadline'}",
        "task",
    )
    write_audit(user["id"], "create", "task", task_id, payload.title)
    return {"message": "Task created successfully.", "id": task_id}


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, payload: StatusUpdate, user: dict = Depends(auth)):
    conn = get_db()
    task = conn.execute(
        "SELECT assigned_to,assigned_by,team_id,title FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    if not task:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found.")

    allowed = {
        user["id"],
        task["assigned_to"],
        task["assigned_by"],
    }
    if user["role"] in EXECUTIVE_ROLES or (task["team_id"] and team_access(conn, task["team_id"], user)):
        allowed.add(user["id"])

    if user["id"] not in allowed:
        conn.close()
        raise HTTPException(status_code=403, detail="You cannot update this task.")

    conn.execute("""
        UPDATE tasks
        SET status=?,comments=?,updated_at=?
        WHERE id=?
    """, (payload.status, payload.extra_notes, now_iso(), task_id))
    conn.commit()
    conn.close()

    write_audit(user["id"], "update_status", "task", task_id, payload.status)
    return {"message": f"Task marked as {payload.status}."}


# ============================================================
# EVENTS
# ============================================================

@app.get("/api/events")
def get_events(team_id: Optional[int] = None, user: dict = Depends(auth)):
    conn = get_db()
    sql = """
        SELECT e.*,t.name AS team_name
        FROM events e
        LEFT JOIN teams t ON t.id=e.team_id
        WHERE 1=1
    """
    args: list[Any] = []
    if team_id:
        sql += " AND e.team_id=?"
        args.append(team_id)
    sql += " ORDER BY e.date ASC,e.start_time ASC,e.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/events")
def create_event(payload: EventReq, user: dict = Depends(require_roles(
    "president","vice_president","general_secretary","joint_secretary"
))):
    conn = get_db()
    if payload.team_id and not team_access(conn, payload.team_id, user):
        conn.close()
        raise HTTPException(status_code=403, detail="You do not manage this team.")

    cur = conn.execute("""
        INSERT INTO events(
            title,date,start_time,end_time,location,event_type,priority,
            description,organizer,capacity,team_id,budget_allocated,created_by,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        payload.title, payload.date, payload.start_time, payload.end_time,
        payload.location, payload.event_type, payload.priority,
        payload.description, payload.organizer, payload.capacity,
        payload.team_id, payload.budget_allocated, user["id"], now_iso(),
    ))
    event_id = cur.lastrowid
    conn.commit()
    conn.close()
    write_audit(user["id"], "create", "event", event_id, payload.title)
    return {"message": "Event added to calendar.", "id": event_id}


# ============================================================
# MEETINGS
# ============================================================

@app.get("/api/meetings")
def get_meetings(team_id: Optional[int] = None, user: dict = Depends(auth)):
    conn = get_db()
    sql = """
        SELECT m.*,u.name AS organizer,t.name AS team_name
        FROM meetings m
        LEFT JOIN users u ON u.id=m.created_by
        LEFT JOIN teams t ON t.id=m.team_id
        WHERE 1=1
    """
    args: list[Any] = []
    if team_id:
        sql += " AND m.team_id=?"
        args.append(team_id)
    sql += " ORDER BY m.date DESC,m.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/meetings")
def create_meeting(
    payload: MeetingReq,
    user: dict = Depends(require_roles(
        "president","vice_president","general_secretary","joint_secretary",
        "cultural_secretary","sports_secretary","technical_secretary",
        "social_responsibility_secretary","pr_media_secretary",
        "student_welfare_representative","womens_representative",
        "placement_training_representative",
    )),
):
    conn = get_db()
    if payload.team_id and not team_access(conn, payload.team_id, user):
        conn.close()
        raise HTTPException(status_code=403, detail="You do not manage this team.")

    cur = conn.execute("""
        INSERT INTO meetings(
            title,date,time,location,meeting_type,agenda,team_id,created_by,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        payload.title, payload.date, payload.time, payload.location,
        payload.meeting_type, payload.agenda, payload.team_id,
        user["id"], now_iso(),
    ))
    meeting_id = cur.lastrowid
    conn.commit()
    conn.close()
    write_audit(user["id"], "create", "meeting", meeting_id, payload.title)
    return {"message": "Meeting scheduled successfully.", "id": meeting_id}


@app.patch("/api/meetings/{meeting_id}")
def complete_meeting(
    meeting_id: int,
    payload: StatusUpdate,
    user: dict = Depends(require_roles(
        "president","vice_president","general_secretary","joint_secretary",
        "cultural_secretary","sports_secretary","technical_secretary",
        "social_responsibility_secretary","pr_media_secretary",
        "student_welfare_representative","womens_representative",
        "placement_training_representative",
    )),
):
    conn = get_db()
    meeting = conn.execute(
        "SELECT id,title,team_id FROM meetings WHERE id=?",
        (meeting_id,),
    ).fetchone()
    if not meeting:
        conn.close()
        raise HTTPException(status_code=404, detail="Meeting not found.")

    if meeting["team_id"] and not team_access(conn, meeting["team_id"], user):
        conn.close()
        raise HTTPException(status_code=403, detail="You cannot update this meeting.")

    status = payload.status or "Completed"
    if status.lower() in {"completed", "complete", "done", "closed"}:
        conn.execute(
            "UPDATE meetings SET status=?,completed_at=? WHERE id=?",
            (status, now_iso(), meeting_id),
        )
    else:
        conn.execute(
            "UPDATE meetings SET status=?,completed_at=NULL WHERE id=?",
            (status, meeting_id),
        )
    conn.commit()
    conn.close()
    write_audit(user["id"], "update_status", "meeting", meeting_id, status)
    return {"message": f"Meeting marked as {status}."}


# ============================================================
# FINANCE
# ============================================================

@app.get("/api/finances")
def get_finances(team_id: Optional[int] = None, user: dict = Depends(auth)):
    conn = get_db()
    sql = """
        SELECT f.*,u.name AS requester,a.name AS approver,t.name AS team_name
        FROM finances f
        LEFT JOIN users u ON u.id=f.requested_by
        LEFT JOIN users a ON a.id=f.approved_by
        LEFT JOIN teams t ON t.id=f.team_id
        WHERE 1=1
    """
    args: list[Any] = []

    if user["role"] not in FINANCE_ROLES:
        sql += " AND f.requested_by=?"
        args.append(user["id"])

    if team_id:
        sql += " AND f.team_id=?"
        args.append(team_id)

    sql += " ORDER BY f.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/finances")
def request_funds(payload: FinanceReq, user: dict = Depends(auth)):
    conn = get_db()
    if payload.team_id and not team_access(conn, payload.team_id, user):
        conn.close()
        raise HTTPException(status_code=403, detail="You do not manage this team.")

    cur = conn.execute("""
        INSERT INTO finances(
            title,amount,type,priority,status,requested_by,team_id,vendor,
            justification,receipt_url,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        payload.title, payload.amount, payload.type, payload.priority,
        "Pending", user["id"], payload.team_id, payload.vendor,
        payload.justification, payload.receipt_url, now_iso(), now_iso(),
    ))
    finance_id = cur.lastrowid
    conn.commit()
    conn.close()
    write_audit(user["id"], "create", "finance", finance_id, payload.title)
    return {"message": "Fund request submitted for approval.", "id": finance_id}


@app.patch("/api/finances/{finance_id}")
def approve_funds(
    finance_id: int,
    payload: StatusUpdate,
    user: dict = Depends(require_roles("treasurer","president","general_secretary","administrator")),
):
    conn = get_db()
    row = conn.execute(
        "SELECT requested_by,title FROM finances WHERE id=?",
        (finance_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Finance request not found.")

    conn.execute("""
        UPDATE finances SET status=?,approved_by=?,updated_at=?
        WHERE id=?
    """, (payload.status, user["id"], now_iso(), finance_id))
    conn.commit()
    conn.close()

    send_notification(
        row["requested_by"],
        "Finance Request Updated",
        f"{row['title']} is now {payload.status}.",
        "finance",
    )
    write_audit(user["id"], "finance_decision", "finance", finance_id, payload.status)
    return {"message": f"Funds {payload.status.lower()}."}


# ============================================================
# GRIEVANCES
# ============================================================

@app.get("/api/grievances")
def get_grievances(user: dict = Depends(auth)):
    conn = get_db()
    if user["role"] in WELFARE_ROLES:
        rows = conn.execute("""
            SELECT g.*,c.name AS creator,a.name AS assignee
            FROM grievances g
            LEFT JOIN users c ON c.id=g.created_by
            LEFT JOIN users a ON a.id=g.assigned_to
            ORDER BY g.id DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT g.*,c.name AS creator,a.name AS assignee
            FROM grievances g
            LEFT JOIN users c ON c.id=g.created_by
            LEFT JOIN users a ON a.id=g.assigned_to
            WHERE g.created_by=?
            ORDER BY g.id DESC
        """, (user["id"],)).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        if item.get("is_anonymous") and user["role"] not in {"faculty_coordinator", "president", "student_welfare_representative"}:
            item["created_by"] = None
            item["creator"] = None
        result.append(item)

    conn.close()
    return result


@app.post("/api/grievances")
def submit_grievance(payload: GrievanceReq, user: dict = Depends(auth)):
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO grievances(
            subject,description,category,department,contact_preference,
            is_anonymous,follow_up_allowed,priority,status,created_by,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        payload.subject, payload.description, payload.category,
        payload.department, payload.contact_preference, int(payload.is_anonymous),
        int(payload.follow_up_allowed), payload.priority, "Open",
        user["id"], now_iso(), now_iso(),
    ))
    grievance_id = cur.lastrowid
    conn.commit()
    conn.close()
    write_audit(user["id"], "create", "grievance", grievance_id, payload.subject)
    return {"message": "Grievance submitted securely.", "id": grievance_id}


@app.patch("/api/grievances/{grievance_id}")
def resolve_grievance(
    grievance_id: int,
    payload: StatusUpdate,
    user: dict = Depends(require_roles("student_welfare_representative","president")),
):
    conn = get_db()
    row = conn.execute(
        "SELECT created_by,subject FROM grievances WHERE id=?",
        (grievance_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Grievance not found.")

    conn.execute("""
        UPDATE grievances SET status=?,resolution_notes=?,updated_at=?
        WHERE id=?
    """, (payload.status, payload.extra_notes, now_iso(), grievance_id))
    conn.commit()
    conn.close()

    if row["created_by"]:
        send_notification(
            row["created_by"],
            "Grievance Updated",
            f"{row['subject']} is now {payload.status}.",
            "grievance",
        )
    write_audit(user["id"], "grievance_decision", "grievance", grievance_id, payload.status)
    return {"message": "Grievance updated."}


# ============================================================
# ANNOUNCEMENTS
# ============================================================

@app.get("/api/announcements")
def get_announcements(
    team_id: Optional[int] = None,
    user: dict = Depends(auth),
):
    conn = get_db()
    sql = """
        SELECT a.*,u.name AS author,t.name AS team_name
        FROM announcements a
        LEFT JOIN users u ON u.id=a.created_by
        LEFT JOIN teams t ON t.id=a.team_id
        WHERE 1=1
    """
    args: list[Any] = []
    if team_id:
        sql += " AND (a.team_id=? OR a.team_id IS NULL)"
        args.append(team_id)
    sql += " ORDER BY a.id DESC LIMIT 50"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/announcements")
def post_announcement(payload: AnnouncementReq, user: dict = Depends(require_roles(
    "president","general_secretary","pr_media_secretary"
))):
    conn = get_db()
    if payload.team_id and not team_access(conn, payload.team_id, user):
        conn.close()
        raise HTTPException(status_code=403, detail="You do not manage this team.")

    cur = conn.execute("""
        INSERT INTO announcements(title,content,audience,team_id,created_by,created_at)
        VALUES(?,?,?,?,?,?)
    """, (
        payload.title, payload.content, payload.audience,
        payload.team_id, user["id"], now_iso(),
    ))
    announcement_id = cur.lastrowid

    target_sql = """
        SELECT id FROM users WHERE is_active=1
    """
    target_args: tuple[Any, ...] = ()
    if payload.team_id:
        target_sql = """
            SELECT DISTINCT u.id
            FROM users u
            JOIN team_members tm ON tm.user_id=u.id
            WHERE tm.team_id=? AND u.is_active=1
        """
        target_args = (payload.team_id,)

    recipients = conn.execute(target_sql, target_args).fetchall()
    for recipient in recipients:
        conn.execute("""
            INSERT INTO notifications(user_id,title,message,kind,created_at)
            VALUES(?,?,?,?,?)
        """, (
            recipient["id"], payload.title, payload.content, "announcement", now_iso()
        ))

    conn.commit()
    conn.close()

    write_audit(user["id"], "create", "announcement", announcement_id, payload.title)
    return {"message": "Announcement broadcasted.", "id": announcement_id, "recipients": len(recipients)}


# ============================================================
# GOALS
# ============================================================

@app.get("/api/goals")
def get_goals(team_id: Optional[int] = None, user: dict = Depends(auth)):
    conn = get_db()
    sql = """
        SELECT g.*,t.name AS team_name,u.name AS owner_name
        FROM goals g
        JOIN teams t ON t.id=g.team_id
        LEFT JOIN users u ON u.id=g.owner_id
        WHERE 1=1
    """
    args: list[Any] = []
    if team_id:
        sql += " AND g.team_id=?"
        args.append(team_id)
    elif user["role"] not in EXECUTIVE_ROLES:
        sql += """
            AND EXISTS(
                SELECT 1 FROM team_members tm
                WHERE tm.team_id=g.team_id AND tm.user_id=?
            )
        """
        args.append(user["id"])
    sql += " ORDER BY g.target_date ASC,g.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/goals")
def create_goal(payload: GoalReq, user: dict = Depends(auth)):
    conn = get_db()
    if not team_access(conn, payload.team_id, user):
        conn.close()
        raise HTTPException(status_code=403, detail="You do not manage or belong to this team.")

    owner_id = payload.owner_id or user["id"]
    cur = conn.execute("""
        INSERT INTO goals(
            team_id,title,description,owner_id,target_date,status,progress,created_by,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        payload.team_id, payload.title, payload.description, owner_id,
        payload.target_date, "Planned", 0, user["id"], now_iso(), now_iso()
    ))
    goal_id = cur.lastrowid
    conn.commit()
    conn.close()
    write_audit(user["id"], "create", "goal", goal_id, payload.title)
    return {"message": "Goal created.", "id": goal_id}


@app.patch("/api/goals/{goal_id}")
def update_goal(goal_id: int, payload: GoalProgressReq, user: dict = Depends(auth)):
    conn = get_db()
    goal = conn.execute("SELECT team_id,title FROM goals WHERE id=?", (goal_id,)).fetchone()
    if not goal:
        conn.close()
        raise HTTPException(status_code=404, detail="Goal not found.")
    if not team_access(conn, goal["team_id"], user):
        conn.close()
        raise HTTPException(status_code=403, detail="You cannot update this goal.")

    conn.execute("""
        UPDATE goals SET progress=?,status=?,updated_at=? WHERE id=?
    """, (payload.progress, payload.status, now_iso(), goal_id))
    conn.commit()
    conn.close()
    write_audit(user["id"], "update_progress", "goal", goal_id, str(payload.progress))
    return {"message": "Goal updated."}


# ============================================================
# DOCUMENTS / SOURCE LINKING
# ============================================================

@app.get("/api/documents")
def get_documents(team_id: Optional[int] = None, user: dict = Depends(auth)):
    conn = get_db()
    sql = """
        SELECT d.*,t.name AS team_name,u.name AS creator
        FROM documents d
        LEFT JOIN teams t ON t.id=d.team_id
        LEFT JOIN users u ON u.id=d.created_by
        WHERE 1=1
    """
    args: list[Any] = []
    if team_id:
        sql += " AND (d.team_id=? OR d.team_id IS NULL)"
        args.append(team_id)
    sql += " ORDER BY d.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/documents")
def add_document(payload: DocumentReq, user: dict = Depends(auth)):
    conn = get_db()
    if payload.team_id and not team_access(conn, payload.team_id, user):
        conn.close()
        raise HTTPException(status_code=403, detail="You do not manage this team.")

    cur = conn.execute("""
        INSERT INTO documents(team_id,title,description,file_url,document_type,created_by,created_at)
        VALUES(?,?,?,?,?,?,?)
    """, (
        payload.team_id, payload.title, payload.description,
        payload.file_url, payload.document_type, user["id"], now_iso()
    ))
    doc_id = cur.lastrowid
    conn.commit()
    conn.close()
    write_audit(user["id"], "create", "document", doc_id, payload.title)
    return {"message": "Document linked.", "id": doc_id}


# ============================================================
# APPROVALS
# ============================================================

@app.get("/api/approvals")
def get_approvals(team_id: Optional[int] = None, user: dict = Depends(auth)):
    conn = get_db()
    sql = """
        SELECT a.*,t.name AS team_name,r.name AS requester,v.name AS reviewer
        FROM approvals a
        LEFT JOIN teams t ON t.id=a.team_id
        LEFT JOIN users r ON r.id=a.requested_by
        LEFT JOIN users v ON v.id=a.reviewed_by
        WHERE 1=1
    """
    args: list[Any] = []
    if user["role"] not in EXECUTIVE_ROLES:
        sql += " AND (a.requested_by=? OR EXISTS(SELECT 1 FROM team_members tm WHERE tm.team_id=a.team_id AND tm.user_id=?))"
        args.extend([user["id"], user["id"]])
    if team_id:
        sql += " AND a.team_id=?"
        args.append(team_id)
    sql += " ORDER BY a.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/approvals")
def create_approval(payload: ApprovalReq, user: dict = Depends(auth)):
    conn = get_db()
    if payload.team_id and not team_access(conn, payload.team_id, user):
        conn.close()
        raise HTTPException(status_code=403, detail="You cannot create an approval for this team.")

    cur = conn.execute("""
        INSERT INTO approvals(team_id,title,description,approval_type,requested_by,status,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
    """, (
        payload.team_id, payload.title, payload.description, payload.approval_type,
        user["id"], "Pending", now_iso(), now_iso()
    ))
    approval_id = cur.lastrowid
    conn.commit()
    conn.close()
    write_audit(user["id"], "create", "approval", approval_id, payload.title)
    return {"message": "Approval requested.", "id": approval_id}


@app.patch("/api/approvals/{approval_id}")
def decide_approval(
    approval_id: int,
    payload: ApprovalDecision,
    user: dict = Depends(require_roles("president","general_secretary","faculty_coordinator")),
):
    conn = get_db()
    row = conn.execute(
        "SELECT requested_by,title FROM approvals WHERE id=?",
        (approval_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Approval not found.")

    conn.execute("""
        UPDATE approvals
        SET status=?,reviewed_by=?,review_notes=?,updated_at=?
        WHERE id=?
    """, (
        payload.status, user["id"], payload.review_notes, now_iso(), approval_id
    ))
    conn.commit()
    conn.close()

    send_notification(
        row["requested_by"],
        "Approval Updated",
        f"{row['title']} is now {payload.status}.",
        "approval",
    )
    write_audit(user["id"], "decision", "approval", approval_id, payload.status)
    return {"message": "Approval decision saved."}


# ============================================================
# NOTIFICATIONS
# ============================================================

@app.get("/api/notifications")
def notifications(user: dict = Depends(auth)):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM notifications
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 100
    """, (user["id"],)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, user: dict = Depends(auth)):
    conn = get_db()
    conn.execute("""
        UPDATE notifications SET is_read=1
        WHERE id=? AND user_id=?
    """, (notification_id, user["id"]))
    conn.commit()
    conn.close()
    return {"message": "Notification marked as read."}


@app.post("/api/notifications/read-all")
def mark_all_notifications_read(user: dict = Depends(auth)):
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE user_id=?",
        (user["id"],),
    )
    conn.commit()
    conn.close()
    return {"message": "All notifications marked as read."}


# ============================================================
# AUDIT / SYSTEM OVERSIGHT
# ============================================================

@app.get("/api/audit-logs")
def audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(require_roles("president","general_secretary","faculty_coordinator")),
):
    conn = get_db()
    rows = conn.execute("""
        SELECT a.*,u.name AS actor
        FROM audit_logs a
        LEFT JOIN users u ON u.id=a.actor_id
        ORDER BY a.id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# EXPORTS
# ============================================================

def csv_response(
    filename: str,
    headers: list[str],
    rows: list[list[Any]],
) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/teams")
def export_teams(user: dict = Depends(auth)):
    conn = get_db()
    rows = conn.execute("""
        SELECT t.name,lead.name AS lead,faculty.name AS faculty,COUNT(tm.id) AS members
        FROM teams t
        LEFT JOIN users lead ON lead.id=t.lead_user_id
        LEFT JOIN users faculty ON faculty.id=t.faculty_coordinator_id
        LEFT JOIN team_members tm ON tm.team_id=t.id
        GROUP BY t.id
        ORDER BY t.name
    """).fetchall()
    conn.close()

    return csv_response(
        f"Council_Teams_{datetime.now():%Y%m%d}.csv",
        ["Team", "Lead", "Faculty Coordinator", "Members"],
        [[r["name"], r["lead"], r["faculty"], r["members"]] for r in rows],
    )


@app.get("/api/export/finance")
def export_finance(user: dict = Depends(require_roles("treasurer","president","general_secretary"))):
    conn = get_db()
    rows = conn.execute("""
        SELECT f.id,f.title,f.amount,f.type,f.priority,f.status,
               u.name AS requester,t.name AS team,f.created_at
        FROM finances f
        LEFT JOIN users u ON u.id=f.requested_by
        LEFT JOIN teams t ON t.id=f.team_id
        ORDER BY f.id DESC
    """).fetchall()
    conn.close()

    return csv_response(
        f"Council_Finance_{datetime.now():%Y%m%d}.csv",
        ["ID","Title","Amount","Type","Priority","Status","Requested By","Team","Created At"],
        [[r["id"],r["title"],r["amount"],r["type"],r["priority"],r["status"],r["requester"],r["team"],r["created_at"]] for r in rows],
    )


@app.get("/api/export/meetings")
def export_meetings(user: dict = Depends(require_roles(
    "president","vice_president","general_secretary","joint_secretary"
))):
    conn = get_db()
    rows = conn.execute("""
        SELECT m.id,m.title,m.date,m.time,m.location,m.meeting_type,
               u.name AS organizer,t.name AS team,m.agenda
        FROM meetings m
        LEFT JOIN users u ON u.id=m.created_by
        LEFT JOIN teams t ON t.id=m.team_id
        ORDER BY m.date DESC,m.id DESC
    """).fetchall()
    conn.close()

    return csv_response(
        f"Council_Meetings_{datetime.now():%Y%m%d}.csv",
        ["ID","Title","Date","Time","Location","Type","Organizer","Team","Agenda"],
        [[r["id"],r["title"],r["date"],r["time"],r["location"],r["meeting_type"],r["organizer"],r["team"],(r["agenda"] or "").replace("\n"," -- ")] for r in rows],
    )


@app.get("/api/export/members")
def export_members(user: dict = Depends(auth)):
    conn = get_db()
    rows = conn.execute("""
        SELECT u.name,u.role,u.class_name,u.branch,u.portfolio,u.email
        FROM users u
        WHERE u.is_active=1
        ORDER BY u.role,u.name
    """).fetchall()
    conn.close()

    return csv_response(
        f"Council_Members_{datetime.now():%Y%m%d}.csv",
        ["Name","Role","Class","Branch","Portfolio","Email"],
        [[r["name"],ROLES.get(r["role"],r["role"]),r["class_name"],r["branch"],r["portfolio"],r["email"]] for r in rows],
    )


# ============================================================
# LEGACY-COMPATIBILITY ROUTES
# ============================================================

# These aliases keep older frontend buttons/endpoints working.
@app.get("/api/export/finances")
def legacy_export_finances(user: dict = Depends(require_roles("treasurer","president","general_secretary"))):
    return export_finance(user)


@app.get("/api/export/meetings")
def legacy_export_meetings(user: dict = Depends(require_roles(
    "president","vice_president","general_secretary","joint_secretary"
))):
    return export_meetings(user)


# ============================================================
# RUNNING LOCALLY
# ============================================================

if __name__ == "__main__":
    import uvicorn

    print(f"Starting {APP_TITLE} v{APP_VERSION}")
    print(f"Database: {DB_PATH}")
    print(f"Frontend: {FRONTEND_DIR if FRONTEND_DIR.exists() else 'not found'}")
    print(f"Council PDF: {COUNCIL_PDF if COUNCIL_PDF.exists() else 'not found'}")
    uvicorn.run(
        "main:app",
        host=os.getenv("SCMS_HOST", "127.0.0.1"),
        port=int(os.getenv("SCMS_PORT", "8000")),
        reload=True,
    )


# Serve the frontend last so /api/* routes always take precedence.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
