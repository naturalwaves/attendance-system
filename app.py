from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import os
import csv
import io

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
class Organization(db.Model):
    __tablename__ = 'organizations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20))
    logo_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', backref='organization', lazy=True)
    users = db.relationship('User', backref='organization', lazy=True)

class SystemSettings(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(100), default='Wakato Technologies')
    company_logo_url = db.Column(db.String(500))

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20))
    logo_url = db.Column(db.String(500))
    address = db.Column(db.String(200))
    api_key = db.Column(db.String(64), unique=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    monday_start = db.Column(db.String(5), default='08:00')
    monday_end = db.Column(db.String(5), default='17:00')
    tuesday_start = db.Column(db.String(5), default='08:00')
    tuesday_end = db.Column(db.String(5), default='17:00')
    wednesday_start = db.Column(db.String(5), default='08:00')
    wednesday_end = db.Column(db.String(5), default='17:00')
    thursday_start = db.Column(db.String(5), default='08:00')
    thursday_end = db.Column(db.String(5), default='17:00')
    friday_start = db.Column(db.String(5), default='08:00')
    friday_end = db.Column(db.String(5), default='17:00')
    saturday_start = db.Column(db.String(5))
    saturday_end = db.Column(db.String(5))
    sunday_start = db.Column(db.String(5))
    sunday_end = db.Column(db.String(5))
    
    staff = db.relationship('Staff', backref='school', lazy=True)
    users = db.relationship('User', backref='school', lazy=True)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Staff(db.Model):
    __tablename__ = 'staff'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(50))
    position = db.Column(db.String(50))
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    times_late = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('staff_id', 'school_id', name='unique_staff_per_school'),)

class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    sign_in_time = db.Column(db.DateTime)
    sign_out_time = db.Column(db.DateTime)
    status = db.Column(db.String(20))
    late_minutes = db.Column(db.Integer, default=0)
    overtime_minutes = db.Column(db.Integer, default=0)
    
    staff = db.relationship('Staff', backref='attendance_records')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_user_schools():
    if current_user.role == 'super_admin':
        return School.query.all()
    elif current_user.role in ['org_admin', 'hr_viewer', 'ceo_viewer']:
        if current_user.organization_id:
            return School.query.filter_by(organization_id=current_user.organization_id).all()
        return []
    elif current_user.role == 'school_admin':
        if current_user.school_id:
            return School.query.filter_by(id=current_user.school_id).all()
        return []
    return []

def get_user_school_ids():
    schools = get_user_schools()
    return [s.id for s in schools]

def can_access_school(school_id):
    if current_user.role == 'super_admin':
        return True
    return school_id in get_user_school_ids()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role not in ['super_admin', 'org_admin', 'school_admin']:
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role != 'super_admin':
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def org_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role not in ['super_admin', 'org_admin']:
            flash('Access denied.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/init-db')
