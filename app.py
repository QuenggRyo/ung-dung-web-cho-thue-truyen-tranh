# app.py  # Đây là file backend chính của Flask, chứa toàn bộ logic chạy web/app

import os, json, uuid, smtplib, hashlib  # Import nhiều thư viện chuẩn:
                                        # os: thao tác thư mục/đường dẫn hệ điều hành
                                        # json: đọc/ghi dữ liệu dạng JSON
                                        # uuid: tạo ID ngẫu nhiên duy nhất cho bản ghi
                                        # smtplib: gửi email qua SMTP
                                        # hashlib: băm/mã hóa chuỗi (dùng cho mật khẩu)

from datetime import datetime, timedelta  # Import datetime để lấy thời gian hiện tại,
                                         # timedelta để cộng/trừ số ngày (ví dụ tính ngày đến hạn)

from email.mime.text import MIMEText  # MIMEText dùng để tạo nội dung email dạng text hoặc html
from email.utils import formataddr    # formataddr giúp ghép "Tên hiển thị + email" chuẩn RFC khi gửi

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify # type: ignore
# Import các thành phần Flask:
# Flask: tạo app
# render_template: render file HTML trong thư mục templates/
# request: lấy dữ liệu từ form, query string...
# redirect: điều hướng sang route khác
# url_for: tạo URL từ tên hàm route
# session: lưu phiên đăng nhập (dữ liệu theo user)
# flash: tạo thông báo popup nhanh (success/danger)
# jsonify: trả dữ liệu JSON cho frontend/API

app = Flask(__name__)  # Tạo đối tượng Flask app; __name__ giúp Flask biết root của project
app.secret_key = "super-secret-change-me"  # Secret key để mã hóa session/cookie; deploy nên đổi cho an toàn

# ================== Cấu hình & tiện ích ==================  # Comment phân tách khu vực cấu hình/tiện ích

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")  # Tạo đường dẫn tới folder data nằm cạnh app.py
USERS_FILE = os.path.join(DATA_DIR, "users.json")           # Đường dẫn file users.json lưu tài khoản
DT_FMT = "%d-%m-%Y %H:%M:%S"                                # Chuỗi format chuẩn cho ngày giờ toàn hệ thống

def now_str():  # Hàm tiện ích trả về thời gian hiện tại dạng chuỗi
    return datetime.now().strftime(DT_FMT)  # Lấy datetime hiện tại rồi format theo DT_FMT

def parse_dt(s):  # Hàm tiện ích chuyển chuỗi thời gian -> datetime
    return datetime.strptime(s, DT_FMT)  # Parse chuỗi s dựa trên DT_FMT

def ensure_dirs():  # Hàm đảm bảo folder/file dữ liệu tồn tại
    os.makedirs(DATA_DIR, exist_ok=True)  # Tạo folder data nếu chưa có, exist_ok tránh lỗi nếu đã có
    if not os.path.exists(USERS_FILE):   # Nếu file users.json chưa tồn tại
        with open(USERS_FILE, "w", encoding="utf-8") as f:  # Mở file để tạo mới với encoding UTF-8
            json.dump([], f, ensure_ascii=False, indent=2)  # Ghi list rỗng [] vào file (mặc định chưa có user)

def hash_pw(pw: str) -> str:  # Hàm băm mật khẩu, nhận pw dạng str và trả về str
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()  # Băm SHA256 để lưu an toàn hơn plaintext

def read_json(path, default):  # Hàm đọc JSON từ path, nếu lỗi thì trả default
    try:  # Bắt đầu khối try để tránh crash khi file lỗi
        with open(path, "r", encoding="utf-8") as f:  # Mở file cần đọc theo UTF-8
            return json.load(f)  # Đọc và parse JSON thành Python object
    except Exception:  # Nếu có bất kỳ lỗi nào (file mất, JSON hỏng...)
        return default  # Trả về giá trị mặc định truyền vào

def write_json(path, data):  # Hàm ghi Python object data ra file JSON path
    os.makedirs(os.path.dirname(path), exist_ok=True)  # Tạo thư mục chứa path nếu chưa có
    with open(path, "w", encoding="utf-8") as f:  # Mở file ở chế độ ghi
        json.dump(data, f, ensure_ascii=False, indent=2)  # Ghi JSON đẹp, giữ tiếng Việt

def user_root(username):  # Hàm tạo/lấy thư mục riêng của 1 user
    p = os.path.join(DATA_DIR, "users", username)  # Ghép thành data/users/<username>
    os.makedirs(p, exist_ok=True)  # Tạo folder user nếu chưa có
    return p  # Trả đường dẫn folder đó

def user_file(username, name):  # Hàm tạo đường dẫn file riêng theo user
    return os.path.join(user_root(username), name)  # Ghép data/users/<username>/<name>

def get_current_username():  # Hàm lấy username đang đăng nhập
    return session.get("username")  # Lấy từ session (nếu chưa login thì None)

def require_login():  # Hàm bắt buộc login
    if not get_current_username():  # Nếu không có username trong session => chưa login
        return redirect(url_for("login"))  # Điều hướng sang trang login

def price_to_int(s: str) -> int:
    # Hàm ngược lại: "10.000" -> 10000 để tính toán
    try:  # Bắt lỗi parse
        return int(s.replace(".",""))  # Bỏ dấu chấm rồi ép int
    except:  # Nếu lỗi parse
        return 0  # Trả 0

def calc_late_fee(r: dict) -> str:
    """
    Tính phí trễ hiện tại cho 1 giao dịch thuê truyện.

    - Nếu giao dịch đã trả (returned_at có giá trị) thì dùng luôn late_fee đang lưu.
    - Nếu chưa trả thì tính lại dựa trên due_at, cấu hình late_fee_per_day của shop.
    - Trả về chuỗi đã format, ví dụ "10.000".
    """
    try:
        # Nếu r không phải dict chuẩn thì cứ để fallback về "0"
        late_fee_stored = r.get("late_fee")
    except Exception:
        late_fee_stored = None

    # Nếu đã trả thì ưu tiên dùng phí trễ đã lưu trong file
    if r.get("returned_at"):
        return late_fee_stored or "0"

    # Giao dịch chưa trả -> tính lại
    username = get_current_username() or ""
    if not username:
        return late_fee_stored or "0"

    # Đọc cấu hình phí trễ/ngày
    shop_cfg = read_shop_cfg(username)
    default_per_day = int(shop_cfg.get("late_fee_per_day", 10000) or 10000)

    # Parse ngày đến hạn
    try:
        due = parse_dt(r.get("due_at", ""))
    except Exception:
        return late_fee_stored or "0"

    days_late = (datetime.now() - due).days
    if days_late <= 0:
        # Chưa trễ ngày nào
        return late_fee_stored or "0"

    # Lấy phí trễ/ngày
    per_day = r.get("late_fee_per_day", default_per_day)
    try:
        per_day_int = int(per_day)
    except Exception:
        per_day_int = default_per_day
    if per_day_int < 0:
        per_day_int = 0

    late_fee = days_late * per_day_int
    return format_price(str(late_fee))

# inject helpers vào Jinja
app.jinja_env.globals.update(
    read_json=read_json,
    user_file=user_file,
    now=now_str,
    price_to_int=price_to_int,  # thêm dòng này để dùng trong template
    calc_late_fee=calc_late_fee,  # helper tính phí trễ dùng trong template
)

# update globals:
# read_json: để template đọc dữ liệu
# user_file: để template biết đường dẫn file user
# now: để template in thời gian hiện tại

# ---------- Email (Gmail fixed) ----------  # Comment đánh dấu khu gửi email

