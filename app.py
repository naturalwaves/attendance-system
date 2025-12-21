from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import csv
import io
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Models
class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default='Attendance System')
    logo_url = db.Column(db.String(500), default='')

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    logo_url = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', backref='organization', lazy=True, cascade='all, delete-orphan')
    departments = db.relationship('Department', backref='organization', lazy=True, cascade='all, delete-orphan')

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500))
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    schedule_in = db.Column(db.String(10), default='08:00')
    schedule_out = db.Column(db.String(10), default='17:00')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True, cascade='all, delete-orphan')
    users = db.relationship('User', backref='school', lazy=True)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='school_admin')
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=True)
    allowed_schools = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def get_accessible_schools(self):
        if self.role == 'super_admin':
            return School.query.all()
        if self.allowed_schools:
            school_ids = [int(id.strip()) for id in self.allowed_schools.split(',') if id.strip()]
            return School.query.filter(School.id.in_(school_ids)).all()
        if self.school_id:
            return [self.school]
        return []
    
    def get_accessible_school_ids(self):
        return [s.id for s in self.get_accessible_schools()]
    
    def can_access_school(self, school_id):
        if self.role == 'super_admin':
            return True
        return school_id in self.get_accessible_school_ids()

class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    department = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance_records = db.relationship('Attendance', backref='staff', lazy=True, cascade='all, delete-orphan')
    
    __table_args__ = (
        db.Index('idx_staff_id_school', 'staff_id', 'school_id'),
    )

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    sign_in_time = db.Column(db.DateTime)
    sign_out_time = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='present')
    is_late = db.Column(db.Boolean, default=False)
    late_reset = db.Column(db.Boolean, default=False)
    overtime_minutes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            flash('Access denied. Super admin privileges required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def get_settings():
    settings = SystemSettings.query.first()
    if not settings:
        settings = SystemSettings(company_name='Attendance System', logo_url='')
        db.session.add(settings)
        db.session.commit()
    return settings

def is_staff_id_unique_in_org(staff_id, organization_id, exclude_staff_id=None):
    query = Staff.query.join(School).filter(
        Staff.staff_id == staff_id,
        School.organization_id == organization_id
    )
    if exclude_staff_id:
        query = query.filter(Staff.id != exclude_staff_id)
    return query.first() is None

# Routes
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
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    settings = get_settings()
    return render_template('dashboard.html', settings=settings)

@app.route('/api/dashboard-stats')
@login_required
def dashboard_stats():
    today = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
        total_staff = Staff.query.filter_by(is_active=True).count()
    else:
        schools = current_user.get_accessible_schools()
        school_ids = [s.id for s in schools]
        total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
    
    school_ids = [s.id for s in schools]
    
    present_today = Attendance.query.join(Staff).filter(
        Attendance.date == today,
        Staff.school_id.in_(school_ids),
        Staff.is_active == True
    ).distinct(Attendance.staff_id).count()
    
    late_today = Attendance.query.join(Staff).filter(
        Attendance.date == today,
        Attendance.is_late == True,
        Attendance.late_reset == False,
        Staff.school_id.in_(school_ids),
        Staff.is_active == True
    ).count()
    
    absent_today = total_staff - present_today
    
    first_checkin = Attendance.query.join(Staff).filter(
        Attendance.date == today,
        Staff.school_id.in_(school_ids)
    ).order_by(Attendance.sign_in_time.asc()).first()
    
    first_checkin_data = None
    if first_checkin:
        first_checkin_data = {
            'name': first_checkin.staff.name,
            'time': first_checkin.sign_in_time.strftime('%H:%M:%S'),
            'school': first_checkin.staff.school.name
        }
    
    recent_activity = []
    recent = Attendance.query.join(Staff).filter(
        Attendance.date == today,
        Staff.school_id.in_(school_ids)
    ).order_by(Attendance.created_at.desc()).limit(10).all()
    
    for r in recent:
        activity_type = 'sign_out' if r.sign_out_time and r.sign_out_time == r.created_at else 'sign_in'
        recent_activity.append({
            'name': r.staff.name,
            'action': 'signed out' if activity_type == 'sign_out' else 'signed in',
            'time': r.created_at.strftime('%H:%M'),
            'late': r.is_late if activity_type == 'sign_in' else False
        })
    
    branch_stats = []
    for school in schools:
        school_total = Staff.query.filter_by(school_id=school.id, is_active=True).count()
        school_present = Attendance.query.join(Staff).filter(
            Attendance.date == today,
            Staff.school_id == school.id,
            Staff.is_active == True
        ).distinct(Attendance.staff_id).count()
        school_late = Attendance.query.join(Staff).filter(
            Attendance.date == today,
            Attendance.is_late == True,
            Attendance.late_reset == False,
            Staff.school_id == school.id,
            Staff.is_active == True
        ).count()
        branch_stats.append({
            'name': school.name,
            'present': school_present,
            'total': school_total,
            'late': school_late,
            'rate': round((school_present / school_total * 100) if school_total > 0 else 0, 1)
        })
    
    return jsonify({
        'branches': len(schools),
        'total_staff': total_staff,
        'present': present_today,
        'late': late_today,
        'absent': absent_today,
        'first_checkin': first_checkin_data,
        'recent_activity': recent_activity,
        'branch_stats': branch_stats
    })

@app.route('/api/search-staff')
@login_required
def search_staff():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    
    if current_user.role == 'super_admin':
        staff = Staff.query.filter(
            Staff.is_active == True,
            (Staff.name.ilike(f'%{query}%') | Staff.staff_id.ilike(f'%{query}%'))
        ).limit(10).all()
    else:
        school_ids = current_user.get_accessible_school_ids()
        staff = Staff.query.filter(
            Staff.school_id.in_(school_ids),
            Staff.is_active == True,
            (Staff.name.ilike(f'%{query}%') | Staff.staff_id.ilike(f'%{query}%'))
        ).limit(10).all()
    
    today = datetime.now().date()
    results = []
    for s in staff:
        attendance = Attendance.query.filter_by(staff_id=s.id, date=today).first()
        status = 'absent'
        if attendance:
            if attendance.sign_out_time:
                status = 'signed_out'
            else:
                status = 'late' if attendance.is_late else 'present'
        results.append({
            'id': s.id,
            'staff_id': s.staff_id,
            'name': s.name,
            'school': s.school.name,
            'department': s.department,
            'status': status
        })
    
    return jsonify(results)

@app.route('/staff')
@login_required
def staff_list():
    organization_id = request.args.get('organization_id', type=int)
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
        
        if organization_id:
            school_ids = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
            staff = Staff.query.filter(Staff.school_id.in_(school_ids)).all() if school_ids else []
            schools = School.query.filter_by(organization_id=organization_id).all()
        else:
            staff = Staff.query.all()
            schools = School.query.all()
    else:
        organizations = []
        schools = current_user.get_accessible_schools()
        school_ids = [s.id for s in schools]
        staff = Staff.query.filter(Staff.school_id.in_(school_ids)).all()
    
    return render_template('staff.html', 
                          staff=staff, 
                          schools=schools, 
                          organizations=organizations,
                          selected_organization=organization_id)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
def add_staff():
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
        schools = School.query.all()
    else:
        organizations = []
        schools = current_user.get_accessible_schools()
    
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        name = request.form.get('name')
        school_id = int(request.form.get('school_id'))
        department = request.form.get('department')
        
        if not current_user.can_access_school(school_id):
            flash('Access denied to this branch.', 'danger')
            return redirect(url_for('staff_list'))
        
        school = School.query.get(school_id)
        if not school:
            flash('Invalid branch selected.', 'danger')
            return redirect(url_for('add_staff'))
        
        if not is_staff_id_unique_in_org(staff_id, school.organization_id):
            flash(f'Staff ID "{staff_id}" already exists in this organization.', 'danger')
            return redirect(url_for('add_staff'))
        
        staff = Staff(
            staff_id=staff_id,
            name=name,
            school_id=school_id,
            department=department
        )
        db.session.add(staff)
        db.session.commit()
        flash('Staff added successfully!', 'success')
        return redirect(url_for('staff_list'))
    
    return render_template('add_staff.html', schools=schools, organizations=organizations)

@app.route('/staff/edit/<int:id>', methods=['POST'])
@login_required
def edit_staff(id):
    staff = Staff.query.get_or_404(id)
    
    if not current_user.can_access_school(staff.school_id):
        flash('Access denied.', 'danger')
        return redirect(url_for('staff_list'))
    
    new_staff_id = request.form.get('staff_id')
    new_school_id = int(request.form.get('school_id'))
    
    if not current_user.can_access_school(new_school_id):
        flash('Access denied to this branch.', 'danger')
        return redirect(url_for('staff_list'))
    
    new_school = School.query.get(new_school_id)
    if not new_school:
        flash('Invalid branch selected.', 'danger')
        return redirect(url_for('staff_list'))
    
    if not is_staff_id_unique_in_org(new_staff_id, new_school.organization_id, exclude_staff_id=id):
        flash(f'Staff ID "{new_staff_id}" already exists in this organization.', 'danger')
        return redirect(url_for('staff_list'))
    
    staff.staff_id = new_staff_id
    staff.name = request.form.get('name')
    staff.school_id = new_school_id
    staff.department = request.form.get('department')
    staff.is_active = request.form.get('is_active') == 'on'
    
    db.session.commit()
    flash('Staff updated successfully!', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/toggle/<int:id>')
@login_required
def toggle_staff(id):
    staff = Staff.query.get_or_404(id)
    
    if not current_user.can_access_school(staff.school_id):
        flash('Access denied.', 'danger')
        return redirect(url_for('staff_list'))
    
    staff.is_active = not staff.is_active
    db.session.commit()
    status = 'activated' if staff.is_active else 'deactivated'
    flash(f'Staff {status} successfully!', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/delete/<int:id>')
@login_required
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    
    if not current_user.can_access_school(staff.school_id):
        flash('Access denied.', 'danger')
        return redirect(url_for('staff_list'))
    
    db.session.delete(staff)
    db.session.commit()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('staff_list'))

@app.route('/staff/bulk-upload', methods=['GET', 'POST'])
@login_required
def bulk_upload():
    schools = current_user.get_accessible_schools()
    
    if request.method == 'POST':
        school_id = int(request.form.get('school_id'))
        
        if not current_user.can_access_school(school_id):
            flash('Access denied to this branch.', 'danger')
            return redirect(url_for('bulk_upload'))
        
        school = School.query.get(school_id)
        if not school:
            flash('Invalid branch selected.', 'danger')
            return redirect(url_for('bulk_upload'))
        
        file = request.files.get('file')
        if not file:
            flash('No file uploaded.', 'danger')
            return redirect(url_for('bulk_upload'))
        
        try:
            stream = io.StringIO(file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)
            
            added = 0
            skipped = 0
            errors = []
            
            for row in reader:
                staff_id = row.get('staff_id', '').strip()
                name = row.get('name', '').strip()
                department = row.get('department', '').strip()
                
                if not staff_id or not name:
                    skipped += 1
                    continue
                
                if not is_staff_id_unique_in_org(staff_id, school.organization_id):
                    errors.append(f'Staff ID "{staff_id}" already exists')
                    skipped += 1
                    continue
                
                staff = Staff(
                    staff_id=staff_id,
                    name=name,
                    department=department,
                    school_id=school_id
                )
                db.session.add(staff)
                added += 1
            
            db.session.commit()
            
            if errors:
                flash(f'Added {added} staff. Skipped {skipped}: {"; ".join(errors[:5])}', 'warning')
            else:
                flash(f'Successfully added {added} staff members!', 'success')
                
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'danger')
        
        return redirect(url_for('staff_list'))
    
    return render_template('bulk_upload.html', schools=schools)

@app.route('/schools')
@login_required
@super_admin_required
def schools():
    organizations = Organization.query.all()
    schools = School.query.all()
    return render_template('schools.html', schools=schools, organizations=organizations)

@app.route('/schools/add', methods=['POST'])
@login_required
@super_admin_required
def add_school():
    name = request.form.get('name')
    address = request.form.get('address')
    organization_id = request.form.get('organization_id')
    schedule_in = request.form.get('schedule_in', '08:00')
    schedule_out = request.form.get('schedule_out', '17:00')
    
    school = School(
        name=name, 
        address=address, 
        organization_id=organization_id,
        schedule_in=schedule_in,
        schedule_out=schedule_out
    )
    db.session.add(school)
    db.session.commit()
    flash('Branch added successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/schools/edit/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def edit_school(id):
    school = School.query.get_or_404(id)
    school.name = request.form.get('name')
    school.address = request.form.get('address')
    school.organization_id = request.form.get('organization_id')
    school.schedule_in = request.form.get('schedule_in', '08:00')
    school.schedule_out = request.form.get('schedule_out', '17:00')
    db.session.commit()
    flash('Branch updated successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/schools/delete/<int:id>')
@login_required
@super_admin_required
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('Branch deleted successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/users')
@login_required
@super_admin_required
def users():
    users = User.query.all()
    schools = School.query.all()
    return render_template('users.html', users=users, schools=schools)

@app.route('/users/add', methods=['POST'])
@login_required
@super_admin_required
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role')
    school_ids = request.form.getlist('school_ids')
    
    if User.query.filter_by(username=username).first():
        flash('Username already exists!', 'danger')
        return redirect(url_for('users'))
    
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role=role
    )
    
    if role == 'school_admin' and school_ids:
        user.allowed_schools = ','.join(school_ids)
        if len(school_ids) == 1:
            user.school_id = int(school_ids[0])
    
    db.session.add(user)
    db.session.commit()
    flash('User added successfully!', 'success')
    return redirect(url_for('users'))

@app.route('/users/edit/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    user.username = request.form.get('username')
    user.role = request.form.get('role')
    school_ids = request.form.getlist('school_ids')
    
    if request.form.get('password'):
        user.password_hash = generate_password_hash(request.form.get('password'))
    
    if user.role == 'school_admin' and school_ids:
        user.allowed_schools = ','.join(school_ids)
        if len(school_ids) == 1:
            user.school_id = int(school_ids[0])
        else:
            user.school_id = None
    else:
        user.allowed_schools = None
        user.school_id = None
    
    db.session.commit()
    flash('User updated successfully!', 'success')
    return redirect(url_for('users'))

@app.route('/users/delete/<int:id>')
@login_required
@super_admin_required
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('Cannot delete your own account!', 'danger')
        return redirect(url_for('users'))
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('users'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@super_admin_required
def settings():
    settings = get_settings()
    organizations = Organization.query.all()
    
    if request.method == 'POST':
        settings.company_name = request.form.get('company_name')
        settings.logo_url = request.form.get('logo_url', '')
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    return render_template('settings.html', settings=settings, organizations=organizations)

@app.route('/organizations/add', methods=['POST'])
@login_required
@super_admin_required
def add_organization():
    name = request.form.get('name')
    logo_url = request.form.get('logo_url', '')
    
    org = Organization(name=name, logo_url=logo_url)
    db.session.add(org)
    db.session.flush()
    
    default_departments = ['Academic', 'Non-Academic', 'Administrative', 'Support Staff']
    for dept_name in default_departments:
        dept = Department(name=dept_name, organization_id=org.id)
        db.session.add(dept)
    
    db.session.commit()
    flash('Organization added successfully with default departments!', 'success')
    return redirect(url_for('settings'))

@app.route('/organizations/edit/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    org.name = request.form.get('name')
    org.logo_url = request.form.get('logo_url', '')
    db.session.commit()
    flash('Organization updated successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/organizations/delete/<int:id>')
@login_required
@super_admin_required
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    if org.schools:
        flash('Cannot delete organization with existing branches!', 'danger')
        return redirect(url_for('settings'))
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/departments/<int:org_id>')
@login_required
@super_admin_required
def manage_departments(org_id):
    organization = Organization.query.get_or_404(org_id)
    departments = Department.query.filter_by(organization_id=org_id).all()
    
    dept_staff_counts = {}
    for dept in departments:
        count = Staff.query.join(School).filter(
            School.organization_id == org_id,
            Staff.department == dept.name
        ).count()
        dept_staff_counts[dept.id] = count
    
    return render_template('manage_departments.html', 
                         organization=organization, 
                         departments=departments,
                         dept_staff_counts=dept_staff_counts)

@app.route('/departments/<int:org_id>/add', methods=['POST'])
@login_required
@super_admin_required
def add_department(org_id):
    name = request.form.get('name')
    if name:
        dept = Department(name=name, organization_id=org_id)
        db.session.add(dept)
        db.session.commit()
        flash('Department added successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))

@app.route('/departments/edit/<int:id>', methods=['POST'])
@login_required
@super_admin_required
def edit_department(id):
    dept = Department.query.get_or_404(id)
    old_name = dept.name
    new_name = request.form.get('name')
    
    if new_name:
        Staff.query.join(School).filter(
            School.organization_id == dept.organization_id,
            Staff.department == old_name
        ).update({Staff.department: new_name}, synchronize_session=False)
        
        dept.name = new_name
        db.session.commit()
        flash('Department updated successfully!', 'success')
    
    return redirect(url_for('manage_departments', org_id=dept.organization_id))

@app.route('/departments/delete/<int:id>')
@login_required
@super_admin_required
def delete_department(id):
    dept = Department.query.get_or_404(id)
    org_id = dept.organization_id
    
    staff_count = Staff.query.join(School).filter(
        School.organization_id == org_id,
        Staff.department == dept.name
    ).count()
    
    if staff_count > 0:
        flash(f'Cannot delete department with {staff_count} staff assigned!', 'danger')
    else:
        db.session.delete(dept)
        db.session.commit()
        flash('Department deleted successfully!', 'success')
    
    return redirect(url_for('manage_departments', org_id=org_id))

@app.route('/api/branch-departments/<int:branch_id>')
@login_required
def get_branch_departments(branch_id):
    school = School.query.get_or_404(branch_id)
    departments = Department.query.filter_by(organization_id=school.organization_id).all()
    return jsonify([{'id': d.id, 'name': d.name} for d in departments])

@app.route('/api/organization-branches/<int:org_id>')
@login_required
def get_organization_branches(org_id):
    if current_user.role == 'super_admin':
        branches = School.query.filter_by(organization_id=org_id).all()
    else:
        accessible_ids = current_user.get_accessible_school_ids()
        branches = School.query.filter(
            School.organization_id == org_id,
            School.id.in_(accessible_ids)
        ).all()
    return jsonify([{'id': b.id, 'name': b.name} for b in branches])

@app.route('/reports/attendance', methods=['GET'])
@login_required
def attendance_report():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    school_id = request.args.get('school_id', type=int)
    
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        report_date = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    
    school_ids = [s.id for s in schools]
    
    if school_id and school_id in school_ids:
        school_ids = [school_id]
    
    records = Attendance.query.join(Staff).filter(
        Attendance.date == report_date,
        Staff.school_id.in_(school_ids)
    ).all()
    
    if request.args.get('download') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Staff ID', 'Name', 'Branch', 'Department', 'Sign In', 'Sign Out', 'Status', 'Late'])
        for r in records:
            writer.writerow([
                r.staff.staff_id,
                r.staff.name,
                r.staff.school.name,
                r.staff.department,
                r.sign_in_time.strftime('%H:%M:%S') if r.sign_in_time else '',
                r.sign_out_time.strftime('%H:%M:%S') if r.sign_out_time else '',
                r.status,
                'Yes' if r.is_late and not r.late_reset else 'No'
            ])
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment;filename=attendance_{date_str}.csv'}
        )
    
    return render_template('attendance_report.html', 
                         records=records, 
                         report_date=report_date,
                         schools=schools,
                         selected_school=school_id)

@app.route('/reports/late', methods=['GET'])
@login_required
def late_report():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    school_id = request.args.get('school_id', type=int)
    
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        report_date = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    
    school_ids = [s.id for s in schools]
    
    if school_id and school_id in school_ids:
        school_ids = [school_id]
    
    records = Attendance.query.join(Staff).filter(
        Attendance.date == report_date,
        Attendance.is_late == True,
        Attendance.late_reset == False,
        Staff.school_id.in_(school_ids)
    ).all()
    
    if request.args.get('download') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Staff ID', 'Name', 'Branch', 'Department', 'Sign In Time', 'Expected Time'])
        for r in records:
            writer.writerow([
                r.staff.staff_id,
                r.staff.name,
                r.staff.school.name,
                r.staff.department,
                r.sign_in_time.strftime('%H:%M:%S') if r.sign_in_time else '',
                r.staff.school.schedule_in
            ])
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment;filename=late_report_{date_str}.csv'}
        )
    
    return render_template('late_report.html', 
                         records=records, 
                         report_date=report_date,
                         schools=schools,
                         selected_school=school_id)

@app.route('/reports/late/reset/<int:id>')
@login_required
def reset_late(id):
    record = Attendance.query.get_or_404(id)
    
    if not current_user.can_access_school(record.staff.school_id):
        flash('Access denied.', 'danger')
        return redirect(url_for('late_report'))
    
    record.late_reset = True
    db.session.commit()
    flash('Late status reset successfully!', 'success')
    return redirect(url_for('late_report'))

@app.route('/reports/absent', methods=['GET'])
@login_required
def absent_report():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    school_id = request.args.get('school_id', type=int)
    
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        report_date = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    
    school_ids = [s.id for s in schools]
    
    if school_id and school_id in school_ids:
        filter_school_ids = [school_id]
    else:
        filter_school_ids = school_ids
    
    present_staff_ids = db.session.query(Attendance.staff_id).filter(
        Attendance.date == report_date
    ).subquery()
    
    absent_staff = Staff.query.filter(
        Staff.school_id.in_(filter_school_ids),
        Staff.is_active == True,
        ~Staff.id.in_(present_staff_ids)
    ).all()
    
    if request.args.get('download') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Staff ID', 'Name', 'Branch', 'Department'])
        for s in absent_staff:
            writer.writerow([s.staff_id, s.name, s.school.name, s.department])
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment;filename=absent_report_{date_str}.csv'}
        )
    
    return render_template('absent_report.html', 
                         staff=absent_staff, 
                         report_date=report_date,
                         schools=schools,
                         selected_school=school_id)

@app.route('/reports/overtime', methods=['GET'])
@login_required
def overtime_report():
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    school_id = request.args.get('school_id', type=int)
    
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        report_date = datetime.now().date()
    
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    
    school_ids = [s.id for s in schools]
    
    if school_id and school_id in school_ids:
        school_ids = [school_id]
    
    records = Attendance.query.join(Staff).filter(
        Attendance.date == report_date,
        Attendance.overtime_minutes > 0,
        Staff.school_id.in_(school_ids)
    ).all()
    
    if request.args.get('download') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Staff ID', 'Name', 'Branch', 'Department', 'Sign Out', 'Expected Out', 'Overtime (mins)'])
        for r in records:
            writer.writerow([
                r.staff.staff_id,
                r.staff.name,
                r.staff.school.name,
                r.staff.department,
                r.sign_out_time.strftime('%H:%M:%S') if r.sign_out_time else '',
                r.staff.school.schedule_out,
                r.overtime_minutes
            ])
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment;filename=overtime_report_{date_str}.csv'}
        )
    
    return render_template('overtime_report.html', 
                         records=records, 
                         report_date=report_date,
                         schools=schools,
                         selected_school=school_id)

@app.route('/analytics')
@login_required
def analytics():
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = current_user.get_accessible_schools()
    
    school_ids = [s.id for s in schools]
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count()
    
    attendance_records = Attendance.query.join(Staff).filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Staff.school_id.in_(school_ids)
    ).all()
    
    total_possible = total_staff * 30
    total_present = len(attendance_records)
    attendance_rate = round((total_present / total_possible * 100) if total_possible > 0 else 0, 1)
    
    late_records = [r for r in attendance_records if r.is_late and not r.late_reset]
    punctuality_rate = round(((total_present - len(late_records)) / total_present * 100) if total_present > 0 else 100, 1)
    
    daily_stats = {}
    for r in attendance_records:
        date_key = r.date.strftime('%Y-%m-%d')
        if date_key not in daily_stats:
            daily_stats[date_key] = {'present': 0, 'late': 0}
        daily_stats[date_key]['present'] += 1
        if r.is_late and not r.late_reset:
            daily_stats[date_key]['late'] += 1
    
    late_by_hour = {}
    for r in late_records:
        if r.sign_in_time:
            hour = r.sign_in_time.hour
            late_by_hour[hour] = late_by_hour.get(hour, 0) + 1
    
    peak_late_hour = max(late_by_hour, key=late_by_hour.get) if late_by_hour else None
    
    dept_stats = {}
    for r in attendance_records:
        dept = r.staff.department or 'Unknown'
        if dept not in dept_stats:
            dept_stats[dept] = {'present': 0, 'late': 0}
        dept_stats[dept]['present'] += 1
        if r.is_late and not r.late_reset:
            dept_stats[dept]['late'] += 1
    
    branch_performance = []
    for school in schools:
        school_records = [r for r in attendance_records if r.staff.school_id == school.id]
        school_staff = Staff.query.filter_by(school_id=school.id, is_active=True).count()
        school_possible = school_staff * 30
        school_rate = round((len(school_records) / school_possible * 100) if school_possible > 0 else 0, 1)
        branch_performance.append({
            'name': school.name,
            'rate': school_rate,
            'staff_count': school_staff
        })
    
    return render_template('analytics.html',
                         attendance_rate=attendance_rate,
                         punctuality_rate=punctuality_rate,
                         total_staff=total_staff,
                         daily_stats=daily_stats,
                         peak_late_hour=peak_late_hour,
                         dept_stats=dept_stats,
                         branch_performance=branch_performance,
                         schools=schools)

