import os,secrets,hmac,hashlib
from datetime import datetime
from decimal import Decimal
from functools import wraps
from flask import Flask,render_template,request,redirect,url_for,session,flash,abort
import requests
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash,check_password_hash

app=Flask(__name__)
app.config["SECRET_KEY"]=os.getenv("SECRET_KEY",secrets.token_hex(32))
u=os.getenv("DATABASE_URL","sqlite:///gecohmarket.db")
if u.startswith("postgres://"): u=u.replace("postgres://","postgresql://",1)
app.config["SQLALCHEMY_DATABASE_URI"]=u
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
db=SQLAlchemy(app)
FEE=Decimal("0.05"); COINS=["LTC"]
BTCPAY_URL=os.getenv("BTCPAY_URL","").rstrip("/")
BTCPAY_STORE_ID=os.getenv("BTCPAY_STORE_ID","")
BTCPAY_API_KEY=os.getenv("BTCPAY_API_KEY","")
BTCPAY_WEBHOOK_SECRET=os.getenv("BTCPAY_WEBHOOK_SECRET","")
PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL","").rstrip("/")

class User(db.Model):
    id=db.Column(db.Integer,primary_key=True); username=db.Column(db.String(40),unique=True,nullable=False); email=db.Column(db.String(160),unique=True,nullable=False)
    password_hash=db.Column(db.String(255),nullable=False); is_seller=db.Column(db.Boolean,default=False); is_admin=db.Column(db.Boolean,default=False)
    verified_seller=db.Column(db.Boolean,default=False); seller_level=db.Column(db.String(30),default="Starter"); balance_eur=db.Column(db.Numeric(14,2),default=0)
class Wallet(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False); coin=db.Column(db.String(10),nullable=False)
    deposit_address=db.Column(db.String(180)); crypto_balance=db.Column(db.Numeric(24,8),default=0); user=db.relationship("User",backref="wallets")
    __table_args__=(db.UniqueConstraint("user_id","coin"),)
class Transaction(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False); tx_type=db.Column(db.String(30),nullable=False)
    coin=db.Column(db.String(10)); amount=db.Column(db.Numeric(24,8),nullable=False); status=db.Column(db.String(30),default="pending"); txid=db.Column(db.String(200))
    created_at=db.Column(db.DateTime,default=datetime.utcnow); user=db.relationship("User",backref="transactions")
class PaymentInvoice(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False,index=True)
    purpose=db.Column(db.String(20),nullable=False)
    order_id=db.Column(db.Integer)
    amount_eur=db.Column(db.Numeric(14,2),nullable=False)
    btcpay_invoice_id=db.Column(db.String(120),unique=True,index=True)
    checkout_url=db.Column(db.String(500))
    status=db.Column(db.String(30),default="new",nullable=False)
    credited=db.Column(db.Boolean,default=False,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
    user=db.relationship("User",backref="payment_invoices")

class Withdrawal(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False); coin=db.Column(db.String(10),nullable=False)
    address=db.Column(db.String(220),nullable=False); amount=db.Column(db.Numeric(24,8),nullable=False); status=db.Column(db.String(30),default="pending")
    created_at=db.Column(db.DateTime,default=datetime.utcnow); user=db.relationship("User",backref="withdrawals")
class Product(db.Model):
    id=db.Column(db.Integer,primary_key=True); seller_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False); title=db.Column(db.String(120),nullable=False)
    slug=db.Column(db.String(140),unique=True,nullable=False); category=db.Column(db.String(60),default="Digital"); description=db.Column(db.Text,nullable=False)
    price=db.Column(db.Numeric(12,2),nullable=False); image_url=db.Column(db.String(500)); active=db.Column(db.Boolean,default=True); featured=db.Column(db.Boolean,default=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow); seller=db.relationship("User",backref="products")
class StockItem(db.Model):
    id=db.Column(db.Integer,primary_key=True); product_id=db.Column(db.Integer,db.ForeignKey("product.id"),nullable=False); payload=db.Column(db.Text,nullable=False)
    sold=db.Column(db.Boolean,default=False); product=db.relationship("Product",backref="stock_items")
class Order(db.Model):
    id=db.Column(db.Integer,primary_key=True); buyer_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False); seller_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    product_id=db.Column(db.Integer,db.ForeignKey("product.id"),nullable=False); amount=db.Column(db.Numeric(12,2),nullable=False); platform_fee=db.Column(db.Numeric(12,2),nullable=False)
    status=db.Column(db.String(30),default="pending"); delivered_payload=db.Column(db.Text); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    product=db.relationship("Product")
