import os
import json
import logging
import traceback
from urllib.parse import urlparse
from flask import Flask, request, jsonify
from flask_cors import CORS
from firebase_admin import credentials, initialize_app, firestore, auth as firebase_auth
from dotenv import load_dotenv

# ------------------------------------------------------
# تحميل المتغيرات والتهيئة
# ------------------------------------------------------
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("store-api")

STATIC_FOLDER = os.getenv("STATIC_FOLDER", "src")
app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path="/")
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))

# ------------------------------------------------------
# إعداد CORS (الإصلاح النهائي)
# ------------------------------------------------------
# دومين موقعك على Netlify:
NETLIFY_ORIGIN = os.getenv("NETLIFY_ORIGIN", "https://md-market.netlify.app")

CORS(
    app,
    resources={r"/api/*": {"origins": [NETLIFY_ORIGIN, "http://localhost:5500", "http://127.0.0.1:5500"]}},
    supports_credentials=True,
)

@app.after_request
def add_cors_headers(response):
    """
    يضيف رؤوس CORS لضمان عمل الطلبات من المتصفح
    """
    origin = request.headers.get("Origin")
    allowed_origins = [NETLIFY_ORIGIN, "http://localhost:5500", "http://127.0.0.1:5500"]

    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        response.headers["Access-Control-Allow-Origin"] = NETLIFY_ORIGIN

    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response

logger.info(f"CORS enabled for {NETLIFY_ORIGIN}")


# --- Ensure robust CORS headers on every response (extra safety) ---
@app.after_request
def add_cors_headers(response):
    """
    Add Access-Control-Allow-* headers robustly.
    Uses `origins_list` defined above to allow only permitted origins,
    or reflects Origin if origins_list == "*".
    """
    try:
        origin = request.headers.get('Origin')
        # If configured wildcard, allow the incoming origin or "*" if none provided
        if origins_list == "*" or origins_list == ['*']:
            # reflect origin if present, otherwise allow all
            response.headers['Access-Control-Allow-Origin'] = origin or '*'
        else:
            if origin:
                # exact match check
                for allowed in origins_list:
                    if allowed == origin:
                        response.headers['Access-Control-Allow-Origin'] = origin
                        break
                    # also allow match by hostname (in case allowed stored without protocol)
                    try:
                        ao = urlparse(allowed).netloc or allowed
                        if ao and ao in origin:
                            response.headers['Access-Control-Allow-Origin'] = origin
                            break
                    except Exception:
                        continue
        # common CORS headers (make sure headers match what frontend may send)
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    except Exception as e:
        logger.exception("after_request CORS header set failed: %s", e)
    return response

# Firebase Admin initialization (expects FIREBASE_SERVICE_ACCOUNT_JSON env var)
FIREBASE_SA_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
if not FIREBASE_SA_JSON:
    logger.error("FIREBASE_SERVICE_ACCOUNT_JSON env var missing")
    raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON not set")

try:
    sa_obj = json.loads(FIREBASE_SA_JSON)
    cred = credentials.Certificate(sa_obj)
    initialize_app(cred)
    db = firestore.client()
    logger.info("Initialized Firebase Admin SDK")
except Exception as e:
    logger.exception("Failed to initialize Firebase Admin SDK: %s", e)
    raise

# Optional AI config (not required)
try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Gemini configured")
    else:
        model = None
except Exception:
    model = None
    logger.warning("google.generativeai not available or failed to configure")

# Main admin uid (put your UID in Railway env MAIN_ADMIN_UID)
MAIN_ADMIN_UID = os.getenv("MAIN_ADMIN_UID", "").strip()
ALLOWED_ROLES = {'admin', 'publisher', 'moderator', 'viewer'}

# ---------------- Helpers ----------------
def get_request_user():
    return getattr(request, 'user', None)

def load_user_doc(uid):
    try:
        doc = db.collection('users').document(uid).get()
        return doc.to_dict() if doc.exists else None
    except Exception:
        logger.exception("Failed to load user doc")
        return None

