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

# Models
class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20), nullable=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False)
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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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

@app.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        schools = School.query.all()
        total_staff = Staff.query.filter_by(is_active=True).count()
        today_attendance = Attendance.query.filter_by(date=today).count()
        late_today = Attendance.query.filter_by(date=today, is_late=True).count()
    else:
        schools = [current_user.school] if current_user.school else []
        if current_user.school:
            total_staff = Staff.query.filter_by(school_id=current_user.school_id, is_active=True).count()
            staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
            today_attendance = Attendance.query.filter(Attendance.staff_id.in_(staff_ids), Attendance.date == today).count() if staff_ids else 0
            late_today = Attendance.query.filter(Attendance.staff_id.in_(staff_ids), Attendance.date == today, Attendance.is_late == True).count() if staff_ids else 0
        else:
            total_staff = 0
            today_attendance = 0
            late_today = 0
    
    return render_template('dashboard.html', schools=schools, total_staff=total_staff, today_attendance=today_attendance, late_today=late_today)

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
        api_key = secrets.token_hex(32)
        
        school = School(name=name, short_name=short_name, api_key=api_key)
        
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        
        db.session.add(school)
        db.session.commit()
        flash('School added successfully!', 'success')
        return redirect(url_for('schools'))
    
    return render_template('add_school.html')

@app.route('/schools/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('super_admin')
def edit_school(id):
    school = School.query.get_or_404(id)
    
    if request.method == 'POST':
        school.name = request.form.get('name')
        school.short_name = request.form.get('short_name')
        
        for day in ['mon', 'tue', 'wed', 'thu', 'fri']:
            start = request.form.get(f'schedule_{day}_start', '08:00')
            end = request.form.get(f'schedule_{day}_end', '17:00')
            setattr(school, f'schedule_{day}_start', start)
            setattr(school, f'schedule_{day}_end', end)
        
        db.session.commit()
        flash('School updated successfully!', 'success')
        return redirect(url_for('schools'))
    
    return render_template('edit_school.html', school=school)

@app.route('/schools/delete/<int:id>')
@login_required
@role_required('super_admin')
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('School deleted successfully!', 'success')
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
    
    if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer']:
        staff = Staff.query.all()
    else:
        staff = Staff.query.filter_by(school_id=current_user.school_id).all()
    
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
        school_id = request.form.get('school_id') or None
        
        existing = User.query.filter_by(username=username).first()
        if existing:
            flash('Username already exists!', 'danger')
            return redirect(url_for('add_user'))
        
        user = User(username=username, role=role, school_id=school_id)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('User added successfully!', 'success')
        return redirect(url_for('users'))
    
    schools = School.query.all()
    roles = ['super_admin', 'hr_viewer', 'ceo_viewer', 'school_admin', 'staff']
    return render_template('add_user.html', schools=schools, roles=roles)

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

# Reports
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
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    
    attendance = query.order_by(Attendance.date.desc()).all()
    schools = School.query.all() if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer'] else []
    
    return render_template('attendance_report.html', 
                         attendance=attendance, 
                         schools=schools, 
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
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    
    attendance = query.order_by(Attendance.date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'School', 'Department', 'Sign In', 'Sign Out', 'Status', 'Late Minutes', 'Overtime Minutes'])
    
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
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
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
    schools = School.query.all() if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer'] else []
    
    return render_template('late_report.html', 
                         late_staff=late_staff, 
                         schools=schools, 
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
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
    staff_list_data = staff_query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Staff ID', 'Name', 'School', 'Department', 'Times Late', '% Punctuality', '% Lateness'])
    
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
        school_name = 'all schools'
    
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
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
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
    
    schools = School.query.all() if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer'] else []
    
    return render_template('absent_report.html', 
                         absent_records=absent_records, 
                         schools=schools, 
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
    
    staff_query = Staff.query.filter_by(is_active=True)
    
    if school_id:
        staff_query = staff_query.filter_by(school_id=school_id)
    elif current_user.role == 'school_admin':
        staff_query = staff_query.filter_by(school_id=current_user.school_id)
    
    all_staff = staff_query.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'School', 'Department'])
    
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
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    
    overtime = query.order_by(Attendance.date.desc()).all()
    schools = School.query.all() if current_user.role in ['super_admin', 'hr_viewer', 'ceo_viewer'] else []
    
    return render_template('overtime_report.html', 
                         overtime=overtime, 
                         schools=schools, 
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
    
    if school_id:
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    elif current_user.role == 'school_admin':
        staff_ids = [s.id for s in Staff.query.filter_by(school_id=current_user.school_id).all()]
        query = query.filter(Attendance.staff_id.in_(staff_ids)) if staff_ids else query.filter(False)
    
    overtime = query.order_by(Attendance.date.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Staff ID', 'Name', 'School', 'Department', 'Sign Out', 'Overtime (mins)'])
    
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

# API for Kiosk
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
    
    if action == 'get_staff':
        staff = Staff.query.filter_by(school_id=school.id, is_active=True).all()
        staff_list_data = [{'id': s.staff_id, 'name': s.name, 'department': s.department} for s in staff]
        response = jsonify({'staff': staff_list_data, 'school_name': school.name})
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
        
        response = jsonify({'success': True, 'synced': synced, 'errors': errors})
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
        
        response = jsonify({'staff_name': staff.name, 'status': status})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    response = jsonify({'error': 'Invalid action'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 400

@app.route('/init-db')
def init_db():
    try:
        db.create_all()
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