def init_db():
    results = []
    try:
        # Create all new tables
        db.create_all()
        results.append("Tables created")
        
        # List of all columns to add
        alter_statements = [
            ('users', 'created_at', 'ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT NOW()'),
            ('users', 'organization_id', 'ALTER TABLE users ADD COLUMN organization_id INTEGER'),
            ('schools', 'created_at', 'ALTER TABLE schools ADD COLUMN created_at TIMESTAMP DEFAULT NOW()'),
            ('schools', 'organization_id', 'ALTER TABLE schools ADD COLUMN organization_id INTEGER'),
            ('schools', 'logo_url', 'ALTER TABLE schools ADD COLUMN logo_url VARCHAR(500)'),
            ('schools', 'short_name', 'ALTER TABLE schools ADD COLUMN short_name VARCHAR(20)'),
            ('schools', 'address', 'ALTER TABLE schools ADD COLUMN address VARCHAR(200)'),
            ('schools', 'monday_start', 'ALTER TABLE schools ADD COLUMN monday_start VARCHAR(5) DEFAULT \'08:00\''),
            ('schools', 'monday_end', 'ALTER TABLE schools ADD COLUMN monday_end VARCHAR(5) DEFAULT \'17:00\''),
            ('schools', 'tuesday_start', 'ALTER TABLE schools ADD COLUMN tuesday_start VARCHAR(5) DEFAULT \'08:00\''),
            ('schools', 'tuesday_end', 'ALTER TABLE schools ADD COLUMN tuesday_end VARCHAR(5) DEFAULT \'17:00\''),
            ('schools', 'wednesday_start', 'ALTER TABLE schools ADD COLUMN wednesday_start VARCHAR(5) DEFAULT \'08:00\''),
            ('schools', 'wednesday_end', 'ALTER TABLE schools ADD COLUMN wednesday_end VARCHAR(5) DEFAULT \'17:00\''),
            ('schools', 'thursday_start', 'ALTER TABLE schools ADD COLUMN thursday_start VARCHAR(5) DEFAULT \'08:00\''),
            ('schools', 'thursday_end', 'ALTER TABLE schools ADD COLUMN thursday_end VARCHAR(5) DEFAULT \'17:00\''),
            ('schools', 'friday_start', 'ALTER TABLE schools ADD COLUMN friday_start VARCHAR(5) DEFAULT \'08:00\''),
            ('schools', 'friday_end', 'ALTER TABLE schools ADD COLUMN friday_end VARCHAR(5) DEFAULT \'17:00\''),
            ('schools', 'saturday_start', 'ALTER TABLE schools ADD COLUMN saturday_start VARCHAR(5)'),
            ('schools', 'saturday_end', 'ALTER TABLE schools ADD COLUMN saturday_end VARCHAR(5)'),
            ('schools', 'sunday_start', 'ALTER TABLE schools ADD COLUMN sunday_start VARCHAR(5)'),
            ('schools', 'sunday_end', 'ALTER TABLE schools ADD COLUMN sunday_end VARCHAR(5)'),
            ('staff', 'created_at', 'ALTER TABLE staff ADD COLUMN created_at TIMESTAMP DEFAULT NOW()'),
            ('staff', 'times_late', 'ALTER TABLE staff ADD COLUMN times_late INTEGER DEFAULT 0'),
            ('staff', 'position', 'ALTER TABLE staff ADD COLUMN position VARCHAR(50)'),
            ('staff', 'is_active', 'ALTER TABLE staff ADD COLUMN is_active BOOLEAN DEFAULT TRUE'),
            ('attendance_records', 'late_minutes', 'ALTER TABLE attendance_records ADD COLUMN late_minutes INTEGER DEFAULT 0'),
            ('attendance_records', 'overtime_minutes', 'ALTER TABLE attendance_records ADD COLUMN overtime_minutes INTEGER DEFAULT 0'),
        ]
        
        for table, column, statement in alter_statements:
            try:
                db.session.execute(db.text(statement))
                db.session.commit()
                results.append(f"Added {table}.{column}")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                    results.append(f"EXISTS: {table}.{column}")
                else:
                    results.append(f"FAILED {table}.{column}: {str(e)[:100]}")
        
        # Create system_settings if not exists
        try:
            if not SystemSettings.query.first():
                settings = SystemSettings(company_name='Wakato Technologies')
                db.session.add(settings)
                db.session.commit()
                results.append("Created system_settings")
            else:
                results.append("system_settings exists")
        except Exception as e:
            results.append(f"system_settings error: {str(e)[:50]}")
        
        # Create default admin if not exists
        try:
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', role='super_admin')
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.commit()
                results.append("Created admin user")
            else:
                results.append("admin user exists")
        except Exception as e:
            results.append(f"admin error: {str(e)[:50]}")
        
        return '<br>'.join(results)
    except Exception as e:
        return f'Error: {str(e)}<br><br>Results so far:<br>' + '<br>'.join(results)

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
    settings = SystemSettings.query.first()
    school_ids = get_user_school_ids()
    
    today = datetime.now().date()
    
    if current_user.role == 'super_admin':
        total_schools = School.query.count()
        total_organizations = Organization.query.count()
    elif current_user.role in ['org_admin', 'hr_viewer', 'ceo_viewer']:
        total_schools = len(school_ids)
        total_organizations = 1 if current_user.organization_id else 0
    else:
        total_schools = len(school_ids)
        total_organizations = 0
    
    total_staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True).count() if school_ids else 0
    
    present_today = AttendanceRecord.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        AttendanceRecord.date == today,
        AttendanceRecord.sign_in_time.isnot(None)
    ).count() if school_ids else 0
    
    late_today = AttendanceRecord.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        AttendanceRecord.date == today,
        AttendanceRecord.status == 'late'
    ).count() if school_ids else 0
    
    absent_today = total_staff - present_today if total_staff > 0 else 0
    
    recent_activity = AttendanceRecord.query.join(Staff).filter(
        Staff.school_id.in_(school_ids)
    ).order_by(AttendanceRecord.id.desc()).limit(10).all() if school_ids else []
    
    return render_template('dashboard.html', 
                         settings=settings,
                         total_schools=total_schools,
                         total_organizations=total_organizations,
                         total_staff=total_staff,
                         present_today=present_today,
                         late_today=late_today,
                         absent_today=absent_today,
                         recent_activity=recent_activity)

