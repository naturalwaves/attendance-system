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
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', '').replace('postgres://', 'postgresql://') or 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default='Attendance System')
    company_logo_url = db.Column(db.String(500))
    api_key = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    logo_url = db.Column(db.String(500))
    is_school = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    branches = db.relationship('School', backref='organization', lazy=True)
    departments = db.relationship('Department', backref='organization', lazy=True)

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='viewer')
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    organization = db.relationship('Organization', backref='users')
    school = db.relationship('School', backref='users')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_active_user(self):
        return self.is_active
    
    def get_id(self):
        return str(self.id)

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True)
    attendance_records = db.relationship('Attendance', backref='school', lazy=True)

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))
    position = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance_records = db.relationship('Attendance', backref='staff', lazy=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.Time)
    check_out = db.Column(db.Time)
    status = db.Column(db.String(20), default='present')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except:
        return None

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

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
        if user and user.check_password(password):
            if not user.is_active:
                flash('Account is disabled.', 'danger')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    
    if current_user.role == 'super_admin':
        total_staff = Staff.query.filter_by(is_active=True).count()
        total_schools = School.query.filter_by(is_active=True).count()
        today_attendance = Attendance.query.filter_by(date=today, status='present').count()
        late_today = Attendance.query.filter_by(date=today, status='late').count()
        absent_today = Attendance.query.filter_by(date=today, status='absent').count()
        organizations = Organization.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        org_schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in org_schools]
        total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).count() if school_ids else 0
        total_schools = len(org_schools)
        today_attendance = Attendance.query.filter(Attendance.school_id.in_(school_ids), Attendance.date==today, Attendance.status=='present').count() if school_ids else 0
        late_today = Attendance.query.filter(Attendance.school_id.in_(school_ids), Attendance.date==today, Attendance.status=='late').count() if school_ids else 0
        absent_today = Attendance.query.filter(Attendance.school_id.in_(school_ids), Attendance.date==today, Attendance.status=='absent').count() if school_ids else 0
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
    else:
        total_staff = 0
        total_schools = 0
        today_attendance = 0
        late_today = 0
        absent_today = 0
        organizations = []
    
    return render_template('dashboard.html', 
                         total_staff=total_staff,
                         total_schools=total_schools,
                         today_attendance=today_attendance,
                         late_today=late_today,
                         absent_today=absent_today,
                         organizations=organizations)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def settings():
    settings_obj = SystemSettings.query.first()
    if not settings_obj:
        settings_obj = SystemSettings(company_name='Attendance System')
        db.session.add(settings_obj)
        db.session.commit()
    
    if request.method == 'POST':
        settings_obj.company_name = request.form.get('company_name', 'Attendance System')
        settings_obj.company_logo_url = request.form.get('company_logo_url', '')
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    return render_template('settings.html', settings=settings_obj, organizations=organizations)

@app.route('/organizations')
@login_required
@role_required('super_admin')
def organizations():
    orgs = Organization.query.filter_by(is_active=True).all()
    return render_template('organizations.html', organizations=orgs)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_organization():
    if request.method == 'POST':
        name = request.form.get('name')
        logo_url = request.form.get('logo_url', '')
        is_school = request.form.get('is_school') == 'on'
        
        org = Organization(name=name, logo_url=logo_url, is_school=is_school)
        db.session.add(org)
        db.session.commit()
        
        if is_school:
            default_depts = ['Academic', 'Non-Academic', 'Administration', 'Support Staff']
        else:
            default_depts = ['Operations', 'Finance', 'Human Resources', 'IT', 'Marketing', 'Administration']
        
        for dept_name in default_depts:
            dept = Department(name=dept_name, organization_id=org.id)
            db.session.add(dept)
        db.session.commit()
        
        flash(f'Organization "{name}" created with default departments!', 'success')
        return redirect(url_for('organizations'))
    
    return render_template('add_organization.html')

@app.route('/organizations/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.logo_url = request.form.get('logo_url', '')
        org.is_school = request.form.get('is_school') == 'on'
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('organizations'))
    return render_template('edit_organization.html', organization=org)

@app.route('/organizations/<int:id>/delete')
@login_required
@role_required('super_admin')
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    org.is_active = False
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('organizations'))