def has_role(user, role):
    if not user:
        return False
    uid = user.get('uid')
    if uid == MAIN_ADMIN_UID and MAIN_ADMIN_UID:
        return True
    doc = load_user_doc(uid)
    if not doc:
        return False
    return doc.get('role') == role

# ---------------- Auth middleware ----------------
@app.before_request
def verify_token():
    # allow CORS preflight
    if request.method == 'OPTIONS':
        return

    # public endpoints
    if request.path.startswith('/api/public'):
        return

    # allow static and root
    if request.path == '/' or request.path.startswith(f'/{STATIC_FOLDER}') or request.path.startswith('/static'):
        return

    # allow public GET on /api/products
    if request.path == '/api/products' and request.method == 'GET':
        return

    # require token for other /api endpoints
    if request.path.startswith('/api'):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            logger.debug("Missing Authorization header for %s %s", request.method, request.path)
            return jsonify({"msg": "Missing or invalid authorization token"}), 401
        try:
            id_token = auth_header.split('Bearer ')[1]
            decoded = firebase_auth.verify_id_token(id_token)
            request.user = decoded
        except Exception as e:
            logger.warning("Token verify failed: %s", e)
            return jsonify({"msg": f"Invalid token: {e}"}), 401

# ---------------- Routes: Static ----------------
@app.route("/")
def index():
    try:
        return app.send_static_file('index.html')
    except Exception:
        return jsonify({"msg": "API ready"}), 200

# ---------------- Products endpoints ----------------
@app.route("/api/products", methods=['GET', 'POST'])
def handle_products():
    products_ref = db.collection('products')

    # POST: create product -> set status 'available' immediately (no admin review)
    if request.method == 'POST':
        try:
            user = get_request_user()
            if not user:
                return jsonify({"msg":"Unauthorized"}), 401

            data = request.get_json() or {}
            name = data.get('name')
            if not name:
                return jsonify({"msg":"Product name required"}), 400

            try:
                quantity = int(data.get('quantity', 0))
            except Exception:
                quantity = 0
            try:
                price = float(data.get('price', 0.0))
            except Exception:
                price = 0.0

            doc_data = {
                'name': name,
                'price': price,
                'quantity': quantity,
                'image_url': data.get('image_url', ''),
                'description': data.get('description', ''),
                'creator_uid': user.get('uid'),
                'added_by': user.get('email'),
                'status': 'available',    # available immediately
                'created_at': firestore.SERVER_TIMESTAMP
            }

            added = products_ref.add(doc_data)
            ref = added[1] if isinstance(added, (list,tuple)) else added
            new_product = ref.get().to_dict() or {}
            new_product['id'] = ref.id

            return jsonify({"msg":"Product created","product": new_product}), 201

        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Failed to create product: %s\n%s", e, tb)
            return jsonify({"msg":"Failed to create product","error": str(e)}), 500

    # GET: public & authenticated behavior
    try:
        user = get_request_user()
        if not user:
            # unauthenticated: return only available products
            docs = products_ref.where('status', '==', 'available').order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        else:
            if has_role(user, 'admin'):
                docs = products_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream()
            else:
                # normal user: return only their own products
                docs = products_ref.where('creator_uid', '==', user.get('uid')).order_by('created_at', direction=firestore.Query.DESCENDING).stream()

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
        return jsonify(products), 200
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Failed to fetch products: %s\n%s", e, tb)
        return jsonify({"msg":"Failed to fetch products","error":str(e)}), 500

