import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import csv
import io
import secrets
import json
from xhtml2pdf import pisa

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', backref='organization', lazy=True, cascade='all, delete-orphan')

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    expected_start_time = db.Column(db.String(10), default='09:00')
    expected_end_time = db.Column(db.String(10), default='17:00')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True, cascade='all, delete-orphan')

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff')
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=True)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    organization = db.relationship('Organization', backref='users')
    school = db.relationship('School', backref='users')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    department = db.Column(db.String(100))
    position = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendances = db.relationship('Attendance', backref='staff', lazy=True, cascade='all, delete-orphan')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time_in = db.Column(db.DateTime)
    time_out = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='present')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Role-based access decorators
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def init_db():
    with app.app_context():
        db.create_all()
        # Run migrations for missing columns
        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE school ADD COLUMN IF NOT EXISTS expected_start_time VARCHAR(10) DEFAULT '09:00'"))
            db.session.execute(text("ALTER TABLE school ADD COLUMN IF NOT EXISTS expected_end_time VARCHAR(10) DEFAULT '17:00'"))
            db.session.commit()
        except:
            db.session.rollback()
        
        # Create admin if not exists
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@example.com',
                role='super_admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()

# Auth routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Dashboard
@app.route('/')
@login_required
def dashboard():
    today = date.today()
    
    if current_user.role == 'super_admin':
        total_staff = Staff.query.filter_by(active=True).count()
        total_present = Attendance.query.filter_by(date=today).distinct(Attendance.staff_id).count()
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        org_schools = School.query.filter_by(organization_id=current_user.organization_id).all()
        school_ids = [s.id for s in org_schools]
        total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.active==True).count()
        total_present = Attendance.query.join(Staff).filter(
            Staff.school_id.in_(school_ids),
            Attendance.date==today
        ).distinct(Attendance.staff_id).count()
        branches = org_schools
    else:
        total_staff = Staff.query.filter_by(school_id=current_user.school_id, active=True).count()
        total_present = Attendance.query.join(Staff).filter(
            Staff.school_id==current_user.school_id,
            Attendance.date==today
        ).distinct(Attendance.staff_id).count()
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    total_absent = total_staff - total_present
    
    # Get recent activity
    recent_attendance = Attendance.query.filter_by(date=today).order_by(Attendance.created_at.desc()).limit(10).all()
    
    # Branch stats
    branch_stats = []
    for branch in branches:
        staff_count = Staff.query.filter_by(school_id=branch.id, active=True).count()
        present_count = Attendance.query.join(Staff).filter(
            Staff.school_id==branch.id,
            Attendance.date==today
        ).distinct(Attendance.staff_id).count()
        branch_stats.append({
            'id': branch.id,
            'name': branch.name,
            'total': staff_count,
            'present': present_count,
            'absent': staff_count - present_count
        })
    
    return render_template('dashboard.html',
        total_staff=total_staff,
        total_present=total_present,
        total_absent=total_absent,
        recent_attendance=recent_attendance,
        branch_stats=branch_stats
    )