@app.route('/organizations/<int:org_id>/departments')
@login_required
def manage_departments(org_id):
    org = Organization.query.get_or_404(org_id)
    
    if current_user.role == 'school_admin':
        if current_user.organization_id != org_id:
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    departments = Department.query.filter_by(organization_id=org_id, is_active=True).all()
    return render_template('manage_departments.html', organization=org, departments=departments)

@app.route('/organizations/<int:org_id>/departments/add', methods=['POST'])
@login_required
def add_department(org_id):
    org = Organization.query.get_or_404(org_id)
    
    if current_user.role == 'school_admin':
        if current_user.organization_id != org_id:
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    name = request.form.get('name')
    if name:
        existing = Department.query.filter_by(organization_id=org_id, name=name, is_active=True).first()
        if existing:
            flash('Department already exists!', 'warning')
        else:
            dept = Department(name=name, organization_id=org_id)
            db.session.add(dept)
            db.session.commit()
            flash(f'Department "{name}" added successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))

@app.route('/departments/<int:id>/delete')
@login_required
def delete_department(id):
    dept = Department.query.get_or_404(id)
    org_id = dept.organization_id
    
    if current_user.role == 'school_admin':
        if current_user.organization_id != org_id:
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    dept.is_active = False
    db.session.commit()
    flash('Department deleted successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))

@app.route('/organizations/<int:org_id>/departments/seed')
@login_required
def seed_default_departments(org_id):
    org = Organization.query.get_or_404(org_id)
    
    if current_user.role == 'school_admin':
        if current_user.organization_id != org_id:
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
    elif current_user.role != 'super_admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    if org.is_school:
        default_depts = ['Academic', 'Non-Academic', 'Administration', 'Support Staff']
    else:
        default_depts = ['Operations', 'Finance', 'Human Resources', 'IT', 'Marketing', 'Administration']
    
    added = 0
    for dept_name in default_depts:
        existing = Department.query.filter_by(organization_id=org_id, name=dept_name, is_active=True).first()
        if not existing:
            dept = Department(name=dept_name, organization_id=org_id)
            db.session.add(dept)
            added += 1
    
    db.session.commit()
    flash(f'Added {added} default departments!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))

@app.route('/schools')
@login_required
def schools():
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
        organizations = Organization.query.filter_by(is_active=True).all()
    elif current_user.role == 'school_admin' and current_user.organization_id:
        schools_list = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
    else:
        schools_list = []
        organizations = []
    return render_template('schools.html', schools=schools_list, organizations=organizations)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_school():
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address', '')
        organization_id = request.form.get('organization_id')
        
        if current_user.role == 'school_admin':
            organization_id = current_user.organization_id
        
        school = School(name=name, address=address, organization_id=organization_id)
        db.session.add(school)
        db.session.commit()
        flash('Branch added successfully!', 'success')
        return redirect(url_for('schools'))
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.filter_by(is_active=True).all()
    else:
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
    
    return render_template('add_school.html', organizations=organizations)

@app.route('/schools/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def edit_school(id):
    school = School.query.get_or_404(id)
    
    if current_user.role == 'school_admin' and school.organization_id != current_user.organization_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('schools'))
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.address = request.form.get('address', '')
        if current_user.role == 'super_admin':
            school.organization_id = request.form.get('organization_id')
        db.session.commit()
        flash('Branch updated successfully!', 'success')
        return redirect(url_for('schools'))
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.filter_by(is_active=True).all()
    else:
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
    
    return render_template('edit_school.html', school=school, organizations=organizations)

@app.route('/schools/<int:id>/delete')
@login_required
@role_required('super_admin')
def delete_school(id):
    school = School.query.get_or_404(id)
    school.is_active = False
    db.session.commit()
    flash('Branch deleted successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/staff')
@login_required
def staff():
    if current_user.role == 'super_admin':
        staff_list = Staff.query.filter_by(is_active=True).all()
    elif current_user.role in ['school_admin', 'hr_viewer'] and current_user.organization_id:
        org_schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in org_schools]
        staff_list = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).all() if school_ids else []
    elif current_user.school_id:
        staff_list = Staff.query.filter_by(school_id=current_user.school_id, is_active=True).all()
    else:
        staff_list = []
    return render_template('staff.html', staff=staff_list)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def add_staff():
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        name = request.form.get('name')
        department = request.form.get('department')
        position = request.form.get('position', '')
        school_id = request.form.get('school_id')
        
        existing = Staff.query.filter_by(staff_id=staff_id).first()
        if existing:
            flash('Staff ID already exists!', 'danger')
            return redirect(url_for('add_staff'))
        
        staff_member = Staff(staff_id=staff_id, name=name, department=department, 
                           position=position, school_id=school_id)
        db.session.add(staff_member)
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff'))
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
        organizations = Organization.query.filter_by(is_active=True).all()
        departments = Department.query.filter_by(is_active=True).all()
        user_org = None
    else:
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
        schools_list = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        departments = Department.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        user_org = Organization.query.get(current_user.organization_id)
    
    return render_template('add_staff.html', schools=schools_list, organizations=organizations, 
                         departments=departments, user_org=user_org)

@app.route('/staff/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def edit_staff(id):
    staff_member = Staff.query.get_or_404(id)
    
    if current_user.role == 'school_admin':
        org_schools = School.query.filter_by(organization_id=current_user.organization_id).all()
        if staff_member.school_id not in [s.id for s in org_schools]:
            flash('Access denied.', 'danger')
            return redirect(url_for('staff'))
    
    if request.method == 'POST':
        staff_member.name = request.form.get('name')
        staff_member.department = request.form.get('department')
        staff_member.position = request.form.get('position', '')
        if current_user.role == 'super_admin':
            staff_member.school_id = request.form.get('school_id')
        db.session.commit()
        flash('Staff updated successfully!', 'success')
        return redirect(url_for('staff'))
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
        departments = Department.query.filter_by(is_active=True).all()
    else:
        schools_list = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        departments = Department.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    
    return render_template('edit_staff.html', staff=staff_member, schools=schools_list, departments=departments)

@app.route('/staff/<int:id>/delete')
@login_required
@role_required('super_admin', 'school_admin')
def delete_staff(id):
    staff_member = Staff.query.get_or_404(id)
    
    if current_user.role == 'school_admin':
        org_schools = School.query.filter_by(organization_id=current_user.organization_id).all()
        if staff_member.school_id not in [s.id for s in org_schools]:
            flash('Access denied.', 'danger')
            return redirect(url_for('staff'))
    
    staff_member.is_active = False
    db.session.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('staff'))

@app.route('/staff/bulk-upload', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'school_admin')
def bulk_upload_staff():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(url_for('bulk_upload_staff'))
        
        file = request.files['file']
        school_id = request.form.get('school_id')
        
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(url_for('bulk_upload_staff'))
        
        if file and file.filename.endswith('.csv'):
            try:
                stream = io.StringIO(file.stream.read().decode('UTF8'), newline=None)
                csv_reader = csv.DictReader(stream)
                
                added = 0
                skipped = 0
                
                for row in csv_reader:
                    sid = row.get('staff_id', '').strip()
                    name = row.get('name', '').strip()
                    department = row.get('department', '').strip()
                    position = row.get('position', '').strip()
                    
                    if not sid or not name:
                        skipped += 1
                        continue
                    
                    existing = Staff.query.filter_by(staff_id=sid).first()
                    if existing:
                        skipped += 1
                        continue
                    
                    staff_member = Staff(staff_id=sid, name=name, department=department,
                                        position=position, school_id=school_id)
                    db.session.add(staff_member)
                    added += 1
                
                db.session.commit()
                flash(f'Uploaded {added} staff. Skipped {skipped}.', 'success')
                return redirect(url_for('staff'))
            except Exception as e:
                flash(f'Error: {str(e)}', 'danger')
                return redirect(url_for('bulk_upload_staff'))
        else:
            flash('Please upload a CSV file', 'danger')
            return redirect(url_for('bulk_upload_staff'))
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
    else:
        schools_list = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
    
    return render_template('bulk_upload.html', schools=schools_list)

@app.route('/users')
@login_required
@role_required('super_admin')
def users():
    users_list = User.query.filter_by(is_active=True).all()
    return render_template('users.html', users=users_list)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_user():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        organization_id = request.form.get('organization_id') or None
        school_id = request.form.get('school_id') or None
        
        existing = User.query.filter((User.username==username) | (User.email==email)).first()
        if existing:
            flash('Username or email already exists!', 'danger')
            return redirect(url_for('add_user'))
        
        user = User(username=username, email=email, role=role,
                   organization_id=organization_id, school_id=school_id)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('User created successfully!', 'success')
        return redirect(url_for('users'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    schools_list = School.query.filter_by(is_active=True).all()
    return render_template('add_user.html', organizations=organizations, schools=schools_list)

@app.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_user(id):
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.email = request.form.get('email')
        user.role = request.form.get('role')
        user.organization_id = request.form.get('organization_id') or None
        user.school_id = request.form.get('school_id') or None
        
        new_password = request.form.get('password')
        if new_password:
            user.set_password(new_password)
        
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    schools_list = School.query.filter_by(is_active=True).all()
    return render_template('edit_user.html', user=user, organizations=organizations, schools=schools_list)

@app.route('/users/<int:id>/delete')
@login_required
@role_required('super_admin')
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('Cannot delete your own account!', 'danger')
        return redirect(url_for('users'))
    user.is_active = False
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('users'))

@app.route('/reports/attendance')
@login_required
def attendance_report():
    start_date = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    school_id = request.args.get('school_id', '')
    
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date)
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
    elif current_user.role in ['school_admin', 'hr_viewer'] and current_user.organization_id:
        org_schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in org_schools]
        query = query.filter(Attendance.school_id.in_(school_ids)) if school_ids else query.filter(False)
        schools_list = org_schools
    elif current_user.school_id:
        query = query.filter(Attendance.school_id == current_user.school_id)
        schools_list = School.query.filter_by(id=current_user.school_id).all()
    else:
        schools_list = []
    
    if school_id:
        query = query.filter(Attendance.school_id == school_id)
    
    records = query.order_by(Attendance.date.desc()).all()
    
    if request.args.get('download') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check In', 'Check Out', 'Status'])
        for record in records:
            writer.writerow([
                record.date.isoformat(),
                record.staff.staff_id,
                record.staff.name,
                record.school.name,
                record.check_in.strftime('%H:%M') if record.check_in else '-',
                record.check_out.strftime('%H:%M') if record.check_out else '-',
                record.status
            ])
        output.seek(0)
        return Response(output, mimetype='text/csv',
                       headers={'Content-Disposition': 'attachment;filename=attendance_report.csv'})
    
    return render_template('attendance_report.html', records=records, schools=schools_list,
                         start_date=start_date, end_date=end_date, selected_school=school_id)

