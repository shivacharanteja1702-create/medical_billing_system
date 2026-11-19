from functools import wraps
from datetime import datetime
from pathlib import Path
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = "replace-this-with-a-long-random-secret-before-deployment"
BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "medical_billing.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'staff'
    );
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        age INTEGER,
        gender TEXT,
        phone TEXT,
        email TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT,
        price REAL NOT NULL CHECK(price >= 0)
    );
    CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL,
        bill_date TEXT NOT NULL,
        discount REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL,
        paid REAL NOT NULL DEFAULT 0,
        notes TEXT,
        FOREIGN KEY(patient_id) REFERENCES patients(id)
    );
    CREATE TABLE IF NOT EXISTS bill_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER NOT NULL,
        service_id INTEGER,
        service_name TEXT NOT NULL,
        price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        FOREIGN KEY(bill_id) REFERENCES bills(id) ON DELETE CASCADE,
        FOREIGN KEY(service_id) REFERENCES services(id)
    );
    """)
    admin = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    if not admin:
        db.execute(
            "INSERT INTO users(username, password_hash, role) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "admin")
        )
    if db.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO services(name, description, price) VALUES (?, ?, ?)",
            [
                ("General Consultation", "Basic doctor consultation", 300),
                ("Blood Test", "Basic laboratory blood test", 250),
                ("X-Ray", "Standard X-ray service", 500),
                ("ECG", "Electrocardiogram test", 400),
                ("Dressing", "Basic wound dressing", 180),
            ]
        )
    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def index():
    return redirect(url_for("dashboard" if session.get("user_id") else "login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(username) < 3 or len(password) < 6:
            flash("Username must have at least 3 characters and password at least 6.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        else:
            try:
                db = get_db()
                db.execute(
                    "INSERT INTO users(username, password_hash, role) VALUES (?, ?, 'staff')",
                    (username, generate_password_hash(password))
                )
                db.commit()
                flash("Registration successful. Please sign in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That username is already registered.", "danger")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    stats = {
        "patients": db.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
        "bills": db.execute("SELECT COUNT(*) FROM bills").fetchone()[0],
        "revenue": db.execute("SELECT COALESCE(SUM(paid), 0) FROM bills").fetchone()[0],
        "outstanding": db.execute("SELECT COALESCE(SUM(total - paid), 0) FROM bills").fetchone()[0],
    }
    recent = db.execute("""
        SELECT bills.*, patients.name AS patient_name
        FROM bills JOIN patients ON patients.id = bills.patient_id
        ORDER BY bills.id DESC LIMIT 6
    """).fetchall()
    return render_template("dashboard.html", stats=stats, recent=recent)


@app.route("/patients", methods=["GET", "POST"])
@login_required
def patients():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Patient name is required.", "danger")
        else:
            age_raw = request.form.get("age", "").strip()
            try:
                age = int(age_raw) if age_raw else None
                if age is not None and not 0 <= age <= 120:
                    raise ValueError
                db.execute("""
                    INSERT INTO patients(name, age, gender, phone, email, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (name, age, request.form.get("gender", ""),
                      request.form.get("phone", "").strip(),
                      request.form.get("email", "").strip(),
                      datetime.now().strftime("%Y-%m-%d %H:%M")))
                db.commit()
                flash("Patient added successfully.", "success")
                return redirect(url_for("patients"))
            except (ValueError, sqlite3.Error):
                db.rollback()
                flash("Please enter a valid patient age and details.", "danger")
    search = request.args.get("q", "").strip()
    rows = db.execute("""
        SELECT * FROM patients
        WHERE name LIKE ? OR phone LIKE ? OR email LIKE ?
        ORDER BY id DESC
    """, (f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
    return render_template("patients.html", patients=rows, search=search)


@app.route("/services", methods=["GET", "POST"])
@login_required
def services():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            price = float(request.form.get("price", ""))
            if not name or price < 0:
                raise ValueError
            db.execute(
                "INSERT INTO services(name, description, price) VALUES (?, ?, ?)",
                (name, request.form.get("description", "").strip(), price)
            )
            db.commit()
            flash("Service added successfully.", "success")
            return redirect(url_for("services"))
        except ValueError:
            flash("Enter a service name and a valid non-negative price.", "danger")
        except sqlite3.IntegrityError:
            flash("A service with that name already exists.", "danger")
    rows = db.execute("SELECT * FROM services ORDER BY name").fetchall()
    return render_template("services.html", services=rows)


@app.route("/bills/new", methods=["GET", "POST"])
@login_required
def new_bill():
    db = get_db()
    patients_list = db.execute("SELECT * FROM patients ORDER BY name").fetchall()
    services_list = db.execute("SELECT * FROM services ORDER BY name").fetchall()

    if request.method == "POST":
        try:
            patient_id = int(request.form.get("patient_id", ""))
            patient = db.execute("SELECT id FROM patients WHERE id = ?", (patient_id,)).fetchone()
            if not patient:
                raise ValueError("Choose a valid patient.")

            discount = round(float(request.form.get("discount") or 0), 2)
            paid = round(float(request.form.get("paid") or 0), 2)
            service_ids = request.form.getlist("service_ids")
            if not service_ids:
                raise ValueError("Select at least one service.")
            if discount < 0 or paid < 0:
                raise ValueError("Discount and payment cannot be negative.")

            selected = []
            subtotal = 0.0
            seen = set()
            for raw_id in service_ids:
                service_id = int(raw_id)
                if service_id in seen:
                    continue
                seen.add(service_id)
                service = db.execute(
                    "SELECT id, name, price FROM services WHERE id = ?", (service_id,)
                ).fetchone()
                if not service:
                    raise ValueError("One selected service no longer exists.")
                qty = int(request.form.get(f"quantity_{service_id}", "1") or 1)
                if qty < 1 or qty > 1000:
                    raise ValueError("Each quantity must be between 1 and 1000.")
                selected.append((service, qty))
                subtotal += float(service["price"]) * qty

            subtotal = round(subtotal, 2)
            if discount > subtotal:
                raise ValueError("Discount cannot be greater than the subtotal.")
            total = round(subtotal - discount, 2)
            if paid > total:
                raise ValueError("Initial payment cannot be greater than the invoice total.")

            # Save the bill and all its line items as one atomic transaction.
            db.execute("BEGIN")
            cursor = db.execute("""
                INSERT INTO bills(patient_id, bill_date, discount, total, paid, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (patient_id, datetime.now().strftime("%Y-%m-%d %H:%M"),
                  discount, total, paid, request.form.get("notes", "").strip()))
            bill_id = cursor.lastrowid

            db.executemany("""
                INSERT INTO bill_items(bill_id, service_id, service_name, price, quantity)
                VALUES (?, ?, ?, ?, ?)
            """, [(bill_id, s["id"], s["name"], float(s["price"]), qty)
                  for s, qty in selected])

            db.commit()
            flash(f"Invoice #{bill_id} generated and saved successfully.", "success")
            return redirect(url_for("bill_detail", bill_id=bill_id))

        except (ValueError, TypeError) as exc:
            db.rollback()
            flash(str(exc) or "Please check all invoice details.", "danger")
        except sqlite3.Error:
            db.rollback()
            app.logger.exception("Invoice database save failed")
            flash("The invoice could not be saved. No data was partially stored. Check the database and try again.", "danger")

    return render_template("new_bill.html", patients=patients_list, services=services_list)


@app.route("/bills")
@login_required
def bills():
    rows = get_db().execute("""
        SELECT bills.*, patients.name AS patient_name
        FROM bills JOIN patients ON patients.id = bills.patient_id
        ORDER BY bills.id DESC
    """).fetchall()
    return render_template("bills.html", bills=rows)


@app.route("/bills/<int:bill_id>")
@login_required
def bill_detail(bill_id):
    db = get_db()
    bill = db.execute("""
        SELECT bills.*, patients.name AS patient_name, patients.phone, patients.email
        FROM bills JOIN patients ON patients.id = bills.patient_id
        WHERE bills.id = ?
    """, (bill_id,)).fetchone()
    if not bill:
        flash("Bill not found.", "danger")
        return redirect(url_for("bills"))
    items = db.execute("SELECT * FROM bill_items WHERE bill_id = ? ORDER BY id", (bill_id,)).fetchall()
    return render_template("bill_detail.html", bill=bill, items=items)


@app.route("/bills/<int:bill_id>/payment", methods=["POST"])
@login_required
def add_payment(bill_id):
    db = get_db()
    bill = db.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    try:
        amount = round(float(request.form.get("amount", "0")), 2)
        if not bill or amount <= 0 or amount > round(bill["total"] - bill["paid"], 2):
            raise ValueError
        db.execute("UPDATE bills SET paid = paid + ? WHERE id = ?", (amount, bill_id))
        db.commit()
        flash("Payment recorded successfully.", "success")
    except ValueError:
        db.rollback()
        flash("Enter a payment amount greater than zero and within the outstanding balance.", "danger")
    return redirect(url_for("bill_detail", bill_id=bill_id))


@app.route("/reports")
@login_required
def reports():
    db = get_db()
    summary = db.execute("""
        SELECT COUNT(*) AS bill_count,
               COALESCE(SUM(total), 0) AS billed,
               COALESCE(SUM(paid), 0) AS received,
               COALESCE(SUM(total - paid), 0) AS outstanding
        FROM bills
    """).fetchone()
    report_bills = db.execute("""
        SELECT bills.id, bills.bill_date, bills.total, bills.paid,
               (bills.total - bills.paid) AS balance,
               patients.name AS patient_name
        FROM bills JOIN patients ON patients.id = bills.patient_id
        ORDER BY bills.id DESC
    """).fetchall()
    return render_template("reports.html", summary=summary, bills=report_bills)


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
