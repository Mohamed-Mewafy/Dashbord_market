import os
import json
import random
import firebase_admin
import google.generativeai as genai
from firebase_admin import credentials, firestore, auth
from flask import Flask, send_file, jsonify, request
from dotenv import load_dotenv

# Load environment variables from .env file (for local development)
load_dotenv()

# --------- Firebase initialization (load service account from env) ---------
FIREBASE_SA_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
if FIREBASE_SA_JSON:
    try:
        sa_info = json.loads(FIREBASE_SA_JSON)
        cred = credentials.Certificate(sa_info)
    except Exception as e:
        raise RuntimeError(f"Failed to parse FIREBASE_SERVICE_ACCOUNT_JSON: {e}")
else:
    # fallback to local path only for dev; do NOT commit firebase-service-account.json to GitHub
    cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "firebase-service-account.json")
    if not os.path.exists(cred_path):
        raise RuntimeError(
            "Firebase service account not found. Set FIREBASE_SERVICE_ACCOUNT_JSON or provide firebase-service-account.json"
        )
    cred = credentials.Certificate(cred_path)

# initialize app only once (safe if running in dev with auto-reload)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --------- Gemini / Google generative AI config ---------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables. Please set it in Railway variables or .env file.")

# Configure the google generative AI client
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# --------- Flask app ---------
app = Flask(__name__, static_folder='src', static_url_path='/')
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24))

# simple auth check for /api routes using Firebase ID tokens
@app.before_request
def verify_token():
    # Only protect /api endpoints (except OPTIONS preflight and explicitly allowed endpoints)
    if request.path.startswith('/api') and request.method != 'OPTIONS':
        # NOTE: /api/cleanup-old-products is left unprotected here for convenience in your dev flow.
        # In production you MUST protect or remove it.
        if request.path == '/api/cleanup-old-products':
            return

        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"msg": "Missing or invalid authorization token"}), 401
        try:
            id_token = auth_header.split('Bearer ')[1]
            decoded_token = auth.verify_id_token(id_token)
            # Attach user info to request for handlers
            request.user = decoded_token
        except Exception as e:
            return jsonify({"msg": f"Invalid token: {e}"}), 401


# --------- Routes ---------
@app.route('/')
def index():
    return app.send_static_file('index.html')


@app.route('/product')
def product_page():
    return app.send_static_file('product.html')


@app.route('/api/products', methods=['GET', 'POST'])
def handle_products():
    products_ref = db.collection('products')
    if request.method == 'POST':
        data = request.get_json() or {}
        quantity = int(data.get('quantity', 0))
        data['quantity'] = quantity
        data['status'] = 'available' if quantity > 0 else 'unavailable'
        # require authenticated user
        creator = getattr(request, 'user', None)
        if not creator:
            return jsonify({"msg": "Unauthorized"}), 401
        data['creator_uid'] = creator.get('uid')
        data['added_by'] = creator.get('email')
        data['created_at'] = firestore.SERVER_TIMESTAMP
        _, ref = products_ref.add(data)
        new_product = ref.get().to_dict()
        new_product['id'] = ref.id
        return jsonify(new_product), 201
    else:
        creator = getattr(request, 'user', None)
        if not creator:
            return jsonify({"msg": "Unauthorized"}), 401
        docs = products_ref.where('creator_uid', '==', creator.get('uid')).order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        products = []
        for doc in docs:
            p = doc.to_dict()
            p['id'] = doc.id
            if 'created_at' in p and p['created_at']:
                try:
                    p['created_at'] = p['created_at'].timestamp()
                except Exception:
                    # If timestamp conversion fails, leave raw value
                    pass
            products.append(p)
        return jsonify(products)


@app.route('/api/products/<string:product_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_product(product_id):
    product_ref = db.collection('products').document(product_id)
    doc = product_ref.get()
    if not doc.exists:
        return jsonify({"msg": "Product not found"}), 404

    product_data = doc.to_dict()
    user = getattr(request, 'user', None)
    if not user:
        return jsonify({"msg": "Unauthorized"}), 401

    is_owner = product_data.get('creator_uid') == user.get('uid')

    if request.method == 'GET':
        product_data['id'] = doc.id
        if 'created_at' in product_data and product_data['created_at']:
            try:
                product_data['created_at'] = product_data['created_at'].timestamp()
            except Exception:
                pass
        return jsonify(product_data)

    if not is_owner:
        return jsonify({"msg": "Forbidden: You are not the owner of this product."}), 403

    if request.method == 'PUT':
        update_data = request.get_json() or {}
        if 'quantity' in update_data:
            quantity = int(update_data['quantity'])
            update_data['quantity'] = quantity
            update_data['status'] = 'available' if quantity > 0 else 'unavailable'
        product_ref.update(update_data)
        updated_doc = product_ref.get().to_dict()
        updated_doc['id'] = product_ref.id
        return jsonify(updated_doc)

    if request.method == 'DELETE':
        product_ref.delete()
        return '', 204


@app.route('/api/products/<string:product_id>/status', methods=['PUT'])
def handle_product_status(product_id):
    product_ref = db.collection('products').document(product_id)
    doc = product_ref.get()
    if not doc.exists:
        return jsonify({"msg": "Product not found"}), 404
    product_data = doc.to_dict()
    user = getattr(request, 'user', None)
    if not user:
        return jsonify({"msg": "Unauthorized"}), 401
    if product_data.get('creator_uid') != user.get('uid'):
        return jsonify({"msg": "Forbidden"}), 403
    req_data = request.get_json() or {}
    if req_data.get('status') == 'available' and product_data.get('quantity', 0) == 0:
        return jsonify({"msg": "Cannot make product available with zero quantity"}), 400
    product_ref.update({'status': req_data['status']})
    return jsonify({"status": "success"})


@app.route('/api/generate-description', methods=['POST'])
def generate_ai_description():
    product_name = (request.json or {}).get('product_name')
    if not product_name:
        return jsonify({"msg": "Product name is required"}), 400
    try:
        prompt = f'''Create a compelling, professional, and enticing marketing description for a product named "{product_name}".

        The description should:
        - Be written in Arabic.
        - Be 2-3 paragraphs long.
        - Highlight the key benefits and unique selling points.
        - Use a tone that is both exciting and trustworthy.
        - End with a strong call to action.

        Generate the description now.'''

        response = model.generate_content(prompt)
        # Depending on the version of google.generativeai client you use, response object shape may differ.
        # The above works if the client returns an object with .text attribute. If not, inspect response.
        text = getattr(response, 'text', None) or str(response)
        return jsonify({"description": text})
    except Exception as e:
        return jsonify({"msg": f"Failed to generate description: {e}"}), 500


@app.route('/api/cleanup-old-products', methods=['POST'])
def cleanup_old_products():
    # TEMPORARY: This endpoint is not protected — secure or remove it in production!
    try:
        docs = db.collection('products').where('creator_uid', '==', None).stream()
        deleted_count = 0
        for doc in docs:
            doc.reference.delete()
            deleted_count += 1
        return jsonify({"msg": f"Cleanup successful. Deleted {deleted_count} ownerless products."})
    except Exception as e:
        return jsonify({"msg": str(e)}), 500


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


if __name__ == '__main__':
    # Run only for local dev. In production gunicorn will serve the app.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)