@app.route('/reports/late')
@login_required
def late_report():
    start_date = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.status == 'late')
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
    elif current_user.role in ['school_admin', 'hr_viewer'] and current_user.organization_id:
        org_schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in org_schools]
        query = query.filter(Attendance.school_id.in_(school_ids)) if school_ids else query.filter(False)
        schools_list = org_schools
    else:
        schools_list = []
    
    records = query.order_by(Attendance.date.desc()).all()
    
    if request.args.get('download') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check In'])
        for record in records:
            writer.writerow([
                record.date.isoformat(),
                record.staff.staff_id,
                record.staff.name,
                record.school.name,
                record.check_in.strftime('%H:%M') if record.check_in else '-'
            ])
        output.seek(0)
        return Response(output, mimetype='text/csv',
                       headers={'Content-Disposition': 'attachment;filename=late_report.csv'})
    
    return render_template('late_report.html', records=records, schools=schools_list,
                         start_date=start_date, end_date=end_date)

@app.route('/reports/absent')
@login_required
def absent_report():
    start_date = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.status == 'absent')
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
    elif current_user.role in ['school_admin', 'hr_viewer'] and current_user.organization_id:
        org_schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in org_schools]
        query = query.filter(Attendance.school_id.in_(school_ids)) if school_ids else query.filter(False)
        schools_list = org_schools
    else:
        schools_list = []
    
    records = query.order_by(Attendance.date.desc()).all()
    
    if request.args.get('download') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch'])
        for record in records:
            writer.writerow([
                record.date.isoformat(),
                record.staff.staff_id,
                record.staff.name,
                record.school.name
            ])
        output.seek(0)
        return Response(output, mimetype='text/csv',
                       headers={'Content-Disposition': 'attachment;filename=absent_report.csv'})
    
    return render_template('absent_report.html', records=records, schools=schools_list,
                         start_date=start_date, end_date=end_date)

