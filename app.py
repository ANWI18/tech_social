import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = 'hackathon_secret_key'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def get_db_connection():
    db_url = os.environ.get('SUPABASE_DB_URL')
    if not db_url:
        raise ValueError("SUPABASE_DB_URL is not set in Environment Variables")
    return psycopg2.connect(db_url.strip())

@app.route('/init-db')
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, hobbies TEXT, bio TEXT, profile_pic TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS posts (id SERIAL PRIMARY KEY, user_id INTEGER, content TEXT, image_url TEXT)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages 
                          (id SERIAL PRIMARY KEY, sender_id INTEGER, receiver_id INTEGER, 
                           message TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_read INTEGER DEFAULT 0)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS calendar_events (id SERIAL PRIMARY KEY, user_id INTEGER, event_text TEXT, event_date TEXT, username TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS wallet_transactions (id SERIAL PRIMARY KEY, user_id INTEGER, username TEXT, amount REAL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cursor.execute('CREATE TABLE IF NOT EXISTS withdrawal_requests (id SERIAL PRIMARY KEY, requester_id INTEGER, username TEXT, amount REAL, reason TEXT, status TEXT DEFAULT \'pending\')')
        cursor.execute('CREATE TABLE IF NOT EXISTS votes (id SERIAL PRIMARY KEY, request_id INTEGER, user_id INTEGER, UNIQUE(request_id, user_id))')
        cursor.execute('''CREATE TABLE IF NOT EXISTS notifications 
                          (id SERIAL PRIMARY KEY, user_id INTEGER, 
                           content TEXT, is_read INTEGER DEFAULT 0)''')
        conn.commit()
        cursor.close()
        conn.close()
        return "✅ SUCCESS: Database Initialized Successfully!"
    except Exception as e:
        return f"❌ DATABASE CRASH: {str(e)}", 500

@app.context_processor
def inject_unread():
    if 'user_id' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM messages WHERE receiver_id = %s AND is_read = 0', (session['user_id'],))
        m_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = 0', (session['user_id'],))
        n_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return dict(unread_msgs=m_count, unread_notifs=n_count)
    return dict(unread_msgs=0, unread_notifs=0)

@app.route('/')
def home():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT users.username, posts.content, posts.id, posts.user_id, users.profile_pic, posts.image_url FROM posts JOIN users ON posts.user_id = users.id ORDER BY posts.id DESC')
    posts = cursor.fetchall()
    cursor.execute('SELECT id, username, profile_pic FROM users WHERE id != %s', (session['user_id'],))
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('feed.html', posts=posts, users=users)

@app.route('/post', methods=['POST'])
def post():
    if 'user_id' not in session: return redirect(url_for('login'))
    content = request.form.get('content')
    file = request.files.get('image_file')
    file_path = None
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        file_path = f"/static/uploads/{filename}"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO posts (user_id, content, image_url) VALUES (%s, %s, %s)', (session['user_id'], content, file_path))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('home'))

@app.route('/calendar', methods=['GET', 'POST'])
def calendar():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        task, date = request.form.get('event_text'), request.form.get('event_date')
        if task and date:
            cursor.execute('INSERT INTO calendar_events (user_id, event_text, event_date, username) VALUES (%s, %s, %s, %s)', (session['user_id'], task, date, session['username']))
            cursor.execute('SELECT id FROM users WHERE id != %s', (session['user_id'],))
            others = cursor.fetchall()
            for u in others:
                cursor.execute('INSERT INTO notifications (user_id, content) VALUES (%s, %s)', (u[0], f"New Squad Event: {task}"))
            conn.commit()
        return redirect(url_for('calendar'))
    
    cursor.execute('UPDATE notifications SET is_read = 1 WHERE user_id = %s AND content LIKE %s', (session['user_id'], 'New Squad Event%'))
    conn.commit()
    # Added 'id' and 'user_id' to select so delete button works
    cursor.execute('SELECT event_text, event_date, username, id, user_id FROM calendar_events ORDER BY event_date ASC')
    events = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('calendar.html', events=events)

@app.route('/delete_task/<int:task_id>')
def delete_task(task_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM calendar_events WHERE id = %s AND user_id = %s', (task_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('calendar'))

@app.route('/messages/<int:receiver_id>', methods=['GET', 'POST'])
@app.route('/chat/<int:receiver_id>', methods=['GET', 'POST'])
def chat(receiver_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        msg = request.form.get('message', '').strip()
        if msg:
            cursor.execute('INSERT INTO messages (sender_id, receiver_id, message) VALUES (%s, %s, %s)', (session['user_id'], receiver_id, msg))
            conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('chat', receiver_id=receiver_id))

    cursor.execute('UPDATE messages SET is_read = 1 WHERE sender_id = %s AND receiver_id = %s', (receiver_id, session['user_id']))
    conn.commit()
    cursor.execute('SELECT sender_id, message, id FROM messages WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s) ORDER BY timestamp ASC', (session['user_id'], receiver_id, receiver_id, session['user_id']))
    chats = cursor.fetchall()
    cursor.execute('SELECT username FROM users WHERE id = %s', (receiver_id,))
    receiver = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('chat.html', chats=chats, receiver=receiver, receiver_id=receiver_id)

@app.route('/delete_message/<int:msg_id>/<int:receiver_id>')
def delete_message(msg_id, receiver_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM messages WHERE id = %s AND sender_id = %s', (msg_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('chat', receiver_id=receiver_id))

@app.route('/wallet', methods=['GET', 'POST'])
def wallet():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        amt = request.form.get('pitch_amount')
        if amt:
            cursor.execute('INSERT INTO wallet_transactions (user_id, username, amount) VALUES (%s, %s, %s)', (session['user_id'], session['username'], float(amt)))
            conn.commit()
    cursor.execute('UPDATE notifications SET is_read = 1 WHERE user_id = %s AND content LIKE %s', (session['user_id'], '%requested money%'))
    conn.commit()
    cursor.execute('SELECT SUM(amount) FROM wallet_transactions')
    total = cursor.fetchone()[0] or 0
    cursor.execute('SELECT SUM(amount) FROM wallet_transactions WHERE user_id = %s', (session['user_id'],))
    personal = cursor.fetchone()[0] or 0
    cursor.execute('SELECT username, amount, timestamp FROM wallet_transactions ORDER BY id DESC LIMIT 5')
    history = cursor.fetchall()
    cursor.execute('SELECT id, requester_id, username, amount, reason, status FROM withdrawal_requests ORDER BY id DESC')
    raw_requests = cursor.fetchall()
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    formatted_requests = []
    for r in raw_requests:
        cursor.execute('SELECT COUNT(*) FROM votes WHERE request_id = %s', (r[0],))
        v_count = cursor.fetchone()[0]
        formatted_requests.append({'id': r[0], 'requester_id': r[1], 'user': r[2], 'amount': r[3], 'reason': r[4], 'status': r[5], 'votes': v_count})
    cursor.close()
    conn.close()
    return render_template('wallet.html', balance=total, personal=personal, history=history, requests=formatted_requests, total_users=total_users)

@app.route('/request_money', methods=['POST'])
def request_money():
    if 'user_id' not in session: return redirect(url_for('login'))
    amt, reason = request.form.get('amount'), request.form.get('reason')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO withdrawal_requests (requester_id, username, amount, reason) VALUES (%s, %s, %s, %s)', (session['user_id'], session['username'], float(amt), reason))
    cursor.execute('SELECT id FROM users WHERE id != %s', (session['user_id'],))
    others = cursor.fetchall()
    for u in others:
        cursor.execute('INSERT INTO notifications (user_id, content) VALUES (%s, %s)', (u[0], f"{session['username']} requested money!"))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('wallet'))

@app.route('/delete_proposal/<int:proposal_id>')
def delete_proposal(proposal_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    # Corrected table name and column name based on init-db
    cursor.execute('DELETE FROM withdrawal_requests WHERE id = %s AND requester_id = %s', (proposal_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('wallet'))

@app.route('/vote/<int:request_id>')
def vote(request_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO votes (request_id, user_id) VALUES (%s, %s)', (request_id, session['user_id']))
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM votes WHERE request_id = %s', (request_id,))
        vote_count = cursor.fetchone()[0]
        if vote_count >= (total_users * 0.66):
            cursor.execute('SELECT amount, status FROM withdrawal_requests WHERE id = %s', (request_id,))
            req = cursor.fetchone()
            if req[1] == 'pending':
                cursor.execute('UPDATE withdrawal_requests SET status = %s WHERE id = %s', ('approved', request_id))
                cursor.execute('INSERT INTO wallet_transactions (user_id, username, amount) VALUES (0, %s, %s)', ('SYSTEM_PAYOUT', -float(req[0])))
        conn.commit()
    except: pass
    cursor.close()
    conn.close()
    return redirect(url_for('wallet'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        un, pw = request.form['username'], request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = %s AND password = %s', (un, pw))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user:
            session['user_id'], session['username'] = user[0], user[1]
            return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        un, pw, hb = request.form['username'], request.form['password'], request.form['hobbies']
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO users (username, password, hobbies, profile_pic) VALUES (%s, %s, %s, %s)', (un, pw, hb, 'https://cdn-icons-png.flaticon.com/512/149/149071.png'))
            conn.commit()
            return redirect(url_for('login'))
        except: return "Error!"
        finally: 
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/delete/<int:post_id>')
def delete_post(post_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM posts WHERE id = %s AND user_id = %s', (post_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('home'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        bio = request.form.get('bio')
        pfp = request.form.get('profile_pic')
        cursor.execute('UPDATE users SET bio = %s, profile_pic = %s WHERE id = %s', (bio, pfp, session['user_id']))
        conn.commit()
        return redirect(url_for('home'))
    cursor.execute('SELECT username, bio, profile_pic, hobbies FROM users WHERE id = %s', (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template('settings.html', user=user)
@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Delete the user from the database
    cursor.execute('DELETE FROM users WHERE id = %s', (session['user_id'],))
    
    # Note: If you want to delete their posts and messages too, 
    # you'd add DELETE queries for those tables here as well.
    
    conn.commit()
    cursor.close()
    conn.close()
    
    # 2. Clear the session to log them out
    session.clear()
    return redirect(url_for('register'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)