# API Endpoints
@app.route('/api/dashboard-stats')
@login_required
def dashboard_stats():
    today = date.today()
    
    if current_user.role == 'super_admin':
        total_staff = Staff.query.filter_by(active=True).count()
        branches = School.query.all()
        school_ids = [s.id for s in branches]
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
        school_ids = [s.id for s in branches]
        total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.active==True).count()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
        school_ids = [current_user.school_id]
        total_staff = Staff.query.filter_by(school_id=current_user.school_id, active=True).count()
    
    total_present = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date==today
    ).distinct(Attendance.staff_id).count()
    
    total_absent = total_staff - total_present
    
    # Calculate late count
    late_count = 0
    for branch in branches:
        expected_start = branch.expected_start_time or '09:00'
        try:
            start_hour, start_min = map(int, expected_start.split(':'))
        except:
            start_hour, start_min = 9, 0
        
        attendances = Attendance.query.join(Staff).filter(
            Staff.school_id==branch.id,
            Attendance.date==today,
            Attendance.time_in.isnot(None)
        ).all()
        
        for att in attendances:
            if att.time_in.hour > start_hour or (att.time_in.hour == start_hour and att.time_in.minute > start_min):
                late_count += 1
    
    # Calculate on-time
    on_time = total_present - late_count
    
    # Branch stats
    branch_stats = []
    for branch in branches:
        staff_count = Staff.query.filter_by(school_id=branch.id, active=True).count()
        present_count = Attendance.query.join(Staff).filter(
            Staff.school_id==branch.id,
            Attendance.date==today
        ).distinct(Attendance.staff_id).count()
        branch_stats.append({
            'id': branch.id,
            'name': branch.name,
            'total': staff_count,
            'present': present_count,
            'absent': staff_count - present_count
        })
    
    # Recent activity
    recent = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date==today
    ).order_by(Attendance.created_at.desc()).limit(10).all()
    
    activity = []
    for att in recent:
        activity.append({
            'name': f"{att.staff.first_name} {att.staff.last_name}",
            'branch': att.staff.school.name,
            'time': att.time_in.strftime('%H:%M') if att.time_in else '-',
            'type': 'check-in' if att.time_in and not att.time_out else 'check-out'
        })
    
    # First check-in
    first_checkin = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date==today,
        Attendance.time_in.isnot(None)
    ).order_by(Attendance.time_in.asc()).first()
    
    first_checkin_data = None
    if first_checkin:
        first_checkin_data = {
            'name': f"{first_checkin.staff.first_name} {first_checkin.staff.last_name}",
            'time': first_checkin.time_in.strftime('%H:%M'),
            'branch': first_checkin.staff.school.name
        }
    
    return jsonify({
        'total_staff': total_staff,
        'total_present': total_present,
        'total_absent': total_absent,
        'late_count': late_count,
        'on_time': on_time,
        'branch_stats': branch_stats,
        'activity': activity,
        'first_checkin': first_checkin_data
    })

@app.route('/api/search-staff')
@login_required
def search_staff():
    query = request.args.get('q', '').strip().lower()
    if len(query) < 2:
        return jsonify([])
    
    if current_user.role == 'super_admin':
        staff_query = Staff.query.filter(Staff.active==True)
    elif current_user.role == 'org_admin':
        org_schools = School.query.filter_by(organization_id=current_user.organization_id).all()
        school_ids = [s.id for s in org_schools]
        staff_query = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.active==True)
    else:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, active=True)
    
    staff_list = staff_query.filter(
        db.or_(
            Staff.first_name.ilike(f'%{query}%'),
            Staff.last_name.ilike(f'%{query}%'),
            Staff.staff_id.ilike(f'%{query}%')
        )
    ).limit(10).all()
    
    today = date.today()
    results = []
    for s in staff_list:
        att = Attendance.query.filter_by(staff_id=s.id, date=today).first()
        status = 'Absent'
        time_in = '-'
        if att and att.time_in:
            status = 'Present'
            time_in = att.time_in.strftime('%H:%M')
        
        results.append({
            'id': s.id,
            'name': f"{s.first_name} {s.last_name}",
            'staff_id': s.staff_id,
            'branch': s.school.name,
            'department': s.department or '-',
            'status': status,
            'time_in': time_in
        })
    
    return jsonify(results)

@app.route('/api/branch-staff/<int:branch_id>')
@login_required
def get_branch_staff(branch_id):
    """Get staff list for a branch with today's attendance - SIMPLE VERSION"""
    today = date.today()
    
    staff_list = Staff.query.filter_by(school_id=branch_id, active=True).all()
    
    result = []
    for staff in staff_list:
        attendance = Attendance.query.filter_by(
            staff_id=staff.id,
            date=today
        ).first()
        
        if attendance:
            status = 'Present'
            time_in = attendance.time_in.strftime('%H:%M') if attendance.time_in else '-'
            time_out = attendance.time_out.strftime('%H:%M') if attendance.time_out else '-'
        else:
            status = 'Absent'
            time_in = '-'
            time_out = '-'
        
        result.append({
            'name': f"{staff.first_name} {staff.last_name}",
            'status': status,
            'time_in': time_in,
            'time_out': time_out
        })
    
    return jsonify(result)