class Ticket(db.Model):
    id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False); subject=db.Column(db.String(120),nullable=False)
    message=db.Column(db.Text,nullable=False); status=db.Column(db.String(30),default="open"); created_at=db.Column(db.DateTime,default=datetime.utcnow)
    user=db.relationship("User",backref="tickets")

def me(): return db.session.get(User,session.get("uid")) if session.get("uid") else None
def auth(fn):
    @wraps(fn)
    def w(*a,**k):
        if not me(): flash("Bitte einloggen.","error"); return redirect(url_for("login"))
        return fn(*a,**k)
    return w
def seller_only(fn):
    @wraps(fn)
    def w(*a,**k):
        if not me() or not (me().is_seller or me().is_admin): return redirect(url_for("dashboard"))
        return fn(*a,**k)
    return w
def ensure_wallets(user):
    for c in COINS:
        if not Wallet.query.filter_by(user_id=user.id,coin=c).first(): db.session.add(Wallet(user_id=user.id,coin=c))
    db.session.commit()
def slugify(s):
    x="".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")
    while "--" in x:x=x.replace("--","-")
    return x or "product"


def btcpay_ready():
    return all([BTCPAY_URL,BTCPAY_STORE_ID,BTCPAY_API_KEY])

def btcpay_create_invoice(amount_eur,metadata):
    if not btcpay_ready():
        raise RuntimeError("BTCPay ist noch nicht konfiguriert.")
    payload={
        "amount":str(Decimal(str(amount_eur)).quantize(Decimal("0.01"))),
        "currency":"EUR",
        "metadata":metadata
    }
    if PUBLIC_BASE_URL:
        payload["checkout"]={"redirectURL":PUBLIC_BASE_URL+"/dashboard","redirectAutomatically":False}
    r=requests.post(
        f"{BTCPAY_URL}/api/v1/stores/{BTCPAY_STORE_ID}/invoices",
        headers={"Authorization":f"token {BTCPAY_API_KEY}","Content-Type":"application/json"},
        json=payload,timeout=20
    )
    r.raise_for_status()
    return r.json()

def valid_btcpay_signature(raw,header):
    if not BTCPAY_WEBHOOK_SECRET or not header:
        return False
    expected="sha256="+hmac.new(BTCPAY_WEBHOOK_SECRET.encode(),raw,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,header)

def credit_internal_eur(user_id,amount,invoice_id):
    user=db.session.get(User,user_id)
    value=Decimal(str(amount)).quantize(Decimal("0.01"))
    user.balance_eur=Decimal(str(user.balance_eur or 0))+value
    db.session.add(Transaction(user_id=user_id,tx_type="deposit",coin="LTC",amount=value,status="settled",txid=invoice_id))
    db.session.commit()

def settle_market_order(order):
    if order.status=="paid":
        return
    item=StockItem.query.filter_by(product_id=order.product_id,sold=False).first()
    if not item:
        order.status="paid_no_stock"
        db.session.commit()
        return
    item.sold=True
    order.delivered_payload=item.payload
    order.status="paid"
    seller=db.session.get(User,order.seller_id)
    seller_net=Decimal(str(order.amount))-Decimal(str(order.platform_fee))
    seller.balance_eur=Decimal(str(seller.balance_eur or 0))+seller_net
    db.session.add(Transaction(user_id=order.seller_id,tx_type="sale",coin="EUR",amount=seller_net,status="settled",txid=f"order:{order.id}"))
    db.session.commit()

@app.context_processor
def ctx(): return {"me":me(),"coins":COINS,"fee":int(FEE*100)}

@app.route("/")
def home(): return render_template("index.html",page="home",products=Product.query.filter_by(active=True).order_by(Product.featured.desc(),Product.created_at.desc()).limit(8).all())
@app.route("/market")
def market():
    q=request.args.get("q","").strip(); cat=request.args.get("category","").strip(); sort=request.args.get("sort","new"); z=Product.query.filter_by(active=True)
    if q:z=z.filter(Product.title.ilike(f"%{q}%"))
    if cat:z=z.filter_by(category=cat)
    z=z.order_by(Product.price.asc() if sort=="low" else Product.price.desc() if sort=="high" else Product.featured.desc(),Product.created_at.desc())
    cats=[r[0] for r in db.session.query(Product.category).distinct().all()]
    return render_template("index.html",page="market",products=z.all(),cats=cats,q=q,cat=cat,sort=sort)
@app.route("/p/<slug>")
def product(slug):
    p=Product.query.filter_by(slug=slug,active=True).first_or_404(); stock=StockItem.query.filter_by(product_id=p.id,sold=False).count()
    return render_template("index.html",page="product",product=p,stock=stock)
