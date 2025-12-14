from flask import Flask, request, redirect, url_for, jsonify, Response, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
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

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    resumption_time = db.Column(db.String(5), default='08:00')
    closing_time = db.Column(db.String(5), default='16:00')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

def get_styles():
    return """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f7fa; min-height: 100vh; }
        .sidebar { width: 250px; background: linear-gradient(180deg, #8B0000 0%, #A52A2A 100%); min-height: 100vh; position: fixed; left: 0; top: 0; padding: 20px 0; }
        .logo { text-align: center; padding: 20px; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; color: white; }
        .logo h2 { font-size: 18px; }
        .nav-menu { list-style: none; }
        .nav-menu li a { display: block; padding: 15px 25px; color: rgba(255,255,255,0.8); text-decoration: none; }
        .nav-menu li a:hover, .nav-menu li a.active { background: rgba(255,255,255,0.1); color: white; border-left: 4px solid #FFD700; }
        .main-content { margin-left: 250px; padding: 30px; }
        .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        .btn { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; font-size: 14px; }
        .btn-primary { background: #8B0000; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-secondary { background: #6c757d; color: white; }
        .card { background: white; border-radius: 10px; padding: 25px; margin-bottom: 20px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .stat-card { background: white; border-radius: 10px; padding: 20px; border-left: 4px solid #8B0000; }
        .stat-card.green { border-left-color: #28a745; }
        .stat-card.orange { border-left-color: #fd7e14; }
        .stat-card.red { border-left-color: #dc3545; }
        .stat-card h3 { color: #666; font-size: 14px; margin-bottom: 10px; }
        .stat-card .number { font-size: 28px; font-weight: bold; color: #333; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: 500; }
        .form-control { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; }
        .alert { padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .alert-success { background: #d4edda; color: #155724; }
        .alert-danger { background: #f8d7da; color: #721c24; }
        .alert-info { background: #d1ecf1; color: #0c5460; }
        .badge { padding: 4px 10px; border-radius: 15px; font-size: 12px; }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-danger { background: #f8d7da; color: #721c24; }
        .badge-info { background: #d1ecf1; color: #0c5460; }
        .filter-form { display: flex; gap: 15px; flex-wrap: wrap; align-items: end; margin-bottom: 20px; }
        .filter-form .form-group { margin-bottom: 0; }
        .upload-area { border: 2px dashed #ddd; padding: 40px; text-align: center; border-radius: 10px; margin-bottom: 20px; }
    </style>
    """

