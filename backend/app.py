import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
import csv
import io
import random
import secrets
import string
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
db_url = os.getenv("DATABASE_URL", "sqlite:///polarx.db")
if db_url.startswith("postgres://"):
    db_url = "postgresql+psycopg2://" + db_url[len("postgres://"): ]
elif db_url.startswith("postgresql://"):
    db_url = "postgresql+psycopg2://" + db_url[len("postgresql://"): ]
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
CORS(app, origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",")])

ROLES = {"ADMIN", "MANAGER", "EXPEDITIONER", "VIEWER"}
ASSET_STATUSES = {"AVAILABLE", "IN_USE", "MAINTENANCE", "LOST"}
EXPEDITION_STATUSES = {"PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="VIEWER")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)

class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_code = db.Column(db.String(60), unique=True, nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    min_quantity = db.Column(db.Integer, default=1)
    status = db.Column(db.String(30), default="AVAILABLE")
    location = db.Column(db.String(180), default="Base Camp")
    last_service = db.Column(db.Date)
    notes = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Expedition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    region = db.Column(db.String(180), nullable=False)
    leader = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(30), default="PLANNED")
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class ExpeditionAsset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expedition_id = db.Column(db.Integer, db.ForeignKey("expedition.id"), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)

class SensorReading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("asset.id"), nullable=True)
    expedition_id = db.Column(db.Integer, db.ForeignKey("expedition.id"), nullable=True)
    sensor_type = db.Column(db.String(60), nullable=False)
    value = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(30), nullable=False)
    recorded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(180))
    action = db.Column(db.String(120))
    entity = db.Column(db.String(80))
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

def iso_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()

def user_dict(u):
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "must_change_password": bool(u.must_change_password)}

def public_user_dict(u):
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "created_at": u.created_at.isoformat() if u.created_at else None, "must_change_password": bool(u.must_change_password)}

def generate_temp_password(length=12):
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password) and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password) and any(c in "!@#$%" for c in password)):
            return password

def asset_dict(a):
    return {
        "id": a.id, "asset_code": a.asset_code, "name": a.name, "category": a.category,
        "quantity": a.quantity, "min_quantity": a.min_quantity, "status": a.status,
        "location": a.location, "last_service": a.last_service.isoformat() if a.last_service else None,
        "notes": a.notes or "", "updated_at": a.updated_at.isoformat() if a.updated_at else None
    }

def expedition_dict(e):
    return {
        "id": e.id, "name": e.name, "region": e.region, "leader": e.leader,
        "start_date": e.start_date.isoformat() if e.start_date else None,
        "end_date": e.end_date.isoformat() if e.end_date else None,
        "status": e.status, "latitude": e.latitude, "longitude": e.longitude,
        "notes": e.notes or ""
    }

def token_for(user):
    payload = {
        "sub": str(user.id), "email": user.email, "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12)
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

def current_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(header[7:], app.config["SECRET_KEY"], algorithms=["HS256"])
        return db.session.get(User, int(payload["sub"]))
    except Exception:
        return None

def auth(required_roles=None):
    required_roles = set(required_roles or [])
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "Authentication required"}), 401
            if required_roles and user.role not in required_roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            request.user = user
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def log(action, entity, entity_id=None, details=""):
    db.session.add(AuditLog(
        user_email=getattr(request, "user", None).email if getattr(request, "user", None) else "system",
        action=action, entity=entity, entity_id=entity_id, details=details
    ))

@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "POLAR-X"})

@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.get("/<path:path>")
def static_files(path):
    full = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(full):
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.post("/api/auth/login")
def login():
    data = request.get_json() or {}
    user = User.query.filter_by(email=data.get("email", "").lower().strip()).first()
    if not user or not check_password_hash(user.password_hash, data.get("password", "")):
        return jsonify({"error": "Invalid email or password"}), 401
    return jsonify({"token": token_for(user), "user": user_dict(user)})

@app.post("/api/auth/change-password")
@auth()
def change_password():
    data = request.get_json() or {}
    current = data.get("current_password", "")
    new_password = data.get("new_password", "")
    if not check_password_hash(request.user.password_hash, current):
        return jsonify({"error": "Current password is incorrect"}), 400
    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400
    if new_password == current:
        return jsonify({"error": "New password must be different from the current password"}), 400
    request.user.password_hash = generate_password_hash(new_password)
    request.user.must_change_password = False
    log("CHANGE_PASSWORD", "User", request.user.id, "Password changed")
    db.session.commit()
    return jsonify({"ok": True, "user": user_dict(request.user)})