def send_email_if_configured(username, subject, html_body, to_email):
    # Hàm gửi email nếu user đã cấu hình email.json
    cfg_path = user_file(username, "email.json")  # Tạo đường dẫn tới file cấu hình email của user
    cfg = read_json(cfg_path, {})  # Đọc cấu hình; nếu không có thì cfg = {}

    # Chỉ còn cần 3 trường này  # Comment: Gmail chỉ cần email gửi, app-pass và tên hiển thị
    required = ["smtp_pass", "sender_name", "sender_email"]  # Danh sách field bắt buộc phải có
    if not all(k in cfg and cfg[k] for k in required):  # Kiểm tra đủ + không rỗng cho 3 field
        return False, "Email chưa cấu hình hoặc thiếu trường (cần sender_email, smtp_pass, sender_name)."  
        # Nếu thiếu => trả False và thông báo lỗi

    try:  # Bắt đầu try vì gửi email có thể lỗi network/login
        msg = MIMEText(html_body, "html", "utf-8")  # Tạo object email nội dung HTML, UTF-8
        msg["Subject"] = subject  # Gán tiêu đề email
        msg["From"] = formataddr((cfg["sender_name"], cfg["sender_email"]))  
        # Tạo trường From hiển thị tên shop + email gửi
        msg["To"] = to_email  # Đặt email người nhận

        # Luôn dùng Gmail: smtp.gmail.com:587 + STARTTLS  # Comment: cố định server Gmail
        server = smtplib.SMTP("smtp.gmail.com", 587)  # Kết nối SMTP Gmail cổng 587
        server.starttls()  # Bật mã hóa TLS trước khi login để an toàn
        # Đăng nhập bằng email gửi đi + App Password  # Comment: Gmail yêu cầu app password
        server.login(cfg["sender_email"], cfg["smtp_pass"])  # Login Gmail SMTP
        server.sendmail(cfg["sender_email"], [to_email], msg.as_string())  
        # Gửi email: from, list người nhận, nội dung dạng string chuẩn SMTP
        server.quit()  # Đóng kết nối SMTP
        return True, "Đã gửi email."  # Trả kết quả thành công
    except Exception as e:  # Nếu có lỗi khi gửi
        return False, f"Lỗi gửi email: {e}"  # Trả False + chuỗi lỗi để debug

# Render mẫu dạng {key}  # Comment: render template email bằng cách thay {variable}
def render_tpl(tpl: str, ctx: dict) -> str:
    if not tpl:  # Nếu template rỗng hoặc None
        return ""  # Trả chuỗi rỗng
    out = tpl  # Copy template vào biến out để thay dần
    for k, v in ctx.items():  # Duyệt từng cặp key/value trong context
        out = out.replace("{" + k + "}", str(v))  # Thay {key} bằng giá trị value
    return out  # Trả template sau khi thay xong

# ---------- Giá & Stock ----------  # Comment phân tách khu xử lý giá thuê và tồn kho

def format_price(raw: str) -> str:
    # Hàm chuẩn hóa giá về dạng có dấu chấm: 10000 -> 10.000
    try:  # Bắt lỗi nếu raw không ép được số
        n = int(str(raw).replace(".","").strip())  # Bỏ dấu chấm, bỏ khoảng trắng, ép int
    except:  # Nếu lỗi
        n = 0  # Giá trị mặc định 0
    s = f"{n:,}".replace(",", ".")  # Format theo dấu phẩy ngàn rồi đổi sang dấu chấm
    return s  # Trả chuỗi giá chuẩn

def log_low_stock(username, manga_id):
    # Hàm tạo thông báo nếu tồn kho thấp (<10)
    mpath = user_file(username, "manga.json")  # Đường dẫn file manga của user
    items = read_json(mpath, [])  # Đọc danh sách truyện
    mg = next((x for x in items if x["id"] == manga_id), None)  
    # Tìm truyện có id = manga_id, không thấy thì None
    if not mg:  # Nếu không tìm thấy truyện
        return  # Thoát hàm
    stock_now = int(mg.get("stock", 0))  # Lấy tồn kho hiện tại của truyện
    if stock_now < 10:  # Nếu tồn kho ít hơn 10
        npath = user_file(username, "notifications.json")  # File thông báo của user
        notifs = read_json(npath, [])  # Đọc danh sách thông báo hiện có
        notifs.append({  # Thêm thông báo mới vào list
            "id": str(uuid.uuid4()),          # Tạo ID noti duy nhất
            "type": "LOW_STOCK",              # Loại thông báo: tồn kho thấp
            "created_at": now_str(),          # Thời gian tạo
            "read": False,                    # Đánh dấu chưa đọc
            "manga_id": mg["id"],             # Lưu luôn ID truyện để sau này dễ xử lý
            "message": (
                f"Truyện '{mg['title']}' (ID {mg['id']}) còn {stock_now} cuốn (< 10)."
            ),  # Nội dung thông báo cụ thể
        })

        write_json(npath, notifs)  # Ghi lại danh sách thông báo

def adjust_stock(username, manga_id, delta):
    # Hàm thay đổi tồn kho (delta âm là trừ, dương là cộng)
    items = read_json(user_file(username, "manga.json"), [])  # Đọc list truyện hiện có
    updated = None  # Biến lưu truyện vừa được update stock
    for x in items:  # Duyệt từng truyện trong list
        if x["id"] == manga_id:  # Nếu đúng truyện cần thay đổi
            x["stock"] = max(0, int(x["stock"]) + int(delta))  
            # Cộng delta vào stock, max(0,...) để không cho âm
            x["updated_at"] = now_str()  # Cập nhật thời gian sửa truyện
            updated = x  # Lưu lại object truyện đã sửa
            break  # Thoát vòng lặp vì đã tìm thấy
    write_json(user_file(username, "manga.json"), items)  # Ghi lại list truyện sau thay đổi
    if updated:  # Nếu có update thành công
        log_low_stock(username, manga_id)  # Kiểm tra và tạo noti nếu stock thấp
    return updated  # Trả truyện đã sửa (hoặc None nếu không tìm thấy)

def count_unread_notifications(username):
    # Hàm đếm số thông báo chưa đọc của user
    lst = read_json(user_file(username, "notifications.json"), [])  # Đọc list thông báo
    return sum(1 for n in lst if not n.get("read"))  
    # Đếm số item có read=False

# ===== Cấu hình cửa hàng (per user) =====  # Comment phân tách khu cấu hình shop theo user

def default_shop_cfg(username: str):
    """
    Giá trị mặc định:
      - shop_name: lấy từ session hoặc users.json, nếu không có thì dùng chuỗi mặc định
      - default_rent_days: 5 ngày
      - late_fee_per_day: 10.000 VND
    """  # Docstring: mô tả rõ cấu hình mặc định
    shop_name = session.get("shop_name", "")  # Thử lấy tên shop từ session
    if not shop_name and username:  # Nếu session không có shop_name và có username
        users = read_json(USERS_FILE, [])  # Đọc file users.json chung
        u = next((u for u in users if u.get("username") == username), None)  
        # Tìm user trong users.json
        if u:  # Nếu tìm thấy user
            shop_name = u.get("shop_name", "")  # Lấy shop_name đã lưu

    if not shop_name:  # Nếu vẫn chưa có tên shop
        shop_name = "Cửa Hàng Truyện Tranh 2025"  # Gán tên mặc định

    return {  # Trả ra dict cấu hình mặc định
        "shop_name": shop_name,  # Tên shop
        "default_rent_days": 5,  # Số ngày thuê mặc định
        "late_fee_per_day": 10000,  # Phí trễ/ngày mặc định
    }

def read_shop_cfg(username: str):
    """
    Đọc shop_config.json của tài khoản.
    Nếu chưa có file thì sinh ra với giá trị mặc định.
    """  # Docstring giải thích hàm
    path = user_file(username, "shop_config.json")  # File cấu hình shop riêng user
    cfg = read_json(path, {})  # Đọc cấu hình hiện có
    base = default_shop_cfg(username)  # Lấy cấu hình mặc định
    for k, v in base.items():  # Duyệt từng cặp key/value của mặc định
        cfg.setdefault(k, v)  # Nếu cfg thiếu key thì thêm value mặc định
    write_json(path, cfg)  # Ghi lại file cấu hình (đảm bảo có đủ key)
    return cfg  # Trả cấu hình cuối cùng

