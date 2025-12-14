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

LOGO_URL = "https://i.ibb.co/PGPKP3HB/corona-logo-2.png"

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
    return '''
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; min-height: 100vh; }
        
        .sidebar { width: 260px; background: linear-gradient(180deg, #8B0000 0%, #6d0000 50%, #4a0000 100%); min-height: 100vh; position: fixed; left: 0; top: 0; padding: 0; box-shadow: 4px 0 15px rgba(0,0,0,0.1); z-index: 100; }
        .logo-section { padding: 20px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); }
        .logo-section img { max-width: 80px; height: auto; margin-bottom: 10px; border-radius: 8px; }
        .logo-section h1 { color: #fff; font-size: 16px; font-weight: 600; margin-bottom: 3px; }
        .logo-section span { color: rgba(255,255,255,0.7); font-size: 11px; }
        
        .nav-menu { list-style: none; padding: 15px 0; }
        .nav-menu li { margin: 2px 0; }
        .nav-menu li a { display: flex; align-items: center; padding: 14px 25px; color: rgba(255,255,255,0.8); text-decoration: none; font-size: 14px; font-weight: 500; transition: all 0.3s ease; border-left: 3px solid transparent; }
        .nav-menu li a:hover { background: rgba(255,255,255,0.1); color: #fff; border-left-color: #FFD700; }
        .nav-menu li a.active { background: rgba(255,255,255,0.15); color: #fff; border-left-color: #FFD700; }
        .nav-menu li a i { margin-right: 12px; width: 20px; text-align: center; font-size: 16px; }
        
        .main-content { margin-left: 260px; padding: 30px; min-height: 100vh; }
        
        .header { background: #fff; padding: 25px 30px; border-radius: 12px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 12px rgba(0,0,0,0.04); }
        .header h1 { color: #1a1a2e; font-size: 26px; font-weight: 700; }
        .header-right { display: flex; align-items: center; gap: 15px; }
        .user-badge { background: #f8f9fa; padding: 8px 16px; border-radius: 20px; font-size: 14px; color: #666; }
        
        .btn { padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; transition: all 0.3s ease; }
        .btn-primary { background: linear-gradient(135deg, #8B0000, #a50000); color: #fff; box-shadow: 0 4px 12px rgba(139,0,0,0.3); }
        .btn-primary:hover { background: linear-gradient(135deg, #a50000, #8B0000); transform: translateY(-2px); box-shadow: 0 6px 16px rgba(139,0,0,0.4); }
        .btn-success { background: linear-gradient(135deg, #28a745, #20c040); color: #fff; box-shadow: 0 4px 12px rgba(40,167,69,0.3); }
        .btn-success:hover { transform: translateY(-2px); }
        .btn-danger { background: linear-gradient(135deg, #dc3545, #e04555); color: #fff; }
        .btn-danger:hover { transform: translateY(-2px); }
        .btn-secondary { background: #6c757d; color: #fff; }
        .btn-sm { padding: 8px 16px; font-size: 13px; }
        
        .card { background: #fff; border-radius: 12px; padding: 25px; margin-bottom: 25px; box-shadow: 0 2px 12px rgba(0,0,0,0.04); }
        .card h2, .card h3 { color: #1a1a2e; margin-bottom: 20px; font-weight: 600; }
        
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 25px; }
        .stat-card { background: #fff; border-radius: 12px; padding: 25px; box-shadow: 0 2px 12px rgba(0,0,0,0.04); border-left: 4px solid #8B0000; transition: transform 0.3s ease; }
        .stat-card:hover { transform: translateY(-3px); }
        .stat-card.green { border-left-color: #28a745; }
        .stat-card.blue { border-left-color: #007bff; }
        .stat-card.orange { border-left-color: #fd7e14; }
        .stat-card.red { border-left-color: #dc3545; }
        .stat-card h3 { color: #666; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }
        .stat-card .number { font-size: 36px; font-weight: 700; color: #1a1a2e; }
        .stat-card small { color: #999; font-size: 12px; }
        
        table { width: 100%; border-collapse: collapse; }
        th { background: #f8f9fa; padding: 14px 16px; text-align: left; font-weight: 600; color: #333; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #eee; }
        td { padding: 14px 16px; border-bottom: 1px solid #f0f0f0; color: #444; font-size: 14px; }
        tr:hover { background: #fafbfc; }
        
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; margin-bottom: 8px; font-weight: 600; color: #333; font-size: 14px; }
        .form-control { width: 100%; padding: 12px 16px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 14px; transition: border-color 0.3s, box-shadow 0.3s; }
        .form-control:focus { outline: none; border-color: #8B0000; box-shadow: 0 0 0 3px rgba(139,0,0,0.1); }
        
        .alert { padding: 16px 20px; border-radius: 8px; margin-bottom: 20px; font-weight: 500; }
        .alert-success { background: linear-gradient(135deg, #d4edda, #c3e6cb); color: #155724; border: 1px solid #b8dabc; }
        .alert-danger { background: linear-gradient(135deg, #f8d7da, #f5c6cb); color: #721c24; border: 1px solid #f1b5bb; }
        .alert-info { background: linear-gradient(135deg, #d1ecf1, #bee5eb); color: #0c5460; border: 1px solid #abdde5; }
        
        .badge { padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .badge-success { background: #d4edda; color: #155724; }
        .badge-danger { background: #f8d7da; color: #721c24; }
        .badge-info { background: #d1ecf1; color: #0c5460; }
        .badge-warning { background: #fff3cd; color: #856404; }
        
        .filter-form { display: flex; gap: 15px; flex-wrap: wrap; align-items: flex-end; }
        .filter-form .form-group { margin-bottom: 0; min-width: 180px; }
        
        .upload-area { border: 2px dashed #d0d0d0; padding: 50px; text-align: center; border-radius: 12px; margin: 20px 0; background: #fafbfc; transition: all 0.3s; }
        .upload-area:hover { border-color: #8B0000; background: #fff5f5; }
        .upload-area p { color: #666; margin-bottom: 20px; font-size: 16px; }
        
        code { background: #f4f4f4; padding: 4px 8px; border-radius: 4px; font-size: 13px; color: #e83e8c; }
        
        .action-btns { display: flex; gap: 8px; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    '''

