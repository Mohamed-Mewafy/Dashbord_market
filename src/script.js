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
    // --- Element Selectors ---
    const authContainer = document.getElementById('authContainer');
    const dashboardContainer = document.getElementById('dashboardContainer');
    const loginForm = document.getElementById('loginForm');
    const loginError = document.getElementById('loginError');
    const logoutBtn = document.getElementById('logoutBtn');
    const userEmailSpan = document.getElementById('userEmail');
    const searchInput = document.getElementById('searchInput');
    const productGrid = document.getElementById('productGrid');
    const productForm = document.getElementById('productForm');
    const productIdField = document.getElementById('productId');
    const productNameField = document.getElementById('productName');
    const productPriceField = document.getElementById('productPrice');
    const productQuantityField = document.getElementById('productQuantity');
    const productImageField = document.getElementById('productImage');
    const productDescriptionField = document.getElementById('productDescription');
    const modal = document.getElementById('productModal');
    const addProductBtn = document.getElementById('addProductBtn');
    const closeModalBtn = document.querySelector('.close-btn');
    const formTitle = document.getElementById('formTitle');
    const submitButton = document.getElementById('submitButton');
    const totalProducts = document.getElementById('totalProducts');
    const siteVisits = document.getElementById('siteVisits');
    const salesChartCtx = document.getElementById('salesChart').getContext('2d');
    const cleanupBtn = document.getElementById('cleanupBtn'); 

    // --- Global State ---
    const API_URL = '/api/products';
    const ANALYTICS_URL = '/api/analytics';
    const CLEANUP_URL = '/api/cleanup-old-products'; 
    let salesChart;
    let allProducts = [];
    let currentUser = null;

    // --- Authentication Logic ---
    auth.onAuthStateChanged(user => {
        if (user) {
            currentUser = user;
            authContainer.style.display = 'none';
            dashboardContainer.style.display = 'block';
            userEmailSpan.textContent = user.email;
            loadDashboardData();
        } else {
            currentUser = null;
            authContainer.style.display = 'block';
            dashboardContainer.style.display = 'none';
            allProducts = [];
            renderProducts(allProducts);
        }
    });

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await auth.signInWithEmailAndPassword(document.getElementById('email').value, document.getElementById('password').value);
            loginError.textContent = '';
        } catch (error) {
            loginError.textContent = "البريد الإلكتروني أو كلمة المرور غير صحيحة.";
        }
    });

    logoutBtn.addEventListener('click', () => auth.signOut());

    // --- API Helper ---
    const fetchWithAuth = async (url, options = {}, useAuth = true) => {
        const headers = { ...options.headers };
        if (useAuth) {
            if (!currentUser) throw new Error('User not authenticated');
            const idToken = await currentUser.getIdToken();
            headers['Authorization'] = `Bearer ${idToken}`;
        }
        if (options.body) headers['Content-Type'] = 'application/json';
        const response = await fetch(url, { ...options, headers });
        if (!response.ok) {
            const errorText = await response.text(); // Read body ONCE as text
            let errorMsg = 'An unknown error occurred';
            try {
                const errorData = JSON.parse(errorText);
                errorMsg = errorData.msg || errorData.error || errorMsg;
            } catch (jsonError) {
                errorMsg = `Request failed with status ${response.status}: ${errorText.substring(0, 100)}`; // Use raw text if not JSON
            }
            console.error(`API Error on ${options.method || 'GET'} ${url}:`, errorMsg, response.status);
            throw new Error(errorMsg);
        }
        return response.status === 204 ? null : response.json();
    };
    
    const formatDate = (timestamp) => {
        if (!timestamp) return 'تاريخ غير معروف';
        const date = new Date(timestamp * 1000);
        return date.toLocaleDateString('ar-EG', { day: '2-digit', month: '2-digit', year: 'numeric' });
    };

    // --- Data Loading & Rendering ---
    const loadDashboardData = async () => {
        try {
            const [products, analytics] = await Promise.all([fetchWithAuth(API_URL), fetchWithAuth(ANALYTICS_URL)]);
            allProducts = products;
            const hasOwnerlessProducts = allProducts.some(p => !p.creator_uid);
            if (cleanupBtn) cleanupBtn.style.display = hasOwnerlessProducts ? 'inline-flex' : 'none';
            
            renderProducts(allProducts);
            updateAnalytics(analytics);
        } catch (error) {
            console.error('Error loading dashboard data:', error);
            productGrid.innerHTML = `<p>خطأ في تحميل البيانات: ${error.message}</p>`;
        }
    };

    const updateAnalytics = (analytics) => {
        totalProducts.textContent = analytics.total_products;
        siteVisits.textContent = analytics.site_visits;
        renderChart(analytics.sales_data);
    };

    const renderChart = (salesData) => {
        if (salesChart) salesChart.destroy();
        salesChart = new Chart(salesChartCtx, { type: 'line', data: { labels: salesData.labels, datasets: [{ label: 'المبيعات', data: salesData.values, backgroundColor: 'rgba(79, 70, 229, 0.1)', borderColor: '#4F46E5', borderWidth: 2, tension: 0.4, fill: true }] }, options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } }, plugins: { legend: { display: false } } } });
    };

    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        renderProducts(allProducts.filter(p => p.name.toLowerCase().includes(searchTerm)));
    });

    const renderProducts = (products) => {
        productGrid.innerHTML = '';
        if (!products || products.length === 0) {
            productGrid.innerHTML = '<p>لا توجد منتجات لعرضها. ابدأ بإضافة منتج جديد.</p>';
            return;
        }
        products.forEach(product => {
            const card = document.createElement('div');
            card.className = 'product-card';
            const isOwner = currentUser && product.creator_uid === currentUser.uid;
            const quantity = product.quantity !== undefined ? product.quantity : 'N/A';
            const status = quantity > 0 ? (product.status || 'available') : 'unavailable';
            const statusText = status === 'available' ? 'متاح' : 'غير متاح';
            const statusClass = status === 'available' ? 'available' : 'unavailable';
            const toggleStatusText = status === 'available' ? 'اجعله غير متاح' : 'اجعله متاح';
            const createdDate = formatDate(product.created_at);

            let quantityAlertHTML = '';
            if (quantity > 0 && quantity <= 3) {
                quantityAlertHTML = `<div class="quantity-alert">متبقي ${quantity} فقط!</div>`;
            }

            // Make image and title clickable
            card.innerHTML = `
                <a href="/product?id=${product.id}" class="product-link">
                    <div class="status-badge ${statusClass}">${statusText}</div>
                    <img src="${product.image_url}" alt="${product.name}" onerror="this.src='https://via.placeholder.com/300x200?text=No+Image'">
                </a>
                <div class="product-info">
                    <h3><a href="/product?id=${product.id}" class="product-link">${product.name}</a></h3>
                    <p class="price">${product.price} ريال</p>
                    ${quantityAlertHTML}
                    <p class="description">${product.description || ''}</p>
                </div>
                <div class="product-meta">
                    <span>الكمية: <strong>${quantity}</strong></span><br>
                    <span>أضيف بواسطة: ${product.added_by || 'غير معروف'}</span><br>
                    <span>تاريخ الإضافة: <strong>${createdDate}</strong></span>
                </div>
                ${isOwner ? `
                <div class="product-actions">
                    <button class="btn btn-status">${toggleStatusText}</button>
                    <button class="btn btn-edit">تعديل</button>
                    <button class="btn btn-delete">حذف</button>
                </div>
                ` : ''}
            `;

            if (isOwner) {
                card.querySelector('.btn-edit').addEventListener('click', () => openModalForEdit(product));
                card.querySelector('.btn-delete').addEventListener('click', () => deleteProduct(product.id));
                const statusBtn = card.querySelector('.btn-status');
                if(statusBtn) statusBtn.addEventListener('click', () => toggleProductStatus(product));
            }
            productGrid.appendChild(card);
        });
    };

    // --- Modal & Form Logic ---
    const openModalForNew = () => {
        productForm.reset();
        productIdField.value = '';
        formTitle.textContent = 'إضافة منتج جديد';
        submitButton.textContent = 'إضافة';
        modal.style.display = 'flex';
    };

    const openModalForEdit = (product) => {
        productIdField.value = product.id;
        productNameField.value = product.name;
        productPriceField.value = product.price;
        productQuantityField.value = product.quantity !== undefined ? product.quantity : '';
        productImageField.value = product.image_url;
        productDescriptionField.value = product.description || '';
        formTitle.textContent = 'تعديل المنتج';
        submitButton.textContent = 'تحديث';
        modal.style.display = 'flex';
    };

    const closeModal = () => modal.style.display = 'none';

    productForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const productData = {
            name: productNameField.value,
            price: parseFloat(productPriceField.value),
            quantity: parseInt(productQuantityField.value, 10),
            image_url: productImageField.value,
            description: productDescriptionField.value
        };
        const id = productIdField.value;
        try {
            const url = id ? `${API_URL}/${id}` : API_URL;
            const method = id ? 'PUT' : 'POST';
            await fetchWithAuth(url, { method, body: JSON.stringify(productData) });
            closeModal();
            loadDashboardData();
        } catch (error) {
            alert(`فشل حفظ المنتج: ${error.message}`);
        }
    });

    // --- Product Actions ---
    const deleteProduct = async (id) => {
        if (!confirm('هل أنت متأكد من رغبتك في حذف هذا المنتج؟')) return;
        try {
            await fetchWithAuth(`${API_URL}/${id}`, { method: 'DELETE' });
            loadDashboardData();
        } catch (error) {
            alert(`فشل حذف المنتج: ${error.message}`);
        }
    };

    const toggleProductStatus = async (product) => {
        const newStatus = product.status === 'available' ? 'unavailable' : 'available';
        if(newStatus === 'available' && product.quantity === 0) {
            alert('لا يمكن جعل المنتج متاحًا والكمية صفر. يرجى تعديل الكمية أولاً.');
            return;
        }
        const confirmMsg = `هل تريد تغيير حالة المنتج إلى \"${newStatus === 'available' ? 'متاح' : 'غير متاح'}\"?`;
        if (!confirm(confirmMsg)) return;
        try {
            await fetchWithAuth(`${API_URL}/${product.id}/status`, { method: 'PUT', body: JSON.stringify({ status: newStatus }) });
            loadDashboardData();
        } catch (error) {
            alert(`فشل تحديث الحالة: ${error.message}`);
        }
    };
    
    // --- Cleanup Logic ---
    if (cleanupBtn) {
        cleanupBtn.addEventListener('click', async () => {
            if (!confirm('سيؤدي هذا الإجراء إلى حذف جميع المنتجات القديمة التي ليس لها مالك مسجل. هل أنت متأكد أنك تريد المتابعة؟ لا يمكن التراجع عن هذا الإجراء.')) return;
            try {
                const result = await fetchWithAuth(CLEANUP_URL, { method: 'POST' }, false); 
                alert(result.msg);
                loadDashboardData(); 
            } catch (error) {
                alert(`فشل التنظيف: ${error.message}`);
            }
        });
    }

    // --- Event Listeners ---
    addProductBtn.addEventListener('click', openModalForNew);
    closeModalBtn.addEventListener('click', closeModal);
    window.addEventListener('click', (event) => { if (event.target === modal) closeModal(); });
});