@app.route('/organizations')
@login_required
@super_admin_required
def organizations():
    settings = SystemSettings.query.first()
    orgs = Organization.query.all()
    return render_template('organizations.html', organizations=orgs, settings=settings)

@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@super_admin_required
def add_organization():
    settings = SystemSettings.query.first()
    if request.method == 'POST':
        name = request.form.get('name')
        short_name = request.form.get('short_name')
        logo_url = request.form.get('logo_url')
        
        org = Organization(name=name, short_name=short_name, logo_url=logo_url)
        db.session.add(org)
        db.session.commit()
        
        flash('Organization added successfully!', 'success')
        return redirect(url_for('organizations'))
    
    return render_template('add_organization.html', settings=settings)

@app.route('/organizations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_organization(id):
    settings = SystemSettings.query.first()
    org = Organization.query.get_or_404(id)
    
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.short_name = request.form.get('short_name')
        org.logo_url = request.form.get('logo_url')
        db.session.commit()
        
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('organizations'))
    
    return render_template('edit_organization.html', organization=org, settings=settings)

@app.route('/organizations/delete/<int:id>')
@login_required
@super_admin_required
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    
    if org.schools:
        flash('Cannot delete organization with schools. Remove schools first.', 'danger')
        return redirect(url_for('organizations'))
    
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('organizations'))

@app.route('/schools')
@login_required
def schools():
    settings = SystemSettings.query.first()
    school_list = get_user_schools()
    return render_template('schools.html', schools=school_list, settings=settings)