@app.context_processor
def inject_shop_cfg():
    """
    Bơm biến shop_cfg vào tất cả template:
      - shop_cfg.shop_name
      - shop_cfg.default_rent_days
      - shop_cfg.late_fee_per_day
    """  # Docstring: giúp bạn hiểu context_processor
    username = get_current_username()  # Lấy username hiện tại
    if not username:  # Nếu chưa đăng nhập
        return {  # Trả dict mặc định để template vẫn chạy
            "shop_cfg": {
                "shop_name": "Hệ thống quản lý & cho thuê truyện tranh",  # Tên shop tiêu đề chung
                "default_rent_days": 5,  # Số ngày thuê default nếu chưa login
                "late_fee_per_day": 10000,  # Phí trễ default nếu chưa login
            }
        }
    return {"shop_cfg": read_shop_cfg(username)}  
    # Nếu login rồi thì bơm cấu hình thực của user vào template

# ===== Đồng bộ khi sửa =====  # Comment khu đồng bộ dữ liệu giữa file

def propagate_manga_changes(username, manga_obj):
    # Hàm đồng bộ khi sửa truyện: cập nhật tên truyện trong rentals.json
    rpath = user_file(username, "rentals.json")  # File lịch sử thuê/trả của user
    rentals = read_json(rpath, [])  # Đọc list rentals
    changed = False  # Cờ đánh dấu có thay đổi không
    for r in rentals:  # Duyệt từng giao dịch thuê
        if r.get("manga_id") == manga_obj["id"]:  # Nếu giao dịch thuộc truyện đang sửa
            if r.get("manga_title") != manga_obj["title"]:  # Nếu tên cũ khác tên mới
                r["manga_title"] = manga_obj["title"]  # Update tên mới
                changed = True  # Đánh dấu đã đổi dữ liệu
    if changed:  # Nếu có bất kỳ giao dịch nào đổi
        write_json(rpath, rentals)  # Ghi lại rentals.json

def propagate_customer_changes(username, customer_obj):
    # Hàm đồng bộ khi sửa khách: cập nhật tên khách trong rentals.json
    rpath = user_file(username, "rentals.json")  # File rentals của user
    rentals = read_json(rpath, [])  # Đọc rentals
    changed = False  # Cờ đánh dấu thay đổi
    for r in rentals:  # Duyệt từng rental
        if r.get("customer_id") == customer_obj["id"]:  # Đúng khách hàng này
            if r.get("customer_name") != customer_obj["name"]:  # Tên cũ khác tên mới
                r["customer_name"] = customer_obj["name"]  # Update tên mới
                changed = True  # Đánh dấu thay đổi
    if changed:  # Nếu có đổi
        write_json(rpath, rentals)  # Ghi lại file rentals

# ================== Auth ==================  # Khu xác thực đăng nhập/đăng ký

@app.route("/", methods=["GET"])
def root():
    # Route gốc "/", chỉ nhận GET
    if get_current_username():  # Nếu đang login
        return redirect(url_for("manga_list"))  # Chuyển về danh sách truyện
    return redirect(url_for("login"))  # Nếu chưa login thì chuyển về login

@app.route("/login", methods=["GET", "POST"])
def login():
    # Route /login nhận GET để hiển thị form, POST để xử lý đăng nhập
    ensure_dirs()  # Đảm bảo thư mục data/users.json tồn tại
    if request.method == "POST":  # Nếu user submit form
        username = request.form.get("username","").strip()  # Lấy username từ form, bỏ khoảng trắng
        password = request.form.get("password","")  # Lấy password từ form
        users = read_json(USERS_FILE, [])  # Đọc danh sách user từ file chung
        found = next((u for u in users if u["username"].lower()==username.lower()), None)
        # Tìm user có username trùng (không phân biệt hoa thường)
        if not found or found["password_hash"] != hash_pw(password):
            # Nếu không tìm thấy user hoặc hash mật khẩu không đúng
            flash("Sai tài khoản hoặc mật khẩu.", "danger")  # Thông báo lỗi
            return render_template("login.html")  # Render lại trang login
        session["username"] = found["username"]  # Lưu username vào session (đánh dấu login)
        session["shop_name"] = found.get("shop_name","")  # Lưu shop_name để dùng nhanh
        return redirect(url_for("manga_list"))  # Đăng nhập thành công -> về manga_list
    return render_template("login.html")  # Nếu GET -> chỉ hiển thị form login

@app.route("/logout")
def logout():
    # Route logout để đăng xuất
    session.clear()  # Xóa toàn bộ session user hiện tại
    return redirect(url_for("login"))  # Quay lại trang login

@app.route("/register", methods=["GET","POST"])
def register():
    # Route /register: GET hiển thị form, POST tạo tài khoản
    ensure_dirs()  # Đảm bảo data folder + users.json tồn tại
    if request.method == "POST":  # Nếu submit form đăng ký
        username = request.form.get("username","").strip()  # Lấy username
        email = request.form.get("email","").strip()  # Lấy email
        password = request.form.get("password","")  # Lấy mật khẩu
        repass = request.form.get("repass","")  # Lấy mật khẩu nhập lại
        shop_name = request.form.get("shop_name","").strip()  # Lấy tên shop
        if not username or not email or not password or not repass or not shop_name:
            # Nếu thiếu bất kỳ trường nào
            flash("Vui lòng nhập đủ thông tin.", "danger")  # Báo lỗi
            return render_template("register.html")  # Render lại register
        if password != repass:  # Nếu mật khẩu nhập lại không giống
            flash("Mật khẩu nhập lại không khớp.", "danger")  # Báo lỗi
            return render_template("register.html")  # Render lại register
        users = read_json(USERS_FILE, [])  # Đọc users.json
        if any(u["username"].lower()==username.lower() for u in users):
            # Nếu đã có user trùng username
            flash("Tên tài khoản đã tồn tại.", "danger")  # Báo lỗi
            return render_template("register.html")  # Render lại register
        users.append({
            # Thêm object user mới vào list users
            "username": username,  # Lưu username
            "email": email,  # Lưu email
            "password_hash": hash_pw(password),  # Lưu mật khẩu dạng hash
            "shop_name": shop_name,  # Lưu tên shop
            "created_at": now_str()  # Lưu thời điểm tạo
        })
        write_json(USERS_FILE, users)  # Ghi list users mới ra file users.json
        write_json(user_file(username, "manga.json"), [])  # Tạo file manga rỗng cho user mới
        write_json(user_file(username, "customers.json"), [])  # Tạo file customers rỗng
        write_json(user_file(username, "rentals.json"), [])  # Tạo file rentals rỗng
        write_json(user_file(username, "notifications.json"), [])  # Tạo file notifications rỗng
        # tạo cấu hình email với mẫu mặc định
        write_json(user_file(username, "email.json"), default_email_cfg(shop_name=""))
        # Tạo email.json mặc định cho user
        session["username"] = username  # Cho login luôn sau khi đăng ký
        session["shop_name"] = shop_name  # Lưu shop_name vào session
        return redirect(url_for("manga_list"))  # Chuyển về danh sách truyện
    return render_template("register.html")  # Nếu GET -> hiển thị form register

# ================== Quản lý Truyện ==================  # Khu CRUD truyện

