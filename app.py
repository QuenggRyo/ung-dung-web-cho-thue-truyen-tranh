# app.py
import os, json, uuid, smtplib, hashlib, ssl
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.utils import formataddr
from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, flash, jsonify # type: ignore

# ========= Gửi mail theo cấu hình đã lưu của user =========
def send_email_using_user_cfg(username: str, subject: str, html_body: str, to_email: str):
    """
    Gửi email bằng Gmail SMTP (App Password) qua SSL 465.
    Lấy cấu hình từ email.json của user để không bị crash.
    """
    try:
        cfg = read_json(user_file(username, "email.json"), {})
        sender_email = (cfg.get("sender_email") or cfg.get("email") or "").strip()
        sender_name = (cfg.get("sender_name") or cfg.get("display_name") or "Cửa Hàng Truyện Tranh 2025").strip()
        smtp_pass = (cfg.get("smtp_pass") or cfg.get("app_password") or "").strip()

        if not sender_email or not smtp_pass:
            return False, "email.json thiếu sender_email hoặc smtp_pass"

        # Tạo nội dung email
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = formataddr((sender_name, sender_email))
        msg["To"] = to_email

        # Gửi qua Gmail SSL port 465 (ổn định trên Render)
        import smtplib, ssl
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
            server.login(sender_email, smtp_pass)
            server.sendmail(sender_email, [to_email], msg.as_string())

        return True, "OK"

    except Exception as e:
        print(f"[EMAIL][USERCFG][ERROR] {e}")
        return False, str(e)
# ==========================================================

# ====== Cấu hình và hàm gửi email an toàn ======
EMAIL_ENABLED    = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST        = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT        = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER        = os.getenv("SMTP_USER", "")
SMTP_PASS        = os.getenv("SMTP_PASS", "")
SMTP_FROM_NAME   = os.getenv("SMTP_FROM_NAME", "Cua Hang Truyen Tranh 2025")
SMTP_FROM_EMAIL  = os.getenv("SMTP_FROM_EMAIL", SMTP_USER or "no-reply@example.com")

def safe_send_email(to_email: str, subject: str, html_body: str):
    """Gửi mail an toàn: nếu lỗi thì không crash"""
    if not EMAIL_ENABLED:
        return True, "Email disabled"
    try:
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM_EMAIL))
        msg["To"] = to_email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())
        return True, "OK"
    except Exception as e:
        return False, str(e)
# ===============================================

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

# ================== Cấu hình & tiện ích ==================
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DT_FMT = "%d-%m-%Y %H:%M:%S"

def now_str():
    return datetime.now().strftime(DT_FMT)

def parse_dt(s):
    return datetime.strptime(s, DT_FMT)

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def user_root(username):
    p = os.path.join(DATA_DIR, "users", username)
    os.makedirs(p, exist_ok=True)
    return p

def user_file(username, name):
    return os.path.join(user_root(username), name)

def get_current_username():
    return session.get("username")

def require_login():
    if not get_current_username():
        return redirect(url_for("login"))

# inject helpers vào Jinja
app.jinja_env.globals.update(read_json=read_json, user_file=user_file, now=now_str)

# ---------- Email (Gmail fixed) ----------
def send_email_if_configured(username, subject, html_body, to_email):
    cfg_path = user_file(username, "email.json")
    cfg = read_json(cfg_path, {})

    # Chỉ còn cần 3 trường này
    required = ["smtp_pass", "sender_name", "sender_email"]
    if not all(k in cfg and cfg[k] for k in required):
        return False, "Email chưa cấu hình hoặc thiếu trường (cần sender_email, smtp_pass, sender_name)."

    try:
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = formataddr((cfg["sender_name"], cfg["sender_email"]))
        msg["To"] = to_email

        # Luôn dùng Gmail: smtp.gmail.com:587 + STARTTLS
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        # Đăng nhập bằng email gửi đi + App Password
        server.login(cfg["sender_email"], cfg["smtp_pass"])
        server.sendmail(cfg["sender_email"], [to_email], msg.as_string())
        server.quit()
        return True, "Đã gửi email."
    except Exception as e:
        return False, f"Lỗi gửi email: {e}"

