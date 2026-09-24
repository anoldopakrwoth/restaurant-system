# Java House Hotel & Restaurant API

Flask API and dashboard for rooms, bookings, customers, restaurant tables, menu items, orders, and invoices.

## Run locally

1. Create a virtual environment and install dependencies:

   `python -m venv .venv`

   `.venv\\Scripts\\activate`

   `pip install -r requirements.txt`

2. Copy `.env.example` to `.env` and set the database values. Set `OPENAI_API_KEY` if hosted AI answers are required.

3. Start the API:

   `python app.py`

Open `index.html` in a browser after the API starts.

## Change the dashboard background

Replace `background.jpg/manager-background.jpg` with another image, then update the `--manager-background-image` line near the top of `index.html` (and `styles.css` if that stylesheet is used separately).

## Staff authentication

Create a staff account with `POST /api/staff/register`, then log in with `POST /api/staff/login`. The login response includes a token valid for eight hours. Send it when viewing or creating customers and when using the AI assistant:

```http
Authorization: Bearer YOUR_STAFF_TOKEN
```

Set a strong `SECRET_KEY` in `.env` before deployment. Do not use the default value.

Roles are enforced on both the API and dashboard. `admin` and `manager` are full operational users: they can see and use rooms, bookings, tables, menu, orders, customers, invoices, AI, and staff management. `receptionist`, `restaurant`, `cashier`, and `housekeeping` only see the dashboard areas needed for their work. The API remains the source of truth, so hiding a dashboard area never replaces server-side authorization.

Operational roles are also enforced: managers/admins/receptionists manage rooms and bookings; restaurant staff manage tables, menu, and orders; cashiers manage orders and invoices; housekeeping can update room status. `PUT` endpoints update records while preserving history.

## Manager workspace

Managers and admins have a `Staff & assignments` workspace. It reads staff accounts from the database, creates users with a specific work area, changes assignments, and removes staff accounts. The manager overview also reports current totals and today's bookings, orders, invoices, and new customers.

Managers can use the dedicated manager entry point at `/manager`. That login accepts only accounts whose database role is `manager` or `admin`; after login, the dashboard hides all non-manager areas for other roles and shows the complete management workspace for managers.

Operational tables include Edit and Delete controls. Changes are sent to the API and committed to the database. Deletes that would break related history are rejected safely; for example, a menu item referenced by an order must be marked unavailable instead of deleted.

Deletion is manager-controlled. All delete endpoints require an authenticated manager/admin session plus a fresh manager email and password in the request. Staff users can use the shared login and see the read-only summary cards, but they cannot delete records or access the manager detail panels.

## Backups

Install MySQL Server tools so `mysqldump` is available, then run this from PowerShell:

```powershell
.\backup_mysql.ps1
```

Copy the generated `backups` folder to a separate drive or cloud storage regularly. Do not store backups in a public web folder.

## HTTPS

Do not expose `python app.py` directly to the internet. Deploy behind a reverse proxy or managed HTTPS service such as Azure App Service, Azure Container Apps, or Nginx with a trusted TLS certificate. Keep Flask listening on localhost/private networking, and set `CORS` to your real dashboard domain instead of allowing every origin.

## AI connection

`POST /api/ai/chat`

Request:

```json
{"message":"How many rooms are available?"}
```

The endpoint includes live rooms, tables, menu, bookings, orders, and invoice data in the model prompt. If `OPENAI_API_KEY` is not configured, it uses a local data-aware fallback for common operational questions. The API key stays server-side and is never returned to clients.

`GET /api/health` reports service status and whether AI is configured.
