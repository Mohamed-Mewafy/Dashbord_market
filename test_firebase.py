# test_firebase.py
import os, json, traceback
from firebase_admin import credentials, initialize_app, firestore

try:
    sa = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not sa:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON not set")

    sa_obj = json.loads(sa)   # سيتسبب بخطأ لو JSON غير صالح
    cred = credentials.Certificate(sa_obj)
    initialize_app(cred)
    db = firestore.client()
    col = list(db.collection("products").limit(1).stream())
    print("Firebase OK — can reach Firestore. Found items:", len(col))
except Exception:
    print("ERROR during firebase test:")
    traceback.print_exc()