def get_nav(active='dashboard'):
    return f"""
    <div class="sidebar">
        <div class="logo">
            <h2>Corona Schools<br>Attendance</h2>
        </div>
        <ul class="nav-menu">
            <li><a href="/dashboard" class="{'active' if active=='dashboard' else ''}">Dashboard</a></li>
            <li><a href="/schools" class="{'active' if active=='schools' else ''}">Schools</a></li>
            <li><a href="/staff" class="{'active' if active=='staff' else ''}">Staff</a></li>
            <li><a href="/bulk-upload" class="{'active' if active=='bulk-upload' else ''}">Bulk Upload</a></li>
            <li><a href="/attendance" class="{'active' if active=='attendance' else ''}">Attendance</a></li>
            <li><a href="/latecomers" class="{'active' if active=='latecomers' else ''}">Late Staff</a></li>
            <li><a href="/absent" class="{'active' if active=='absent' else ''}">Absent Staff</a></li>
            <li><a href="/overtime" class="{'active' if active=='overtime' else ''}">Overtime</a></li>
            <li><a href="/admins" class="{'active' if active=='admins' else ''}">Admins</a></li>
            <li><a href="/settings" class="{'active' if active=='settings' else ''}">Settings</a></li>
            <li><a href="/logout">Logout</a></li>
        </ul>
    </div>
    """

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
        error = '<div class="alert alert-danger">Invalid username or password</div>'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - Corona Schools Attendance</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #8B0000, #A52A2A); min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
            .login-box {{ background: white; padding: 40px; border-radius: 10px; width: 100%; max-width: 400px; }}
            .login-box h1 {{ color: #8B0000; margin-bottom: 10px; text-align: center; }}
            .login-box p {{ color: #666; margin-bottom: 30px; text-align: center; }}
            .form-group {{ margin-bottom: 20px; }}
            .form-group label {{ display: block; margin-bottom: 5px; font-weight: 500; }}
            .form-control {{ width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 5px; }}
            .btn {{ width: 100%; padding: 12px; background: #8B0000; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }}
            .btn:hover {{ background: #A52A2A; }}
            .alert {{ padding: 10px; border-radius: 5px; margin-bottom: 20px; }}
            .alert-danger {{ background: #f8d7da; color: #721c24; }}
        </style>
    </head>
    <body>
        <div class="login-box">
            <h1>Staff Attendance</h1>
            <p>Sign in to access the dashboard</p>
            {error}
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
    """

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
    
    if school_filter == 'all':
        total_staff = Staff.query.filter_by(active=True).count()
        countable_staff = Staff.query.filter_by(active=True).filter(Staff.department != 'Management').count()
        today_records = Attendance.query.filter_by(date=today).all()
    else:
        school_id = int(school_filter)
        total_staff = Staff.query.filter_by(school_id=school_id, active=True).count()
        countable_staff = Staff.query.filter_by(school_id=school_id, active=True).filter(Staff.department != 'Management').count()
        today_records = Attendance.query.filter_by(school_id=school_id, date=today).all()
    
    signed_in_ids = set()
    signed_in_countable = 0
    late_count = 0
    
    for a in today_records:
        signed_in_ids.add(a.staff_id)
        staff = Staff.query.get(a.staff_id)
        if staff and staff.department != 'Management':
            signed_in_countable += 1
        if staff and a.sign_in:
            school = School.query.get(staff.school_id)
            if school:
                resumption = datetime.strptime(school.resumption_time, '%H:%M').time()
                if a.sign_in.time() > resumption:
                    late_count += 1
    
    absent_count = countable_staff - signed_in_countable
    if absent_count < 0:
        absent_count = 0
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    school_rows = ''
    for s in schools:
        staff_count = Staff.query.filter_by(school_id=s.id, active=True).count()
        today_count = Attendance.query.filter_by(school_id=s.id, date=today).count()
        school_rows += f'<tr><td>{s.name}</td><td>{s.resumption_time}</td><td>{s.closing_time}</td><td>{staff_count}</td><td>{today_count}</td></tr>'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dashboard - Corona Schools Attendance</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('dashboard')}
        <div class="main-content">
            <div class="header">
                <h1>Dashboard</h1>
                <span>Welcome, {current_user.username}</span>
            </div>
            
            <div class="card">
                <form method="GET">
                    <div class="form-group" style="max-width: 300px;">
                        <label>Filter by School</label>
                        <select name="school" class="form-control" onchange="this.form.submit()">
                            {school_options}
                        </select>
                    </div>
                </form>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <h3>Total Schools</h3>
                    <div class="number">{len(schools)}</div>
                </div>
                <div class="stat-card green">
                    <h3>Total Staff</h3>
                    <div class="number">{total_staff}</div>
                </div>
                <div class="stat-card green">
                    <h3>Signed In Today</h3>
                    <div class="number">{len(signed_in_ids)}</div>
                </div>
                <div class="stat-card orange">
                    <h3>Late Today</h3>
                    <div class="number">{late_count}</div>
                </div>
                <div class="stat-card red">
                    <h3>Absent Today</h3>
                    <div class="number">{absent_count}</div>
                    <small style="color:#666;">Excludes Management</small>
                </div>
            </div>
            
            <div class="card">
                <h2 style="margin-bottom: 20px;">Schools Overview</h2>
                <table>
                    <thead>
                        <tr><th>School</th><th>Resumption</th><th>Closing</th><th>Staff</th><th>Signed In</th></tr>
                    </thead>
                    <tbody>
                        {school_rows}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/schools')
@login_required
def schools():
    all_schools = School.query.all()
    
    rows = ''
    for s in all_schools:
        staff_count = Staff.query.filter_by(school_id=s.id).count()
        rows += f'''
        <tr>
            <td>{s.name}</td>
            <td>{s.resumption_time}</td>
            <td>{s.closing_time}</td>
            <td><code>{s.api_key[:20]}...</code></td>
            <td>{staff_count}</td>
            <td>
                <a href="/schools/edit/{s.id}" class="btn btn-secondary" style="padding:5px 10px;">Edit</a>
                <form method="POST" action="/schools/delete/{s.id}" style="display:inline;" onsubmit="return confirm('Delete?');">
                    <button class="btn btn-danger" style="padding:5px 10px;">Delete</button>
                </form>
            </td>
        </tr>
        '''
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Schools - Corona Schools Attendance</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('schools')}
        <div class="main-content">
            <div class="header">
                <h1>Schools</h1>
                <a href="/schools/add" class="btn btn-primary">Add School</a>
            </div>
            <div class="card">
                <table>
                    <thead>
                        <tr><th>Name</th><th>Resumption</th><th>Closing</th><th>API Key</th><th>Staff</th><th>Actions</th></tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if request.method == 'POST':
        name = request.form.get('name')
        resumption = request.form.get('resumption_time', '08:00')
        closing = request.form.get('closing_time', '16:00')
        
        school = School(name=name, api_key=secrets.token_hex(32), resumption_time=resumption, closing_time=closing)
        db.session.add(school)
        db.session.commit()
        return redirect(url_for('schools'))
    
    time_opts = ''.join([f'<option value="{h:02d}:{m:02d}">{h:02d}:{m:02d}</option>' for h in range(6,22) for m in [0,30]])
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Add School</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('schools')}
        <div class="main-content">
            <div class="header"><h1>Add School</h1></div>
            <div class="card">
                <form method="POST">
                    <div class="form-group">
                        <label>School Name</label>
                        <input type="text" name="name" class="form-control" required>
                    </div>
                    <div class="form-group">
                        <label>Resumption Time</label>
                        <select name="resumption_time" class="form-control">{time_opts.replace('value="08:00"', 'value="08:00" selected')}</select>
                    </div>
                    <div class="form-group">
                        <label>Closing Time</label>
                        <select name="closing_time" class="form-control">{time_opts.replace('value="16:00"', 'value="16:00" selected')}</select>
                    </div>
                    <button class="btn btn-primary">Save</button>
                    <a href="/schools" class="btn btn-secondary">Cancel</a>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_school(id):
    school = School.query.get_or_404(id)
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.resumption_time = request.form.get('resumption_time', '08:00')
        school.closing_time = request.form.get('closing_time', '16:00')
        db.session.commit()
        return redirect(url_for('schools'))
    
    time_opts = ''.join([f'<option value="{h:02d}:{m:02d}" {"selected" if f"{h:02d}:{m:02d}"==school.resumption_time else ""}>{h:02d}:{m:02d}</option>' for h in range(6,22) for m in [0,30]])
    time_opts_c = ''.join([f'<option value="{h:02d}:{m:02d}" {"selected" if f"{h:02d}:{m:02d}"==school.closing_time else ""}>{h:02d}:{m:02d}</option>' for h in range(6,22) for m in [0,30]])
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Edit School</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('schools')}
        <div class="main-content">
            <div class="header"><h1>Edit School</h1></div>
            <div class="card">
                <form method="POST">
                    <div class="form-group">
                        <label>School Name</label>
                        <input type="text" name="name" class="form-control" value="{school.name}" required>
                    </div>
                    <div class="form-group">
                        <label>Resumption Time</label>
                        <select name="resumption_time" class="form-control">{time_opts}</select>
                    </div>
                    <div class="form-group">
                        <label>Closing Time</label>
                        <select name="closing_time" class="form-control">{time_opts_c}</select>
                    </div>
                    <button class="btn btn-primary">Update</button>
                    <a href="/schools" class="btn btn-secondary">Cancel</a>
                </form>
            </div>
            <div class="card">
                <h3>API Key</h3>
                <p><code>{school.api_key}</code></p>
                <form method="POST" action="/schools/regenerate/{school.id}">
                    <button class="btn btn-secondary">Regenerate Key</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/schools/delete/<int:id>', methods=['POST'])
@login_required
def delete_school(id):
    school = School.query.get_or_404(id)
    Staff.query.filter_by(school_id=id).delete()
    Attendance.query.filter_by(school_id=id).delete()
    db.session.delete(school)
    db.session.commit()
    return redirect(url_for('schools'))

@app.route('/schools/regenerate/<int:id>', methods=['POST'])
@login_required
def regenerate_key(id):
    school = School.query.get_or_404(id)
    school.api_key = secrets.token_hex(32)
    db.session.commit()
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
    
    rows = ''
    for s in all_staff:
        school = School.query.get(s.school_id)
        status = '<span class="badge badge-success">Active</span>' if s.active else '<span class="badge badge-danger">Inactive</span>'
        dept = f'<span class="badge badge-info">{s.department}</span>' if s.department else '-'
        rows += f'''
        <tr>
            <td>{s.staff_id}</td>
            <td>{s.firstname}</td>
            <td>{s.surname}</td>
            <td>{dept}</td>
            <td>{school.name if school else "Unknown"}</td>
            <td>{status}</td>
            <td>
                <form method="POST" action="/staff/toggle/{s.id}" style="display:inline;">
                    <button class="btn btn-secondary" style="padding:5px 10px;">Toggle</button>
                </form>
                <form method="POST" action="/staff/delete/{s.id}" style="display:inline;" onsubmit="return confirm('Delete?');">
                    <button class="btn btn-danger" style="padding:5px 10px;">Delete</button>
                </form>
            </td>
        </tr>
        '''
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Staff - Corona Schools Attendance</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('staff')}
        <div class="main-content">
            <div class="header">
                <h1>Staff</h1>
                <a href="/staff/add" class="btn btn-primary">Add Staff</a>
            </div>
            <div class="card">
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
                        <tr><th>ID</th><th>First Name</th><th>Surname</th><th>Department</th><th>School</th><th>Status</th><th>Actions</th></tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    schools = School.query.all()
    
    if request.method == 'POST':
        staff = Staff(
            staff_id=request.form.get('staff_id'),
            firstname=request.form.get('firstname'),
            surname=request.form.get('surname'),
            department=request.form.get('department', ''),
            school_id=request.form.get('school_id')
        )
        db.session.add(staff)
        db.session.commit()
        return redirect(url_for('staff'))
    
    school_opts = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Add Staff</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('staff')}
        <div class="main-content">
            <div class="header"><h1>Add Staff</h1></div>
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
                        <small style="color:#666;">Staff with "Management" will not be counted as absent</small>
                    </div>
                    <div class="form-group">
                        <label>School</label>
                        <select name="school_id" class="form-control" required>{school_opts}</select>
                    </div>
                    <button class="btn btn-primary">Save</button>
                    <a href="/staff" class="btn btn-secondary">Cancel</a>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

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
    Attendance.query.filter_by(staff_id=id).delete()
    db.session.delete(staff)
    db.session.commit()
    return redirect(url_for('staff'))

@app.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    schools = School.query.all()
    message = ''
    
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        file = request.files.get('csv_file')
        
        if not school_id or not file:
            message = '<div class="alert alert-danger">Please select a school and upload a file</div>'
        else:
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                reader = csv.DictReader(stream)
                added = 0
                skipped = 0
                
                for row in reader:
                    firstname = row.get('Firstname') or row.get('firstname') or row.get('First Name') or ''
                    surname = row.get('Surname') or row.get('surname') or row.get('Last Name') or ''
                    staff_id = row.get('ID') or row.get('id') or row.get('Staff ID') or row.get('staff_id') or ''
                    department = row.get('Department') or row.get('department') or ''
                    
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
                    
                    staff = Staff(staff_id=staff_id, firstname=firstname, surname=surname, department=department, school_id=school_id)
                    db.session.add(staff)
                    added += 1
                
                db.session.commit()
                message = f'<div class="alert alert-success">Added {added} staff. Skipped {skipped}.</div>'
            except Exception as e:
                message = f'<div class="alert alert-danger">Error: {str(e)}</div>'
    
    school_opts = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bulk Upload</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('bulk-upload')}
        <div class="main-content">
            <div class="header"><h1>Bulk Upload Staff</h1></div>
            {message}
            <div class="card">
                <form method="POST" enctype="multipart/form-data">
                    <div class="form-group">
                        <label>Select School</label>
                        <select name="school_id" class="form-control" required>
                            <option value="">-- Select --</option>
                            {school_opts}
                        </select>
                    </div>
                    <div class="upload-area">
                        <p>Upload CSV file with columns: Firstname, Surname, ID, Department</p>
                        <input type="file" name="csv_file" accept=".csv" class="form-control" style="max-width:400px;margin:0 auto;" required>
                    </div>
                    <button class="btn btn-primary">Upload</button>
                </form>
            </div>
            <div class="card">
                <h3>CSV Format Example</h3>
                <table style="max-width:500px;">
                    <thead><tr><th>Firstname</th><th>Surname</th><th>ID</th><th>Department</th></tr></thead>
                    <tbody>
                        <tr><td>John</td><td>Smith</td><td>EMP001</td><td>Teaching</td></tr>
                        <tr><td>Jane</td><td>Doe</td><td>EMP002</td><td>Management</td></tr>
                    </tbody>
                </table>
                <p style="margin-top:15px;color:#666;">Staff with "Management" department will not be counted as absent.</p>
                <a href="/download-template" class="btn btn-secondary" style="margin-top:15px;">Download Template</a>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/download-template')
@login_required
def download_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Firstname', 'Surname', 'ID', 'Department'])
    writer.writerow(['John', 'Smith', 'EMP001', 'Teaching'])
    writer.writerow(['Jane', 'Doe', 'EMP002', 'Management'])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=staff_template.csv'})

@app.route('/attendance')
@login_required
def attendance():
    schools = School.query.all()
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    query = Attendance.query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    records = query.order_by(Attendance.date.desc()).all()
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    rows = ''
    for r in records:
        staff = Staff.query.get(r.staff_id)
        school = School.query.get(r.school_id)
        rows += f'''
        <tr>
            <td>{r.date}</td>
            <td>{staff.staff_id if staff else "-"}</td>
            <td>{staff.firstname + " " + staff.surname if staff else "Unknown"}</td>
            <td>{staff.department if staff else "-"}</td>
            <td>{school.name if school else "Unknown"}</td>
            <td>{r.sign_in.strftime("%H:%M:%S") if r.sign_in else "-"}</td>
            <td>{r.sign_out.strftime("%H:%M:%S") if r.sign_out else "-"}</td>
        </tr>
        '''
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Attendance</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('attendance')}
        <div class="main-content">
            <div class="header">
                <h1>Attendance Reports</h1>
                <a href="/attendance/download?school={school_filter}&from_date={from_date}&to_date={to_date}" class="btn btn-success">Download CSV</a>
            </div>
            <div class="card">
                <form method="GET" class="filter-form">
                    <div class="form-group">
                        <label>School</label>
                        <select name="school" class="form-control">{school_options}</select>
                    </div>
                    <div class="form-group">
                        <label>From</label>
                        <input type="date" name="from_date" class="form-control" value="{from_date}">
                    </div>
                    <div class="form-group">
                        <label>To</label>
                        <input type="date" name="to_date" class="form-control" value="{to_date}">
                    </div>
                    <button class="btn btn-primary">Filter</button>
                </form>
            </div>
            <div class="card">
                <table>
                    <thead><tr><th>Date</th><th>Staff ID</th><th>Name</th><th>Dept</th><th>School</th><th>Sign In</th><th>Sign Out</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/attendance/download')
@login_required
def download_attendance():
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    query = Attendance.query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    records = query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Surname', 'Department', 'School', 'Sign In', 'Sign Out'])
    for r in records:
        staff = Staff.query.get(r.staff_id)
        school = School.query.get(r.school_id)
        writer.writerow([r.date, staff.staff_id if staff else '', staff.firstname if staff else '', staff.surname if staff else '', staff.department if staff else '', school.name if school else '', r.sign_in.strftime('%H:%M:%S') if r.sign_in else '', r.sign_out.strftime('%H:%M:%S') if r.sign_out else ''])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=attendance_{from_date}_to_{to_date}.csv'})

@app.route('/latecomers')
@login_required
def latecomers():
    schools = School.query.all()
    school_filter = request.args.get('school', 'all')
    report_date = request.args.get('date', date.today().isoformat())
    
    if school_filter == 'all':
        records = Attendance.query.filter_by(date=report_date).all()
    else:
        records = Attendance.query.filter_by(date=report_date, school_id=int(school_filter)).all()
    
    late_list = []
    for a in records:
        if a.sign_in:
            staff = Staff.query.get(a.staff_id)
            school = School.query.get(a.school_id)
            if school:
                resumption = datetime.strptime(school.resumption_time, '%H:%M').time()
                if a.sign_in.time() > resumption:
                    late_mins = (datetime.combine(date.today(), a.sign_in.time()) - datetime.combine(date.today(), resumption)).seconds // 60
                    late_list.append({'staff': staff, 'school': school, 'sign_in': a.sign_in, 'late_mins': late_mins})
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    rows = ''
    for r in late_list:
        rows += f'<tr><td>{r["staff"].staff_id}</td><td>{r["staff"].firstname} {r["staff"].surname}</td><td>{r["staff"].department or "-"}</td><td>{r["school"].name}</td><td>{r["school"].resumption_time}</td><td>{r["sign_in"].strftime("%H:%M:%S")}</td><td><span class="badge badge-danger">{r["late_mins"]} mins</span></td></tr>'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Late Staff</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('latecomers')}
        <div class="main-content">
            <div class="header">
                <h1>Late Staff Report</h1>
                <a href="/latecomers/download?school={school_filter}&date={report_date}" class="btn btn-success">Download CSV</a>
            </div>
            <div class="card">
                <form method="GET" class="filter-form">
                    <div class="form-group">
                        <label>School</label>
                        <select name="school" class="form-control">{school_options}</select>
                    </div>
                    <div class="form-group">
                        <label>Date</label>
                        <input type="date" name="date" class="form-control" value="{report_date}">
                    </div>
                    <button class="btn btn-primary">Filter</button>
                </form>
            </div>
            <div class="card">
                <h3>{len(late_list)} late staff found</h3>
                <table>
                    <thead><tr><th>Staff ID</th><th>Name</th><th>Dept</th><th>School</th><th>Expected</th><th>Arrived</th><th>Late By</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/latecomers/download')
@login_required
def download_latecomers():
    school_filter = request.args.get('school', 'all')
    report_date = request.args.get('date', date.today().isoformat())
    
    if school_filter == 'all':
        records = Attendance.query.filter_by(date=report_date).all()
    else:
        records = Attendance.query.filter_by(date=report_date, school_id=int(school_filter)).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'First Name', 'Surname', 'Department', 'School', 'Expected', 'Arrived', 'Late By (mins)'])
    
    for a in records:
        if a.sign_in:
            staff = Staff.query.get(a.staff_id)
            school = School.query.get(a.school_id)
            if school:
                resumption = datetime.strptime(school.resumption_time, '%H:%M').time()
                if a.sign_in.time() > resumption:
                    late_mins = (datetime.combine(date.today(), a.sign_in.time()) - datetime.combine(date.today(), resumption)).seconds // 60
                    writer.writerow([staff.staff_id, staff.firstname, staff.surname, staff.department or '', school.name, school.resumption_time, a.sign_in.strftime('%H:%M:%S'), late_mins])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=latecomers_{report_date}.csv'})

@app.route('/absent')
@login_required
def absent():
    schools = School.query.all()
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
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    rows = ''
    for s in absent_staff:
        school = School.query.get(s.school_id)
        rows += f'<tr><td>{s.staff_id}</td><td>{s.firstname} {s.surname}</td><td>{s.department or "-"}</td><td>{school.name if school else "Unknown"}</td></tr>'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Absent Staff</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('absent')}
        <div class="main-content">
            <div class="header">
                <h1>Absent Staff Report</h1>
                <a href="/absent/download?school={school_filter}&date={report_date}" class="btn btn-success">Download CSV</a>
            </div>
            <div class="card">
                <form method="GET" class="filter-form">
                    <div class="form-group">
                        <label>School</label>
                        <select name="school" class="form-control">{school_options}</select>
                    </div>
                    <div class="form-group">
                        <label>Date</label>
                        <input type="date" name="date" class="form-control" value="{report_date}">
                    </div>
                    <button class="btn btn-primary">Filter</button>
                </form>
            </div>
            <div class="card">
                <div class="alert alert-info">Staff with "Management" department are excluded from this report.</div>
                <h3>{len(absent_staff)} absent staff found</h3>
                <table>
                    <thead><tr><th>Staff ID</th><th>Name</th><th>Dept</th><th>School</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """

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
        writer.writerow([s.staff_id, s.firstname, s.surname, s.department or '', school.name if school else ''])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=absent_{report_date}.csv'})

@app.route('/overtime')
@login_required
def overtime():
    schools = School.query.all()
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    query = Attendance.query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    
    overtime_list = []
    for a in query.all():
        if a.sign_out:
            staff = Staff.query.get(a.staff_id)
            school = School.query.get(a.school_id)
            if school:
                closing = datetime.strptime(school.closing_time, '%H:%M').time()
                if a.sign_out.time() > closing:
                    ot_mins = (datetime.combine(date.today(), a.sign_out.time()) - datetime.combine(date.today(), closing)).seconds // 60
                    overtime_list.append({'date': a.date, 'staff': staff, 'school': school, 'sign_out': a.sign_out, 'ot_mins': ot_mins})
    
    school_options = '<option value="all">All Schools</option>'
    for s in schools:
        selected = 'selected' if school_filter == str(s.id) else ''
        school_options += f'<option value="{s.id}" {selected}>{s.name}</option>'
    
    rows = ''
    for r in overtime_list:
        hrs = r['ot_mins'] // 60
        mins = r['ot_mins'] % 60
        rows += f'<tr><td>{r["date"]}</td><td>{r["staff"].staff_id}</td><td>{r["staff"].firstname} {r["staff"].surname}</td><td>{r["staff"].department or "-"}</td><td>{r["school"].name}</td><td>{r["school"].closing_time}</td><td>{r["sign_out"].strftime("%H:%M:%S")}</td><td><span class="badge badge-success">{hrs}h {mins}m</span></td></tr>'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Overtime</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('overtime')}
        <div class="main-content">
            <div class="header">
                <h1>Overtime Report</h1>
                <a href="/overtime/download?school={school_filter}&from_date={from_date}&to_date={to_date}" class="btn btn-success">Download CSV</a>
            </div>
            <div class="card">
                <form method="GET" class="filter-form">
                    <div class="form-group">
                        <label>School</label>
                        <select name="school" class="form-control">{school_options}</select>
                    </div>
                    <div class="form-group">
                        <label>From</label>
                        <input type="date" name="from_date" class="form-control" value="{from_date}">
                    </div>
                    <div class="form-group">
                        <label>To</label>
                        <input type="date" name="to_date" class="form-control" value="{to_date}">
                    </div>
                    <button class="btn btn-primary">Filter</button>
                </form>
            </div>
            <div class="card">
                <h3>{len(overtime_list)} overtime records found</h3>
                <table>
                    <thead><tr><th>Date</th><th>Staff ID</th><th>Name</th><th>Dept</th><th>School</th><th>Closing</th><th>Left At</th><th>Overtime</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/overtime/download')
@login_required
def download_overtime():
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    query = Attendance.query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Surname', 'Department', 'School', 'Closing', 'Left At', 'Overtime (mins)'])
    
    for a in query.all():
        if a.sign_out:
            staff = Staff.query.get(a.staff_id)
            school = School.query.get(a.school_id)
            if school:
                closing = datetime.strptime(school.closing_time, '%H:%M').time()
                if a.sign_out.time() > closing:
                    ot_mins = (datetime.combine(date.today(), a.sign_out.time()) - datetime.combine(date.today(), closing)).seconds // 60
                    writer.writerow([a.date, staff.staff_id, staff.firstname, staff.surname, staff.department or '', school.name, school.closing_time, a.sign_out.strftime('%H:%M:%S'), ot_mins])
    
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=overtime_{from_date}_to_{to_date}.csv'})

@app.route('/admins')
@login_required
def admins():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    all_users = User.query.all()
    rows = ''
    for u in all_users:
        role = '<span class="badge badge-success">Admin</span>' if u.is_admin else '<span class="badge badge-info">User</span>'
        rows += f'''
        <tr>
            <td>{u.username}</td>
            <td>{role}</td>
            <td>
                <form method="POST" action="/admins/delete/{u.id}" style="display:inline;" onsubmit="return confirm('Delete?');">
                    <button class="btn btn-danger" style="padding:5px 10px;">Delete</button>
                </form>
            </td>
        </tr>
        '''
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admins</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('admins')}
        <div class="main-content">
            <div class="header">
                <h1>Admin Management</h1>
                <a href="/admins/add" class="btn btn-primary">Add Admin</a>
            </div>
            <div class="card">
                <table>
                    <thead><tr><th>Username</th><th>Role</th><th>Actions</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/admins/add', methods=['GET', 'POST'])
@login_required
def add_admin():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        user = User(
            username=request.form.get('username'),
            password_hash=generate_password_hash(request.form.get('password')),
            is_admin=request.form.get('is_admin') == 'on'
        )
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('admins'))
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Add Admin</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('admins')}
        <div class="main-content">
            <div class="header"><h1>Add Admin</h1></div>
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
                        <label><input type="checkbox" name="is_admin"> Super Admin</label>
                    </div>
                    <button class="btn btn-primary">Save</button>
                    <a href="/admins" class="btn btn-secondary">Cancel</a>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/admins/delete/<int:id>', methods=['POST'])
@login_required
def delete_admin(id):
    if not current_user.is_admin or id == current_user.id:
        return redirect(url_for('admins'))
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for('admins'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    message = ''
    if request.method == 'POST':
        if check_password_hash(current_user.password_hash, request.form.get('current_password')):
            current_user.password_hash = generate_password_hash(request.form.get('new_password'))
            db.session.commit()
            message = '<div class="alert alert-success">Password changed!</div>'
        else:
            message = '<div class="alert alert-danger">Current password incorrect</div>'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Settings</title>
        {get_styles()}
    </head>
    <body>
        {get_nav('settings')}
        <div class="main-content">
            <div class="header"><h1>Settings</h1></div>
            {message}
            <div class="card">
                <h3>Change Password</h3>
                <form method="POST" style="max-width:400px;">
                    <div class="form-group">
                        <label>Current Password</label>
                        <input type="password" name="current_password" class="form-control" required>
                    </div>
                    <div class="form-group">
                        <label>New Password</label>
                        <input type="password" name="new_password" class="form-control" required>
                    </div>
                    <button class="btn btn-primary">Change Password</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    school = School.query.filter_by(api_key=api_key).first()
    if not school:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    if 'attendance' in data:
        for record in data['attendance']:
            staff = Staff.query.filter_by(staff_id=record['staff_id'], school_id=school.id).first()
            if staff:
                att = Attendance.query.filter_by(staff_id=staff.id, school_id=school.id, date=record['date']).first()
                if not att:
                    att = Attendance(staff_id=staff.id, school_id=school.id, date=record['date'])
                    db.session.add(att)
                if record.get('sign_in'):
                    att.sign_in = datetime.fromisoformat(record['sign_in'])
                if record.get('sign_out'):
                    att.sign_out = datetime.fromisoformat(record['sign_out'])
        db.session.commit()
    
    staff_list = [{'id': s.staff_id, 'firstname': s.firstname, 'surname': s.surname, 'department': s.department} for s in Staff.query.filter_by(school_id=school.id, active=True).all()]
    return jsonify({'school': school.name, 'resumption_time': school.resumption_time, 'closing_time': school.closing_time, 'staff': staff_list})

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', password_hash=generate_password_hash('admin123'), is_admin=True)
            db.session.add(admin)
            db.session.commit()

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