@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
@org_admin_required
def add_school():
    settings = SystemSettings.query.first()
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
    else:
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
    
    if request.method == 'POST':
        import secrets
        
        name = request.form.get('name')
        short_name = request.form.get('short_name')
        logo_url = request.form.get('logo_url')
        address = request.form.get('address')
        organization_id = request.form.get('organization_id')
        
        if organization_id:
            organization_id = int(organization_id)
            if current_user.role != 'super_admin' and organization_id != current_user.organization_id:
                flash('Access denied.', 'danger')
                return redirect(url_for('schools'))
        else:
            organization_id = None
        
        school = School(
            name=name,
            short_name=short_name,
            logo_url=logo_url,
            address=address,
            organization_id=organization_id,
            api_key=secrets.token_hex(32),
            monday_start=request.form.get('monday_start', '08:00'),
            monday_end=request.form.get('monday_end', '17:00'),
            tuesday_start=request.form.get('tuesday_start', '08:00'),
            tuesday_end=request.form.get('tuesday_end', '17:00'),
            wednesday_start=request.form.get('wednesday_start', '08:00'),
            wednesday_end=request.form.get('wednesday_end', '17:00'),
            thursday_start=request.form.get('thursday_start', '08:00'),
            thursday_end=request.form.get('thursday_end', '17:00'),
            friday_start=request.form.get('friday_start', '08:00'),
            friday_end=request.form.get('friday_end', '17:00'),
            saturday_start=request.form.get('saturday_start'),
            saturday_end=request.form.get('saturday_end'),
            sunday_start=request.form.get('sunday_start'),
            sunday_end=request.form.get('sunday_end')
        )
        
        db.session.add(school)
        db.session.commit()
        
        flash(f'School added successfully! API Key: {school.api_key}', 'success')
        return redirect(url_for('schools'))
    
    return render_template('add_school.html', settings=settings, organizations=organizations)

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_school(id):
    settings = SystemSettings.query.first()
    school = School.query.get_or_404(id)
    
    if not can_access_school(id):
        flash('Access denied.', 'danger')
        return redirect(url_for('schools'))
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
    else:
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.short_name = request.form.get('short_name')
        school.logo_url = request.form.get('logo_url')
        school.address = request.form.get('address')
        
        organization_id = request.form.get('organization_id')
        if organization_id:
            organization_id = int(organization_id)
            if current_user.role != 'super_admin' and organization_id != current_user.organization_id:
                flash('Access denied.', 'danger')
                return redirect(url_for('schools'))
            school.organization_id = organization_id
        else:
            if current_user.role == 'super_admin':
                school.organization_id = None
        
        school.monday_start = request.form.get('monday_start', '08:00')
        school.monday_end = request.form.get('monday_end', '17:00')
        school.tuesday_start = request.form.get('tuesday_start', '08:00')
        school.tuesday_end = request.form.get('tuesday_end', '17:00')
        school.wednesday_start = request.form.get('wednesday_start', '08:00')
        school.wednesday_end = request.form.get('wednesday_end', '17:00')
        school.thursday_start = request.form.get('thursday_start', '08:00')
        school.thursday_end = request.form.get('thursday_end', '17:00')
        school.friday_start = request.form.get('friday_start', '08:00')
        school.friday_end = request.form.get('friday_end', '17:00')
        school.saturday_start = request.form.get('saturday_start') or None
        school.saturday_end = request.form.get('saturday_end') or None
        school.sunday_start = request.form.get('sunday_start') or None
        school.sunday_end = request.form.get('sunday_end') or None
        
        db.session.commit()
        flash('School updated successfully!', 'success')
        return redirect(url_for('schools'))
    
    return render_template('edit_school.html', school=school, settings=settings, organizations=organizations)

@app.route('/schools/delete/<int:id>')
@login_required
@super_admin_required
def delete_school(id):
    school = School.query.get_or_404(id)
    
    Staff.query.filter_by(school_id=id).delete()
    
    db.session.delete(school)
    db.session.commit()
    flash('School deleted successfully!', 'success')
    return redirect(url_for('schools'))

@app.route('/staff')
@login_required
def staff():
    settings = SystemSettings.query.first()
    school_ids = get_user_school_ids()
    schools = get_user_schools()
    
    school_filter = request.args.get('school_id', type=int)
    
    query = Staff.query.filter(Staff.school_id.in_(school_ids)) if school_ids else Staff.query.filter(False)
    
    if school_filter and school_filter in school_ids:
        query = query.filter_by(school_id=school_filter)
    
    staff_list = query.all()
    
    return render_template('staff.html', staff=staff_list, schools=schools, settings=settings)

@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_staff():
    settings = SystemSettings.query.first()
    schools = get_user_schools()
    
    if request.method == 'POST':
        school_id = int(request.form.get('school_id'))
        
        if not can_access_school(school_id):
            flash('Access denied.', 'danger')
            return redirect(url_for('staff'))
        
        staff_member = Staff(
            staff_id=request.form.get('staff_id'),
            name=request.form.get('name'),
            department=request.form.get('department'),
            position=request.form.get('position'),
            school_id=school_id
        )
        
        db.session.add(staff_member)
        db.session.commit()
        
        flash('Staff member added successfully!', 'success')
        return redirect(url_for('staff'))
    
    return render_template('add_staff.html', schools=schools, settings=settings)

