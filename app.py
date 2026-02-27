import os
import threading
import traceback
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── Database config ──────────────────────────────────────────────────────────
database_url = os.getenv('DATABASE_URL', 'sqlite:///contacts.db')
# Render uses 'postgres://' but SQLAlchemy needs 'postgresql://'
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-me-in-production')

db = SQLAlchemy(app)


# ── Model ─────────────────────────────────────────────────────────────────────
class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30))
    company = db.Column(db.String(120))
    service = db.Column(db.String(80))
    message = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Contact {self.name} – {self.email}>'


# ── Email helper (Resend HTTP API – works on Render free tier) ────────────────
def send_email_background(subject, recipient, body):
    """Send email via Resend HTTP API in a background thread."""
    import urllib.request
    import urllib.error
    import json as jsonlib

    api_key = os.getenv('RESEND_API_KEY')
    from_email = os.getenv('FROM_EMAIL', 'onboarding@resend.dev')

    if not api_key:
        print('[WARN] RESEND_API_KEY not set — skipping email.')
        return

    try:
        print(f'[DEBUG] Sending email: from={from_email}, to={recipient}, key={api_key[:8]}...')
        payload = jsonlib.dumps({
            'from': from_email,
            'to': [recipient],
            'subject': subject,
            'text': body
        }).encode('utf-8')

        req = urllib.request.Request(
            'https://api.resend.com/emails',
            data=payload,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'User-Agent': 'DBMG-Website/1.0'
            }
        )
        response = urllib.request.urlopen(req, timeout=10)
        print(f'[INFO] Email sent to {recipient} (status {response.status})')
    except urllib.error.HTTPError as http_err:
        error_body = http_err.read().decode('utf-8', errors='replace')
        print(f'[WARN] Email send failed: {http_err.code} {http_err.reason}')
        print(f'[WARN] Resend error details: {error_body}')
    except Exception as e:
        print(f'[WARN] Email send failed: {e}')
        print(traceback.format_exc())


# ── Serve static site files ───────────────────────────────────────────────────
SITE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/')
def serve_index():
    return send_from_directory(SITE_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_file(filename):
    return send_from_directory(SITE_DIR, filename)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/submit-contact', methods=['POST'])
def submit_contact():
    try:
        data = request.get_json()

        # Basic validation
        required = ['name', 'email', 'message']
        for field in required:
            if not data.get(field, '').strip():
                return jsonify({'success': False, 'message': f'"{field}" is required.'}), 400

        # Save to database
        try:
            contact = Contact(
                name=data.get('name', '').strip(),
                email=data.get('email', '').strip(),
                phone=data.get('phone', '').strip(),
                company=data.get('company', '').strip(),
                service=data.get('service', '').strip(),
                message=data.get('message', '').strip(),
            )
            db.session.add(contact)
            db.session.commit()
            print(f'[INFO] Contact saved: {contact.name} ({contact.email})')
        except Exception as db_err:
            db.session.rollback()
            print(f'[WARN] Database save failed: {db_err}')
            print(traceback.format_exc())

        # Send email in background thread (won't block the response)
        import random
        import string
        unique_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        subject = f'New Contact Form Submission – {data.get("name", "Unknown")} [{unique_id}]'
        body = f"""
New contact form submission received on DBM GROUPS website.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Name     : {data.get('name', 'N/A')}
  Email    : {data.get('email', 'N/A')}
  Phone    : {data.get('phone', 'N/A') or 'N/A'}
  Company  : {data.get('company', 'N/A') or 'N/A'}
  Service  : {data.get('service', 'N/A') or 'N/A'}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Message:
{data.get('message', 'N/A')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """.strip()

        email_thread = threading.Thread(
            target=send_email_background,
            args=(subject, os.getenv('NOTIFY_EMAIL', 'sales@dbmgroups.com'), body)
        )
        email_thread.start()

        return jsonify({'success': True, 'message': 'Thank you! Your message has been sent successfully.'})

    except Exception as e:
        print(f'[ERROR] submit_contact crashed: {e}')
        print(traceback.format_exc())
        return jsonify({'success': False, 'message': 'Server error. Please try again later.'}), 500


# ── Admin: view all submissions (optional) ────────────────────────────────────
@app.route('/contacts', methods=['GET'])
def list_contacts():
    contacts = Contact.query.order_by(Contact.submitted_at.desc()).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'email': c.email,
        'phone': c.phone,
        'company': c.company,
        'service': c.service,
        'message': c.message,
        'submitted_at': c.submitted_at.isoformat()
    } for c in contacts])


# Create database tables on startup (works with both gunicorn and python app.py)
with app.app_context():
    db.create_all()
    print('Database tables created OK.')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
