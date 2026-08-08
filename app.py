import os, secrets
from datetime import datetime
from decimal import Decimal
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
db_url = os.environ.get("DATABASE_URL", "sqlite:///gecohmarket.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
PLATFORM_FEE = Decimal("0.05")

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_seller = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    category = db.Column(db.String(60), nullable=False, default="Digital")
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(12,2), nullable=False)
    image_url = db.Column(db.String(500))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    seller = db.relationship("User", backref="products")

class StockItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    payload = db.Column(db.Text, nullable=False)
    sold = db.Column(db.Boolean, default=False, nullable=False)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    amount = db.Column(db.Numeric(12,2), nullable=False)
    platform_fee = db.Column(db.Numeric(12,2), nullable=False)
    status = db.Column(db.String(30), default="pending", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    product = db.relationship("Product")

def slugify(s):
    out = "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")
    while "--" in out:
        out = out.replace("--","-")
    return (out or "product")[:120]

def me():
    uid = session.get("uid")
    return db.session.get(User, uid) if uid else None

def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not me():
            flash("Bitte zuerst einloggen.", "error")
            return redirect(url_for("login"))
        return fn(*a, **k)
    return w

def seller_required(fn):
    @wraps(fn)
    def w(*a, **k):
        u = me()
        if not u or not (u.is_seller or u.is_admin):
            flash("Seller-Zugang benötigt.", "error")
            return redirect(url_for("dashboard"))
        return fn(*a, **k)
    return w

@app.context_processor
def inject():
    return {"me": me(), "platform_fee_percent": int(PLATFORM_FEE*100)}

@app.route("/")
def home():
    products = Product.query.filter_by(active=True).order_by(Product.created_at.desc()).limit(8).all()
    return render_template("index.html", page="home", products=products)

@app.route("/market")
def market():
    q = request.args.get("q","").strip()
    cat = request.args.get("category","").strip()
    query = Product.query.filter_by(active=True)
    if q:
        query = query.filter(Product.title.ilike(f"%{q}%"))
    if cat:
        query = query.filter_by(category=cat)
    products = query.order_by(Product.created_at.desc()).all()
    cats = [r[0] for r in db.session.query(Product.category).distinct().all()]
    return render_template("index.html", page="market", products=products, cats=cats, q=q, cat=cat)

@app.route("/p/<slug>")
def product(slug):
    p = Product.query.filter_by(slug=slug, active=True).first_or_404()
    available = StockItem.query.filter_by(product_id=p.id, sold=False).count()
    return render_template("index.html", page="product", product=p, available=available)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        if len(username) < 3 or len(password) < 8:
            flash("Username min. 3 Zeichen, Passwort min. 8 Zeichen.", "error")
            return redirect(url_for("register"))
        if User.query.filter((User.username==username)|(User.email==email)).first():
            flash("Username oder E-Mail vergeben.", "error")
            return redirect(url_for("register"))
        u = User(username=username, email=email, password_hash=generate_password_hash(password))
        db.session.add(u); db.session.commit(); session["uid"] = u.id
        return redirect(url_for("dashboard"))
    return render_template("index.html", page="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(email=request.form["email"].strip().lower()).first()
        if not u or not check_password_hash(u.password_hash, request.form["password"]):
            flash("Login fehlgeschlagen.", "error")
            return redirect(url_for("login"))
        session["uid"] = u.id
        return redirect(url_for("dashboard"))
    return render_template("index.html", page="login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/dashboard")
@login_required
def dashboard():
    orders = Order.query.filter_by(buyer_id=me().id).order_by(Order.created_at.desc()).all()
    return render_template("index.html", page="dashboard", orders=orders)

@app.route("/seller/enable", methods=["POST"])
@login_required
def seller_enable():
    u = me(); u.is_seller = True; db.session.commit()
    return redirect(url_for("seller"))

@app.route("/seller")
@seller_required
def seller():
    products = Product.query.filter_by(seller_id=me().id).order_by(Product.created_at.desc()).all()
    orders = Order.query.filter_by(seller_id=me().id).order_by(Order.created_at.desc()).all()
    gross = sum((Decimal(str(o.amount)) for o in orders if o.status=="paid"), Decimal("0"))
    return render_template("index.html", page="seller", products=products, orders=orders, gross=gross)

@app.route("/seller/product/new", methods=["GET","POST"])
@seller_required
def product_new():
    if request.method == "POST":
        title = request.form["title"].strip()
        slug = slugify(title); base = slug; n = 2
        while Product.query.filter_by(slug=slug).first():
            slug = f"{base}-{n}"; n += 1
        p = Product(
            seller_id=me().id,
            title=title,
            slug=slug,
            category=request.form["category"].strip(),
            description=request.form["description"].strip(),
            price=Decimal(request.form["price"]),
            image_url=request.form.get("image_url","").strip() or None,
        )
        db.session.add(p); db.session.commit()
        return redirect(url_for("product_stock", pid=p.id))
    return render_template("index.html", page="product_new")

@app.route("/seller/product/<int:pid>/stock", methods=["GET","POST"])
@seller_required
def product_stock(pid):
    p = Product.query.get_or_404(pid)
    if p.seller_id != me().id and not me().is_admin:
        abort(403)
    if request.method == "POST":
        lines = [x.strip() for x in request.form["stock"].splitlines() if x.strip()]
        for line in lines:
            db.session.add(StockItem(product_id=p.id, payload=line))
        db.session.commit()
        flash(f"{len(lines)} Stock-Einträge hinzugefügt.", "ok")
        return redirect(url_for("seller"))
    available = StockItem.query.filter_by(product_id=p.id, sold=False).count()
    return render_template("index.html", page="stock", product=p, available=available)

@app.route("/buy/<int:pid>", methods=["POST"])
@login_required
def buy(pid):
    p = Product.query.filter_by(id=pid, active=True).first_or_404()
    if p.seller_id == me().id:
        flash("Eigenes Produkt kann nicht gekauft werden.", "error")
        return redirect(url_for("product", slug=p.slug))
    item = StockItem.query.filter_by(product_id=p.id, sold=False).first()
    if not item:
        flash("Ausverkauft.", "error")
        return redirect(url_for("product", slug=p.slug))
    amount = Decimal(str(p.price))
    fee = (amount * PLATFORM_FEE).quantize(Decimal("0.01"))
    db.session.add(Order(buyer_id=me().id, seller_id=p.seller_id, product_id=p.id, amount=amount, platform_fee=fee))
    db.session.commit()
    flash("Bestellung erstellt. Zahlung kommt in V2.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/admin")
@login_required
def admin():
    if not me().is_admin:
        abort(403)
    stats = {"users":User.query.count(),"products":Product.query.count(),"orders":Order.query.count(),"sellers":User.query.filter_by(is_seller=True).count()}
    return render_template("index.html", page="admin", stats=stats)

@app.cli.command("make-admin")
def make_admin():
    email = input("Admin E-Mail: ").strip().lower()
    u = User.query.filter_by(email=email).first()
    if not u:
        print("Nicht gefunden"); return
    u.is_admin = True; u.is_seller = True; db.session.commit()
    print("Admin gesetzt")

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","8080")))
