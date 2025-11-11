import os
import json
import random
import firebase_admin
import google.generativeai as genai
from firebase_admin import credentials, firestore, auth
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

# -----------------------------------------------------------
# تحميل متغيرات البيئة
# -----------------------------------------------------------
load_dotenv()

# -----------------------------------------------------------
# إعداد Firebase
# -----------------------------------------------------------
FIREBASE_SA_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

if FIREBASE_SA_JSON:
    try:
        sa_info = json.loads(FIREBASE_SA_JSON)
        cred = credentials.Certificate(sa_info)
    except Exception as e:
        raise RuntimeError(f"فشل تحميل بيانات الخدمة: {e}")
else:
    cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "firebase-service-account.json")
    if not os.path.exists(cred_path):
        raise RuntimeError("لم يتم العثور على بيانات Firebase Service Account.")
    cred = credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -----------------------------------------------------------
# إعداد Gemini API
# -----------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("يرجى إضافة GEMINI_API_KEY إلى متغيرات البيئة.")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# -----------------------------------------------------------
# إنشاء تطبيق Flask
# -----------------------------------------------------------
app = Flask(__name__, static_folder='src', static_url_path='/')
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24))

# -----------------------------------------------------------
# إعدادات CORS للسماح باتصال InfinityFree وVercel
# -----------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://your-site.vercel.app",
    "https://ports3low.epizy.com",  # 🔥 موقعك على InfinityFree
    "https://*.epizy.com"
]

app.config['CORS_HEADERS'] = 'Content-Type'
CORS(app, origins=CORS_ALLOWED_ORIGINS, supports_credentials=True)
# -----------------------------------------------------------


# -----------------------------------------------------------
# المسارات (Endpoints)
# -----------------------------------------------------------

@app.route('/')
def index():
    return jsonify({"msg": "API يعمل بنجاح 🚀"})


# 🧩 عرض المنتجات أو إضافة منتج جديد
@app.route("/api/products", methods=['GET', 'POST'])
def handle_products():
    products_ref = db.collection('products')

    # ✅ السماح بقراءة عامة بدون توثيق (GET فقط)
    if request.method == 'GET':
        try:
            docs = list(products_ref.stream())
            products = []
            for doc in docs:
                p = doc.to_dict()
                p['id'] = doc.id
                if 'created_at' in p and p['created_at']:
                    try:
                        p['created_at'] = p['created_at'].timestamp()
                    except Exception:
                        pass
                products.append(p)
            return jsonify(products)
        except Exception as e:
            return jsonify({"msg": f"خطأ في جلب المنتجات: {e}"}), 500

    # 🔒 إضافة منتج جديد (تتطلب توثيق Firebase)
    if request.method == 'POST':
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"msg": "ممنوع بدون توثيق"}), 401
        try:
            id_token = auth_header.split('Bearer ')[1]
            decoded_token = auth.verify_id_token(id_token)
            data = request.get_json() or {}
            data['creator_uid'] = decoded_token.get('uid')
            data['added_by'] = decoded_token.get('email')
            data['created_at'] = firestore.SERVER_TIMESTAMP
            _, ref = products_ref.add(data)
            new_product = ref.get().to_dict()
            new_product['id'] = ref.id
            return jsonify(new_product), 201
        except Exception as e:
            return jsonify({"msg": f"فشل إضافة المنتج: {e}"}), 500


# 🧩 عرض تفاصيل منتج محدد
@app.route('/api/products/<string:product_id>', methods=['GET'])
def get_product(product_id):
    try:
        doc = db.collection('products').document(product_id).get()
        if not doc.exists:
            return jsonify({"msg": "المنتج غير موجود"}), 404
        product = doc.to_dict()
        product['id'] = doc.id
        if 'created_at' in product and product['created_at']:
            try:
                product['created_at'] = product['created_at'].timestamp()
            except Exception:
                pass
        return jsonify(product)
    except Exception as e:
        return jsonify({"msg": f"حدث خطأ أثناء جلب المنتج: {e}"}), 500


# 🧩 تحليلات بسيطة (اختياري)
@app.route('/api/analytics')
def get_analytics():
    try:
        total_products = len(list(db.collection('products').stream()))
    except Exception:
        total_products = 0
    return jsonify({
        "total_products": total_products,
        "site_visits": random.randint(1000, 5000),
        "sales_data": {
            "labels": ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو"],
            "values": [random.randint(100, 400) for _ in range(6)]
        }
    })


# -----------------------------------------------------------
# تشغيل التطبيق
# -----------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)