@app.route("/manga", methods=["GET"])
def manga_list():
    # Route hiển thị danh sách truyện
    if require_login():
        return require_login()  # Nếu chưa login -> redirect login

    q = (request.args.get("q") or "").strip().lower()
    # Lấy query tìm kiếm từ URL ?q=..., nếu None thì dùng "", rồi lower để so sánh

    username = get_current_username()  # Lấy username hiện tại
    items = read_json(user_file(username, "manga.json"), [])
    # Đọc danh sách truyện của user từ manga.json

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    # Sắp xếp truyện theo ngày tạo giảm dần (mới nhất trước)

    if q:  # Nếu có từ khóa tìm kiếm
        def match_item(m):
            title = (m.get("title") or "").lower()
            author = (m.get("author") or "").lower()
            genre = (m.get("genre") or "").lower()
            barcode = (m.get("barcode") or "").lower()
            # Cho phép:
            #  - gõ tên / tác giả / thể loại: chỉ cần chứa q
            #  - quét mã vạch: chuỗi q phải trùng đúng barcode
            return (
                q in title
                or q in author
                or q in genre
                or (barcode and q == barcode)
            )

        items = [m for m in items if match_item(m)]
        # Lọc truyện khớp với từ khóa / mã vạch

    unread_count = count_unread_notifications(username)
    # Đếm số noti chưa đọc để hiển thị badge

    return render_template("manga_list.html", items=items, q=q, unread_count=unread_count)
    # Render trang manga_list.html và truyền biến items, q, unread_count

@app.route("/manga/add", methods=["POST"])
def manga_add():
    # Route thêm truyện mới (POST từ form)
    if require_login(): return require_login()  # Chặn nếu chưa login
    username = get_current_username()  # Lấy username
    items = read_json(user_file(username, "manga.json"), [])  # Đọc list truyện hiện có
    payload = {
        # Tạo object truyện mới từ form
        "id": (request.form.get("id") or "").strip(),          # ID truyện
        "title": (request.form.get("title") or "").strip(),    # Tên truyện
        "genre": (request.form.get("genre") or "").strip(),    # Thể loại
        "author": (request.form.get("author") or "").strip(),  # Tác giả
        "rent_price": format_price(request.form.get("rent_price") or "0"),  # Giá thuê chuẩn hóa
        "condition": (request.form.get("condition") or "Mới").strip(),      # Tình trạng (mặc định "Mới")
        "stock": int(request.form.get("stock") or "0"),        # Tồn kho ép int
        "barcode": (request.form.get("barcode") or "").strip(),  # Mã vạch gắn với truyện
        "created_at": now_str(),                               # Ngày tạo
        "updated_at": now_str()                                # Ngày cập nhật
    }
    if any(x["id"]==payload["id"] for x in items):
        # Nếu ID mới trùng với ID cũ
        flash("ID truyện đã tồn tại.", "danger")  # Báo lỗi
    else:
        # Nếu không trùng
        items.append(payload)  # Thêm truyện mới vào list
        write_json(user_file(username, "manga.json"), items)  # Ghi list ra file
        log_low_stock(username, payload["id"])  # Kiểm tra stock thấp để tạo noti
        flash("Đã thêm truyện.", "success")  # Báo thành công
    return redirect(url_for("manga_list"))  # Quay lại danh sách truyện

@app.route("/manga/update/<mid>", methods=["POST"])
def manga_update(mid):
    # Route cập nhật truyện theo ID mid
    if require_login(): return require_login()  # Chặn nếu chưa login
    username = get_current_username()  # Lấy username
    items = read_json(user_file(username, "manga.json"), [])  # Đọc list truyện
    updated_obj = None  # Khởi tạo biến lưu truyện vừa sửa
    for x in items:  # Duyệt từng truyện
        if x["id"] == mid:  # Nếu đúng truyện cần sửa
            x["title"] = (request.form.get("title") or "").strip()   # Cập nhật tên
            x["genre"] = (request.form.get("genre") or "").strip()   # Cập nhật thể loại
            x["author"] = (request.form.get("author") or "").strip() # Cập nhật tác giả
            x["rent_price"] = format_price(request.form.get("rent_price") or "0")  # Cập nhật giá thuê
            x["condition"] = (request.form.get("condition") or "Mới").strip()      # Cập nhật tình trạng
            x["stock"] = int(request.form.get("stock") or "0")       # Cập nhật tồn kho
            x["barcode"] = (request.form.get("barcode") or "").strip()  # Cập nhật / thay mã vạch
            x["updated_at"] = now_str()  # Cập nhật thời gian sửa
            updated_obj = x  # Lưu object vừa sửa
            break  # Thoát vòng lặp
    write_json(user_file(username, "manga.json"), items)  # Ghi list truyện mới
    if updated_obj:
        # Nếu có truyện được sửa thật
        propagate_manga_changes(username, updated_obj)  # Đồng bộ tên vào rentals
        log_low_stock(username, updated_obj["id"])  # Kiểm tra tồn kho thấp
    flash("Đã cập nhật truyện.", "success")  # Thông báo thành công
    return redirect(url_for("manga_list"))  # Quay lại danh sách

@app.route("/manga/delete/<mid>", methods=["POST"])
def manga_delete(mid):
    # Route xóa truyện theo ID mid
    if require_login():
        return require_login()  # Chặn nếu chưa login

    username = get_current_username()  # Lấy username

    # 1) Kiểm tra còn giao dịch chưa trả với truyện này không
    rentals = read_json(user_file(username, "rentals.json"), [])  # Đọc lịch sử thuê
    if any(r["manga_id"] == mid and not r.get("returned_at") for r in rentals):
        # Nếu còn giao dịch chưa trả của truyện này
        flash("còn người chưa trả truyện", "danger")  # Báo lỗi không cho xóa
        return redirect(url_for("manga_list"))  # Quay lại danh sách

    # 2) Xóa các rental liên quan đến truyện này
    rentals = [r for r in rentals if r["manga_id"] != mid]
    write_json(user_file(username, "rentals.json"), rentals)

    # 3) Xóa truyện trong manga.json
    items = read_json(user_file(username, "manga.json"), [])
    items = [x for x in items if x["id"] != mid]
    write_json(user_file(username, "manga.json"), items)

    # 4) Xóa các thông báo tồn kho thấp của truyện này
    npath = user_file(username, "notifications.json")
    notifs = read_json(npath, [])

    def is_low_stock_of_deleted_manga(n):
        # Chỉ xóa thông báo tồn kho thấp của truyện này
        if n.get("type") != "LOW_STOCK":
            return False
        # Trường hợp mới: có lưu manga_id
        if n.get("manga_id") == mid:
            return True
        # Trường hợp cũ: chưa có manga_id, thì dò trong message
        msg = (n.get("message") or "")
        return f"(ID {mid})" in msg

    notifs = [n for n in notifs if not is_low_stock_of_deleted_manga(n)]
    write_json(npath, notifs)

    flash("Đã xóa truyện, lịch sử liên quan và thông báo tồn kho.", "success")
    return redirect(url_for("manga_list"))

# ================== Quản lý Khách hàng ==================  # Khu CRUD khách hàng

@app.route("/customers")
def customers_list():
    # Route hiển thị danh sách khách hàng
    if require_login(): return require_login()  # Chặn nếu chưa login
    q = (request.args.get("q") or "").strip().lower()  # Lấy từ khóa tìm kiếm
    username = get_current_username()  # Lấy username hiện tại
    items = read_json(user_file(username, "customers.json"), [])  # Đọc list khách
    items.sort(key=lambda x: x.get("created_at",""), reverse=True)  # Sắp xếp khách mới lên trước
    if q:  # Nếu có tìm kiếm
        items = [c for c in items if q in c["name"].lower() or q in c["phone"].lower() or q in c["email"].lower() or q in c["id"].lower()]
        # Lọc khách theo tên/sđt/email/id
    unread_count = count_unread_notifications(username)  # Đếm thông báo chưa đọc
    return render_template("customers_list.html", items=items, q=q, unread_count=unread_count)
    # Render trang customers_list.html

