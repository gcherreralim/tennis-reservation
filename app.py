from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date

app = Flask(__name__)
app.secret_key = "bfqc_tennis_res"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ----------------------- DATABASE MODELS ----------------------- #

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    time_slot = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    contact_number = db.Column(db.String(20), nullable=False)
    with_coaching = db.Column(db.Boolean, default=False)

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

# -------------------- DATE/TIME HELPERS -------------------- #

def get_time_slots():
    return [f"{hour:02}:00" for hour in range(6, 20)]  # 6AM to 8PM

def get_calendar_dates(week_offset=0):
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    sunday = today - timedelta(days=today.weekday() + 1) if today.weekday() != 6 else today
    start = sunday + timedelta(weeks=week_offset)
    return [start + timedelta(days=i) for i in range(7)]  # Sunday to Saturday

# ------------------------ ROUTES ------------------------ #

@app.route("/", methods=["GET", "POST"])
def index():
    error_message = None

    if request.method == "POST":
        name = request.form["name"]
        contact = request.form["contact"]
        date_str = request.form["date"]
        time_slot = request.form["time_slot"]
        with_coaching = request.form.get("with_coaching") == "yes"

        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        if selected_date < date.today():
            error_message = "Cannot reserve past dates."
        else:
            existing = Reservation.query.filter_by(date=selected_date, time_slot=time_slot).first()
            if existing:
                error_message = "This time slot is already reserved. Please choose another."
            else:
                user_reservations = Reservation.query.filter_by(date=selected_date, contact_number=contact).count()
                if user_reservations >= 2:
                    error_message = "You can only book up to 2 hours per day."
                else:
                    new_res = Reservation(
                        date=selected_date,
                        time_slot=time_slot,
                        name=name,
                        contact_number=contact,
                        with_coaching=with_coaching
                    )
                    db.session.add(new_res)
                    db.session.commit()
                    return redirect(url_for("index"))

    week_offset = int(request.args.get("week_offset", 0))
    dates = get_calendar_dates(week_offset)
    slots = get_time_slots()
    reservations = Reservation.query.filter(Reservation.date.in_(dates)).all()
    reservations_dict = {}

    def mask_name(full_name):
        if " " in full_name:
            first, last = full_name.split(" ", 1)
            return f"{first} {last[0]}"
        return full_name
    

    for res in reservations:
        key = (res.date.isoformat(), res.time_slot)
        if "admin" in session:
            reservations_dict[key] = res 
        else:
            reservations_dict[key] = {
                "masked_name": mask_name(res.name),
                "with_coaching": res.with_coaching
            }

    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    selected_date = today  # default for slot availability map

    # For slot filtering in dropdown
    slot_available_map = {
        d.isoformat(): {
            slot: not Reservation.query.filter_by(date=d, time_slot=slot).first()
            for slot in slots
        }
        for d in dates
    }

    return render_template(
        "index.html",
        reservations_dict=reservations_dict,
        dates=dates,
        time_slots=slots,
        week_offset=week_offset,
        is_admin="admin" in session,
        today=today,
        today_str=today_str,
        error_message=error_message,
        slot_available_map=slot_available_map,
        selected_date=selected_date
    )

# ------------------------ ADMIN LOGIN ------------------------ #

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if "admin" not in session:
        return redirect(url_for("login"))
    
    today = date.today()
    now = datetime.now()
    reservations = Reservation.query.order_by(Reservation.date, Reservation.time_slot).all()
    upcoming = [r for r in reservations if datetime.combine(r.date, datetime.strptime(r.time_slot, "%H:%M").time()) >= now]
    completed = [r for r in reservations if datetime.combine(r.date, datetime.strptime(r.time_slot, "%H:%M").time()) < now]
    
    time_slots = get_time_slots()
    reserved_slots = {(r.date.isoformat(), r.time_slot) for r in reservations}

    return render_template("admin.html", reservations=upcoming, completed=completed, time_slots=time_slots, reserved_slots=reserved_slots, today=today, now=now)

@app.route("/edit_modal", methods=["POST"])
def edit_reservation_modal():
    if "admin" not in session:
        return redirect(url_for("login"))

    res_id = request.form["res_id"]
    reservation = Reservation.query.get_or_404(res_id)

    new_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
    new_time_slot = request.form["time_slot"]

    new_datetime = datetime.combine(new_date, datetime.strptime(new_time_slot, "%H:%M").time())
    if new_datetime < datetime.now():
        flash("Cannot edit to a past time slot.", "error")
        return redirect(url_for("admin"))

    existing = Reservation.query.filter_by(date=new_date, time_slot=new_time_slot).first()
    if existing and existing.id != reservation.id:
        flash("That time slot is already reserved.", "error")
        return redirect(url_for("admin"))

    reservation.name = request.form["name"]
    reservation.contact_number = request.form["contact"]
    reservation.date = new_date
    reservation.time_slot = new_time_slot
    reservation.with_coaching = request.form["with_coaching"] == "yes"

    db.session.commit()
    flash("Reservation updated successfully!", "success")
    return redirect(url_for("admin"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = Admin.query.filter_by(username=request.form["username"]).first()
        if user and check_password_hash(user.password_hash, request.form["password"]):
            session["admin"] = True
            return redirect(url_for("admin"))
        return "Invalid credentials."
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))

@app.route("/delete/<int:res_id>")
def delete(res_id):
    if "admin" not in session:
        return redirect(url_for("login"))
    res = Reservation.query.get_or_404(res_id)
    if res:
        db.session.delete(res)
        db.session.commit()
        flash("Reservation deleted.", "success")
    return redirect(url_for("admin"))

# ------------------------ INIT ------------------------ #

def create_tables():
    with app.app_context():
        db.create_all()
        if not Admin.query.filter_by(username="bfqc_tennis_admin").first():
            hashed = generate_password_hash("admin_bogart_123", method='pbkdf2:sha256')
            admin = Admin(username="bfqc_tennis_admin", password_hash=hashed)
            db.session.add(admin)
            db.session.commit()

if __name__ == "__main__":
    create_tables()
    app.run(debug=True)
