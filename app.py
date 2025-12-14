from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, time
import os
import secrets
import csv
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(16))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    last_sync = db.Column(db.DateTime)
    resumption_time = db.Column(db.Time, default=time(8, 0))
    closing_time = db.Column(db.Time, default=time(17, 0))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'))

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    active = db.Column(db.Boolean, default=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    staff_name = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    action = db.Column(db.String(10), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

BASE = '''<!DOCTYPE html>
<html>
<head>
<title>Staff Attendance</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Arial,sans-serif;background:#f5f5f5;color:#333}
.nav{background:#c41e3a;padding:1rem 2rem;display:flex;justify-content:space-between;align-items:center}
.nav-brand{color:white;font-size:1.3rem;font-weight:bold}
.nav-links a{color:white;text-decoration:none;margin-left:1rem;padding:0.5rem}
.nav-links a:hover{background:rgba(255,255,255,0.2);border-radius:4px}
.container{max-width:1200px;margin:0 auto;padding:2rem}
.card{background:white;border-radius:8px;padding:1.5rem;margin-bottom:1.5rem;box-shadow:0 2px 4px rgba(0,0,0,0.1)}
.btn{padding:0.6rem 1.2rem;border:none;border-radius:5px;cursor:pointer;text-decoration:none;display:inline-block;font-size:0.9rem}
.btn-primary{background:#c41e3a;color:white}
.btn-secondary{background:#6c757d;color:white}
.btn-success{background:#28a745;color:white}
.btn-danger{background:#dc3545;color:white}
.btn-sm{padding:0.4rem 0.8rem;font-size:0.85rem}
table{width:100%;border-collapse:collapse;margin-top:1rem}
th,td{padding:0.8rem;text-align:left;border-bottom:1px solid #ddd}
th{background:#f8f9fa;font-weight:600}
.form-group{margin-bottom:1rem}
.form-group label{display:block;margin-bottom:0.4rem;font-weight:500}
.form-group input,.form-group select{width:100%;padding:0.7rem;border:1px solid #ddd;border-radius:5px}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin-bottom:1.5rem}
.stat-card{background:white;padding:1.2rem;border-radius:8px;text-align:center;box-shadow:0 2px 4px rgba(0,0,0,0.1)}
.stat-card h3{font-size:2rem;color:#c41e3a}
.stat-card p{color:#666;margin-top:0.3rem}
.badge{padding:0.3rem 0.6rem;border-radius:20px;font-size:0.8rem}
.badge-success{background:#d4edda;color:#155724}
.badge-danger{background:#f8d7da;color:#721c24}
.badge-secondary{background:#e9ecef;color:#6c757d}
.filter-bar{display:flex;gap:1rem;align-items:flex-end;flex-wrap:wrap;margin-bottom:1rem;padding:1rem;background:white;border-radius:8px}
.filter-bar .form-group{margin-bottom:0}
.page-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;flex-wrap:wrap;gap:1rem}
.time-box{font-family:monospace;background:#f0f0f0;padding:0.3rem 0.6rem;border-radius:4px}
.alert{padding:1rem;border-radius:5px;margin-bottom:1rem}
.alert-success{background:#d4edda;color:#155724}
.alert-error{background:#f8d7da;color:#721c24}
</style>
</head>
<body>
{% if current_user.is_authenticated %}
<nav class="nav">
<div class="nav-brand">Staff Attendance System</div>
<div class="nav-links">
<a href="{{ url_for('dashboard') }}">Dashboard</a>
<a href="{{ url_for('today') }}">Today</a>
<a href="{{ url_for('latecomers') }}">Late Staff</a>
<a href="{{ url_for('overtime') }}">Overtime</a>
<a href="{{ url_for('attendance') }}">Reports</a>
<a href="{{ url_for('staff') }}">Staff</a>
{% if current_user.role == 'superadmin' %}
<a href="{{ url_for('schools') }}">Schools</a>
<a href="{{ url_for('admins') }}">Admins</a>
{% endif %}
<a href="{{ url_for('settings') }}">Settings</a>
<a href="{{ url_for('logout') }}">Logout</a>
</div>
</nav>
{% endif %}
<div class="container">
{% with messages = get_flashed_messages(with_categories=true) %}
{% for c, m in messages %}
<div class="alert alert-{{ c }}">{{ m }}</div>
{% endfor %}
{% endwith %}
{% block content %}{% endblock %}
</div>
</body>
</html>'''

LOGIN = '''{% extends "base" %}
{% block content %}
<div style="max-width:400px;margin:3rem auto">
<div class="card" style="text-align:center">
<h2 style="color:#c41e3a;margin-bottom:1.5rem">Staff Attendance System</h2>
<form method="POST">
<div class="form-group"><label>Username</label><input type="text" name="username" required></div>
<div class="form-group"><label>Password</label><input type="password" name="password" required></div>
<button type="submit" class="btn btn-primary" style="width:100%">Login</button>
</form>
</div>
</div>
{% endblock %}'''

DASHBOARD = '''{% extends "base" %}
{% block content %}
<h2 style="margin-bottom:1.5rem">Dashboard</h2>
<div class="stats-grid">
<div class="stat-card"><h3>{{ total_schools }}</h3><p>Schools</p></div>
<div class="stat-card"><h3>{{ total_staff }}</h3><p>Total Staff</p></div>
<div class="stat-card"><h3>{{ on_site }}</h3><p>On Site</p></div>
<div class="stat-card"><h3>{{ today_signins }}</h3><p>Today Sign-ins</p></div>
<div class="stat-card"><h3>{{ late_today }}</h3><p>Late Today</p></div>
</div>
<div class="card">
<h3>Schools Overview</h3>
<table>
<tr><th>School</th><th>Resumption</th><th>Closing</th><th>On Site</th><th>Late</th><th>Last Sync</th></tr>
{% for s in schools %}
<tr>
<td>{{ s.name }}</td>
<td><span class="time-box">{{ s.resumption }}</span></td>
<td><span class="time-box">{{ s.closing }}</span></td>
<td>{{ s.on_site }}</td>
<td><span class="badge {% if s.late > 0 %}badge-danger{% else %}badge-success{% endif %}">{{ s.late }}</span></td>
<td>{{ s.last_sync.strftime('%Y-%m-%d %H:%M') if s.last_sync else 'Never' }}</td>
</tr>
{% else %}
<tr><td colspan="6" style="text-align:center;padding:2rem">No schools configured</td></tr>
{% endfor %}
</table>
</div>
{% endblock %}'''

SCHOOLS = '''{% extends "base" %}
{% block content %}
<div class="page-header">
<h2>Manage Schools</h2>
<a href="{{ url_for('add_school') }}" class="btn btn-primary">+ Add School</a>
</div>
<div class="card">
<table>
<tr><th>Name</th><th>Code</th><th>Resumption</th><th>Closing</th><th>Actions</th></tr>
{% for s in schools %}
<tr>
<td>{{ s.name }}</td>
<td>{{ s.code }}</td>
<td><span class="time-box">{{ s.resumption_time.strftime('%H:%M') if s.resumption_time else '08:00' }}</span></td>
<td><span class="time-box">{{ s.closing_time.strftime('%H:%M') if s.closing_time else '17:00' }}</span></td>
<td>
<a href="{{ url_for('edit_school', id=s.id) }}" class="btn btn-secondary btn-sm">Edit</a>
<a href="{{ url_for('delete_school', id=s.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Delete?')">Delete</a>
</td>
</tr>
{% else %}
<tr><td colspan="5" style="text-align:center;padding:2rem">No schools yet</td></tr>
{% endfor %}
</table>
</div>
{% endblock %}'''

ADD_SCHOOL = '''{% extends "base" %}
{% block content %}
<h2 style="margin-bottom:1.5rem">Add School</h2>
<div class="card" style="max-width:500px">
<form method="POST">
<div class="form-group"><label>School Name</label><input type="text" name="name" required></div>
<div class="form-group"><label>School Code</label><input type="text" name="code" required></div>
<div class="form-group"><label>Resumption Time</label>
<select name="resumption_time">
{% for h in range(5,12) %}
<option value="{{ '%02d:00'|format(h) }}" {% if h==8 %}selected{% endif %}>{{ '%02d:00'|format(h) }}</option>
<option value="{{ '%02d:30'|format(h) }}">{{ '%02d:30'|format(h) }}</option>
{% endfor %}
</select>
</div>
<div class="form-group"><label>Closing Time</label>
<select name="closing_time">
{% for h in range(14,22) %}
<option value="{{ '%02d:00'|format(h) }}" {% if h==17 %}selected{% endif %}>{{ '%02d:00'|format(h) }}</option>
<option value="{{ '%02d:30'|format(h) }}">{{ '%02d:30'|format(h) }}</option>
{% endfor %}
</select>
</div>
<button type="submit" class="btn btn-primary">Add School</button>
<a href="{{ url_for('schools') }}" class="btn btn-secondary">Cancel</a>
</form>
</div>
{% endblock %}'''

EDIT_SCHOOL = '''{% extends "base" %}
{% block content %}
<h2 style="margin-bottom:1.5rem">Edit School</h2>
<div class="card" style="max-width:500px">
<form method="POST">
<div class="form-group"><label>School Name</label><input type="text" name="name" value="{{ school.name }}" required></div>
<div class="form-group"><label>School Code</label><input type="text" value="{{ school.code }}" disabled></div>
<div class="form-group"><label>Resumption Time</label>
<select name="resumption_time">
{% for h in range(5,12) %}
<option value="{{ '%02d:00'|format(h) }}" {% if school.resumption_time and school.resumption_time.hour==h and school.resumption_time.minute==0 %}selected{% endif %}>{{ '%02d:00'|format(h) }}</option>
<option value="{{ '%02d:30'|format(h) }}" {% if school.resumption_time and school.resumption_time.hour==h and school.resumption_time.minute==30 %}selected{% endif %}>{{ '%02d:30'|format(h) }}</option>
{% endfor %}
</select>
</div>
<div class="form-group"><label>Closing Time</label>
<select name="closing_time">
{% for h in range(14,22) %}
<option value="{{ '%02d:00'|format(h) }}" {% if school.closing_time and school.closing_time.hour==h and school.closing_time.minute==0 %}selected{% endif %}>{{ '%02d:00'|format(h) }}</option>
<option value="{{ '%02d:30'|format(h) }}" {% if school.closing_time and school.closing_time.hour==h and school.closing_time.minute==30 %}selected{% endif %}>{{ '%02d:30'|format(h) }}</option>
{% endfor %}
</select>
</div>
<div class="form-group"><label>API Key</label><input type="text" value="{{ school.api_key }}" readonly onclick="this.select()"></div>
<button type="submit" class="btn btn-primary">Save</button>
<a href="{{ url_for('regenerate_key', id=school.id) }}" class="btn btn-secondary" onclick="return confirm('Regenerate?')">New Key</a>
<a href="{{ url_for('schools') }}" class="btn btn-secondary">Cancel</a>
</form>
</div>
{% endblock %}'''

STAFF_LIST = '''{% extends "base" %}
{% block content %}
<div class="page-header">
<h2>Manage Staff</h2>
<a href="{{ url_for('add_staff') }}" class="btn btn-primary">+ Add Staff</a>
</div>
<div class="filter-bar">
<form method="GET" style="display:flex;gap:1rem;align-items:flex-end">
<div class="form-group"><label>School</label>
<select name="school" onchange="this.form.submit()">
<option value="">All Schools</option>
{% for s in schools %}<option value="{{ s.id }}" {% if selected_school==s.id %}selected{% endif %}>{{ s.name }}</option>{% endfor %}
</select>
</div>
</form>
</div>
<div class="card">
<table>
<tr><th>Staff ID</th><th>Name</th><th>Department</th><th>School</th><th>Status</th><th>Actions</th></tr>
{% for s in staff %}
<tr>
<td>{{ s.staff_id }}</td>
<td>{{ s.name }}</td>
<td>{{ s.department or '-' }}</td>
<td>{{ s.school.name }}</td>
<td><span class="badge {% if s.active %}badge-success{% else %}badge-secondary{% endif %}">{{ 'Active' if s.active else 'Inactive' }}</span></td>
<td>
<a href="{{ url_for('toggle_staff', id=s.id) }}" class="btn btn-secondary btn-sm">Toggle</a>
<a href="{{ url_for('delete_staff', id=s.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Delete?')">Delete</a>
</td>
</tr>
{% else %}
<tr><td colspan="6" style="text-align:center;padding:2rem">No staff members</td></tr>
{% endfor %}
</table>
</div>
{% endblock %}'''

ADD_STAFF = '''{% extends "base" %}
{% block content %}
<h2 style="margin-bottom:1.5rem">Add Staff</h2>
<div class="card" style="max-width:500px">
<form method="POST">
<div class="form-group"><label>School</label>
<select name="school_id" required>
{% for s in schools %}<option value="{{ s.id }}">{{ s.name }}</option>{% endfor %}
</select>
</div>
<div class="form-group"><label>Staff ID</label><input type="text" name="staff_id" required></div>
<div class="form-group"><label>Full Name</label><input type="text" name="name" required></div>
<div class="form-group"><label>Department</label><input type="text" name="department"></div>
<button type="submit" class="btn btn-primary">Add Staff</button>
<a href="{{ url_for('staff') }}" class="btn btn-secondary">Cancel</a>
</form>
</div>
{% endblock %}'''

LATE = '''{% extends "base" %}
{% block content %}
<div class="page-header">
<h2>Late Staff Report</h2>
<a href="{{ url_for('download_latecomers', school=selected_school or '', date=selected_date) }}" class="btn btn-success">Download CSV</a>
</div>
<div class="filter-bar">
<form method="GET" style="display:flex;gap:1rem;align-items:flex-end;flex-wrap:wrap">
<div class="form-group"><label>School</label>
<select name="school">
<option value="">All Schools</option>
{% for s in schools %}<option value="{{ s.id }}" {% if selected_school==s.id %}selected{% endif %}>{{ s.name }}</option>{% endfor %}
</select>
</div>
<div class="form-group"><label>Date</label><input type="date" name="date" value="{{ selected_date }}"></div>
<button type="submit" class="btn btn-primary">Filter</button>
</form>
</div>
<div class="card">
<table>
<tr><th>Staff ID</th><th>Name</th><th>School</th><th>Resumption</th><th>Arrival</th><th>Late By</th></tr>
{% for r in records %}
<tr>
<td>{{ r.staff_id }}</td>
<td>{{ r.name }}</td>
<td>{{ r.school }}</td>
<td><span class="time-box">{{ r.resumption }}</span></td>
<td><span class="time-box">{{ r.arrival }}</span></td>
<td><span class="badge badge-danger">{{ r.late_by }}</span></td>
</tr>
{% else %}
<tr><td colspan="6" style="text-align:center;padding:2rem">No late arrivals</td></tr>
{% endfor %}
</table>
</div>
{% endblock %}'''

OVERTIME = '''{% extends "base" %}
{% block content %}
<div class="page-header">
<h2>Overtime Report</h2>
<a href="{{ url_for('download_overtime', school=selected_school or '', from_date=from_date, to_date=to_date) }}" class="btn btn-success">Download CSV</a>
</div>
<div class="filter-bar">
<form method="GET" style="display:flex;gap:1rem;align-items:flex-end;flex-wrap:wrap">
<div class="form-group"><label>School</label>
<select name="school">
<option value="">All Schools</option>
{% for s in schools %}<option value="{{ s.id }}" {% if selected_school==s.id %}selected{% endif %}>{{ s.name }}</option>{% endfor %}
</select>
</div>
<div class="form-group"><label>From</label><input type="date" name="from_date" value="{{ from_date }}"></div>
<div class="form-group"><label>To</label><input type="date" name="to_date" value="{{ to_date }}"></div>
<button type="submit" class="btn btn-primary">Filter</button>
</form>
</div>
<div class="stat-card" style="max-width:200px;margin-bottom:1rem"><h3>{{ total_overtime }}</h3><p>Total Overtime</p></div>
<div class="card">
<table>
<tr><th>Staff ID</th><th>Name</th><th>School</th><th>Days</th><th>Overtime</th></tr>
{% for r in records %}
<tr>
<td>{{ r.staff_id }}</td>
<td>{{ r.name }}</td>
<td>{{ r.school }}</td>
<td>{{ r.days_worked }}</td>
<td><span class="badge badge-success">{{ r.overtime_hours }}h {{ r.overtime_mins }}m</span></td>
</tr>
{% else %}
<tr><td colspan="5" style="text-align:center;padding:2rem">No overtime records</td></tr>
{% endfor %}
</table>
</div>
{% endblock %}'''

ATTENDANCE = '''{% extends "base" %}
{% block content %}
<div class="page-header">
<h2>Attendance Reports</h2>
<a href="{{ url_for('download_attendance', school=selected_school or '', from_date=from_date, to_date=to_date) }}" class="btn btn-success">Download CSV</a>
</div>
<div class="filter-bar">
<form method="GET" style="display:flex;gap:1rem;align-items:flex-end;flex-wrap:wrap">
<div class="form-group"><label>School</label>
<select name="school">
<option value="">All Schools</option>
{% for s in schools %}<option value="{{ s.id }}" {% if selected_school==s.id %}selected{% endif %}>{{ s.name }}</option>{% endfor %}
</select>
</div>
<div class="form-group"><label>From</label><input type="date" name="from_date" value="{{ from_date }}"></div>
<div class="form-group"><label>To</label><input type="date" name="to_date" value="{{ to_date }}"></div>
<button type="submit" class="btn btn-primary">Filter</button>
</form>
</div>
<div class="card">
<table>
<tr><th>Date</th><th>Staff ID</th><th>Name</th><th>School</th><th>First In</th><th>Last Out</th></tr>
{% for r in records %}
<tr>
<td>{{ r.date }}</td>
<td>{{ r.staff_id }}</td>
<td>{{ r.name }}</td>
<td>{{ r.school }}</td>
<td><span class="time-box">{{ r.first_in or '-' }}</span></td>
<td><span class="time-box">{{ r.last_out or '-' }}</span></td>
</tr>
{% else %}
<tr><td colspan="6" style="text-align:center;padding:2rem">No records</td></tr>
{% endfor %}
</table>
</div>
{% endblock %}'''

TODAY = '''{% extends "base" %}
{% block content %}
<h2 style="margin-bottom:1.5rem">Today's Activity</h2>
<div class="filter-bar">
<form method="GET" style="display:flex;gap:1rem;align-items:flex-end">
<div class="form-group"><label>School</label>
<select name="school" onchange="this.form.submit()">
<option value="">All Schools</option>
{% for s in schools %}<option value="{{ s.id }}" {% if selected_school==s.id %}selected{% endif %}>{{ s.name }}</option>{% endfor %}
</select>
</div>
</form>
</div>
<div class="card">
<table>
<tr><th>Time</th><th>Staff ID</th><th>Name</th><th>School</th><th>Action</th></tr>
{% for r in records %}
<tr>
<td><span class="time-box">{{ r.timestamp.strftime('%H:%M:%S') }}</span></td>
<td>{{ r.staff_id }}</td>
<td>{{ r.staff_name }}</td>
<td>{{ r.school.name }}</td>
<td><span class="badge {% if r.action=='IN' %}badge-success{% else %}badge-secondary{% endif %}">{{ r.action }}</span></td>
</tr>
{% else %}
<tr><td colspan="5" style="text-align:center;padding:2rem">No activity today</td></tr>
{% endfor %}
</table>
</div>
{% endblock %}'''

ADMINS = '''{% extends "base" %}
{% block content %}
<h2 style="margin-bottom:1.5rem">Manage Admins</h2>
<div class="card" style="max-width:500px;margin-bottom:1.5rem">
<h3 style="margin-bottom:1rem">Add Admin</h3>
<form method="POST">
<div class="form-group"><label>Username</label><input type="text" name="username" required></div>
<div class="form-group"><label>Password</label><input type="password" name="password" required></div>
<div class="form-group"><label>Role</label>
<select name="role" id="role" onchange="document.getElementById('sg').style.display=this.value=='schooladmin'?'block':'none'">
<option value="superadmin">Super Admin</option>
<option value="schooladmin">School Admin</option>
</select>
</div>
<div class="form-group" id="sg" style="display:none"><label>School</label>
<select name="school_id">{% for s in schools %}<option value="{{ s.id }}">{{ s.name }}</option>{% endfor %}</select>
</div>
<button type="submit" class="btn btn-primary">Add Admin</button>
</form>
</div>
<div class="card">
<h3 style="margin-bottom:1rem">Current Admins</h3>
<table>
<tr><th>Username</th><th>Role</th><th>School</th><th>Actions</th></tr>
{% for u in users %}
<tr>
<td>{{ u.username }}</td>
<td>{{ u.role }}</td>
<td>{{ u.school.name if u.school else 'All' }}</td>
<td>{% if u.username != 'admin' %}<a href="{{ url_for('delete_admin', id=u.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Delete?')">Delete</a>{% endif %}</td>
</tr>
{% endfor %}
</table>
</div>
{% endblock %}'''

SETTINGS = '''{% extends "base" %}
{% block content %}
<h2 style="margin-bottom:1.5rem">Settings</h2>
<div class="card" style="max-width:500px">
<h3 style="margin-bottom:1rem">Change Password</h3>
<form method="POST">
<div class="form-group"><label>Current Password</label><input type="password" name="current_password" required></div>
<div class="form-group"><label>New Password</label><input type="password" name="new_password" required></div>
<div class="form-group"><label>Confirm Password</label><input type="password" name="confirm_password" required></div>
<button type="submit" class="btn btn-primary">Change Password</button>
</form>
</div>
{% endblock %}'''

def render(template, **kwargs):
    return render_template_string(template.replace('{% extends "base" %}', '{% extends base %}'), base=BASE, **kwargs)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
    return render(LOGIN)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    schools = School.query.all()
    today_date = datetime.utcnow().date()
    school_data = []
    total_on_site = 0
    total_today = 0
    total_late = 0
    for school in schools:
        records = Attendance.query.filter(Attendance.school_id == school.id, db.func.date(Attendance.timestamp) == today_date).all()
        staff_status = {}
        staff_first_in = {}
        for r in records:
            staff_status[r.staff_id] = r.action
            if r.action == 'IN' and (r.staff_id not in staff_first_in or r.timestamp < staff_first_in[r.staff_id]):
                staff_first_in[r.staff_id] = r.timestamp
        on_site = sum(1 for s in staff_status.values() if s == 'IN')
        total_on_site += on_site
        total_today += len(set(r.staff_id for r in records))
        resumption = school.resumption_time or time(8, 0)
        late_count = sum(1 for t in staff_first_in.values() if t.time() > resumption)
        total_late += late_count
        school_data.append({'name': school.name, 'resumption': resumption.strftime('%H:%M'), 'closing': (school.closing_time or time(17, 0)).strftime('%H:%M'), 'on_site': on_site, 'late': late_count, 'last_sync': school.last_sync})
    return render(DASHBOARD, schools=school_data, total_schools=len(schools), total_staff=Staff.query.filter_by(active=True).count(), on_site=total_on_site, today_signins=total_today, late_today=total_late)

@app.route('/schools')
@login_required
def schools():
    if current_user.role != 'superadmin':
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    return render(SCHOOLS, schools=School.query.all())

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        school = School(name=request.form['name'], code=request.form['code'], api_key=secrets.token_hex(32), resumption_time=datetime.strptime(request.form['resumption_time'], '%H:%M').time(), closing_time=datetime.strptime(request.form['closing_time'], '%H:%M').time())
        db.session.add(school)
        db.session.commit()
        flash('School added', 'success')
        return redirect(url_for('schools'))
    return render(ADD_SCHOOL)

@app.route('/schools/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_school(id):
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    school = School.query.get_or_404(id)
    if request.method == 'POST':
        school.name = request.form['name']
        school.resumption_time = datetime.strptime(request.form['resumption_time'], '%H:%M').time()
        school.closing_time = datetime.strptime(request.form['closing_time'], '%H:%M').time()
        db.session.commit()
        flash('School updated', 'success')
        return redirect(url_for('schools'))
    return render(EDIT_SCHOOL, school=school)

@app.route('/schools/<int:id>/regenerate')
@login_required
def regenerate_key(id):
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    school = School.query.get_or_404(id)
    school.api_key = secrets.token_hex(32)
    db.session.commit()
    flash('API key regenerated', 'success')
    return redirect(url_for('edit_school', id=id))

@app.route('/schools/<int:id>/delete')
@login_required
def delete_school(id):
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    school = School.query.get_or_404(id)
    Attendance.query.filter_by(school_id=id).delete()
    Staff.query.filter_by(school_id=id).delete()
    db.session.delete(school)
    db.session.commit()
    flash('School deleted', 'success')
    return redirect(url_for('schools'))

@app.route('/staff')
@login_required
def staff():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    if current_user.role == 'schooladmin':
        staff_list = Staff.query.filter_by(school_id=current_user.school_id).all()
    elif selected:
        staff_list = Staff.query.filter_by(school_id=selected).all()
    else:
        staff_list = Staff.query.all()
    for s in staff_list:
        s.school = School.query.get(s.school_id)
    return render(STAFF_LIST, staff=staff_list, schools=schools, selected_school=selected)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    schools = School.query.all() if current_user.role == 'superadmin' else [School.query.get(current_user.school_id)]
    if request.method == 'POST':
        s = Staff(staff_id=request.form['staff_id'], name=request.form['name'], department=request.form.get('department'), school_id=request.form['school_id'])
        db.session.add(s)
        db.session.commit()
        flash('Staff added', 'success')
        return redirect(url_for('staff'))
    return render(ADD_STAFF, schools=schools)

@app.route('/staff/<int:id>/toggle')
@login_required
def toggle_staff(id):
    s = Staff.query.get_or_404(id)
    s.active = not s.active
    db.session.commit()
    return redirect(url_for('staff'))

@app.route('/staff/<int:id>/delete')
@login_required
def delete_staff(id):
    s = Staff.query.get_or_404(id)
    db.session.delete(s)
    db.session.commit()
    flash('Staff deleted', 'success')
    return redirect(url_for('staff'))

@app.route('/latecomers')
@login_required
def latecomers():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    selected_date = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    query_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    records = []
    school_list = [School.query.get(selected)] if selected else schools
    for school in school_list:
        if not school:
            continue
        resumption = school.resumption_time or time(8, 0)
        day_records = Attendance.query.filter(Attendance.school_id == school.id, db.func.date(Attendance.timestamp) == query_date, Attendance.action == 'IN').all()
        staff_first_in = {}
        for r in day_records:
            if r.staff_id not in staff_first_in or r.timestamp < staff_first_in[r.staff_id]['time']:
                staff_first_in[r.staff_id] = {'time': r.timestamp, 'name': r.staff_name}
        for staff_id, data in staff_first_in.items():
            if data['time'].time() > resumption:
                late_mins = int((datetime.combine(query_date, data['time'].time()) - datetime.combine(query_date, resumption)).total_seconds() // 60)
                records.append({'staff_id': staff_id, 'name': data['name'], 'school': school.name, 'resumption': resumption.strftime('%H:%M'), 'arrival': data['time'].strftime('%H:%M'), 'late_by': f"{late_mins // 60}h {late_mins % 60}m" if late_mins >= 60 else f"{late_mins}m"})
    return render(LATE, records=records, schools=schools, selected_school=selected, selected_date=selected_date)

@app.route('/latecomers/download')
@login_required
def download_latecomers():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    selected_date = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    query_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    records = []
    school_list = [School.query.get(selected)] if selected else schools
    for school in school_list:
        if not school:
            continue
        resumption = school.resumption_time or time(8, 0)
        day_records = Attendance.query.filter(Attendance.school_id == school.id, db.func.date(Attendance.timestamp) == query_date, Attendance.action == 'IN').all()
        staff_first_in = {}
        for r in day_records:
            if r.staff_id not in staff_first_in or r.timestamp < staff_first_in[r.staff_id]['time']:
                staff_first_in[r.staff_id] = {'time': r.timestamp, 'name': r.staff_name}
        for staff_id, data in staff_first_in.items():
            if data['time'].time() > resumption:
                late_mins = int((datetime.combine(query_date, data['time'].time()) - datetime.combine(query_date, resumption)).total_seconds() // 60)
                records.append([staff_id, data['name'], school.name, resumption.strftime('%H:%M'), data['time'].strftime('%H:%M'), f"{late_mins // 60}h {late_mins % 60}m" if late_mins >= 60 else f"{late_mins}m"])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Resumption', 'Arrival', 'Late By'])
    writer.writerows(records)
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=latecomers_{selected_date}.csv'})

@app.route('/overtime')
@login_required
def overtime():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    from_date = request.args.get('from_date', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.utcnow().strftime('%Y-%m-%d'))
    records = []
    total_mins = 0
    school_list = [School.query.get(selected)] if selected else schools
    for school in school_list:
        if not school:
            continue
        closing = school.closing_time or time(17, 0)
        att = Attendance.query.filter(Attendance.school_id == school.id, Attendance.timestamp >= datetime.strptime(from_date, '%Y-%m-%d'), Attendance.timestamp <= datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)).all()
        staff_data = {}
        for r in att:
            if r.staff_id not in staff_data:
                staff_data[r.staff_id] = {'name': r.staff_name, 'days': {}}
            d = r.timestamp.date()
            if d not in staff_data[r.staff_id]['days']:
                staff_data[r.staff_id]['days'][d] = None
            if r.action == 'OUT' and (staff_data[r.staff_id]['days'][d] is None or r.timestamp > staff_data[r.staff_id]['days'][d]):
                staff_data[r.staff_id]['days'][d] = r.timestamp
        for staff_id, data in staff_data.items():
            ot = 0
            days = 0
            for d, last_out in data['days'].items():
                if last_out and last_out.time() > closing:
                    days += 1
                    ot += int((datetime.combine(d, last_out.time()) - datetime.combine(d, closing)).total_seconds() // 60)
            if ot > 0:
                total_mins += ot
                records.append({'staff_id': staff_id, 'name': data['name'], 'school': school.name, 'days_worked': days, 'overtime_hours': ot // 60, 'overtime_mins': ot % 60})
    records.sort(key=lambda x: x['overtime_hours'] * 60 + x['overtime_mins'], reverse=True)
    return render(OVERTIME, records=records, schools=schools, selected_school=selected, from_date=from_date, to_date=to_date, total_overtime=f"{total_mins // 60}h {total_mins % 60}m")

@app.route('/overtime/download')
@login_required
def download_overtime():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    from_date = request.args.get('from_date', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.utcnow().strftime('%Y-%m-%d'))
    records = []
    school_list = [School.query.get(selected)] if selected else schools
    for school in school_list:
        if not school:
            continue
        closing = school.closing_time or time(17, 0)
        att = Attendance.query.filter(Attendance.school_id == school.id, Attendance.timestamp >= datetime.strptime(from_date, '%Y-%m-%d'), Attendance.timestamp <= datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)).all()
        staff_data = {}
        for r in att:
            if r.staff_id not in staff_data:
                staff_data[r.staff_id] = {'name': r.staff_name, 'days': {}}
            d = r.timestamp.date()
            if d not in staff_data[r.staff_id]['days']:
                staff_data[r.staff_id]['days'][d] = None
            if r.action == 'OUT' and (staff_data[r.staff_id]['days'][d] is None or r.timestamp > staff_data[r.staff_id]['days'][d]):
                staff_data[r.staff_id]['days'][d] = r.timestamp
        for staff_id, data in staff_data.items():
            ot = 0
            days = 0
            for d, last_out in data['days'].items():
                if last_out and last_out.time() > closing:
                    days += 1
                    ot += int((datetime.combine(d, last_out.time()) - datetime.combine(d, closing)).total_seconds() // 60)
            if ot > 0:
                records.append([staff_id, data['name'], school.name, days, ot // 60, ot % 60])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Days', 'OT Hours', 'OT Mins'])
    writer.writerows(records)
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=overtime_{from_date}_{to_date}.csv'})

@app.route('/attendance')
@login_required
def attendance():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    from_date = request.args.get('from_date', (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.utcnow().strftime('%Y-%m-%d'))
    query = Attendance.query
    if selected:
        query = query.filter(Attendance.school_id == selected)
    query = query.filter(Attendance.timestamp >= datetime.strptime(from_date, '%Y-%m-%d'), Attendance.timestamp <= datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1))
    raw = query.order_by(Attendance.timestamp.desc()).all()
    grouped = {}
    for r in raw:
        key = (r.timestamp.date(), r.staff_id, r.school_id)
        if key not in grouped:
            school = School.query.get(r.school_id)
            grouped[key] = {'date': r.timestamp.strftime('%Y-%m-%d'), 'staff_id': r.staff_id, 'name': r.staff_name, 'school': school.name if school else 'Unknown', 'first_in': None, 'last_out': None}
        if r.action == 'IN' and (grouped[key]['first_in'] is None or r.timestamp.strftime('%H:%M') < grouped[key]['first_in']):
            grouped[key]['first_in'] = r.timestamp.strftime('%H:%M')
        if r.action == 'OUT' and (grouped[key]['last_out'] is None or r.timestamp.strftime('%H:%M') > grouped[key]['last_out']):
            grouped[key]['last_out'] = r.timestamp.strftime('%H:%M')
    records = sorted(grouped.values(), key=lambda x: x['date'], reverse=True)
    return render(ATTENDANCE, records=records, schools=schools, selected_school=selected, from_date=from_date, to_date=to_date)

@app.route('/attendance/download')
@login_required
def download_attendance():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    from_date = request.args.get('from_date', (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.utcnow().strftime('%Y-%m-%d'))
    query = Attendance.query
    if selected:
        query = query.filter(Attendance.school_id == selected)
    query = query.filter(Attendance.timestamp >= datetime.strptime(from_date, '%Y-%m-%d'), Attendance.timestamp <= datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1))
    raw = query.order_by(Attendance.timestamp.desc()).all()
    grouped = {}
    for r in raw:
        key = (r.timestamp.date(), r.staff_id, r.school_id)
        if key not in grouped:
            school = School.query.get(r.school_id)
            grouped[key] = {'date': r.timestamp.strftime('%Y-%m-%d'), 'staff_id': r.staff_id, 'name': r.staff_name, 'school': school.name if school else 'Unknown', 'first_in': None, 'last_out': None}
        if r.action == 'IN' and (grouped[key]['first_in'] is None or r.timestamp.strftime('%H:%M') < grouped[key]['first_in']):
            grouped[key]['first_in'] = r.timestamp.strftime('%H:%M')
        if r.action == 'OUT' and (grouped[key]['last_out'] is None or r.timestamp.strftime('%H:%M') > grouped[key]['last_out']):
            grouped[key]['last_out'] = r.timestamp.strftime('%H:%M')
    records = sorted(grouped.values(), key=lambda x: x['date'], reverse=True)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'School', 'First In', 'Last Out'])
    for r in records:
        writer.writerow([r['date'], r['staff_id'], r['name'], r['school'], r['first_in'] or '', r['last_out'] or ''])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=attendance_{from_date}_{to_date}.csv'})

@app.route('/today')
@login_required
def today():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    today_date = datetime.utcnow().date()
    query = Attendance.query.filter(db.func.date(Attendance.timestamp) == today_date)
    if selected:
        query = query.filter(Attendance.school_id == selected)
    records = query.order_by(Attendance.timestamp.desc()).all()
    for r in records:
        r.school = School.query.get(r.school_id)
    return render(TODAY, records=records, schools=schools, selected_school=selected)

@app.route('/admins', methods=['GET', 'POST'])
@login_required
def admins():
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        school_id = request.form.get('school_id') if request.form['role'] == 'schooladmin' else None
        user = User(username=request.form['username'], password_hash=generate_password_hash(request.form['password']), role=request.form['role'], school_id=school_id)
        db.session.add(user)
        db.session.commit()
        flash('Admin added', 'success')
    users = User.query.all()
    for u in users:
        u.school = School.query.get(u.school_id) if u.school_id else None
    return render(ADMINS, users=users, schools=School.query.all())

@app.route('/admins/<int:id>/delete')
@login_required
def delete_admin(id):
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(id)
    if user.username != 'admin':
        db.session.delete(user)
        db.session.commit()
        flash('Admin deleted', 'success')
    return redirect(url_for('admins'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        if check_password_hash(current_user.password_hash, request.form['current_password']):
            if request.form['new_password'] == request.form['confirm_password']:
                current_user.password_hash = generate_password_hash(request.form['new_password'])
                db.session.commit()
                flash('Password changed', 'success')
            else:
                flash('Passwords do not match', 'error')
        else:
            flash('Current password incorrect', 'error')
    return render(SETTINGS)

@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    school = School.query.filter_by(api_key=api_key).first()
    if not school:
        return jsonify({'error': 'Invalid API key'}), 401
    data = request.get_json()
    for record in data.get('attendance', []):
        att = Attendance(staff_id=record['staff_id'], staff_name=record.get('staff_name'), school_id=school.id, timestamp=datetime.fromisoformat(record['timestamp']), action=record['action'])
        db.session.add(att)
    school.last_sync = datetime.utcnow()
    db.session.commit()
    staff_list = [{'staff_id': s.staff_id, 'name': s.name, 'active': s.active} for s in Staff.query.filter_by(school_id=school.id).all()]
    return jsonify({'status': 'ok', 'staff': staff_list})

@app.route('/api/check')
def api_check():
    api_key = request.headers.get('X-API-Key')
    school = School.query.filter_by(api_key=api_key).first()
    if school:
        return jsonify({'status': 'ok', 'school': school.name})
    return jsonify({'error': 'Invalid API key'}), 401

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', password_hash=generate_password_hash('admin123'), role='superadmin'))
        db.session.commit()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
