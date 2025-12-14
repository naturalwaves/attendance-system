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

# Models
class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    last_sync = db.Column(db.DateTime)
    resumption_time = db.Column(db.Time, default=time(8, 0))
    closing_time = db.Column(db.Time, default=time(17, 0))
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

# Beautiful Base Template with Corona Schools Logo
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}Corona Schools Attendance{% endblock %}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Poppins', sans-serif; 
            background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
            min-height: 100vh;
            color: #2d3748;
        }
        
        .navbar { 
            background: linear-gradient(135deg, #c41e3a 0%, #a01830 100%);
            padding: 0.8rem 2rem; 
            display: flex; 
            align-items: center; 
            justify-content: space-between; 
            box-shadow: 0 4px 20px rgba(196, 30, 58, 0.3);
            position: sticky;
            top: 0;
            z-index: 1000;
        }
        
        .navbar-brand { 
            display: flex; 
            align-items: center; 
            gap: 15px; 
        }
        
        .navbar-brand img { 
            height: 50px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        
        .navbar-brand span { 
            color: white; 
            font-size: 1.4rem; 
            font-weight: 600;
            text-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        
        .navbar-links { 
            display: flex; 
            gap: 0.5rem; 
            align-items: center;
            flex-wrap: wrap;
        }
        
        .navbar-links a { 
            color: white; 
            text-decoration: none; 
            font-size: 0.9rem; 
            padding: 0.6rem 1rem; 
            border-radius: 8px; 
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .navbar-links a:hover { 
            background: rgba(255,255,255,0.2);
            transform: translateY(-2px);
        }
        
        .navbar-links a i {
            font-size: 1rem;
        }
        
        .container { 
            max-width: 1300px; 
            margin: 0 auto; 
            padding: 2rem; 
        }
        
        .page-title {
            font-size: 1.8rem;
            font-weight: 600;
            color: #1a202c;
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .page-title i {
            color: #c41e3a;
        }
        
        .card { 
            background: white; 
            border-radius: 16px; 
            padding: 1.8rem; 
            margin-bottom: 1.5rem; 
            box-shadow: 0 4px 25px rgba(0,0,0,0.08);
            border: 1px solid rgba(0,0,0,0.05);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0,0,0,0.12);
        }
        
        .card-header {
            font-size: 1.1rem;
            font-weight: 600;
            color: #1a202c;
            margin-bottom: 1.2rem;
            padding-bottom: 0.8rem;
            border-bottom: 2px solid #f0f0f0;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .card-header i {
            color: #c41e3a;
        }
        
        .btn { 
            padding: 0.7rem 1.4rem; 
            border: none; 
            border-radius: 10px; 
            cursor: pointer; 
            font-size: 0.9rem; 
            font-weight: 500;
            text-decoration: none; 
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s ease;
        }
        
        .btn i {
            font-size: 0.9rem;
        }
        
        .btn-primary { 
            background: linear-gradient(135deg, #c41e3a 0%, #a01830 100%);
            color: white; 
            box-shadow: 0 4px 15px rgba(196, 30, 58, 0.3);
        }
        
        .btn-primary:hover { 
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(196, 30, 58, 0.4);
        }
        
        .btn-secondary { 
            background: linear-gradient(135deg, #718096 0%, #4a5568 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(113, 128, 150, 0.3);
        }
        
        .btn-secondary:hover { 
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(113, 128, 150, 0.4);
        }
        
        .btn-success { 
            background: linear-gradient(135deg, #48bb78 0%, #38a169 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(72, 187, 120, 0.3);
        }
        
        .btn-success:hover { 
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(72, 187, 120, 0.4);
        }
        
        .btn-danger { 
            background: linear-gradient(135deg, #fc8181 0%, #f56565 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(252, 129, 129, 0.3);
        }
        
        .btn-danger:hover { 
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(252, 129, 129, 0.4);
        }
        
        .btn-warning { 
            background: linear-gradient(135deg, #ecc94b 0%, #d69e2e 100%);
            color: #1a202c;
            box-shadow: 0 4px 15px rgba(236, 201, 75, 0.3);
        }
        
        .btn-info { 
            background: linear-gradient(135deg, #4299e1 0%, #3182ce 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(66, 153, 225, 0.3);
        }
        
        .btn-sm {
            padding: 0.5rem 1rem;
            font-size: 0.85rem;
        }
        
        table { 
            width: 100%; 
            border-collapse: collapse; 
            margin-top: 1rem; 
        }
        
        th, td { 
            padding: 1rem; 
            text-align: left; 
            border-bottom: 1px solid #edf2f7; 
        }
        
        th { 
            background: linear-gradient(135deg, #f8f9fa 0%, #edf2f7 100%);
            font-weight: 600; 
            color: #4a5568;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        tr:hover { 
            background: #fafbfc; 
        }
        
        .form-group { 
            margin-bottom: 1.2rem; 
        }
        
        .form-group label { 
            display: block; 
            margin-bottom: 0.5rem; 
            font-weight: 500; 
            color: #4a5568;
            font-size: 0.9rem;
        }
        
        .form-group input, .form-group select { 
            width: 100%; 
            padding: 0.8rem 1rem; 
            border: 2px solid #e2e8f0; 
            border-radius: 10px; 
            font-size: 0.95rem;
            font-family: 'Poppins', sans-serif;
            transition: all 0.3s ease;
        }
        
        .form-group input:focus, .form-group select:focus { 
            outline: none; 
            border-color: #c41e3a;
            box-shadow: 0 0 0 3px rgba(196, 30, 58, 0.1);
        }
        
        .stats-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); 
            gap: 1.5rem; 
            margin-bottom: 2rem; 
        }
        
        .stat-card { 
            background: white;
            padding: 1.5rem; 
            border-radius: 16px; 
            text-align: center;
            box-shadow: 0 4px 25px rgba(0,0,0,0.08);
            border: 1px solid rgba(0,0,0,0.05);
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }
        
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(135deg, #c41e3a 0%, #a01830 100%);
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 30px rgba(0,0,0,0.15);
        }
        
        .stat-card .icon {
            width: 60px;
            height: 60px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1rem;
            font-size: 1.5rem;
        }
        
        .stat-card.primary .icon { background: rgba(196, 30, 58, 0.1); color: #c41e3a; }
        .stat-card.success .icon { background: rgba(72, 187, 120, 0.1); color: #48bb78; }
        .stat-card.warning .icon { background: rgba(236, 201, 75, 0.1); color: #d69e2e; }
        .stat-card.info .icon { background: rgba(66, 153, 225, 0.1); color: #4299e1; }
        
        .stat-card h3 { 
            font-size: 2.2rem; 
            font-weight: 700;
            color: #1a202c;
            margin-bottom: 0.3rem;
        }
        
        .stat-card p { 
            color: #718096; 
            font-size: 0.9rem;
            font-weight: 500;
        }
        
        .alert { 
            padding: 1rem 1.5rem; 
            border-radius: 12px; 
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .alert i {
            font-size: 1.2rem;
        }
        
        .alert-success { 
            background: linear-gradient(135deg, #c6f6d5 0%, #9ae6b4 100%);
            color: #276749;
            border: 1px solid #9ae6b4;
        }
        
        .alert-error { 
            background: linear-gradient(135deg, #fed7d7 0%, #feb2b2 100%);
            color: #c53030;
            border: 1px solid #feb2b2;
        }
        
        .filter-bar { 
            display: flex; 
            gap: 1rem; 
            align-items: flex-end; 
            flex-wrap: wrap; 
            margin-bottom: 1.5rem; 
            padding: 1.5rem; 
            background: white; 
            border-radius: 16px;
            box-shadow: 0 4px 25px rgba(0,0,0,0.08);
            border: 1px solid rgba(0,0,0,0.05);
        }
        
        .filter-bar .form-group { 
            margin-bottom: 0; 
            min-width: 180px;
        }
        
        .badge { 
            padding: 0.4rem 0.8rem; 
            border-radius: 20px; 
            font-size: 0.8rem;
            font-weight: 500;
        }
        
        .badge-success { 
            background: linear-gradient(135deg, #c6f6d5 0%, #9ae6b4 100%);
            color: #276749; 
        }
        
        .badge-secondary { 
            background: linear-gradient(135deg, #e2e8f0 0%, #cbd5e0 100%);
            color: #4a5568; 
        }
        
        .badge-danger { 
            background: linear-gradient(135deg, #fed7d7 0%, #feb2b2 100%);
            color: #c53030; 
        }
        
        .badge-info { 
            background: linear-gradient(135deg, #bee3f8 0%, #90cdf4 100%);
            color: #2c5282; 
        }
        
        .page-header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 1.5rem; 
            flex-wrap: wrap; 
            gap: 1rem; 
        }
        
        .button-group { 
            display: flex; 
            gap: 0.8rem; 
            flex-wrap: wrap; 
        }
        
        .time-display { 
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #edf2f7 0%, #e2e8f0 100%);
            padding: 0.4rem 0.8rem; 
            border-radius: 8px;
            font-weight: 600;
            color: #2d3748;
        }
        
        .empty-state {
            text-align: center;
            padding: 3rem;
            color: #a0aec0;
        }
        
        .empty-state i {
            font-size: 4rem;
            margin-bottom: 1rem;
            opacity: 0.5;
        }
        
        .empty-state p {
            font-size: 1.1rem;
        }
        
        @media (max-width: 768px) {
            .navbar {
                flex-direction: column;
                gap: 1rem;
                padding: 1rem;
            }
            
            .navbar-links {
                justify-content: center;
            }
            
            .container {
                padding: 1rem;
            }
            
            .stats-grid {
                grid-template-columns: 1fr 1fr;
            }
        }
    </style>
</head>
<body>
    {% if current_user.is_authenticated %}
    <nav class="navbar">
        <div class="navbar-brand">
            <img src="https://coronaschools.com/wp-content/uploads/2020/06/Corona-Logo.png" alt="Corona Schools Logo">
            <span>Staff Attendance System</span>
        </div>
        <div class="navbar-links">
            <a href="{{ url_for('dashboard') }}"><i class="fas fa-home"></i> Dashboard</a>
            <a href="{{ url_for('today') }}"><i class="fas fa-clock"></i> Today</a>
            <a href="{{ url_for('latecomers') }}"><i class="fas fa-user-clock"></i> Late Staff</a>
            <a href="{{ url_for('overtime') }}"><i class="fas fa-hourglass-half"></i> Overtime</a>
            <a href="{{ url_for('attendance') }}"><i class="fas fa-chart-bar"></i> Reports</a>
            <a href="{{ url_for('staff') }}"><i class="fas fa-users"></i> Staff</a>
            {% if current_user.role == 'superadmin' %}
            <a href="{{ url_for('schools') }}"><i class="fas fa-school"></i> Schools</a>
            <a href="{{ url_for('admins') }}"><i class="fas fa-user-shield"></i> Admins</a>
            {% endif %}
            <a href="{{ url_for('settings') }}"><i class="fas fa-cog"></i> Settings</a>
            <a href="{{ url_for('logout') }}"><i class="fas fa-sign-out-alt"></i> Logout</a>
        </div>
    </nav>
    {% endif %}
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
        <div class="alert alert-{{ category }}">
            <i class="fas {% if category == 'success' %}fa-check-circle{% else %}fa-exclamation-circle{% endif %}"></i>
            {{ message }}
        </div>
        {% endfor %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Login - Corona Schools{% endblock %}
{% block content %}
<div style="max-width: 420px; margin: 3rem auto;">
    <div class="card" style="text-align: center; padding: 2.5rem;">
        <img src="https://coronaschools.com/wp-content/uploads/2020/06/Corona-Logo.png" alt="Corona Schools Logo" style="height: 100px; margin-bottom: 1.5rem;">
        <h2 style="margin-bottom: 0.5rem; color: #c41e3a; font-size: 1.6rem;">Staff Attendance System</h2>
        <p style="color: #718096; margin-bottom: 2rem;">Sign in to your account</p>
        <form method="POST">
            <div class="form-group">
                <label><i class="fas fa-user" style="margin-right: 5px;"></i>Username</label>
                <input type="text" name="username" required placeholder="Enter your username">
            </div>
            <div class="form-group">
                <label><i class="fas fa-lock" style="margin-right: 5px;"></i>Password</label>
                <input type="password" name="password" required placeholder="Enter your password">
            </div>
            <button type="submit" class="btn btn-primary" style="width: 100%; padding: 1rem; font-size: 1rem;">
                <i class="fas fa-sign-in-alt"></i> Sign In
            </button>
        </form>
    </div>
</div>
{% endblock %}
'''

DASHBOARD_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Dashboard - Corona Schools{% endblock %}
{% block content %}
<h2 class="page-title"><i class="fas fa-tachometer-alt"></i> Dashboard</h2>
<div class="stats-grid">
    <div class="stat-card primary">
        <div class="icon"><i class="fas fa-school"></i></div>
        <h3>{{ total_schools }}</h3>
        <p>Total Schools</p>
    </div>
    <div class="stat-card success">
        <div class="icon"><i class="fas fa-users"></i></div>
        <h3>{{ total_staff }}</h3>
        <p>Total Staff</p>
    </div>
    <div class="stat-card info">
        <div class="icon"><i class="fas fa-building"></i></div>
        <h3>{{ on_site }}</h3>
        <p>Currently On Site</p>
    </div>
    <div class="stat-card primary">
        <div class="icon"><i class="fas fa-sign-in-alt"></i></div>
        <h3>{{ today_signins }}</h3>
        <p>Sign-ins Today</p>
    </div>
    <div class="stat-card warning">
        <div class="icon"><i class="fas fa-user-clock"></i></div>
        <h3>{{ late_today }}</h3>
        <p>Late Today</p>
    </div>
</div>
<div class="card">
    <div class="card-header"><i class="fas fa-list"></i> Schools Overview</div>
    <table>
        <tr>
            <th>School</th>
            <th>Resumption</th>
            <th>Closing</th>
            <th>On Site</th>
            <th>Late Today</th>
            <th>Last Sync</th>
        </tr>
        {% for school in schools %}
        <tr>
            <td><strong>{{ school.name }}</strong></td>
            <td><span class="time-display">{{ school.resumption }}</span></td>
            <td><span class="time-display">{{ school.closing }}</span></td>
            <td>{{ school.on_site }}</td>
            <td><span class="badge {% if school.late > 0 %}badge-danger{% else %}badge-success{% endif %}">{{ school.late }}</span></td>
            <td>{{ school.last_sync.strftime('%Y-%m-%d %H:%M') if school.last_sync else 'Never' }}</td>
        </tr>
        {% else %}
        <tr>
            <td colspan="6">
                <div class="empty-state">
                    <i class="fas fa-school"></i>
                    <p>No schools configured yet</p>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

SCHOOLS_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Schools - Corona Schools{% endblock %}
{% block content %}
<div class="page-header">
    <h2 class="page-title"><i class="fas fa-school"></i> Manage Schools</h2>
    <a href="{{ url_for('add_school') }}" class="btn btn-primary"><i class="fas fa-plus"></i> Add School</a>
</div>
<div class="card">
    <table>
        <tr>
            <th>Name</th>
            <th>Code</th>
            <th>Resumption</th>
            <th>Closing</th>
            <th>API Key</th>
            <th>Actions</th>
        </tr>
        {% for school in schools %}
        <tr>
            <td><strong>{{ school.name }}</strong></td>
            <td>{{ school.code }}</td>
            <td><span class="time-display">{{ school.resumption_time.strftime('%H:%M') if school.resumption_time else '08:00' }}</span></td>
            <td><span class="time-display">{{ school.closing_time.strftime('%H:%M') if school.closing_time else '17:00' }}</span></td>
            <td><code style="background: #f0f0f0; padding: 0.3rem 0.6rem; border-radius: 6px; font-size: 0.8rem;">{{ school.api_key[:16] }}...</code></td>
            <td>
                <a href="{{ url_for('edit_school', id=school.id) }}" class="btn btn-secondary btn-sm"><i class="fas fa-edit"></i> Edit</a>
                <a href="{{ url_for('delete_school', id=school.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Delete this school and all its data?')"><i class="fas fa-trash"></i> Delete</a>
            </td>
        </tr>
        {% else %}
        <tr>
            <td colspan="6">
                <div class="empty-state">
                    <i class="fas fa-school"></i>
                    <p>No schools yet. Add your first school!</p>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

ADD_SCHOOL_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Add School - Corona Schools{% endblock %}
{% block content %}
<h2 class="page-title"><i class="fas fa-plus-circle"></i> Add New School</h2>
<div class="card" style="max-width: 550px;">
    <form method="POST">
        <div class="form-group">
            <label><i class="fas fa-school"></i> School Name</label>
            <input type="text" name="name" required placeholder="e.g. Corona School Gbagada">
        </div>
        <div class="form-group">
            <label><i class="fas fa-code"></i> School Code</label>
            <input type="text" name="code" required placeholder="e.g. CSG">
        </div>
        <div class="form-group">
            <label><i class="fas fa-clock"></i> Resumption Time</label>
            <select name="resumption_time">
                {% for hour in range(5, 12) %}
                <option value="{{ '%02d:00'|format(hour) }}" {% if hour == 8 %}selected{% endif %}>{{ '%02d:00'|format(hour) }}</option>
                <option value="{{ '%02d:30'|format(hour) }}">{{ '%02d:30'|format(hour) }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label><i class="fas fa-door-closed"></i> Closing Time</label>
            <select name="closing_time">
                {% for hour in range(14, 22) %}
                <option value="{{ '%02d:00'|format(hour) }}" {% if hour == 17 %}selected{% endif %}>{{ '%02d:00'|format(hour) }}</option>
                <option value="{{ '%02d:30'|format(hour) }}">{{ '%02d:30'|format(hour) }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="button-group">
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Add School</button>
            <a href="{{ url_for('schools') }}" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>
        </div>
    </form>
</div>
{% endblock %}
'''

EDIT_SCHOOL_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Edit School - Corona Schools{% endblock %}
{% block content %}
<h2 class="page-title"><i class="fas fa-edit"></i> Edit School</h2>
<div class="card" style="max-width: 550px;">
    <form method="POST">
        <div class="form-group">
            <label><i class="fas fa-school"></i> School Name</label>
            <input type="text" name="name" value="{{ school.name }}" required>
        </div>
        <div class="form-group">
            <label><i class="fas fa-code"></i> School Code</label>
            <input type="text" value="{{ school.code }}" disabled style="background: #f5f5f5; cursor: not-allowed;">
        </div>
        <div class="form-group">
            <label><i class="fas fa-clock"></i> Resumption Time</label>
            <select name="resumption_time">
                {% for hour in range(5, 12) %}
                <option value="{{ '%02d:00'|format(hour) }}" {% if school.resumption_time and school.resumption_time.hour == hour and school.resumption_time.minute == 0 %}selected{% endif %}>{{ '%02d:00'|format(hour) }}</option>
                <option value="{{ '%02d:30'|format(hour) }}" {% if school.resumption_time and school.resumption_time.hour == hour and school.resumption_time.minute == 30 %}selected{% endif %}>{{ '%02d:30'|format(hour) }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label><i class="fas fa-door-closed"></i> Closing Time</label>
            <select name="closing_time">
                {% for hour in range(14, 22) %}
                <option value="{{ '%02d:00'|format(hour) }}" {% if school.closing_time and school.closing_time.hour == hour and school.closing_time.minute == 0 %}selected{% endif %}>{{ '%02d:00'|format(hour) }}</option>
                <option value="{{ '%02d:30'|format(hour) }}" {% if school.closing_time and school.closing_time.hour == hour and school.closing_time.minute == 30 %}selected{% endif %}>{{ '%02d:30'|format(hour) }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label><i class="fas fa-key"></i> API Key (for kiosk setup)</label>
            <input type="text" value="{{ school.api_key }}" readonly onclick="this.select()" style="font-family: monospace; background: #f5f5f5; cursor: pointer;">
        </div>
        <div class="button-group">
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Changes</button>
            <a href="{{ url_for('regenerate_key', id=school.id) }}" class="btn btn-warning" onclick="return confirm('Regenerate API key? The kiosk will need reconfiguration.')"><i class="fas fa-sync"></i> Regenerate Key</a>
            <a href="{{ url_for('schools') }}" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>
        </div>
    </form>
</div>
{% endblock %}
'''

STAFF_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Staff - Corona Schools{% endblock %}
{% block content %}
<div class="page-header">
    <h2 class="page-title"><i class="fas fa-users"></i> Manage Staff</h2>
    <a href="{{ url_for('add_staff') }}" class="btn btn-primary"><i class="fas fa-user-plus"></i> Add Staff</a>
</div>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end;">
        <div class="form-group">
            <label><i class="fas fa-school"></i> School</label>
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
        <tr>
            <th>Staff ID</th>
            <th>Name</th>
            <th>Department</th>
            <th>School</th>
            <th>Status</th>
            <th>Actions</th>
        </tr>
        {% for s in staff %}
        <tr>
            <td><strong>{{ s.staff_id }}</strong></td>
            <td>{{ s.name }}</td>
            <td>{{ s.department or '-' }}</td>
            <td>{{ s.school.name }}</td>
            <td><span class="badge {% if s.active %}badge-success{% else %}badge-secondary{% endif %}">{{ 'Active' if s.active else 'Inactive' }}</span></td>
            <td>
                <a href="{{ url_for('toggle_staff', id=s.id) }}" class="btn btn-secondary btn-sm"><i class="fas fa-toggle-{% if s.active %}off{% else %}on{% endif %}"></i> {{ 'Deactivate' if s.active else 'Activate' }}</a>
                <a href="{{ url_for('delete_staff', id=s.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Delete this staff member?')"><i class="fas fa-trash"></i></a>
            </td>
        </tr>
        {% else %}
        <tr>
            <td colspan="6">
                <div class="empty-state">
                    <i class="fas fa-users"></i>
                    <p>No staff members yet</p>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

ADD_STAFF_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Add Staff - Corona Schools{% endblock %}
{% block content %}
<h2 class="page-title"><i class="fas fa-user-plus"></i> Add Staff Member</h2>
<div class="card" style="max-width: 550px;">
    <form method="POST">
        <div class="form-group">
            <label><i class="fas fa-school"></i> School</label>
            <select name="school_id" required>
                {% for school in schools %}
                <option value="{{ school.id }}">{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label><i class="fas fa-id-badge"></i> Staff ID</label>
            <input type="text" name="staff_id" required placeholder="e.g. STF001">
        </div>
        <div class="form-group">
            <label><i class="fas fa-user"></i> Full Name</label>
            <input type="text" name="name" required placeholder="e.g. John Doe">
        </div>
        <div class="form-group">
            <label><i class="fas fa-building"></i> Department (optional)</label>
            <input type="text" name="department" placeholder="e.g. Mathematics">
        </div>
        <div class="button-group">
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Add Staff</button>
            <a href="{{ url_for('staff') }}" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>
        </div>
    </form>
</div>
{% endblock %}
'''

LATECOMERS_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Late Staff - Corona Schools{% endblock %}
{% block content %}
<div class="page-header">
    <h2 class="page-title"><i class="fas fa-user-clock"></i> Late Staff Report</h2>
    <a href="{{ url_for('download_latecomers', school=selected_school or '', date=selected_date) }}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
</div>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
        <div class="form-group">
            <label><i class="fas fa-school"></i> School</label>
            <select name="school">
                <option value="">All Schools</option>
                {% for school in schools %}
                <option value="{{ school.id }}" {% if selected_school == school.id %}selected{% endif %}>{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label><i class="fas fa-calendar"></i> Date</label>
            <input type="date" name="date" value="{{ selected_date }}">
        </div>
        <button type="submit" class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
    </form>
</div>
<div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); max-width: 300px;">
    <div class="stat-card warning">
        <div class="icon"><i class="fas fa-user-clock"></i></div>
        <h3>{{ records|length }}</h3>
        <p>Late Staff</p>
    </div>
</div>
<div class="card">
    <table>
        <tr>
            <th>Staff ID</th>
            <th>Name</th>
            <th>School</th>
            <th>Resumption</th>
            <th>Arrival</th>
            <th>Late By</th>
        </tr>
        {% for r in records %}
        <tr>
            <td><strong>{{ r.staff_id }}</strong></td>
            <td>{{ r.name }}</td>
            <td>{{ r.school }}</td>
            <td><span class="time-display">{{ r.resumption }}</span></td>
            <td><span class="time-display">{{ r.arrival }}</span></td>
            <td><span class="badge badge-danger">{{ r.late_by }}</span></td>
        </tr>
        {% else %}
        <tr>
            <td colspan="6">
                <div class="empty-state">
                    <i class="fas fa-check-circle"></i>
                    <p>No late arrivals for this date!</p>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

OVERTIME_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Overtime Report - Corona Schools{% endblock %}
{% block content %}
<div class="page-header">
    <h2 class="page-title"><i class="fas fa-hourglass-half"></i> Overtime Report</h2>
    <a href="{{ url_for('download_overtime', school=selected_school or '', from_date=from_date, to_date=to_date) }}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
</div>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
        <div class="form-group">
            <label><i class="fas fa-school"></i> School</label>
            <select name="school">
                <option value="">All Schools</option>
                {% for school in schools %}
                <option value="{{ school.id }}" {% if selected_school == school.id %}selected{% endif %}>{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label><i class="fas fa-calendar"></i> From Date</label>
            <input type="date" name="from_date" value="{{ from_date }}">
        </div>
        <div class="form-group">
            <label><i class="fas fa-calendar"></i> To Date</label>
            <input type="date" name="to_date" value="{{ to_date }}">
        </div>
        <button type="submit" class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
    </form>
</div>
<div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); max-width: 300px;">
    <div class="stat-card info">
        <div class="icon"><i class="fas fa-clock"></i></div>
        <h3>{{ total_overtime }}</h3>
        <p>Total Overtime</p>
    </div>
</div>
<div class="card">
    <table>
        <tr>
            <th>Staff ID</th>
            <th>Name</th>
            <th>School</th>
            <th>Days Worked</th>
            <th>Total Overtime</th>
        </tr>
        {% for r in records %}
        <tr>
            <td><strong>{{ r.staff_id }}</strong></td>
            <td>{{ r.name }}</td>
            <td>{{ r.school }}</td>
            <td>{{ r.days_worked }}</td>
            <td><span class="badge badge-info">{{ r.overtime_hours }}h {{ r.overtime_mins }}m</span></td>
        </tr>
        {% else %}
        <tr>
            <td colspan="5">
                <div class="empty-state">
                    <i class="fas fa-clock"></i>
                    <p>No overtime records for this period</p>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

ATTENDANCE_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Attendance Reports - Corona Schools{% endblock %}
{% block content %}
<div class="page-header">
    <h2 class="page-title"><i class="fas fa-chart-bar"></i> Attendance Reports</h2>
    <a href="{{ url_for('download_attendance', school=selected_school or '', from_date=from_date, to_date=to_date) }}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
</div>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end; flex-wrap: wrap;">
        <div class="form-group">
            <label><i class="fas fa-school"></i> School</label>
            <select name="school">
                <option value="">All Schools</option>
                {% for school in schools %}
                <option value="{{ school.id }}" {% if selected_school == school.id %}selected{% endif %}>{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label><i class="fas fa-calendar"></i> From Date</label>
            <input type="date" name="from_date" value="{{ from_date }}">
        </div>
        <div class="form-group">
            <label><i class="fas fa-calendar"></i> To Date</label>
            <input type="date" name="to_date" value="{{ to_date }}">
        </div>
        <button type="submit" class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
    </form>
</div>
<div class="card">
    <table>
        <tr>
            <th>Date</th>
            <th>Staff ID</th>
            <th>Name</th>
            <th>School</th>
            <th>First In</th>
            <th>Last Out</th>
        </tr>
        {% for r in records %}
        <tr>
            <td><strong>{{ r.date }}</strong></td>
            <td>{{ r.staff_id }}</td>
            <td>{{ r.name }}</td>
            <td>{{ r.school }}</td>
            <td><span class="time-display">{{ r.first_in or '-' }}</span></td>
            <td><span class="time-display">{{ r.last_out or '-' }}</span></td>
        </tr>
        {% else %}
        <tr>
            <td colspan="6">
                <div class="empty-state">
                    <i class="fas fa-calendar-times"></i>
                    <p>No attendance records for this period</p>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

TODAY_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Today's Activity - Corona Schools{% endblock %}
{% block content %}
<h2 class="page-title"><i class="fas fa-clock"></i> Today's Activity</h2>
<div class="filter-bar">
    <form method="GET" style="display: flex; gap: 1rem; align-items: flex-end;">
        <div class="form-group">
            <label><i class="fas fa-school"></i> School</label>
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
        <tr>
            <th>Time</th>
            <th>Staff ID</th>
            <th>Name</th>
            <th>School</th>
            <th>Action</th>
        </tr>
        {% for r in records %}
        <tr>
            <td><span class="time-display">{{ r.timestamp.strftime('%H:%M:%S') }}</span></td>
            <td><strong>{{ r.staff_id }}</strong></td>
            <td>{{ r.staff_name }}</td>
            <td>{{ r.school.name }}</td>
            <td><span class="badge {% if r.action == 'IN' %}badge-success{% else %}badge-secondary{% endif %}">{{ r.action }}</span></td>
        </tr>
        {% else %}
        <tr>
            <td colspan="5">
                <div class="empty-state">
                    <i class="fas fa-calendar-day"></i>
                    <p>No activity recorded today</p>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
'''

ADMINS_TEMPLATE = '''
{% extends 'base' %}
{% block title %}Manage Admins - Corona Schools{% endblock %}
{% block content %}
<h2 class="page-title"><i class="fas fa-user-shield"></i> Manage Admins</h2>
<div class="card" style="max-width: 550px; margin-bottom: 2rem;">
    <div class="card-header"><i class="fas fa-user-plus"></i> Add New Admin</div>
    <form method="POST">
        <div class="form-group">
            <label><i class="fas fa-user"></i> Username</label>
            <input type="text" name="username" required placeholder="Enter username">
        </div>
        <div class="form-group">
            <label><i class="fas fa-lock"></i> Password</label>
            <input type="password" name="password" required placeholder="Enter password">
        </div>
        <div class="form-group">
            <label><i class="fas fa-user-tag"></i> Role</label>
            <select name="role" id="role-select" onchange="toggleSchoolSelect()">
                <option value="superadmin">Super Admin (All Schools)</option>
                <option value="schooladmin">School Admin (Single School)</option>
            </select>
        </div>
        <div class="form-group" id="school-group" style="display: none;">
            <label><i class="fas fa-school"></i> School</label>
            <select name="school_id">
                {% for school in schools %}
                <option value="{{ school.id }}">{{ school.name }}</option>
                {% endfor %}
            </select>
        </div>
        <button type="submit" class="btn btn-primary"><i class="fas fa-plus"></i> Add Admin</button>
    </form>
</div>
<script>
function toggleSchoolSelect() {
    var role = document.getElementById('role-select').value;
    document.getElementById('school-group').style.display = role === 'schooladmin' ? 'block' : 'none';
}
</script>
<div class="card">
    <div class="card-header"><i class="fas fa-users-cog"></i> Current Admins</div>
    <table>
        <tr>
            <th>Username</th>
            <th>Role</th>
            <th>School</th>
            <th>Actions</th>
        </tr>
        {% for user in users %}
        <tr>
            <td><strong>{{ user.username }}</strong></td>
            <td><span class="badge {% if user.role == 'superadmin' %}badge-info{% else %}badge-secondary{% endif %}">{{ user.role }}</span></td>
            <td>{{ user.school.name if user.school else 'All Schools' }}</td>
            <td>
                {% if user.username != 'admin' %}
                <a href="{{ url_for('delete_admin', id=user.id) }}" class="btn btn-danger btn-sm" onclick="return confirm('Delete this admin?')"><i class="fas fa-trash"></i> Delete</a>
                {% else %}
                <span style="color: #a0aec0;">Default Admin</span>
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
{% block title %}Settings - Corona Schools{% endblock %}
{% block content %}
<h2 class="page-title"><i class="fas fa-cog"></i> Settings</h2>
<div class="card" style="max-width: 550px;">
    <div class="card-header"><i class="fas fa-key"></i> Change Password</div>
    <form method="POST">
        <div class="form-group">
            <label><i class="fas fa-lock"></i> Current Password</label>
            <input type="password" name="current_password" required placeholder="Enter current password">
        </div>
        <div class="form-group">
            <label><i class="fas fa-lock"></i> New Password</label>
            <input type="password" name="new_password" required placeholder="Enter new password">
        </div>
        <div class="form-group">
            <label><i class="fas fa-lock"></i> Confirm New Password</label>
            <input type="password" name="confirm_password" required placeholder="Confirm new password">
        </div>
        <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Change Password</button>
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
                records.append([staff_id, data['name'], school.name, resumption.strftime('%H:%M'), 
                               data['time'].strftime('%H:%M'), f"{hours}h {mins}m" if hours else f"{mins}m"])
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Resumption Time', 'Arrival Time', 'Late By'])
    writer.writerows(records)
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
                records.append([staff_id, data['name'], school.name, days_worked, 
                               staff_overtime // 60, staff_overtime % 60])
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Days Worked', 'Overtime Hours', 'Overtime Minutes'])
    writer.writerows(records)
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
        flash('School added successfully', 'success')
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
        flash('School updated successfully', 'success')
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
        flash('Staff member added', 'success')
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
    flash('Staff member deleted', 'success')
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
                flash('Password changed successfully', 'success')
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
        db.session.commit()

port = int(os.environ.get('PORT', 5000))
app.run(host='0.0.0.0', port=port, debug=False)
