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

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')

database_url = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'login'

class SystemSettings(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(100), default='Wakato Technologies')
    company_logo_url = db.Column(db.String(500), nullable=True)
    
    @staticmethod
    def get_settings():
        settings = SystemSettings.query.first()
        if not settings:
            settings = SystemSettings(company_name='Wakato Technologies')
            db.session.add(settings)
            db.session.commit()
        return settings

class Organization(db.Model):
    __tablename__ = 'organizations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    logo_url = db.Column(db.String(500), nullable=True)
    branches = db.relationship('School', backref='organization', lazy=True)

user_schools = db.Table('user_schools',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('school_id', db.Integer, db.ForeignKey('schools.id'), primary_key=True)
)

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20), nullable=True)
    logo_url = db.Column(db.String(500), nullable=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True)
    schedule_mon_start = db.Column(db.String(5), default='08:00')
    schedule_mon_end = db.Column(db.String(5), default='17:00')
    schedule_tue_start = db.Column(db.String(5), default='08:00')
    schedule_tue_end = db.Column(db.String(5), default='17:00')
    schedule_wed_start = db.Column(db.String(5), default='08:00')
    schedule_wed_end = db.Column(db.String(5), default='17:00')
    schedule_thu_start = db.Column(db.String(5), default='08:00')
    schedule_thu_end = db.Column(db.String(5), default='17:00')
    schedule_fri_start = db.Column(db.String(5), default='08:00')
    schedule_fri_end = db.Column(db.String(5), default='17:00')
    staff = db.relationship('Staff', backref='school', lazy=True, cascade='all, delete-orphan')
    users = db.relationship('User', backref='school', lazy=True)

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='school_admin')
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    allowed_schools = db.relationship('School', secondary=user_schools, lazy='subquery',
        backref=db.backref('allowed_users', lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_initials(self):
        return self.username[0].upper() if self.username else 'U'
    
    def get_accessible_schools(self):
        if self.role == 'super_admin':
            return School.query.all()
        elif self.allowed_schools:
            return self.allowed_schools
        elif self.school_id:
            return [self.school]
        return []
    
    def get_accessible_school_ids(self):
        return [s.id for s in self.get_accessible_schools()]
    
    def get_accessible_organizations(self):
        if self.role == 'super_admin':
            return Organization.query.all()
        org_ids = set()
        for school in self.get_accessible_schools():
            if school.organization_id:
                org_ids.add(school.organization_id)
        if org_ids:
            return Organization.query.filter(Organization.id.in_(org_ids)).all()
        return []
    
    def get_display_organization(self):
        if self.role == 'super_admin':
            return None
        schools = self.get_accessible_schools()
        if not schools:
            return None
        first_school = schools[0]
        if first_school.organization:
            return first_school.organization
        return None

class Staff(db.Model):
    __tablename__ = 'staff'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    times_late = db.Column(db.Integer, default=0)
    attendance = db.relationship('Attendance', backref='staff', lazy=True, cascade='all, delete-orphan')

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    sign_in_time = db.Column(db.DateTime, nullable=True)
    sign_out_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='present')
    is_late = db.Column(db.Boolean, default=False)
    late_minutes = db.Column(db.Integer, default=0)
    overtime_minutes = db.Column(db.Integer, default=0)

db.init_app(app)
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_settings():
    if current_user.is_authenticated:
        settings = SystemSettings.get_settings()
        user_org = current_user.get_display_organization()
        return {'system_settings': settings, 'user_organization': user_org}
    return {'system_settings': None, 'user_organization': None}

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_school_schedule(school, day_of_week):
    days = ['mon', 'tue', 'wed', 'thu', 'fri']
    if day_of_week < 5:
        day = days[day_of_week]
        start = getattr(school, f'schedule_{day}_start')
        end = getattr(school, f'schedule_{day}_end')
        return start, end
    return None, None

def get_staff_data_for_api(school):
    staff = Staff.query.filter_by(school_id=school.id, is_active=True).all()
    staff_list_data = []
    for s in staff:
        name_parts = s.name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        staff_list_data.append({
            'staff_id': s.staff_id,
            'first_name': first_name,
            'last_name': last_name,
            'name': s.name,
            'department': s.department
        })
    return staff_list_data

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

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
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def settings():
    settings = SystemSettings.get_settings()
    organizations = Organization.query.all()
    if request.method == 'POST':
        settings.company_name = request.form.get('company_name', 'Wakato Technologies')
        settings.company_logo_url = request.form.get('company_logo_url', '').strip() or None
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    return render_template('settings.html', settings=settings, organizations=organizations)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_organization():
    if request.method == 'POST':
        name = request.form.get('name')
        logo_url = request.form.get('logo_url', '').strip() or None
        org = Organization(name=name, logo_url=logo_url)
        db.session.add(org)
        db.session.commit()
        flash('Organization added successfully!', 'success')
        return redirect(url_for('settings'))
    return render_template('add_organization.html')

@app.route('/organizations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.logo_url = request.form.get('logo_url', '').strip() or None
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('settings'))
    return render_template('edit_organization.html', organization=org)

@app.route('/organizations/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    if org.branches:
        flash('Cannot delete organization with branches. Remove branches first.', 'danger')
        return redirect(url_for('settings'))
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    accessible_school_ids = current_user.get_accessible_school_ids()
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    if current_user.role == 'super_admin' or accessible_school_ids:
        if current_user.role == 'super_admin':
            all_staff = Staff.query.filter_by(is_active=True).all()
        else:
            all_staff = Staff.query.filter(Staff.school_id.in_(accessible_school_ids), Staff.is_active==True).all()
        total_staff = len(all_staff)
        all_staff_ids = [s.id for s in all_staff]
        today_attendance = Attendance.query.filter(
            Attendance.staff_id.in_(all_staff_ids),
            Attendance.date == today
        ).count() if all_staff_ids else 0
        late_today = Attendance.query.filter(
            Attendance.staff_id.in_(all_staff_ids),
            Attendance.date == today,
            Attendance.is_late == True
        ).count() if all_staff_ids else 0
        non_mgmt_staff = [s for s in all_staff if s.department != 'Management']
        non_mgmt_ids = [s.id for s in non_mgmt_staff]
        present_ids = [a.staff_id for a in Attendance.query.filter(
            Attendance.staff_id.in_(non_mgmt_ids),
            Attendance.date == today
        ).all()] if non_mgmt_ids else []
        absent_today = len([s for s in non_mgmt_staff if s.id not in present_ids])
        school_stats = []
        for school in schools:
            school_staff = Staff.query.filter_by(school_id=school.id, is_active=True).all()
            school_staff_ids = [s.id for s in school_staff]
            school_present = Attendance.query.filter(
                Attendance.staff_id.in_(school_staff_ids),
                Attendance.date == today
            ).count() if school_staff_ids else 0
            school_late = Attendance.query.filter(
                Attendance.staff_id.in_(school_staff_ids),
                Attendance.date == today,
                Attendance.is_late == True
            ).count() if school_staff_ids else 0
            school_stats.append({
                'school': school,
                'total_staff': len(school_staff),
                'present': school_present,
                'late': school_late
            })
    else:
        total_staff = 0
        today_attendance = 0
        late_today = 0
        absent_today = 0
        school_stats = []
    return render_template('dashboard.html', 
                         schools=schools,
                         school_stats=school_stats,
                         total_schools=len(schools),
                         total_staff=total_staff, 
                         today_attendance=today_attendance, 
                         late_today=late_today,
                         absent_today=absent_today)

@app.route('/schools')
@login_required
@role_required('super_admin')
def schools():
    all_schools = School.query.all()
    return render_template('schools.html', schools=all_schools)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_school():
    if request.method == 'POST':
        name = request.form.get('name')
        short_name = request.form.get('short_name')
        logo_url = request.form.get('logo_url', '').strip() or None
        organization_id = request.form.get('organization_id') or None
        api_key = secrets.token_hex(32)
        school = School(name=name, short_name=short_name, logo_url=logo_url, api_key=api_key, organization_id=organization_id)
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        db.session.add(school)
        db.session.commit()
        flash('Branch added successfully!', 'success')
        return redirect(url_for('schools'))
    organizations = Organization.query.all()
    return render_template('add_school.html', organizations=organizations)

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_school(id):
    school = School.query.get_or_404(id)
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.short_name = request.form.get('short_name')
        school.logo_url = request.form.get('logo_url', '').strip() or None
        school.organization_id = request.form.get('organization_id') or None
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        db.session.commit()
        flash('Branch updated successfully!', 'success')
        return redirect(url_for('schools'))
    organizations = Organization.query.all()
    return render_template('edit_school.html', school=school, organizations=organizations)

@app.route('/schools/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('Branch deleted successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/schools/regenerate-key/<int:id>')
@login_required
@role_required('super_admin')
def regenerate_api_key(id):
    school = School.query.get_or_404(id)
    school.api_key = secrets.token_hex(32)
    db.session.commit()
    flash('API key regenerated successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/staff')
@login_required
def staff_list():
    today = date.today()
    accessible_school_ids = current_user.get_accessible_school_ids()
    if current_user.role == 'super_admin':
        staff = Staff.query.all()
    elif accessible_school_ids:
        staff = Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()
    else:
        staff = []
    staff_with_status = []
    for s in staff:
        attendance_today = Attendance.query.filter_by(staff_id=s.id, date=today).first()
        if s.department == 'Management':
            status = 'N/A'
            status_color = 'secondary'
        elif attendance_today:
            if attendance_today.sign_out_time:
                status = 'Signed Out'
                status_color = 'primary'
            else:
                status = 'Signed In'
                status_color = 'success'
        else:
            status = 'Absent'
            status_color = 'danger'
        staff_with_status.append({
            'staff': s,
            'status': status,
            'status_color': status_color
        })
    schools = School.query.all()
    return render_template('staff.html', staff_with_status=staff_with_status, schools=schools)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_staff():
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        name = request.form.get('name')
        department = request.form.get('department')
        school_id = request.form.get('school_id')
        if current_user.role == 'school_admin':
            school_id = current_user.school_id
        existing = Staff.query.filter_by(staff_id=staff_id).first()
        if existing:
            flash('Staff ID already exists!', 'danger')
            return redirect(url_for('add_staff'))
        staff = Staff(staff_id=staff_id, name=name, department=department, school_id=school_id)
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff_list'))
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = [current_user.school]
    departments = ['Academic', 'Admin', 'Non-Academic', 'Management']
    return render_template('add_staff.html', schools=schools, departments=departments)

@app.route('/staff/toggle/<int:id>')
@login_required
@role_required('super_admin', 'school_admin')
def toggle_staff(id):
    staff = Staff.query.get_or_404(id)
    if current_user.role == 'school_admin' and staff.school_id != current_user.school_id:
        flash('You do not have permission to modify this staff.', 'danger')
        return redirect(url_for('staff_list'))
    staff.is_active = not staff.is_active
    db.session.commit()
    status = 'activated' if staff.is_active else 'deactivated'
    flash(f'Staff {status} successfully!', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    db.session.delete(staff)
    db.session.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/bulk-upload', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def bulk_upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected!', 'danger')
            return redirect(url_for('bulk_upload'))
        file = request.files['file']
        if file.filename == '':
            flash('No file selected!', 'danger')
            return redirect(url_for('bulk_upload'))
        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file!', 'danger')
            return redirect(url_for('bulk_upload'))
        school_id = request.form.get('school_id')
        if current_user.role == 'school_admin':
            school_id = current_user.school_id
        try:
            stream = io.StringIO(file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)
            added = 0
            skipped = 0
            for row in reader:
                staff_id = row.get('staff_id', '').strip()
                name = row.get('name', '').strip()
                department = row.get('department', '').strip()
                if not staff_id or not name:
                    skipped += 1
                    continue
                existing = Staff.query.filter_by(staff_id=staff_id).first()
                if existing:
                    skipped += 1
                    continue
                if department not in ['Academic', 'Admin', 'Non-Academic', 'Management']:
                    department = 'Academic'
                staff = Staff(staff_id=staff_id, name=name, department=department, school_id=school_id)
                db.session.add(staff)
                added += 1
            db.session.commit()
            flash(f'Bulk upload complete! Added: {added}, Skipped: {skipped}', 'success')
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'danger')
        return redirect(url_for('staff_list'))
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = [current_user.school]
    return render_template('bulk_upload.html', schools=schools)

@app.route('/users')
@login_required
@role_required('super_admin')
def users():
    all_users = User.query.all()
    return render_template('users.html', users=all_users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_user():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        school_ids = request.form.getlist('school_ids')
        existing = User.query.filter_by(username=username).first()
        if existing:
            flash('Username already exists!', 'danger')
            return redirect(url_for('add_user'))
        user = User(username=username, role=role)
        user.set_password(password)
        if school_ids:
            for school_id in school_ids:
                school = School.query.get(int(school_id))
                if school:
                    user.allowed_schools.append(school)
        db.session.add(user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    schools = School.query.all()
    roles = ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin', 'staff']
    return render_template('add_user.html', schools=schools, roles=roles)

@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_user(id):
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.role = request.form.get('role')
        school_ids = request.form.getlist('school_ids')
        password = request.form.get('password')
        if password:
            user.set_password(password)
        user.allowed_schools = []
        if school_ids:
            for school_id in school_ids:
                school = School.query.get(int(school_id))
                if school:
                    user.allowed_schools.append(school)
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    schools = School.query.all()
    roles = ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin', 'staff']
    return render_template('edit_user.html', user=user, schools=schools, roles=roles)

@app.route('/users/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete yourself!', 'danger')
        return redirect(url_for('users'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('users'))

@app.route('/reports/attendance')
@login_required
def attendance_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if today_param == '1':
        date_from = today.isoformat()
        date_to = today.isoformat()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
    accessible_school_ids = current_user.get_accessible_school_ids()
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    attendance = query.order_by(Attendance.date.desc()).all()
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    return render_template('attendance_report.html', 
                         attendance=attendance, 
                         schools=schools,
                         organizations=current_user.get_accessible_organizations(),
                         date_from=date_from,
                         date_to=date_to,
                         school_id=school_id,
                         today=today.isoformat())

@app.route('/reports/attendance/download')
@login_required
def download_attendance():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
    accessible_school_ids = current_user.get_accessible_school_ids()
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    attendance = query.order_by(Attendance.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Department', 'Sign In', 'Sign Out', 'Status', 'Late Minutes', 'Overtime Minutes'])
    for a in attendance:
        writer.writerow([
            a.date.strftime('%d/%m/%Y'),
            a.staff.staff_id,
            a.staff.name,
            a.staff.school.short_name or a.staff.school.name,
            a.staff.department,
            a.sign_in_time.strftime('%H:%M') if a.sign_in_time else '',
            a.sign_out_time.strftime('%H:%M') if a.sign_out_time else '',
            'Late' if a.is_late else 'On Time',
            a.late_minutes,
            a.overtime_minutes
        ])
    output.seek(0)
    filename = f'attendance_{date_from}_to_{date_to}.csv'
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/reports/late')
@login_required
def late_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    calc_mode = request.args.get('calc_mode', 'alltime')
    today = date.today()
    if today_param == '1':
        date_from = today.isoformat()
        date_to = today.isoformat()
    show_toggle = bool(date_from and date_to)
    start_date = None
    end_date = None
    if date_from and date_to:
        try:
            start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
            end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        except:
            pass
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    staff_list_data = staff_query.all()
    late_staff = []
    for s in staff_list_data:
        if s.department == 'Management':
            continue
        if start_date and end_date:
            period_att_query = Attendance.query.filter(
                Attendance.staff_id == s.id,
                Attendance.date >= start_date,
                Attendance.date <= end_date
            )
            period_total = period_att_query.count()
            period_late = period_att_query.filter_by(is_late=True).count()
        else:
            period_total = 0
            period_late = 0
        all_att_query = Attendance.query.filter_by(staff_id=s.id)
        all_total = all_att_query.count()
        all_late = all_att_query.filter_by(is_late=True).count()
        if start_date and end_date:
            times_late = period_late
        else:
            times_late = s.times_late
        if start_date and end_date and period_total == 0:
            continue
        if times_late > 0 or s.times_late > 0:
            if calc_mode == 'period' and start_date and end_date:
                if period_total > 0:
                    punctuality = round(((period_total - period_late) / period_total) * 100, 1)
                    lateness = round((period_late / period_total) * 100, 1)
                else:
                    punctuality = 100.0
                    lateness = 0.0
            else:
                if all_total > 0:
                    punctuality = round(((all_total - all_late) / all_total) * 100, 1)
                    lateness = round((all_late / all_total) * 100, 1)
                else:
                    punctuality = 100.0
                    lateness = 0.0
            late_staff.append({
                'staff': s,
                'times_late': times_late,
                'punctuality': punctuality,
                'lateness': lateness
            })
    late_staff.sort(key=lambda x: x['times_late'], reverse=True)
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    return render_template('late_report.html', 
                         late_staff=late_staff, 
                         schools=schools,
                         organizations=current_user.get_accessible_organizations(),
                         date_from=date_from,
                         date_to=date_to,
                         school_id=school_id,
                         calc_mode=calc_mode,
                         show_toggle=show_toggle,
                         today=today.isoformat())

@app.route('/reports/late/download')
@login_required
def download_late_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    calc_mode = request.args.get('calc_mode', 'alltime')
    start_date = None
    end_date = None
    if date_from and date_to:
        try:
            start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
            end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        except:
            pass
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    staff_list_data = staff_query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'Branch', 'Department', 'Times Late', '% Punctuality', '% Lateness'])
    for s in staff_list_data:
        if s.department == 'Management':
            continue
        if start_date and end_date:
            period_att_query = Attendance.query.filter(
                Attendance.staff_id == s.id,
                Attendance.date >= start_date,
                Attendance.date <= end_date
            )
            period_total = period_att_query.count()
            period_late = period_att_query.filter_by(is_late=True).count()
        else:
            period_total = 0
            period_late = 0
        all_att_query = Attendance.query.filter_by(staff_id=s.id)
        all_total = all_att_query.count()
        all_late = all_att_query.filter_by(is_late=True).count()
        if start_date and end_date:
            times_late = period_late
        else:
            times_late = s.times_late
        if start_date and end_date and period_total == 0:
            continue
        if times_late > 0 or s.times_late > 0:
            if calc_mode == 'period' and start_date and end_date:
                if period_total > 0:
                    punctuality = round(((period_total - period_late) / period_total) * 100, 1)
                    lateness = round((period_late / period_total) * 100, 1)
                else:
                    punctuality = 100.0
                    lateness = 0.0
            else:
                if all_total > 0:
                    punctuality = round(((all_total - all_late) / all_total) * 100, 1)
                    lateness = round((all_late / all_total) * 100, 1)
                else:
                    punctuality = 100.0
                    lateness = 0.0
            writer.writerow([
                s.staff_id,
                s.name,
                s.school.short_name or s.school.name,
                s.department,
                times_late,
                punctuality,
                lateness
            ])
    output.seek(0)
    filename = f'late_report_{date_from}_to_{date_to}.csv' if date_from and date_to else f'late_report_{date.today()}.csv'
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/reports/late/reset', methods=['POST'])
@login_required
@role_required('super_admin')
def reset_late_counter():
    school_id = request.form.get('school_id', '')
    if school_id:
        staff = Staff.query.filter_by(school_id=school_id).all()
        school = School.query.get(school_id)
        school_name = school.name if school else 'Unknown'
    else:
        staff = Staff.query.all()
        school_name = 'all branches'
    for s in staff:
        s.times_late = 0
    db.session.commit()
    flash(f'Late counters reset for {school_name}!', 'success')
    return redirect(url_for('late_report'))

@app.route('/reports/absent')
@login_required
def absent_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if today_param == '1':
        date_from = today.isoformat()
        date_to = today.isoformat()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    all_staff = staff_query.all()
    absent_records = []
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            for s in all_staff:
                if s.department == 'Management':
                    continue
                attendance = Attendance.query.filter_by(staff_id=s.id, date=current_date).first()
                if not attendance:
                    absent_records.append({
                        'date': current_date,
                        'staff': s
                    })
        current_date += timedelta(days=1)
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    return render_template('absent_report.html', 
                         absent_records=absent_records, 
                         schools=schools,
                         organizations=current_user.get_accessible_organizations(),
                         date_from=date_from,
                         date_to=date_to,
                         school_id=school_id,
                         today=today.isoformat())

@app.route('/reports/absent/download')
@login_required
def download_absent_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    accessible_school_ids = current_user.get_accessible_school_ids()
    staff_query = Staff.query.filter_by(is_active=True)
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    all_staff = staff_query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Department'])
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            for s in all_staff:
                if s.department == 'Management':
                    continue
                attendance = Attendance.query.filter_by(staff_id=s.id, date=current_date).first()
                if not attendance:
                    writer.writerow([
                        current_date.strftime('%d/%m/%Y'),
                        s.staff_id,
                        s.name,
                        s.school.short_name or s.school.name,
                        s.department
                    ])
        current_date += timedelta(days=1)
    output.seek(0)
    filename = f'absent_{date_from}_to_{date_to}.csv'
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/reports/overtime')
@login_required
def overtime_report():
    today_param = request.args.get('today', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if today_param == '1':
        date_from = today.isoformat()
        date_to = today.isoformat()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Attendance.overtime_minutes > 0
    )
    accessible_school_ids = current_user.get_accessible_school_ids()
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    overtime = query.order_by(Attendance.date.desc()).all()
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    return render_template('overtime_report.html', 
                         overtime=overtime, 
                         schools=schools,
                         organizations=current_user.get_accessible_organizations(),
                         date_from=date_from,
                         date_to=date_to,
                         school_id=school_id,
                         today=today.isoformat())

@app.route('/reports/overtime/download')
@login_required
def download_overtime_report():
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    school_id = request.args.get('school_id', '')
    today = date.today()
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()
    try:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        start_date = today
        end_date = today
    query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Attendance.overtime_minutes > 0
    )
    accessible_school_ids = current_user.get_accessible_school_ids()
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(accessible_school_ids)).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    overtime = query.order_by(Attendance.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Department', 'Sign Out', 'Overtime (mins)'])
    for o in overtime:
        writer.writerow([
            o.date.strftime('%d/%m/%Y'),
            o.staff.staff_id,
            o.staff.name,
            o.staff.school.short_name or o.staff.school.name,
            o.staff.department,
            o.sign_out_time.strftime('%H:%M') if o.sign_out_time else '',
            o.overtime_minutes
        ])
    output.seek(0)
    filename = f'overtime_{date_from}_to_{date_to}.csv'
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

@app.route('/reports/analytics')
@login_required
def analytics():
    period = request.args.get('period', '30')
    school_id = request.args.get('school_id', '')
    organization_id = request.args.get('organization_id', '')
    department_filter = request.args.get('department', '')
    start_date_param = request.args.get('start_date', '')
    end_date_param = request.args.get('end_date', '')
    
    today = date.today()
    
    if period == 'today':
        start_date = today
        end_date = today
        period_days = 1
    elif period == 'custom' and start_date_param and end_date_param:
        try:
            start_date = datetime.strptime(start_date_param, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_param, '%Y-%m-%d').date()
            period_days = (end_date - start_date).days + 1
        except:
            start_date = today - timedelta(days=30)
            end_date = today
            period_days = 30
    elif period == 'this_week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
        period_days = (end_date - start_date).days + 1
    elif period == 'last_week':
        start_date = today - timedelta(days=today.weekday() + 7)
        end_date = today - timedelta(days=today.weekday() + 1)
        period_days = 7
    elif period == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
        period_days = (end_date - start_date).days + 1
    elif period == 'last_month':
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
        period_days = (end_date - start_date).days + 1
    else:
        try:
            period_days = int(period)
        except:
            period_days = 30
        start_date = today - timedelta(days=period_days)
        end_date = today
    
    previous_start = start_date - timedelta(days=period_days)
    previous_end = start_date - timedelta(days=1)
    
    accessible_school_ids = current_user.get_accessible_school_ids()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    
    organizations = current_user.get_accessible_organizations()
    departments = ['Academic', 'Admin', 'Non-Academic', 'Management']
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if organization_id:
        org_school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
        staff_query = staff_query.filter(Staff.school_id.in_(org_school_ids))
    elif school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role != 'super_admin' and accessible_school_ids:
        staff_query = staff_query.filter(Staff.school_id.in_(accessible_school_ids))
    
    if department_filter:
        staff_query = staff_query.filter_by(department=department_filter)
    
    all_staff = staff_query.all()
    staff_ids = [s.id for s in all_staff]
    
    current_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all() if staff_ids else []
    
    previous_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= previous_start,
        Attendance.date < start_date
    ).all() if staff_ids else []
    
    total_staff = len(all_staff)
    branch_count = len(set(s.school_id for s in all_staff)) if all_staff else 0
    total_records = len(current_attendance)
    
    working_days = sum(1 for i in range(period_days) if (start_date + timedelta(days=i)).weekday() < 5)
    expected_attendance = total_staff * working_days if total_staff > 0 else 1
    
    attendance_rate = round((total_records / expected_attendance) * 100, 1) if expected_attendance > 0 else 0
    attendance_rate = min(attendance_rate, 100)
    
    prev_working_days = sum(1 for i in range(period_days) if (previous_start + timedelta(days=i)).weekday() < 5)
    prev_expected = total_staff * prev_working_days if total_staff > 0 else 1
    prev_attendance_rate = round((len(previous_attendance) / prev_expected) * 100, 1) if prev_expected > 0 else 0
    prev_attendance_rate = min(prev_attendance_rate, 100)
    
    attendance_trend = round(attendance_rate - prev_attendance_rate, 1)
    
    on_time_count = sum(1 for a in current_attendance if not a.is_late)
    late_count = sum(1 for a in current_attendance if a.is_late)
    punctuality_rate = round((on_time_count / total_records) * 100, 1) if total_records > 0 else 100
    
    prev_on_time = sum(1 for a in previous_attendance if not a.is_late)
    prev_punctuality = round((prev_on_time / len(previous_attendance)) * 100, 1) if previous_attendance else 100
    punctuality_trend = round(punctuality_rate - prev_punctuality, 1)
    
    total_late_minutes = sum(a.late_minutes for a in current_attendance if a.is_late)
    avg_late_minutes = round(total_late_minutes / late_count, 1) if late_count > 0 else 0
    
    total_overtime_minutes = sum(a.overtime_minutes for a in current_attendance)
    overtime_hours = total_overtime_minutes // 60
    overtime_mins = total_overtime_minutes % 60
    
    trend_labels = []
    trend_data = []
    punctuality_data = []
    
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            day_attendance = [a for a in current_attendance if a.date == current_date]
            day_count = len(day_attendance)
            day_rate = round((day_count / total_staff) * 100, 1) if total_staff > 0 else 0
            day_on_time = sum(1 for a in day_attendance if not a.is_late)
            day_punctuality = round((day_on_time / day_count) * 100, 1) if day_count > 0 else 100
            
            trend_labels.append(current_date.strftime('%d %b'))
            trend_data.append(min(day_rate, 100))
            punctuality_data.append(day_punctuality)
        current_date += timedelta(days=1)
    
    late_by_day = [0, 0, 0, 0, 0, 0, 0]
    for a in current_attendance:
        if a.is_late:
            late_by_day[a.date.weekday()] += 1
    
    dept_list = ['Academic', 'Admin', 'Non-Academic', 'Management']
    department_labels = []
    department_data = []
    for dept in dept_list:
        dept_staff = [s for s in all_staff if s.department == dept]
        if dept_staff:
            dept_staff_ids = [s.id for s in dept_staff]
            dept_attendance = [a for a in current_attendance if a.staff_id in dept_staff_ids]
            dept_on_time = sum(1 for a in dept_attendance if not a.is_late)
            dept_punctuality = round((dept_on_time / len(dept_attendance)) * 100) if dept_attendance else 0
            department_labels.append(dept)
            department_data.append(dept_punctuality)
    
    branch_labels = []
    branch_attendance = []
    branch_punctuality = []
    
    for school in schools[:10]:
        school_staff = [s for s in all_staff if s.school_id == school.id]
        if school_staff:
            school_staff_ids = [s.id for s in school_staff]
            school_att = [a for a in current_attendance if a.staff_id in school_staff_ids]
            
            school_working_days = working_days
            school_expected = len(school_staff) * school_working_days if school_staff else 1
            school_rate = round((len(school_att) / school_expected) * 100, 1) if school_expected > 0 else 0
            
            school_on_time = sum(1 for a in school_att if not a.is_late)
            school_punct = round((school_on_time / len(school_att)) * 100, 1) if school_att else 100
            
            branch_labels.append(school.short_name or school.name[:15])
            branch_attendance.append(min(school_rate, 100))
            branch_punctuality.append(school_punct)
    
    early_arrivals = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_attendance = [a for a in current_attendance if a.staff_id == s.id]
        early_count = 0
        total_early_mins = 0
        for a in staff_attendance:
            if a.sign_in_time and not a.is_late:
                school = s.school
                if school:
                    day_of_week = a.date.weekday()
                    start_time_str, _ = get_school_schedule(school, day_of_week)
                    if start_time_str:
                        scheduled_start = datetime.strptime(start_time_str, '%H:%M').time()
                        if a.sign_in_time.time() < scheduled_start:
                            early_count += 1
                            delta = datetime.combine(a.date, scheduled_start) - datetime.combine(a.date, a.sign_in_time.time())
                            total_early_mins += int(delta.total_seconds() / 60)
        if early_count > 0:
            avg_early = round(total_early_mins / early_count)
            early_arrivals.append({
                'name': s.name,
                'branch': s.school.short_name or s.school.name if s.school else 'N/A',
                'early_count': early_count,
                'avg_early_mins': avg_early
            })
    early_arrivals.sort(key=lambda x: x['early_count'], reverse=True)
    early_arrivals = early_arrivals[:5]
    
    perfect_attendance = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_attendance = [a for a in current_attendance if a.staff_id == s.id]
        staff_on_time = sum(1 for a in staff_attendance if not a.is_late)
        if len(staff_attendance) >= working_days and staff_on_time == len(staff_attendance):
            perfect_attendance.append({
                'name': s.name,
                'branch': s.school.short_name or s.school.name if s.school else 'N/A',
                'days': len(staff_attendance)
            })
    perfect_attendance.sort(key=lambda x: x['days'], reverse=True)
    perfect_attendance = perfect_attendance[:5]
    
    most_improved = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        prev_staff_att = [a for a in previous_attendance if a.staff_id == s.id]
        curr_staff_att = [a for a in current_attendance if a.staff_id == s.id]
        prev_late = sum(1 for a in prev_staff_att if a.is_late)
        curr_late = sum(1 for a in curr_staff_att if a.is_late)
        if prev_late > 0 and curr_late < prev_late:
            reduction = prev_late - curr_late
            improvement = round((reduction / prev_late) * 100, 1) if prev_late > 0 else 0
            most_improved.append({
                'name': s.name,
                'branch': s.school.short_name or s.school.name if s.school else 'N/A',
                'prev_late': prev_late,
                'curr_late': curr_late,
                'reduction': reduction,
                'improvement': improvement
            })
    most_improved.sort(key=lambda x: x['reduction'], reverse=True)
    most_improved = most_improved[:5]
    
    attendance_streaks = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_attendance = sorted([a for a in current_attendance if a.staff_id == s.id], key=lambda x: x.date)
        current_streak = 0
        max_streak = 0
        for a in staff_attendance:
            if not a.is_late:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        if max_streak >= 3:
            attendance_streaks.append({
                'name': s.name,
                'branch': s.school.short_name or s.school.name if s.school else 'N/A',
                'streak': max_streak
            })
    attendance_streaks.sort(key=lambda x: x['streak'], reverse=True)
    attendance_streaks = attendance_streaks[:5]
    
    top_performers = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_attendance = [a for a in current_attendance if a.staff_id == s.id]
        if len(staff_attendance) >= 3:
            on_time = sum(1 for a in staff_attendance if not a.is_late)
            punctuality = round((on_time / len(staff_attendance)) * 100, 1)
            top_performers.append({
                'name': s.name,
                'branch': s.school.short_name or s.school.name if s.school else 'N/A',
                'punctuality': punctuality
            })
    top_performers.sort(key=lambda x: x['punctuality'], reverse=True)
    top_performers = top_performers[:5]
    
    needs_attention = []
    for s in all_staff:
        if s.department == 'Management':
            continue
        staff_attendance = [a for a in current_attendance if a.staff_id == s.id]
        late_cnt = sum(1 for a in staff_attendance if a.is_late)
        if late_cnt > 0:
            needs_attention.append({
                'name': s.name,
                'branch': s.school.short_name or s.school.name if s.school else 'N/A',
                'late_count': late_cnt
            })
    needs_attention.sort(key=lambda x: x['late_count'], reverse=True)
    needs_attention = needs_attention[:5]
    
    return render_template('analytics.html',
                         schools=schools,
                         organizations=organizations,
                         departments=departments,
                         selected_school_id=school_id,
                         selected_organization_id=organization_id,
                         selected_department=department_filter,
                         period=period,
                         start_date=start_date.strftime('%Y-%m-%d'),
                         end_date=end_date.strftime('%Y-%m-%d'),
                         attendance_rate=attendance_rate,
                         attendance_trend=attendance_trend,
                         punctuality_rate=punctuality_rate,
                         punctuality_trend=punctuality_trend,
                         total_staff=total_staff,
                         branch_count=branch_count,
                         total_records=total_records,
                         on_time_count=on_time_count,
                         late_count=late_count,
                         avg_late_minutes=avg_late_minutes,
                         overtime_hours=overtime_hours,
                         overtime_mins=overtime_mins,
                         trend_labels=trend_labels,
                         trend_data=trend_data,
                         punctuality_data=punctuality_data,
                         late_by_day=late_by_day,
                         department_labels=department_labels,
                         department_data=department_data,
                         branch_labels=branch_labels,
                         branch_attendance=branch_attendance,
                         branch_punctuality=branch_punctuality,
                         early_arrivals=early_arrivals,
                         perfect_attendance=perfect_attendance,
                         most_improved=most_improved,
                         attendance_streaks=attendance_streaks,
                         top_performers=top_performers,
                         needs_attention=needs_attention)


@app.route('/api/sync', methods=['GET', 'POST', 'OPTIONS'])
def api_sync():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        return response
    
    if request.method == 'GET':
        response = jsonify({'status': 'API is working', 'message': 'Use POST with X-API-Key header'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        response = jsonify({'error': 'API key required'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 401
    
    school = School.query.filter_by(api_key=api_key).first()
    
    if not school:
        response = jsonify({'error': 'Invalid API key'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 401
    
    data = request.get_json()
    
    if not data:
        response = jsonify({'error': 'No data provided'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 400
    
    action = data.get('action')
    
    if action is None and 'records' in data:
        records = data.get('records', [])
        
        if len(records) == 0:
            staff_list_data = get_staff_data_for_api(school)
            response = jsonify({
                'success': True,
                'staff': staff_list_data,
                'school': {
                    'name': school.name,
                    'short_name': school.short_name or '',
                    'logo_url': school.logo_url or ''
                }
            })
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response
        
        synced = 0
        errors = []
        
        for record in records:
            try:
                staff = Staff.query.filter_by(staff_id=record['staff_id'], school_id=school.id).first()
                
                if not staff:
                    errors.append(f"Staff {record['staff_id']} not found")
                    continue
                
                record_date = datetime.strptime(record['date'], '%Y-%m-%d').date()
                
                attendance = Attendance.query.filter_by(staff_id=staff.id, date=record_date).first()
                
                sign_in_time = record.get('sign_in_time')
                sign_out_time = record.get('sign_out_time')
                
                if sign_in_time and not attendance:
                    sign_in_datetime = datetime.strptime(f"{record['date']} {sign_in_time}", '%Y-%m-%d %H:%M:%S')
                    
                    day_of_week = record_date.weekday()
                    start_time, end_time = get_school_schedule(school, day_of_week)
                    
                    is_late = False
                    late_minutes = 0
                    
                    if start_time:
                        scheduled_start = datetime.strptime(start_time, '%H:%M').time()
                        if sign_in_datetime.time() > scheduled_start:
                            is_late = True
                            delta = datetime.combine(record_date, sign_in_datetime.time()) - datetime.combine(record_date, scheduled_start)
                            late_minutes = int(delta.total_seconds() / 60)
                            staff.times_late += 1
                    
                    attendance = Attendance(
                        staff_id=staff.id,
                        date=record_date,
                        sign_in_time=sign_in_datetime,
                        is_late=is_late,
                        late_minutes=late_minutes
                    )
                    db.session.add(attendance)
                    synced += 1
                
                if sign_out_time and attendance and not attendance.sign_out_time:
                    sign_out_datetime = datetime.strptime(f"{record['date']} {sign_out_time}", '%Y-%m-%d %H:%M:%S')
                    attendance.sign_out_time = sign_out_datetime
                    
                    day_of_week = record_date.weekday()
                    start_time, end_time = get_school_schedule(school, day_of_week)
                    
                    if end_time:
                        scheduled_end = datetime.strptime(end_time, '%H:%M').time()
                        if sign_out_datetime.time() > scheduled_end:
                            delta = datetime.combine(record_date, sign_out_datetime.time()) - datetime.combine(record_date, scheduled_end)
                            attendance.overtime_minutes = int(delta.total_seconds() / 60)
                    
                    synced += 1
            
            except Exception as e:
                errors.append(str(e))
        
        db.session.commit()
        
        staff_list_data = get_staff_data_for_api(school)
        response = jsonify({
            'success': True,
            'synced': synced,
            'errors': errors,
            'staff': staff_list_data,
            'school': {
                'name': school.name,
                'short_name': school.short_name or '',
                'logo_url': school.logo_url or ''
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    if action == 'get_staff':
        staff_list_data = get_staff_data_for_api(school)
        response = jsonify({
            'staff': staff_list_data,
            'school': {
                'name': school.name,
                'short_name': school.short_name or '',
                'logo_url': school.logo_url or ''
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    elif action == 'sync_attendance':
        records = data.get('records', [])
        synced = 0
        errors = []
        
        for record in records:
            try:
                staff = Staff.query.filter_by(staff_id=record['staff_id'], school_id=school.id).first()
                
                if not staff:
                    errors.append(f"Staff {record['staff_id']} not found")
                    continue
                
                record_date = datetime.strptime(record['date'], '%Y-%m-%d').date()
                record_time = datetime.strptime(record['timestamp'], '%Y-%m-%d %H:%M:%S')
                
                attendance = Attendance.query.filter_by(staff_id=staff.id, date=record_date).first()
                
                if record['type'] == 'sign_in':
                    if not attendance:
                        day_of_week = record_date.weekday()
                        start_time, end_time = get_school_schedule(school, day_of_week)
                        
                        is_late = False
                        late_minutes = 0
                        
                        if start_time:
                            scheduled_start = datetime.strptime(start_time, '%H:%M').time()
                            if record_time.time() > scheduled_start:
                                is_late = True
                                delta = datetime.combine(record_date, record_time.time()) - datetime.combine(record_date, scheduled_start)
                                late_minutes = int(delta.total_seconds() / 60)
                                staff.times_late += 1
                        
                        attendance = Attendance(
                            staff_id=staff.id,
                            date=record_date,
                            sign_in_time=record_time,
                            is_late=is_late,
                            late_minutes=late_minutes
                        )
                        db.session.add(attendance)
                        synced += 1
                
                elif record['type'] == 'sign_out':
                    if attendance and not attendance.sign_out_time:
                        attendance.sign_out_time = record_time
                        
                        day_of_week = record_date.weekday()
                        start_time, end_time = get_school_schedule(school, day_of_week)
                        
                        if end_time:
                            scheduled_end = datetime.strptime(end_time, '%H:%M').time()
                            if record_time.time() > scheduled_end:
                                delta = datetime.combine(record_date, record_time.time()) - datetime.combine(record_date, scheduled_end)
                                attendance.overtime_minutes = int(delta.total_seconds() / 60)
                        
                        synced += 1
            
            except Exception as e:
                errors.append(str(e))
        
        db.session.commit()
        
        staff_list_data = get_staff_data_for_api(school)
        response = jsonify({
            'success': True,
            'synced': synced,
            'errors': errors,
            'staff': staff_list_data,
            'school': {
                'name': school.name,
                'short_name': school.short_name or '',
                'logo_url': school.logo_url or ''
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    elif action == 'check_status':
        staff_id = data.get('staff_id')
        staff = Staff.query.filter_by(staff_id=staff_id, school_id=school.id).first()
        
        if not staff:
            response = jsonify({'error': 'Staff not found'})
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response, 404
        
        today_date = date.today()
        attendance = Attendance.query.filter_by(staff_id=staff.id, date=today_date).first()
        
        if attendance:
            if attendance.sign_out_time:
                status = 'signed_out'
            else:
                status = 'signed_in'
        else:
            status = 'not_signed_in'
        
        name_parts = staff.name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        response = jsonify({
            'staff_id': staff.staff_id,
            'first_name': first_name,
            'last_name': last_name,
            'name': staff.name,
            'status': status
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    response = jsonify({'error': 'Invalid action'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 400


@app.route('/init-db')
def init_db():
    try:
        db.create_all()
        
        try:
            db.session.execute(db.text('ALTER TABLE schools ADD COLUMN organization_id INTEGER'))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('ALTER TABLE schools ADD COLUMN logo_url VARCHAR(500)'))
            db.session.commit()
        except:
            db.session.rollback()
        
        try:
            db.session.execute(db.text('''
                CREATE TABLE IF NOT EXISTS user_schools (
                    user_id INTEGER NOT NULL,
                    school_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, school_id),
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (school_id) REFERENCES schools(id)
                )
            '''))
            db.session.commit()
        except:
            db.session.rollback()
        
        if not SystemSettings.query.first():
            settings = SystemSettings(company_name='Wakato Technologies')
            db.session.add(settings)
        
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', role='super_admin')
            admin.set_password('admin123')
            db.session.add(admin)
        
        db.session.commit()
        return 'Database initialized successfully!'
    except Exception as e:
        return f'Error: {str(e)}'


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
