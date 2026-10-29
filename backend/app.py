import logging
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import timedelta

import google.generativeai as genai
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
  JWTManager,
  create_access_token,
  get_jwt_identity,
  jwt_required,
)
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("shazai")

# ---------------------------------------------------------------------------
# Configuration (everything comes from environment variables)
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))

DATABASE_PATH = os.getenv(
  "DATABASE_PATH",
  os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db"),
)

# Comma separated list, e.g. "http://localhost:5173,https://myapp.vercel.app"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
  # Fail soft so the service still boots, but make the problem impossible to miss.
  # A random key means tokens stop working after every restart.
  JWT_SECRET_KEY = secrets.token_hex(32)
  logger.warning("JWT_SECRET_KEY is not set. Using a temporary random key; "
                 "all logins will be invalidated on restart. Set it in your environment.")

MAX_CODE_LENGTH = 20000
MAX_LOG_LENGTH = 10000
MIN_PASSWORD_LENGTH = 6
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

model = None
if GEMINI_API_KEY:
  genai.configure(api_key=GEMINI_API_KEY)
  model = genai.GenerativeModel(GEMINI_MODEL)
else:
  logger.warning("GEMINI_API_KEY is not set. /api/debug will return 503 until it is configured.")

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=int(os.getenv("JWT_EXPIRES_HOURS", "24")))
CORS(app, resources={r"/api/*": {"origins": CORS_ORIGINS}})
jwt = JWTManager(app)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_conn():
  conn = sqlite3.connect(DATABASE_PATH)
  conn.execute("PRAGMA foreign_keys = ON")
  return conn


def create_table():
  with closing(get_conn()) as conn:
    conn.execute("""CREATE TABLE IF NOT EXISTS users(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT NOT NULL,
                 email TEXT NOT NULL,
                 password TEXT NOT NULL
                 )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS history(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER NOT NULL,
                 raw_code TEXT NOT NULL,
                 error_log TEXT NOT NULL,
                 ai_response TEXT NOT NULL,
                 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY (user_id) REFERENCES users(id)
                 )""")
    try:
      conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    except sqlite3.IntegrityError:
      logger.warning("Duplicate usernames exist; unique index on users.username was not created.")
    conn.commit()


create_table()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class ApiError(Exception):
  """An error that is safe to show to the client."""

  def __init__(self, message, status_code=400):
    super().__init__(message)
    self.message = message
    self.status_code = status_code


def get_json_body():
  data = request.get_json(silent=True)
  if not isinstance(data, dict):
    raise ApiError("Request body must be valid JSON", 400)
  return data


def clean_text(value):
  return value.strip() if isinstance(value, str) else ""


class AIServiceError(Exception):
  pass


def ask_ai(raw_code, error_log):
  if model is None:
    raise AIServiceError("AI service is not configured")

  prompt = f"""
  You are an expert developer and elite debugger. Analyze the following code and error log carefully.

  Code:
  {raw_code}

  Error Log:
  {error_log}

  Provide the response strictly in Markdown format with two clear sections:
    ## 🔍 Bug Description:
    (Explain the issue in short and crisp points)

    ## 🛠️ Fixed Code:
    (Provide ONLY the corrected code inside a standard markdown code block)

  """
  try:
    response = model.generate_content(prompt, request_options={"timeout": GEMINI_TIMEOUT_SECONDS})
    return response.text
  except Exception as e:
    logger.exception("Gemini request failed")
    raise AIServiceError(str(e)) from e


# ---------------------------------------------------------------------------
# Error handlers: every error leaves the API as {"error": "..."}
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
  return jsonify({"error": e.message}), e.status_code


@app.errorhandler(HTTPException)
def handle_http_error(e):
  return jsonify({"error": e.description or e.name}), e.code


@app.errorhandler(Exception)
def handle_unexpected_error(e):
  logger.exception("Unhandled error on %s %s", request.method, request.path)
  return jsonify({"error": "Internal server error. Please try again later."}), 500


@jwt.unauthorized_loader
def missing_token(reason):
  return jsonify({"error": "Authentication required. Please log in."}), 401


@jwt.invalid_token_loader
def invalid_token(reason):
  return jsonify({"error": "Invalid token. Please log in again."}), 401


