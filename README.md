# Siddhant College Student Council Management System — Integrated

The frontend is copied unchanged and the existing FastAPI backend is placed in `backend/main.py`.

## Run

### Windows
1. Open a terminal in `backend`.
2. Run: `py -m pip install -r requirements.txt`
3. Run: `py -m uvicorn main:app --reload --host 127.0.0.1 --port 8000`
4. Open `frontend/index.html` in the browser.

The frontend already points to:
`http://127.0.0.1:8000/api`

### Recommended single-server mode
Copy `frontend/index.html` into `backend/frontend/index.html`, then run the backend. The existing backend automatically serves `./frontend` at `/` when that folder exists.

Demo accounts are seeded by the backend:
- Non-faculty users: password `student123`
- Faculty coordinator: password `admin123`

Example:
`kiran.prasad@scms.local` / `student123`


## Supabase deployment

The SCMS schema and current SQLite data have been migrated to the configured Supabase project. The FastAPI backend now supports Supabase Postgres through `DATABASE_URL` while retaining SQLite as a local fallback.

1. Copy `.env.example` to `.env`.
2. Put your Supabase Postgres connection string in `DATABASE_URL`.
3. Install requirements with `pip install -r backend/requirements.txt`.
4. Start the API with `uvicorn backend.main:app --host 0.0.0.0 --port 8000` (or run from `backend` as `uvicorn main:app --host 0.0.0.0 --port 8000`).
5. Keep the database URL server-side only.

The browser must never receive a Supabase database password, secret key, or service-role key. Supabase recommends RLS for direct frontend Data API access; this SCMS build keeps authorization in FastAPI and uses the database connection only on the server.