@app.post("/api/auth/register")
def register():
    data = request.get_json() or {}
    email = data.get("email", "").lower().strip()
    if not email or not data.get("password") or not data.get("name"):
        return jsonify({"error": "Name, email and password are required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409
    role = data.get("role", "VIEWER")
    if role not in ROLES:
        role = "VIEWER"
    user = User(name=data["name"], email=email, role=role,
                password_hash=generate_password_hash(data["password"]))
    db.session.add(user); db.session.commit()
    return jsonify({"token": token_for(user), "user": user_dict(user)}), 201

@app.get("/api/users")
@auth({"ADMIN"})
def list_users():
    return jsonify([public_user_dict(u) for u in User.query.order_by(User.created_at.desc()).all()])

@app.post("/api/users")
@auth({"ADMIN"})
def create_user():
    data = request.get_json() or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).lower().strip()
    role = str(data.get("role", "VIEWER")).upper().strip()
    password = str(data.get("password", "")).strip()
    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400
    if role not in ROLES:
        return jsonify({"error": "Invalid role"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409
    generated = not password
    if generated:
        password = generate_temp_password()
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    user = User(name=name, email=email, role=role, password_hash=generate_password_hash(password), must_change_password=True)
    db.session.add(user)
    db.session.flush()
    log("CREATE", "User", user.id, f"Created {email} with role {role}")
    db.session.commit()
    return jsonify({"user": public_user_dict(user), "temporary_password": password, "generated": generated}), 201

@app.post("/api/users/<int:user_id>/reset-password")
@auth({"ADMIN"})
def reset_user_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    password = generate_temp_password()
    user.password_hash = generate_password_hash(password)
    user.must_change_password = True
    log("RESET_PASSWORD", "User", user.id, f"Password reset for {user.email}")
    db.session.commit()
    return jsonify({"user": public_user_dict(user), "temporary_password": password})

@app.put("/api/users/<int:user_id>")
@auth({"ADMIN"})
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    data = request.get_json() or {}
    if "name" in data and str(data["name"]).strip():
        user.name = str(data["name"]).strip()
    if "role" in data:
        role = str(data["role"]).upper().strip()
        if role not in ROLES:
            return jsonify({"error": "Invalid role"}), 400
        user.role = role
    log("UPDATE", "User", user.id, f"Updated {user.email}")
    db.session.commit()
    return jsonify(public_user_dict(user))

@app.get("/api/me")
@auth()
def me():
    return jsonify(user_dict(request.user))

@app.get("/api/dashboard")
@auth()
def dashboard():
    assets = Asset.query.all()
    alerts = []
    for a in assets:
        if a.quantity <= a.min_quantity:
            alerts.append({"type": "LOW_STOCK", "severity": "HIGH", "message": f"{a.name} is at/below minimum stock ({a.quantity})"})
        if a.status == "MAINTENANCE":
            alerts.append({"type": "MAINTENANCE", "severity": "MEDIUM", "message": f"{a.name} is under maintenance"})
        if a.status == "LOST":
            alerts.append({"type": "LOST", "severity": "CRITICAL", "message": f"{a.name} is marked lost"})
    expeditions = Expedition.query.order_by(Expedition.created_at.desc()).all()
    return jsonify({
        "stats": {
            "total_assets": len(assets),
            "available": sum(a.status == "AVAILABLE" for a in assets),
            "in_use": sum(a.status == "IN_USE" for a in assets),
            "maintenance": sum(a.status == "MAINTENANCE" for a in assets),
            "lost": sum(a.status == "LOST" for a in assets),
            "active_expeditions": sum(e.status == "ACTIVE" for e in expeditions)
        },
        "alerts": alerts[:30],
        "recent_expeditions": [expedition_dict(e) for e in expeditions[:5]]
    })

@app.get("/api/assets")
@auth()
def assets():
    q = request.args.get("q", "").lower()
    status = request.args.get("status", "")
    category = request.args.get("category", "")
    query = Asset.query
    if q:
        query = query.filter(db.or_(Asset.name.ilike(f"%{q}%"), Asset.asset_code.ilike(f"%{q}%"), Asset.location.ilike(f"%{q}%")))
    if status:
        query = query.filter_by(status=status)
    if category:
        query = query.filter_by(category=category)
    return jsonify([asset_dict(a) for a in query.order_by(Asset.updated_at.desc()).all()])

@app.post("/api/assets")
@auth({"ADMIN", "MANAGER", "EXPEDITIONER"})
def create_asset():
    data = request.get_json() or {}
    if not data.get("asset_code") or not data.get("name") or not data.get("category"):
        return jsonify({"error": "asset_code, name and category are required"}), 400
    if Asset.query.filter_by(asset_code=data["asset_code"]).first():
        return jsonify({"error": "Asset code already exists"}), 409
    a = Asset(
        asset_code=data["asset_code"], name=data["name"], category=data["category"],
        quantity=int(data.get("quantity", 1)), min_quantity=int(data.get("min_quantity", 1)),
        status=data.get("status", "AVAILABLE"), location=data.get("location", "Base Camp"),
        last_service=iso_date(data.get("last_service")), notes=data.get("notes", "")
    )
    if a.status not in ASSET_STATUSES: a.status = "AVAILABLE"
    db.session.add(a); db.session.flush(); log("CREATE", "Asset", a.id, a.name); db.session.commit()
    return jsonify(asset_dict(a)), 201

@app.put("/api/assets/<int:asset_id>")
@auth({"ADMIN", "MANAGER", "EXPEDITIONER"})
def update_asset(asset_id):
    a = db.session.get(Asset, asset_id)
    if not a: return jsonify({"error": "Asset not found"}), 404
    data = request.get_json() or {}
    for key in ["asset_code", "name", "category", "location", "notes"]:
        if key in data: setattr(a, key, data[key])
    for key in ["quantity", "min_quantity"]:
        if key in data: setattr(a, key, int(data[key]))
    if "status" in data and data["status"] in ASSET_STATUSES: a.status = data["status"]
    if "last_service" in data: a.last_service = iso_date(data["last_service"])
    log("UPDATE", "Asset", a.id, a.name); db.session.commit()
    return jsonify(asset_dict(a))

@app.delete("/api/assets/<int:asset_id>")
@auth({"ADMIN", "MANAGER"})
def delete_asset(asset_id):
    a = db.session.get(Asset, asset_id)
    if not a: return jsonify({"error": "Asset not found"}), 404
    log("DELETE", "Asset", a.id, a.name); db.session.delete(a); db.session.commit()
    return jsonify({"ok": True})

@app.get("/api/expeditions")
@auth()
def expeditions():
    return jsonify([expedition_dict(e) for e in Expedition.query.order_by(Expedition.created_at.desc()).all()])

@app.post("/api/expeditions")
@auth({"ADMIN", "MANAGER"})
def create_expedition():
    data = request.get_json() or {}
    if not data.get("name") or not data.get("region") or not data.get("leader"):
        return jsonify({"error": "name, region and leader are required"}), 400
    e = Expedition(
        name=data["name"], region=data["region"], leader=data["leader"],
        start_date=iso_date(data.get("start_date")), end_date=iso_date(data.get("end_date")),
        status=data.get("status", "PLANNED"), notes=data.get("notes", "")
    )
    if e.status not in EXPEDITION_STATUSES: e.status = "PLANNED"
    db.session.add(e); db.session.flush(); log("CREATE", "Expedition", e.id, e.name); db.session.commit()
    return jsonify(expedition_dict(e)), 201

@app.put("/api/expeditions/<int:expedition_id>")
@auth({"ADMIN", "MANAGER", "EXPEDITIONER"})
def update_expedition(expedition_id):
    e = db.session.get(Expedition, expedition_id)
    if not e: return jsonify({"error": "Expedition not found"}), 404
    data = request.get_json() or {}
    for key in ["name", "region", "leader", "notes"]:
        if key in data: setattr(e, key, data[key])
    for key in ["start_date", "end_date"]:
        if key in data: setattr(e, key, iso_date(data[key]))
    if data.get("status") in EXPEDITION_STATUSES: e.status = data["status"]
    if "latitude" in data: e.latitude = data["latitude"]
    if "longitude" in data: e.longitude = data["longitude"]
    log("UPDATE", "Expedition", e.id, e.name); db.session.commit()
    return jsonify(expedition_dict(e))

@app.delete("/api/expeditions/<int:expedition_id>")
@auth({"ADMIN", "MANAGER"})
def delete_expedition(expedition_id):
    e = db.session.get(Expedition, expedition_id)
    if not e:
        return jsonify({"error": "Expedition not found"}), 404
    ExpeditionAsset.query.filter_by(expedition_id=e.id).delete(synchronize_session=False)
    SensorReading.query.filter_by(expedition_id=e.id).delete(synchronize_session=False)
    log("DELETE", "Expedition", e.id, e.name)
    db.session.delete(e)
    db.session.commit()
    return jsonify({"ok": True})

@app.post("/api/expeditions/<int:expedition_id>/assign")
@auth({"ADMIN", "MANAGER", "EXPEDITIONER"})
def assign_asset(expedition_id):
    if not db.session.get(Expedition, expedition_id):
        return jsonify({"error": "Expedition not found"}), 404
    data = request.get_json() or {}
    asset = db.session.get(Asset, data.get("asset_id"))
    if not asset: return jsonify({"error": "Asset not found"}), 404
    qty = max(1, int(data.get("quantity", 1)))
    if qty > asset.quantity: return jsonify({"error": "Insufficient asset quantity"}), 400
    existing = ExpeditionAsset.query.filter_by(expedition_id=expedition_id, asset_id=asset.id).first()
    if existing: existing.quantity += qty
    else: db.session.add(ExpeditionAsset(expedition_id=expedition_id, asset_id=asset.id, quantity=qty))
    asset.quantity -= qty
    if asset.quantity == 0: asset.status = "IN_USE"
    log("ASSIGN", "Asset", asset.id, f"Expedition {expedition_id}, qty {qty}")
    db.session.commit()
    return jsonify({"ok": True, "asset": asset_dict(asset)})

@app.post("/api/expeditions/<int:expedition_id>/location")
@auth({"ADMIN", "MANAGER", "EXPEDITIONER"})
def update_location(expedition_id):
    e = db.session.get(Expedition, expedition_id)
    if not e: return jsonify({"error": "Expedition not found"}), 404
    data = request.get_json() or {}
    e.latitude, e.longitude = data.get("latitude"), data.get("longitude")
    db.session.commit()
    return jsonify(expedition_dict(e))

@app.get("/api/audit")
@auth({"ADMIN", "MANAGER"})
def audit():
    rows = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(100).all()
    return jsonify([{"id": x.id, "user_email": x.user_email, "action": x.action, "entity": x.entity,
                     "entity_id": x.entity_id, "details": x.details, "created_at": x.created_at.isoformat()} for x in rows])


@app.get("/api/analytics/forecast")
@auth()
def forecast():
    assets = Asset.query.all()
    # Lightweight, explainable forecast for a hackathon demo.
    # Production version can replace this with a trained ML model.
    result=[]
    for a in assets:
        baseline=max(a.min_quantity, 1)
        if a.status == "IN_USE":
            daily_use=max(0.2, a.min_quantity/7)
        elif a.quantity <= a.min_quantity:
            daily_use=max(0.15, a.min_quantity/10)
        else:
            daily_use=max(0.05, a.quantity/30)
        days=max(0, round(a.quantity/daily_use))
        recommended=max(0, int(round(a.min_quantity*2-a.quantity)))
        risk="CRITICAL" if a.quantity==0 else ("HIGH" if a.quantity<=a.min_quantity else ("MEDIUM" if days<14 else "LOW"))
        result.append({"asset_id":a.id,"asset":a.name,"quantity":a.quantity,
                       "estimated_days_remaining":days,"recommended_restock":recommended,
                       "risk":risk,"basis":"current stock, minimum stock and operational status"})
    return jsonify(sorted(result,key=lambda x:({"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3}[x["risk"]],x["estimated_days_remaining"])))

@app.get("/api/telemetry")
@auth()
def telemetry():
    rows=SensorReading.query.order_by(SensorReading.recorded_at.desc()).limit(100).all()
    return jsonify([{"id":r.id,"asset_id":r.asset_id,"expedition_id":r.expedition_id,
                     "sensor_type":r.sensor_type,"value":r.value,"unit":r.unit,
                     "recorded_at":r.recorded_at.isoformat()} for r in rows])

@app.post("/api/telemetry/simulate")
@auth({"ADMIN","MANAGER","EXPEDITIONER"})
def simulate_telemetry():
    data=request.get_json() or {}
    expedition_id=data.get("expedition_id")
    sensor_type=data.get("sensor_type","TEMPERATURE")
    presets={"TEMPERATURE":(-45,-10,"°C"),"BATTERY":(20,100,"%"),
             "WIND":(0,80,"km/h"),"PRESSURE":(650,1050,"hPa")}
    lo,hi,unit=presets.get(sensor_type,presets["TEMPERATURE"])
    value=round(random.uniform(lo,hi),2)
    row=SensorReading(expedition_id=expedition_id,sensor_type=sensor_type,value=value,unit=unit)
    db.session.add(row); db.session.commit()
    return jsonify({"id":row.id,"sensor_type":sensor_type,"value":value,"unit":unit,"recorded_at":row.recorded_at.isoformat()})

@app.post("/api/self-test")
@auth({"ADMIN"})
def self_test():
    """Create an isolated demo dataset and verify the core database relationships."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    demo_email = f"selftest-{stamp}@polarx.local"
    demo_password = generate_temp_password()

    demo_user = User(
        name=f"POLAR-X Self Test {stamp}",
        email=demo_email,
        role="EXPEDITIONER",
        password_hash=generate_password_hash(demo_password),
        must_change_password=True,
    )
    db.session.add(demo_user)

    expedition = Expedition(
        name=f"POLAR-X Demo Expedition {stamp}",
        region="Antarctica Demo Zone",
        leader=demo_user.name,
        start_date=datetime.now(timezone.utc).date(),
        end_date=(datetime.now(timezone.utc) + timedelta(days=14)).date(),
        status="ACTIVE",
        latitude=-75.2500,
        longitude=0.1000,
        notes="Automatically generated by POLAR-X Self-Test / Demo Mode.",
    )
    db.session.add(expedition)
    db.session.flush()

    assets = [
        Asset(asset_code=f"SELF-{stamp}-01", name="Demo Thermal Suit", category="PERSONAL PROTECTIVE EQUIPMENT", quantity=12, min_quantity=4, status="AVAILABLE", location="Demo Base Camp", notes="Self-test asset"),
        Asset(asset_code=f"SELF-{stamp}-02", name="Demo Satellite Beacon", category="COMMUNICATION", quantity=5, min_quantity=2, status="IN_USE", location="Demo Expedition", notes="Self-test asset"),
        Asset(asset_code=f"SELF-{stamp}-03", name="Demo Emergency Battery", category="POWER", quantity=8, min_quantity=3, status="AVAILABLE", location="Demo Base Camp", notes="Self-test asset"),
    ]
    db.session.add_all(assets)
    db.session.flush()

    for asset in assets:
        db.session.add(ExpeditionAsset(expedition_id=expedition.id, asset_id=asset.id, quantity=1))

    readings = [
        SensorReading(expedition_id=expedition.id, asset_id=assets[0].id, sensor_type="TEMPERATURE", value=-31.5, unit="°C"),
        SensorReading(expedition_id=expedition.id, asset_id=assets[1].id, sensor_type="BATTERY", value=84.0, unit="%"),
        SensorReading(expedition_id=expedition.id, asset_id=assets[2].id, sensor_type="WIND", value=42.7, unit="km/h"),
    ]
    db.session.add_all(readings)
    log("SELF_TEST", "System", None, f"Created demo dataset {stamp}")
    db.session.commit()

    checks = [
        ("database_connection", True, "Database session committed successfully"),
        ("test_user_created", User.query.filter_by(id=demo_user.id).count() == 1, "Test user exists"),
        ("expedition_created", Expedition.query.filter_by(id=expedition.id).count() == 1, "Test expedition exists"),
        ("assets_created", Asset.query.filter(Asset.id.in_([a.id for a in assets])).count() == len(assets), f"Created {len(assets)} test assets"),
        ("asset_assignments", ExpeditionAsset.query.filter_by(expedition_id=expedition.id).count() == len(assets), f"Linked {len(assets)} assets to the expedition"),
        ("telemetry_created", SensorReading.query.filter_by(expedition_id=expedition.id).count() == len(readings), f"Created {len(readings)} telemetry readings"),
        ("user_role", demo_user.role == "EXPEDITIONER", "Role assignment is valid"),
        ("temporary_password", check_password_hash(demo_user.password_hash, demo_password), "Generated password matches stored hash"),
    ]
    return jsonify({
        "ok": all(x[1] for x in checks),
        "message": "POLAR-X self-test completed successfully" if all(x[1] for x in checks) else "POLAR-X self-test completed with failures",
        "test_user": {"name": demo_user.name, "email": demo_email, "role": demo_user.role, "temporary_password": demo_password},
        "expedition": expedition_dict(expedition),
        "assets_created": len(assets),
        "telemetry_created": len(readings),
        "checks": [{"name": n, "passed": bool(passed), "details": details} for n, passed, details in checks],
    }), 201

@app.get("/api/reports/assets.csv")
@auth({"ADMIN","MANAGER","VIEWER","EXPEDITIONER"})
def assets_csv():
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(["Code","Asset","Category","Quantity","Minimum","Status","Location","Last Service"])
    for a in Asset.query.order_by(Asset.category,Asset.name).all():
        writer.writerow([a.asset_code,a.name,a.category,a.quantity,a.min_quantity,a.status,a.location,
                         a.last_service.isoformat() if a.last_service else ""])
    return Response(output.getvalue(),mimetype="text/csv",
                    headers={"Content-Disposition":"attachment; filename=polar-x-assets.csv"})

@app.get("/api/reports/expeditions.csv")
@auth({"ADMIN","MANAGER","VIEWER","EXPEDITIONER"})
def expeditions_csv():
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(["Expedition","Region","Leader","Start","End","Status","Latitude","Longitude"])
    for e in Expedition.query.order_by(Expedition.created_at.desc()).all():
        writer.writerow([e.name,e.region,e.leader,e.start_date,e.end_date,e.status,e.latitude,e.longitude])
    return Response(output.getvalue(),mimetype="text/csv",
                    headers={"Content-Disposition":"attachment; filename=polar-x-expeditions.csv"})

def seed():
    if User.query.count() == 0:
        demo = [
            ("POLAR-X Admin", "admin@polarx.local", "Admin@123", "ADMIN"),
            ("Logistics Manager", "manager@polarx.local", "Manager@123", "MANAGER"),
            ("Expedition Officer", "expedition@polarx.local", "Expedition@123", "EXPEDITIONER"),
            ("Read Only", "viewer@polarx.local", "Viewer@123", "VIEWER"),
        ]
        for name, email, password, role in demo:
            db.session.add(User(name=name, email=email, role=role, password_hash=generate_password_hash(password), must_change_password=False))
    if Asset.query.count() == 0:
        samples = [
            ("GPS-001", "Satellite GPS", "Navigation", 8, 2, "AVAILABLE", "Station A"),
            ("PWR-002", "Portable Power Unit", "Power", 5, 1, "AVAILABLE", "Station A"),
            ("MED-003", "Medical Kit", "Medical", 12, 3, "IN_USE", "Field Camp"),
            ("COM-004", "Satellite Communicator", "Communication", 3, 1, "MAINTENANCE", "Workshop"),
            ("TNT-005", "Emergency Tent", "Shelter", 2, 2, "AVAILABLE", "Warehouse"),
        ]
        for row in samples:
            db.session.add(Asset(asset_code=row[0], name=row[1], category=row[2], quantity=row[3],
                                 min_quantity=row[4], status=row[5], location=row[6]))
    if Expedition.query.count() == 0:
        db.session.add(Expedition(name="Himalayan Polar Simulation", region="High-Altitude Test Zone",
                                  leader="Dr. Polaris", status="ACTIVE"))
    db.session.commit()

def migrate_user_table():
    # create_all does not add new columns to an existing database, so add the
    # password-change flag when upgrading an older POLAR-X database.
    inspector = db.inspect(db.engine)
    columns = {c["name"] for c in inspector.get_columns("user")} if "user" in inspector.get_table_names() else set()
    if "must_change_password" not in columns:
        dialect = db.engine.dialect.name
        if dialect == "sqlite":
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"))
        elif dialect == "mysql":
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE"))
        db.session.commit()

with app.app_context():
    db.create_all()
    migrate_user_table()
    seed()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
