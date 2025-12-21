from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import os
import csv
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ============================================
# DATABASE MODELS
# ============================================

class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    logo_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', backref='organization', lazy=True, cascade='all, delete-orphan')

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True, cascade='all, delete-orphan')
    attendance_records = db.relationship('Attendance', backref='school', lazy=True, cascade='all, delete-orphan')

user_schools = db.Table('user_schools',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('school_id', db.Integer, db.ForeignKey('school.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='viewer')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', secondary=user_schools, lazy='subquery',
                              backref=db.backref('users', lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(50))
    department = db.Column(db.String(100))
    position = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance_records = db.relationship('Attendance', backref='staff', lazy=True, cascade='all, delete-orphan')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    check_in = db.Column(db.DateTime, nullable=False)
    check_out = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='present')
    notes = db.Column(db.Text)
    device_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ============================================
# DECORATORS
# ============================================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['super_admin', 'school_admin']:
            flash('You do not have permission to access this page.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            flash('You do not have permission to access this page.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_user_schools():
    if current_user.role == 'super_admin':
        return School.query.all()
    return current_user.schools

def get_user_school_ids():
    if current_user.role == 'super_admin':
        return [s.id for s in School.query.all()]
    return [s.id for s in current_user.schools]

# ============================================
# AUTHENTICATION ROUTES
# ============================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password) and user.is_active:
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid username or password.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ============================================
# DASHBOARD
# ============================================

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    school_ids = get_user_school_ids()
    
    total_schools = len(school_ids)
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
    
    today_attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        db.func.date(Attendance.check_in) == today
    ).count()
    
    # Late count (after 9:00 AM)
    late_count = 0
    nine_am = datetime.strptime('09:00', '%H:%M').time()
    records = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        db.func.date(Attendance.check_in) == today
    ).all()
    for record in records:
        if record.check_in.time() > nine_am:
            late_count += 1
    
    today_absent = max(0, total_staff - today_attendance)
    
    # Branch stats
    branch_stats = []
    schools = School.query.filter(School.id.in_(school_ids)).all()
    for school in schools:
        school_staff = Staff.query.filter_by(school_id=school.id, is_active=True).count()
        school_present = Attendance.query.filter(
            Attendance.school_id == school.id,
            db.func.date(Attendance.check_in) == today
        ).count()
        
        school_late = 0
        school_records = Attendance.query.filter(
            Attendance.school_id == school.id,
            db.func.date(Attendance.check_in) == today
        ).all()
        for record in school_records:
            if record.check_in.time() > nine_am:
                school_late += 1
        
        school_absent = max(0, school_staff - school_present)
        attendance_rate = round((school_present / school_staff * 100), 1) if school_staff > 0 else 0
        
        branch_stats.append({
            'id': school.id,
            'name': school.name,
            'total_staff': school_staff,
            'present': school_present,
            'late': school_late,
            'absent': school_absent,
            'attendance_rate': attendance_rate
        })
    
    return render_template('dashboard.html',
                          total_schools=total_schools,
                          total_staff=total_staff,
                          today_present=today_attendance,
                          today_late=late_count,
                          today_absent=today_absent,
                          branch_stats=branch_stats,
                          today_date=today.strftime('%B %d, %Y'))

# ============================================
# API ENDPOINTS
# ============================================

@app.route('/api/dashboard-stats')
@login_required
def api_dashboard_stats():
    today = date.today()
    school_ids = get_user_school_ids()
    nine_am = datetime.strptime('09:00', '%H:%M').time()
    
    total_schools = len(school_ids)
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
    
    today_attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        db.func.date(Attendance.check_in) == today
    ).count()
    
    late_count = 0
    records = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        db.func.date(Attendance.check_in) == today
    ).all()
    for record in records:
        if record.check_in.time() > nine_am:
            late_count += 1
    
    absent_count = max(0, total_staff - today_attendance)
    
    # First check-in
    first_checkin = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        db.func.date(Attendance.check_in) == today
    ).order_by(Attendance.check_in.asc()).first()
    
    first_checkin_data = None
    if first_checkin:
        staff = Staff.query.get(first_checkin.staff_id)
        school = School.query.get(first_checkin.school_id)
        if staff and school:
            first_checkin_data = {
                'name': staff.name,
                'branch': school.name,
                'department': staff.department or 'General',
                'time': first_checkin.check_in.strftime('%H:%M')
            }
    
    # Recent activity
    recent = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        db.func.date(Attendance.check_in) == today
    ).order_by(Attendance.check_in.desc()).limit(20).all()
    
    recent_activity = []
    for record in recent:
        staff = Staff.query.get(record.staff_id)
        school = School.query.get(record.school_id)
        if staff and school:
            recent_activity.append({
                'name': staff.name,
                'time': record.check_in.strftime('%H:%M'),
                'branch': school.name
            })
    
    return jsonify({
        'total_schools': total_schools,
        'total_staff': total_staff,
        'today_attendance': today_attendance,
        'late_today': late_count,
        'absent_today': absent_count,
        'first_checkin': first_checkin_data,
        'recent_activity': recent_activity
    })