@app.route("/customers/add", methods=["POST"])
def customers_add():
    # Route thêm khách hàng mới
    if require_login(): return require_login()  # Chặn nếu chưa login
    username = get_current_username()  # Lấy user
    items = read_json(user_file(username, "customers.json"), [])  # Đọc list khách
    new = {
        # Object khách mới
        "id": (request.form.get("id") or "").strip(),  # ID khách
        "name": (request.form.get("name") or "").strip(),  # Tên khách
        "age": int(request.form.get("age") or "0"),  # Tuổi
        "phone": (request.form.get("phone") or "").strip(),  # SĐT
        "address": (request.form.get("address") or "").strip(),  # Địa chỉ
        "national_id": (request.form.get("national_id") or "").strip(),  # CCCD
        "email": (request.form.get("email") or "").strip(),  # Email
        "created_at": now_str(),  # Ngày tạo
        "updated_at": now_str()  # Ngày sửa
    }
    if any(x["id"]==new["id"] for x in items):
        # Nếu trùng ID khách
        flash("ID khách hàng đã tồn tại.", "danger")  # Báo lỗi
    else:
        # Nếu không trùng
        items.append(new)  # Thêm khách
        write_json(user_file(username, "customers.json"), items)  # Ghi lại file
        flash("Đã thêm khách hàng.", "success")  # Báo thành công
    return redirect(url_for("customers_list"))  # Quay lại danh sách khách

@app.route("/customers/update/<cid>", methods=["POST"])
def customers_update(cid):
    # Route cập nhật khách theo ID cid
    if require_login(): return require_login()  # Chặn nếu chưa login
    username = get_current_username()  # Lấy user
    items = read_json(user_file(username, "customers.json"), [])  # Đọc list khách
    updated_obj = None  # Biến lưu khách vừa sửa
    for x in items:  # Duyệt từng khách
        if x["id"] == cid:  # Nếu đúng khách cần sửa
            x["name"] = (request.form.get("name") or "").strip()  # Sửa tên
            x["age"] = int(request.form.get("age") or "0")  # Sửa tuổi
            x["phone"] = (request.form.get("phone") or "").strip()  # Sửa SĐT
            x["address"] = (request.form.get("address") or "").strip()  # Sửa địa chỉ
            x["national_id"] = (request.form.get("national_id") or "").strip()  # Sửa CCCD
            x["email"] = (request.form.get("email") or "").strip()  # Sửa email
            x["updated_at"] = now_str()  # Cập nhật thời gian sửa
            updated_obj = x  # Lưu khách vừa sửa
            break  # Thoát vòng lặp
    write_json(user_file(username, "customers.json"), items)  # Ghi list khách mới
    if updated_obj:
        propagate_customer_changes(username, updated_obj)  # Đồng bộ tên khách trong rentals
    flash("Đã cập nhật khách hàng.", "success")  # Báo thành công
    return redirect(url_for("customers_list"))  # Quay lại danh sách khách

@app.route("/customers/delete/<cid>", methods=["POST"])
def customers_delete(cid):
    # Route xóa khách theo ID cid
    if require_login(): return require_login()  # Chặn nếu chưa login
    username = get_current_username()  # Lấy user
    rentals = read_json(user_file(username, "rentals.json"), [])  # Đọc rentals
    if any(r["customer_id"]==cid and not r.get("returned_at") for r in rentals):
        # Nếu khách còn giao dịch chưa trả
        flash("khách hàng còn giao dịch chưa trả truyện", "danger")  # Báo lỗi
        return redirect(url_for("customers_list"))  # Quay lại danh sách
    rentals = [r for r in rentals if r["customer_id"] != cid]  # Xóa rentals liên quan khách này
    write_json(user_file(username, "rentals.json"), rentals)  # Ghi lại rentals
    items = read_json(user_file(username, "customers.json"), [])  # Đọc list khách
    items = [x for x in items if x["id"] != cid]  # Loại bỏ khách cần xóa
    write_json(user_file(username, "customers.json"), items)  # Ghi lại file
    flash("Đã xóa khách hàng và lịch sử liên quan.", "success")  # Báo thành công
    return redirect(url_for("customers_list"))  # Quay lại danh sách khách

# ================== Thuê / Trả truyện ==================  # Khu xử lý giao dịch

@app.route("/rentals")
def rentals_list():
    # Route hiển thị danh sách thuê/trả
    if require_login(): 
        return require_login()  # Nếu chưa login thì redirect
    q = (request.args.get("q") or "").strip().lower()  # Lấy từ khóa tìm kiếm giao dịch
    username = get_current_username()  # Lấy user hiện tại

    rentals = read_json(user_file(username, "rentals.json"), [])  # Đọc list giao dịch thuê/trả

        # ===== TÍNH LẠI PHÍ TRỄ CHO CÁC GIAO DỊCH CHƯA TRẢ =====
    now = datetime.now()  # Lấy thời gian hiện tại để so với hạn trả
    shop_cfg = read_shop_cfg(username)  # Đọc cấu hình shop (phí trễ hiện tại)
    default_per_day = int(shop_cfg.get("late_fee_per_day", 10000) or 10000)
    # Lấy phí trễ/ngày mặc định, nếu cfg thiếu thì 10000

    for r in rentals:
        # Chỉ tính cho những giao dịch chưa trả
        if not r.get("returned_at"):  # Nếu returned_at rỗng => chưa trả
            try:
                due = parse_dt(r["due_at"])  # Parse ngày đến hạn trả
            except Exception:
                # Nếu dữ liệu ngày bị lỗi thì bỏ qua để không crash
                continue  # Bỏ qua rental lỗi format

            days_late = (now - due).days  # Tính số ngày trễ: hiện tại - hạn trả
            late_fee = 0  # Mặc định phí trễ = 0
            if days_late > 0:
                # Lấy phí trễ/ngày từ giao dịch, nếu không có thì dùng cấu hình hiện tại
                per_day = r.get("late_fee_per_day", default_per_day)  # Ưu tiên phí lưu lúc tạo GD
                try:
                    per_day_int = int(per_day)  # Ép phí/ngày thành int
                except Exception:
                    per_day_int = default_per_day  # Nếu lỗi ép -> dùng mặc định

                if per_day_int < 0:
                    per_day_int = 0  # Không cho phí âm

                late_fee = days_late * per_day_int  # Phí trễ = số ngày trễ * phí/ngày

            # Ghi lại vào object để hiển thị ra bảng
            r["late_fee"] = format_price(str(late_fee))  # Lưu late_fee dạng "10.000"
    # =======================================================

    rentals.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    # Sắp xếp giao dịch mới nhất lên trước
    if q:
        rentals = [
            r for r in rentals
            if q in r["manga_title"].lower() or q in r["customer_name"].lower()
        ]
        # Lọc giao dịch theo tên truyện hoặc tên khách chứa q
    unread_count = count_unread_notifications(username)  # Đếm noti chưa đọc
    return render_template(
        "rentals_list.html",
        rentals=rentals,
        q=q,
        unread_count=unread_count,
    )
    # Render rentals_list.html với list giao dịch + keyword + badge noti

@app.route("/api/manga-price")
def api_manga_price():
    # API trả giá thuê của 1 truyện để autofill ở form tạo giao dịch
    # Bắt buộc đăng nhập
    if require_login():
        return require_login()  # Nếu chưa login thì redirect

    username = get_current_username()  # Lấy user
    manga_id = (request.args.get("manga_id") or "").strip()  # Lấy manga_id từ query string

    items = read_json(user_file(username, "manga.json"), [])  # Đọc list truyện
    mg = next((m for m in items if m.get("id") == manga_id), None)
    # Tìm truyện có id = manga_id

    if not mg:
        return jsonify({"ok": False})  # Không tìm thấy truyện => trả ok False

    return jsonify({"ok": True, "price": mg.get("rent_price", "0")})
    # Nếu thấy truyện => trả ok True + giá thuê

@app.route("/api/manga-from-barcode")
def api_manga_from_barcode():
    """
    API tìm truyện theo mã vạch để dùng khi quét trong form tạo giao dịch.

    Trả về:
      { "ok": True, "id": "...", "price": "..." } nếu tìm thấy
      { "ok": False } nếu không tìm thấy
    """
    if require_login():
        return require_login()

    username = get_current_username()
    barcode = (request.args.get("barcode") or "").strip()

    if not barcode:
        return jsonify({"ok": False})

    items = read_json(user_file(username, "manga.json"), [])

    # Tìm truyện có barcode trùng khớp
    mg = next(
        (m for m in items if (m.get("barcode") or "").strip() == barcode),
        None,
    )

    if not mg:
        return jsonify({"ok": False})

    return jsonify(
        {
            "ok": True,
            "id": mg.get("id", ""),
            "price": mg.get("rent_price", "0"),
        }
    )