@app.route('/staff/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_staff(id):
    settings = SystemSettings.query.first()
    staff_member = Staff.query.get_or_404(id)
    
    if not can_access_school(staff_member.school_id):
        flash('Access denied.', 'danger')
        return redirect(url_for('staff'))
    
    schools = get_user_schools()
    
    if request.method == 'POST':
        new_school_id = int(request.form.get('school_id'))
        
        if not can_access_school(new_school_id):
            flash('Access denied.', 'danger')
            return redirect(url_for('staff'))
        
        staff_member.staff_id = request.form.get('staff_id')
        staff_member.name = request.form.get('name')
        staff_member.department = request.form.get('department')
        staff_member.position = request.form.get('position')
        staff_member.school_id = new_school_id
        staff_member.is_active = request.form.get('is_active') == 'on'
        
        db.session.commit()
        flash('Staff member updated successfully!', 'success')
        return redirect(url_for('staff'))
    
    return render_template('edit_staff.html', staff=staff_member, schools=schools, settings=settings)

@app.route('/staff/delete/<int:id>')
@login_required
@admin_required
def delete_staff(id):
    staff_member = Staff.query.get_or_404(id)
    
    if not can_access_school(staff_member.school_id):
        flash('Access denied.', 'danger')
        return redirect(url_for('staff'))
    
    AttendanceRecord.query.filter_by(staff_id=id).delete()
    db.session.delete(staff_member)
    db.session.commit()
    
    flash('Staff member deleted successfully!', 'success')
    return redirect(url_for('staff'))

@app.route('/staff/upload', methods=['GET', 'POST'])
@login_required
@admin_required
def upload_staff():
    settings = SystemSettings.query.first()
    schools = get_user_schools()
    
    if request.method == 'POST':
        school_id = int(request.form.get('school_id'))
        
        if not can_access_school(school_id):
            flash('Access denied.', 'danger')
            return redirect(url_for('staff'))
        
        file = request.files.get('file')
        if not file:
            flash('No file uploaded', 'danger')
            return redirect(url_for('upload_staff'))
        
        try:
            content = file.read().decode('utf-8')
            csv_reader = csv.DictReader(io.StringIO(content))
            
            count = 0
            for row in csv_reader:
                existing = Staff.query.filter_by(staff_id=row['staff_id'], school_id=school_id).first()
                if not existing:
                    staff_member = Staff(
                        staff_id=row['staff_id'],
                        name=row['name'],
                        department=row.get('department', ''),
                        position=row.get('position', ''),
                        school_id=school_id
                    )
                    db.session.add(staff_member)
                    count += 1
            
            db.session.commit()
            flash(f'{count} staff members uploaded successfully!', 'success')
        except Exception as e:
            flash(f'Error uploading file: {str(e)}', 'danger')
        
        return redirect(url_for('staff'))
    
    return render_template('upload_staff.html', schools=schools, settings=settings)

@app.route('/users')
@login_required
@org_admin_required
def users():
    settings = SystemSettings.query.first()
    
    if current_user.role == 'super_admin':
        user_list = User.query.all()
    else:
        user_list = User.query.filter_by(organization_id=current_user.organization_id).all()
    
    return render_template('users.html', users=user_list, settings=settings)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@org_admin_required
def add_user():
    settings = SystemSettings.query.first()
    schools = get_user_schools()
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
        available_roles = ['super_admin', 'org_admin', 'hr_viewer', 'ceo_viewer', 'school_admin']
    else:
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
        available_roles = ['hr_viewer', 'ceo_viewer', 'school_admin']
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        school_id = request.form.get('school_id')
        organization_id = request.form.get('organization_id')
        
        if role not in available_roles:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('add_user'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('add_user'))
        
        user = User(username=username, role=role)
        user.set_password(password)
        
        if role == 'school_admin' and school_id:
            school_id = int(school_id)
            if can_access_school(school_id):
                user.school_id = school_id
                school = School.query.get(school_id)
                if school:
                    user.organization_id = school.organization_id
        elif role in ['org_admin', 'hr_viewer', 'ceo_viewer'] and organization_id:
            organization_id = int(organization_id)
            if current_user.role == 'super_admin' or organization_id == current_user.organization_id:
                user.organization_id = organization_id
        
        db.session.add(user)
        db.session.commit()
        
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    
    return render_template('add_user.html', schools=schools, organizations=organizations, 
                         available_roles=available_roles, settings=settings)

@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@org_admin_required
def edit_user(id):
    settings = SystemSettings.query.first()
    user = User.query.get_or_404(id)
    
    if current_user.role != 'super_admin':
        if user.organization_id != current_user.organization_id:
            flash('Access denied.', 'danger')
            return redirect(url_for('users'))
    
    schools = get_user_schools()
    
    if current_user.role == 'super_admin':
        organizations = Organization.query.all()
        available_roles = ['super_admin', 'org_admin', 'hr_viewer', 'ceo_viewer', 'school_admin']
    else:
        organizations = Organization.query.filter_by(id=current_user.organization_id).all()
        available_roles = ['hr_viewer', 'ceo_viewer', 'school_admin']
    
    if request.method == 'POST':
        role = request.form.get('role')
        school_id = request.form.get('school_id')
        organization_id = request.form.get('organization_id')
        new_password = request.form.get('password')
        
        if role not in available_roles:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('edit_user', id=id))
        
        user.role = role
        
        if role == 'school_admin' and school_id:
            school_id = int(school_id)
            if can_access_school(school_id):
                user.school_id = school_id
                school = School.query.get(school_id)
                if school:
                    user.organization_id = school.organization_id
            user.organization_id = None
        elif role in ['org_admin', 'hr_viewer', 'ceo_viewer'] and organization_id:
            organization_id = int(organization_id)
            if current_user.role == 'super_admin' or organization_id == current_user.organization_id:
                user.organization_id = organization_id
            user.school_id = None
        elif role == 'super_admin':
            user.school_id = None
            user.organization_id = None
        
        if new_password:
            user.set_password(new_password)
        
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    
    return render_template('edit_user.html', user=user, schools=schools, organizations=organizations,
                         available_roles=available_roles, settings=settings)