@app.route("/api/products/<string:product_id>", methods=['GET', 'PUT', 'DELETE'])
def product_detail(product_id):
    ref = db.collection('products').document(product_id)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"msg":"Product not found"}), 404
    product = doc.to_dict()
    user = get_request_user()

    # GET
    if request.method == 'GET':
        product['id'] = doc.id
        if 'created_at' in product and product['created_at']:
            try: product['created_at'] = product['created_at'].timestamp()
            except Exception: pass
        return jsonify(product), 200

    # subsequent methods require owner or admin
    if not user:
        return jsonify({"msg":"Unauthorized"}), 401
    uid = user.get('uid')
    is_owner = product.get('creator_uid') == uid
    if not (is_owner or has_role(user, 'admin')):
        return jsonify({"msg":"Forbidden"}), 403

    if request.method == 'PUT':
        update_data = request.get_json() or {}
        if 'quantity' in update_data:
            try:
                update_data['quantity'] = int(update_data['quantity'])
            except:
                update_data['quantity'] = 0
        ref.update(update_data)
        updated = ref.get().to_dict()
        updated['id'] = ref.id
        return jsonify(updated), 200

    if request.method == 'DELETE':
        ref.delete()
        return '', 204

# Approve / Reject remain for admin if you still want them (not used if auto-available)
@app.route("/api/products/<string:product_id>/approve", methods=['POST'])
def approve_product(product_id):
    user = get_request_user()
    if not user or not has_role(user, 'admin'):
        return jsonify({"msg":"Forbidden"}), 403
    ref = db.collection('products').document(product_id)
    if not ref.get().exists:
        return jsonify({"msg":"Product not found"}), 404
    ref.update({
        'status': 'available',
        'approved_by': user.get('uid'),
        'approved_at': firestore.SERVER_TIMESTAMP
    })
    return jsonify({"msg":"Product approved"}), 200

@app.route("/api/products/<string:product_id>/reject", methods=['POST'])
def reject_product(product_id):
    user = get_request_user()
    if not user or not has_role(user, 'admin'):
        return jsonify({"msg":"Forbidden"}), 403
    data = request.get_json() or {}
    reason = data.get('reason')
    ref = db.collection('products').document(product_id)
    if not ref.get().exists:
        return jsonify({"msg":"Product not found"}), 404
    ref.update({
        'status': 'rejected',
        'rejected_by': user.get('uid'),
        'rejected_at': firestore.SERVER_TIMESTAMP
    })
    # optionally store rejection reason in document
    if reason:
        ref.update({'rejection_reason': reason})
    return jsonify({"msg":"Product rejected"}), 200

# My products (for dashboard)
@app.route("/api/my/products", methods=['GET'])
def my_products():
    user = get_request_user()
    if not user:
        return jsonify({"msg":"Unauthorized"}), 401
    try:
        uid = user.get('uid')
        docs = db.collection('products').where('creator_uid', '==', uid).order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        products = []
        for doc in docs:
            p = doc.to_dict()
            p['id'] = doc.id
            if 'created_at' in p and p['created_at']:
                try: p['created_at'] = p['created_at'].timestamp()
                except: pass
            products.append(p)
        return jsonify(products), 200
    except Exception as e:
        logger.exception("Failed to fetch my products")
        return jsonify({"msg":"Failed to fetch products","error":str(e)}), 500

# Public products endpoint
@app.route("/api/public/products", methods=['GET'])
def public_products():
    try:
        docs = db.collection('products').where('status', '==', 'available').order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        products = []
        for doc in docs:
            p = doc.to_dict()
            p['id'] = doc.id
            if 'created_at' in p and p['created_at']:
                try: p['created_at'] = p['created_at'].timestamp()
                except: pass
            products.append(p)
        return jsonify(products), 200
    except Exception as e:
        logger.exception("Failed to fetch public products")
        return jsonify({"msg":"Failed to fetch public products","error":str(e)}), 500

# Test route for CORS diagnostics (temporary)
@app.route("/api/_test_cors", methods=['GET', 'OPTIONS'])
def test_cors():
    """
    Simple route to check CORS headers and origin detection in browser.
    Open from frontend domain and check Network/Console for Access-Control-Allow-Origin header.
    """
    return jsonify({
        "ok": True,
        "origin_received": request.headers.get('Origin')
    }), 200