@app.route('/api/sync', methods=['POST'])
def sync_attendance():
    """API endpoint for external devices to sync attendance data"""
    api_key = request.headers.get('X-API-Key')
    
    stored_key = SystemSettings.query.filter_by(setting_key='api_key').first()
    if not stored_key or stored_key.setting_value != api_key:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    results = {'success': 0, 'failed': 0, 'errors': []}
    
    records = data if isinstance(data, list) else [data]
    
    for record in records:
        try:
            staff_id_str = record.get('staff_id')
            record_date = record.get('date', date.today().isoformat())
            time_in = record.get('time_in')
            time_out = record.get('time_out')
            
            staff = Staff.query.filter_by(staff_id=staff_id_str).first()
            if not staff:
                results['failed'] += 1
                results['errors'].append(f"Staff {staff_id_str} not found")
                continue
            
            att_date = datetime.strptime(record_date, '%Y-%m-%d').date()
            
            attendance = Attendance.query.filter_by(staff_id=staff.id, date=att_date).first()
            
            if not attendance:
                attendance = Attendance(staff_id=staff.id, date=att_date)
                db.session.add(attendance)
            
            if time_in:
                attendance.time_in = datetime.strptime(f"{record_date} {time_in}", '%Y-%m-%d %H:%M')
            if time_out:
                attendance.time_out = datetime.strptime(f"{record_date} {time_out}", '%Y-%m-%d %H:%M')
            
            attendance.status = 'present'
            db.session.commit()
            results['success'] += 1
            
        except Exception as e:
            results['failed'] += 1
            results['errors'].append(str(e))
            db.session.rollback()
    
    return jsonify(results)

# Organization Management
@app.route('/organizations')
@login_required
@role_required('super_admin')
def organizations():
    orgs = Organization.query.all()
    return render_template('organizations.html', organizations=orgs)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_organization():
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        
        org = Organization(name=name, address=address)
        db.session.add(org)
        db.session.commit()
        flash('Organization added successfully', 'success')
        return redirect(url_for('organizations'))
    
    return render_template('organization_form.html')