# Render mẫu dạng {key}
def render_tpl(tpl: str, ctx: dict) -> str:
    if not tpl:
        return ""
    out = tpl
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v))
    return out

# ---------- Giá & Stock ----------
def format_price(raw: str) -> str:
    try:
        n = int(str(raw).replace(".","").strip())
    except:
        n = 0
    s = f"{n:,}".replace(",", ".")
    return s

def price_to_int(s: str) -> int:
    try:
        return int(s.replace(".",""))
    except:
        return 0

def log_low_stock(username, manga_id):
    mpath = user_file(username, "manga.json")
    items = read_json(mpath, [])
    mg = next((x for x in items if x["id"] == manga_id), None)
    if not mg:
        return
    stock_now = int(mg.get("stock", 0))
    if stock_now < 10:
        npath = user_file(username, "notifications.json")
        notifs = read_json(npath, [])
        notifs.append({
            "id": str(uuid.uuid4()),
            "type": "LOW_STOCK",
            "created_at": now_str(),
            "read": False,
            "message": f"Truyện '{mg['title']}' (ID {mg['id']}) còn {stock_now} cuốn (< 10)."
        })
        write_json(npath, notifs)

def adjust_stock(username, manga_id, delta):
    items = read_json(user_file(username, "manga.json"), [])
    updated = None
    for x in items:
        if x["id"] == manga_id:
            x["stock"] = max(0, int(x["stock"]) + int(delta))
            x["updated_at"] = now_str()
            updated = x
            break
    write_json(user_file(username, "manga.json"), items)
    if updated:
        log_low_stock(username, manga_id)
    return updated

def count_unread_notifications(username):
    lst = read_json(user_file(username, "notifications.json"), [])
    return sum(1 for n in lst if not n.get("read"))

# ===== Đồng bộ khi sửa =====
def propagate_manga_changes(username, manga_obj):
    rpath = user_file(username, "rentals.json")
    rentals = read_json(rpath, [])
    changed = False
    for r in rentals:
        if r.get("manga_id") == manga_obj["id"]:
            if r.get("manga_title") != manga_obj["title"]:
                r["manga_title"] = manga_obj["title"]
                changed = True
    if changed:
        write_json(rpath, rentals)

def propagate_customer_changes(username, customer_obj):
    rpath = user_file(username, "rentals.json")
    rentals = read_json(rpath, [])
    changed = False
    for r in rentals:
        if r.get("customer_id") == customer_obj["id"]:
            if r.get("customer_name") != customer_obj["name"]:
                r["customer_name"] = customer_obj["name"]
                changed = True
    if changed:
        write_json(rpath, rentals)