def get_nav(active='dashboard'):
    items = [
        ('dashboard', 'fa-home', 'Dashboard'),
        ('schools', 'fa-school', 'Schools'),
        ('staff', 'fa-users', 'Staff'),
        ('bulk-upload', 'fa-cloud-upload-alt', 'Bulk Upload'),
        ('attendance', 'fa-clipboard-list', 'Attendance'),
        ('latecomers', 'fa-clock', 'Late Staff'),
        ('absent', 'fa-user-times', 'Absent Staff'),
        ('overtime', 'fa-hourglass-half', 'Overtime'),
        ('admins', 'fa-user-shield', 'Admins'),
        ('settings', 'fa-cog', 'Settings'),
    ]
    
    nav_items = ''
    for key, icon, label in items:
        active_class = 'active' if active == key else ''
        url = '/dashboard' if key == 'dashboard' else f'/{key}'
        nav_items += f'<li><a href="{url}" class="{active_class}"><i class="fas {icon}"></i> {label}</a></li>'
    
    return f'''
    <div class="sidebar">
        <div class="logo-section">
            <img src="{LOGO_URL}" alt="Corona Schools" onerror="this.style.display='none'">
            <h1>Corona Schools</h1>
            <span>Staff Attendance System</span>
        </div>
        <ul class="nav-menu">
            {nav_items}
            <li><a href="/logout"><i class="fas fa-sign-out-alt"></i> Logout</a></li>
        </ul>
    </div>
    '''

def page(title, content, active='dashboard'):
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Corona Schools Attendance</title>
    {get_styles()}