@app.route('/api/search-staff')
@login_required
def api_search_staff():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    
    today = date.today()
    school_ids = get_user_school_ids()
    nine_am = datetime.strptime('09:00', '%H:%M').time()
    
    staff_results = Staff.query.filter(
        Staff.school_id.in_(school_ids),
        Staff.is_active == True,
        db.or_(
            Staff.name.ilike(f'%{query}%'),
            Staff.staff_id.ilike(f'%{query}%')
        )
    ).limit(10).all()
    
    results = []
    colors_list = ['#667eea', '#11998e', '#e74c3c', '#9b59b6', '#3498db', '#1abc9c', '#e67e22', '#2c3e50']
    
    for staff in staff_results:
        school = School.query.get(staff.school_id)
        attendance = Attendance.query.filter(
            Attendance.staff_id == staff.id,
            db.func.date(Attendance.check_in) == today
        ).first()
        
        if attendance:
            if attendance.check_in.time() > nine_am:
                status, status_text = 'late', 'Late'
            else:
                status, status_text = 'signed-in', 'Signed In'
        else:
            status, status_text = 'absent', 'Absent'
        
        name_parts = staff.name.split()
        initials = ''.join([p[0].upper() for p in name_parts[:2]])
        color = colors_list[sum(ord(c) for c in staff.name) % len(colors_list)]
        
        results.append({
            'id': staff.id,
            'name': staff.name,
            'staff_id': staff.staff_id,
            'branch': school.name if school else 'Unknown',
            'department': staff.department or 'General',
            'initials': initials,
            'color': color,
            'status': status,
            'status_text': status_text
        })
    
    return jsonify(results)

@app.route('/api/sync', methods=['POST'])
def api_sync():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({'error': 'API key required'}), 401
    
    setting = SystemSettings.query.filter_by(setting_key='api_key').first()
    if not setting or setting.setting_value != api_key:
        return jsonify({'error': 'Invalid API key'}), 401
    
    try:
        staff_id = data.get('staff_id')
        device_id = data.get('device_id')
        timestamp = data.get('timestamp')
        action = data.get('action', 'check_in')
        
        staff = Staff.query.filter_by(staff_id=staff_id).first()
        if not staff:
            return jsonify({'error': 'Staff not found'}), 404
        
        check_time = datetime.fromisoformat(timestamp) if timestamp else datetime.now()
        
        if action == 'check_in':
            today = date.today()
            existing = Attendance.query.filter(
                Attendance.staff_id == staff.id,
                db.func.date(Attendance.check_in) == today
            ).first()
            
            if existing:
                return jsonify({'message': 'Already checked in today', 'record_id': existing.id})
            
            nine_am = datetime.strptime('09:00', '%H:%M').time()
            status = 'late' if check_time.time() > nine_am else 'present'
            
            attendance = Attendance(
                staff_id=staff.id,
                school_id=staff.school_id,
                check_in=check_time,
                status=status,
                device_id=device_id
            )
            db.session.add(attendance)
            db.session.commit()
            
            return jsonify({'message': 'Check-in recorded', 'record_id': attendance.id, 'status': status})
        
        elif action == 'check_out':
            today = date.today()
            attendance = Attendance.query.filter(
                Attendance.staff_id == staff.id,
                db.func.date(Attendance.check_in) == today
            ).first()
            
            if not attendance:
                return jsonify({'error': 'No check-in record found for today'}), 404
            
            attendance.check_out = check_time
            db.session.commit()
            return jsonify({'message': 'Check-out recorded', 'record_id': attendance.id})
        
        return jsonify({'error': 'Invalid action'}), 400
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ============================================
# ORGANIZATION MANAGEMENT
# ============================================

@app.route('/organizations')
@login_required
@super_admin_required
def organizations():
    return render_template('organizations.html', organizations=Organization.query.all())