# API Routes for external device
@app.route('/api/staff', methods=['GET'])
def api_get_staff():
    api_key = request.headers.get('X-API-Key')
    if api_key != os.environ.get('API_KEY', 'default-api-key'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    school_id = request.args.get('school_id', type=int)
    
    query = Staff.query.filter_by(is_active=True)
    if school_id:
        query = query.filter_by(school_id=school_id)
    
    staff = query.all()
    
    return jsonify([{
        'id': s.id,
        'staff_id': s.staff_id,
        'name': s.name,
        'department': s.department,
        'school_id': s.school_id,
        'school_name': s.school.name
    } for s in staff])

@app.route('/api/attendance', methods=['POST'])
def api_record_attendance():
    api_key = request.headers.get('X-API-Key')
    if api_key != os.environ.get('API_KEY', 'default-api-key'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    staff_id = data.get('staff_id')
    action = data.get('action', 'sign_in')
    timestamp = data.get('timestamp')
    
    if timestamp:
        try:
            record_time = datetime.fromisoformat(timestamp)
        except:
            record_time = datetime.now()
    else:
        record_time = datetime.now()
    
    staff = Staff.query.filter_by(staff_id=staff_id, is_active=True).first()
    if not staff:
        return jsonify({'error': 'Staff not found'}), 404
    
    today = record_time.date()
    attendance = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
    
    if action == 'sign_in':
        if attendance:
            return jsonify({'error': 'Already signed in today', 'attendance_id': attendance.id}), 400
        
        schedule_in = datetime.strptime(staff.school.schedule_in, '%H:%M').time()
        is_late = record_time.time() > schedule_in
        
        attendance = Attendance(
            staff_id=staff.id,
            date=today,
            sign_in_time=record_time,
            status='present',
            is_late=is_late
        )
        db.session.add(attendance)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Sign in recorded',
            'attendance_id': attendance.id,
            'is_late': is_late,
            'time': record_time.strftime('%H:%M:%S')
        })
    
    elif action == 'sign_out':
        if not attendance:
            return jsonify({'error': 'No sign in record found for today'}), 400
        
        if attendance.sign_out_time:
            return jsonify({'error': 'Already signed out today'}), 400
        
        attendance.sign_out_time = record_time
        
        schedule_out = datetime.strptime(staff.school.schedule_out, '%H:%M').time()
        if record_time.time() > schedule_out:
            scheduled_out_dt = datetime.combine(today, schedule_out)
            overtime = (record_time - scheduled_out_dt).seconds // 60
            attendance.overtime_minutes = overtime
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Sign out recorded',
            'attendance_id': attendance.id,
            'overtime_minutes': attendance.overtime_minutes,
            'time': record_time.strftime('%H:%M:%S')
        })
    
    return jsonify({'error': 'Invalid action'}), 400