@app.route('/reports/overtime')
@login_required
def overtime_report():
    start_date = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    
    query = Attendance.query.filter(Attendance.date >= start_date, Attendance.date <= end_date, Attendance.check_out != None)
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
    elif current_user.role in ['school_admin', 'hr_viewer'] and current_user.organization_id:
        org_schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in org_schools]
        query = query.filter(Attendance.school_id.in_(school_ids)) if school_ids else query.filter(False)
        schools_list = org_schools
    else:
        schools_list = []
    
    all_records = query.order_by(Attendance.date.desc()).all()
    
    from datetime import time
    overtime_cutoff = time(17, 0)
    records = [r for r in all_records if r.check_out and r.check_out > overtime_cutoff]
    
    if request.args.get('download') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Staff ID', 'Name', 'Branch', 'Check Out', 'Overtime Hours'])
        for record in records:
            overtime_mins = (record.check_out.hour * 60 + record.check_out.minute) - (17 * 60)
            overtime_hrs = round(overtime_mins / 60, 2)
            writer.writerow([
                record.date.isoformat(),
                record.staff.staff_id,
                record.staff.name,
                record.school.name,
                record.check_out.strftime('%H:%M'),
                overtime_hrs
            ])
        output.seek(0)
        return Response(output, mimetype='text/csv',
                       headers={'Content-Disposition': 'attachment;filename=overtime_report.csv'})
    
    return render_template('overtime_report.html', records=records, schools=schools_list,
                         start_date=start_date, end_date=end_date)