@app.route("/rentals/create", methods=["POST"])
def rentals_create():
    # Route tạo giao dịch thuê mới
    if require_login(): return require_login()  # Chặn nếu chưa login
    username = get_current_username()  # Lấy user
    customers = read_json(user_file(username, "customers.json"), [])  # Đọc list khách
    manga = read_json(user_file(username, "manga.json"), [])  # Đọc list truyện
    customer_id = (request.form.get("customer_id") or "").strip()  # Lấy id khách từ form
    manga_id = (request.form.get("manga_id") or "").strip()  # Lấy id truyện từ form
        # Đọc cấu hình cửa hàng (số ngày thuê + phí trễ)
    shop_cfg = read_shop_cfg(username)  # Đọc shop config
    rent_days = int(shop_cfg.get("default_rent_days", 5) or 5)
    # Lấy số ngày thuê mặc định, thiếu thì 5
    if rent_days < 1:
        rent_days = 1  # Không cho số ngày thuê nhỏ hơn 1

    rent_price = format_price(request.form.get("rent_price") or "0")  
    # Lấy giá thuê từ form và chuẩn hóa
    start_at = now_str()  # Thời điểm tạo giao dịch
    due_at = (datetime.now() + timedelta(days=rent_days)).strftime(DT_FMT)
    # Tính ngày đến hạn = hôm nay + rent_days

    cust = next((c for c in customers if c["id"]==customer_id), None)
    # Tìm khách đã chọn
    mg = next((m for m in manga if m["id"]==manga_id), None)
    # Tìm truyện đã chọn
    if not cust or not mg:
        flash("Không tìm thấy khách hàng hoặc truyện.", "danger")  # Báo lỗi nếu thiếu
        return redirect(url_for("rentals_list"))  # Quay về list
    if int(mg["stock"]) <= 0:
        flash("Truyện đã hết hàng.", "danger")  # Báo hết hàng
        return redirect(url_for("rentals_list"))  # Quay về list

    adjust_stock(username, manga_id, -1)  
    # Trừ tồn kho đi 1 vì vừa cho thuê

    rec = {
        # Tạo object giao dịch thuê mới
        "id": str(uuid.uuid4()),  # ID giao dịch duy nhất
        "manga_id": mg["id"],  # ID truyện thuê
        "manga_title": mg["title"],  # Tên truyện tại thời điểm thuê
        "customer_id": cust["id"],  # ID khách thuê
        "customer_name": cust["name"],  # Tên khách tại thời điểm thuê
        "rent_price": rent_price,  # Giá thuê
        "late_fee": "0",  # Phí trễ ban đầu là 0
        # lưu phí trễ theo ngày tại thời điểm tạo giao dịch
        "late_fee_per_day": int(shop_cfg.get("late_fee_per_day", 10000) or 0),
        # Lưu phí trễ/ngày tại thời điểm tạo để sau này cfg đổi vẫn giữ đúng
        "created_at": start_at,  # Ngày thuê
        "due_at": due_at,  # Ngày đến hạn
        "returned_at": "",  # Chưa trả nên rỗng
    }
    rentals = read_json(user_file(username, "rentals.json"), [])  # Đọc list rentals cũ
    rentals.append(rec)  # Thêm giao dịch mới
    write_json(user_file(username, "rentals.json"), rentals)  # Ghi list rentals mới

    # ------ Gửi email theo mẫu người dùng ------
    cfg = read_json(user_file(username, "email.json"), {})  
    # Đọc cấu hình email user
    tpl = cfg.get("tpl_rent") or default_email_cfg(session.get('shop_name','')).get("tpl_rent")
    # Lấy template thuê; nếu user chưa có thì dùng mặc định
    ctx = {
        # Tạo context để nhét vào template
        "customer_name": cust["name"],
        "manga_title": mg["title"],
        "rent_price": rent_price,
        "start_at": start_at,
        "due_at": due_at,
        "return_at": "",
        "late_fee": "0",
        "shop_name": session.get("shop_name","Cửa hàng")
    }
    subject = f"[{session.get('shop_name','Cửa hàng')}] Xác nhận thuê truyện"
    # Tiêu đề email
    html = render_tpl(tpl, ctx)  # Render template thành HTML hoàn chỉnh
    send_email_if_configured(username, subject, html, cust["email"])
    # Gửi email nếu user đã cấu hình
    # -------------------------------------------

    flash("Đã tạo giao dịch thuê.", "success")  # Thông báo tạo thành công
    return redirect(url_for("rentals_list"))  # Quay lại danh sách giao dịch