@jwt.expired_token_loader
def expired_token(jwt_header, jwt_payload):
  return jsonify({"error": "Session expired. Please log in again."}), 401


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
  return jsonify({"status": "ok", "message": "ShazAI backend is running"}), 200


@app.route("/api/register", methods=["POST"])
def register():
  data = get_json_body()
  username = clean_text(data.get("username"))
  email = clean_text(data.get("email")).lower()
  password = data.get("password")

  if not username or not email or not isinstance(password, str) or not password:
    raise ApiError("All fields are mandatory", 400)
  if not EMAIL_PATTERN.match(email):
    raise ApiError("Please enter a valid email address", 400)
  if len(password) < MIN_PASSWORD_LENGTH:
    raise ApiError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters", 400)

  hashed_password = generate_password_hash(password)

  with closing(get_conn()) as conn:
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
      raise ApiError("Username already exists", 409)
    try:
      conn.execute(
        "INSERT INTO users(username, password, email) VALUES(?,?,?)",
        (username, hashed_password, email),
      )
      conn.commit()
    except sqlite3.IntegrityError:
      raise ApiError("Username already exists", 409)

  return jsonify({"message": "Register Successfully"}), 200


@app.route("/api/login", methods=["POST"])
def login():
  data = get_json_body()
  username = clean_text(data.get("username"))
  password = data.get("password")

  if not username or not isinstance(password, str) or not password:
    raise ApiError("Username and password are required", 400)

  with closing(get_conn()) as conn:
    user = conn.execute("SELECT id, password FROM users WHERE username = ?", (username,)).fetchone()

  if not user:
    raise ApiError("User Not Found", 401)
  if not check_password_hash(user[1], password):
    raise ApiError("Invalid Password", 401)

  access_token = create_access_token(identity=str(user[0]))
  return jsonify({"message": "Login Successfully", "access_token": access_token}), 200


@app.route("/api/private", methods=["GET"])
@jwt_required()
def private():
  return jsonify({"message": "Access Granted", "user_id": get_jwt_identity()}), 200


@app.route("/api/debug", methods=["POST"])
@jwt_required()
def debug():
  user_id = get_jwt_identity()
  data = get_json_body()
  raw_code = clean_text(data.get("raw_code"))
  error_log = clean_text(data.get("error_log")) or "No error log provided"

  if not raw_code:
    raise ApiError("Code is required", 400)
  if len(raw_code) > MAX_CODE_LENGTH:
    raise ApiError(f"Code is too long (max {MAX_CODE_LENGTH} characters)", 413)
  if len(error_log) > MAX_LOG_LENGTH:
    raise ApiError(f"Error log is too long (max {MAX_LOG_LENGTH} characters)", 413)

  try:
    ai_response = ask_ai(raw_code, error_log)
  except AIServiceError:
    # Not saved to history: a failed AI call should not look like a real answer.
    if model is None:
      raise ApiError("AI service is not configured on the server", 503)
    raise ApiError("The AI service is unavailable right now. Please try again.", 502)

  with closing(get_conn()) as conn:
    conn.execute(
      "INSERT INTO history(user_id, raw_code, error_log, ai_response) VALUES(?,?,?,?)",
      (user_id, raw_code, error_log, ai_response),
    )
    conn.commit()

  return jsonify({"message": "Debug successfully", "response": ai_response}), 200


@app.route("/api/history", methods=["GET"])
@jwt_required()
def history():
  user_id = get_jwt_identity()
  with closing(get_conn()) as conn:
    rows = conn.execute(
      "SELECT id, raw_code, error_log, ai_response, created_at FROM history "
      "WHERE user_id = ? ORDER BY id DESC",
      (user_id,),
    ).fetchall()

  history_list = [
    {
      "id": row[0],
      "raw_code": row[1],
      "error_log": row[2],
      "ai_response": row[3],
      "created_at": row[4],
    }
    for row in rows
  ]
  return jsonify(history_list), 200


if __name__ == "__main__":
  app.run(
    host="127.0.0.1",
    port=int(os.getenv("PORT", "5000")),
    debug=os.getenv("FLASK_DEBUG", "0") == "1",
  )
