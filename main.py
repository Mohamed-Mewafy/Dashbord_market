# app.py (محدّث) - يسمح للواجهة العامة بقراءة المنتجات دون توكن
import os
import json
import logging
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from firebase_admin import credentials, initialize_app, firestore, auth as firebase_auth
from dotenv import load_dotenv

# load local .env in dev
load_dotenv()

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("store-api")

# Flask app & static folder
STATIC_FOLDER = os.getenv("STATIC_FOLDER", "src")
app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='/')
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
if CORS_ORIGINS and CORS_ORIGINS != "*":
    origins_list = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
else:
    origins_list = "*"  # allow all if not specified
CORS(app, origins=origins_list, supports_credentials=True)
logger.info("CORS origins: %s", origins_list)

# Firebase initialization
FIREBASE_SA_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
if not FIREBASE_SA_JSON:
    logger.error("FIREBASE_SERVICE_ACCOUNT_JSON env var missing - cannot init Firebase Admin SDK")
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

# Optional AI (Gemini) - keep safe if not configured
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

# Admin UID for main admin
MAIN_ADMIN_UID = os.getenv("MAIN_ADMIN_UID", "").strip()
ALLOWED_ROLES = {'admin', 'publisher', 'moderator', 'viewer'}

# helpers
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
    if uid == MAIN_ADMIN_UID:
        return True
    doc = load_user_doc(uid)
    if not doc:
        return False
    return doc.get('role') == role

# Auth middleware
@app.before_request
def verify_token():
    # allow CORS preflight
    if request.method == 'OPTIONS':
        return

    # allow public endpoints
    if request.path.startswith('/api/public'):
        return

    # allow static files and root
    if request.path == '/' or request.path.startswith(f'/{STATIC_FOLDER}') or request.path.startswith('/static'):
        return

    # Allow public GET on /api/products (returns available products when not authenticated)
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

# Serve index
@app.route("/")
def index():
    try:
        return app.send_static_file('index.html')
    except Exception:
        return jsonify({"msg": "API ready"}), 200

# Products endpoints
@app.route("/api/products", methods=['GET', 'POST'])
def handle_products():
    products_ref = db.collection('products')

    # POST: create new product (publisher only)
    if request.method == 'POST':
        try:
            user = get_request_user()
            if not user:
                return jsonify({"msg":"Unauthorized"}), 401
            if not has_role(user, 'publisher'):
                return jsonify({"msg":"Your account is not allowed to publish products."}), 403

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
                'status': 'pending',  # default pending for admin approval
                'created_at': firestore.SERVER_TIMESTAMP
            }

            added = products_ref.add(doc_data)
            if isinstance(added, (list, tuple)):
                ref = added[-1]
            else:
                ref = added
            new_product = ref.get().to_dict()
            new_product['id'] = ref.id
            return jsonify(new_product), 201
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Failed to create product: %s\n%s", e, tb)
            return jsonify({"msg":"Failed to create product","error": str(e)}), 500

    # GET: if no user (public) return available products; if user present follow rules
    try:
        user = get_request_user()
        if not user:
            # public: only available
            docs = products_ref.where('status', '==', 'available').order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        else:
            if has_role(user, 'admin'):
                docs = products_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream()
            else:
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

    if request.method == 'GET':
        product['id'] = doc.id
        if 'created_at' in product and product['created_at']:
            try: product['created_at'] = product['created_at'].timestamp()
            except Exception: pass
        return jsonify(product), 200

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

# Approve / Reject (admin only)
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
    update = {
        'status': 'rejected',
        'rejected_by': user.get('uid'),
        'rejected_at': firestore.SERVER_TIMESTAMP
    }
    if reason:
        update['rejection_reason'] = reason
    ref.update(update)
    return jsonify({"msg":"Product rejected"}), 200

# Public products endpoint (kept for compatibility)
@app.route("/api/public/products", methods=['GET'])
def public_products():
    try:
        logger.info("Public products request")
        docs = db.collection('products').where('status', '==', 'available').order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        products = []
        for doc in docs:
            p = doc.to_dict()
            p['id'] = doc.id
            if 'created_at' in p and p['created_at']:
                try: p['created_at'] = p['created_at'].timestamp()
                except: pass
            products.append(p)
        if not products:
            return jsonify({"msg":"No available products","data": []}), 200
        return jsonify(products), 200
    except Exception as e:
        logger.exception("Failed to fetch public products")
        return jsonify({"msg":"Failed to fetch public products","error":str(e)}), 500

# analytics
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

# Cleanup
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