@app.route("/rentals/return/<rid>", methods=["POST"])
def rentals_return(rid):
    # Route xử lý trả truyện theo rental id rid
    if require_login(): return require_login()  # Chặn nếu chưa login
    username = get_current_username()  # Lấy user
    rentals = read_json(user_file(username, "rentals.json"), [])  # Đọc rentals
    customers = read_json(user_file(username, "customers.json"), [])  # Đọc list khách
    found = None  # Biến lưu giao dịch cần trả
    for r in rentals:  # Duyệt từng giao dịch
        if r["id"] == rid and not r.get("returned_at"):
            # Nếu đúng giao dịch và chưa trả
            found = r  # Lưu vào found
            break  # Thoát vòng lặp

    if not found:
        # Nếu không tìm thấy hoặc đã trả
        flash("Không tìm thấy giao dịch hoặc đã trả.", "danger")  # Báo lỗi
        return redirect(url_for("rentals_list"))  # Quay lại list
    else:
        # chỉ chạy khi tìm thấy giao dịch
        shop_cfg = read_shop_cfg(username)  # Đọc cấu hình hiện tại
        default_per_day = int(shop_cfg.get("late_fee_per_day", 10000) or 10000)
        # Phí trễ/ngày mặc định

        due = parse_dt(found["due_at"])  # Parse ngày đến hạn
        days_late = (datetime.now() - due).days  # Tính số ngày trễ

        late_fee = 0  # Mặc định phí trễ
        if days_late > 0:
            per_day = found.get("late_fee_per_day", default_per_day)
            # Lấy phí/ngày đã lưu lúc tạo giao dịch
            try:
                per_day_int = int(per_day)  # Ép int
            except Exception:
                per_day_int = default_per_day  # Lỗi ép -> dùng mặc định

            if per_day_int < 0:
                per_day_int = 0  # Không cho âm

            late_fee = days_late * per_day_int  # Phí trễ = ngày trễ * phí/ngày

    found["late_fee"] = format_price(str(late_fee))  # Lưu phí trễ dạng đẹp
    found["returned_at"] = now_str()  # Lưu thời điểm trả

    write_json(user_file(username, "rentals.json"), rentals)  
    # Ghi lại rentals sau khi update

    adjust_stock(username, found["manga_id"], +1)  
    # Cộng tồn kho lại 1 vì đã trả truyện

    cust = next((c for c in customers if c["id"]==found["customer_id"]), None)
    # Tìm khách của giao dịch này
    if cust:
        # Nếu tìm thấy khách
        cfg = read_json(user_file(username, "email.json"), {})  
        # Đọc cấu hình email
        tpl = cfg.get("tpl_return") or default_email_cfg(session.get('shop_name','')).get("tpl_return")
        # Lấy template trả truyện
        ctx = {
            # Context cho email trả
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
        # Tiêu đề email trả
        html = render_tpl(tpl, ctx)  # Render template trả
        send_email_if_configured(username, subject, html, cust["email"])
        # Gửi email thông báo trả truyện

    flash("Đã cập nhật trả truyện.", "success")  # Báo thành công
    return redirect(url_for("rentals_list"))  # Quay lại list

# ================== Thông báo ==================  # Khu thông báo stock thấp

@app.route("/notifications", methods=["GET","POST"])
def notifications():
    # Route hiển thị và cập nhật trạng thái thông báo
    if require_login():
        return require_login()  # Chặn nếu chưa login

    username = get_current_username()  # Lấy user hiện tại
    notifs_path = user_file(username, "notifications.json")  # File noti của user
    notifs = read_json(notifs_path, [])  # Đọc list noti

    if request.method == "POST":
        # Ưu tiên xử lý yêu cầu xóa toàn bộ thông báo
        delete_flag = request.args.get("delete")
        if delete_flag == "all":
            # Xóa TẤT CẢ thông báo của user
            notifs = []
            write_json(notifs_path, notifs)
            return jsonify({"ok": True})

        # Còn lại là đánh dấu đã đọc như cũ
        nid = request.args.get("read")  # Lấy id noti cần đánh dấu từ query

        if nid == "all":
            # Đánh dấu tất cả thông báo là đã đọc
            for n in notifs:
                n["read"] = True
        else:
            # Đánh dấu 1 thông báo (double-click)
            for n in notifs:
                if n["id"] == nid:
                    n["read"] = True
                    break

        write_json(notifs_path, notifs)  # Ghi list noti sau khi update
        return jsonify({"ok": True})  # Trả JSON ok cho frontend

    # GET: hiển thị trang thông báo
    notifs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    unread_count = count_unread_notifications(username)
    return render_template("notifications.html", notifs=notifs, unread_count=unread_count)

# ===================== THỐNG KÊ DOANH THU =====================  # Khu thống kê doanh thu

@app.route("/stats")
def stats():
    if require_login():
        return require_login()

    from datetime import datetime, timedelta

    username = get_current_username()
    rentals = read_json(user_file(username, "rentals.json"), [])
    customers = read_json(user_file(username, "customers.json"), [])
    manga = read_json(user_file(username, "manga.json"), [])

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

    # Hàm kiểm tra giao dịch có nằm trong khoảng ngày thuê hay không (created_at)
    def in_range(rec):
        try:
            t = parse_dt(rec["created_at"])
        except Exception:
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

    # Giữ lại bản đầy đủ để tính phí trễ theo NGÀY và các thống kê khác
    rentals_all = list(rentals)

    # Lọc danh sách theo khoảng ngày thuê (cho tổng giao dịch + tổng giá thuê)
    if date_from or date_to:
        rentals = [r for r in rentals if in_range(r)]

    # Hàm kiểm tra giao dịch có ngày trả nằm trong khoảng lọc hay không (returned_at)
    # (giữ lại nếu sau này cần, hiện tại không dùng cho phí trễ nữa)
    def in_return_range(rec):
        returned_at_str = rec.get("returned_at")
        if not returned_at_str:
            return False
        try:
            t = parse_dt(returned_at_str)
        except Exception:
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

    # ========= Chuẩn bị một số biến date cho việc tính phí trễ theo NGÀY =========
    def parse_date_only(s: str):
        try:
            return datetime.strptime(s, "%d-%m-%Y").date()
        except Exception:
            return None

    from_date = parse_date_only(date_from) if date_from else None
    to_date = parse_date_only(date_to) if date_to else None
    today_date = datetime.now().date()

    # ========== 1) Thống kê doanh thu (giữ logic tổng tiền thuê như cũ) ==========
    # Tổng số giao dịch + tổng giá thuê tính theo NGÀY THUÊ
    total_trans = len(rentals)
    total_rent = sum(price_to_int(r["rent_price"]) for r in rentals)

    # Tổng phí trễ sẽ được tính lại dựa trên từng NGÀY TRỄ (xem thêm bên dưới)
    total_late = 0

    # ========== 2) Thống kê tổng quan cửa hàng ==========
    total_customers = len(customers)
    total_manga = len(manga)

    # Giao dịch đang cho thuê (chưa có returned_at)
    rentals_open = [r for r in rentals_all if not r.get("returned_at")]
    total_active = len(rentals_open)

    # Giao dịch đang quá hạn
    now_dt = datetime.now()
    total_overdue = 0
    for r in rentals_open:
        try:
            due_dt = parse_dt(r["due_at"])
        except Exception:
            continue
        if due_dt < now_dt:
            total_overdue += 1

    # ========== 3) Chuẩn bị dữ liệu biểu đồ doanh thu theo ngày ==========
    rent_per_day = {}
    late_per_day = {}

    # Đọc cấu hình phí trễ/ngày mặc định để dùng khi rental không có late_fee_per_day riêng
    shop_cfg = read_shop_cfg(username)
    default_per_day = int(shop_cfg.get("late_fee_per_day", 10000) or 10000)

    def date_only_from_str(dt_str: str):
        try:
            return parse_dt(dt_str).date()
        except Exception:
            return None

    for r in rentals_all:
        # --- Doanh thu tiền thuê theo ngày thuê ---
        if in_range(r):
            try:
                d = parse_dt(r["created_at"]).strftime("%d-%m-%Y")
            except Exception:
                d = None
            if d:
                rent_per_day[d] = rent_per_day.get(d, 0) + price_to_int(r["rent_price"])

        # --- Phí trễ tính THEO TỪNG NGÀY TRỄ ---
        # Ngày đến hạn
        due_date = date_only_from_str(r.get("due_at", ""))
        if not due_date:
            continue

        # Ngày bắt đầu tính trễ là NGÀY SAU hạn trả
        start_late_date = due_date + timedelta(days=1)

        # Ngày kết thúc tính trễ:
        # - Nếu đã trả: lấy ngày trả
        # - Nếu chưa trả: lấy min(ngày hôm nay, to_date nếu người dùng chọn)
        returned_at_str = r.get("returned_at", "")
        if returned_at_str:
            end_late_date = date_only_from_str(returned_at_str)
        else:
            end_late_date = today_date

        if to_date and end_late_date and end_late_date > to_date:
            end_late_date = to_date

        # Nếu người dùng có chọn from_date thì không tính những ngày trước đó
        if from_date and start_late_date < from_date:
            start_late_date = from_date

        # Nếu sau khi hiệu chỉnh mà end < start thì không có ngày trễ nào trong khoảng lọc
        if not end_late_date or end_late_date < start_late_date:
            continue

        # Lấy phí trễ/ngày cho giao dịch này
        per_day = r.get("late_fee_per_day", default_per_day)
        try:
            per_day_int = int(per_day)
        except Exception:
            per_day_int = default_per_day
        if per_day_int < 0:
            per_day_int = 0

        # Cộng phí trễ cho từng ngày trong [start_late_date, end_late_date]
        cur = start_late_date
        while cur <= end_late_date:
            d_str = cur.strftime("%d-%m-%Y")
            late_per_day[d_str] = late_per_day.get(d_str, 0) + per_day_int
            total_late += per_day_int
            cur += timedelta(days=1)

    # Tổng phí trễ trong khoảng lọc = tổng phí của mọi ngày trễ
    total = total_rent + total_late

    all_days = sorted(
        set(list(rent_per_day.keys()) + list(late_per_day.keys())),
        key=lambda s: datetime.strptime(s, "%d-%m-%Y")
    )
    chart_labels = all_days
    chart_revenue = [
        rent_per_day.get(d, 0) + late_per_day.get(d, 0)
        for d in all_days
    ]

    # ========== 4) Chuẩn bị dữ liệu biểu đồ thể loại ==========
    manga_map = {m["id"]: m for m in manga}
    genre_count = {}

    for r in rentals:
        mg = manga_map.get(r.get("manga_id"))
        genre_str = ""
        if mg:
            genre_str = mg.get("genre", "") or ""
        parts = [p.strip() for p in genre_str.split(",") if p.strip()]
        if not parts:
            parts = ["Khác"]
        for g in parts:
            genre_count[g] = genre_count.get(g, 0) + 1

    genre_labels = list(genre_count.keys())
    genre_counts = [genre_count[g] for g in genre_labels]

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
        # mới
        total_customers=total_customers,
        total_manga=total_manga,
        total_active=total_active,
        total_overdue=total_overdue,
        chart_labels=chart_labels,
        chart_revenue=chart_revenue,
        genre_labels=genre_labels,
        genre_counts=genre_counts,
        unread_count=unread_count,
    )