@app.route('/organizations/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.address = request.form.get('address')
        db.session.commit()
        flash('Organization updated successfully', 'success')
        return redirect(url_for('organizations'))
    
    return render_template('organization_form.html', organization=org)

@app.route('/organizations/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin')
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully', 'success')
    return redirect(url_for('organizations'))

# Branch Management
@app.route('/branches')
@login_required
@role_required('super_admin', 'org_admin')
def branches():
    if current_user.role == 'super_admin':
        branch_list = School.query.all()
    else:
        branch_list = School.query.filter_by(organization_id=current_user.organization_id).all()
    return render_template('branches.html', branches=branch_list)

@app.route('/branches/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin')
def add_branch():
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        expected_start_time = request.form.get('expected_start_time', '09:00')
        expected_end_time = request.form.get('expected_end_time', '17:00')
        
        if current_user.role == 'super_admin':
            org_id = request.form.get('organization_id')
        else:
            org_id = current_user.organization_id
        
        branch = School(
            name=name,
            address=address,
            organization_id=org_id,
            expected_start_time=expected_start_time,
            expected_end_time=expected_end_time
        )
        db.session.add(branch)
        db.session.commit()
        flash('Branch added successfully', 'success')
        return redirect(url_for('branches'))
    
    if current_user.role == 'super_admin':
        orgs = Organization.query.all()
    else:
        orgs = Organization.query.filter_by(id=current_user.organization_id).all()
    
    return render_template('branch_form.html', organizations=orgs)

@app.route('/branches/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin')
def edit_branch(id):
    branch = School.query.get_or_404(id)
    
    if current_user.role == 'org_admin' and branch.organization_id != current_user.organization_id:
        flash('Access denied', 'error')
        return redirect(url_for('branches'))
    
    if request.method == 'POST':
        branch.name = request.form.get('name')
        branch.address = request.form.get('address')
        branch.expected_start_time = request.form.get('expected_start_time', '09:00')
        branch.expected_end_time = request.form.get('expected_end_time', '17:00')
        
        if current_user.role == 'super_admin':
            branch.organization_id = request.form.get('organization_id')
        
        db.session.commit()
        flash('Branch updated successfully', 'success')
        return redirect(url_for('branches'))
    
    if current_user.role == 'super_admin':
        orgs = Organization.query.all()
    else:
        orgs = Organization.query.filter_by(id=current_user.organization_id).all()
    
    return render_template('branch_form.html', branch=branch, organizations=orgs)

@app.route('/branches/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin')
def delete_branch(id):
    branch = School.query.get_or_404(id)
    
    if current_user.role == 'org_admin' and branch.organization_id != current_user.organization_id:
        flash('Access denied', 'error')
        return redirect(url_for('branches'))
    
    db.session.delete(branch)
    db.session.commit()
    flash('Branch deleted successfully', 'success')
    return redirect(url_for('branches'))

# Staff Management
@app.route('/staff')
@login_required
def staff_list():
    if current_user.role == 'super_admin':
        staff = Staff.query.all()
    elif current_user.role == 'org_admin':
        org_schools = School.query.filter_by(organization_id=current_user.organization_id).all()
        school_ids = [s.id for s in org_schools]
        staff = Staff.query.filter(Staff.school_id.in_(school_ids)).all()
    else:
        staff = Staff.query.filter_by(school_id=current_user.school_id).all()
    
    return render_template('staff.html', staff=staff)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin', 'school_admin')
def add_staff():
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        department = request.form.get('department')
        position = request.form.get('position')
        
        if current_user.role in ['super_admin', 'org_admin']:
            school_id = request.form.get('school_id')
        else:
            school_id = current_user.school_id
        
        if Staff.query.filter_by(staff_id=staff_id).first():
            flash('Staff ID already exists', 'error')
            return redirect(url_for('add_staff'))
        
        staff = Staff(
            staff_id=staff_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            department=department,
            position=position,
            school_id=school_id
        )
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully', 'success')
        return redirect(url_for('staff_list'))
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    return render_template('staff_form.html', branches=branches)

@app.route('/staff/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin', 'school_admin')
def edit_staff(id):
    staff = Staff.query.get_or_404(id)
    
    if request.method == 'POST':
        staff.first_name = request.form.get('first_name')
        staff.last_name = request.form.get('last_name')
        staff.email = request.form.get('email')
        staff.phone = request.form.get('phone')
        staff.department = request.form.get('department')
        staff.position = request.form.get('position')
        staff.active = request.form.get('active') == 'on'
        
        if current_user.role in ['super_admin', 'org_admin']:
            staff.school_id = request.form.get('school_id')
        
        db.session.commit()
        flash('Staff updated successfully', 'success')
        return redirect(url_for('staff_list'))
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    return render_template('staff_form.html', staff=staff, branches=branches)

@app.route('/staff/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin', 'school_admin')
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    db.session.delete(staff)
    db.session.commit()
    flash('Staff deleted successfully', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/upload', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin', 'school_admin')
def upload_staff():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'error')
            return redirect(url_for('upload_staff'))
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('upload_staff'))
        
        if current_user.role in ['super_admin', 'org_admin']:
            school_id = request.form.get('school_id')
        else:
            school_id = current_user.school_id
        
        try:
            stream = io.StringIO(file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)
            
            count = 0
            for row in reader:
                if not Staff.query.filter_by(staff_id=row.get('staff_id')).first():
                    staff = Staff(
                        staff_id=row.get('staff_id'),
                        first_name=row.get('first_name'),
                        last_name=row.get('last_name'),
                        email=row.get('email'),
                        phone=row.get('phone'),
                        department=row.get('department'),
                        position=row.get('position'),
                        school_id=school_id
                    )
                    db.session.add(staff)
                    count += 1
            
            db.session.commit()
            flash(f'{count} staff members uploaded successfully', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error uploading file: {str(e)}', 'error')
        
        return redirect(url_for('staff_list'))
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    return render_template('upload_staff.html', branches=branches)

# User Management
@app.route('/users')
@login_required
@role_required('super_admin', 'org_admin')
def users():
    if current_user.role == 'super_admin':
        user_list = User.query.all()
    else:
        user_list = User.query.filter_by(organization_id=current_user.organization_id).all()
    
    return render_template('users.html', users=user_list)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin')
def add_user():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('add_user'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return redirect(url_for('add_user'))
        
        user = User(username=username, email=email, role=role)
        user.set_password(password)
        
        if role == 'org_admin':
            user.organization_id = request.form.get('organization_id')
        elif role == 'school_admin':
            user.school_id = request.form.get('school_id')
            school = School.query.get(user.school_id)
            if school:
                user.organization_id = school.organization_id
        
        db.session.add(user)
        db.session.commit()
        flash('User added successfully', 'success')
        return redirect(url_for('users'))
    
    organizations = Organization.query.all() if current_user.role == 'super_admin' else []
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    else:
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    
    return render_template('user_form.html', organizations=organizations, branches=branches)

@app.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin')
def edit_user(id):
    user = User.query.get_or_404(id)
    
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.email = request.form.get('email')
        user.role = request.form.get('role')
        
        if request.form.get('password'):
            user.set_password(request.form.get('password'))
        
        if user.role == 'org_admin':
            user.organization_id = request.form.get('organization_id')
            user.school_id = None
        elif user.role == 'school_admin':
            user.school_id = request.form.get('school_id')
            school = School.query.get(user.school_id)
            if school:
                user.organization_id = school.organization_id
        else:
            user.organization_id = None
            user.school_id = None
        
        db.session.commit()
        flash('User updated successfully', 'success')
        return redirect(url_for('users'))
    
    organizations = Organization.query.all() if current_user.role == 'super_admin' else []
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    else:
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    
    return render_template('user_form.html', user=user, organizations=organizations, branches=branches)

@app.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin')
def delete_user(id):
    user = User.query.get_or_404(id)
    
    if user.id == current_user.id:
        flash('You cannot delete your own account', 'error')
        return redirect(url_for('users'))
    
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully', 'success')
    return redirect(url_for('users'))

# Reports
@app.route('/reports/attendance')
@login_required
def attendance_report():
    start_date = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    branch_id = request.args.get('branch_id', '')
    
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    query = Attendance.query.join(Staff).filter(
        Attendance.date >= start,
        Attendance.date <= end
    )
    
    if branch_id:
        query = query.filter(Staff.school_id == int(branch_id))
    elif current_user.role == 'org_admin':
        org_schools = School.query.filter_by(organization_id=current_user.organization_id).all()
        school_ids = [s.id for s in org_schools]
        query = query.filter(Staff.school_id.in_(school_ids))
    elif current_user.role == 'school_admin':
        query = query.filter(Staff.school_id == current_user.school_id)
    
    records = query.order_by(Attendance.date.desc(), Attendance.time_in.desc()).all()
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    return render_template('reports/attendance.html',
        records=records,
        branches=branches,
        start_date=start_date,
        end_date=end_date,
        selected_branch=branch_id
    )

@app.route('/reports/late')
@login_required
def late_report():
    start_date = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    branch_id = request.args.get('branch_id', '')
    
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    late_records = []
    
    filter_branches = [School.query.get(int(branch_id))] if branch_id else branches
    
    for branch in filter_branches:
        expected_start = branch.expected_start_time or '09:00'
        try:
            start_hour, start_min = map(int, expected_start.split(':'))
        except:
            start_hour, start_min = 9, 0
        
        attendances = Attendance.query.join(Staff).filter(
            Staff.school_id == branch.id,
            Attendance.date >= start,
            Attendance.date <= end,
            Attendance.time_in.isnot(None)
        ).all()
        
        for att in attendances:
            if att.time_in.hour > start_hour or (att.time_in.hour == start_hour and att.time_in.minute > start_min):
                late_records.append(att)
    
    late_records.sort(key=lambda x: (x.date, x.time_in), reverse=True)
    
    return render_template('reports/late.html',
        records=late_records,
        branches=branches,
        start_date=start_date,
        end_date=end_date,
        selected_branch=branch_id
    )

@app.route('/reports/absent')
@login_required
def absent_report():
    report_date = request.args.get('date', date.today().isoformat())
    branch_id = request.args.get('branch_id', '')
    
    check_date = datetime.strptime(report_date, '%Y-%m-%d').date()
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
        staff_query = Staff.query.filter_by(active=True)
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
        school_ids = [s.id for s in branches]
        staff_query = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.active==True)
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, active=True)
    
    if branch_id:
        staff_query = staff_query.filter(Staff.school_id == int(branch_id))
    
    all_staff = staff_query.all()
    
    present_staff_ids = db.session.query(Attendance.staff_id).filter(
        Attendance.date == check_date
    ).distinct().all()
    present_ids = [p[0] for p in present_staff_ids]
    
    absent_staff = [s for s in all_staff if s.id not in present_ids]
    
    return render_template('reports/absent.html',
        staff=absent_staff,
        branches=branches,
        report_date=report_date,
        selected_branch=branch_id
    )