@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        n=request.form["username"].strip().lower(); e=request.form["email"].strip().lower(); pw=request.form["password"]
        if User.query.filter((User.username==n)|(User.email==e)).first(): flash("Account existiert schon.","error"); return redirect(url_for("register"))
        u=User(username=n,email=e,password_hash=generate_password_hash(pw)); db.session.add(u); db.session.commit(); ensure_wallets(u); session["uid"]=u.id; return redirect(url_for("dashboard"))
    return render_template("index.html",page="register")
@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=User.query.filter_by(email=request.form["email"].strip().lower()).first()
        if not u or not check_password_hash(u.password_hash,request.form["password"]): flash("Login fehlgeschlagen.","error"); return redirect(url_for("login"))
        session["uid"]=u.id; ensure_wallets(u); return redirect(url_for("dashboard"))
    return render_template("index.html",page="login")
@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("home"))
@app.route("/dashboard")
@auth
def dashboard():
    return render_template("index.html",page="dashboard",orders=Order.query.filter_by(buyer_id=me().id).order_by(Order.created_at.desc()).limit(8).all(),txs=Transaction.query.filter_by(user_id=me().id).order_by(Transaction.created_at.desc()).limit(8).all())
@app.route("/wallet")
@auth
def wallet():
    ensure_wallets(me()); return render_template("index.html",page="wallet",wallets=Wallet.query.filter_by(user_id=me().id).all(),txs=Transaction.query.filter_by(user_id=me().id).order_by(Transaction.created_at.desc()).limit(20).all())
@app.route("/wallet/deposit/<coin>",methods=["GET","POST"])
@auth
def deposit(coin):
    coin=coin.upper()
    if coin!="LTC": abort(404)
    wallet=Wallet.query.filter_by(user_id=me().id,coin=coin).first_or_404()
    if request.method=="POST":
        try:
            amount=Decimal(request.form["amount"]).quantize(Decimal("0.01"))
            if amount<Decimal("1.00"): raise ValueError
        except Exception:
            flash("Mindesteinzahlung: 1,00 € Gegenwert.","error")
            return redirect(url_for("deposit",coin=coin))
        try:
            inv=btcpay_create_invoice(amount,{"purpose":"wallet_deposit","userId":str(me().id),"coin":"LTC"})
            rec=PaymentInvoice(user_id=me().id,purpose="deposit",amount_eur=amount,btcpay_invoice_id=inv.get("id"),checkout_url=inv.get("checkoutLink"),status=inv.get("status","New"))
            db.session.add(rec); db.session.commit()
            return redirect(inv["checkoutLink"])
        except Exception as e:
            flash("LTC-Zahlung konnte nicht erstellt werden: "+str(e),"error")
    recent=PaymentInvoice.query.filter_by(user_id=me().id,purpose="deposit").order_by(PaymentInvoice.created_at.desc()).limit(10).all()
    return render_template("index.html",page="deposit",wallet=wallet,recent_invoices=recent,btcpay_ready=btcpay_ready())
@app.route("/wallet/withdraw",methods=["GET","POST"])
@auth
def withdraw():
    if request.method=="POST":
        c=request.form["coin"]; a=Decimal(request.form["amount"]); addr=request.form["address"].strip()
        db.session.add(Withdrawal(user_id=me().id,coin=c,address=addr,amount=a)); db.session.add(Transaction(user_id=me().id,tx_type="withdrawal",coin=c,amount=-a,status="pending")); db.session.commit()
        flash("Auszahlungsanfrage erstellt.","ok"); return redirect(url_for("wallet"))
    return render_template("index.html",page="withdraw")
@app.route("/seller/enable",methods=["POST"])
@auth
def seller_enable(): me().is_seller=True; db.session.commit(); return redirect(url_for("seller"))
@app.route("/seller")
@seller_only
def seller():
    ps=Product.query.filter_by(seller_id=me().id).all(); os=Order.query.filter_by(seller_id=me().id).order_by(Order.created_at.desc()).all()
    gross=sum((Decimal(str(o.amount)) for o in os if o.status=="paid"),Decimal("0")); net=sum((Decimal(str(o.amount))-Decimal(str(o.platform_fee)) for o in os if o.status=="paid"),Decimal("0"))
    return render_template("index.html",page="seller",products=ps,orders=os,gross=gross,net=net)
@app.route("/seller/new",methods=["GET","POST"])
@seller_only
def new_product():
    if request.method=="POST":
        title=request.form["title"].strip(); s=slugify(title); n=2; base=s
        while Product.query.filter_by(slug=s).first(): s=f"{base}-{n}"; n+=1
        p=Product(seller_id=me().id,title=title,slug=s,category=request.form["category"],description=request.form["description"],price=Decimal(request.form["price"]),image_url=request.form.get("image_url") or None)
        db.session.add(p); db.session.commit(); return redirect(url_for("stock",pid=p.id))
    return render_template("index.html",page="new_product")