@app.route('/api/status/<staff_id>')
def api_staff_status(staff_id):
    api_key = request.headers.get('X-API-Key')
    if api_key != os.environ.get('API_KEY', 'default-api-key'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    staff = Staff.query.filter_by(staff_id=staff_id, is_active=True).first()
    if not staff:
        return jsonify({'error': 'Staff not found'}), 404
    
    today = datetime.now().date()
    attendance = Attendance.query.filter_by(staff_id=staff.id, date=today).first()
    
    status = 'not_signed_in'
    if attendance:
        if attendance.sign_out_time:
            status = 'signed_out'
        else:
            status = 'signed_in'
    
    return jsonify({
        'staff_id': staff.staff_id,
        'name': staff.name,
        'status': status,
        'sign_in_time': attendance.sign_in_time.strftime('%H:%M:%S') if attendance and attendance.sign_in_time else None,
        'sign_out_time': attendance.sign_out_time.strftime('%H:%M:%S') if attendance and attendance.sign_out_time else None,
        'is_late': attendance.is_late if attendance else None
    })

@app.route('/init-db')
def init_db():
    db.create_all()
    
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            password_hash=generate_password_hash('admin123'),
            role='super_admin'
        )
        db.session.add(admin)
    
    if not SystemSettings.query.first():
        settings = SystemSettings(company_name='Attendance System')
        db.session.add(settings)
    
    db.session.commit()
    return 'Database initialized! Default admin: admin/admin123'

# Auto-fix database on startup - adds missing columns
with app.app_context():
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text('ALTER TABLE "user" ADD COLUMN allowed_schools TEXT;'))
            conn.commit()
            print("Added allowed_schools column")
    except Exception as e:
        # Column already exists or other error - that's fine
        print(f"DB migration check: {e}")

if __name__ == '__main__':
    app.run(debug=True)
