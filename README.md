# POLAR-X — Integrated Polar Expedition Logistics & Asset Management

A working full-stack prototype based on the SIH26062 proposal.

## Stack
- Frontend: HTML, CSS, JavaScript
- Backend: Python + Flask
- Database: MySQL-ready via SQLAlchemy; SQLite can be used for local demo
- Auth: JWT + role-based access control
- Offline-first: browser local queue + automatic sync when connectivity returns
- GPS: browser Geolocation API with demo fallback
- API: REST endpoints

## Features
- Login/register
- Roles: ADMIN, MANAGER, EXPEDITIONER, VIEWER
- Dashboard with asset statistics and alerts
- Add/edit/delete assets
- Asset status tracking: AVAILABLE, IN_USE, MAINTENANCE, LOST
- Low-stock / overdue / maintenance alerts
- Expedition creation and status updates
- Expedition assignment of assets
- GPS position capture
- Offline asset changes queued in localStorage and synced later
- Search/filter/sort inventory
- Audit log
- Responsive UI

## Run

### 1. Backend
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

For MySQL set:
`DATABASE_URL=mysql+pymysql://root:password@localhost/polar_x`

For a zero-setup demo, leave the SQLite URL in `.env`.

### 2. Frontend
The Flask server serves the frontend at:
`http://127.0.0.1:5000`

### Demo accounts
- admin@polarx.local / Admin@123
- manager@polarx.local / Manager@123
- expedition@polarx.local / Expedition@123
- viewer@polarx.local / Viewer@123

Change passwords before deployment.


## Extended demo features

### AI-assisted inventory forecasting
`GET /api/analytics/forecast` produces an explainable stock-risk estimate using current quantity, minimum quantity and operational status. It is deliberately transparent rather than pretending to be a trained ML model.

### IoT telemetry simulator
`POST /api/telemetry/simulate` generates temperature, battery, wind or pressure readings. This lets the SIH demo show the same architecture that a real sensor gateway can use.

### Reports
- `/api/reports/assets.csv`
- `/api/reports/expeditions.csv`

### MySQL with Docker
```bash
docker compose up -d
```
Then set:
```env
DATABASE_URL=mysql+pymysql://polarx:polarx_password@127.0.0.1:3306/polar_x
```

## Architecture
Browser → Flask REST API → SQLAlchemy → MySQL/SQLite
                  ↘ JWT/RBAC
                  ↘ telemetry + GPS
                  ↘ audit trail
                  ↘ offline browser queue

## Web application deployment

POLAR-X is a single web application: Flask serves the HTML/CSS/JavaScript client and REST API from the same origin. You can run it locally at `http://127.0.0.1:5000` or deploy it as a Python web service.

### Render deployment
1. Push this folder to GitHub.
2. Create a new Web Service on Render and connect the repository.
3. Render can use `render.yaml`, or use build command `pip install -r backend/requirements.txt` and start command `gunicorn backend.app:app`.
4. Set a strong `SECRET_KEY` environment variable.
5. For production persistence, use a managed MySQL/PostgreSQL database rather than the demo SQLite database.

### Browser/PWA
The frontend includes a web manifest and service worker for basic app-shell caching. API changes still require connectivity unless queued by the existing offline workflow.

## Admin user management

Administrators now have a **User Management** page.

1. Sign in as `admin@polarx.local` / `Admin@123`.
2. Open **User Management**.
3. Click **Create User**.
4. Enter the user's name and email.
5. Select `ADMIN`, `MANAGER`, `EXPEDITIONER`, or `VIEWER`.
6. Optionally enter a password. If left blank, POLAR-X securely generates a temporary password.
7. POLAR-X displays the new user's login credentials once so the administrator can copy/share them securely.
8. The new user signs in with those credentials and is required to choose a new password on first login.
9. Administrators can also generate a new temporary password using **Reset password** from the user list.

The credentials are displayed in the web interface; automatic email delivery is not configured in this demo because no SMTP/email provider is included. For production deployment, connect an email provider and send invitation/reset links rather than emailing plain passwords.

## Render cloud deployment

This package includes `render.yaml` for a Render Blueprint with a Flask web service and managed PostgreSQL database. Render supports Flask web services with Gunicorn and provides an `onrender.com` HTTPS URL. The Blueprint connects the app to PostgreSQL through `DATABASE_URL`.

1. Push the `POLAR-X-WEB-APPLICATION` folder to a GitHub repository.
2. In Render, choose **New → Blueprint** and select the repository.
3. Review the `polar-x` web service and `polar-x-db` PostgreSQL database.
4. Deploy. The generated service URL can be opened from any device with internet access.
5. The app health check is `/healthz`.

For a hackathon/demo deployment, the Render free web service/database options can be used for testing. Render currently notes that free web services spin down after inactivity and free Postgres databases have limited retention, so use a paid/persistent database plan for long-term production data.
