import os
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
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

# ── Mail config (Google Workspace / Gmail SMTP) ──────────────────────────────
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

db = SQLAlchemy(app)
mail = Mail(app)


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
    import traceback
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
        except Exception as db_err:
            db.session.rollback()
            print(f'[WARN] Database save failed: {db_err}')
            print(traceback.format_exc())
            # Continue anyway — still try to send email

        # Send email notification
        try:
            recipient = 'sales@dbmgroups.com'
            subject = f'New Contact Form Submission – {data.get("name", "Unknown")}'
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

            msg = Message(subject=subject, recipients=[recipient], body=body)
            mail.send(msg)
        except Exception as mail_err:
            print(f'[WARN] Email send failed: {mail_err}')
            print(traceback.format_exc())
            return jsonify({
                'success': True,
                'message': 'Your message was saved, but email notification failed. We will still get back to you!'
            })

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