@app.route("/seller/stock/<int:pid>",methods=["GET","POST"])
@seller_only
def stock(pid):
    p=Product.query.get_or_404(pid)
    if request.method=="POST":
        for x in [v.strip() for v in request.form["stock"].splitlines() if v.strip()]: db.session.add(StockItem(product_id=p.id,payload=x))
        db.session.commit(); return redirect(url_for("seller"))
    return render_template("index.html",page="stock",product=p,stock=StockItem.query.filter_by(product_id=p.id,sold=False).count())
@app.route("/buy/<int:pid>",methods=["POST"])
@auth
def buy(pid):
    p=Product.query.get_or_404(pid)
    if p.seller_id==me().id:
        flash("Eigenes Produkt kann nicht gekauft werden.","error")
        return redirect(url_for("product",slug=p.slug))
    if not StockItem.query.filter_by(product_id=p.id,sold=False).first():
        flash("Produkt ist ausverkauft.","error")
        return redirect(url_for("product",slug=p.slug))
    amount=Decimal(str(p.price)); fee=(amount*FEE).quantize(Decimal("0.01"))
    order=Order(buyer_id=me().id,seller_id=p.seller_id,product_id=p.id,amount=amount,platform_fee=fee,status="payment_pending")
    db.session.add(order); db.session.commit()
    try:
        inv=btcpay_create_invoice(amount,{"purpose":"market_order","orderId":str(order.id),"userId":str(me().id)})
        db.session.add(PaymentInvoice(user_id=me().id,purpose="order",order_id=order.id,amount_eur=amount,btcpay_invoice_id=inv.get("id"),checkout_url=inv.get("checkoutLink"),status=inv.get("status","New")))
        db.session.commit()
        return redirect(inv["checkoutLink"])
    except Exception as e:
        flash("Checkout konnte nicht erstellt werden: "+str(e),"error")
        return redirect(url_for("product",slug=p.slug))

@app.route("/webhooks/btcpay",methods=["POST"])
def btcpay_webhook():
    raw=request.get_data()
    if not valid_btcpay_signature(raw,request.headers.get("BTCPay-Sig")):
        return "invalid signature",401
    event=request.get_json(silent=True) or {}
    invoice_id=event.get("invoiceId")
    event_type=event.get("type")
    if not invoice_id:
        return "ok",200
    rec=PaymentInvoice.query.filter_by(btcpay_invoice_id=invoice_id).first()
    if not rec:
        return "ok",200
    rec.status=event_type or rec.status
    if event_type=="InvoiceSettled" and not rec.credited:
        if rec.purpose=="deposit":
            credit_internal_eur(rec.user_id,rec.amount_eur,invoice_id)
        elif rec.purpose=="order" and rec.order_id:
            order=db.session.get(Order,rec.order_id)
            if order: settle_market_order(order)
        rec.credited=True
        db.session.commit()
    elif event_type in ("InvoiceExpired","InvoiceInvalid"):
        if rec.order_id:
            order=db.session.get(Order,rec.order_id)
            if order and order.status=="payment_pending": order.status="payment_failed"
        db.session.commit()
    return "ok",200

@app.route("/support",methods=["GET","POST"])
@auth
def support():
    if request.method=="POST": db.session.add(Ticket(user_id=me().id,subject=request.form["subject"],message=request.form["message"])); db.session.commit(); return redirect(url_for("support"))
    return render_template("index.html",page="support",tickets=Ticket.query.filter_by(user_id=me().id).order_by(Ticket.created_at.desc()).all())
@app.route("/admin")
@auth
def admin():
    if not me().is_admin: abort(403)
    stats={"users":User.query.count(),"sellers":User.query.filter_by(is_seller=True).count(),"products":Product.query.count(),"orders":Order.query.count(),"withdrawals":Withdrawal.query.filter_by(status="pending").count()}
    return render_template("index.html",page="admin",stats=stats,withdrawals=Withdrawal.query.order_by(Withdrawal.created_at.desc()).limit(20).all())
@app.cli.command("make-admin")
def make_admin():
    e=input("Admin E-Mail: ").strip().lower(); u=User.query.filter_by(email=e).first()
    if u: u.is_admin=True; u.is_seller=True; u.verified_seller=True; u.seller_level="Verified"; db.session.commit(); print("Admin gesetzt.")
with app.app_context(): db.create_all()
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))