# ================== Auth ==================
@app.route("/", methods=["GET"])
def root():
    if get_current_username():
        return redirect(url_for("manga_list"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    ensure_dirs()
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        users = read_json(USERS_FILE, [])
        found = next((u for u in users if u["username"].lower()==username.lower()), None)
        if not found or found["password_hash"] != hash_pw(password):
            flash("Sai tài khoản hoặc mật khẩu.", "danger")
            return render_template("login.html")
        session["username"] = found["username"]
        session["shop_name"] = found.get("shop_name","")
        return redirect(url_for("manga_list"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    ensure_dirs()
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email = request.form.get("email","").strip()
        password = request.form.get("password","")
        repass = request.form.get("repass","")
        shop_name = request.form.get("shop_name","").strip()
        if not username or not email or not password or not repass or not shop_name:
            flash("Vui lòng nhập đủ thông tin.", "danger")
            return render_template("register.html")
        if password != repass:
            flash("Mật khẩu nhập lại không khớp.", "danger")
            return render_template("register.html")
        users = read_json(USERS_FILE, [])
        if any(u["username"].lower()==username.lower() for u in users):
            flash("Tên tài khoản đã tồn tại.", "danger")
            return render_template("register.html")
        users.append({
            "username": username,
            "email": email,
            "password_hash": hash_pw(password),
            "shop_name": shop_name,
            "created_at": now_str()
        })
        write_json(USERS_FILE, users)
        write_json(user_file(username, "manga.json"), [])
        write_json(user_file(username, "customers.json"), [])
        write_json(user_file(username, "rentals.json"), [])
        write_json(user_file(username, "notifications.json"), [])
        # tạo cấu hình email với mẫu mặc định
        write_json(user_file(username, "email.json"), default_email_cfg(shop_name=""))
        session["username"] = username
        session["shop_name"] = shop_name
        return redirect(url_for("manga_list"))
    return render_template("register.html")

# ================== Quản lý Truyện ==================
@app.route("/manga", methods=["GET"])
def manga_list():
    if require_login(): return require_login()
    q = (request.args.get("q") or "").strip().lower()
    username = get_current_username()
    items = read_json(user_file(username, "manga.json"), [])
    items.sort(key=lambda x: x.get("created_at",""), reverse=True)
    if q:
        items = [m for m in items if q in m["title"].lower() or q in m["author"].lower() or q in m["genre"].lower()]
    unread_count = count_unread_notifications(username)
    return render_template("manga_list.html", items=items, q=q, unread_count=unread_count)

@app.route("/manga/add", methods=["POST"])
def manga_add():
    if require_login(): return require_login()
    username = get_current_username()
    items = read_json(user_file(username, "manga.json"), [])
    payload = {
        "id": (request.form.get("id") or "").strip(),
        "title": (request.form.get("title") or "").strip(),
        "genre": (request.form.get("genre") or "").strip(),
        "author": (request.form.get("author") or "").strip(),
        "rent_price": format_price(request.form.get("rent_price") or "0"),
        "condition": (request.form.get("condition") or "Mới").strip(),
        "stock": int(request.form.get("stock") or "0"),
        "created_at": now_str(),
        "updated_at": now_str()
    }
    if any(x["id"]==payload["id"] for x in items):
        flash("ID truyện đã tồn tại.", "danger")
    else:
        items.append(payload)
        write_json(user_file(username, "manga.json"), items)
        log_low_stock(username, payload["id"])
        flash("Đã thêm truyện.", "success")
    return redirect(url_for("manga_list"))

@app.route("/manga/update/<mid>", methods=["POST"])
def manga_update(mid):
    if require_login(): return require_login()
    username = get_current_username()
    items = read_json(user_file(username, "manga.json"), [])
    updated_obj = None
    for x in items:
        if x["id"] == mid:
            x["title"] = (request.form.get("title") or "").strip()
            x["genre"] = (request.form.get("genre") or "").strip()
            x["author"] = (request.form.get("author") or "").strip()
            x["rent_price"] = format_price(request.form.get("rent_price") or "0")
            x["condition"] = (request.form.get("condition") or "Mới").strip()
            x["stock"] = int(request.form.get("stock") or "0")
            x["updated_at"] = now_str()
            updated_obj = x
            break
    write_json(user_file(username, "manga.json"), items)
    if updated_obj:
        propagate_manga_changes(username, updated_obj)
        log_low_stock(username, updated_obj["id"])
    flash("Đã cập nhật truyện.", "success")
    return redirect(url_for("manga_list"))

@app.route("/manga/delete/<mid>", methods=["POST"])
def manga_delete(mid):
    if require_login(): return require_login()
    username = get_current_username()
    rentals = read_json(user_file(username, "rentals.json"), [])
    if any(r["manga_id"]==mid and not r.get("returned_at") for r in rentals):
        flash("còn người chưa trả truyện", "danger")
        return redirect(url_for("manga_list"))
    rentals = [r for r in rentals if r["manga_id"] != mid]
    write_json(user_file(username, "rentals.json"), rentals)
    items = read_json(user_file(username, "manga.json"), [])
    items = [x for x in items if x["id"] != mid]
    write_json(user_file(username, "manga.json"), items)
    flash("Đã xóa truyện và lịch sử liên quan.", "success")
    return redirect(url_for("manga_list"))

# ================== Quản lý Khách hàng ==================
@app.route("/customers")
def customers_list():
    if require_login(): return require_login()
    q = (request.args.get("q") or "").strip().lower()
    username = get_current_username()
    items = read_json(user_file(username, "customers.json"), [])
    items.sort(key=lambda x: x.get("created_at",""), reverse=True)
    if q:
        items = [c for c in items if q in c["name"].lower() or q in c["phone"].lower() or q in c["email"].lower() or q in c["id"].lower()]
    unread_count = count_unread_notifications(username)
    return render_template("customers_list.html", items=items, q=q, unread_count=unread_count)

@app.route("/customers/add", methods=["POST"])
def customers_add():
    if require_login(): return require_login()
    username = get_current_username()
    items = read_json(user_file(username, "customers.json"), [])
    new = {
        "id": (request.form.get("id") or "").strip(),
        "name": (request.form.get("name") or "").strip(),
        "age": int(request.form.get("age") or "0"),
        "phone": (request.form.get("phone") or "").strip(),
        "address": (request.form.get("address") or "").strip(),
        "national_id": (request.form.get("national_id") or "").strip(),
        "email": (request.form.get("email") or "").strip(),
        "created_at": now_str(),
        "updated_at": now_str()
    }
    if any(x["id"]==new["id"] for x in items):
        flash("ID khách hàng đã tồn tại.", "danger")
    else:
        items.append(new)
        write_json(user_file(username, "customers.json"), items)
        flash("Đã thêm khách hàng.", "success")
    return redirect(url_for("customers_list"))

@app.route("/customers/update/<cid>", methods=["POST"])
def customers_update(cid):
    if require_login(): return require_login()
    username = get_current_username()
    items = read_json(user_file(username, "customers.json"), [])
    updated_obj = None
    for x in items:
        if x["id"] == cid:
            x["name"] = (request.form.get("name") or "").strip()
            x["age"] = int(request.form.get("age") or "0")
            x["phone"] = (request.form.get("phone") or "").strip()
            x["address"] = (request.form.get("address") or "").strip()
            x["national_id"] = (request.form.get("national_id") or "").strip()
            x["email"] = (request.form.get("email") or "").strip()
            x["updated_at"] = now_str()
            updated_obj = x
            break
    write_json(user_file(username, "customers.json"), items)
    if updated_obj:
        propagate_customer_changes(username, updated_obj)
    flash("Đã cập nhật khách hàng.", "success")
    return redirect(url_for("customers_list"))

@app.route("/customers/delete/<cid>", methods=["POST"])
def customers_delete(cid):
    if require_login(): return require_login()
    username = get_current_username()
    rentals = read_json(user_file(username, "rentals.json"), [])
    if any(r["customer_id"]==cid and not r.get("returned_at") for r in rentals):
        flash("khách hàng còn giao dịch chưa trả truyện", "danger")
        return redirect(url_for("customers_list"))
    rentals = [r for r in rentals if r["customer_id"] != cid]
    write_json(user_file(username, "rentals.json"), rentals)
    items = read_json(user_file(username, "customers.json"), [])
    items = [x for x in items if x["id"] != cid]
    write_json(user_file(username, "customers.json"), items)
    flash("Đã xóa khách hàng và lịch sử liên quan.", "success")
    return redirect(url_for("customers_list"))

# ================== Thuê / Trả truyện ==================
@app.route("/rentals")
def rentals_list():
    if require_login(): return require_login()
    q = (request.args.get("q") or "").strip().lower()
    username = get_current_username()
    rentals = read_json(user_file(username, "rentals.json"), [])
    rentals.sort(key=lambda x: x.get("created_at",""), reverse=True)
    if q:
        rentals = [r for r in rentals if q in r["manga_title"].lower() or q in r["customer_name"].lower()]
    unread_count = count_unread_notifications(username)
    return render_template("rentals_list.html", rentals=rentals, q=q, unread_count=unread_count)

@app.route("/rentals/create", methods=["POST"])
def rentals_create():
    if require_login(): return require_login()
    username = get_current_username()
    customers = read_json(user_file(username, "customers.json"), [])
    manga = read_json(user_file(username, "manga.json"), [])
    customer_id = (request.form.get("customer_id") or "").strip()
    manga_id = (request.form.get("manga_id") or "").strip()
    rent_price = format_price(request.form.get("rent_price") or "0")
    start_at = now_str()
    due_at = (datetime.now() + timedelta(days=5)).strftime(DT_FMT)

    cust = next((c for c in customers if c["id"]==customer_id), None)
    mg = next((m for m in manga if m["id"]==manga_id), None)
    if not cust or not mg:
        flash("Không tìm thấy khách hàng hoặc truyện.", "danger")
        return redirect(url_for("rentals_list"))
    if int(mg["stock"]) <= 0:
        flash("Truyện đã hết hàng.", "danger")
        return redirect(url_for("rentals_list"))

    adjust_stock(username, manga_id, -1)

    rec = {
        "id": str(uuid.uuid4()),
        "manga_id": mg["id"],
        "manga_title": mg["title"],
        "customer_id": cust["id"],
        "customer_name": cust["name"],
        "rent_price": rent_price,
        "late_fee": "0",
        "created_at": start_at,
        "due_at": due_at,
        "returned_at": "",
    }
    rentals = read_json(user_file(username, "rentals.json"), [])
    rentals.append(rec)
    write_json(user_file(username, "rentals.json"), rentals)

        # ------ Gửi email theo mẫu người dùng (không để crash) ------
    cfg = read_json(user_file(username, "email.json"), {})
    tpl = cfg.get("tpl_rent")
    if not tpl:
        # fallback template (dùng chuỗi trong ngoặc để tránh lỗi 3-nháy)
        tpl = (
            "<h3>{{ shop_name }} - Xác nhận thuê truyện</h3>"
            "<p>Xin chào {{ customer_name }}, bạn đã thuê <b>{{ manga_title }}</b>.</p>"
            "<ul>"
            "<li>Giá thuê: {{ rent_price }}</li>"
            "<li>Ngày thuê: {{ start_at }}</li>"
            "<li>Đến hạn: {{ due_at }}</li>"
            "</ul>"
        )

    ctx = {
        "customer_name": cust["name"],
        "manga_title": mg["title"],
        "rent_price": rent_price,
        "start_at": start_at,
        "due_at": due_at,
        "shop_name": session.get("shop_name", "Cửa hàng"),
    }

    # TẠO subject + html (bắt buộc có trước khi gửi)
    subject = f"[{session.get('shop_name','Cửa hàng')}] Xác nhận thuê truyện"
    html = render_template_string(tpl, **ctx)

    # Gửi mail theo cấu hình của user trong email.json
    to_email = str(cust.get("email", "")).strip()
    ok, msg = send_email_using_user_cfg(username, subject, html, to_email)
    if not ok:
        print(f"[EMAIL][WARN] {msg}")
        flash("Đã tạo giao dịch, nhưng chưa gửi được email thông báo.", "warning")

    flash("Đã tạo giao dịch thuê.", "success")
    return redirect(url_for("rentals_list"))

@app.route("/rentals/return/<rid>", methods=["POST"])
def rentals_return(rid):
    if require_login(): return require_login()
    username = get_current_username()
    rentals = read_json(user_file(username, "rentals.json"), [])
    customers = read_json(user_file(username, "customers.json"), [])
    found = None
    for r in rentals:
        if r["id"] == rid and not r.get("returned_at"):
            found = r
            break
    if not found:
        flash("Không tìm thấy giao dịch hoặc đã trả.", "danger")
        return redirect(url_for("rentals_list"))
    due = parse_dt(found["due_at"])
    days_late = (datetime.now() - due).days
    late_fee = 0
    if days_late > 0:
        late_fee = days_late * 10000
    found["late_fee"] = format_price(str(late_fee))
    found["returned_at"] = now_str()
    write_json(user_file(username, "rentals.json"), rentals)

    adjust_stock(username, found["manga_id"], +1)

    cust = next((c for c in customers if c["id"]==found["customer_id"]), None)
    if cust:
        cfg = read_json(user_file(username, "email.json"), {})
        tpl = cfg.get("tpl_return") or default_email_cfg(session.get('shop_name','')).get("tpl_return")
        ctx = {
            "customer_name": cust["name"],
            "manga_title": found["manga_title"],
            "rent_price": found["rent_price"],
            "start_at": found["created_at"],
            "due_at": found["due_at"],
            "return_at": found["returned_at"],
            "late_fee": found["late_fee"],
            "shop_name": session.get("shop_name","Cửa hàng")
        }
        subject = f"[{session.get('shop_name','Cửa hàng')}] Xác nhận trả truyện"
        html = render_tpl(tpl, ctx)
        send_email_if_configured(username, subject, html, cust["email"])

    flash("Đã cập nhật trả truyện.", "success")
    return redirect(url_for("rentals_list"))

# ================== Thông báo ==================
@app.route("/notifications", methods=["GET","POST"])
def notifications():
    if require_login(): return require_login()
    username = get_current_username()
    notifs_path = user_file(username, "notifications.json")
    notifs = read_json(notifs_path, [])
    if request.method == "POST":
        nid = request.args.get("read")
        for n in notifs:
            if n["id"] == nid:
                n["read"] = True
        write_json(notifs_path, notifs)
        return jsonify({"ok": True})
    notifs.sort(key=lambda x: x.get("created_at",""), reverse=True)
    unread_count = count_unread_notifications(username)
    return render_template("notifications.html", notifs=notifs, unread_count=unread_count)

# ===================== THỐNG KÊ DOANH THU =====================
@app.route("/stats")
def stats():
    if require_login():
        return require_login()

    from datetime import datetime

    username = get_current_username()
    rentals = read_json(user_file(username, "rentals.json"), [])

    # Lấy ngày từ query string
    date_from = (request.args.get("from") or "").strip()
    date_to   = (request.args.get("to") or "").strip()

    # Nếu người dùng không chọn ngày, mặc định là ngày hiện tại
    if not date_from or not date_to:
        today = datetime.now().strftime("%d-%m-%Y")
        if not date_from:
            date_from = today
        if not date_to:
            date_to = today

    # Hàm kiểm tra giao dịch có nằm trong khoảng ngày hay không
    def in_range(rec):
        try:
            t = parse_dt(rec["created_at"])
        except:
            return False

        ok = True
        if date_from:
            if len(date_from) == 10:
                ok &= t >= parse_dt(date_from + " 00:00:00")
            else:
                ok &= t >= parse_dt(date_from)
        if date_to:
            if len(date_to) == 10:
                ok &= t <= parse_dt(date_to + " 23:59:59")
            else:
                ok &= t <= parse_dt(date_to)
        return ok

    # Lọc danh sách theo khoảng ngày
    if date_from or date_to:
        rentals = [r for r in rentals if in_range(r)]

    # Tính toán thống kê
    total_trans = len(rentals)
    total_rent = sum(price_to_int(r["rent_price"]) for r in rentals)
    total_late = sum(price_to_int(r.get("late_fee", "0")) for r in rentals if r.get("returned_at"))
    total = total_rent + total_late
    unread_count = count_unread_notifications(username)

    # Render ra template
    return render_template(
        "stats.html",
        total_trans=total_trans,
        total_rent=total_rent,
        total_late=total_late,
        total=total,
        date_from=date_from,
        date_to=date_to,
        unread_count=unread_count
    )

# ============== Cấu hình email (thêm 2 mẫu) ==============
def default_email_cfg(shop_name: str = ""):
    return {
        # KHÔNG còn các field: smtp_host, smtp_port, smtp_user
        "smtp_pass": "",
        "sender_name": (shop_name if shop_name else ""),
        "sender_email": "",
        "use_tls": True,  # giữ để tương thích, dùng TLS
        "tpl_rent": (
            "Kính gửi {customer_name},<br>"
            "Bạn đã thuê truyện <b>{manga_title}</b> với giá <b>{rent_price} VND</b>.<br>"
            "Ngày thuê: {start_at}<br>Ngày đến hạn: {due_at}<br><br>"
            "Trân trọng,<br>{shop_name}"
        ),
        "tpl_return": (
            "Kính gửi {customer_name},<br>"
            "Bạn đã trả truyện <b>{manga_title}</b>.<br>"
            "Ngày thuê: {start_at}<br>Ngày đến hạn: {due_at}<br>"
            "Ngày trả: {return_at}<br>"
            "Phí trễ hạn: <b>{late_fee} VND</b><br><br>"
            "Trân trọng,<br>{shop_name}"
        ),
    }

@app.route("/email-settings", methods=["GET", "POST"])
def email_settings():
    if require_login(): 
        return require_login()

    username = get_current_username()
    path = user_file(username, "email.json")
    cfg = read_json(path, {})

    # Khôi phục mẫu mặc định (không đụng tới mật khẩu nếu đã có)
    if request.method == "GET" and request.args.get("reset_tpl") == "1":
        base = default_email_cfg(session.get('shop_name', ''))
        cfg.setdefault("smtp_pass", "")
        cfg.setdefault("sender_name", session.get('shop_name', 'Cửa Hàng Truyện Tranh 2025'))
        cfg.setdefault("sender_email", "")
        cfg.setdefault("use_tls", True)
        cfg["tpl_rent"] = base["tpl_rent"]
        cfg["tpl_return"] = base["tpl_return"]
        write_json(path, cfg)
        flash("Đã khôi phục mẫu email mặc định.", "success")
        return redirect(url_for("email_settings"))

    # Lưu cấu hình
    if request.method == "POST":
        cfg = {
            "smtp_pass": (request.form.get("smtp_pass") or "").strip(),
            "sender_name": (request.form.get("sender_name") or "").strip(),
            "sender_email": (request.form.get("sender_email") or "").strip(),
            "use_tls": request.form.get("use_tls") == "on",
            "tpl_rent": (request.form.get("tpl_rent") or "").strip(),
            "tpl_return": (request.form.get("tpl_return") or "").strip(),
        }
        base = default_email_cfg(session.get('shop_name', ''))
        if not cfg.get("tpl_rent"):
            cfg["tpl_rent"] = base["tpl_rent"]
        if not cfg.get("tpl_return"):
            cfg["tpl_return"] = base["tpl_return"]
        write_json(path, cfg)
        flash("Đã lưu cấu hình email.", "success")
        return redirect(url_for("email_settings"))

    # Đảm bảo có sẵn mẫu mặc định lần đầu mở
    if not cfg.get("tpl_rent") or not cfg.get("tpl_return"):
        base = default_email_cfg(session.get('shop_name', ''))
        cfg.setdefault("tpl_rent", base["tpl_rent"])
        cfg.setdefault("tpl_return", base["tpl_return"])
        write_json(path, cfg)

    unread_count = count_unread_notifications(username)
    return render_template("email_settings.html", cfg=cfg, unread_count=unread_count)

# ================== Run ==================
if __name__ == "__main__":
    ensure_dirs()
    app.run(debug=True)
