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

`app.py` currently has the JWT signing secret hardcoded as a literal string.
For anything beyond a class project, move it into `.env` alongside
`GEMINI_API_KEY` and read it with `os.getenv(...)`, the same way the Gemini
key is handled.