# Analytics (placeholder)
@app.route("/api/analytics", methods=['GET'])
def get_analytics():
    try:
        total_products = len(list(db.collection('products').stream()))
        return jsonify({
            "total_products": total_products,
            "site_visits": 0,
            "sales_data": {
                "labels": ["يناير","فبراير","مارس","أبريل","مايو","يونيو"],
                "values": [0,0,0,0,0,0]
            }
        }), 200
    except Exception as e:
        logger.exception("analytics error")
        return jsonify({"msg":"Failed to get analytics","error":str(e)}), 500

# AI description (optional)
@app.route("/api/generate-description", methods=['POST'])
def generate_ai_description():
    if model is None:
        return jsonify({"msg":"AI model not configured"}), 501
    product_name = (request.json or {}).get('product_name')
    if not product_name:
        return jsonify({"msg":"Product name required"}), 400
    try:
        prompt = f"""Create a compelling Arabic marketing description for the product named "{product_name}". 2-3 paragraphs, call to action at the end."""
        response = model.generate_content(prompt)
        return jsonify({"description": response.text}), 200
    except Exception as e:
        logger.exception("AI generation failed")
        return jsonify({"msg":"AI generation failed","error":str(e)}), 500

# Admin user management
@app.route("/api/admin/create_user", methods=['POST'])
def admin_create_user():
    user = get_request_user()
    if not user or not has_role(user, 'admin'):
        return jsonify({"msg":"Forbidden"}), 403
    data = request.get_json() or {}
    email = data.get('email')
    password = data.get('password') or "TempPass#123"
    role = data.get('role', 'publisher')
    if role not in ALLOWED_ROLES:
        return jsonify({"msg":"Invalid role"}), 400
    try:
        new_user = firebase_auth.create_user(email=email, password=password)
        uid = new_user.uid
        db.collection('users').document(uid).set({
            "email": email,
            "role": role,
            "active": True,
            "created_by": user.get('uid'),
            "created_at": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"msg":"User created","uid":uid}), 201
    except Exception as e:
        logger.exception("create user failed")
        return jsonify({"msg":"Failed to create user","error":str(e)}), 500

@app.route("/api/admin/users", methods=['GET'])
def admin_list_users():
    user = get_request_user()
    if not user or not has_role(user, 'admin'):
        return jsonify({"msg":"Forbidden"}), 403
    docs = db.collection('users').stream()
    users = []
    for d in docs:
        u = d.to_dict(); u['uid'] = d.id
        users.append(u)
    return jsonify(users), 200

@app.route("/api/admin/users/<string:uid>", methods=['PUT'])
def admin_update_user(uid):
    user = get_request_user()
    if not user or not has_role(user, 'admin'):
        return jsonify({"msg":"Forbidden"}), 403
    data = request.get_json() or {}
    update = {}
    if 'role' in data and data['role'] in ALLOWED_ROLES:
        update['role'] = data['role']
    if 'active' in data:
        update['active'] = bool(data['active'])
    if not update:
        return jsonify({"msg":"No updates provided"}), 400
    try:
        db.collection('users').document(uid).update(update)
        return jsonify({"msg":"User updated"}), 200
    except Exception as e:
        logger.exception("user update failed")
        return jsonify({"msg":"Failed to update user","error":str(e)}), 500

# Cleanup (admin only)
@app.route("/api/cleanup-old-products", methods=['POST'])
def cleanup_old_products():
    user = get_request_user()
    if not user or not has_role(user, 'admin'):
        return jsonify({"msg":"Forbidden"}), 403
    try:
        docs = db.collection('products').where('creator_uid', '==', None).stream()
        deleted = 0
        for d in docs:
            d.reference.delete()
            deleted += 1
        return jsonify({"msg": f"Deleted {deleted} ownerless products"}), 200
    except Exception as e:
        logger.exception("cleanup failed")
        return jsonify({"msg":"Cleanup failed","error":str(e)}), 500

# Run
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)
