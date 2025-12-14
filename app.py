from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify, session, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
import os
import secrets
import csv
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    resumption_time = db.Column(db.String(5), default='08:00')
    closing_time = db.Column(db.String(5), default='16:00')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True, cascade='all, delete-orphan')
    attendance = db.relationship('Attendance', backref='school', lazy=True, cascade='all, delete-orphan')

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    firstname = db.Column(db.String(100), nullable=False)
    surname = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), default='')
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance = db.relationship('Attendance', backref='staff', lazy=True, cascade='all, delete-orphan')
    __table_args__ = (db.UniqueConstraint('staff_id', 'school_id', name='unique_staff_per_school'),)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    sign_in = db.Column(db.DateTime)
    sign_out = db.Column(db.DateTime)
    date = db.Column(db.Date, nullable=False)
    synced = db.Column(db.Boolean, default=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Logo URL
LOGO = "https://i.ibb.co/PGPKP3HB/corona-logo-2.png"

# Base template with navigation
def base_template(content, active='dashboard'):
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Corona Schools Attendance</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f7fa; min-height: 100vh; }}
        .sidebar {{ width: 260px; background: linear-gradient(180deg, #8B0000 0%, #A52A2A 100%); min-height: 100vh; position: fixed; left: 0; top: 0; padding: 20px 0; }}
        .logo-container {{ text-align: center; padding: 20px; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }}
        .logo-container img {{ max-width: 120px; height: auto; }}
        .logo-container h2 {{ color: white; font-size: 14px; margin-top: 10px; }}
        .nav-menu {{ list-style: none; }}
        .nav-menu li a {{ display: flex; align-items: center; padding: 15px 25px; color: rgba(255,255,255,0.8); text-decoration: none; transition: all 0.3s; }}
        .nav-menu li a:hover, .nav-menu li a.active {{ background: rgba(255,255,255,0.1); color: white; border-left: 4px solid #FFD700; }}
        .nav-menu li a i {{ margin-right: 12px; width: 20px; }}
        .main-content {{ margin-left: 260px; padding: 30px; }}
        .header {{ background: white; padding: 20px 30px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: center; }}
        .header h1 {{ color: #333; font-size: 24px; }}
        .user-info {{ display: flex; align-items: center; gap: 15px; }}
        .user-info span {{ color: #666; }}
        .btn {{ padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; transition: all 0.3s; }}
        .btn-primary {{ background: #8B0000; color: white; }}
        .btn-primary:hover {{ background: #A52A2A; }}
        .btn-success {{ background: #28a745; color: white; }}
        .btn-success:hover {{ background: #218838; }}
        .btn-danger {{ background: #dc3545; color: white; }}
        .btn-danger:hover {{ background: #c82333; }}
        .btn-secondary {{ background: #6c757d; color: white; }}
        .btn-secondary:hover {{ background: #5a6268; }}
        .card {{ background: white; border-radius: 10px; padding: 25px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat-card {{ background: white; border-radius: 10px; padding: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); border-left: 4px solid #8B0000; }}
        .stat-card.green {{ border-left-color: #28a745; }}
        .stat-card.orange {{ border-left-color: #fd7e14; }}
        .stat-card.red {{ border-left-color: #dc3545; }}
        .stat-card.blue {{ border-left-color: #007bff; }}
        .stat-card h3 {{ color: #666; font-size: 14px; margin-bottom: 10px; }}
        .stat-card .number {{ font-size: 32px; font-weight: bold; color: #333; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; color: #333; }}
        tr:hover {{ background: #f8f9fa; }}
        .form-group {{ margin-bottom: 20px; }}
        .form-group label {{ display: block; margin-bottom: 8px; font-weight: 500; color: #333; }}
        .form-control {{ width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }}
        .form-control:focus {{ outline: none; border-color: #8B0000; }}
        select.form-control {{ cursor: pointer; }}
        .alert {{ padding: 15px 20px; border-radius: 6px; margin-bottom: 20px; }}
        .alert-success {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
        .alert-danger {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
        .alert-info {{ background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }}
        .badge {{ padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
        .badge-success {{ background: #d4edda; color: #155724; }}
        .badge-danger {{ background: #f8d7da; color: #721c24; }}
        .badge-warning {{ background: #fff3cd; color: #856404; }}
        .badge-info {{ background: #d1ecf1; color: #0c5460; }}
        .filter-form {{ display: flex; gap: 15px; flex-wrap: wrap; align-items: end; margin-bottom: 20px; }}
        .filter-form .form-group {{ margin-bottom: 0; min-width: 150px; }}
        .action-buttons {{ display: flex; gap: 8px; }}
        .upload-area {{ border: 2px dashed #ddd; border-radius: 10px; padding: 40px; text-align: center; margin-bottom: 20px; }}
        .upload-area:hover {{ border-color: #8B0000; background: #fef8f8; }}
        .upload-area i {{ font-size: 48px; color: #8B0000; margin-bottom: 15px; }}
        .upload-area p {{ color: #666; margin-bottom: 15px; }}
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo-container">
            <img src="{LOGO_URL}" alt="Corona Schools" onerror="this.style.display='none'">
            <h2>Attendance System</h2>
        </div>
        <ul class="nav-menu">
            <li><a href="/dashboard" class="{'active' if active == 'dashboard' else ''}"><i class="fas fa-home"></i> Dashboard</a></li>
            <li><a href="/schools" class="{'active' if active == 'schools' else ''}"><i class="fas fa-school"></i> Schools</a></li>
            <li><a href="/staff" class="{'active' if active == 'staff' else ''}"><i class="fas fa-users"></i> Staff</a></li>
            <li><a href="/bulk-upload" class="{'active' if active == 'bulk-upload' else ''}"><i class="fas fa-upload"></i> Bulk Upload</a></li>
            <li><a href="/attendance" class="{'active' if active == 'attendance' else ''}"><i class="fas fa-clipboard-list"></i> Attendance</a></li>
            <li><a href="/latecomers" class="{'active' if active == 'latecomers' else ''}"><i class="fas fa-clock"></i> Late Staff</a></li>
            <li><a href="/absent" class="{'active' if active == 'absent' else ''}"><i class="fas fa-user-times"></i> Absent Staff</a></li>
            <li><a href="/overtime" class="{'active' if active == 'overtime' else ''}"><i class="fas fa-hourglass-half"></i> Overtime</a></li>
            <li><a href="/admins" class="{'active' if active == 'admins' else ''}"><i class="fas fa-user-shield"></i> Admins</a></li>
            <li><a href="/settings" class="{'active' if active == 'settings' else ''}"><i class="fas fa-cog"></i> Settings</a></li>
            <li><a href="/logout"><i class="fas fa-sign-out-alt"></i> Logout</a></li>
        </ul>
    </div>
    <div class="main-content">
        {content}
    </div>
</body>
</html>
'''

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    error = ''
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        error = 'Invalid username or password'
    
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Corona Schools Attendance</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #8B0000 0%, #A52A2A 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
        .login-container {{ background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); width: 100%; max-width: 400px; text-align: center; }}
        .login-container img {{ max-width: 150px; margin-bottom: 20px; }}
        .login-container h1 {{ color: #8B0000; margin-bottom: 10px; font-size: 24px; }}
        .login-container p {{ color: #666; margin-bottom: 30px; }}
        .form-group {{ margin-bottom: 20px; text-align: left; }}
        .form-group label {{ display: block; margin-bottom: 8px; font-weight: 500; color: #333; }}
        .form-control {{ width: 100%; padding: 14px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }}
        .form-control:focus {{ outline: none; border-color: #8B0000; }}
        .btn {{ width: 100%; padding: 14px; background: #8B0000; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; transition: background 0.3s; }}
        .btn:hover {{ background: #A52A2A; }}
        .error {{ background: #f8d7da; color: #721c24; padding: 12px; border-radius: 6px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <div class="login-container">
        <img src="{LOGO_URL}" alt="Corona Schools" onerror="this.style.display='none'">
        <h1>Staff Attendance</h1>
        <p>Sign in to access the dashboard</p>
        {'<div class="error">' + error + '</div>' if error else ''}
        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" class="form-control" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" class="form-control" required>
            </div>
            <button type="submit" class="btn">Sign In</button>
        </form>
    </div>
</body>
</html>
'''
    return html

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    school_filter = request.args.get('school', 'all')
    
    schools = School.query.all()
    
    # Base query for staff (excluding Management for absence count)
    if school_filter == 'all':
        total_staff = Staff.query.filter_by(active=True).count()
        # For absent calculation, exclude Management
        countable_staff = Staff.query.filter_by(active=True).filter(Staff.department != 'Management').all()
        today_attendance = Attendance.query.filter_by(date=today).all()
        today_signins = len(set(a.staff_id for a in today_attendance))
        
        # Count signed in staff who are NOT Management
        signed_in_countable = set()
        for a in today_attendance:
            staff = Staff.query.get(a.staff_id)
            if staff and staff.department != 'Management':
                signed_in_countable.add(a.staff_id)
        
        late_count = 0
        for a in today_attendance:
            staff = Staff.query.get(a.staff_id)
            if staff and a.sign_in:
                school = School.query.get(staff.school_id)
                if school:
                    resumption = datetime.strptime(school.resumption_time, '%H:%M').time()
                    if a.sign_in.time() > resumption:
                        late_count += 1
    else:
        school_id = int(school_filter)
        total_staff = Staff.query.filter_by(school_id=school_id, active=True).count()
        countable_staff = Staff.query.filter_by(school_id=school_id, active=True).filter(Staff.department != 'Management').all()
        today_attendance = Attendance.query.filter_by(school_id=school_id, date=today).all()
        today_signins = len(set(a.staff_id for a in today_attendance))
        
        # Count signed in staff who are NOT Management
        signed_in_countable = set()
        for a in today_attendance:
            staff = Staff.query.get(a.staff_id)
            if staff and staff.department != 'Management':
                signed_in_countable.add(a.staff_id)
        
        school = School.query.get(school_id)
        late_count = 0
        if school:
            resumption = datetime.strptime(school.resumption_time, '%H:%M').time()
            for a in today_attendance:
                if a.sign_in and a.sign_in.time() > resumption:
                    late_count += 1
    
    # Absent = countable staff who haven't signed in (Management excluded)
    absent_count = len(countable_staff) - len(signed_in_countable)
    if absent_count < 0:
        absent_count = 0
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <div class="header">
        <h1>Dashboard</h1>
        <div class="user-info">
            <span>Welcome, {current_user.username}</span>
        </div>
    </div>
    
    <div class="card">
        <form method="GET" style="display: flex; gap: 15px; align-items: center;">
            <div class="form-group" style="margin-bottom: 0;">
                <label>Filter by School</label>
                <select name="school" class="form-control" onchange="this.form.submit()">
                    {school_options}
                </select>
            </div>
        </form>
    </div>
    
    <div class="stats-grid">
        <div class="stat-card">
            <h3><i class="fas fa-school"></i> Total Schools</h3>
            <div class="number">{len(schools)}</div>
        </div>
        <div class="stat-card green">
            <h3><i class="fas fa-users"></i> Total Staff</h3>
            <div class="number">{total_staff}</div>
        </div>
        <div class="stat-card blue">
            <h3><i class="fas fa-check-circle"></i> Signed In Today</h3>
            <div class="number">{today_signins}</div>
        </div>
        <div class="stat-card orange">
            <h3><i class="fas fa-clock"></i> Late Today</h3>
            <div class="number">{late_count}</div>
        </div>
        <div class="stat-card red">
            <h3><i class="fas fa-user-times"></i> Absent Today</h3>
            <div class="number">{absent_count}</div>
            <small style="color: #666;">Excludes Management</small>
        </div>
    </div>
    
    <div class="card">
        <h2 style="margin-bottom: 20px;">Schools Overview</h2>
        <table>
            <thead>
                <tr>
                    <th>School Name</th>
                    <th>Resumption</th>
                    <th>Closing</th>
                    <th>Total Staff</th>
                    <th>Signed In Today</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for school in schools:
        school_staff_count = Staff.query.filter_by(school_id=school.id, active=True).count()
        school_today_count = Attendance.query.filter_by(school_id=school.id, date=today).count()
        content += f'''
            <tr>
                <td>{school.name}</td>
                <td>{school.resumption_time}</td>
                <td>{school.closing_time}</td>
                <td>{school_staff_count}</td>
                <td>{school_today_count}</td>
            </tr>
        '''
    
    content += '''
            </tbody>
        </table>
    </div>
    '''
    
    return base_template(content, 'dashboard')

@app.route('/schools')
@login_required
def schools():
    all_schools = School.query.all()
    
    content = '''
    <div class="header">
        <h1>Schools Management</h1>
        <a href="/schools/add" class="btn btn-primary"><i class="fas fa-plus"></i> Add School</a>
    </div>
    
    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>School Name</th>
                    <th>Resumption Time</th>
                    <th>Closing Time</th>
                    <th>API Key</th>
                    <th>Staff Count</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for school in all_schools:
        staff_count = Staff.query.filter_by(school_id=school.id).count()
        content += f'''
            <tr>
                <td>{school.name}</td>
                <td>{school.resumption_time}</td>
                <td>{school.closing_time}</td>
                <td><code style="background: #f1f1f1; padding: 4px 8px; border-radius: 4px; font-size: 12px;">{school.api_key[:20]}...</code></td>
                <td>{staff_count}</td>
                <td class="action-buttons">
                    <a href="/schools/edit/{school.id}" class="btn btn-secondary" style="padding: 6px 12px;"><i class="fas fa-edit"></i></a>
                    <form method="POST" action="/schools/delete/{school.id}" style="display:inline;" onsubmit="return confirm('Delete this school?');">
                        <button type="submit" class="btn btn-danger" style="padding: 6px 12px;"><i class="fas fa-trash"></i></button>
                    </form>
                </td>
            </tr>
        '''
    
    content += '''
            </tbody>
        </table>
    </div>
    '''
    
    return base_template(content, 'schools')

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if request.method == 'POST':
        name = request.form.get('name')
        resumption_time = request.form.get('resumption_time', '08:00')
        closing_time = request.form.get('closing_time', '16:00')
        
        if School.query.filter_by(name=name).first():
            flash('School with this name already exists', 'danger')
        else:
            school = School(
                name=name,
                api_key=secrets.token_hex(32),
                resumption_time=resumption_time,
                closing_time=closing_time
            )
            db.session.add(school)
            db.session.commit()
            flash('School added successfully', 'success')
            return redirect(url_for('schools'))
    
    time_options = ''
    for h in range(6, 22):
        for m in ['00', '30']:
            t = f'{h:02d}:{m}'
            time_options += f'<option value="{t}">{t}</option>'
    
    content = f'''
    <div class="header">
        <h1>Add New School</h1>
    </div>
    
    <div class="card">
        <form method="POST">
            <div class="form-group">
                <label>School Name</label>
                <input type="text" name="name" class="form-control" required>
            </div>
            <div class="form-group">
                <label>Resumption Time</label>
                <select name="resumption_time" class="form-control">
                    {time_options.replace('value="08:00"', 'value="08:00" selected')}
                </select>
            </div>
            <div class="form-group">
                <label>Closing Time</label>
                <select name="closing_time" class="form-control">
                    {time_options.replace('value="16:00"', 'value="16:00" selected')}
                </select>
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save School</button>
            <a href="/schools" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    
    return base_template(content, 'schools')

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_school(id):
    school = School.query.get_or_404(id)
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.resumption_time = request.form.get('resumption_time', '08:00')
        school.closing_time = request.form.get('closing_time', '16:00')
        db.session.commit()
        flash('School updated successfully', 'success')
        return redirect(url_for('schools'))
    
    time_options = ''
    for h in range(6, 22):
        for m in ['00', '30']:
            t = f'{h:02d}:{m}'
            selected_r = 'selected' if t == school.resumption_time else ''
            selected_c = 'selected' if t == school.closing_time else ''
            time_options += f'<option value="{t}">{t}</option>'
    
    # Rebuild with proper selection
    resumption_opts = ''
    closing_opts = ''
    for h in range(6, 22):
        for m in ['00', '30']:
            t = f'{h:02d}:{m}'
            resumption_opts += f'<option value="{t}" {"selected" if t == school.resumption_time else ""}>{t}</option>'
            closing_opts += f'<option value="{t}" {"selected" if t == school.closing_time else ""}>{t}</option>'
    
    content = f'''
    <div class="header">
        <h1>Edit School</h1>
    </div>
    
    <div class="card">
        <form method="POST">
            <div class="form-group">
                <label>School Name</label>
                <input type="text" name="name" class="form-control" value="{school.name}" required>
            </div>
            <div class="form-group">
                <label>Resumption Time</label>
                <select name="resumption_time" class="form-control">
                    {resumption_opts}
                </select>
            </div>
            <div class="form-group">
                <label>Closing Time</label>
                <select name="closing_time" class="form-control">
                    {closing_opts}
                </select>
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Update School</button>
            <a href="/schools" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    
    <div class="card" style="margin-top: 20px;">
        <h3 style="margin-bottom: 15px;">API Key</h3>
        <p style="margin-bottom: 15px;"><code style="background: #f1f1f1; padding: 10px; border-radius: 4px; display: block; word-break: break-all;">{school.api_key}</code></p>
        <form method="POST" action="/schools/regenerate-key/{school.id}" onsubmit="return confirm('Regenerate API key? The kiosk will need to be updated.');">
            <button type="submit" class="btn btn-secondary"><i class="fas fa-sync"></i> Regenerate Key</button>
        </form>
    </div>
    '''
    
    return base_template(content, 'schools')

@app.route('/schools/delete/<int:id>', methods=['POST'])
@login_required
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('School deleted successfully', 'success')
    return redirect(url_for('schools'))

@app.route('/schools/regenerate-key/<int:id>', methods=['POST'])
@login_required
def regenerate_key(id):
    school = School.query.get_or_404(id)
    school.api_key = secrets.token_hex(32)
    db.session.commit()
    flash('API key regenerated successfully', 'success')
    return redirect(url_for('edit_school', id=id))

@app.route('/staff')
@login_required
def staff():
    school_filter = request.args.get('school', 'all')
    schools = School.query.all()
    
    if school_filter == 'all':
        all_staff = Staff.query.all()
    else:
        all_staff = Staff.query.filter_by(school_id=int(school_filter)).all()
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <div class="header">
        <h1>Staff Management</h1>
        <a href="/staff/add" class="btn btn-primary"><i class="fas fa-plus"></i> Add Staff</a>
    </div>
    
    <div class="card" style="margin-bottom: 20px;">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label>Filter by School</label>
                <select name="school" class="form-control" onchange="this.form.submit()">
                    {school_options}
                </select>
            </div>
        </form>
    </div>
    
    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>Staff ID</th>
                    <th>First Name</th>
                    <th>Surname</th>
                    <th>Department</th>
                    <th>School</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for s in all_staff:
        school = School.query.get(s.school_id)
        school_name = school.name if school else 'Unknown'
        status = '<span class="badge badge-success">Active</span>' if s.active else '<span class="badge badge-danger">Inactive</span>'
        dept_badge = f'<span class="badge badge-info">{s.department}</span>' if s.department else '-'
        
        content += f'''
            <tr>
                <td>{s.staff_id}</td>
                <td>{s.firstname}</td>
                <td>{s.surname}</td>
                <td>{dept_badge}</td>
                <td>{school_name}</td>
                <td>{status}</td>
                <td class="action-buttons">
                    <form method="POST" action="/staff/toggle/{s.id}" style="display:inline;">
                        <button type="submit" class="btn {'btn-danger' if s.active else 'btn-success'}" style="padding: 6px 12px;">
                            <i class="fas {'fa-ban' if s.active else 'fa-check'}"></i>
                        </button>
                    </form>
                    <form method="POST" action="/staff/delete/{s.id}" style="display:inline;" onsubmit="return confirm('Delete this staff member?');">
                        <button type="submit" class="btn btn-danger" style="padding: 6px 12px;"><i class="fas fa-trash"></i></button>
                    </form>
                </td>
            </tr>
        '''
    
    content += '''
            </tbody>
        </table>
    </div>
    '''
    
    return base_template(content, 'staff')

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    schools = School.query.all()
    
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        firstname = request.form.get('firstname')
        surname = request.form.get('surname')
        department = request.form.get('department', '')
        school_id = request.form.get('school_id')
        
        existing = Staff.query.filter_by(staff_id=staff_id, school_id=school_id).first()
        if existing:
            flash('Staff ID already exists in this school', 'danger')
        else:
            staff = Staff(
                staff_id=staff_id,
                firstname=firstname,
                surname=surname,
                department=department,
                school_id=school_id
            )
            db.session.add(staff)
            db.session.commit()
            flash('Staff member added successfully', 'success')
            return redirect(url_for('staff'))
    
    school_options = ''
    for s in schools:
        school_options += f'<option value="{s.id}">{s.name}</option>'
    
    content = f'''
    <div class="header">
        <h1>Add New Staff</h1>
    </div>
    
    <div class="card">
        <form method="POST">
            <div class="form-group">
                <label>Staff ID</label>
                <input type="text" name="staff_id" class="form-control" required>
            </div>
            <div class="form-group">
                <label>First Name</label>
                <input type="text" name="firstname" class="form-control" required>
            </div>
            <div class="form-group">
                <label>Surname</label>
                <input type="text" name="surname" class="form-control" required>
            </div>
            <div class="form-group">
                <label>Department</label>
                <input type="text" name="department" class="form-control" placeholder="e.g. Teaching, Admin, Management">
                <small style="color: #666;">Note: Staff with "Management" department will not be counted as absent</small>
            </div>
            <div class="form-group">
                <label>School</label>
                <select name="school_id" class="form-control" required>
                    {school_options}
                </select>
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Staff</button>
            <a href="/staff" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    
    return base_template(content, 'staff')

@app.route('/staff/toggle/<int:id>', methods=['POST'])
@login_required
def toggle_staff(id):
    staff = Staff.query.get_or_404(id)
    staff.active = not staff.active
    db.session.commit()
    return redirect(url_for('staff'))

@app.route('/staff/delete/<int:id>', methods=['POST'])
@login_required
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    db.session.delete(staff)
    db.session.commit()
    flash('Staff member deleted', 'success')
    return redirect(url_for('staff'))

# BULK UPLOAD
@app.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    schools = School.query.all()
    message = ''
    message_type = ''
    
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        file = request.files.get('csv_file')
        
        if not school_id:
            message = 'Please select a school'
            message_type = 'danger'
        elif not file or not file.filename.endswith('.csv'):
            message = 'Please upload a valid CSV file'
            message_type = 'danger'
        else:
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                reader = csv.DictReader(stream)
                
                added = 0
                skipped = 0
                errors = []
                
                for row in reader:
                    # Handle different column name formats
                    firstname = row.get('Firstname') or row.get('firstname') or row.get('FirstName') or row.get('First Name') or ''
                    surname = row.get('Surname') or row.get('surname') or row.get('LastName') or row.get('Last Name') or ''
                    staff_id = row.get('ID') or row.get('id') or row.get('Staff ID') or row.get('StaffID') or row.get('staff_id') or ''
                    department = row.get('Department') or row.get('department') or row.get('Dept') or ''
                    
                    firstname = firstname.strip()
                    surname = surname.strip()
                    staff_id = staff_id.strip()
                    department = department.strip()
                    
                    if not firstname or not surname or not staff_id:
                        skipped += 1
                        continue
                    
                    existing = Staff.query.filter_by(staff_id=staff_id, school_id=school_id).first()
                    if existing:
                        skipped += 1
                        continue
                    
                    staff = Staff(
                        staff_id=staff_id,
                        firstname=firstname,
                        surname=surname,
                        department=department,
                        school_id=school_id
                    )
                    db.session.add(staff)
                    added += 1
                
                db.session.commit()
                message = f'Successfully added {added} staff members. {skipped} skipped (duplicates or missing data).'
                message_type = 'success'
                
            except Exception as e:
                message = f'Error processing file: {str(e)}'
                message_type = 'danger'
    
    school_options = ''
    for s in schools:
        school_options += f'<option value="{s.id}">{s.name}</option>'
    
    alert_html = ''
    if message:
        alert_html = f'<div class="alert alert-{message_type}">{message}</div>'
    
    content = f'''
    <div class="header">
        <h1>Bulk Staff Upload</h1>
    </div>
    
    {alert_html}
    
    <div class="card">
        <h3 style="margin-bottom: 20px;">Upload Staff Records</h3>
        <form method="POST" enctype="multipart/form-data">
            <div class="form-group">
                <label>Select School</label>
                <select name="school_id" class="form-control" required>
                    <option value="">-- Select School --</option>
                    {school_options}
                </select>
            </div>
            
            <div class="upload-area">
                <i class="fas fa-cloud-upload-alt"></i>
                <p>Upload a CSV file with staff records</p>
                <input type="file" name="csv_file" accept=".csv" class="form-control" style="max-width: 400px; margin: 0 auto;" required>
            </div>
            
            <button type="submit" class="btn btn-primary"><i class="fas fa-upload"></i> Upload Staff</button>
        </form>
    </div>
    
    <div class="card">
        <h3 style="margin-bottom: 15px;">CSV Format</h3>
        <p style="margin-bottom: 15px;">Your CSV file should have the following columns:</p>
        <table style="max-width: 500px;">
            <thead>
                <tr>
                    <th>Firstname</th>
                    <th>Surname</th>
                    <th>ID</th>
                    <th>Department</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>John</td>
                    <td>Smith</td>
                    <td>EMP001</td>
                    <td>Teaching</td>
                </tr>
                <tr>
                    <td>Jane</td>
                    <td>Doe</td>
                    <td>EMP002</td>
                    <td>Management</td>
                </tr>
            </tbody>
        </table>
        <p style="margin-top: 15px; color: #666;"><i class="fas fa-info-circle"></i> Staff with "Management" department will not be counted as absent.</p>
        
        <div style="margin-top: 20px;">
            <a href="/download-template" class="btn btn-secondary"><i class="fas fa-download"></i> Download Template</a>
        </div>
    </div>
    '''
    
    return base_template(content, 'bulk-upload')

@app.route('/download-template')
@login_required
def download_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Firstname', 'Surname', 'ID', 'Department'])
    writer.writerow(['John', 'Smith', 'EMP001', 'Teaching'])
    writer.writerow(['Jane', 'Doe', 'EMP002', 'Admin'])
    writer.writerow(['Mary', 'Johnson', 'EMP003', 'Management'])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=staff_template.csv'}
    )

@app.route('/attendance')
@login_required
def attendance():
    schools = School.query.all()
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    query = Attendance.query
    
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    
    query = query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    records = query.order_by(Attendance.date.desc(), Attendance.sign_in.desc()).all()
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <div class="header">
        <h1>Attendance Reports</h1>
        <a href="/attendance/download?school={school_filter}&from_date={from_date}&to_date={to_date}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
    </div>
    
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label>School</label>
                <select name="school" class="form-control">
                    {school_options}
                </select>
            </div>
            <div class="form-group">
                <label>From Date</label>
                <input type="date" name="from_date" class="form-control" value="{from_date}">
            </div>
            <div class="form-group">
                <label>To Date</label>
                <input type="date" name="to_date" class="form-control" value="{to_date}">
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
        </form>
    </div>
    
    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Staff ID</th>
                    <th>Name</th>
                    <th>Department</th>
                    <th>School</th>
                    <th>Sign In</th>
                    <th>Sign Out</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for r in records:
        staff = Staff.query.get(r.staff_id)
        school = School.query.get(r.school_id)
        staff_name = f"{staff.firstname} {staff.surname}" if staff else 'Unknown'
        staff_id_display = staff.staff_id if staff else 'N/A'
        dept = staff.department if staff and staff.department else '-'
        school_name = school.name if school else 'Unknown'
        sign_in = r.sign_in.strftime('%H:%M:%S') if r.sign_in else '-'
        sign_out = r.sign_out.strftime('%H:%M:%S') if r.sign_out else '-'
        
        content += f'''
            <tr>
                <td>{r.date}</td>
                <td>{staff_id_display}</td>
                <td>{staff_name}</td>
                <td>{dept}</td>
                <td>{school_name}</td>
                <td>{sign_in}</td>
                <td>{sign_out}</td>
            </tr>
        '''
    
    content += '''
            </tbody>
        </table>
    </div>
    '''
    
    return base_template(content, 'attendance')

@app.route('/attendance/download')
@login_required
def download_attendance():
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    query = Attendance.query
    
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    
    query = query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    records = query.order_by(Attendance.date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Surname', 'Department', 'School', 'Sign In', 'Sign Out'])
    
    for r in records:
        staff = Staff.query.get(r.staff_id)
        school = School.query.get(r.school_id)
        writer.writerow([
            r.date,
            staff.staff_id if staff else '',
            staff.firstname if staff else '',
            staff.surname if staff else '',
            staff.department if staff else '',
            school.name if school else '',
            r.sign_in.strftime('%H:%M:%S') if r.sign_in else '',
            r.sign_out.strftime('%H:%M:%S') if r.sign_out else ''
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=attendance_{from_date}_to_{to_date}.csv'}
    )

@app.route('/latecomers')
@login_required
def latecomers():
    schools = School.query.all()
    school_filter = request.args.get('school', 'all')
    report_date = request.args.get('date', date.today().isoformat())
    
    late_records = []
    
    if school_filter == 'all':
        attendance_records = Attendance.query.filter_by(date=report_date).all()
    else:
        attendance_records = Attendance.query.filter_by(date=report_date, school_id=int(school_filter)).all()
    
    for a in attendance_records:
        if a.sign_in:
            staff = Staff.query.get(a.staff_id)
            school = School.query.get(a.school_id)
            if school:
                resumption = datetime.strptime(school.resumption_time, '%H:%M').time()
                if a.sign_in.time() > resumption:
                    late_records.append({
                        'staff': staff,
                        'school': school,
                        'sign_in': a.sign_in,
                        'late_by': (datetime.combine(date.today(), a.sign_in.time()) - 
                                   datetime.combine(date.today(), resumption)).seconds // 60
                    })
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <div class="header">
        <h1>Late Staff Report</h1>
        <a href="/latecomers/download?school={school_filter}&date={report_date}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
    </div>
    
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label>School</label>
                <select name="school" class="form-control">
                    {school_options}
                </select>
            </div>
            <div class="form-group">
                <label>Date</label>
                <input type="date" name="date" class="form-control" value="{report_date}">
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
        </form>
    </div>
    
    <div class="card">
        <h3 style="margin-bottom: 15px;">Found {len(late_records)} late staff</h3>
        <table>
            <thead>
                <tr>
                    <th>Staff ID</th>
                    <th>Name</th>
                    <th>Department</th>
                    <th>School</th>
                    <th>Expected</th>
                    <th>Arrived</th>
                    <th>Late By</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for r in late_records:
        content += f'''
            <tr>
                <td>{r['staff'].staff_id}</td>
                <td>{r['staff'].firstname} {r['staff'].surname}</td>
                <td>{r['staff'].department or '-'}</td>
                <td>{r['school'].name}</td>
                <td>{r['school'].resumption_time}</td>
                <td>{r['sign_in'].strftime('%H:%M:%S')}</td>
                <td><span class="badge badge-danger">{r['late_by']} mins</span></td>
            </tr>
        '''
    
    content += '''
            </tbody>
        </table>
    </div>
    '''
    
    return base_template(content, 'latecomers')

@app.route('/latecomers/download')
@login_required
def download_latecomers():
    school_filter = request.args.get('school', 'all')
    report_date = request.args.get('date', date.today().isoformat())
    
    late_records = []
    
    if school_filter == 'all':
        attendance_records = Attendance.query.filter_by(date=report_date).all()
    else:
        attendance_records = Attendance.query.filter_by(date=report_date, school_id=int(school_filter)).all()
    
    for a in attendance_records:
        if a.sign_in:
            staff = Staff.query.get(a.staff_id)
            school = School.query.get(a.school_id)
            if school:
                resumption = datetime.strptime(school.resumption_time, '%H:%M').time()
                if a.sign_in.time() > resumption:
                    late_records.append({
                        'staff': staff,
                        'school': school,
                        'sign_in': a.sign_in,
                        'late_by': (datetime.combine(date.today(), a.sign_in.time()) - 
                                   datetime.combine(date.today(), resumption)).seconds // 60
                    })
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'First Name', 'Surname', 'Department', 'School', 'Expected Time', 'Arrival Time', 'Late By (mins)'])
    
    for r in late_records:
        writer.writerow([
            r['staff'].staff_id,
            r['staff'].firstname,
            r['staff'].surname,
            r['staff'].department or '',
            r['school'].name,
            r['school'].resumption_time,
            r['sign_in'].strftime('%H:%M:%S'),
            r['late_by']
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=latecomers_{report_date}.csv'}
    )

@app.route('/absent')
@login_required
def absent():
    schools = School.query.all()
    school_filter = request.args.get('school', 'all')
    report_date = request.args.get('date', date.today().isoformat())
    
    # Get all active staff (excluding Management)
    if school_filter == 'all':
        all_staff = Staff.query.filter_by(active=True).filter(Staff.department != 'Management').all()
    else:
        all_staff = Staff.query.filter_by(school_id=int(school_filter), active=True).filter(Staff.department != 'Management').all()
    
    # Get staff who signed in
    if school_filter == 'all':
        signed_in = Attendance.query.filter_by(date=report_date).all()
    else:
        signed_in = Attendance.query.filter_by(date=report_date, school_id=int(school_filter)).all()
    
    signed_in_ids = set(a.staff_id for a in signed_in)
    
    # Get absent staff
    absent_staff = [s for s in all_staff if s.id not in signed_in_ids]
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <div class="header">
        <h1>Absent Staff Report</h1>
        <a href="/absent/download?school={school_filter}&date={report_date}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
    </div>
    
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label>School</label>
                <select name="school" class="form-control">
                    {school_options}
                </select>
            </div>
            <div class="form-group">
                <label>Date</label>
                <input type="date" name="date" class="form-control" value="{report_date}">
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
        </form>
    </div>
    
    <div class="card">
        <div class="alert alert-info">
            <i class="fas fa-info-circle"></i> Staff with "Management" department are excluded from this report as they do not sign in.
        </div>
        <h3 style="margin-bottom: 15px;">Found {len(absent_staff)} absent staff</h3>
        <table>
            <thead>
                <tr>
                    <th>Staff ID</th>
                    <th>Name</th>
                    <th>Department</th>
                    <th>School</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for s in absent_staff:
        school = School.query.get(s.school_id)
        content += f'''
            <tr>
                <td>{s.staff_id}</td>
                <td>{s.firstname} {s.surname}</td>
                <td>{s.department or '-'}</td>
                <td>{school.name if school else 'Unknown'}</td>
            </tr>
        '''
    
    content += '''
            </tbody>
        </table>
    </div>
    '''
    
    return base_template(content, 'absent')

@app.route('/absent/download')
@login_required
def download_absent():
    school_filter = request.args.get('school', 'all')
    report_date = request.args.get('date', date.today().isoformat())
    
    if school_filter == 'all':
        all_staff = Staff.query.filter_by(active=True).filter(Staff.department != 'Management').all()
        signed_in = Attendance.query.filter_by(date=report_date).all()
    else:
        all_staff = Staff.query.filter_by(school_id=int(school_filter), active=True).filter(Staff.department != 'Management').all()
        signed_in = Attendance.query.filter_by(date=report_date, school_id=int(school_filter)).all()
    
    signed_in_ids = set(a.staff_id for a in signed_in)
    absent_staff = [s for s in all_staff if s.id not in signed_in_ids]
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'First Name', 'Surname', 'Department', 'School'])
    
    for s in absent_staff:
        school = School.query.get(s.school_id)
        writer.writerow([
            s.staff_id,
            s.firstname,
            s.surname,
            s.department or '',
            school.name if school else ''
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=absent_staff_{report_date}.csv'}
    )

@app.route('/overtime')
@login_required
def overtime():
    schools = School.query.all()
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    overtime_records = []
    
    query = Attendance.query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    
    for a in query.all():
        if a.sign_out:
            staff = Staff.query.get(a.staff_id)
            school = School.query.get(a.school_id)
            if school:
                closing = datetime.strptime(school.closing_time, '%H:%M').time()
                if a.sign_out.time() > closing:
                    overtime_mins = (datetime.combine(date.today(), a.sign_out.time()) - 
                                   datetime.combine(date.today(), closing)).seconds // 60
                    overtime_records.append({
                        'date': a.date,
                        'staff': staff,
                        'school': school,
                        'sign_out': a.sign_out,
                        'overtime_mins': overtime_mins
                    })
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    content = f'''
    <div class="header">
        <h1>Overtime Report</h1>
        <a href="/overtime/download?school={school_filter}&from_date={from_date}&to_date={to_date}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
    </div>
    
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label>School</label>
                <select name="school" class="form-control">
                    {school_options}
                </select>
            </div>
            <div class="form-group">
                <label>From Date</label>
                <input type="date" name="from_date" class="form-control" value="{from_date}">
            </div>
            <div class="form-group">
                <label>To Date</label>
                <input type="date" name="to_date" class="form-control" value="{to_date}">
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
        </form>
    </div>
    
    <div class="card">
        <h3 style="margin-bottom: 15px;">Found {len(overtime_records)} overtime records</h3>
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Staff ID</th>
                    <th>Name</th>
                    <th>Department</th>
                    <th>School</th>
                    <th>Closing Time</th>
                    <th>Left At</th>
                    <th>Overtime</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for r in overtime_records:
        hours = r['overtime_mins'] // 60
        mins = r['overtime_mins'] % 60
        content += f'''
            <tr>
                <td>{r['date']}</td>
                <td>{r['staff'].staff_id}</td>
                <td>{r['staff'].firstname} {r['staff'].surname}</td>
                <td>{r['staff'].department or '-'}</td>
                <td>{r['school'].name}</td>
                <td>{r['school'].closing_time}</td>
                <td>{r['sign_out'].strftime('%H:%M:%S')}</td>
                <td><span class="badge badge-success">{hours}h {mins}m</span></td>
            </tr>
        '''
    
    content += '''
            </tbody>
        </table>
    </div>
    '''
    
    return base_template(content, 'overtime')

@app.route('/overtime/download')
@login_required
def download_overtime():
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    overtime_records = []
    
    query = Attendance.query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    
    for a in query.all():
        if a.sign_out:
            staff = Staff.query.get(a.staff_id)
            school = School.query.get(a.school_id)
            if school:
                closing = datetime.strptime(school.closing_time, '%H:%M').time()
                if a.sign_out.time() > closing:
                    overtime_mins = (datetime.combine(date.today(), a.sign_out.time()) - 
                                   datetime.combine(date.today(), closing)).seconds // 60
                    overtime_records.append({
                        'date': a.date,
                        'staff': staff,
                        'school': school,
                        'sign_out': a.sign_out,
                        'overtime_mins': overtime_mins
                    })
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Surname', 'Department', 'School', 'Closing Time', 'Left At', 'Overtime (mins)'])
    
    for r in overtime_records:
        writer.writerow([
            r['date'],
            r['staff'].staff_id,
            r['staff'].firstname,
            r['staff'].surname,
            r['staff'].department or '',
            r['school'].name,
            r['school'].closing_time,
            r['sign_out'].strftime('%H:%M:%S'),
            r['overtime_mins']
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=overtime_{from_date}_to_{to_date}.csv'}
    )

@app.route('/admins')
@login_required
def admins():
    if not current_user.is_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    all_users = User.query.all()
    
    content = '''
    <div class="header">
        <h1>Admin Management</h1>
        <a href="/admins/add" class="btn btn-primary"><i class="fas fa-plus"></i> Add Admin</a>
    </div>
    
    <div class="card">
        <table>
            <thead>
                <tr>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for u in all_users:
        role = '<span class="badge badge-success">Super Admin</span>' if u.is_admin else '<span class="badge badge-info">User</span>'
        content += f'''
            <tr>
                <td>{u.username}</td>
                <td>{role}</td>
                <td>
                    <form method="POST" action="/admins/delete/{u.id}" style="display:inline;" onsubmit="return confirm('Delete this user?');">
                        <button type="submit" class="btn btn-danger" style="padding: 6px 12px;"><i class="fas fa-trash"></i></button>
                    </form>
                </td>
            </tr>
        '''
    
    content += '''
            </tbody>
        </table>
    </div>
    '''
    
    return base_template(content, 'admins')

@app.route('/admins/add', methods=['GET', 'POST'])
@login_required
def add_admin():
    if not current_user.is_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = request.form.get('is_admin') == 'on'
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
        else:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                is_admin=is_admin
            )
            db.session.add(user)
            db.session.commit()
            flash('User added successfully', 'success')
            return redirect(url_for('admins'))
    
    content = '''
    <div class="header">
        <h1>Add New Admin</h1>
    </div>
    
    <div class="card">
        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" class="form-control" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" class="form-control" required>
            </div>
            <div class="form-group">
                <label style="display: flex; align-items: center; gap: 10px;">
                    <input type="checkbox" name="is_admin">
                    Super Admin privileges
                </label>
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save User</button>
            <a href="/admins" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
    '''
    
    return base_template(content, 'admins')

@app.route('/admins/delete/<int:id>', methods=['POST'])
@login_required
def delete_admin(id):
    if not current_user.is_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('dashboard'))
    
    if id == current_user.id:
        flash('Cannot delete yourself', 'danger')
        return redirect(url_for('admins'))
    
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted', 'success')
    return redirect(url_for('admins'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        
        if check_password_hash(current_user.password_hash, current_password):
            current_user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash('Password changed successfully', 'success')
        else:
            flash('Current password is incorrect', 'danger')
    
    content = '''
    <div class="header">
        <h1>Settings</h1>
    </div>
    
    <div class="card">
        <h3 style="margin-bottom: 20px;">Change Password</h3>
        <form method="POST" style="max-width: 400px;">
            <div class="form-group">
                <label>Current Password</label>
                <input type="password" name="current_password" class="form-control" required>
            </div>
            <div class="form-group">
                <label>New Password</label>
                <input type="password" name="new_password" class="form-control" required>
            </div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Change Password</button>
        </form>
    </div>
    '''
    
    return base_template(content, 'settings')

# API for kiosk sync
@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    
    school = School.query.filter_by(api_key=api_key).first()
    if not school:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    
    # Process attendance records from kiosk
    if 'attendance' in data:
        for record in data['attendance']:
            staff = Staff.query.filter_by(staff_id=record['staff_id'], school_id=school.id).first()
            if staff:
                attendance = Attendance.query.filter_by(
                    staff_id=staff.id,
                    school_id=school.id,
                    date=record['date']
                ).first()
                
                if not attendance:
                    attendance = Attendance(
                        staff_id=staff.id,
                        school_id=school.id,
                        date=record['date']
                    )
                    db.session.add(attendance)
                
                if record.get('sign_in'):
                    attendance.sign_in = datetime.fromisoformat(record['sign_in'])
                if record.get('sign_out'):
                    attendance.sign_out = datetime.fromisoformat(record['sign_out'])
        
        db.session.commit()
    
    # Return school data for kiosk
    staff_list = []
    for s in Staff.query.filter_by(school_id=school.id, active=True).all():
        staff_list.append({
            'id': s.staff_id,
            'firstname': s.firstname,
            'surname': s.surname,
            'department': s.department
        })
    
    return jsonify({
        'school': school.name,
        'resumption_time': school.resumption_time,
        'closing_time': school.closing_time,
        'staff': staff_list
    })

def init_db():
    with app.app_context():
        db.create_all()
        
        # Create default admin if not exists
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print("Default admin created: admin / admin123")

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
