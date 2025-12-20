from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
from functools import wraps
import os
from io import BytesIO
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


# ============== MODELS ==============

class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(50), unique=True)
    org_type = db.Column(db.String(50), default='school')
    address = db.Column(db.Text)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    schools = db.relationship('School', backref='organization', lazy=True)
    users = db.relationship('User', backref='organization', lazy=True)
    departments = db.relationship('Department', backref='organization', lazy=True)


class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(50))
    address = db.Column(db.Text)
    phone = db.Column(db.String(20))
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    staff = db.relationship('Staff', backref='school', lazy=True)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='viewer')
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attendance_records = db.relationship('Attendance', backref='staff', lazy=True)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.DateTime)
    check_out = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='present')
    late_minutes = db.Column(db.Integer, default=0)
    overtime_minutes = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ============== HELPER FUNCTIONS ==============

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_date_range(period, start_date=None, end_date=None):
    today = date.today()
    if period == 'today':
        return today, today
    elif period == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif period == 'week':
        start = today - timedelta(days=today.weekday())
        return start, today
    elif period == 'month':
        start = today.replace(day=1)
        return start, today
    elif period == 'year':
        start = today.replace(month=1, day=1)
        return start, today
    elif period == 'custom' and start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            return start, end
        except:
            return today, today
    return today, today


# ============== MIGRATION ROUTE (PUBLIC - REMOVE AFTER USE) ==============

@app.route('/migrate-db')
def migrate_db():
    try:
        from sqlalchemy import text
        
        migrations = [
            # Add columns to user table
            "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS organization_id INTEGER",
            "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS school_id INTEGER",
            "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            
            # Add columns to organization table
            "ALTER TABLE organization ADD COLUMN IF NOT EXISTS org_type VARCHAR(50) DEFAULT 'school'",
            "ALTER TABLE organization ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE organization ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            
            # Add columns to school table
            "ALTER TABLE school ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE school ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            
            # Add columns to staff table
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            
            # Create department table
            """CREATE TABLE IF NOT EXISTS department (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                organization_id INTEGER,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Create system_settings table
            """CREATE TABLE IF NOT EXISTS system_settings (
                id SERIAL PRIMARY KEY,
                key VARCHAR(100) UNIQUE NOT NULL,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Update existing users to be active
            "UPDATE \"user\" SET is_active = TRUE WHERE is_active IS NULL",
            
            # Update existing organizations to be active
            "UPDATE organization SET is_active = TRUE WHERE is_active IS NULL",
            
            # Update existing schools to be active
            "UPDATE school SET is_active = TRUE WHERE is_active IS NULL",
            
            # Update existing staff to be active
            "UPDATE staff SET is_active = TRUE WHERE is_active IS NULL",
        ]
        
        results = []
        for sql in migrations:
            try:
                db.session.execute(text(sql))
                db.session.commit()
                results.append(f"✓ Success: {sql[:50]}...")
            except Exception as e:
                db.session.rollback()
                results.append(f"⚠ Skipped (may already exist): {sql[:50]}...")
        
        # Create default settings if missing
        default_settings = {
            'work_start_time': '08:00',
            'work_end_time': '17:00',
            'late_threshold': '15',
            'early_threshold': '10',
            'overtime_threshold': '30'
        }
        
        for key, value in default_settings.items():
            try:
                existing = db.session.execute(text(f"SELECT id FROM system_settings WHERE key = :key"), {'key': key}).fetchone()
                if not existing:
                    db.session.execute(text("INSERT INTO system_settings (key, value) VALUES (:key, :value)"), {'key': key, 'value': value})
                    db.session.commit()
                    results.append(f"✓ Added setting: {key}")
            except Exception as e:
                db.session.rollback()
                results.append(f"⚠ Setting {key}: {str(e)}")
        
        return f'''
        <html>
        <head><title>Migration Complete</title></head>
        <body style="font-family: Arial, sans-serif; padding: 20px; max-width: 800px; margin: 0 auto;">
            <h1 style="color: green;">✓ Database Migration Complete!</h1>
            <h3>Your data has been preserved.</h3>
            <h4>Migration Results:</h4>
            <ul>
                {"".join(f"<li>{r}</li>" for r in results)}
            </ul>
            <br>
            <a href="/login" style="background: #667eea; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go to Login</a>
            <br><br>
            <p style="color: red;"><strong>Important:</strong> Remove the /migrate-db route from app.py after successful migration!</p>
        </body>
        </html>
        '''
        
    except Exception as e:
        return f'''
        <html>
        <head><title>Migration Error</title></head>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h1 style="color: red;">Migration Error</h1>
            <p>{str(e)}</p>
            <a href="/login">Try Login Anyway</a>
        </body>
        </html>
        '''


# ============== AUTH ROUTES ==============

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            # Check is_active only if the column exists and has a value
            is_active = getattr(user, 'is_active', True)
            if is_active is None or is_active:
                login_user(user)
                next_page = request.args.get('next')
                flash('Login successful!', 'success')
                return redirect(next_page if next_page else url_for('dashboard'))
            else:
                flash('Account is deactivated', 'danger')
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ============== DASHBOARD ==============

@app.route('/')
@login_required
def dashboard():
    today = date.today()
    
    # Get staff based on user role
    if current_user.role == 'super_admin':
        staff_query = Staff.query.filter_by(is_active=True)
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_query = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True)
    elif current_user.school_id:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, is_active=True)
    else:
        staff_query = Staff.query.filter_by(is_active=True)
    
    total_staff = staff_query.count()
    
    # Today's attendance
    staff_ids = [s.id for s in staff_query.all()]
    today_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date == today
    ).all() if staff_ids else []
    
    present_count = len([a for a in today_attendance if a.status == 'present'])
    late_count = len([a for a in today_attendance if a.late_minutes and a.late_minutes > 0])
    absent_count = total_staff - present_count
    
    # Calculate rates
    attendance_rate = round((present_count / total_staff * 100), 1) if total_staff > 0 else 0
    punctuality_rate = round(((present_count - late_count) / present_count * 100), 1) if present_count > 0 else 100
    
    # Recent attendance records
    recent_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids)
    ).order_by(Attendance.created_at.desc()).limit(10).all() if staff_ids else []
    
    return render_template('dashboard.html',
                         total_staff=total_staff,
                         present_count=present_count,
                         absent_count=absent_count,
                         late_count=late_count,
                         attendance_rate=attendance_rate,
                         punctuality_rate=punctuality_rate,
                         recent_attendance=recent_attendance,
                         today=today)


