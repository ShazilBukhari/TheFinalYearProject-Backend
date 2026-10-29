# ShazAI Backend

Flask API backend for ShazAI — handles user auth and sends code + error logs to
Gemini for AI-powered debugging.

## Stack

- Flask + Flask-JWT-Extended (auth)
- Flask-CORS
- SQLite3 (`database.db`, created automatically on first run)
- Google Generative AI (`gemini-2.5-flash`)

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

Create a `.env` file in this folder (see `.env.example`):

```
GEMINI_API_KEY=your_gemini_api_key_here
```

Run it:

```bash
python app.py
```

The server starts on `http://127.0.0.1:5000`. The SQLite database and its
tables (`users`, `history`) are created automatically on first run.

## API

| Route | Method | Auth | Description |
| --- | --- | --- | --- |
| `/api/register` | POST | — | Create an account |
| `/api/login` | POST | — | Log in, returns a JWT |
| `/api/debug` | POST | JWT | Send `raw_code` + `error_log`, get an AI fix |
| `/api/history` | GET | JWT | Past debug requests for the logged-in user |
| `/api/private` | GET | JWT | Sample protected route |

## Note

All configuration comes from environment variables (see `.env.example`):
`GEMINI_API_KEY`, `JWT_SECRET_KEY` (required in production), and the optional
`CORS_ORIGINS`, `DATABASE_PATH`, `JWT_EXPIRES_HOURS` and `GEMINI_MODEL`.

SQLite lives on the server's local disk. On hosts with an ephemeral
filesystem (e.g. Render free tier) the data is lost on every redeploy or
restart; mount a persistent disk and point `DATABASE_PATH` at it, or move to a
hosted database.

Every error response is JSON in the form `{"error": "message"}`.