@app.route('/organization/add', methods=['GET', 'POST'])
@login_required
@super_admin_required
def add_organization():
    if request.method == 'POST':
        org = Organization(
            name=request.form.get('name'),
            address=request.form.get('address'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            logo_url=request.form.get('logo_url')
        )
        db.session.add(org)
        db.session.commit()
        flash('Organization added successfully!', 'success')
        return redirect(url_for('organizations'))
    return render_template('organization_form.html', organization=None)

@app.route('/organization/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.address = request.form.get('address')
        org.phone = request.form.get('phone')
        org.email = request.form.get('email')
        org.logo_url = request.form.get('logo_url')
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('organizations'))
    return render_template('organization_form.html', organization=org)

@app.route('/organization/delete/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('organizations'))

# ============================================
# BRANCH MANAGEMENT
# ============================================

@app.route('/branches')
@login_required
@admin_required
def branches():
    schools = School.query.all() if current_user.role == 'super_admin' else current_user.schools
    return render_template('branches.html', branches=schools, organizations=Organization.query.all())

@app.route('/branch/add', methods=['GET', 'POST'])
@login_required
@super_admin_required
def add_branch():
    if request.method == 'POST':
        school = School(
            name=request.form.get('name'),
            address=request.form.get('address'),
            organization_id=request.form.get('organization_id')
        )
        db.session.add(school)
        db.session.commit()
        flash('Branch added successfully!', 'success')
        return redirect(url_for('branches'))
    return render_template('branch_form.html', branch=None, organizations=Organization.query.all())

@app.route('/branch/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_branch(id):
    school = School.query.get_or_404(id)
    
    if current_user.role != 'super_admin' and school not in current_user.schools:
        flash('Permission denied.', 'error')
        return redirect(url_for('branches'))
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.address = request.form.get('address')
        if current_user.role == 'super_admin':
            school.organization_id = request.form.get('organization_id')
        db.session.commit()
        flash('Branch updated successfully!', 'success')
        return redirect(url_for('branches'))
    return render_template('branch_form.html', branch=school, organizations=Organization.query.all())

@app.route('/branch/delete/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def delete_branch(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('Branch deleted successfully!', 'success')
    return redirect(url_for('branches'))

# ============================================
# STAFF MANAGEMENT
# ============================================

@app.route('/staff')
@login_required
def staff_list():
    school_ids = get_user_school_ids()
    staff = Staff.query.filter(Staff.school_id.in_(school_ids)).all()
    return render_template('staff.html', staff=staff, schools=get_user_schools())

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_staff():
    if request.method == 'POST':
        staff = Staff(
            staff_id=request.form.get('staff_id'),
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            department=request.form.get('department'),
            position=request.form.get('position'),
            school_id=request.form.get('school_id')
        )
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff_list'))
    return render_template('staff_form.html', staff=None, schools=get_user_schools())

@app.route('/staff/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_staff(id):
    staff = Staff.query.get_or_404(id)
    
    if staff.school_id not in get_user_school_ids():
        flash('Permission denied.', 'error')
        return redirect(url_for('staff_list'))
    
    if request.method == 'POST':
        staff.staff_id = request.form.get('staff_id')
        staff.name = request.form.get('name')
        staff.email = request.form.get('email')
        staff.phone = request.form.get('phone')
        staff.department = request.form.get('department')
        staff.position = request.form.get('position')
        staff.school_id = request.form.get('school_id')
        staff.is_active = request.form.get('is_active') == 'on'
        db.session.commit()
        flash('Staff updated successfully!', 'success')
        return redirect(url_for('staff_list'))
    return render_template('staff_form.html', staff=staff, schools=get_user_schools())

@app.route('/staff/delete/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    if staff.school_id not in get_user_school_ids():
        flash('Permission denied.', 'error')
        return redirect(url_for('staff_list'))
    
    db.session.delete(staff)
    db.session.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/bulk-upload', methods=['GET', 'POST'])
@login_required
@admin_required
def bulk_upload_staff():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected.', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        school_id = request.form.get('school_id')
        
        if file.filename == '' or not file.filename.endswith('.csv'):
            flash('Please upload a CSV file.', 'error')
            return redirect(request.url)
        
        try:
            stream = io.StringIO(file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)
            count = 0
            
            for row in reader:
                if Staff.query.filter_by(staff_id=row.get('staff_id', '').strip()).first():
                    continue
                
                staff = Staff(
                    staff_id=row.get('staff_id', '').strip(),
                    name=row.get('name', '').strip(),
                    email=row.get('email', '').strip(),
                    phone=row.get('phone', '').strip(),
                    department=row.get('department', '').strip(),
                    position=row.get('position', '').strip(),
                    school_id=school_id
                )
                db.session.add(staff)
                count += 1
            
            db.session.commit()
            flash(f'{count} staff members uploaded!', 'success')
            return redirect(url_for('staff_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('staff_bulk_upload.html', schools=get_user_schools())

# ============================================
# USER MANAGEMENT
# ============================================

@app.route('/users')
@login_required
@super_admin_required
def users():
    return render_template('users.html', users=User.query.all())

@app.route('/user/add', methods=['GET', 'POST'])
@login_required
@super_admin_required
def add_user():
    if request.method == 'POST':
        user = User(
            username=request.form.get('username'),
            email=request.form.get('email'),
            role=request.form.get('role')
        )
        user.set_password(request.form.get('password'))
        
        for school_id in request.form.getlist('schools'):
            school = School.query.get(school_id)
            if school:
                user.schools.append(school)
        
        db.session.add(user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    return render_template('user_form.html', user=None, schools=School.query.all())

@app.route('/user/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.email = request.form.get('email')
        user.role = request.form.get('role')
        user.is_active = request.form.get('is_active') == 'on'
        
        if request.form.get('password'):
            user.set_password(request.form.get('password'))
        
        user.schools = []
        for school_id in request.form.getlist('schools'):
            school = School.query.get(school_id)
            if school:
                user.schools.append(school)
        
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    return render_template('user_form.html', user=user, schools=School.query.all())

@app.route('/user/delete/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('Cannot delete yourself.', 'error')
        return redirect(url_for('users'))
    
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('users'))

# ============================================
# REPORTS
# ============================================

@app.route('/reports/attendance')
@login_required
def attendance_report():
    school_ids = get_user_school_ids()
    schools = get_user_schools()
    
    start_date = request.args.get('start_date', date.today().strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', date.today().strftime('%Y-%m-%d'))
    school_id = request.args.get('school_id', '')
    
    query = Attendance.query.filter(Attendance.school_id.in_(school_ids))
    
    if start_date:
        query = query.filter(db.func.date(Attendance.check_in) >= start_date)
    if end_date:
        query = query.filter(db.func.date(Attendance.check_in) <= end_date)
    if school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = query.order_by(Attendance.check_in.desc()).all()
    
    return render_template('reports/attendance.html',
                          records=records, schools=schools,
                          start_date=start_date, end_date=end_date,
                          selected_school=school_id)

@app.route('/reports/late')
@login_required
def late_report():
    schools = get_user_schools()
    start_date = request.args.get('start_date', date.today().strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', date.today().strftime('%Y-%m-%d'))
    school_id = request.args.get('school_id', '')
    nine_am = datetime.strptime('09:00', '%H:%M').time()
    
    late_records = []
    target_schools = [School.query.get(school_id)] if school_id else schools
    
    for school in target_schools:
        if not school:
            continue
        
        records = Attendance.query.filter(
            Attendance.school_id == school.id,
            db.func.date(Attendance.check_in) >= start_date,
            db.func.date(Attendance.check_in) <= end_date
        ).all()
        
        for record in records:
            if record.check_in.time() > nine_am:
                late_records.append({
                    'record': record,
                    'expected_time': nine_am,
                    'late_by': datetime.combine(date.today(), record.check_in.time()) - 
                              datetime.combine(date.today(), nine_am)
                })
    
    return render_template('reports/late.html',
                          late_records=late_records, schools=schools,
                          start_date=start_date, end_date=end_date,
                          selected_school=school_id)

@app.route('/reports/absent')
@login_required
def absent_report():
    schools = get_user_schools()
    report_date = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    school_id = request.args.get('school_id', '')
    
    absent_staff = []
    target_schools = [School.query.get(school_id)] if school_id else schools
    
    for school in target_schools:
        if not school:
            continue
        staff_list = Staff.query.filter_by(school_id=school.id, is_active=True).all()
        
        checked_in_ids = [a.staff_id for a in Attendance.query.filter(
            Attendance.school_id == school.id,
            db.func.date(Attendance.check_in) == report_date
        ).all()]
        
        for staff in staff_list:
            if staff.id not in checked_in_ids:
                absent_staff.append({'staff': staff, 'school': school})
    
    return render_template('reports/absent.html',
                          absent_staff=absent_staff, schools=schools,
                          report_date=report_date, selected_school=school_id)

@app.route('/reports/overtime')
@login_required
def overtime_report():
    schools = get_user_schools()
    start_date = request.args.get('start_date', date.today().strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', date.today().strftime('%Y-%m-%d'))
    school_id = request.args.get('school_id', '')
    five_pm = datetime.strptime('17:00', '%H:%M').time()
    
    overtime_records = []
    target_schools = [School.query.get(school_id)] if school_id else schools
    
    for school in target_schools:
        if not school:
            continue
        
        records = Attendance.query.filter(
            Attendance.school_id == school.id,
            Attendance.check_out.isnot(None),
            db.func.date(Attendance.check_in) >= start_date,
            db.func.date(Attendance.check_in) <= end_date
        ).all()
        
        for record in records:
            if record.check_out and record.check_out.time() > five_pm:
                overtime_records.append({
                    'record': record,
                    'expected_end': five_pm,
                    'overtime': datetime.combine(date.today(), record.check_out.time()) - 
                               datetime.combine(date.today(), five_pm)
                })
    
    return render_template('reports/overtime.html',
                          overtime_records=overtime_records, schools=schools,
                          start_date=start_date, end_date=end_date,
                          selected_school=school_id)

# ============================================
# ANALYTICS
# ============================================

@app.route('/analytics')
@login_required
def analytics():
    school_ids = get_user_school_ids()
    schools = get_user_schools()
    organizations = Organization.query.all() if current_user.role == 'super_admin' else []
    nine_am = datetime.strptime('09:00', '%H:%M').time()
    five_pm = datetime.strptime('17:00', '%H:%M').time()
    
    period = request.args.get('period', 'today')
    org_id = request.args.get('organization', '')
    school_id = request.args.get('branch', '')
    department = request.args.get('department', '')
    
    today = date.today()
    
    # Date range
    if period == 'today':
        start_date, end_date = today, today
    elif period == 'yesterday':
        start_date = end_date = today - timedelta(days=1)
    elif period == 'this_week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif period == 'last_week':
        start_date = today - timedelta(days=today.weekday() + 7)
        end_date = today - timedelta(days=today.weekday() + 1)
    elif period == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'last_month':
        last_month = today.replace(day=1) - timedelta(days=1)
        start_date = last_month.replace(day=1)
        end_date = last_month
    elif period == 'custom':
        start_date = datetime.strptime(request.args.get('start_date', str(today)), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.args.get('end_date', str(today)), '%Y-%m-%d').date()
    else:
        start_date, end_date = today, today
    
    # Filter schools
    filtered_school_ids = school_ids
    if org_id:
        filtered_school_ids = [s.id for s in School.query.filter_by(organization_id=org_id).all() if s.id in school_ids]
    if school_id:
        filtered_school_ids = [int(school_id)] if int(school_id) in filtered_school_ids else []
    
    # Departments
    departments = [d[0] for d in db.session.query(Staff.department).filter(
        Staff.school_id.in_(school_ids), Staff.department.isnot(None)
    ).distinct().all() if d[0]]
    
    # Staff count
    total_staff_query = Staff.query.filter(Staff.school_id.in_(filtered_school_ids), Staff.is_active == True)
    if department:
        total_staff_query = total_staff_query.filter(Staff.department == department)
    total_staff_count = total_staff_query.count()
    
    # Attendance
    attendance_query = Attendance.query.filter(
        Attendance.school_id.in_(filtered_school_ids),
        db.func.date(Attendance.check_in) >= start_date,
        db.func.date(Attendance.check_in) <= end_date
    )
    if department:
        staff_ids = [s.id for s in Staff.query.filter(Staff.department == department).all()]
        attendance_query = attendance_query.filter(Attendance.staff_id.in_(staff_ids))
    
    attendance_records = attendance_query.all()
    total_records = len(attendance_records)
    
    # Metrics
    working_days = max(1, (end_date - start_date).days + 1)
    expected_attendance = total_staff_count * working_days
    attendance_rate = round((total_records / expected_attendance * 100), 1) if expected_attendance > 0 else 0
    
    late_count = on_time_count = total_late_minutes = 0
    for record in attendance_records:
        if record.check_in.time() > nine_am:
            late_count += 1
            total_late_minutes += (datetime.combine(date.today(), record.check_in.time()) - 
                                  datetime.combine(date.today(), nine_am)).seconds // 60
        else:
            on_time_count += 1
    
    punctuality_rate = round((on_time_count / total_records * 100), 1) if total_records > 0 else 0
    avg_late_minutes = round(total_late_minutes / late_count) if late_count > 0 else 0
    
    # Overtime
    total_overtime_minutes = 0
    for record in attendance_records:
        if record.check_out and record.check_out.time() > five_pm:
            total_overtime_minutes += (datetime.combine(date.today(), record.check_out.time()) - 
                                      datetime.combine(date.today(), five_pm)).seconds // 60
    
    # Daily chart
    daily_attendance = []
    current = max(start_date, today - timedelta(days=6))
    while current <= end_date:
        count = Attendance.query.filter(
            Attendance.school_id.in_(filtered_school_ids),
            db.func.date(Attendance.check_in) == current
        ).count()
        daily_attendance.append({'date': current.strftime('%b %d'), 'count': count})
        current += timedelta(days=1)
    
    # Department stats
    dept_stats = []
    for dept in departments:
        dept_staff = Staff.query.filter(
            Staff.school_id.in_(filtered_school_ids),
            Staff.department == dept, Staff.is_active == True
        ).all()
        dept_attendance = Attendance.query.filter(
            Attendance.staff_id.in_([s.id for s in dept_staff]),
            db.func.date(Attendance.check_in) >= start_date,
            db.func.date(Attendance.check_in) <= end_date
        ).count()
        expected = len(dept_staff) * working_days
        dept_stats.append({
            'name': dept,
            'staff_count': len(dept_staff),
            'attendance': dept_attendance,
            'rate': round((dept_attendance / expected * 100), 1) if expected > 0 else 0
        })
    
    return render_template('analytics.html',
                          schools=schools, organizations=organizations, departments=departments,
                          period=period, start_date=start_date.strftime('%Y-%m-%d'),
                          end_date=end_date.strftime('%Y-%m-%d'),
                          selected_org=org_id, selected_branch=school_id, selected_department=department,
                          total_staff=total_staff_count, total_records=total_records,
                          attendance_rate=attendance_rate, punctuality_rate=punctuality_rate,
                          on_time_count=on_time_count, late_count=late_count,
                          avg_late_minutes=avg_late_minutes,
                          total_overtime_hours=round(total_overtime_minutes / 60, 1),
                          daily_attendance=daily_attendance, dept_stats=dept_stats)

@app.route('/analytics/download-pdf')
@login_required
def download_analytics_pdf():
    school_ids = get_user_school_ids()
    today = date.today()
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
    today_attendance = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        db.func.date(Attendance.check_in) == today
    ).count()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    
    elements = [
        Paragraph("Attendance Report", ParagraphStyle('Title', parent=styles['Heading1'], alignment=TA_CENTER)),
        Spacer(1, 20),
        Paragraph(f"Date: {today.strftime('%B %d, %Y')}", styles['Normal']),
        Spacer(1, 20)
    ]
    
    data = [['Metric', 'Value'], ['Total Staff', str(total_staff)], ['Present Today', str(today_attendance)]]
    table = Table(data, colWidths=[3*inch, 2*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey)
    ]))
    elements.append(table)
    
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, 
                    download_name=f"report_{today.strftime('%Y%m%d')}.pdf",
                    mimetype='application/pdf')

# ============================================
# SETTINGS & PROFILE
# ============================================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@super_admin_required
def settings():
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        if api_key:
            setting = SystemSettings.query.filter_by(setting_key='api_key').first()
            if setting:
                setting.setting_value = api_key
            else:
                db.session.add(SystemSettings(setting_key='api_key', setting_value=api_key))
            db.session.commit()
            flash('Settings updated!', 'success')
    
    api_key = SystemSettings.query.filter_by(setting_key='api_key').first()
    return render_template('settings.html', api_key=api_key.setting_value if api_key else '')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.email = request.form.get('email')
        
        if request.form.get('current_password') and request.form.get('new_password'):
            if current_user.check_password(request.form.get('current_password')):
                current_user.set_password(request.form.get('new_password'))
                flash('Password updated!', 'success')
            else:
                flash('Current password incorrect.', 'error')
                return redirect(url_for('profile'))
        
        db.session.commit()
        flash('Profile updated!', 'success')
    
    return render_template('profile.html')

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

# ============================================
# DATABASE INIT
# ============================================

def init_db():
    with app.app_context():
        db.create_all()
        
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', email='admin@example.com', role='super_admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