@app.route('/users/delete/<int:id>')
@login_required
@org_admin_required
def delete_user(id):
    user = User.query.get_or_404(id)
    
    if user.id == current_user.id:
        flash('Cannot delete your own account', 'danger')
        return redirect(url_for('users'))
    
    if current_user.role != 'super_admin':
        if user.organization_id != current_user.organization_id:
            flash('Access denied.', 'danger')
            return redirect(url_for('users'))
    
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('users'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@super_admin_required
def settings():
    system_settings = SystemSettings.query.first()
    if not system_settings:
        system_settings = SystemSettings(company_name='Wakato Technologies')
        db.session.add(system_settings)
        db.session.commit()
    
    if request.method == 'POST':
        system_settings.company_name = request.form.get('company_name')
        system_settings.company_logo_url = request.form.get('company_logo_url')
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    return render_template('settings.html', settings=system_settings)

@app.route('/reports/attendance')
@login_required
def attendance_report():
    settings = SystemSettings.query.first()
    schools = get_user_schools()
    school_ids = get_user_school_ids()
    
    school_filter = request.args.get('school_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = AttendanceRecord.query.join(Staff).filter(Staff.school_id.in_(school_ids)) if school_ids else AttendanceRecord.query.filter(False)
    
    if school_filter and school_filter in school_ids:
        query = query.filter(Staff.school_id == school_filter)
    
    if start_date:
        query = query.filter(AttendanceRecord.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
    if end_date:
        query = query.filter(AttendanceRecord.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
    
    records = query.order_by(AttendanceRecord.date.desc()).all()
    
    return render_template('attendance_report.html', records=records, schools=schools, settings=settings)

@app.route('/reports/late')
@login_required
def late_report():
    settings = SystemSettings.query.first()
    schools = get_user_schools()
    school_ids = get_user_school_ids()
    
    school_filter = request.args.get('school_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = AttendanceRecord.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        AttendanceRecord.status == 'late'
    ) if school_ids else AttendanceRecord.query.filter(False)
    
    if school_filter and school_filter in school_ids:
        query = query.filter(Staff.school_id == school_filter)
    
    if start_date:
        query = query.filter(AttendanceRecord.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
    if end_date:
        query = query.filter(AttendanceRecord.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
    
    records = query.order_by(AttendanceRecord.date.desc()).all()
    
    return render_template('late_report.html', records=records, schools=schools, settings=settings)

@app.route('/reports/absent')
@login_required
def absent_report():
    settings = SystemSettings.query.first()
    schools = get_user_schools()
    school_ids = get_user_school_ids()
    
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    school_filter = request.args.get('school_id', type=int)
    
    staff_query = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True) if school_ids else Staff.query.filter(False)
    
    if school_filter and school_filter in school_ids:
        staff_query = staff_query.filter_by(school_id=school_filter)
    
    all_staff = staff_query.all()
    
    present_staff_ids = [r.staff_id for r in AttendanceRecord.query.filter_by(date=report_date).all()]
    absent_staff = [s for s in all_staff if s.id not in present_staff_ids]
    
    return render_template('absent_report.html', staff=absent_staff, schools=schools, 
                         report_date=report_date, settings=settings)

@app.route('/reports/overtime')
@login_required
def overtime_report():
    settings = SystemSettings.query.first()
    schools = get_user_schools()
    school_ids = get_user_school_ids()
    
    school_filter = request.args.get('school_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = AttendanceRecord.query.join(Staff).filter(
        Staff.school_id.in_(school_ids),
        AttendanceRecord.overtime_minutes > 0
    ) if school_ids else AttendanceRecord.query.filter(False)
    
    if school_filter and school_filter in school_ids:
        query = query.filter(Staff.school_id == school_filter)
    
    if start_date:
        query = query.filter(AttendanceRecord.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
    if end_date:
        query = query.filter(AttendanceRecord.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
    
    records = query.order_by(AttendanceRecord.date.desc()).all()
    
    return render_template('overtime_report.html', records=records, schools=schools, settings=settings)

@app.route('/reports/staff-lateness')
@login_required
def staff_lateness_report():
    settings = SystemSettings.query.first()
    schools = get_user_schools()
    school_ids = get_user_school_ids()
    
    school_filter = request.args.get('school_id', type=int)
    
    staff_query = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active == True) if school_ids else Staff.query.filter(False)
    
    if school_filter and school_filter in school_ids:
        staff_query = staff_query.filter_by(school_id=school_filter)
    
    staff_list = staff_query.all()
    
    staff_data = []
    for s in staff_list:
        total_records = AttendanceRecord.query.filter_by(staff_id=s.id).count()
        late_records = AttendanceRecord.query.filter_by(staff_id=s.id, status='late').count()
        
        punctuality_rate = ((total_records - late_records) / total_records * 100) if total_records > 0 else 100
        lateness_rate = (late_records / total_records * 100) if total_records > 0 else 0
        
        staff_data.append({
            'staff': s,
            'times_late': s.times_late,
            'punctuality_rate': round(punctuality_rate, 1),
            'lateness_rate': round(lateness_rate, 1)
        })
    
    return render_template('staff_lateness_report.html', staff_data=staff_data, schools=schools, settings=settings)

@app.route('/reports/reset-late-counts', methods=['POST'])
@login_required
@super_admin_required
def reset_late_counts():
    school_ids = get_user_school_ids()
    Staff.query.filter(Staff.school_id.in_(school_ids)).update({Staff.times_late: 0}, synchronize_session=False)
    db.session.commit()
    flash('Late counts reset successfully!', 'success')
    return redirect(url_for('staff_lateness_report'))

@app.route('/reports/download/<report_type>')
@login_required
def download_report(report_type):
    school_ids = get_user_school_ids()
    school_filter = request.args.get('school_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    if report_type == 'attendance':
        writer.writerow(['Date', 'Staff ID', 'Name', 'School', 'Sign In', 'Sign Out', 'Status', 'Late Minutes', 'Overtime'])
        
        query = AttendanceRecord.query.join(Staff).filter(Staff.school_id.in_(school_ids)) if school_ids else AttendanceRecord.query.filter(False)
        
        if school_filter and school_filter in school_ids:
            query = query.filter(Staff.school_id == school_filter)
        if start_date:
            query = query.filter(AttendanceRecord.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            query = query.filter(AttendanceRecord.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        
        for record in query.all():
            writer.writerow([
                record.date,
                record.staff.staff_id,
                record.staff.name,
                record.staff.school.name,
                record.sign_in_time.strftime('%H:%M') if record.sign_in_time else '',
                record.sign_out_time.strftime('%H:%M') if record.sign_out_time else '',
                record.status,
                record.late_minutes,
                record.overtime_minutes
            ])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'{report_type}_report_{datetime.now().strftime("%Y%m%d")}.csv'
    )

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
    
    data = request.get_json() or {}
    action = data.get('action')
    records = data.get('records', [])
    
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
    
    if action is None and len(records) == 0:
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
    
    processed = 0
    for record in records:
        staff_id_str = record.get('staffId')
        staff = Staff.query.filter_by(staff_id=staff_id_str, school_id=school.id).first()
        
        if not staff:
            continue
        
        record_date = datetime.fromisoformat(record.get('timestamp').replace('Z', '+00:00')).date()
        record_time = datetime.fromisoformat(record.get('timestamp').replace('Z', '+00:00'))
        action_type = record.get('action')
        
        attendance = AttendanceRecord.query.filter_by(staff_id=staff.id, date=record_date).first()
        
        if action_type == 'sign_in':
            if not attendance:
                attendance = AttendanceRecord(staff_id=staff.id, date=record_date)
                db.session.add(attendance)
            
            if not attendance.sign_in_time:
                attendance.sign_in_time = record_time
                
                day_name = record_date.strftime('%A').lower()
                start_time_str = getattr(school, f'{day_name}_start', '08:00')
                
                if start_time_str:
                    start_time = datetime.strptime(start_time_str, '%H:%M').time()
                    scheduled_start = datetime.combine(record_date, start_time)
                    
                    if record_time > scheduled_start:
                        late_minutes = int((record_time - scheduled_start).total_seconds() / 60)
                        attendance.status = 'late'
                        attendance.late_minutes = late_minutes
                        staff.times_late += 1
                    else:
                        attendance.status = 'present'
                        attendance.late_minutes = 0
                else:
                    attendance.status = 'present'
        
        elif action_type == 'sign_out':
            if attendance and attendance.sign_in_time:
                attendance.sign_out_time = record_time
                
                day_name = record_date.strftime('%A').lower()
                end_time_str = getattr(school, f'{day_name}_end', '17:00')
                
                if end_time_str:
                    end_time = datetime.strptime(end_time_str, '%H:%M').time()
                    scheduled_end = datetime.combine(record_date, end_time)
                    
                    if record_time > scheduled_end:
                        overtime_minutes = int((record_time - scheduled_end).total_seconds() / 60)
                        attendance.overtime_minutes = overtime_minutes
        
        processed += 1
    
    db.session.commit()
    
    staff_list_data = get_staff_data_for_api(school)
    response = jsonify({
        'success': True,
        'processed': processed,
        'staff': staff_list_data,
        'school': {
            'name': school.name,
            'short_name': school.short_name or '',
            'logo_url': school.logo_url or ''
        }
    })
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

if __name__ == '__main__':
    app.run(debug=True)
