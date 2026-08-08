from flask import Flask,jsonify,request
from werkzeug.security import generate_password_hash,check_password_hash
from flask_jwt_extended import create_access_token,JWTManager,jwt_required,get_jwt_identity
from flask_cors import CORS 
import sqlite3
import os
from dotenv import load_dotenv
import google.generativeai as genai


load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel('gemini-2.5-flash')

app=Flask(__name__)
CORS(app)
app.config["JWT_SECRET_KEY"]="finalyearproject_secret_key_shazai_2026"
jwt = JWTManager(app)

def get_conn():
  return sqlite3.connect('database.db')

def create_table():
  conn = get_conn()
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
  conn.commit()
  conn.close()

create_table()

#that is a normal python function to send a prompt to gemini ai 

def ask_ai(raw_code, error_log):
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
    response = model.generate_content(prompt)
    return response.text
  except Exception as e:
    return f"API Error: {str(e)}"


@app.route('/', methods=["GET"])
def hello():
    # Test ke liye ek chota sa galat code bhej kar dekhte hain
    test_code = "print('Hello' + 5)"  # String aur integer add nahi ho sakte
    test_error = "TypeError: can only concatenate str (not 'int') to str"
    
    ai_reply = ask_ai(test_code, test_error)
    
    return jsonify({
        "message": "Yaha sab sahi hain",
        "ai_test_response": ai_reply
    }), 200

@app.route('/api/register',methods=["POST"])
def register():
  data = request.get_json()
  username = data.get('username')
  password = data.get('password')
  email = data.get('email')
   
  if not username or not password or not email:
    return jsonify({"error":"All fields are mandatory"}),400
  
  hash_password = generate_password_hash(password)
  conn = get_conn()
  cursor = conn.execute("SELECT * FROM users WHERE username = ?",(username,))
  user = cursor.fetchone()

  if user:
    return jsonify({"error":"Username already exists"}),401
  
  conn.execute("INSERT INTO users(username,password,email) VALUES(?,?,?)",(username,hash_password,email))
  conn.commit()
  conn.close()
  return jsonify({"message":"Register Successfully"}),200


@app.route('/api/login',methods=["POST"])
def login():
  data = request.get_json()
  username = data.get('username')
  password = data.get('password')
  email = data.get('email')
   
  if not username or not password or not email:
    return jsonify({"error":"All fields are mandatory"}),400
  
  conn = get_conn()
  cursor = conn.execute("SELECT id,password FROM users WHERE username = ?",(username,))
  user = cursor.fetchone()

  if not user:
    return jsonify({"error":"User Not Found"}),401
  
  if not check_password_hash(user[1],password):
    return jsonify({"error":"Invalid Password"}),401


  access_token = create_access_token(identity=str(user[0]))
  return jsonify({"message":"Login Successfully","access_token":access_token}),200

@app.route('/api/private',methods=["GET"])
@jwt_required()
def private():
  user_id = get_jwt_identity()
  return jsonify({"message":"Access Granted","user_id":user_id}),200


@app.route('/api/debug',methods=["POST"])
@jwt_required()
def debug():
  user_id = get_jwt_identity()
  data = request.get_json()
  raw_code = data.get("raw_code")
  error_log = data.get("error_log")
  if not raw_code:
    return jsonify({"error":"All fields are required"}),400
  ai_response = ask_ai(raw_code, error_log)
  conn = get_conn()
  conn.execute("INSERT INTO history(user_id, raw_code, error_log, ai_response) VALUES(?,?,?,?)",(user_id,raw_code,error_log,ai_response))
  conn.commit()
  conn.close()

  return jsonify({"message": "Debug successfully","response":ai_response}),200




@app.route('/api/history',methods=["GET"])
@jwt_required()
def history():
  user_id = get_jwt_identity()
  conn = get_conn()
  cursor = conn.execute("SELECT id, raw_code, error_log, ai_response, created_at FROM history WHERE user_id = ? ORDER BY id DESC",(user_id,))
  rows = cursor.fetchall()
  conn.close()

  history_list = []
  for row in rows:
      history_list.append({
          "id": row[0],
          "raw_code": row[1],
          "error_log": row[2],
          "ai_response": row[3],
          "created_at": row[4]
      })
  
  return jsonify(history_list)


if __name__ == "__main__":
  app.run(debug=True)