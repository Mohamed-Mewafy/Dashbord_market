const firebaseConfig = {
    apiKey: "AIzaSyAqWe8zke0UckY3c5FKpP3vWo1XCmdyuPY",
    authDomain: "egflix-3ed5e.firebaseapp.com",
    projectId: "egflix-3ed5e",
    storageBucket: "egflix-3ed5e.appspot.com",
    messagingSenderId: "865194173153",
    appId: "1:865194173153:web:fb97eadf68f5e7dd778da0"
};

firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();

document.addEventListener('DOMContentLoaded', () => {
    const userEmailSpan = document.getElementById('userEmail');
    const logoutBtn = document.getElementById('logoutBtn');
    const productContent = document.getElementById('productContent');
    
    let currentUser = null;

    auth.onAuthStateChanged(user => {
        if (user) {
            currentUser = user;
            userEmailSpan.textContent = user.email;
            loadProductDetails();
        } else {
            // If not logged in, redirect to the main page
            window.location.href = '/';
        }
    });

    logoutBtn.addEventListener('click', () => {
        auth.signOut().then(() => {
            window.location.href = '/';
        });
    });

    const fetchWithAuth = async (url, options = {}) => {
        if (!currentUser) throw new Error('User not authenticated');
        const idToken = await currentUser.getIdToken();
        const headers = { ...options.headers, 'Authorization': `Bearer ${idToken}` };
        if (options.body) {
            headers['Content-Type'] = 'application/json';
        }
        const response = await fetch(url, { ...options, headers });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ msg: 'An unknown error occurred' }));
            throw new Error(errorData.msg || `Request failed with status ${response.status}`);
        }
        return response.json();
    };

    const getProductIdFromUrl = () => {
        const params = new URLSearchParams(window.location.search);
        return params.get('id');
    };

    const loadProductDetails = async () => {
        const productId = getProductIdFromUrl();
        if (!productId) {
            productContent.innerHTML = '<p>لم يتم العثور على معرّف المنتج.</p>';
            return;
        }

        try {
            const product = await fetchWithAuth(`/api/products/${productId}`);
            renderProduct(product);
        } catch (error) {
            console.error('Error loading product:', error);
            productContent.innerHTML = `<p>خطأ في تحميل المنتج: ${error.message}</p>`;
        }
    };

    const renderProduct = (product) => {
        const statusText = product.status === 'available' ? 'متوفر' : 'غير متوفر';
        const statusClass = product.status === 'available' ? 'available' : 'unavailable';

        productContent.innerHTML = `
            <div class="product-layout">
                <div class="product-image-gallery">
                    <img src="${product.image_url}" alt="${product.name}" onerror="this.src='https://via.placeholder.com/500x500?text=No+Image'">
                </div>
                <div class="product-details">
                    <h1>${product.name}</h1>
                    <p class="price">${product.price} ريال</p>
                    <p class="status ${statusClass}">${statusText} (الكمية: ${product.quantity})</p>
                    <p class="description">${product.description || 'لا يوجد وصف أساسي للمنتج.'}</p>
                    
                    <div class="ai-section">
                        <div class="ai-header">
                            <h2><i class="fas fa-robot"></i> رؤية تسويقية بالذكاء الاصطناعي</h2>
                            <button id="generateAiDescriptionBtn" class="btn"><i class="fas fa-magic"></i> إنشاء وصف</button>
                        </div>
                        <div id="aiDescription" class="loading-spinner" style="display: none;">
                           <i class="fas fa-spinner fa-spin"></i>
                           <p>... أفكر في كلمات تسويقية مذهلة</p>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.getElementById('generateAiDescriptionBtn').addEventListener('click', () => generateAiDescription(product.name));
    };

    const generateAiDescription = async (productName) => {
        const aiDescriptionContainer = document.getElementById('aiDescription');
        const generateBtn = document.getElementById('generateAiDescriptionBtn');
        
        aiDescriptionContainer.style.display = 'flex';
        aiDescriptionContainer.innerHTML = `
            <div class="loading-spinner" style="padding: 20px;">
                <i class="fas fa-spinner fa-spin"></i>
                <p>... أفكر في كلمات تسويقية مذهلة</p>
            </div>`;
        generateBtn.disabled = true;

        try {
            const result = await fetchWithAuth('/api/generate-description', {
                method: 'POST',
                body: JSON.stringify({ product_name: productName })
            });
            aiDescriptionContainer.style.display = 'block'; // Change to block to remove flex properties
            aiDescriptionContainer.innerHTML = result.description;
        } catch (error) {
            console.error('Error generating AI description:', error);
            aiDescriptionContainer.innerHTML = `<p style="color: red;">فشل في توليد الوصف: ${error.message}</p>`;
        } finally {
            generateBtn.disabled = false;
        }
    };
});