@app.route('/reports/overtime')
@login_required
def overtime_report():
    start_date = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    branch_id = request.args.get('branch_id', '')
    
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    overtime_records = []
    
    filter_branches = [School.query.get(int(branch_id))] if branch_id else branches
    
    for branch in filter_branches:
        expected_end = branch.expected_end_time or '17:00'
        try:
            end_hour, end_min = map(int, expected_end.split(':'))
        except:
            end_hour, end_min = 17, 0
        
        attendances = Attendance.query.join(Staff).filter(
            Staff.school_id == branch.id,
            Attendance.date >= start,
            Attendance.date <= end,
            Attendance.time_out.isnot(None)
        ).all()
        
        for att in attendances:
            if att.time_out.hour > end_hour or (att.time_out.hour == end_hour and att.time_out.minute > end_min):
                overtime_records.append(att)
    
    overtime_records.sort(key=lambda x: (x.date, x.time_out), reverse=True)
    
    return render_template('reports/overtime.html',
        records=overtime_records,
        branches=branches,
        start_date=start_date,
        end_date=end_date,
        selected_branch=branch_id
    )

# Analytics
@app.route('/analytics')
@login_required
def analytics():
    start_date = request.args.get('start_date', (date.today() - timedelta(days=30)).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    branch_id = request.args.get('branch_id', '')
    
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    if branch_id:
        filter_branches = [School.query.get(int(branch_id))]
        school_ids = [int(branch_id)]
    else:
        filter_branches = branches
        school_ids = [b.id for b in branches]
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.active==True).count()
    
    total_days = (end - start).days + 1
    working_days = sum(1 for i in range(total_days) if (start + timedelta(days=i)).weekday() < 5)
    
    expected_attendance = total_staff * working_days
    
    actual_attendance = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date >= start,
        Attendance.date <= end
    ).count()
    
    attendance_rate = (actual_attendance / expected_attendance * 100) if expected_attendance > 0 else 0
    
    # Calculate late and on-time
    late_count = 0
    on_time_count = 0
    total_late_minutes = 0
    total_overtime_minutes = 0
    
    for branch in filter_branches:
        expected_start = branch.expected_start_time or '09:00'
        expected_end = branch.expected_end_time or '17:00'
        
        try:
            start_hour, start_min = map(int, expected_start.split(':'))
        except:
            start_hour, start_min = 9, 0
        
        try:
            end_hour, end_min = map(int, expected_end.split(':'))
        except:
            end_hour, end_min = 17, 0
        
        attendances = Attendance.query.join(Staff).filter(
            Staff.school_id == branch.id,
            Attendance.date >= start,
            Attendance.date <= end
        ).all()
        
        for att in attendances:
            if att.time_in:
                if att.time_in.hour > start_hour or (att.time_in.hour == start_hour and att.time_in.minute > start_min):
                    late_count += 1
                    late_mins = (att.time_in.hour - start_hour) * 60 + (att.time_in.minute - start_min)
                    total_late_minutes += late_mins
                else:
                    on_time_count += 1
            
            if att.time_out:
                if att.time_out.hour > end_hour or (att.time_out.hour == end_hour and att.time_out.minute > end_min):
                    ot_mins = (att.time_out.hour - end_hour) * 60 + (att.time_out.minute - end_min)
                    total_overtime_minutes += ot_mins
    
    punctuality_rate = (on_time_count / actual_attendance * 100) if actual_attendance > 0 else 0
    
    # Daily trend
    daily_data = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            day_attendance = Attendance.query.join(Staff).filter(
                Staff.school_id.in_(school_ids),
                Attendance.date == current
            ).count()
            daily_data.append({
                'date': current.strftime('%Y-%m-%d'),
                'count': day_attendance,
                'expected': total_staff
            })
        current += timedelta(days=1)
    
    return render_template('analytics.html',
        branches=branches,
        start_date=start_date,
        end_date=end_date,
        selected_branch=branch_id,
        total_staff=total_staff,
        attendance_rate=round(attendance_rate, 1),
        punctuality_rate=round(punctuality_rate, 1),
        late_count=late_count,
        on_time_count=on_time_count,
        total_late_minutes=total_late_minutes,
        total_overtime_minutes=total_overtime_minutes,
        daily_data=daily_data
    )