@app.route('/reports/analytics')
@login_required
def analytics():
    start_date = request.args.get('start_date', (date.today() - timedelta(days=30)).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
        school_ids = [s.id for s in schools_list]
    elif current_user.role in ['school_admin', 'hr_viewer', 'ceo_viewer'] and current_user.organization_id:
        schools_list = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in schools_list]
    else:
        schools_list = []
        school_ids = []
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).count() if school_ids else 0
    
    attendance_records = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all() if school_ids else []
    
    total_records = len(attendance_records)
    present_count = len([r for r in attendance_records if r.status == 'present'])
    late_count = len([r for r in attendance_records if r.status == 'late'])
    absent_count = len([r for r in attendance_records if r.status == 'absent'])
    
    attendance_rate = round((present_count + late_count) / total_records * 100, 1) if total_records > 0 else 0
    
    branch_stats = []
    for school in schools_list:
        school_records = [r for r in attendance_records if r.school_id == school.id]
        school_present = len([r for r in school_records if r.status in ['present', 'late']])
        school_total = len(school_records)
        rate = round(school_present / school_total * 100, 1) if school_total > 0 else 0
        branch_stats.append({'name': school.name, 'total': school_total, 'present': school_present, 'rate': rate})
    
    branch_stats.sort(key=lambda x: x['rate'], reverse=True)
    
    return render_template('analytics.html', total_staff=total_staff, attendance_rate=attendance_rate,
                         present_count=present_count, late_count=late_count, absent_count=absent_count,
                         branch_stats=branch_stats, start_date=start_date, end_date=end_date)