# ============== Cấu hình email (thêm 2 mẫu) ==============  # Khu default email template

def default_email_cfg(shop_name: str = ""):
    # Hàm tạo cấu hình email mặc định
    return {
        # KHÔNG còn các field: smtp_host, smtp_port, smtp_user
        "smtp_pass": "",  # App password Gmail mặc định rỗng
        "sender_name": (shop_name if shop_name else ""),  # Tên hiển thị người gửi
        "sender_email": "",  # Email gửi mặc định rỗng
        "use_tls": True,  # Luôn dùng TLS với Gmail
        "tpl_rent": (
            # Template email khi thuê
            "Kính gửi {customer_name},<br>"
            "Bạn đã thuê truyện <b>{manga_title}</b> với giá <b>{rent_price} VND</b>.<br>"
            "Ngày thuê: {start_at}<br>Ngày đến hạn: {due_at}<br><br>"
            "Trân trọng,<br>{shop_name}"
        ),
        "tpl_return": (
            # Template email khi trả
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
    """
    Trang CẤU HÌNH:
      - Phần trên: Cấu hình cửa hàng
      - Phần dưới: Cấu hình email
    """  # Docstring mô tả chức năng trang
    if require_login():
        return require_login()  # Chặn nếu chưa login

    username = get_current_username()  # Lấy user
    shop_cfg = read_shop_cfg(username)  # Đọc shop_cfg

    # ----- CẤU HÌNH EMAIL -----
    path = user_file(username, "email.json")  # File email.json của user
    cfg = read_json(path, {})  # Đọc cấu hình email hiện có

    # Khôi phục mẫu mặc định (chỉ ảnh hưởng tới template email)
    if request.method == "GET" and request.args.get("reset_tpl") == "1":
        # Nếu mở trang bằng ?reset_tpl=1 thì reset template
        base = default_email_cfg(shop_cfg.get("shop_name", ""))  # Lấy template default theo shop_name
        cfg.setdefault("smtp_pass", "")  # Nếu chưa có smtp_pass thì set rỗng
        cfg.setdefault("sender_name", shop_cfg.get("shop_name", "Cửa Hàng Truyện Tranh 2025"))
        # Nếu chưa có sender_name thì set theo tên shop
        cfg.setdefault("sender_email", "")  # Nếu thiếu sender_email thì set rỗng
        cfg.setdefault("use_tls", True)  # Nếu thiếu use_tls thì set True
        cfg["tpl_rent"] = base["tpl_rent"]  # Ghi đè tpl_rent về default
        cfg["tpl_return"] = base["tpl_return"]  # Ghi đè tpl_return về default
        write_json(path, cfg)  # Ghi lại email.json
        flash("Đã khôi phục mẫu email mặc định.", "success")  # Thông báo
        return redirect(url_for("email_settings"))  # Reload trang cấu hình

    if request.method == "POST":
        # Nếu submit form cấu hình
        action = (request.form.get("action") or "").strip()
        # Lấy action để biết form bên shop hay email

        # ----- LƯU CẤU HÌNH CỬA HÀNG -----
        if action == "shop":
            shop_name = (request.form.get("shop_name") or "").strip()  # Lấy shop_name từ form
            if not shop_name:
                shop_name = shop_cfg.get("shop_name", "")  # Nếu bỏ trống thì giữ cũ

            def safe_int(val, default):
                # Hàm nhỏ ép int an toàn
                try:
                    return int(val)  # Ép int
                except Exception:
                    return default  # Lỗi -> dùng default

            default_days = safe_int(
                request.form.get("default_rent_days"),
                shop_cfg.get("default_rent_days", 5),
            )  # Lấy số ngày thuê mặc định mới

            late_per_day = safe_int(
                request.form.get("late_fee_per_day"),
                shop_cfg.get("late_fee_per_day", 10000),
            )  # Lấy phí trễ/ngày mới

            if default_days < 1:
                default_days = 1  # Không cho ngày thuê <1
            if late_per_day < 0:
                late_per_day = 0  # Không cho phí âm

            shop_cfg.update(
                {
                    "shop_name": shop_name,  # Update tên shop
                    "default_rent_days": default_days,  # Update số ngày thuê
                    "late_fee_per_day": late_per_day,  # Update phí trễ/ngày
                }
            )
            write_json(user_file(username, "shop_config.json"), shop_cfg)
            # Ghi shop_cfg mới vào file shop_config.json

            # Cập nhật users.json để lần đăng nhập sau vẫn thấy tên mới
            users = read_json(USERS_FILE, [])  # Đọc users.json chung
            changed = False  # Cờ đánh dấu có đổi không
            for u in users:  # Duyệt users
                if u.get("username") == username:  # Đúng user hiện tại
                    u["shop_name"] = shop_name  # Update shop_name trong users.json
                    changed = True  # Đánh dấu đã đổi
                    break  # Thoát vòng lặp
            if changed:
                write_json(USERS_FILE, users)  # Ghi lại users.json nếu có đổi

            # Cập nhật session hiện tại
            session["shop_name"] = shop_name  # Update shop_name trong session

            flash("Đã lưu cấu hình cửa hàng.", "success")  # Thông báo thành công
            return redirect(url_for("email_settings"))  # Reload trang

        # ----- LƯU CẤU HÌNH EMAIL -----
        else:
            cfg = {
                "smtp_pass": (request.form.get("smtp_pass") or "").strip(),  # App password Gmail
                "sender_name": (request.form.get("sender_name") or "").strip(),  # Tên hiển thị khi gửi
                "sender_email": (request.form.get("sender_email") or "").strip(),  # Email gửi
                "use_tls": True,  # luôn dùng STARTTLS với Gmail
                "tpl_rent": (request.form.get("tpl_rent") or "").strip(),  # Template thuê do user nhập
                "tpl_return": (request.form.get("tpl_return") or "").strip(),  # Template trả do user nhập
            }
            base = default_email_cfg(shop_cfg.get("shop_name", ""))  # Lấy template default
            if not cfg.get("tpl_rent"):
                cfg["tpl_rent"] = base["tpl_rent"]  # Nếu tpl_rent rỗng -> dùng default
            if not cfg.get("tpl_return"):
                cfg["tpl_return"] = base["tpl_return"]  # Nếu tpl_return rỗng -> dùng default
            write_json(path, cfg)  # Ghi email.json mới
            flash("Đã lưu cấu hình email.", "success")  # Thông báo
            return redirect(url_for("email_settings"))  # Reload trang

    # Đảm bảo có sẵn mẫu mặc định lần đầu mở
    if not cfg.get("tpl_rent") or not cfg.get("tpl_return"):
        base = default_email_cfg(shop_cfg.get("shop_name", ""))  # Lấy default template
        cfg.setdefault("tpl_rent", base["tpl_rent"])  # Nếu thiếu tpl_rent thì set default
        cfg.setdefault("tpl_return", base["tpl_return"])  # Nếu thiếu tpl_return thì set default
        write_json(path, cfg)  # Ghi lại email.json để lần sau có sẵn

    unread_count = count_unread_notifications(username)  # Đếm noti chưa đọc
    return render_template(
        "email_settings.html",
        cfg=cfg,
        shop_cfg=shop_cfg,
        unread_count=unread_count,
    )
    # Render trang email_settings.html

# ================== Run ==================  # Khu chạy app

if __name__ == "__main__":
    # Chỉ chạy khi bạn chạy file trực tiếp: python app.py
    ensure_dirs()  # Đảm bảo data folder/file sẵn sàng
    app.run(debug=True)  # Chạy Flask ở chế độ debug (tự reload, hiện lỗi chi tiết)