</head>
<body>
    {get_nav(active)}
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
        error = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> Invalid username or password</div>'
    
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Corona Schools Attendance</title>
    {get_styles()}
    <style>
        body {{ background: linear-gradient(135deg, #8B0000 0%, #4a0000 100%); display: flex; align-items: center; justify-content: center; }}
        .login-container {{ background: #fff; padding: 50px; border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 100%; max-width: 420px; }}
        .login-header {{ text-align: center; margin-bottom: 35px; }}
        .login-header img {{ max-width: 100px; height: auto; margin-bottom: 15px; border-radius: 8px; }}
        .login-header h1 {{ color: #1a1a2e; font-size: 28px; margin-bottom: 8px; }}
        .login-header p {{ color: #666; }}
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <img src="{LOGO_URL}" alt="Corona Schools" onerror="this.style.display='none'">
            <h1>Corona Schools</h1>
            <p>Staff Attendance System</p>
        </div>
        {error}
        <form method="POST">
            <div class="form-group">
                <label><i class="fas fa-user"></i> Username</label>
                <input type="text" name="username" class="form-control" placeholder="Enter your username" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-lock"></i> Password</label>
                <input type="password" name="password" class="form-control" placeholder="Enter your password" required>
            </div>
            <button type="submit" class="btn btn-primary" style="width: 100%; padding: 14px; font-size: 16px;">
                <i class="fas fa-sign-in-alt"></i> Sign In
            </button>
        </form>
    </div>
</body>
</html>
'''

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
        s = Staff.query.get(a.staff_id)
        if s and s.department != 'Management':
            signed_in_countable += 1
        if s and a.sign_in:
            sch = School.query.get(s.school_id)
            if sch:
                try:
                    res_time = datetime.strptime(sch.resumption_time, '%H:%M').time()
                    if a.sign_in.time() > res_time:
                        late_count += 1
                except:
                    pass
    
    absent_count = max(0, countable_staff - signed_in_countable)
    
    school_opts = '<option value="all">All Schools</option>'
    for s in schools:
        sel = 'selected' if school_filter == str(s.id) else ''
        school_opts += f'<option value="{s.id}" {sel}>{s.name}</option>'
    
    school_rows = ''
    for s in schools:
        sc = Staff.query.filter_by(school_id=s.id, active=True).count()
        tc = Attendance.query.filter_by(school_id=s.id, date=today).count()
        school_rows += f'<tr><td><strong>{s.name}</strong></td><td>{s.resumption_time}</td><td>{s.closing_time}</td><td>{sc}</td><td><span class="badge badge-success">{tc}</span></td></tr>'
    
    content = f'''
    <div class="header">
        <h1><i class="fas fa-home"></i> Dashboard</h1>
        <div class="header-right">
            <span class="user-badge"><i class="fas fa-user"></i> {current_user.username}</span>
        </div>
    </div>
    
    <div class="card">
        <form method="GET" style="max-width: 300px;">
            <div class="form-group" style="margin-bottom: 0;">
                <label><i class="fas fa-filter"></i> Filter by School</label>
                <select name="school" class="form-control" onchange="this.form.submit()">{school_opts}</select>
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
            <div class="number">{len(signed_in_ids)}</div>
        </div>
        <div class="stat-card orange">
            <h3><i class="fas fa-clock"></i> Late Today</h3>
            <div class="number">{late_count}</div>
        </div>
        <div class="stat-card red">
            <h3><i class="fas fa-user-times"></i> Absent Today</h3>
            <div class="number">{absent_count}</div>
            <small>Excludes Management</small>
        </div>
    </div>
    
    <div class="card">
        <h2><i class="fas fa-building"></i> Schools Overview</h2>
        <table>
            <thead><tr><th>School Name</th><th>Resumption</th><th>Closing</th><th>Total Staff</th><th>Signed In</th></tr></thead>
            <tbody>{school_rows if school_rows else '<tr><td colspan="5" style="text-align:center;color:#999;">No schools added yet</td></tr>'}</tbody>
        </table>
    </div>
    '''
    return page('Dashboard', content, 'dashboard')

@app.route('/schools')
@login_required
def schools():
    all_schools = School.query.all()
    rows = ''
    for s in all_schools:
        sc = Staff.query.filter_by(school_id=s.id).count()
        rows += f'''<tr>
            <td><strong>{s.name}</strong></td><td>{s.resumption_time}</td><td>{s.closing_time}</td>
            <td><code>{s.api_key[:16]}...</code></td><td><span class="badge badge-info">{sc}</span></td>
            <td class="action-btns">
                <a href="/schools/edit/{s.id}" class="btn btn-secondary btn-sm"><i class="fas fa-edit"></i></a>
                <form method="POST" action="/schools/delete/{s.id}" style="display:inline;" onsubmit="return confirm('Delete this school?');">
                    <button class="btn btn-danger btn-sm"><i class="fas fa-trash"></i></button>
                </form>
            </td>
        </tr>'''
    
    content = f'''
    <div class="header">
        <h1><i class="fas fa-school"></i> Schools</h1>
        <a href="/schools/add" class="btn btn-primary"><i class="fas fa-plus"></i> Add School</a>
    </div>
    <div class="card">
        <table>
            <thead><tr><th>School Name</th><th>Resumption</th><th>Closing</th><th>API Key</th><th>Staff</th><th>Actions</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="6" style="text-align:center;color:#999;">No schools yet</td></tr>'}</tbody>
        </table>
    </div>
    '''
    return page('Schools', content, 'schools')

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
def add_school():
    if request.method == 'POST':
        s = School(name=request.form.get('name'), api_key=secrets.token_hex(32), 
                   resumption_time=request.form.get('resumption_time', '08:00'),
                   closing_time=request.form.get('closing_time', '16:00'))
        db.session.add(s)
        db.session.commit()
        return redirect(url_for('schools'))
    
    time_opts = ''.join([f'<option value="{h:02d}:{m:02d}" {"selected" if h==8 and m==0 else ""}>{h:02d}:{m:02d}</option>' for h in range(5,23) for m in [0,30]])
    time_opts_c = ''.join([f'<option value="{h:02d}:{m:02d}" {"selected" if h==16 and m==0 else ""}>{h:02d}:{m:02d}</option>' for h in range(5,23) for m in [0,30]])
    
    content = f'''
    <div class="header"><h1><i class="fas fa-plus-circle"></i> Add New School</h1></div>
    <div class="card">
        <form method="POST" style="max-width: 500px;">
            <div class="form-group">
                <label><i class="fas fa-school"></i> School Name</label>
                <input type="text" name="name" class="form-control" placeholder="e.g. Corona Secondary School Agbara" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-clock"></i> Resumption Time</label>
                <select name="resumption_time" class="form-control">{time_opts}</select>
            </div>
            <div class="form-group">
                <label><i class="fas fa-clock"></i> Closing Time</label>
                <select name="closing_time" class="form-control">{time_opts_c}</select>
            </div>
            <div style="display:flex;gap:10px;">
                <button class="btn btn-primary"><i class="fas fa-save"></i> Save School</button>
                <a href="/schools" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>
            </div>
        </form>
    </div>
    '''
    return page('Add School', content, 'schools')

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_school(id):
    s = School.query.get_or_404(id)
    if request.method == 'POST':
        s.name = request.form.get('name')
        s.resumption_time = request.form.get('resumption_time', '08:00')
        s.closing_time = request.form.get('closing_time', '16:00')
        db.session.commit()
        return redirect(url_for('schools'))
    
    time_opts = ''.join([f'<option value="{h:02d}:{m:02d}" {"selected" if f"{h:02d}:{m:02d}"==s.resumption_time else ""}>{h:02d}:{m:02d}</option>' for h in range(5,23) for m in [0,30]])
    time_opts_c = ''.join([f'<option value="{h:02d}:{m:02d}" {"selected" if f"{h:02d}:{m:02d}"==s.closing_time else ""}>{h:02d}:{m:02d}</option>' for h in range(5,23) for m in [0,30]])
    
    content = f'''
    <div class="header"><h1><i class="fas fa-edit"></i> Edit School</h1></div>
    <div class="card">
        <form method="POST" style="max-width: 500px;">
            <div class="form-group">
                <label><i class="fas fa-school"></i> School Name</label>
                <input type="text" name="name" class="form-control" value="{s.name}" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-clock"></i> Resumption Time</label>
                <select name="resumption_time" class="form-control">{time_opts}</select>
            </div>
            <div class="form-group">
                <label><i class="fas fa-clock"></i> Closing Time</label>
                <select name="closing_time" class="form-control">{time_opts_c}</select>
            </div>
            <div style="display:flex;gap:10px;">
                <button class="btn btn-primary"><i class="fas fa-save"></i> Update</button>
                <a href="/schools" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>
            </div>
        </form>
    </div>
    <div class="card">
        <h3><i class="fas fa-key"></i> API Key</h3>
        <p style="margin:15px 0;"><code style="word-break:break-all;">{s.api_key}</code></p>
        <form method="POST" action="/schools/regenerate/{s.id}" onsubmit="return confirm('Regenerate API key?');">
            <button class="btn btn-secondary btn-sm"><i class="fas fa-sync"></i> Regenerate</button>
        </form>
    </div>
    '''
    return page('Edit School', content, 'schools')

@app.route('/schools/delete/<int:id>', methods=['POST'])
@login_required
def delete_school(id):
    s = School.query.get_or_404(id)
    Staff.query.filter_by(school_id=id).delete()
    Attendance.query.filter_by(school_id=id).delete()
    db.session.delete(s)
    db.session.commit()
    return redirect(url_for('schools'))

@app.route('/schools/regenerate/<int:id>', methods=['POST'])
@login_required
def regenerate_key(id):
    s = School.query.get_or_404(id)
    s.api_key = secrets.token_hex(32)
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
    
    school_opts = '<option value="all">All Schools</option>'
    for s in schools:
        sel = 'selected' if school_filter == str(s.id) else ''
        school_opts += f'<option value="{s.id}" {sel}>{s.name}</option>'
    
    rows = ''
    for st in all_staff:
        sch = School.query.get(st.school_id)
        status = '<span class="badge badge-success">Active</span>' if st.active else '<span class="badge badge-danger">Inactive</span>'
        dept = f'<span class="badge badge-info">{st.department}</span>' if st.department else '-'
        rows += f'''<tr>
            <td><strong>{st.staff_id}</strong></td><td>{st.firstname}</td><td>{st.surname}</td><td>{dept}</td>
            <td>{sch.name if sch else "Unknown"}</td><td>{status}</td>
            <td class="action-btns">
                <form method="POST" action="/staff/toggle/{st.id}" style="display:inline;">
                    <button class="btn btn-secondary btn-sm" title="Toggle"><i class="fas fa-power-off"></i></button>
                </form>
                <form method="POST" action="/staff/delete/{st.id}" style="display:inline;" onsubmit="return confirm('Delete?');">
                    <button class="btn btn-danger btn-sm"><i class="fas fa-trash"></i></button>
                </form>
            </td>
        </tr>'''
    
    content = f'''
    <div class="header">
        <h1><i class="fas fa-users"></i> Staff Management</h1>
        <a href="/staff/add" class="btn btn-primary"><i class="fas fa-plus"></i> Add Staff</a>
    </div>
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label><i class="fas fa-filter"></i> Filter by School</label>
                <select name="school" class="form-control" onchange="this.form.submit()">{school_opts}</select>
            </div>
        </form>
    </div>
    <div class="card">
        <table>
            <thead><tr><th>Staff ID</th><th>First Name</th><th>Surname</th><th>Department</th><th>School</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="7" style="text-align:center;color:#999;">No staff found</td></tr>'}</tbody>
        </table>
    </div>
    '''
    return page('Staff', content, 'staff')

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    schools = School.query.all()
    if request.method == 'POST':
        st = Staff(staff_id=request.form.get('staff_id'), firstname=request.form.get('firstname'),
                   surname=request.form.get('surname'), department=request.form.get('department', ''),
                   school_id=request.form.get('school_id'))
        db.session.add(st)
        db.session.commit()
        return redirect(url_for('staff'))
    
    school_opts = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    
    content = f'''
    <div class="header"><h1><i class="fas fa-user-plus"></i> Add New Staff</h1></div>
    <div class="card">
        <form method="POST" style="max-width: 500px;">
            <div class="form-group">
                <label><i class="fas fa-id-badge"></i> Staff ID</label>
                <input type="text" name="staff_id" class="form-control" placeholder="e.g. EMP001" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-user"></i> First Name</label>
                <input type="text" name="firstname" class="form-control" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-user"></i> Surname</label>
                <input type="text" name="surname" class="form-control" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-briefcase"></i> Department</label>
                <input type="text" name="department" class="form-control" placeholder="e.g. Teaching, Admin, Management">
                <small style="color:#666;"><i class="fas fa-info-circle"></i> Staff with "Management" won't be counted as absent</small>
            </div>
            <div class="form-group">
                <label><i class="fas fa-school"></i> School</label>
                <select name="school_id" class="form-control" required>
                    <option value="">-- Select --</option>{school_opts}
                </select>
            </div>
            <div style="display:flex;gap:10px;">
                <button class="btn btn-primary"><i class="fas fa-save"></i> Save</button>
                <a href="/staff" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>
            </div>
        </form>
    </div>
    '''
    return page('Add Staff', content, 'staff')

@app.route('/staff/toggle/<int:id>', methods=['POST'])
@login_required
def toggle_staff(id):
    st = Staff.query.get_or_404(id)
    st.active = not st.active
    db.session.commit()
    return redirect(url_for('staff'))

@app.route('/staff/delete/<int:id>', methods=['POST'])
@login_required
def delete_staff(id):
    st = Staff.query.get_or_404(id)
    Attendance.query.filter_by(staff_id=id).delete()
    db.session.delete(st)
    db.session.commit()
    return redirect(url_for('staff'))

@app.route('/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    schools = School.query.all()
    msg = ''
    
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        file = request.files.get('csv_file')
        
        if not school_id or not file:
            msg = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> Please select school and file</div>'
        else:
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                reader = csv.DictReader(stream)
                added, skipped = 0, 0
                
                for row in reader:
                    fn = (row.get('Firstname') or row.get('firstname') or row.get('First Name') or '').strip()
                    sn = (row.get('Surname') or row.get('surname') or row.get('Last Name') or '').strip()
                    sid = (row.get('ID') or row.get('id') or row.get('Staff ID') or row.get('staff_id') or '').strip()
                    dept = (row.get('Department') or row.get('department') or '').strip()
                    
                    if not fn or not sn or not sid:
                        skipped += 1
                        continue
                    if Staff.query.filter_by(staff_id=sid, school_id=school_id).first():
                        skipped += 1
                        continue
                    
                    db.session.add(Staff(staff_id=sid, firstname=fn, surname=sn, department=dept, school_id=school_id))
                    added += 1
                
                db.session.commit()
                msg = f'<div class="alert alert-success"><i class="fas fa-check-circle"></i> Added <strong>{added}</strong> staff. Skipped <strong>{skipped}</strong>.</div>'
            except Exception as e:
                msg = f'<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> Error: {str(e)}</div>'
    
    school_opts = ''.join([f'<option value="{s.id}">{s.name}</option>' for s in schools])
    
    content = f'''
    <div class="header"><h1><i class="fas fa-cloud-upload-alt"></i> Bulk Staff Upload</h1></div>
    {msg}
    <div class="card">
        <h3><i class="fas fa-upload"></i> Upload Staff Records</h3>
        <form method="POST" enctype="multipart/form-data">
            <div class="form-group" style="max-width:400px;">
                <label><i class="fas fa-school"></i> Select School</label>
                <select name="school_id" class="form-control" required>
                    <option value="">-- Select --</option>{school_opts}
                </select>
            </div>
            <div class="upload-area">
                <i class="fas fa-file-csv" style="font-size:48px;color:#8B0000;display:block;margin-bottom:15px;"></i>
                <p>Upload CSV with: Firstname, Surname, ID, Department</p>
                <input type="file" name="csv_file" accept=".csv" class="form-control" style="max-width:400px;margin:0 auto;" required>
            </div>
            <button class="btn btn-primary"><i class="fas fa-upload"></i> Upload</button>
        </form>
    </div>
    <div class="card">
        <h3><i class="fas fa-info-circle"></i> CSV Format</h3>
        <table style="max-width:500px;">
            <thead><tr><th>Firstname</th><th>Surname</th><th>ID</th><th>Department</th></tr></thead>
            <tbody>
                <tr><td>John</td><td>Smith</td><td>EMP001</td><td>Teaching</td></tr>
                <tr><td>Jane</td><td>Doe</td><td>EMP002</td><td>Management</td></tr>
            </tbody>
        </table>
        <div class="alert alert-info" style="margin-top:20px;max-width:500px;">
            <i class="fas fa-lightbulb"></i> "Management" staff won't be counted as absent
        </div>
        <a href="/download-template" class="btn btn-secondary" style="margin-top:15px;"><i class="fas fa-download"></i> Download Template</a>
    </div>
    '''
    return page('Bulk Upload', content, 'bulk-upload')

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
    
    school_opts = '<option value="all">All Schools</option>'
    for s in schools:
        sel = 'selected' if school_filter == str(s.id) else ''
        school_opts += f'<option value="{s.id}" {sel}>{s.name}</option>'
    
    rows = ''
    for r in records:
        st = Staff.query.get(r.staff_id)
        sch = School.query.get(r.school_id)
        dept = f'<span class="badge badge-info">{st.department}</span>' if st and st.department else '-'
        rows += f'''<tr>
            <td>{r.date}</td><td><strong>{st.staff_id if st else "-"}</strong></td>
            <td>{st.firstname + " " + st.surname if st else "Unknown"}</td><td>{dept}</td>
            <td>{sch.name if sch else "Unknown"}</td>
            <td>{r.sign_in.strftime("%H:%M:%S") if r.sign_in else "-"}</td>
            <td>{r.sign_out.strftime("%H:%M:%S") if r.sign_out else "-"}</td>
        </tr>'''
    
    content = f'''
    <div class="header">
        <h1><i class="fas fa-clipboard-list"></i> Attendance Reports</h1>
        <a href="/attendance/download?school={school_filter}&from_date={from_date}&to_date={to_date}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
    </div>
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label><i class="fas fa-school"></i> School</label>
                <select name="school" class="form-control">{school_opts}</select>
            </div>
            <div class="form-group">
                <label><i class="fas fa-calendar"></i> From</label>
                <input type="date" name="from_date" class="form-control" value="{from_date}">
            </div>
            <div class="form-group">
                <label><i class="fas fa-calendar"></i> To</label>
                <input type="date" name="to_date" class="form-control" value="{to_date}">
            </div>
            <button class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
        </form>
    </div>
    <div class="card">
        <table>
            <thead><tr><th>Date</th><th>Staff ID</th><th>Name</th><th>Dept</th><th>School</th><th>Sign In</th><th>Sign Out</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="7" style="text-align:center;color:#999;">No records found</td></tr>'}</tbody>
        </table>
    </div>
    '''
    return page('Attendance', content, 'attendance')

@app.route('/attendance/download')
@login_required
def download_attendance():
    school_filter = request.args.get('school', 'all')
    from_date = request.args.get('from_date', date.today().isoformat())
    to_date = request.args.get('to_date', date.today().isoformat())
    
    query = Attendance.query.filter(Attendance.date >= from_date, Attendance.date <= to_date)
    if school_filter != 'all':
        query = query.filter_by(school_id=int(school_filter))
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'First Name', 'Surname', 'Department', 'School', 'Sign In', 'Sign Out'])
    for r in query.all():
        st = Staff.query.get(r.staff_id)
        sch = School.query.get(r.school_id)
        writer.writerow([r.date, st.staff_id if st else '', st.firstname if st else '', st.surname if st else '', 
                         st.department if st else '', sch.name if sch else '',
                         r.sign_in.strftime('%H:%M:%S') if r.sign_in else '', r.sign_out.strftime('%H:%M:%S') if r.sign_out else ''])
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
            st = Staff.query.get(a.staff_id)
            sch = School.query.get(a.school_id)
            if sch:
                try:
                    res = datetime.strptime(sch.resumption_time, '%H:%M').time()
                    if a.sign_in.time() > res:
                        mins = (datetime.combine(date.today(), a.sign_in.time()) - datetime.combine(date.today(), res)).seconds // 60
                        late_list.append({'staff': st, 'school': sch, 'sign_in': a.sign_in, 'mins': mins})
                except:
                    pass
    
    school_opts = '<option value="all">All Schools</option>'
    for s in schools:
        sel = 'selected' if school_filter == str(s.id) else ''
        school_opts += f'<option value="{s.id}" {sel}>{s.name}</option>'
    
    rows = ''
    for r in late_list:
        dept = f'<span class="badge badge-info">{r["staff"].department}</span>' if r["staff"].department else '-'
        rows += f'''<tr>
            <td><strong>{r["staff"].staff_id}</strong></td><td>{r["staff"].firstname} {r["staff"].surname}</td>
            <td>{dept}</td><td>{r["school"].name}</td><td>{r["school"].resumption_time}</td>
            <td>{r["sign_in"].strftime("%H:%M:%S")}</td><td><span class="badge badge-danger">{r["mins"]} mins</span></td>
        </tr>'''
    
    content = f'''
    <div class="header">
        <h1><i class="fas fa-clock"></i> Late Staff Report</h1>
        <a href="/latecomers/download?school={school_filter}&date={report_date}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
    </div>
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label><i class="fas fa-school"></i> School</label>
                <select name="school" class="form-control">{school_opts}</select>
            </div>
            <div class="form-group">
                <label><i class="fas fa-calendar"></i> Date</label>
                <input type="date" name="date" class="form-control" value="{report_date}">
            </div>
            <button class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
        </form>
    </div>
    <div class="card">
        <h3><i class="fas fa-exclamation-triangle" style="color:#fd7e14;"></i> {len(late_list)} late staff found</h3>
        <table>
            <thead><tr><th>Staff ID</th><th>Name</th><th>Dept</th><th>School</th><th>Expected</th><th>Arrived</th><th>Late By</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="7" style="text-align:center;color:#999;">No late arrivals</td></tr>'}</tbody>
        </table>
    </div>
    '''
    return page('Late Staff', content, 'latecomers')

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
            st = Staff.query.get(a.staff_id)
            sch = School.query.get(a.school_id)
            if sch:
                try:
                    res = datetime.strptime(sch.resumption_time, '%H:%M').time()
                    if a.sign_in.time() > res:
                        mins = (datetime.combine(date.today(), a.sign_in.time()) - datetime.combine(date.today(), res)).seconds // 60
                        writer.writerow([st.staff_id, st.firstname, st.surname, st.department or '', sch.name, sch.resumption_time, a.sign_in.strftime('%H:%M:%S'), mins])
                except:
                    pass
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
    
    signed_ids = set(a.staff_id for a in signed_in)
    absent_staff = [s for s in all_staff if s.id not in signed_ids]
    
    school_opts = '<option value="all">All Schools</option>'
    for s in schools:
        sel = 'selected' if school_filter == str(s.id) else ''
        school_opts += f'<option value="{s.id}" {sel}>{s.name}</option>'
    
    rows = ''
    for s in absent_staff:
        sch = School.query.get(s.school_id)
        dept = f'<span class="badge badge-info">{s.department}</span>' if s.department else '-'
        rows += f'<tr><td><strong>{s.staff_id}</strong></td><td>{s.firstname} {s.surname}</td><td>{dept}</td><td>{sch.name if sch else "Unknown"}</td></tr>'
    
    content = f'''
    <div class="header">
        <h1><i class="fas fa-user-times"></i> Absent Staff Report</h1>
        <a href="/absent/download?school={school_filter}&date={report_date}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
    </div>
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label><i class="fas fa-school"></i> School</label>
                <select name="school" class="form-control">{school_opts}</select>
            </div>
            <div class="form-group">
                <label><i class="fas fa-calendar"></i> Date</label>
                <input type="date" name="date" class="form-control" value="{report_date}">
            </div>
            <button class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
        </form>
    </div>
    <div class="card">
        <div class="alert alert-info"><i class="fas fa-info-circle"></i> "Management" staff are excluded from this report</div>
        <h3><i class="fas fa-user-times" style="color:#dc3545;"></i> {len(absent_staff)} absent staff found</h3>
        <table>
            <thead><tr><th>Staff ID</th><th>Name</th><th>Dept</th><th>School</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;color:#999;">Everyone present!</td></tr>'}</tbody>
        </table>
    </div>
    '''
    return page('Absent Staff', content, 'absent')

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
    
    signed_ids = set(a.staff_id for a in signed_in)
    absent_staff = [s for s in all_staff if s.id not in signed_ids]
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'First Name', 'Surname', 'Department', 'School'])
    for s in absent_staff:
        sch = School.query.get(s.school_id)
        writer.writerow([s.staff_id, s.firstname, s.surname, s.department or '', sch.name if sch else ''])
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
    
    ot_list = []
    for a in query.all():
        if a.sign_out:
            st = Staff.query.get(a.staff_id)
            sch = School.query.get(a.school_id)
            if sch:
                try:
                    closing = datetime.strptime(sch.closing_time, '%H:%M').time()
                    if a.sign_out.time() > closing:
                        mins = (datetime.combine(date.today(), a.sign_out.time()) - datetime.combine(date.today(), closing)).seconds // 60
                        ot_list.append({'date': a.date, 'staff': st, 'school': sch, 'sign_out': a.sign_out, 'mins': mins})
                except:
                    pass
    
    school_opts = '<option value="all">All Schools</option>'
    for s in schools:
        sel = 'selected' if school_filter == str(s.id) else ''
        school_opts += f'<option value="{s.id}" {sel}>{s.name}</option>'
    
    rows = ''
    for r in ot_list:
        h, m = r['mins'] // 60, r['mins'] % 60
        dept = f'<span class="badge badge-info">{r["staff"].department}</span>' if r["staff"].department else '-'
        rows += f'''<tr>
            <td>{r["date"]}</td><td><strong>{r["staff"].staff_id}</strong></td><td>{r["staff"].firstname} {r["staff"].surname}</td>
            <td>{dept}</td><td>{r["school"].name}</td><td>{r["school"].closing_time}</td>
            <td>{r["sign_out"].strftime("%H:%M:%S")}</td><td><span class="badge badge-success">{h}h {m}m</span></td>
        </tr>'''
    
    content = f'''
    <div class="header">
        <h1><i class="fas fa-hourglass-half"></i> Overtime Report</h1>
        <a href="/overtime/download?school={school_filter}&from_date={from_date}&to_date={to_date}" class="btn btn-success"><i class="fas fa-download"></i> Download CSV</a>
    </div>
    <div class="card">
        <form method="GET" class="filter-form">
            <div class="form-group">
                <label><i class="fas fa-school"></i> School</label>
                <select name="school" class="form-control">{school_opts}</select>
            </div>
            <div class="form-group">
                <label><i class="fas fa-calendar"></i> From</label>
                <input type="date" name="from_date" class="form-control" value="{from_date}">
            </div>
            <div class="form-group">
                <label><i class="fas fa-calendar"></i> To</label>
                <input type="date" name="to_date" class="form-control" value="{to_date}">
            </div>
            <button class="btn btn-primary"><i class="fas fa-filter"></i> Filter</button>
        </form>
    </div>
    <div class="card">
        <h3><i class="fas fa-star" style="color:#28a745;"></i> {len(ot_list)} overtime records found</h3>
        <table>
            <thead><tr><th>Date</th><th>Staff ID</th><th>Name</th><th>Dept</th><th>School</th><th>Closing</th><th>Left At</th><th>Overtime</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="8" style="text-align:center;color:#999;">No overtime records</td></tr>'}</tbody>
        </table>
    </div>
    '''
    return page('Overtime', content, 'overtime')

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
            st = Staff.query.get(a.staff_id)
            sch = School.query.get(a.school_id)
            if sch:
                try:
                    closing = datetime.strptime(sch.closing_time, '%H:%M').time()
                    if a.sign_out.time() > closing:
                        mins = (datetime.combine(date.today(), a.sign_out.time()) - datetime.combine(date.today(), closing)).seconds // 60
                        writer.writerow([a.date, st.staff_id, st.firstname, st.surname, st.department or '', sch.name, sch.closing_time, a.sign_out.strftime('%H:%M:%S'), mins])
                except:
                    pass
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=overtime_{from_date}_to_{to_date}.csv'})

@app.route('/admins')
@login_required
def admins():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    rows = ''
    for u in users:
        role = '<span class="badge badge-success">Super Admin</span>' if u.is_admin else '<span class="badge badge-info">User</span>'
        rows += f'''<tr>
            <td><strong>{u.username}</strong></td><td>{role}</td>
            <td><form method="POST" action="/admins/delete/{u.id}" style="display:inline;" onsubmit="return confirm('Delete?');">
                <button class="btn btn-danger btn-sm"><i class="fas fa-trash"></i></button>
            </form></td>
        </tr>'''
    
    content = f'''
    <div class="header">
        <h1><i class="fas fa-user-shield"></i> Admin Management</h1>
        <a href="/admins/add" class="btn btn-primary"><i class="fas fa-plus"></i> Add Admin</a>
    </div>
    <div class="card">
        <table>
            <thead><tr><th>Username</th><th>Role</th><th>Actions</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    '''
    return page('Admins', content, 'admins')

@app.route('/admins/add', methods=['GET', 'POST'])
@login_required
def add_admin():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        u = User(username=request.form.get('username'), password_hash=generate_password_hash(request.form.get('password')),
                 is_admin=request.form.get('is_admin') == 'on')
        db.session.add(u)
        db.session.commit()
        return redirect(url_for('admins'))
    
    content = '''
    <div class="header"><h1><i class="fas fa-user-plus"></i> Add New Admin</h1></div>
    <div class="card">
        <form method="POST" style="max-width: 500px;">
            <div class="form-group">
                <label><i class="fas fa-user"></i> Username</label>
                <input type="text" name="username" class="form-control" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-lock"></i> Password</label>
                <input type="password" name="password" class="form-control" required>
            </div>
            <div class="form-group">
                <label style="display:flex;align-items:center;gap:10px;cursor:pointer;">
                    <input type="checkbox" name="is_admin" style="width:18px;height:18px;">
                    <span>Super Admin privileges</span>
                </label>
            </div>
            <div style="display:flex;gap:10px;">
                <button class="btn btn-primary"><i class="fas fa-save"></i> Save</button>
                <a href="/admins" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>
            </div>
        </form>
    </div>
    '''
    return page('Add Admin', content, 'admins')

@app.route('/admins/delete/<int:id>', methods=['POST'])
@login_required
def delete_admin(id):
    if not current_user.is_admin or id == current_user.id:
        return redirect(url_for('admins'))
    u = User.query.get_or_404(id)
    db.session.delete(u)
    db.session.commit()
    return redirect(url_for('admins'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    msg = ''
    if request.method == 'POST':
        if check_password_hash(current_user.password_hash, request.form.get('current_password')):
            current_user.password_hash = generate_password_hash(request.form.get('new_password'))
            db.session.commit()
            msg = '<div class="alert alert-success"><i class="fas fa-check-circle"></i> Password changed!</div>'
        else:
            msg = '<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> Current password incorrect</div>'
    
    content = f'''
    <div class="header"><h1><i class="fas fa-cog"></i> Settings</h1></div>
    {msg}
    <div class="card">
        <h3><i class="fas fa-key"></i> Change Password</h3>
        <form method="POST" style="max-width:400px;margin-top:20px;">
            <div class="form-group">
                <label><i class="fas fa-lock"></i> Current Password</label>
                <input type="password" name="current_password" class="form-control" required>
            </div>
            <div class="form-group">
                <label><i class="fas fa-lock"></i> New Password</label>
                <input type="password" name="new_password" class="form-control" required>
            </div>
            <button class="btn btn-primary"><i class="fas fa-save"></i> Change Password</button>
        </form>
    </div>
    '''
    return page('Settings', content, 'settings')

@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    school = School.query.filter_by(api_key=api_key).first()
    if not school:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json() or {}
    if 'attendance' in data:
        for r in data['attendance']:
            st = Staff.query.filter_by(staff_id=r.get('staff_id'), school_id=school.id).first()
            if st:
                att = Attendance.query.filter_by(staff_id=st.id, school_id=school.id, date=r.get('date')).first()
                if not att:
                    att = Attendance(staff_id=st.id, school_id=school.id, date=r.get('date'))
                    db.session.add(att)
                if r.get('sign_in'):
                    att.sign_in = datetime.fromisoformat(r['sign_in'])
                if r.get('sign_out'):
                    att.sign_out = datetime.fromisoformat(r['sign_out'])
        db.session.commit()
    
    staff_list = [{'id': s.staff_id, 'firstname': s.firstname, 'surname': s.surname, 'department': s.department} 
                  for s in Staff.query.filter_by(school_id=school.id, active=True).all()]
    return jsonify({'school': school.name, 'resumption_time': school.resumption_time, 'closing_time': school.closing_time, 'staff': staff_list})

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', password_hash=generate_password_hash('admin123'), is_admin=True))
            db.session.commit()

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