@app.route('/analytics/download')
@login_required
def download_analytics():
    start_date = request.args.get('start_date', (date.today() - timedelta(days=30)).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    branch_id = request.args.get('branch_id', '')
    
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    if current_user.role == 'super_admin':
        branches = School.query.all()
    elif current_user.role == 'org_admin':
        branches = School.query.filter_by(organization_id=current_user.organization_id).all()
    else:
        branches = School.query.filter_by(id=current_user.school_id).all()
    
    if branch_id:
        school_ids = [int(branch_id)]
        branch_name = School.query.get(int(branch_id)).name
    else:
        school_ids = [b.id for b in branches]
        branch_name = "All Branches"
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.active==True).count()
    
    total_days = (end - start).days + 1
    working_days = sum(1 for i in range(total_days) if (start + timedelta(days=i)).weekday() < 5)
    expected_attendance = total_staff * working_days
    
    actual_attendance = Attendance.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        Attendance.date >= start,
        Attendance.date <= end
    ).count()
    
    attendance_rate = (actual_attendance / expected_attendance * 100) if expected_attendance > 0 else 0
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; }}
            h1 {{ color: #1a365d; }}
            .stat {{ margin: 10px 0; padding: 10px; background: #f0f0f0; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background: #1a365d; color: white; }}
        </style>
    </head>
    <body>
        <h1>Analytics Report</h1>
        <p><strong>Period:</strong> {start_date} to {end_date}</p>
        <p><strong>Branch:</strong> {branch_name}</p>
        
        <div class="stat"><strong>Total Staff:</strong> {total_staff}</div>
        <div class="stat"><strong>Attendance Rate:</strong> {attendance_rate:.1f}%</div>
        <div class="stat"><strong>Total Attendance Records:</strong> {actual_attendance}</div>
        <div class="stat"><strong>Working Days:</strong> {working_days}</div>
        
        <p style="margin-top: 40px; font-size: 12px; color: #666;">
            Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </p>
    </body>
    </html>
    """
    
    pdf_buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=pdf_buffer)
    pdf_buffer.seek(0)
    
    return Response(
        pdf_buffer.getvalue(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename=analytics_{start_date}_{end_date}.pdf'}
    )

# Settings
@app.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def settings():
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        
        setting = SystemSettings.query.filter_by(setting_key='api_key').first()
        if setting:
            setting.setting_value = api_key
            setting.updated_at = datetime.utcnow()
        else:
            setting = SystemSettings(setting_key='api_key', setting_value=api_key)
            db.session.add(setting)
        
        db.session.commit()
        flash('Settings updated successfully', 'success')
        return redirect(url_for('settings'))
    
    api_key_setting = SystemSettings.query.filter_by(setting_key='api_key').first()
    current_api_key = api_key_setting.setting_value if api_key_setting else ''
    
    return render_template('settings.html', api_key=current_api_key)

@app.route('/settings/generate-key', methods=['POST'])
@login_required
@role_required('super_admin')
def generate_api_key():
    new_key = secrets.token_urlsafe(32)
    
    setting = SystemSettings.query.filter_by(setting_key='api_key').first()
    if setting:
        setting.setting_value = new_key
        setting.updated_at = datetime.utcnow()
    else:
        setting = SystemSettings(setting_key='api_key', setting_value=new_key)
        db.session.add(setting)
    
    db.session.commit()
    flash('New API key generated', 'success')
    return redirect(url_for('settings'))

# Profile
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.email = request.form.get('email')
        
        if request.form.get('new_password'):
            if current_user.check_password(request.form.get('current_password')):
                current_user.set_password(request.form.get('new_password'))
                flash('Password updated successfully', 'success')
            else:
                flash('Current password is incorrect', 'error')
                return redirect(url_for('profile'))
        
        db.session.commit()
        flash('Profile updated successfully', 'success')
        return redirect(url_for('profile'))
    
    return render_template('profile.html')

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