# ============== ORGANIZATION MANAGEMENT ==============

@app.route('/organizations')
@login_required
@role_required('super_admin')
def manage_organizations():
    organizations = Organization.query.all()
    return render_template('manage_organizations.html', organizations=organizations)


@app.route('/organizations/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def add_organization():
    if request.method == 'POST':
        org = Organization(
            name=request.form.get('name'),
            code=request.form.get('code'),
            org_type=request.form.get('org_type', 'school'),
            address=request.form.get('address'),
            phone=request.form.get('phone'),
            email=request.form.get('email')
        )
        db.session.add(org)
        db.session.commit()
        
        # Seed default departments
        default_depts = ['Administration', 'Operations', 'Finance', 'Human Resources', 'IT']
        for dept_name in default_depts:
            dept = Department(name=dept_name, organization_id=org.id)
            db.session.add(dept)
        db.session.commit()
        
        flash('Organization added successfully!', 'success')
        return redirect(url_for('manage_organizations'))
    
    return render_template('add_organization.html')


@app.route('/organizations/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_organization(id):
    org = Organization.query.get_or_404(id)
    
    if request.method == 'POST':
        org.name = request.form.get('name')
        org.code = request.form.get('code')
        org.org_type = request.form.get('org_type')
        org.address = request.form.get('address')
        org.phone = request.form.get('phone')
        org.email = request.form.get('email')
        org.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Organization updated successfully!', 'success')
        return redirect(url_for('manage_organizations'))
    
    return render_template('edit_organization.html', organization=org)


@app.route('/organizations/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin')
def delete_organization(id):
    org = Organization.query.get_or_404(id)
    db.session.delete(org)
    db.session.commit()
    flash('Organization deleted successfully!', 'success')
    return redirect(url_for('manage_organizations'))


# ============== DEPARTMENT MANAGEMENT ==============

@app.route('/organizations/<int:org_id>/departments')
@login_required
@role_required('super_admin', 'org_admin')
def manage_departments(org_id):
    org = Organization.query.get_or_404(org_id)
    departments = Department.query.filter_by(organization_id=org_id).order_by(Department.name).all()
    return render_template('manage_departments.html', organization=org, departments=departments)


@app.route('/organizations/<int:org_id>/departments/add', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin')
def add_department(org_id):
    name = request.form.get('name')
    if name:
        dept = Department(name=name, organization_id=org_id)
        db.session.add(dept)
        db.session.commit()
        flash('Department added successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))


@app.route('/departments/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin')
def delete_department(id):
    dept = Department.query.get_or_404(id)
    org_id = dept.organization_id
    db.session.delete(dept)
    db.session.commit()
    flash('Department deleted successfully!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))


@app.route('/organizations/<int:org_id>/departments/seed', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin')
def seed_default_departments(org_id):
    org = Organization.query.get_or_404(org_id)
    
    org_type = getattr(org, 'org_type', 'general') or 'general'
    
    if org_type == 'school':
        defaults = ['Academic', 'Non-Academic', 'Administration', 'Support Staff']
    elif org_type == 'hospital':
        defaults = ['Medical', 'Nursing', 'Administration', 'Support', 'Laboratory']
    elif org_type == 'corporate':
        defaults = ['Executive', 'Operations', 'Finance', 'HR', 'IT', 'Marketing', 'Sales']
    else:
        defaults = ['Administration', 'Operations', 'Finance', 'Human Resources', 'IT']
    
    existing = [d.name for d in Department.query.filter_by(organization_id=org_id).all()]
    for name in defaults:
        if name not in existing:
            dept = Department(name=name, organization_id=org_id)
            db.session.add(dept)
    
    db.session.commit()
    flash('Default departments added!', 'success')
    return redirect(url_for('manage_departments', org_id=org_id))


# ============== SCHOOL/BRANCH MANAGEMENT ==============

@app.route('/schools')
@login_required
@role_required('super_admin', 'org_admin')
def manage_schools():
    if current_user.role == 'super_admin':
        schools = School.query.all()
    else:
        schools = School.query.filter_by(organization_id=current_user.organization_id).all()
    
    organizations = Organization.query.filter_by(is_active=True).all()
    return render_template('manage_schools.html', schools=schools, organizations=organizations)


@app.route('/schools/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin')
def add_school():
    if request.method == 'POST':
        org_id = request.form.get('organization_id')
        if current_user.role == 'org_admin':
            org_id = current_user.organization_id
        
        school = School(
            name=request.form.get('name'),
            code=request.form.get('code'),
            address=request.form.get('address'),
            phone=request.form.get('phone'),
            organization_id=org_id
        )
        db.session.add(school)
        db.session.commit()
        flash('Branch added successfully!', 'success')
        return redirect(url_for('manage_schools'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    return render_template('add_school.html', organizations=organizations)


@app.route('/schools/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin')
def edit_school(id):
    school = School.query.get_or_404(id)
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.code = request.form.get('code')
        school.address = request.form.get('address')
        school.phone = request.form.get('phone')
        if current_user.role == 'super_admin':
            school.organization_id = request.form.get('organization_id')
        school.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Branch updated successfully!', 'success')
        return redirect(url_for('manage_schools'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    return render_template('edit_school.html', school=school, organizations=organizations)


@app.route('/schools/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin')
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('Branch deleted successfully!', 'success')
    return redirect(url_for('manage_schools'))


# ============== USER MANAGEMENT ==============

@app.route('/users')
@login_required
@role_required('super_admin', 'org_admin')
def manage_users():
    if current_user.role == 'super_admin':
        users = User.query.all()
    else:
        users = User.query.filter_by(organization_id=current_user.organization_id).all()
    
    return render_template('manage_users.html', users=users)


@app.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin')
def add_user():
    if request.method == 'POST':
        org_id = request.form.get('organization_id')
        if current_user.role == 'org_admin':
            org_id = current_user.organization_id
        
        user = User(
            username=request.form.get('username'),
            email=request.form.get('email'),
            role=request.form.get('role'),
            organization_id=org_id if org_id else None,
            school_id=request.form.get('school_id') or None
        )
        user.set_password(request.form.get('password'))
        db.session.add(user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('manage_users'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    schools = School.query.filter_by(is_active=True).all()
    return render_template('add_user.html', organizations=organizations, schools=schools)


@app.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin')
def edit_user(id):
    user = User.query.get_or_404(id)
    
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.email = request.form.get('email')
        user.role = request.form.get('role')
        user.is_active = 'is_active' in request.form
        
        if current_user.role == 'super_admin':
            user.organization_id = request.form.get('organization_id') or None
        user.school_id = request.form.get('school_id') or None
        
        new_password = request.form.get('password')
        if new_password:
            user.set_password(new_password)
        
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('manage_users'))
    
    organizations = Organization.query.filter_by(is_active=True).all()
    schools = School.query.filter_by(is_active=True).all()
    return render_template('edit_user.html', user=user, organizations=organizations, schools=schools)


@app.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin')
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete yourself!', 'danger')
        return redirect(url_for('manage_users'))
    
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('manage_users'))


# ============== STAFF MANAGEMENT ==============

@app.route('/staff')
@login_required
def manage_staff():
    if current_user.role == 'super_admin':
        staff = Staff.query.all()
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff = Staff.query.filter(Staff.school_id.in_(school_ids)).all()
    elif current_user.school_id:
        staff = Staff.query.filter_by(school_id=current_user.school_id).all()
    else:
        staff = Staff.query.all()
    
    return render_template('manage_staff.html', staff=staff)


@app.route('/staff/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin', 'school_admin')
def add_staff():
    if request.method == 'POST':
        school_id = request.form.get('school_id')
        if current_user.role == 'school_admin':
            school_id = current_user.school_id
        
        staff = Staff(
            staff_id=request.form.get('staff_id'),
            first_name=request.form.get('first_name'),
            last_name=request.form.get('last_name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            department=request.form.get('department'),
            position=request.form.get('position'),
            school_id=school_id
        )
        db.session.add(staff)
        db.session.commit()
        flash('Staff member added successfully!', 'success')
        return redirect(url_for('manage_staff'))
    
    # Get schools based on role
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
        departments = Department.query.all()
    elif current_user.role == 'org_admin' and current_user.organization_id:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        departments = Department.query.filter_by(organization_id=current_user.organization_id).all()
    elif current_user.school_id:
        schools = [School.query.get(current_user.school_id)]
        school = School.query.get(current_user.school_id)
        departments = Department.query.filter_by(organization_id=school.organization_id).all() if school else []
    else:
        schools = School.query.filter_by(is_active=True).all()
        departments = Department.query.all()
    
    return render_template('add_staff.html', schools=schools, departments=departments)


@app.route('/staff/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin', 'school_admin')
def edit_staff(id):
    staff = Staff.query.get_or_404(id)
    
    if request.method == 'POST':
        staff.staff_id = request.form.get('staff_id')
        staff.first_name = request.form.get('first_name')
        staff.last_name = request.form.get('last_name')
        staff.email = request.form.get('email')
        staff.phone = request.form.get('phone')
        staff.department = request.form.get('department')
        staff.position = request.form.get('position')
        staff.is_active = 'is_active' in request.form
        
        if current_user.role in ['super_admin', 'org_admin']:
            staff.school_id = request.form.get('school_id')
        
        db.session.commit()
        flash('Staff member updated successfully!', 'success')
        return redirect(url_for('manage_staff'))
    
    if current_user.role == 'super_admin':
        schools = School.query.filter_by(is_active=True).all()
        departments = Department.query.all()
    elif current_user.role == 'org_admin' and current_user.organization_id:
        schools = School.query.filter_by(organization_id=current_user.organization_id, is_active=True).all()
        departments = Department.query.filter_by(organization_id=current_user.organization_id).all()
    elif current_user.school_id:
        schools = [School.query.get(current_user.school_id)]
        school = School.query.get(current_user.school_id)
        departments = Department.query.filter_by(organization_id=school.organization_id).all() if school else []
    else:
        schools = School.query.filter_by(is_active=True).all()
        departments = Department.query.all()
    
    return render_template('edit_staff.html', staff=staff, schools=schools, departments=departments)


@app.route('/staff/<int:id>/delete', methods=['POST'])
@login_required
@role_required('super_admin', 'org_admin', 'school_admin')
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    db.session.delete(staff)
    db.session.commit()
    flash('Staff member deleted successfully!', 'success')
    return redirect(url_for('manage_staff'))


# ============== ATTENDANCE MANAGEMENT ==============

@app.route('/attendance')
@login_required
def view_attendance():
    period = request.args.get('period', 'today')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    school_id = request.args.get('school_id')
    
    date_start, date_end = get_date_range(period, start_date, end_date)
    
    # Build query based on role
    if current_user.role == 'super_admin':
        staff_ids = [s.id for s in Staff.query.all()]
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids_list = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(school_ids_list)).all()]
    elif current_user.school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
    else:
        staff_ids = [s.id for s in Staff.query.all()]
    
    query = Attendance.query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else Attendance.query.filter(False)
    
    if school_id:
        school_staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(school_staff_ids))
    
    attendance = query.filter(
        Attendance.date >= date_start,
        Attendance.date <= date_end
    ).order_by(Attendance.date.desc(), Attendance.check_in.desc()).all()
    
    schools = School.query.filter_by(is_active=True).all()
    
    return render_template('attendance.html',
                         attendance=attendance,
                         schools=schools,
                         period=period,
                         start_date=start_date,
                         end_date=end_date,
                         selected_school=school_id)


@app.route('/attendance/add', methods=['GET', 'POST'])
@login_required
@role_required('super_admin', 'org_admin', 'school_admin')
def add_attendance():
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        attendance_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        
        check_in_str = request.form.get('check_in')
        check_out_str = request.form.get('check_out')
        
        check_in = datetime.strptime(f"{attendance_date} {check_in_str}", '%Y-%m-%d %H:%M') if check_in_str else None
        check_out = datetime.strptime(f"{attendance_date} {check_out_str}", '%Y-%m-%d %H:%M') if check_out_str else None
        
        # Calculate late minutes
        late_minutes = 0
        work_start = datetime.strptime(f"{attendance_date} 08:00", '%Y-%m-%d %H:%M')
        if check_in and check_in > work_start:
            late_minutes = int((check_in - work_start).total_seconds() / 60)
        
        # Calculate overtime
        overtime_minutes = 0
        work_end = datetime.strptime(f"{attendance_date} 17:00", '%Y-%m-%d %H:%M')
        if check_out and check_out > work_end:
            overtime_minutes = int((check_out - work_end).total_seconds() / 60)
        
        attendance = Attendance(
            staff_id=staff_id,
            date=attendance_date,
            check_in=check_in,
            check_out=check_out,
            status='present',
            late_minutes=late_minutes,
            overtime_minutes=overtime_minutes,
            notes=request.form.get('notes')
        )
        db.session.add(attendance)
        db.session.commit()
        flash('Attendance record added!', 'success')
        return redirect(url_for('view_attendance'))
    
    # Get staff based on role
    if current_user.role == 'super_admin':
        staff = Staff.query.filter_by(is_active=True).all()
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True).all()
    elif current_user.school_id:
        staff = Staff.query.filter_by(school_id=current_user.school_id, is_active=True).all()
    else:
        staff = Staff.query.filter_by(is_active=True).all()
    
    return render_template('add_attendance.html', staff=staff)


# ============== REPORTS ==============

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')


@app.route('/reports/attendance')
@login_required
def attendance_report():
    period = request.args.get('period', 'month')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    date_start, date_end = get_date_range(period, start_date, end_date)
    
    # Get staff based on role
    if current_user.role == 'super_admin':
        staff_query = Staff.query.filter_by(is_active=True)
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_query = Staff.query.filter(Staff.school_id.in_(school_ids), Staff.is_active==True)
    elif current_user.school_id:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, is_active=True)
    else:
        staff_query = Staff.query.filter_by(is_active=True)
    
    staff_list = staff_query.all()
    staff_ids = [s.id for s in staff_list]
    
    # Get attendance data
    attendance_data = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= date_start,
        Attendance.date <= date_end
    ).all() if staff_ids else []
    
    # Calculate stats per staff
    report_data = []
    for staff in staff_list:
        staff_attendance = [a for a in attendance_data if a.staff_id == staff.id]
        total_days = (date_end - date_start).days + 1
        present_days = len(staff_attendance)
        late_days = len([a for a in staff_attendance if a.late_minutes and a.late_minutes > 0])
        
        report_data.append({
            'staff': staff,
            'total_days': total_days,
            'present_days': present_days,
            'absent_days': total_days - present_days,
            'late_days': late_days,
            'attendance_rate': round(present_days / total_days * 100, 1) if total_days > 0 else 0
        })
    
    return render_template('attendance_report.html',
                         report_data=report_data,
                         period=period,
                         start_date=date_start,
                         end_date=date_end)


@app.route('/reports/late')
@login_required
def late_report():
    period = request.args.get('period', 'month')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    date_start, date_end = get_date_range(period, start_date, end_date)
    
    # Get staff IDs based on role
    if current_user.role == 'super_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(is_active=True).all()]
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(school_ids)).all()]
    elif current_user.school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
    else:
        staff_ids = [s.id for s in Staff.query.filter_by(is_active=True).all()]
    
    late_records = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= date_start,
        Attendance.date <= date_end,
        Attendance.late_minutes > 0
    ).order_by(Attendance.date.desc()).all() if staff_ids else []
    
    return render_template('late_report.html',
                         late_records=late_records,
                         period=period,
                         start_date=date_start,
                         end_date=date_end)


@app.route('/reports/overtime')
@login_required
def overtime_report():
    period = request.args.get('period', 'month')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    date_start, date_end = get_date_range(period, start_date, end_date)
    
    # Get staff IDs based on role
    if current_user.role == 'super_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(is_active=True).all()]
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_ids = [s.id for s in Staff.query.filter(Staff.school_id.in_(school_ids)).all()]
    elif current_user.school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
    else:
        staff_ids = [s.id for s in Staff.query.filter_by(is_active=True).all()]
    
    overtime_records = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= date_start,
        Attendance.date <= date_end,
        Attendance.overtime_minutes > 0
    ).order_by(Attendance.date.desc()).all() if staff_ids else []
    
    return render_template('overtime_report.html',
                         overtime_records=overtime_records,
                         period=period,
                         start_date=date_start,
                         end_date=date_end)


# ============== ANALYTICS ==============

@app.route('/reports/analytics')
@login_required
def analytics():
    period = request.args.get('period', 'month')
    school_id = request.args.get('school_id')
    organization_id = request.args.get('organization_id')
    department = request.args.get('department')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    date_start, date_end = get_date_range(period, start_date, end_date)
    
    # Build staff query based on role and filters
    if current_user.role == 'super_admin':
        staff_query = Staff.query.filter_by(is_active=True)
        if organization_id:
            school_ids_list = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
            staff_query = staff_query.filter(Staff.school_id.in_(school_ids_list))
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids_list = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_query = Staff.query.filter(Staff.school_id.in_(school_ids_list), Staff.is_active==True)
    elif current_user.school_id:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, is_active=True)
    else:
        staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    if department:
        staff_query = staff_query.filter_by(department=department)
    
    staff_list = staff_query.all()
    staff_ids = [s.id for s in staff_list]
    total_staff = len(staff_list)
    
    # Get attendance records
    attendance_records = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= date_start,
        Attendance.date <= date_end
    ).all() if staff_ids else []
    
    # Calculate metrics
    total_days = (date_end - date_start).days + 1
    working_days = total_days
    total_possible = total_staff * working_days if total_staff > 0 else 1
    
    present_count = len(attendance_records)
    late_count = len([a for a in attendance_records if a.late_minutes and a.late_minutes > 0])
    on_time_count = present_count - late_count
    
    total_late_minutes = sum(a.late_minutes or 0 for a in attendance_records)
    total_overtime_minutes = sum(a.overtime_minutes or 0 for a in attendance_records)
    
    attendance_rate = round(present_count / total_possible * 100, 1) if total_possible > 0 else 0
    punctuality_rate = round(on_time_count / present_count * 100, 1) if present_count > 0 else 100
    avg_late_minutes = round(total_late_minutes / late_count, 1) if late_count > 0 else 0
    avg_overtime = round(total_overtime_minutes / present_count, 1) if present_count > 0 else 0
    
    # Previous period comparison
    period_length = (date_end - date_start).days + 1
    prev_start = date_start - timedelta(days=period_length)
    prev_end = date_start - timedelta(days=1)
    
    prev_attendance = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= prev_start,
        Attendance.date <= prev_end
    ).all() if staff_ids else []
    
    prev_possible = total_staff * period_length if total_staff > 0 else 1
    prev_present = len(prev_attendance)
    prev_late = len([a for a in prev_attendance if a.late_minutes and a.late_minutes > 0])
    prev_on_time = prev_present - prev_late
    
    prev_attendance_rate = round(prev_present / prev_possible * 100, 1) if prev_possible > 0 else 0
    prev_punctuality_rate = round(prev_on_time / prev_present * 100, 1) if prev_present > 0 else 100
    
    attendance_trend = round(attendance_rate - prev_attendance_rate, 1)
    punctuality_trend = round(punctuality_rate - prev_punctuality_rate, 1)
    
    # Chart data - Attendance trend by date
    trend_data = {'labels': [], 'attendance': [], 'punctuality': []}
    current_date = date_start
    while current_date <= date_end:
        day_records = [a for a in attendance_records if a.date == current_date]
        day_present = len(day_records)
        day_late = len([a for a in day_records if a.late_minutes and a.late_minutes > 0])
        day_on_time = day_present - day_late
        
        trend_data['labels'].append(current_date.strftime('%b %d'))
        trend_data['attendance'].append(round(day_present / total_staff * 100, 1) if total_staff > 0 else 0)
        trend_data['punctuality'].append(round(day_on_time / day_present * 100, 1) if day_present > 0 else 100)
        current_date += timedelta(days=1)
    
    # Late by day of week
    late_by_day = {'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], 'data': [0]*7}
    for a in attendance_records:
        if a.late_minutes and a.late_minutes > 0:
            late_by_day['data'][a.date.weekday()] += 1
    
    # Department performance
    dept_data = {'labels': [], 'attendance': [], 'punctuality': []}
    departments_list = list(set(s.department for s in staff_list if s.department))
    for dept in departments_list:
        dept_staff = [s for s in staff_list if s.department == dept]
        dept_staff_ids = [s.id for s in dept_staff]
        dept_records = [a for a in attendance_records if a.staff_id in dept_staff_ids]
        
        dept_possible = len(dept_staff) * working_days if dept_staff else 1
        dept_present = len(dept_records)
        dept_late = len([a for a in dept_records if a.late_minutes and a.late_minutes > 0])
        
        dept_data['labels'].append(dept)
        dept_data['attendance'].append(round(dept_present / dept_possible * 100, 1) if dept_possible > 0 else 0)
        dept_data['punctuality'].append(round((dept_present - dept_late) / dept_present * 100, 1) if dept_present > 0 else 100)
    
    # Branch comparison
    branch_data = {'labels': [], 'data': []}
    if current_user.role in ['super_admin', 'org_admin']:
        branches = School.query.filter_by(is_active=True).all()
        for branch in branches:
            branch_staff = [s for s in staff_list if s.school_id == branch.id]
            branch_staff_ids = [s.id for s in branch_staff]
            branch_records = [a for a in attendance_records if a.staff_id in branch_staff_ids]
            branch_possible = len(branch_staff) * working_days if branch_staff else 1
            
            branch_data['labels'].append(branch.name[:15])
            branch_data['data'].append(round(len(branch_records) / branch_possible * 100, 1) if branch_possible > 0 else 0)
    
    # Arrival distribution
    arrival_data = {'labels': ['Early', 'On Time', 'Late <15min', 'Late 15-30min', 'Late >30min'], 'data': [0]*5}
    for a in attendance_records:
        late_mins = a.late_minutes or 0
        if late_mins == 0:
            if a.check_in and a.check_in.hour < 8:
                arrival_data['data'][0] += 1
            else:
                arrival_data['data'][1] += 1
        elif late_mins < 15:
            arrival_data['data'][2] += 1
        elif late_mins <= 30:
            arrival_data['data'][3] += 1
        else:
            arrival_data['data'][4] += 1
    
    # Present vs Absent pie
    present_absent = {'present': present_count, 'absent': max(0, total_possible - present_count)}
    
    # Weekly comparison
    weekly_data = {'labels': [], 'current': [], 'previous': []}
    for i in range(min(4, (date_end - date_start).days // 7 + 1)):
        week_start = date_start + timedelta(weeks=i)
        week_end = min(week_start + timedelta(days=6), date_end)
        
        week_records = [a for a in attendance_records if week_start <= a.date <= week_end]
        week_days = (week_end - week_start).days + 1
        week_possible = total_staff * week_days if total_staff > 0 else 1
        
        weekly_data['labels'].append(f'Week {i+1}')
        weekly_data['current'].append(round(len(week_records) / week_possible * 100, 1) if week_possible > 0 else 0)
        
        # Previous period same week
        prev_week_start = prev_start + timedelta(weeks=i)
        prev_week_end = min(prev_week_start + timedelta(days=6), prev_end)
        prev_week_records = [a for a in prev_attendance if prev_week_start <= a.date <= prev_week_end]
        prev_week_days = max(1, (prev_week_end - prev_week_start).days + 1)
        prev_week_possible = total_staff * prev_week_days if total_staff > 0 else 1
        weekly_data['previous'].append(round(len(prev_week_records) / prev_week_possible * 100, 1) if prev_week_possible > 0 else 0)
    
    # Rankings
    staff_stats = []
    for staff_member in staff_list:
        staff_records = [a for a in attendance_records if a.staff_id == staff_member.id]
        s_present = len(staff_records)
        s_late = len([a for a in staff_records if a.late_minutes and a.late_minutes > 0])
        s_total_late = sum(a.late_minutes or 0 for a in staff_records)
        s_early = len([a for a in staff_records if a.check_in and (a.late_minutes is None or a.late_minutes == 0) and a.check_in.hour < 8])
        
        # Previous period stats for comparison
        prev_staff_records = [a for a in prev_attendance if a.staff_id == staff_member.id]
        prev_s_present = len(prev_staff_records)
        
        staff_stats.append({
            'staff': staff_member,
            'present': s_present,
            'late': s_late,
            'on_time': s_present - s_late,
            'total_late_mins': s_total_late,
            'early_arrivals': s_early,
            'attendance_rate': round(s_present / working_days * 100, 1) if working_days > 0 else 0,
            'punctuality_rate': round((s_present - s_late) / s_present * 100, 1) if s_present > 0 else 100,
            'improvement': s_present - prev_s_present
        })
    
    top_performers = sorted(staff_stats, key=lambda x: (x['attendance_rate'], x['punctuality_rate']), reverse=True)[:5]
    needs_attention = sorted(staff_stats, key=lambda x: (x['attendance_rate'], x['punctuality_rate']))[:5]
    early_arrivals = sorted(staff_stats, key=lambda x: x['early_arrivals'], reverse=True)[:5]
    perfect_attendance = [s for s in staff_stats if s['attendance_rate'] == 100 and s['punctuality_rate'] == 100][:5]
    most_improved = sorted(staff_stats, key=lambda x: x['improvement'], reverse=True)[:5]
    
    # Calculate streaks
    for stat in staff_stats:
        streak = 0
        check_date = date_end
        while check_date >= date_start:
            day_record = [a for a in attendance_records if a.staff_id == stat['staff'].id and a.date == check_date and (a.late_minutes is None or a.late_minutes == 0)]
            if day_record:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break
        stat['streak'] = streak
    
    on_time_streaks = sorted(staff_stats, key=lambda x: x['streak'], reverse=True)[:5]
    
    # Get filter options
    organizations = Organization.query.filter_by(is_active=True).all()
    schools = School.query.filter_by(is_active=True).all()
    
    # Get departments based on user's organization
    if current_user.role == 'super_admin':
        all_departments = list(set(s.department for s in Staff.query.filter(Staff.department.isnot(None)).all() if s.department))
    elif current_user.role == 'org_admin' and current_user.organization_id:
        org_departments = Department.query.filter_by(organization_id=current_user.organization_id).all()
        all_departments = [d.name for d in org_departments]
    elif current_user.school_id:
        school_obj = School.query.get(current_user.school_id)
        if school_obj:
            org_departments = Department.query.filter_by(organization_id=school_obj.organization_id).all()
            all_departments = [d.name for d in org_departments]
        else:
            all_departments = []
    else:
        all_departments = []
    
    # Period label
    period_labels = {
        'today': 'Today',
        'yesterday': 'Yesterday',
        'week': 'This Week',
        'month': 'This Month',
        'year': 'This Year',
        'custom': f'{date_start} to {date_end}'
    }
    
    return render_template('analytics.html',
        # Metrics
        attendance_rate=attendance_rate,
        punctuality_rate=punctuality_rate,
        total_staff=total_staff,
        present_count=present_count,
        late_count=late_count,
        on_time_count=on_time_count,
        avg_late_minutes=avg_late_minutes,
        avg_overtime=avg_overtime,
        total_overtime=total_overtime_minutes,
        
        # Trends
        attendance_trend=attendance_trend,
        punctuality_trend=punctuality_trend,
        attendance_change=attendance_trend,
        punctuality_change=punctuality_trend,
        
        # Chart data
        trend_data=trend_data,
        late_by_day=late_by_day,
        dept_data=dept_data,
        branch_data=branch_data,
        arrival_data=arrival_data,
        present_absent=present_absent,
        weekly_data=weekly_data,
        
        # Rankings
        top_performers=top_performers,
        needs_attention=needs_attention,
        early_arrivals=early_arrivals,
        perfect_attendance=perfect_attendance,
        most_improved=most_improved,
        on_time_streaks=on_time_streaks,
        
        # Filters
        organizations=organizations,
        schools=schools,
        departments=all_departments,
        period=period,
        period_label=period_labels.get(period, period),
        start_date=start_date,
        end_date=end_date,
        selected_school=school_id,
        selected_org=organization_id,
        selected_department=department
    )


@app.route('/reports/analytics/pdf')
@login_required
def analytics_pdf():
    period = request.args.get('period', 'month')
    school_id = request.args.get('school_id')
    organization_id = request.args.get('organization_id')
    department = request.args.get('department')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    date_start, date_end = get_date_range(period, start_date, end_date)
    
    # Build staff query
    if current_user.role == 'super_admin':
        staff_query = Staff.query.filter_by(is_active=True)
        if organization_id:
            school_ids_list = [s.id for s in School.query.filter_by(organization_id=organization_id).all()]
            staff_query = staff_query.filter(Staff.school_id.in_(school_ids_list))
    elif current_user.role == 'org_admin' and current_user.organization_id:
        school_ids_list = [s.id for s in School.query.filter_by(organization_id=current_user.organization_id).all()]
        staff_query = Staff.query.filter(Staff.school_id.in_(school_ids_list), Staff.is_active==True)
    elif current_user.school_id:
        staff_query = Staff.query.filter_by(school_id=current_user.school_id, is_active=True)
    else:
        staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    if department:
        staff_query = staff_query.filter_by(department=department)
    
    staff_list = staff_query.all()
    staff_ids = [s.id for s in staff_list]
    total_staff = len(staff_list)
    
    # Get attendance records
    attendance_records = Attendance.query.filter(
        Attendance.staff_id.in_(staff_ids),
        Attendance.date >= date_start,
        Attendance.date <= date_end
    ).all() if staff_ids else []
    
    # Calculate metrics
    total_days = (date_end - date_start).days + 1
    working_days = total_days
    total_possible = total_staff * working_days if total_staff > 0 else 1
    
    present_count = len(attendance_records)
    late_count = len([a for a in attendance_records if a.late_minutes and a.late_minutes > 0])
    on_time_count = present_count - late_count
    
    total_late_minutes = sum(a.late_minutes or 0 for a in attendance_records)
    total_overtime_minutes = sum(a.overtime_minutes or 0 for a in attendance_records)
    
    attendance_rate = round(present_count / total_possible * 100, 1) if total_possible > 0 else 0
    punctuality_rate = round(on_time_count / present_count * 100, 1) if present_count > 0 else 100
    avg_late_minutes = round(total_late_minutes / late_count, 1) if late_count > 0 else 0
    avg_overtime = round(total_overtime_minutes / present_count, 1) if present_count > 0 else 0
    
    # Rankings
    staff_stats = []
    for staff_member in staff_list:
        staff_records = [a for a in attendance_records if a.staff_id == staff_member.id]
        s_present = len(staff_records)
        s_late = len([a for a in staff_records if a.late_minutes and a.late_minutes > 0])
        s_early = len([a for a in staff_records if a.check_in and (a.late_minutes is None or a.late_minutes == 0) and a.check_in.hour < 8])
        
        staff_stats.append({
            'staff': staff_member,
            'present': s_present,
            'late': s_late,
            'on_time': s_present - s_late,
            'early_arrivals': s_early,
            'attendance_rate': round(s_present / working_days * 100, 1) if working_days > 0 else 0,
            'punctuality_rate': round((s_present - s_late) / s_present * 100, 1) if s_present > 0 else 100
        })
    
    top_performers = sorted(staff_stats, key=lambda x: (x['attendance_rate'], x['punctuality_rate']), reverse=True)[:5]
    needs_attention = sorted(staff_stats, key=lambda x: (x['attendance_rate'], x['punctuality_rate']))[:5]
    
    period_labels = {
        'today': 'Today',
        'yesterday': 'Yesterday',
        'week': 'This Week',
        'month': 'This Month',
        'year': 'This Year',
        'custom': f'{date_start} to {date_end}'
    }
    
    html = render_template('analytics_pdf.html',
        generated_date=datetime.now().strftime('%B %d, %Y at %I:%M %p'),
        period_label=period_labels.get(period, period),
        attendance_rate=attendance_rate,
        punctuality_rate=punctuality_rate,
        total_staff=total_staff,
        late_count=late_count,
        on_time_count=on_time_count,
        avg_late_minutes=avg_late_minutes,
        total_overtime=total_overtime_minutes,
        avg_overtime=avg_overtime,
        top_performers=top_performers,
        needs_attention=needs_attention
    )
    
    pdf = BytesIO()
    pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=pdf)
    pdf.seek(0)
    
    response = make_response(pdf.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=analytics_report_{date.today()}.pdf'
    
    return response


# ============== SETTINGS ==============

@app.route('/settings')
@login_required
def settings():
    settings_dict = {}
    try:
        all_settings = SystemSettings.query.all()
        for s in all_settings:
            settings_dict[s.key] = s.value
    except:
        pass
    
    stats = {
        'organizations': Organization.query.count(),
        'staff': Staff.query.count(),
        'attendance': Attendance.query.count()
    }
    
    return render_template('settings.html', settings=settings_dict, stats=stats)


@app.route('/settings/save', methods=['POST'])
@login_required
def save_settings():
    if current_user.role not in ['super_admin', 'org_admin']:
        flash('Access denied', 'danger')
        return redirect(url_for('settings'))
    
    settings_to_save = ['work_start_time', 'work_end_time', 'late_threshold', 
                        'early_threshold', 'overtime_threshold']
    
    for key in settings_to_save:
        value = request.form.get(key)
        if value:
            setting = SystemSettings.query.filter_by(key=key).first()
            if setting:
                setting.value = value
            else:
                setting = SystemSettings(key=key, value=value)
                db.session.add(setting)
    
    db.session.commit()
    flash('Settings saved successfully!', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/regenerate-api-key', methods=['POST'])
@login_required
def regenerate_api_key():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('settings'))
    
    import secrets
    new_key = secrets.token_hex(32)
    
    setting = SystemSettings.query.filter_by(key='api_key').first()
    if setting:
        setting.value = new_key
    else:
        setting = SystemSettings(key='api_key', value=new_key)
        db.session.add(setting)
    
    db.session.commit()
    flash('API key regenerated successfully!', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/clear-attendance', methods=['POST'])
@login_required
def clear_attendance():
    if current_user.role != 'super_admin':
        flash('Access denied', 'danger')
        return redirect(url_for('settings'))
    
    Attendance.query.delete()
    db.session.commit()
    flash('All attendance records cleared!', 'success')
    return redirect(url_for('settings'))


# ============== API ==============

@app.route('/api/attendance/sync', methods=['POST'])
def api_sync_attendance():
    api_key = request.headers.get('X-API-Key')
    
    try:
        stored_key = SystemSettings.query.filter_by(key='api_key').first()
        if not stored_key or api_key != stored_key.value:
            return jsonify({'error': 'Invalid API key'}), 401
    except:
        return jsonify({'error': 'API not configured'}), 500
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    records = data if isinstance(data, list) else [data]
    created = 0
    errors = []
    
    for record in records:
        try:
            staff = Staff.query.filter_by(staff_id=record.get('staff_id')).first()
            if not staff:
                errors.append(f"Staff {record.get('staff_id')} not found")
                continue
            
            attendance_date = datetime.strptime(record.get('date'), '%Y-%m-%d').date()
            
            existing = Attendance.query.filter_by(
                staff_id=staff.id,
                date=attendance_date
            ).first()
            
            if existing:
                if record.get('check_out'):
                    existing.check_out = datetime.strptime(f"{attendance_date} {record.get('check_out')}", '%Y-%m-%d %H:%M')
                    work_end = datetime.strptime(f"{attendance_date} 17:00", '%Y-%m-%d %H:%M')
                    if existing.check_out > work_end:
                        existing.overtime_minutes = int((existing.check_out - work_end).total_seconds() / 60)
            else:
                check_in = None
                late_minutes = 0
                if record.get('check_in'):
                    check_in = datetime.strptime(f"{attendance_date} {record.get('check_in')}", '%Y-%m-%d %H:%M')
                    work_start = datetime.strptime(f"{attendance_date} 08:00", '%Y-%m-%d %H:%M')
                    if check_in > work_start:
                        late_minutes = int((check_in - work_start).total_seconds() / 60)
                
                attendance = Attendance(
                    staff_id=staff.id,
                    date=attendance_date,
                    check_in=check_in,
                    status='present',
                    late_minutes=late_minutes
                )
                db.session.add(attendance)
                created += 1
            
            db.session.commit()
        except Exception as e:
            errors.append(str(e))
    
    return jsonify({
        'success': True,
        'created': created,
        'errors': errors
    })


# ============== DATABASE INIT ==============

@app.route('/init-db')
def init_db():
    db.create_all()
    
    # Create default admin if not exists
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@example.com',
            role='super_admin'
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
    
    # Create default settings
    default_settings = {
        'work_start_time': '08:00',
        'work_end_time': '17:00',
        'late_threshold': '15',
        'early_threshold': '10',
        'overtime_threshold': '30'
    }
    
    for key, value in default_settings.items():
        if not SystemSettings.query.filter_by(key=key).first():
            setting = SystemSettings(key=key, value=value)
            db.session.add(setting)
    
    db.session.commit()
    
    flash('Database initialized successfully!', 'success')
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
