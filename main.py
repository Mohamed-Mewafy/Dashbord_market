import os
import json
import random
import firebase_admin
from firebase_admin import credentials, firestore, auth
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# ---------------- Firebase init ----------------
FIREBASE_SA_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
if FIREBASE_SA_JSON:
    sa_info = json.loads(FIREBASE_SA_JSON)
    cred = credentials.Certificate(sa_info)
else:
    cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "firebase-service-account.json")
    if not os.path.exists(cred_path):
        raise RuntimeError("Firebase service account not found. Set FIREBASE_SERVICE_ACCOUNT_JSON or provide firebase-service-account.json")
    cred = credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ---------------- Flask app (serve static dashboard) ----------------
# افترض أن ملفات الواجهة موجودة في مجلد 'src' داخل المشروع
STATIC_FOLDER = os.getenv("STATIC_FOLDER", "src")  # غيّر لو عندك اسم مجلد مختلف
app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='/')
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24))

# ---------------- CORS ----------------
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    # أضف دومينات الواجهات اللي تستخدمها
    "https://bin-sports3low.epizy.com",
    "https://ports3low.epizy.com",
    "https://your-site.vercel.app",
]
CORS(app, origins=CORS_ALLOWED_ORIGINS, supports_credentials=True)

# ---------------- Serve dashboard pages ----------------
# Serve the dashboard index at root. If you prefer /dashboard, change route accordingly.
@app.route('/', methods=['GET'])
def serve_index():
    # إذا كان لديك index.html داخل مجلد static_folder (مثلاً src/index.html)
    return app.send_static_file('index.html')

# Optional: also serve dashboard under /dashboard for clarity
@app.route('/dashboard', methods=['GET'])
def serve_dashboard():
    return app.send_static_file('index.html')

# If you have other static assets in subpaths (css/js/images) Flask will already serve them
# because we set static_folder and static_url_path='/' above.

# ---------------- API endpoints (unchanged) ----------------

@app.route('/api/health')
def health():
    return jsonify({"msg": "API يعمل بنجاح 🎉"})

@app.route('/api/products', methods=['GET', 'POST'])
def products_handler():
    products_ref = db.collection('products')

    if request.method == 'GET':
        try:
            # حاول ترتيب حسب created_at وإذا فشل اعمل fallback
            try:
                docs = list(products_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream())
            except Exception:
                docs = list(products_ref.stream())
            items = []
            for d in docs:
                p = d.to_dict()
                p['id'] = d.id
                if 'created_at' in p and p['created_at']:
                    try:
                        p['created_at'] = p['created_at'].timestamp()
                    except Exception:
                        pass
                items.append(p)
            return jsonify(items)
        except Exception as e:
            return jsonify({"msg": f"خطأ في جلب المنتجات: {e}"}), 500

    # POST -> إضافة منتج (محمي بتوكن Firebase)
    if request.method == 'POST':
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"msg": "Unauthorized"}), 401
        try:
            id_token = auth_header.split('Bearer ')[1]
            decoded = auth.verify_id_token(id_token)
            payload = request.get_json() or {}
            payload['creator_uid'] = decoded.get('uid')
            payload['added_by'] = decoded.get('email')
            payload['created_at'] = firestore.SERVER_TIMESTAMP
            _, ref = products_ref.add(payload)
            new_doc = ref.get().to_dict()
            new_doc['id'] = ref.id
            return jsonify(new_doc), 201
        except Exception as e:
            return jsonify({"msg": "Failed to create product", "error": str(e)}), 500


@app.route('/api/products/<string:product_id>', methods=['GET', 'PUT', 'DELETE'])
def product_item(product_id):
    product_ref = db.collection('products').document(product_id)
    doc = product_ref.get()
    if not doc.exists:
        return jsonify({"msg": "Product not found"}), 404

    product_data = doc.to_dict()
    if request.method == 'GET':
        product_data['id'] = doc.id
        if 'created_at' in product_data and product_data['created_at']:
            try:
                product_data['created_at'] = product_data['created_at'].timestamp()
            except Exception:
                pass
        return jsonify(product_data)

    # For update/delete require owner auth
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"msg": "Unauthorized"}), 401
    try:
        id_token = auth_header.split('Bearer ')[1]
        decoded = auth.verify_id_token(id_token)
    except Exception as e:
        return jsonify({"msg": f"Invalid token: {e}"}), 401

    is_owner = product_data.get('creator_uid') == decoded.get('uid')
    if not is_owner:
        return jsonify({"msg": "Forbidden: not owner"}), 403

    if request.method == 'PUT':
        update_data = request.get_json() or {}
        if 'quantity' in update_data:
            try:
                q = int(update_data['quantity'])
                update_data['quantity'] = q
                update_data['status'] = 'available' if q > 0 else 'unavailable'
            except Exception:
                pass
        product_ref.update(update_data)
        updated = product_ref.get().to_dict()
        updated['id'] = product_ref.id
        return jsonify(updated)

    if request.method == 'DELETE':
        product_ref.delete()
        return '', 204

# ---------------- run ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))