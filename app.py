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
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://postgres:bigdaddy8624@db.ytavcjojzfbshstoewmc.supabase.co:5432/postgres')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    last_sync = db.Column(db.DateTime)
    resumption_time = db.Column(db.Time, default=time(8, 0))  # Default 8:00 AM
    closing_time = db.Column(db.Time, default=time(17, 0))    # Default 5:00 PM
    staff = db.relationship('Staff', backref='school', lazy=True)
    attendance = db.relationship('Attendance', backref='school', lazy=True)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'))
    school = db.relationship('School', backref='admins')

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    active = db.Column(db.Boolean, default=True)
    __table_args__ = (db.UniqueConstraint('staff_id', 'school_id'),)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    staff_name = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    action = db.Column(db.String(10), nullable=False)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Base template
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}Attendance System{% endblock %}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Arial, sans-serif; background: #f5f5f5; color: #333; }
        .navbar { background: #c41e3a; padding: 0.8rem 2rem; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .navbar-brand { display: flex; align-items: center; gap: 12px; }
        .navbar-brand img { height: 45px; }
        .navbar-brand span { color: white; font-size: 1.3rem; font-weight: 600; }
        .navbar-links { display: flex; gap: 1.5rem; align-items: center; }
        .navbar-links a { color: white; text-decoration: none; font-size: 0.95rem; padding: 0.5rem 0.8rem; border-radius: 4px; transition: background 0.2s; }
        .navbar-links a:hover { background: rgba(255,255,255,0.15); }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .card { background: white; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e8e8e8; }
        .btn { padding: 0.6rem 1.2rem; border: none; border-radius: 5px; cursor: pointer; font-size: 0.9rem; text-decoration: none; display: inline-block; transition: all 0.2s; }
        .btn-primary { background: #c41e3a; color: white; }
        .btn-primary:hover { background: #a01830; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-secondary:hover { background: #545b62; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .btn-info { background: #17a2b8; color: white; }
        .btn-info:hover { background: #138496; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { padding: 0.9rem; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: 600; color: #555; }
        tr:hover { background: #fafafa; }
        .form-group { margin-bottom: 1rem; }
        .form-group label { display: block; margin-bottom: 0.4rem; font-weight: 500; color: #555; }
        .form-group input, .form-group select { width: 100%; padding: 0.7rem; border: 1px solid #ddd; border-radius: 5px; font-size: 0.95rem; }
        .form-group input:focus, .form-group select:focus { outline: none; border-color: #c41e3a; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
        .stat-card { background: white; padding: 1.2rem; border-radius: 8px; text-align: center; border: 1px solid #e8e8e8; }
        .stat-card h3 { font-size: 2rem; color: #c41e3a; }
        .stat-card p { color: #666; margin-top: 0.3rem; }
        .stat-card.warning h3 { color: #ffc107; }
        .stat-card.info h3 { color: #17a2b8; }
        .alert { padding: 1rem; border-radius: 5px; margin-bottom: 1rem; }
        .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .filter-bar { display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap; margin-bottom: 1rem; padding: 1rem; background: white; border-radius: 8px; border: 1px solid #e8e8e8; }
        .filter-bar .form-group { margin-bottom: 0; }
        .badge { padding: 0.3rem 0.6rem; border-radius: 20px; font-size: 0.8rem; }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-secondary { background: #e9ecef; color: #6c757d; }
        .badge-danger { background: #f8d7da; color: #721c24; }
        .badge-info { background: #d1ecf1; color: #0c5460; }
        .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem; }
        .page-header h2 { color: #333; }
        .button-group { display: flex; gap: 0.5rem; flex-wrap: wrap; }
        .time-display { font-family: monospace; background: #f5f5f5; padding: 0.3rem 0.6rem; border-radius: 3px; }
    </style>
</head>
<body>
    {% if current_user.is_authenticated %}
    <nav class="navbar">
        <div class="navbar-brand">
            <img src="https://i.imgur.com/yARMhzG.png" alt="Logo">
            <span>Attendance System</span>
        </div>
        <div class="navbar-links">
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
        {% for category, message in messages %}
        <div class="alert alert-{{ category }}">{{ message }}</div>
        {% endfor %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Login{% endblock %}
{% block content %}
<div style="max-width: 400px; margin: 4rem auto;">
    <div class="card" style="text-align: center;">
        <img src="https://i.imgur.com/yARMhzG.png" alt="Logo" style="height: 80px; margin-bottom: 1rem;">
        <h2 style="margin-bottom: 1.5rem; color: #c41e3a;">Staff Attendance System</h2>
        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit" class="btn btn-primary" style="width: 100%;">Login</button>
        </form>
    </div>
</div>
{% endblock %}
'''

DASHBOARD_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<h2 style="margin-bottom: 1.5rem;">Dashboard</h2>
<div class="stats-grid">
    <div class="stat-card">
        <h3>{{ total_schools }}</h3>
        <p>Total Schools</p>
    </div>
    <div class="stat-card">
        <h3>{{ total_staff }}</h3>
        <p>Total Staff</p>
    </div>
    <div class="stat-card">
        <h3>{{ on_site }}</h3>
        <p>Currently On Site</p>
    </div>
    <div class="stat-card">
        <h3>{{ today_signins }}</h3>
        <p>Sign-ins Today</p>
    </div>
    <div class="stat-card warning">
        <h3>{{ late_today }}</h3>
        <p>Late Today</p>
    </div>
</div>
<div class="card">
    <h3 style="margin-bottom: 1rem;">Schools Overview</h3>
    <table>
        <tr><th>School</th><th>Resumption</th><th>Closing</th><th>On Site</th><th>Late Today</th><th>Last Sync</th></tr>
        {% for school in schools %}
        <tr>
            <td>{{ school.name }}</td>
            <td><span class="time-display">{{ school.resumption }}</span></td>
            <td><span class="time-display">{{ school.closing }}</span></td>
            <td>{{ school.on_site }}</td>
            <td><span class="badge {% if school.late > 0 %}badge-danger{% else %}badge-success{% endif %}">{{ school.late }}</span></td>
            <td>{{ school.last_sync.strftime('%Y-%m-%d %H:%M') if school.last_sync else 'Never' }}</td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

SCHOOLS_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Schools{% endblock %}
{% block content %}
<div class="page-header">
    <h2>Manage Schools</h2>
    <a href="{{ url_for('add_school') }}" class="btn btn-primary">+ Add School</a>
</div>
<div class="card">
    <table>
        <tr><th>Name</th><th>Code</th><th>Resumption</th><th>Closing</th><th>API Key</th><th>Actions</th></tr>
        {% for school in schools %}
        <tr>
            <td>{{ school.name }}</td>
            <td>{{ school.code }}</td>
            <td><span class="time-display">{{ school.resumption_time.strftime('%H:%M') if school.resumption_time else '08:00' }}</span></td>
            <td><span class="time-display">{{ school.closing_time.strftime('%H:%M') if school.closing_time else '17:00' }}</span></td>
            <td><code style="background: #f5f5f5; padding: 0.3rem 0.5rem; border-radius: 3px; font-size: 0.85rem;">{{ school.api_key[:20] }}...</code></td>
            <td>
                <a href="{{ url_for('edit_school', id=school.id) }}" class="btn btn-secondary" style="padding: 0.4rem 0.8rem;">Edit</a>
                <a href="{{ url_for('delete_school', id=school.id) }}" class="btn btn-danger" style="padding: 0.4rem 0.8rem;" onclick="return confirm('Delete this school?')">Delete</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

ADD_SCHOOL_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Add School{% endblock %}
{% block content %}
<h2 style="margin-bottom: 1.5rem;">Add New School</h2>
<div class="card" style="max-width: 500px;">
    <form method="POST">
        <div class="form-group">
            <label>School Name</label>
            <input type="text" name="name" required placeholder="e.g. School 8">
        </div>
        <div class="form-group">
            <label>School Code</label>
            <input type="text" name="code" required placeholder="e.g. SCH8">
        </div>
        <div class="form-group">
            <label>Resumption Time</label>
            <select name="resumption_time">
                {% for hour in range(5, 12) %}
                <option value="{{ '%02d:00'|format(hour) }}" {% if hour == 8 %}selected{% endif %}>{{ '%02d:00'|format(hour) }}</option>
                <option value="{{ '%02d:30'|format(hour) }}">{{ '%02d:30'|format(hour) }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>Closing Time</label>
            <select name="closing_time">
                {% for hour in range(14, 22) %}
                <option value="{{ '%02d:00'|format(hour) }}" {% if hour == 17 %}selected{% endif %}>{{ '%02d:00'|format(hour) }}</option>
                <option value="{{ '%02d:30'|format(hour) }}">{{ '%02d:30'|format(hour) }}</option>
                {% endfor %}
            </select>
        </div>
        <button type="submit" class="btn btn-primary">Add School</button>
        <a href="{{ url_for('schools') }}" class="btn btn-secondary">Cancel</a>
    </form>
</div>
{% endblock %}
'''

EDIT_SCHOOL_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Edit School{% endblock %}
{% block content %}
<h2 style="margin-bottom: 1.5rem;">Edit School</h2>
<div class="card" style="max-width: 500px;">
    <form method="POST">
        <div class="form-group">
            <label>School Name</label>
            <input type="text" name="name" value="{{ school.name }}" required>
        </div>
        <div class="form-group">
            <label>School Code</label>
            <input type="text" value="{{ school.code }}" disabled style="background: #f5f5f5;">
        </div>
        <div class="form-group">
            <label>Resumption Time</label>
            <select name="resumption_time">
                {% for hour in range(5, 12) %}
                <option value="{{ '%02d:00'|format(hour) }}" {% if school.resumption_time and school.resumption_time.hour == hour and school.resumption_time.minute == 0 %}selected{% endif %}>{{ '%02d:00'|format(hour) }}</option>
                <option value="{{ '%02d:30'|format(hour) }}" {% if school.resumption_time and school.resumption_time.hour == hour and school.resumption_time.minute == 30 %}selected{% endif %}>{{ '%02d:30'|format(hour) }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>Closing Time</label>
            <select name="closing_time">
                {% for hour in range(14, 22) %}
                <option value="{{ '%02d:00'|format(hour) }}" {% if school.closing_time and school.closing_time.hour == hour and school.closing_time.minute == 0 %}selected{% endif %}>{{ '%02d:00'|format(hour) }}</option>
                <option value="{{ '%02d:30'|format(hour) }}" {% if school.closing_time and school.closing_time.hour == hour and school.closing_time.minute == 30 %}selected{% endif %}>{{ '%02d:30'|format(hour) }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>API Key (for kiosk setup)</label>
            <input type="text" value="{{ school.api_key }}" readonly onclick="this.select()" style="font-family: monospace; background: #f5f5f5;">
        </div>
        <button type="submit" class="btn btn-primary">Save Changes</button>
        <a href="{{ url_for('regenerate_key', id=school.id) }}" class="btn btn-secondary" onclick="return confirm('Regenerate API key?')">Regenerate Key</a>
        <a href="{{ url_for('schools') }}" class="btn btn-secondary">Cancel</a>
    </form>
</div>
{% endblock %}
'''

STAFF_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Staff{% endblock %}
{% block content %}
<div class="page-header">
    <h2>Manage Staff</h2>
    <a href="{{ url_for('add_staff') }}" class="btn btn-primary">+ Add Staff</a>
</div>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end;">
        <div class="form-group">
            <label>School</label>
            <select name="school" onchange="this.form.submit()">
                <option value="">All Schools</option>
                {% for school in schools %}
                <option value="{{ school.id }}" {% if selected_school == school.id %}selected{% endif %}>{{ school.name }}</option>
                {% endfor %}
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
                <a href="{{ url_for('toggle_staff', id=s.id) }}" class="btn btn-secondary" style="padding: 0.4rem 0.8rem;">{{ 'Deactivate' if s.active else 'Activate' }}</a>
                <a href="{{ url_for('delete_staff', id=s.id) }}" class="btn btn-danger" style="padding: 0.4rem 0.8rem;" onclick="return confirm('Delete?')">Delete</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

ADD_STAFF_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Add Staff{% endblock %}
{% block content %}
<h2 style="margin-bottom: 1.5rem;">Add Staff Member</h2>
<div class="card" style="max-width: 500px;">
    <form method="POST">
        <div class="form-group">
            <label>School</label>
            <select name="school_id" required>
                {% for school in schools %}
                <option value="{{ school.id }}">{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>Staff ID</label>
            <input type="text" name="staff_id" required placeholder="e.g. STF001">
        </div>
        <div class="form-group">
            <label>Full Name</label>
            <input type="text" name="name" required>
        </div>
        <div class="form-group">
            <label>Department (optional)</label>
            <input type="text" name="department">
        </div>
        <button type="submit" class="btn btn-primary">Add Staff</button>
        <a href="{{ url_for('staff') }}" class="btn btn-secondary">Cancel</a>
    </form>
</div>
{% endblock %}
'''

LATECOMERS_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Late Staff{% endblock %}
{% block content %}
<div class="page-header">
    <h2>Late Staff Report</h2>
    <div class="button-group">
        <a href="{{ url_for('download_latecomers', school=selected_school or '', date=selected_date) }}" class="btn btn-success">Download CSV</a>
    </div>
</div>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
        <div class="form-group">
            <label>School</label>
            <select name="school">
                <option value="">All Schools</option>
                {% for school in schools %}
                <option value="{{ school.id }}" {% if selected_school == school.id %}selected{% endif %}>{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>Date</label>
            <input type="date" name="date" value="{{ selected_date }}">
        </div>
        <button type="submit" class="btn btn-primary">Filter</button>
    </form>
</div>
<div class="stats-grid">
    <div class="stat-card warning">
        <h3>{{ records|length }}</h3>
        <p>Late Staff</p>
    </div>
</div>
<div class="card">
    <table>
        <tr><th>Staff ID</th><th>Name</th><th>School</th><th>Resumption Time</th><th>Arrival Time</th><th>Late By</th></tr>
        {% for r in records %}
        <tr>
            <td>{{ r.staff_id }}</td>
            <td>{{ r.name }}</td>
            <td>{{ r.school }}</td>
            <td><span class="time-display">{{ r.resumption }}</span></td>
            <td><span class="time-display">{{ r.arrival }}</span></td>
            <td><span class="badge badge-danger">{{ r.late_by }}</span></td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

OVERTIME_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Overtime Report{% endblock %}
{% block content %}
<div class="page-header">
    <h2>Overtime Report</h2>
    <div class="button-group">
        <a href="{{ url_for('download_overtime', school=selected_school or '', from_date=from_date, to_date=to_date) }}" class="btn btn-success">Download CSV</a>
    </div>
</div>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
        <div class="form-group">
            <label>School</label>
            <select name="school">
                <option value="">All Schools</option>
                {% for school in schools %}
                <option value="{{ school.id }}" {% if selected_school == school.id %}selected{% endif %}>{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>From Date</label>
            <input type="date" name="from_date" value="{{ from_date }}">
        </div>
        <div class="form-group">
            <label>To Date</label>
            <input type="date" name="to_date" value="{{ to_date }}">
        </div>
        <button type="submit" class="btn btn-primary">Filter</button>
    </form>
</div>
<div class="stats-grid">
    <div class="stat-card info">
        <h3>{{ total_overtime }}</h3>
        <p>Total Overtime Hours</p>
    </div>
</div>
<div class="card">
    <table>
        <tr><th>Staff ID</th><th>Name</th><th>School</th><th>Days Worked</th><th>Total Overtime</th></tr>
        {% for r in records %}
        <tr>
            <td>{{ r.staff_id }}</td>
            <td>{{ r.name }}</td>
            <td>{{ r.school }}</td>
            <td>{{ r.days_worked }}</td>
            <td><span class="badge badge-info">{{ r.overtime_hours }}h {{ r.overtime_mins }}m</span></td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

ATTENDANCE_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Attendance Reports{% endblock %}
{% block content %}
<h2 style="margin-bottom: 1.5rem;">Attendance Reports</h2>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
        <div class="form-group">
            <label>School</label>
            <select name="school">
                <option value="">All Schools</option>
                {% for school in schools %}
                <option value="{{ school.id }}" {% if selected_school == school.id %}selected{% endif %}>{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>From Date</label>
            <input type="date" name="from_date" value="{{ from_date }}">
        </div>
        <div class="form-group">
            <label>To Date</label>
            <input type="date" name="to_date" value="{{ to_date }}">
        </div>
        <button type="submit" class="btn btn-primary">Filter</button>
        <a href="{{ url_for('download_attendance', school=selected_school or '', from_date=from_date, to_date=to_date) }}" class="btn btn-success">Download CSV</a>
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
            <td>{{ r.first_in }}</td>
            <td>{{ r.last_out or '-' }}</td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

TODAY_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Today's Activity{% endblock %}
{% block content %}
<h2 style="margin-bottom: 1.5rem;">Today's Activity</h2>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end;">
        <div class="form-group">
            <label>School</label>
            <select name="school" onchange="this.form.submit()">
                <option value="">All Schools</option>
                {% for school in schools %}
                <option value="{{ school.id }}" {% if selected_school == school.id %}selected{% endif %}>{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
    </form>
</div>
<div class="card">
    <table>
        <tr><th>Time</th><th>Staff ID</th><th>Name</th><th>School</th><th>Action</th></tr>
        {% for r in records %}
        <tr>
            <td>{{ r.timestamp.strftime('%H:%M:%S') }}</td>
            <td>{{ r.staff_id }}</td>
            <td>{{ r.staff_name }}</td>
            <td>{{ r.school.name }}</td>
            <td><span class="badge {% if r.action == 'IN' %}badge-success{% else %}badge-secondary{% endif %}">{{ r.action }}</span></td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

ADMINS_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Manage Admins{% endblock %}
{% block content %}
<div class="page-header">
    <h2>Manage Admins</h2>
</div>
<div class="card" style="max-width: 500px; margin-bottom: 2rem;">
    <h3 style="margin-bottom: 1rem;">Add New Admin</h3>
    <form method="POST">
        <div class="form-group">
            <label>Username</label>
            <input type="text" name="username" required>
        </div>
        <div class="form-group">
            <label>Password</label>
            <input type="password" name="password" required>
        </div>
        <div class="form-group">
            <label>Role</label>
            <select name="role" id="role-select" onchange="toggleSchoolSelect()">
                <option value="superadmin">Super Admin</option>
                <option value="schooladmin">School Admin</option>
            </select>
        </div>
        <div class="form-group" id="school-group" style="display: none;">
            <label>School</label>
            <select name="school_id">
                {% for school in schools %}
                <option value="{{ school.id }}">{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <button type="submit" class="btn btn-primary">Add Admin</button>
    </form>
</div>
<script>
function toggleSchoolSelect() {
    var role = document.getElementById('role-select').value;
    document.getElementById('school-group').style.display = role === 'schooladmin' ? 'block' : 'none';
}
</script>
<div class="card">
    <h3 style="margin-bottom: 1rem;">Current Admins</h3>
    <table>
        <tr><th>Username</th><th>Role</th><th>School</th><th>Actions</th></tr>
        {% for user in users %}
        <tr>
            <td>{{ user.username }}</td>
            <td>{{ user.role }}</td>
            <td>{{ user.school.name if user.school else 'All' }}</td>
            <td>
                {% if user.username != 'admin' %}
                <a href="{{ url_for('delete_admin', id=user.id) }}" class="btn btn-danger" style="padding: 0.4rem 0.8rem;" onclick="return confirm('Delete?')">Delete</a>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

SETTINGS_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Settings{% endblock %}
{% block content %}
<h2 style="margin-bottom: 1.5rem;">Settings</h2>
<div class="card" style="max-width: 500px;">
    <h3 style="margin-bottom: 1rem;">Change Password</h3>
    <form method="POST">
        <div class="form-group">
            <label>Current Password</label>
            <input type="password" name="current_password" required>
        </div>
        <div class="form-group">
            <label>New Password</label>
            <input type="password" name="new_password" required>
        </div>
        <div class="form-group">
            <label>Confirm New Password</label>
            <input type="password" name="confirm_password" required>
        </div>
        <button type="submit" class="btn btn-primary">Change Password</button>
    </form>
</div>
{% endblock %}
'''

# Routes
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
    return render_template_string(LOGIN_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), base=BASE_TEMPLATE)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    schools = School.query.all()
    today = datetime.utcnow().date()
    school_data = []
    total_on_site = 0
    total_today = 0
    total_late = 0
    
    for school in schools:
        today_records = Attendance.query.filter(
            Attendance.school_id == school.id,
            db.func.date(Attendance.timestamp) == today
        ).all()
        
        staff_status = {}
        staff_first_in = {}
        for r in today_records:
            staff_status[r.staff_id] = r.action
            if r.action == 'IN' and (r.staff_id not in staff_first_in or r.timestamp < staff_first_in[r.staff_id]):
                staff_first_in[r.staff_id] = r.timestamp
        
        on_site = sum(1 for s in staff_status.values() if s == 'IN')
        total_on_site += on_site
        total_today += len(set(r.staff_id for r in today_records))
        
        resumption = school.resumption_time or time(8, 0)
        late_count = sum(1 for t in staff_first_in.values() if t.time() > resumption)
        total_late += late_count
        
        school_data.append({
            'name': school.name,
            'resumption': resumption.strftime('%H:%M'),
            'closing': (school.closing_time or time(17, 0)).strftime('%H:%M'),
            'on_site': on_site,
            'late': late_count,
            'last_sync': school.last_sync
        })
    
    return render_template_string(DASHBOARD_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), 
        base=BASE_TEMPLATE, schools=school_data, total_schools=len(schools),
        total_staff=Staff.query.filter_by(active=True).count(), on_site=total_on_site, 
        today_signins=total_today, late_today=total_late)

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
        
        day_records = Attendance.query.filter(
            Attendance.school_id == school.id,
            db.func.date(Attendance.timestamp) == query_date,
            Attendance.action == 'IN'
        ).all()
        
        staff_first_in = {}
        for r in day_records:
            if r.staff_id not in staff_first_in or r.timestamp < staff_first_in[r.staff_id]['time']:
                staff_first_in[r.staff_id] = {'time': r.timestamp, 'name': r.staff_name}
        
        for staff_id, data in staff_first_in.items():
            if data['time'].time() > resumption:
                late_seconds = (datetime.combine(query_date, data['time'].time()) - 
                               datetime.combine(query_date, resumption)).total_seconds()
                late_mins = int(late_seconds // 60)
                hours = late_mins // 60
                mins = late_mins % 60
                records.append({
                    'staff_id': staff_id,
                    'name': data['name'],
                    'school': school.name,
                    'resumption': resumption.strftime('%H:%M'),
                    'arrival': data['time'].strftime('%H:%M'),
                    'late_by': f"{hours}h {mins}m" if hours else f"{mins}m"
                })
    
    return render_template_string(LATECOMERS_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), 
        base=BASE_TEMPLATE, records=records, schools=schools, selected_school=selected, selected_date=selected_date)

@app.route('/latecomers/download')
@login_required
def download_latecomers():
    selected = request.args.get('school', type=int)
    selected_date = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))
    
    query_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
    records = []
    schools = School.query.all()
    school_list = [School.query.get(selected)] if selected else schools
    
    for school in school_list:
        if not school:
            continue
        resumption = school.resumption_time or time(8, 0)
        
        day_records = Attendance.query.filter(
            Attendance.school_id == school.id,
            db.func.date(Attendance.timestamp) == query_date,
            Attendance.action == 'IN'
        ).all()
        
        staff_first_in = {}
        for r in day_records:
            if r.staff_id not in staff_first_in or r.timestamp < staff_first_in[r.staff_id]['time']:
                staff_first_in[r.staff_id] = {'time': r.timestamp, 'name': r.staff_name}
        
        for staff_id, data in staff_first_in.items():
            if data['time'].time() > resumption:
                late_seconds = (datetime.combine(query_date, data['time'].time()) - 
                               datetime.combine(query_date, resumption)).total_seconds()
                late_mins = int(late_seconds // 60)
                hours = late_mins // 60
                mins = late_mins % 60
                records.append({
                    'staff_id': staff_id,
                    'name': data['name'],
                    'school': school.name,
                    'resumption': resumption.strftime('%H:%M'),
                    'arrival': data['time'].strftime('%H:%M'),
                    'late_by': f"{hours}h {mins}m" if hours else f"{mins}m"
                })
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Resumption Time', 'Arrival Time', 'Late By'])
    for r in records:
        writer.writerow([r['staff_id'], r['name'], r['school'], r['resumption'], r['arrival'], r['late_by']])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename=latecomers_{selected_date}.csv'})

@app.route('/overtime')
@login_required
def overtime():
    schools = School.query.all()
    selected = request.args.get('school', type=int)
    from_date = request.args.get('from_date', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.utcnow().strftime('%Y-%m-%d'))
    
    records = []
    total_overtime_mins = 0
    school_list = [School.query.get(selected)] if selected else schools
    
    for school in school_list:
        if not school:
            continue
        closing = school.closing_time or time(17, 0)
        
        query = Attendance.query.filter(
            Attendance.school_id == school.id,
            Attendance.timestamp >= datetime.strptime(from_date, '%Y-%m-%d'),
            Attendance.timestamp <= datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)
        ).all()
        
        staff_data = {}
        for r in query:
            date_key = r.timestamp.date()
            if r.staff_id not in staff_data:
                staff_data[r.staff_id] = {'name': r.staff_name, 'days': {}}
            if date_key not in staff_data[r.staff_id]['days']:
                staff_data[r.staff_id]['days'][date_key] = {'last_out': None}
            if r.action == 'OUT' and (staff_data[r.staff_id]['days'][date_key]['last_out'] is None or 
                                      r.timestamp > staff_data[r.staff_id]['days'][date_key]['last_out']):
                staff_data[r.staff_id]['days'][date_key]['last_out'] = r.timestamp
        
        for staff_id, data in staff_data.items():
            staff_overtime = 0
            days_worked = 0
            for date_key, day_data in data['days'].items():
                if day_data['last_out'] and day_data['last_out'].time() > closing:
                    days_worked += 1
                    overtime_seconds = (datetime.combine(date_key, day_data['last_out'].time()) - 
                                       datetime.combine(date_key, closing)).total_seconds()
                    staff_overtime += int(overtime_seconds // 60)
            
            if staff_overtime > 0:
                total_overtime_mins += staff_overtime
                records.append({
                    'staff_id': staff_id,
                    'name': data['name'],
                    'school': school.name,
                    'days_worked': days_worked,
                    'overtime_hours': staff_overtime // 60,
                    'overtime_mins': staff_overtime % 60
                })
    
    records.sort(key=lambda x: x['overtime_hours'] * 60 + x['overtime_mins'], reverse=True)
    total_hours = total_overtime_mins // 60
    total_mins = total_overtime_mins % 60
    
    return render_template_string(OVERTIME_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), 
        base=BASE_TEMPLATE, records=records, schools=schools, selected_school=selected,
        from_date=from_date, to_date=to_date, total_overtime=f"{total_hours}h {total_mins}m")

@app.route('/overtime/download')
@login_required
def download_overtime():
    selected = request.args.get('school', type=int)
    from_date = request.args.get('from_date', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.utcnow().strftime('%Y-%m-%d'))
    
    records = []
    schools = School.query.all()
    school_list = [School.query.get(selected)] if selected else schools
    
    for school in school_list:
        if not school:
            continue
        closing = school.closing_time or time(17, 0)
        
        query = Attendance.query.filter(
            Attendance.school_id == school.id,
            Attendance.timestamp >= datetime.strptime(from_date, '%Y-%m-%d'),
            Attendance.timestamp <= datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)
        ).all()
        
        staff_data = {}
        for r in query:
            date_key = r.timestamp.date()
            if r.staff_id not in staff_data:
                staff_data[r.staff_id] = {'name': r.staff_name, 'days': {}}
            if date_key not in staff_data[r.staff_id]['days']:
                staff_data[r.staff_id]['days'][date_key] = {'last_out': None}
            if r.action == 'OUT' and (staff_data[r.staff_id]['days'][date_key]['last_out'] is None or 
                                      r.timestamp > staff_data[r.staff_id]['days'][date_key]['last_out']):
                staff_data[r.staff_id]['days'][date_key]['last_out'] = r.timestamp
        
        for staff_id, data in staff_data.items():
            staff_overtime = 0
            days_worked = 0
            for date_key, day_data in data['days'].items():
                if day_data['last_out'] and day_data['last_out'].time() > closing:
                    days_worked += 1
                    overtime_seconds = (datetime.combine(date_key, day_data['last_out'].time()) - 
                                       datetime.combine(date_key, closing)).total_seconds()
                    staff_overtime += int(overtime_seconds // 60)
            
            if staff_overtime > 0:
                records.append({
                    'staff_id': staff_id,
                    'name': data['name'],
                    'school': school.name,
                    'days_worked': days_worked,
                    'overtime_hours': staff_overtime // 60,
                    'overtime_mins': staff_overtime % 60
                })
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Days Worked', 'Overtime Hours', 'Overtime Minutes'])
    for r in records:
        writer.writerow([r['staff_id'], r['name'], r['school'], r['days_worked'], r['overtime_hours'], r['overtime_mins']])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename=overtime_{from_date}_to_{to_date}.csv'})

@app.route('/schools')
@login_required
def schools():
    if current_user.role != 'superadmin':
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    schools = School.query.all()
    return render_template_string(SCHOOLS_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), base=BASE_TEMPLATE, schools=schools)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        res_time = datetime.strptime(request.form['resumption_time'], '%H:%M').time()
        cls_time = datetime.strptime(request.form['closing_time'], '%H:%M').time()
        school = School(name=request.form['name'], code=request.form['code'], 
                       api_key=secrets.token_hex(32), resumption_time=res_time, closing_time=cls_time)
        db.session.add(school)
        db.session.commit()
        flash('School added', 'success')
        return redirect(url_for('schools'))
    return render_template_string(ADD_SCHOOL_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), base=BASE_TEMPLATE)

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
    return render_template_string(EDIT_SCHOOL_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), base=BASE_TEMPLATE, school=school)

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
    return render_template_string(STAFF_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), 
        base=BASE_TEMPLATE, staff=staff_list, schools=schools, selected_school=selected)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    schools = School.query.all() if current_user.role == 'superadmin' else [current_user.school]
    if request.method == 'POST':
        s = Staff(staff_id=request.form['staff_id'], name=request.form['name'],
                  department=request.form.get('department'), school_id=request.form['school_id'])
        db.session.add(s)
        db.session.commit()
        flash('Staff added', 'success')
        return redirect(url_for('staff'))
    return render_template_string(ADD_STAFF_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), base=BASE_TEMPLATE, schools=schools)

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
    if from_date:
        query = query.filter(Attendance.timestamp >= datetime.strptime(from_date, '%Y-%m-%d'))
    if to_date:
        query = query.filter(Attendance.timestamp <= datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1))
    
    raw_records = query.order_by(Attendance.timestamp.desc()).all()
    
    grouped = {}
    for r in raw_records:
        key = (r.timestamp.date(), r.staff_id, r.school_id)
        if key not in grouped:
            school = School.query.get(r.school_id)
            grouped[key] = {'date': r.timestamp.strftime('%Y-%m-%d'), 'staff_id': r.staff_id, 
                           'name': r.staff_name, 'school': school.name if school else 'Unknown',
                           'first_in': None, 'last_out': None}
        if r.action == 'IN' and (grouped[key]['first_in'] is None or r.timestamp.strftime('%H:%M') < grouped[key]['first_in']):
            grouped[key]['first_in'] = r.timestamp.strftime('%H:%M')
        if r.action == 'OUT' and (grouped[key]['last_out'] is None or r.timestamp.strftime('%H:%M') > grouped[key]['last_out']):
            grouped[key]['last_out'] = r.timestamp.strftime('%H:%M')
    
    records = sorted(grouped.values(), key=lambda x: x['date'], reverse=True)
    return render_template_string(ATTENDANCE_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), 
        base=BASE_TEMPLATE, records=records, schools=schools, selected_school=selected, from_date=from_date, to_date=to_date)

@app.route('/attendance/download')
@login_required
def download_attendance():
    selected = request.args.get('school', type=int)
    from_date = request.args.get('from_date', (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d'))
    to_date = request.args.get('to_date', datetime.utcnow().strftime('%Y-%m-%d'))
    
    query = Attendance.query
    if selected:
        query = query.filter(Attendance.school_id == selected)
    if from_date:
        query = query.filter(Attendance.timestamp >= datetime.strptime(from_date, '%Y-%m-%d'))
    if to_date:
        query = query.filter(Attendance.timestamp <= datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1))
    
    raw_records = query.order_by(Attendance.timestamp.desc()).all()
    
    grouped = {}
    for r in raw_records:
        key = (r.timestamp.date(), r.staff_id, r.school_id)
        if key not in grouped:
            school = School.query.get(r.school_id)
            grouped[key] = {'date': r.timestamp.strftime('%Y-%m-%d'), 'staff_id': r.staff_id, 
                           'name': r.staff_name, 'school': school.name if school else 'Unknown',
                           'first_in': None, 'last_out': None}
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
    return Response(output.getvalue(), mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename=attendance_{from_date}_to_{to_date}.csv'})

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
    return render_template_string(TODAY_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), 
        base=BASE_TEMPLATE, records=records, schools=schools, selected_school=selected)

@app.route('/admins', methods=['GET', 'POST'])
@login_required
def admins():
    if current_user.role != 'superadmin':
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        school_id = request.form.get('school_id') if request.form['role'] == 'schooladmin' else None
        user = User(username=request.form['username'], 
                   password_hash=generate_password_hash(request.form['password']),
                   role=request.form['role'], school_id=school_id)
        db.session.add(user)
        db.session.commit()
        flash('Admin added', 'success')
    users = User.query.all()
    schools = School.query.all()
    return render_template_string(ADMINS_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), base=BASE_TEMPLATE, users=users, schools=schools)

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
    return render_template_string(SETTINGS_TEMPLATE.replace("{% extends 'base' %}", "{% extends base %}"), base=BASE_TEMPLATE)

# API for kiosk sync
@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    school = School.query.filter_by(api_key=api_key).first()
    if not school:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    for record in data.get('attendance', []):
        att = Attendance(staff_id=record['staff_id'], staff_name=record.get('staff_name'),
                        school_id=school.id, timestamp=datetime.fromisoformat(record['timestamp']),
                        action=record['action'])
        db.session.add(att)
    
    school.last_sync = datetime.utcnow()
    db.session.commit()
    
    staff_list = [{'staff_id': s.staff_id, 'name': s.name, 'active': s.active} 
                  for s in Staff.query.filter_by(school_id=school.id).all()]
    return jsonify({'status': 'ok', 'staff': staff_list})

@app.route('/api/check')
def api_check():
    api_key = request.headers.get('X-API-Key')
    school = School.query.filter_by(api_key=api_key).first()
    if school:
        return jsonify({'status': 'ok', 'school': school.name})
    return jsonify({'error': 'Invalid API key'}), 401

# Initialize database
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password_hash=generate_password_hash('admin123'), role='superadmin')
        db.session.add(admin)
        for i in range(1, 8):
            school = School(name=f'School {i}', code=f'SCH{i}', api_key=secrets.token_hex(32))
            db.session.add(school)
        db.session.commit()

port = int(os.environ.get('PORT', 5000))
app.run(host='0.0.0.0', port=port, debug=False)