@app.route('/reports/analytics/pdf')
@login_required
def analytics_pdf():
    start_date = request.args.get('start_date', (date.today() - timedelta(days=30)).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    
    if current_user.role == 'super_admin':
        schools_list = School.query.filter_by(is_active=True).all()
        school_ids = [s.id for s in schools_list]
    elif current_user.role in ['school_admin', 'hr_viewer', 'ceo_viewer'] and current_user.organization_id:
        schools_list = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        school_ids = [s.id for s in schools_list]
    else:
        schools_list = []
        school_ids = []
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).count() if school_ids else 0
    
    attendance_records = Attendance.query.filter(
        Attendance.school_id.in_(school_ids),
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all() if school_ids else []
    
    total_records = len(attendance_records)
    present_count = len([r for r in attendance_records if r.status == 'present'])
    late_count = len([r for r in attendance_records if r.status == 'late'])
    absent_count = len([r for r in attendance_records if r.status == 'absent'])
    
    attendance_rate = round((present_count + late_count) / total_records * 100, 1) if total_records > 0 else 0
    
    branch_stats = []
    for school in schools_list:
        school_records = [r for r in attendance_records if r.school_id == school.id]
        school_present = len([r for r in school_records if r.status in ['present', 'late']])
        school_total = len(school_records)
        rate = round(school_present / school_total * 100, 1) if school_total > 0 else 0
        branch_stats.append({'name': school.name, 'total': school_total, 'present': school_present, 'rate': rate})
    
    settings_obj = SystemSettings.query.first()
    company_name = settings_obj.company_name if settings_obj else 'Attendance System'
    
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #007bff; color: white; }}
            tr:nth-child(even) {{ background-color: #f8f9fa; }}
        </style>
    </head>
    <body>
        <h1>{company_name} - Analytics Report</h1>
        <p>Period: {start_date} to {end_date}</p>
        <h2>Summary</h2>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Total Staff</td><td>{total_staff}</td></tr>
            <tr><td>Attendance Rate</td><td>{attendance_rate}%</td></tr>
            <tr><td>Present</td><td>{present_count}</td></tr>
            <tr><td>Late</td><td>{late_count}</td></tr>
            <tr><td>Absent</td><td>{absent_count}</td></tr>
        </table>
        <h2>Branch Performance</h2>
        <table>
            <tr><th>Branch</th><th>Total</th><th>Present</th><th>Rate</th></tr>
    '''
    for b in branch_stats:
        html += f"<tr><td>{b['name']}</td><td>{b['total']}</td><td>{b['present']}</td><td>{b['rate']}%</td></tr>"
    html += f'</table><p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p></body></html>'
    
    pdf_buffer = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=pdf_buffer)
    pdf_buffer.seek(0)
    
    return Response(pdf_buffer, mimetype='application/pdf',
                   headers={'Content-Disposition': f'attachment;filename=analytics_{start_date}_{end_date}.pdf'})

@app.route('/api/sync', methods=['POST'])
def api_sync():
    api_key = request.headers.get('X-API-Key')
    settings_obj = SystemSettings.query.first()
    
    if not settings_obj or not settings_obj.api_key or api_key != settings_obj.api_key:
        return jsonify({'error': 'Invalid API key'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400
    
    records = data.get('records', [])
    synced = 0
    errors = []
    
    for record in records:
        try:
            staff_member = Staff.query.filter_by(staff_id=record.get('staff_id')).first()
            if not staff_member:
                errors.append(f"Staff {record.get('staff_id')} not found")
                continue
            
            record_date = datetime.strptime(record.get('date'), '%Y-%m-%d').date()
            existing = Attendance.query.filter_by(staff_id=staff_member.id, date=record_date).first()
            
            check_in = datetime.strptime(record.get('check_in'), '%H:%M').time() if record.get('check_in') else None
            check_out = datetime.strptime(record.get('check_out'), '%H:%M').time() if record.get('check_out') else None
            
            from datetime import time
            late_time = time(8, 15)
            status = 'late' if check_in and check_in > late_time else 'present'
            
            if existing:
                existing.check_in = check_in or existing.check_in
                existing.check_out = check_out or existing.check_out
                existing.status = status
            else:
                attendance = Attendance(staff_id=staff_member.id, school_id=staff_member.school_id,
                                       date=record_date, check_in=check_in, check_out=check_out, status=status)
                db.session.add(attendance)
            synced += 1
        except Exception as e:
            errors.append(str(e))
    
    db.session.commit()
    return jsonify({'success': True, 'synced': synced, 'errors': errors})

@app.route('/init-db')
def init_db():
    db.create_all()
    
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', email='admin@example.com', role='super_admin')
        admin.set_password('admin123')
        db.session.add(admin)
    
    settings_obj = SystemSettings.query.first()
    if not settings_obj:
        settings_obj = SystemSettings(company_name='Attendance System', api_key=secrets.token_hex(32))
        db.session.add(settings_obj)
    
    db.session.commit()
    return 'Database initialized! <a href="/login">Go to Login</a>'

@app.route('/migrate-departments')
def migrate_departments():
    try:
        from sqlalchemy import text
        results = []
        
        columns_to_add = [
            ("\"user\"", "organization_id", "INTEGER"),
            ("\"user\"", "school_id", "INTEGER"),
            ("\"user\"", "is_active", "BOOLEAN DEFAULT TRUE"),
            ("\"user\"", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("organization", "logo_url", "VARCHAR(500)"),
            ("organization", "is_school", "BOOLEAN DEFAULT TRUE"),
            ("organization", "is_active", "BOOLEAN DEFAULT TRUE"),
            ("organization", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("school", "address", "VARCHAR(200)"),
            ("school", "is_active", "BOOLEAN DEFAULT TRUE"),
            ("school", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("staff", "department", "VARCHAR(100)"),
            ("staff", "position", "VARCHAR(100)"),
            ("staff", "is_active", "BOOLEAN DEFAULT TRUE"),
            ("staff", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("attendance", "school_id", "INTEGER"),
            ("attendance", "check_in", "TIME"),
            ("attendance", "check_out", "TIME"),
            ("attendance", "status", "VARCHAR(20) DEFAULT 'present'"),
            ("attendance", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("system_settings", "company_logo_url", "VARCHAR(500)"),
            ("system_settings", "api_key", "VARCHAR(100)"),
            ("system_settings", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]
        
        for table, column, col_type in columns_to_add:
            try:
                db.session.execute(text(f"SELECT {column} FROM {table} LIMIT 1"))
                results.append(f"✓ {table}.{column} exists")
            except:
                db.session.rollback()
                try:
                    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                    db.session.commit()
                    results.append(f"✚ Added {table}.{column}")
                except Exception as e:
                    db.session.rollback()
                    results.append(f"✗ Error {table}.{column}: {str(e)[:50]}")
        
        try:
            db.session.execute(text("SELECT id FROM department LIMIT 1"))
            results.append("✓ department table exists")
        except:
            db.session.rollback()
            try:
                db.session.execute(text("""
                    CREATE TABLE department (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        organization_id INTEGER,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                db.session.commit()
                results.append("✚ Created department table")
            except Exception as e:
                db.session.rollback()
                results.append(f"✗ Department table error: {str(e)[:50]}")
        
        try:
            db.session.execute(text("UPDATE \"user\" SET is_active = TRUE WHERE is_active IS NULL"))
            db.session.execute(text("UPDATE organization SET is_active = TRUE WHERE is_active IS NULL"))
            db.session.execute(text("UPDATE organization SET is_school = TRUE WHERE is_school IS NULL"))
            db.session.execute(text("UPDATE school SET is_active = TRUE WHERE is_active IS NULL"))
            db.session.execute(text("UPDATE staff SET is_active = TRUE WHERE is_active IS NULL"))
            db.session.execute(text("UPDATE attendance SET status = 'present' WHERE status IS NULL"))
            db.session.commit()
            results.append("✓ Set default values")
        except Exception as e:
            db.session.rollback()
            results.append(f"✗ Defaults error: {str(e)[:50]}")
        
        try:
            db.session.execute(text("""
                UPDATE attendance 
                SET school_id = staff.school_id 
                FROM staff 
                WHERE attendance.staff_id = staff.id 
                AND attendance.school_id IS NULL
            """))
            db.session.commit()
            results.append("✓ Updated attendance school_id from staff")
        except Exception as e:
            db.session.rollback()
            results.append(f"Note: attendance school_id update: {str(e)[:50]}")
        
        try:
            orgs = Organization.query.all()
            added_depts = 0
            for org in orgs:
                if Department.query.filter_by(organization_id=org.id).count() == 0:
                    depts = ['Academic', 'Non-Academic', 'Administration', 'Support Staff'] if org.is_school else ['Operations', 'Finance', 'HR', 'IT', 'Marketing', 'Admin']
                    for d in depts:
                        db.session.add(Department(name=d, organization_id=org.id))
                        added_depts += 1
            db.session.commit()
            results.append(f"✓ Added {added_depts} default departments")
        except Exception as e:
            db.session.rollback()
            results.append(f"✗ Departments error: {str(e)[:50]}")
        
        html = '<h2>Migration Results:</h2><ul style="font-family: monospace;">'
        for r in results:
            color = 'green' if r.startswith('✓') or r.startswith('✚') else 'red' if r.startswith('✗') else 'orange'
            html += f'<li style="color: {color};">{r}</li>'
        html += '</ul><br><a href="/login" style="font-size: 18px;">Go to Login</a>'
        return html
    
    except Exception as e:
        db.session.rollback()
        return f'Migration error: {str(e)}'

if __name__ == '__main__':
    app.run(debug=True)
