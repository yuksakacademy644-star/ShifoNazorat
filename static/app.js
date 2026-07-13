// Initialize Telegram WebApp SDK (safe fallback if SDK not loaded)
var tg;
try {
    tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
} catch(e) {
    tg = null;
}

// Fallback mock for non-Telegram environments
if (!tg) {
    tg = {
        ready: function() {},
        expand: function() {},
        initDataUnsafe: {},
        close: function() {},
        showAlert: function(msg) { alert(msg); },
        MainButton: { setText: function(){}, show: function(){}, hide: function(){}, onClick: function(){} }
    };
}

// App State
let currentUser = {
    chat_id: 0,
    name: "Mehmon",
    role: "guest"
};
let selectedRating = 0;
let patientId = null;
let currentFilter = "all";
let currentPatientsList = [];

// Rating descriptions (Uzbek)
const ratingDescriptions = {
    1: "1/5 - Juda yomon 😞",
    2: "2/5 - Yomon 🙁",
    3: "3/5 - O'rta 😐",
    4: "4/5 - Yaxshi 🙂",
    5: "5/5 - A'lo! 😄"
};

// ================= INITIALIZATION =================
function initApp() {
    try {
        // Notify Telegram we are ready
        tg.ready();
        tg.expand();

        // Define string extensions first
        if (!String.prototype.stripOrEmpty) {
            String.prototype.stripOrEmpty = function() { return this.trim(); };
        }

        // Extract user info from URL query parameters or Telegram WebApp user object
        const urlParams = new URLSearchParams(window.location.search);
        const tgUser = tg.initDataUnsafe ? tg.initDataUnsafe.user : null;
        const queryChatId = parseInt(urlParams.get("chat_id")) || 0;

        if (queryChatId) {
            currentUser.chat_id = queryChatId;
            currentUser.name = tgUser
                ? ((tgUser.first_name || '') + ' ' + (tgUser.last_name || '')).trim()
                : (urlParams.get("name") || "Mehmon");
        } else if (tgUser) {
            currentUser.chat_id = tgUser.id;
            currentUser.name = ((tgUser.first_name || '') + ' ' + (tgUser.last_name || '')).trim();
        } else {
            currentUser.chat_id = 0;
            currentUser.name = "Mehmon";
        }

        // Authenticate and load appropriate view
        checkUserRole();
        setupEventListeners();

    } catch(initErr) {
        console.error("App init error:", initErr);
        var loaderStatus = document.getElementById("loader-status");
        if (loaderStatus) loaderStatus.innerText = "❌ Xatolik: " + initErr.message;
        var loaderRetry = document.getElementById("loader-retry-btn");
        if (loaderRetry) loaderRetry.style.display = "inline-block";
    }
}

// Run immediately if DOM is ready, otherwise wait for DOMContentLoaded
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
} else {
    initApp();
}

// ====== CACHE HELPERS ======
const CACHE_KEY_PREFIX = "shifo_user_";
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 daqiqa

function getCachedUser(chatId) {
    try {
        const raw = localStorage.getItem(CACHE_KEY_PREFIX + chatId);
        if (!raw) return null;
        const { data, ts } = JSON.parse(raw);
        if (Date.now() - ts > CACHE_TTL_MS) { localStorage.removeItem(CACHE_KEY_PREFIX + chatId); return null; }
        return data;
    } catch(e) { console.warn('Cache read error:', e); return null; }
}

function setCachedUser(chatId, data) {
    try { localStorage.setItem(CACHE_KEY_PREFIX + chatId, JSON.stringify({ data, ts: Date.now() })); } catch(e) { console.warn('Cache write error:', e); }
}

function clearCachedUser(chatId) {
    try { localStorage.removeItem(CACHE_KEY_PREFIX + chatId); } catch(e) { console.warn('Cache clear error:', e); }
}

// ====== RENDER VIEWS from data ======
function renderUserView(data) {
    const urlParams = new URLSearchParams(window.location.search);
    currentUser.role = data.role;
    currentUser.name = data.name;

    document.getElementById("loader").classList.add("hidden");

    if (data.role === "admin") {
        document.getElementById("admin-name").innerText = data.name;
        document.getElementById("admin-view").classList.remove("hidden");
        const tabParam = urlParams.get("tab") || "stats";
        switchTab(tabParam);
    } else if (data.role === "patient") {
        patientId = data.patient.id;
        document.getElementById("patient-welcome").innerText = `Salom, ${data.patient.bemor_ismi}!`;
        document.getElementById("patient-doctor").innerText = data.patient.shifokor_ismi || "Noma'lum";
        document.getElementById("patient-visit-date").innerText = data.patient.oxirgi_tashrif_sanasi || "Noma'lum";

        document.getElementById("prof-name").innerText = data.patient.bemor_ismi;
        document.getElementById("prof-phone").innerText = data.patient.bemor_telefoni;

        const statusClass = data.patient.status === "Faol" ? "active" : "norozi";
        document.getElementById("prof-status").innerHTML = `<span class="status-badge ${statusClass}">${data.patient.status}</span>`;

        document.getElementById("prof-visits").innerText = data.patient.tashriflar_soni || 1;
        document.getElementById("prof-last-visit").innerText = data.patient.oxirgi_tashrif_sanasi || "Yo'q";
        document.getElementById("prof-doctor").innerText = data.patient.shifokor_ismi || "Yo'q";
        document.getElementById("prof-last-rating").innerText = data.patient.oxirgi_baho ? `${data.patient.oxirgi_baho} / 5` : "Baholanmagan";

        if (data.patient.oxirgi_baho) {
            showPatientThankYou(data.patient.oxirgi_baho);
        } else {
            document.getElementById("patient-rating-box").classList.remove("hidden");
        }

        initPatientPortalData();
        document.getElementById("patient-view").classList.remove("hidden");
    } else if (data.role === "doctor") {
        document.getElementById("doctor-title-name").innerText = data.name;
        document.getElementById("doctor-chat-id-badge").innerText = `ID: ${currentUser.chat_id}`;
        document.getElementById("doctor-view").classList.remove("hidden");
        initDoctorPortalData();
    } else {
        document.getElementById("guest-view").classList.remove("hidden");
    }
}

// ====== AUTHENTICATE (Cache-First) ======
async function checkUserRole() {
    const loaderStatus = document.getElementById("loader-status");
    const loaderRetry  = document.getElementById("loader-retry-btn");
    const bar = document.getElementById("loader-bar");

    function setLoaderStatus(msg) { if (loaderStatus) loaderStatus.innerText = msg; }

    // --- 1. Try cache first: show UI instantly ---
    const cached = getCachedUser(currentUser.chat_id);
    if (cached) {
        setLoaderStatus("Tezkor kirish...");
        if (bar) { bar.style.transition = "width 0.25s ease-out"; bar.style.width = "100%"; }
        // Small delay so the bar animation is visible
        await new Promise(r => setTimeout(r, 200));
        renderUserView(cached);

        // --- 2. Silently refresh in background ---
        setTimeout(async () => {
            try {
                const res = await fetch(
                    `/api/check-user?chat_id=${currentUser.chat_id}&name=${encodeURIComponent(currentUser.name)}`,
                    { headers: { "Connection": "keep-alive" } }
                );
                if (res.ok) {
                    const fresh = await res.json();
                    setCachedUser(currentUser.chat_id, fresh);
                    // If role changed (e.g. patient registered), reload silently
                    if (fresh.role !== cached.role) location.reload();
                }
            } catch { /* silent */ }
        }, 500);
        return;
    }

    // --- 3. No cache: connect to server with status messages ---
    setLoaderStatus("Serverga ulanmoqda...");
    const t2  = setTimeout(() => setLoaderStatus("Ulanish o'rnatilmoqda... ⏳"), 2000);
    const t5  = setTimeout(() => setLoaderStatus("Deyarli tayyor... 🔗"), 5000);
    const t10 = setTimeout(() => setLoaderStatus("Internet ulanishingiz sekin bo'lishi mumkin..."), 10000);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 20000);

    // Animate bar to 80% while waiting
    if (bar) { bar.style.transition = "width 12s ease-out"; bar.style.width = "80%"; }

    try {
        const res = await fetch(
            `/api/check-user?chat_id=${currentUser.chat_id}&name=${encodeURIComponent(currentUser.name)}`,
            { signal: controller.signal, headers: { "Connection": "keep-alive" } }
        );
        clearTimeout(t2); clearTimeout(t5); clearTimeout(t10); clearTimeout(timeoutId);
        if (!res.ok) throw new Error(`Server xatosi: ${res.status}`);

        setLoaderStatus("Yuklanmoqda...");
        if (bar) { bar.style.transition = "width 0.4s ease-out"; bar.style.width = "100%"; }

        const data = await res.json();
        setCachedUser(currentUser.chat_id, data); // Save to cache
        renderUserView(data);

    } catch (err) {
        clearTimeout(t2); clearTimeout(t5); clearTimeout(t10); clearTimeout(timeoutId);
        console.error("Auth error:", err);

        if (bar) { bar.style.transition = "none"; bar.style.background = "#ef4444"; bar.style.width = "100%"; }

        if (err.name === "AbortError") {
            setLoaderStatus("❌ Server 20 soniyada javob bermadi. Qayta urinib ko'ring.");
        } else {
            setLoaderStatus("❌ Ulanishda xatolik yuz berdi.");
        }
        if (loaderRetry) loaderRetry.style.display = "inline-block";
        showToast("Tizimga ulanishda xatolik!", "error");
    }
}

// Setup Event Listeners
function setupEventListeners() {
    // 1. Navigation Tabs
    const navItems = document.querySelectorAll(".bottom-nav .nav-item");
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const tabName = item.getAttribute("data-tab");
            switchTab(tabName);
        });
    });

    // 2. Set Today Date button in Form
    document.getElementById("btn-set-today").addEventListener("click", () => {
        const today = new Date().toISOString().split('T')[0];
        document.getElementById("oxirgi_tashrif_sanasi").value = today;
    });

    // 3. Add Patient Form Submission
    document.getElementById("add-patient-form").addEventListener("submit", handleAddPatient);

    // 4. Live Search Input
    document.getElementById("search-input").addEventListener("input", (e) => {
        loadPatientsList(e.target.value);
    });

    // 5. Settings toggles
    document.getElementById("setting-auto-messages").addEventListener("change", handleSettingsChange);
    document.getElementById("setting-test-mode").addEventListener("change", handleSettingsChange);

    // 6. Interactive Star rating buttons
    const starBtns = document.querySelectorAll(".stars-rating .star-btn");
    starBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            selectedRating = parseInt(btn.getAttribute("data-value"));
            highlightStars(selectedRating);
            
            const submitBtn = document.getElementById("btn-submit-rating");
            submitBtn.classList.remove("disabled");
            submitBtn.disabled = false;
            
            document.getElementById("rating-desc").innerText = ratingDescriptions[selectedRating];
        });
    });

    // 7. Patient Submit Rating button
    document.getElementById("btn-submit-rating").addEventListener("click", submitPatientRating);

    // 8. Patient Profile Tabs Switching
    const patientTabBtns = document.querySelectorAll(".patient-tab-btn");
    patientTabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const tabName = btn.getAttribute("data-ptab");
            
            patientTabBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            document.querySelectorAll(".patient-tab-content").forEach(tc => {
                if (tc.id === `ptab-${tabName}`) {
                    tc.classList.remove("hidden");
                } else {
                    tc.classList.add("hidden");
                }
            });

            // Load data dynamically based on the active tab
            if (tabName === "qa") {
                loadPatientQA();
            } else if (tabName === "family") {
                loadPatientFamily();
            }
        });
    });

    // 9. Filter Pills
    const filterPills = document.querySelectorAll(".filter-pill");
    filterPills.forEach(pill => {
        pill.addEventListener("click", () => {
            filterPills.forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            currentFilter = pill.getAttribute("data-filter");
            const serverFilters = ["today", "3days", "callback"];
            if (serverFilters.includes(currentFilter)) {
                loadPatientsList("", currentFilter);
            } else {
                loadPatientsList(document.getElementById("search-input").value);
            }
        });
    });

    // 10. Preset checkup date buttons (add form + modal)
    document.querySelectorAll(".preset-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const months = parseInt(btn.getAttribute("data-months"));
            const targetId = btn.getAttribute("data-target") || "rejalashtirilgan_tekshiruv";
            const d = new Date();
            d.setMonth(d.getMonth() + months);
            document.getElementById(targetId).value = d.toISOString().split('T')[0];
            document.querySelectorAll(`[data-target='${targetId}'], .checkup-presets:not([data-target]) .preset-btn`)
                .forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
        });
    });

    // 11. Edit patient form submission
    document.getElementById("edit-patient-form").addEventListener("submit", saveEditedPatient);

    // 12. Setup listeners for new Booking, KPI, EMR, and Lab automation features
    setupClinicAutomationEventListeners();
}

// ================= TAB SWITCHING LOGIC =================
function switchTab(tabName) {
    // Update active class on nav buttons
    const navItems = document.querySelectorAll(".bottom-nav .nav-item");
    navItems.forEach(item => {
        if (item.getAttribute("data-tab") === tabName) {
            item.classList.add("active");
        } else {
            item.classList.remove("active");
        }
    });

    // Hide all tabs and show selected
    const tabs = document.querySelectorAll(".tab-content");
    tabs.forEach(tab => {
        if (tab.id === `tab-${tabName}`) {
            tab.classList.remove("hidden");
        } else {
            tab.classList.add("hidden");
        }
    });

    // Load data based on tab
    if (tabName === "stats") {
        loadStatistics();
    } else if (tabName === "list") {
        loadPatientsList();
    } else if (tabName === "bookings") {
        loadBookingsList();
    } else if (tabName === "qa") {
        loadAdminQA();
    } else if (tabName === "settings") {
        loadSettings();
    } else if (tabName === "add") {
        // Set date to today by default
        const today = new Date().toISOString().split('T')[0];
        document.getElementById("oxirgi_tashrif_sanasi").value = today;
    }
}

// ================= ADMIN: STATISTICS =================
async function loadStatistics() {
    try {
        const res = await fetch("/api/stats");
        const data = await res.json();
        
        document.getElementById("stat-total").innerText = data.total_patients;
        document.getElementById("stat-active").innerText = data.active_patients;
        document.getElementById("stat-norozi").innerText = data.norozi_patients;
        document.getElementById("stat-rating").innerText = data.avg_rating.toFixed(1);
        document.getElementById("stat-repeat").innerText = data.repeat_count || 0;
        document.getElementById("stat-rated-count").innerText = data.rated_count || 0;

        // Progress bar for average rating (e.g. 4.5/5 -> 90%)
        const percent = (data.avg_rating / 5) * 100;
        document.getElementById("progress-percent").innerText = `${percent.toFixed(0)}%`;
        document.getElementById("progress-bar-fill").style.width = `${percent}%`;

        // Render Star breakdown
        for (let star = 1; star <= 5; star++) {
            const count = data.star_counts[star] || 0;
            const pct = data.rated_count > 0 ? (count / data.rated_count) * 100 : 0;
            document.getElementById(`star-${star}-count`).innerText = count;
            document.getElementById(`star-${star}-fill`).style.width = `${pct}%`;
        }

        // Fetch and render Doctor KPIs
        const kpiRes = await fetch("/api/analytics/kpis");
        const kpis = await kpiRes.json();
        const kpiTbody = document.getElementById("kpi-tbody");
        kpiTbody.innerHTML = "";
        kpis.forEach(k => {
            kpiTbody.innerHTML += `
                <tr>
                    <td><strong>${k.doctor_name}</strong></td>
                    <td>${k.total_patients}</td>
                    <td>${k.repeat_patients}</td>
                    <td>${k.repeat_rate}%</td>
                    <td>${k.avg_rating > 0 ? k.avg_rating.toFixed(1) + ' ⭐' : 'baholanmagan'}</td>
                    <td>${k.revenue.toLocaleString()} UZS</td>
                </tr>
            `;
        });

        // Fetch and render Financial ROI
        const roiRes = await fetch("/api/analytics/roi");
        const roi = await roiRes.json();
        document.getElementById("roi-budget-input").value = roi.marketing_budget;
        document.getElementById("roi-revenue").innerText = `${roi.total_revenue.toLocaleString()} UZS`;
        document.getElementById("roi-cac").innerText = `${roi.cac.toLocaleString()} UZS`;
        document.getElementById("roi-profit").innerText = `${roi.net_profit.toLocaleString()} UZS`;
        document.getElementById("roi-percent").innerText = `${roi.roi}%`;

    } catch (err) {
        console.error("Error loading stats:", err);
    }
}

// ================= ADMIN: PATIENTS LIST =================
async function loadPatientsList(query = "", serverFilter = null) {
    const listContainer = document.getElementById("patients-list-container");
    listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    try {
        let url = "/api/patients?";
        if (query) url += `q=${encodeURIComponent(query)}&`;
        if (serverFilter && ["today", "3days", "callback"].includes(serverFilter)) {
            url += `filter=${serverFilter}`;
        }
        const res = await fetch(url);
        currentPatientsList = await res.json();
        applyFiltersAndRender();
    } catch (err) {
        console.error("Error loading list:", err);
        listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--red);"><i class="fa-solid fa-circle-xmark"></i> Xatolik yuz berdi.</div>`;
    }
}

function applyFiltersAndRender() {
    const serverFilters = ["today", "3days", "callback"];
    if (serverFilters.includes(currentFilter)) {
        renderPatientsList(currentPatientsList);
        return;
    }
    let filtered = [...currentPatientsList];
    if (currentFilter === "good")    filtered = filtered.filter(p => p.oxirgi_baho >= 4);
    else if (currentFilter === "bad")    filtered = filtered.filter(p => p.oxirgi_baho !== null && p.oxirgi_baho <= 3);
    else if (currentFilter === "repeat") filtered = filtered.filter(p => p.tashriflar_soni > 1);
    else if (currentFilter === "pending")filtered = filtered.filter(p => p.oxirgi_baho === null);
    renderPatientsList(filtered);
}

function renderPatientsList(patients) {
    const listContainer = document.getElementById("patients-list-container");
    if (patients.length === 0) {
        listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--text-muted);"><i class="fa-solid fa-circle-info"></i> Bemorlar topilmadi.</div>`;
        return;
    }
    listContainer.innerHTML = "";
    const today = new Date().toISOString().split('T')[0];
    patients.forEach(p => {
        const card = document.createElement("div");
        card.className = "patient-row-card";
        const statusClass = p.status === "Faol" ? "active" : (p.status === "Kelgan" ? "active" : "norozi");
        const ratingDisplay = p.oxirgi_baho ? `${p.oxirgi_baho} <i class="fa-solid fa-star" style="color:var(--gold);"></i>` : "Kutilmoqda ⏳";
        const linkDisplay = p.chat_id
            ? `<span style="color:var(--green);"><i class="fa-solid fa-circle-nodes"></i> Ulangan</span>`
            : `<span style="color:var(--text-muted);"><i class="fa-solid fa-link-slash"></i> Ulanmagan</span>`;
        const visitsDisplay = p.tashriflar_soni > 1
            ? `<span style="color:#a78bfa;font-weight:600;font-size:11px;"><i class="fa-solid fa-arrows-spin"></i> ${p.tashriflar_soni}x</span>`
            : `<span style="font-size:11px;color:var(--text-muted);">1-tashrif</span>`;
        let checkupBadge = '';
        if (p.rejalashtirilgan_tekshiruv) {
            const isUrgent = p.rejalashtirilgan_tekshiruv <= today;
            checkupBadge = `<span class="checkup-badge ${isUrgent ? 'urgent' : ''}"><i class="fa-solid fa-calendar-check"></i> ${p.rejalashtirilgan_tekshiruv}</span>`;
        }
        card.innerHTML = `
            <div class="patient-row-header">
                <div class="patient-row-title">
                    <h4>${p.bemor_ismi}</h4>
                    <p><i class="fa-solid fa-phone" style="font-size:10px;"></i> ${p.bemor_telefoni}</p>
                </div>
                <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
                    <span class="status-badge ${statusClass}">${p.status || 'Faol'}</span>
                    ${visitsDisplay}
                </div>
            </div>
            <div class="patient-row-details">
                <div class="detail-item">
                    <span class="lbl">Shifokor</span>
                    <span class="val">${p.shifokor_ismi || 'Belgilanmagan'}</span>
                </div>
                <div class="detail-item">
                    <span class="lbl">Tashrif / Baho</span>
                    <span class="val">${p.oxirgi_tashrif_sanasi || "Noma'lum"} / ${ratingDisplay}</span>
                </div>
                ${p.tashrif_maqsadi ? `<div class="detail-item"><span class="lbl">Maqsad</span><span class="val">${p.tashrif_maqsadi}</span></div>` : ''}
                ${checkupBadge ? `<div class="detail-item" style="grid-column:1/-1;">${checkupBadge}</div>` : ''}
            </div>
            <div class="patient-row-actions">
                <span style="font-size:11px;align-self:center;margin-right:auto;">${linkDisplay}</span>
                <button class="btn-medkarta-trigger" onclick="openPatientMedkarta(${p.id}, '${p.bemor_ismi.replace(/'/g, "\\'")}')"><i class="fa-solid fa-file-medical"></i> Karta</button>
                <button class="btn-edit" onclick="openEditPatient(${p.id})"><i class="fa-solid fa-pen"></i> Tahrir</button>
                <button class="btn-archive" onclick="archivePatient(${p.id}, this)"><i class="fa-solid fa-box-archive"></i></button>
                ${p.chat_id && !p.oxirgi_baho ? `<button class="btn-action" onclick="sendManualFollowup(${p.id})"><i class="fa-solid fa-paper-plane"></i></button>` : ''}
            </div>
        `;
        listContainer.appendChild(card);
    });
}

// Manually trigger Telegram follow-up from WebApp
async function sendManualFollowup(id) {
    try {
        const res = await fetch(`/api/patients/send-followup/${id}`, { method: "POST" });
        const data = await res.json();
        
        if (res.ok) {
            showToast("Eslatma muvaffaqiyatli yuborildi!", "success");
            loadPatientsList(document.getElementById("search-input").value);
        } else {
            showToast(data.detail || "Xabar yuborishda xatolik!", "error");
        }
    } catch (err) {
        showToast("Aloqa xatosi!", "error");
    }
}

// ================= ADMIN: ADD PATIENT =================
async function handleAddPatient(e) {
    e.preventDefault();
    const payload = {
        bemor_ismi: document.getElementById("bemor_ismi").value.trim(),
        bemor_telefoni: document.getElementById("bemor_telefoni").value.trim(),
        shifokor_ismi: document.getElementById("shifokor_ismi").value.trim(),
        oxirgi_tashrif_sanasi: document.getElementById("oxirgi_tashrif_sanasi").value,
        tashrif_maqsadi: document.getElementById("tashrif_maqsadi").value.trim(),
        rejalashtirilgan_tekshiruv: document.getElementById("rejalashtirilgan_tekshiruv").value || null
    };
    try {
        const res = await fetch("/api/patients/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            showToast("Bemor muvaffaqiyatli qo'shildi!", "success");
            document.getElementById("add-patient-form").reset();
            document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
            switchTab("list");
        } else {
            const data = await res.json();
            showToast(data.detail || "Saqlashda xatolik!", "error");
        }
    } catch (err) {
        showToast("Aloqa xatosi!", "error");
    }
}

// ================= ADMIN: SETTINGS =================
async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const settings = await res.json();
        
        document.getElementById("setting-auto-messages").checked = settings.auto_messages_enabled === "1";
        document.getElementById("setting-test-mode").checked = settings.test_mode === "1";

        // Load doctors linking list
        loadDoctorsLinkList();
    } catch (err) {
        console.error("Error loading settings:", err);
    }
}

async function handleSettingsChange() {
    const payload = {
        auto_messages_enabled: document.getElementById("setting-auto-messages").checked ? "1" : "0",
        test_mode: document.getElementById("setting-test-mode").checked ? "1" : "0"
    };

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            showToast("Sozlamalar yangilandi", "success");
        }
    } catch (err) {
        showToast("Sozlamalarni saqlashda xatolik!", "error");
    }
}

// ================= PATIENT: STAR RATING INTERACTION =================
function highlightStars(rating) {
    const starBtns = document.querySelectorAll(".stars-rating .star-btn");
    starBtns.forEach(btn => {
        const val = parseInt(btn.getAttribute("data-value"));
        const icon = btn.querySelector("i");
        if (val <= rating) {
            btn.classList.add("active");
            icon.className = "fa-solid fa-star";
        } else {
            btn.classList.remove("active");
            icon.className = "fa-regular fa-star";
        }
    });
}

async function submitPatientRating() {
    if (selectedRating === 0 || !patientId) return;
    
    const submitBtn = document.getElementById("btn-submit-rating");
    submitBtn.disabled = true;
    submitBtn.innerText = "Yuborilmoqda...";

    try {
        const res = await fetch("/api/patients/submit-rating", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ patient_id: patientId, rating: selectedRating })
        });
        
        if (res.ok) {
            showPatientThankYou(selectedRating);
            showToast("Baholaganingiz uchun rahmat!", "success");
        } else {
            showToast("Xatolik yuz berdi. Qayta urinib ko'ring.", "error");
            submitBtn.disabled = false;
            submitBtn.innerText = "Bahoni yuborish";
        }
    } catch (err) {
        showToast("Aloqa xatosi!", "error");
        submitBtn.disabled = false;
        submitBtn.innerText = "Bahoni yuborish";
    }
}

function showPatientThankYou(rating) {
    document.getElementById("patient-rating-box").classList.add("hidden");
    
    // Change thank you message based on rating
    const feedbackResponse = document.getElementById("patient-feedback-response");
    if (rating <= 3) {
        feedbackResponse.innerText = "Siz bergan baho qabul qilindi. Siz bilan tez orada ma'muriyatimiz bog'lanadi.";
    } else {
        feedbackResponse.innerText = "Katta rahmat! Kelgusi tashrifingiz uchun sizga 5% chegirma taqdim etamiz! Promokod: SHIFO5";
    }
    
    document.getElementById("patient-thankyou-box").classList.remove("hidden");
}

// ================= TOAST NOTIFICATION HELPERS =================
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    
    let icon = "fa-info-circle";
    if (type === "success") icon = "fa-check-circle";
    if (type === "error") icon = "fa-exclamation-circle";
    
    toast.innerHTML = `
        <i class="fa-solid ${icon}"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add("hide");
        setTimeout(() => { toast.remove(); }, 300);
    }, 3000);
}

// ================= DOCTORS DATALIST =================
async function loadDoctorsDatalist() {
    try {
        const res = await fetch("/api/doctors");
        const doctors = await res.json();
        ["doctors-datalist", "edit-doctors-datalist"].forEach(id => {
            const dl = document.getElementById(id);
            if (dl) {
                dl.innerHTML = "";
                doctors.forEach(doc => {
                    const opt = document.createElement("option");
                    opt.value = doc;
                    dl.appendChild(opt);
                });
            }
        });
    } catch (e) { console.error("Doctors load error:", e); }
}

// ================= EDIT PATIENT =================
async function openEditPatient(id) {
    try {
        await loadDoctorsDatalist();
        const res = await fetch(`/api/patients/get/${id}`);
        if (!res.ok) { showToast("Bemor topilmadi!", "error"); return; }
        const p = await res.json();
        document.getElementById("edit-patient-id").value = p.id;
        document.getElementById("edit-bemor-ismi").value = p.bemor_ismi || "";
        document.getElementById("edit-bemor-telefoni").value = p.bemor_telefoni || "";
        document.getElementById("edit-shifokor-ismi").value = p.shifokor_ismi || "";
        document.getElementById("edit-tashrif-maqsadi").value = p.tashrif_maqsadi || "";
        document.getElementById("edit-oxirgi-tashrif").value = p.oxirgi_tashrif_sanasi || "";
        document.getElementById("edit-rejalashtirilgan").value = p.rejalashtirilgan_tekshiruv || "";
        const statusEl = document.getElementById("edit-status");
        statusEl.value = p.status || "Faol";
        document.getElementById("edit-modal").classList.remove("hidden");
    } catch (e) {
        showToast("Xatolik yuz berdi!", "error");
    }
}

function closeEditModal() {
    document.getElementById("edit-modal").classList.add("hidden");
}

async function saveEditedPatient(e) {
    e.preventDefault();
    const id = document.getElementById("edit-patient-id").value;
    const payload = {
        bemor_ismi: document.getElementById("edit-bemor-ismi").value.trim(),
        bemor_telefoni: document.getElementById("edit-bemor-telefoni").value.trim(),
        shifokor_ismi: document.getElementById("edit-shifokor-ismi").value.trim(),
        oxirgi_tashrif_sanasi: document.getElementById("edit-oxirgi-tashrif").value,
        tashrif_maqsadi: document.getElementById("edit-tashrif-maqsadi").value.trim(),
        rejalashtirilgan_tekshiruv: document.getElementById("edit-rejalashtirilgan").value || null,
        status: document.getElementById("edit-status").value
    };
    try {
        const res = await fetch(`/api/patients/update/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            showToast("Ma'lumotlar yangilandi!", "success");
            closeEditModal();
            loadPatientsList(document.getElementById("search-input").value);
        } else {
            const data = await res.json();
            showToast(data.detail || "Xatolik!", "error");
        }
    } catch (e) { showToast("Aloqa xatosi!", "error"); }
}

// ================= ARCHIVE PATIENT =================
async function archivePatient(id, btn) {
    if (!confirm("Bemorni arxivga o'tkazishni tasdiqlaysizmi?")) return;
    try {
        const res = await fetch(`/api/patients/archive/${id}`, { method: "POST" });
        if (res.ok) {
            showToast("Bemor arxivga o'tkazildi.", "success");
            btn.closest(".patient-row-card").remove();
        } else {
            showToast("Arxivlashda xatolik!", "error");
        }
    } catch (e) { showToast("Aloqa xatosi!", "error"); }
}

// ================= CLINIC AUTOMATION: NEW FEATURES JS =================

let currentAdminEMRPatientId = null;
let currentPatientEMRTab = 'records';
let currentAdminEMRTab = 'emr';
let patientDoctorsList = [];
let selectedBookingSlot = null;

// 1. Setup new event listeners
function setupClinicAutomationEventListeners() {
    // Admin add doctor form submit
    const addDoctorForm = document.getElementById("admin-add-doctor-form");
    if (addDoctorForm) {
        addDoctorForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const name = document.getElementById("add-doc-name").value.trim();
            const specialty = document.getElementById("add-doc-specialty").value.trim();
            const price = parseFloat(document.getElementById("add-doc-price").value) || 100000;
            const available_hours = document.getElementById("add-doc-hours").value.trim();

            try {
                showToast("Shifokor qo'shilmoqda...", "info");
                const res = await fetch("/api/doctors/add", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        name: name,
                        specialty: specialty,
                        price: price,
                        available_hours: available_hours
                    })
                });

                if (res.ok) {
                    showToast("Yangi shifokor muvaffaqiyatli qo'shildi!", "success");
                    addDoctorForm.reset();
                    // Set defaults back
                    document.getElementById("add-doc-price").value = "100000";
                    document.getElementById("add-doc-hours").value = "09:00,10:00,11:00,12:00,14:00,15:00,16:00,17:00";
                    // Reload doctors linking list
                    loadDoctorsLinkList();
                    // Reload datalists so the new doctor is available for autocomplete/dropdowns
                    loadDoctorsDatalist();
                } else {
                    const data = await res.json();
                    showToast(data.detail || "Xatolik yuz berdi!", "error");
                }
            } catch (err) {
                showToast("Aloqa xatosi!", "error");
            }
        });
    }

    // Save marketing budget button
    const btnSaveBudget = document.getElementById("btn-save-budget");
    if (btnSaveBudget) {
        btnSaveBudget.addEventListener("click", async () => {
            const amount = parseFloat(document.getElementById("roi-budget-input").value) || 0;
            try {
                const res = await fetch("/api/analytics/marketing-budget", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ amount: amount })
                });
                if (res.ok) {
                    showToast("Byudjet saqlandi va qayta hisoblandi!", "success");
                    loadStatistics();
                } else {
                    showToast("Xatolik yuz berdi!", "error");
                }
            } catch (e) {
                showToast("Aloqa xatosi!", "error");
            }
        });
    }

    // Add EMR record form submit
    const addEMRForm = document.getElementById("add-emr-record-form");
    if (addEMRForm) {
        addEMRForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData();
            formData.append("doctor_name", document.getElementById("emr-doctor-name").value.trim());
            formData.append("visit_date", document.getElementById("emr-visit-date").value);
            formData.append("diagnosis", document.getElementById("emr-diagnosis").value.trim());
            formData.append("prescription", document.getElementById("emr-prescription").value.trim());
            formData.append("notes", document.getElementById("emr-notes").value.trim());
            
            const fileInput = document.getElementById("emr-file-input");
            if (fileInput && fileInput.files.length > 0) {
                formData.append("file", fileInput.files[0]);
            }

            try {
                showToast("Saqlanmoqda va push yuborilmoqda...", "info");
                const res = await fetch(`/api/patients/${currentAdminEMRPatientId}/records`, {
                    method: "POST",
                    body: formData
                });
                if (res.ok) {
                    showToast("Xulosa saqlandi va bemorga push xabar yuborildi!", "success");
                    addEMRForm.reset();
                    // Set visit date back to today
                    document.getElementById("emr-visit-date").value = new Date().toISOString().split('T')[0];
                    loadAdminEMRHistory();
                } else {
                    showToast("Yozishda xatolik yuz berdi!", "error");
                }
            } catch (err) {
                showToast("Aloqa xatosi!", "error");
            }
        });
    }

    // Upload Lab report form submit
    const uploadLabForm = document.getElementById("upload-lab-form");
    if (uploadLabForm) {
        uploadLabForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const testName = document.getElementById("lab-test-name").value.trim();
            const fileInput = document.getElementById("lab-file-input");
            if (!fileInput.files.length) {
                showToast("Iltimos, PDF faylni tanlang!", "error");
                return;
            }
            const formData = new FormData();
            formData.append("patient_id", currentAdminEMRPatientId);
            formData.append("test_name", testName);
            formData.append("file", fileInput.files[0]);

            try {
                showToast("Fayl yuklanmoqda...", "info");
                const res = await fetch("/api/lab-results/upload", {
                    method: "POST",
                    body: formData
                });
                if (res.ok) {
                    showToast("PDF yuklandi va Telegram orqali yuborildi!", "success");
                    uploadLabForm.reset();
                    loadAdminLabsList();
                } else {
                    const data = await res.json();
                    showToast(data.detail || "Yuklashda xatolik!", "error");
                }
            } catch (err) {
                showToast("Aloqa xatosi!", "error");
            }
        });
    }

    // Patient booking inputs change listeners
    const pDoctorSelect = document.getElementById("pbook-doctor-select");
    const pDateInput = document.getElementById("pbook-date-input");
    if (pDoctorSelect && pDateInput) {
        // Set min date to today for bookings
        pDateInput.min = new Date().toISOString().split('T')[0];
        
        pDoctorSelect.addEventListener("change", loadPatientBookingSlots);
        pDateInput.addEventListener("change", loadPatientBookingSlots);
    }

    // Patient booking submit button
    const btnPbookSubmit = document.getElementById("btn-pbook-submit");
    if (btnPbookSubmit) {
        btnPbookSubmit.addEventListener("click", submitPatientBooking);
    }

    // Patient QA submit button
    const btnQaSubmit = document.getElementById("btn-qa-submit");
    if (btnQaSubmit) {
        btnQaSubmit.addEventListener("click", submitPatientQuestion);
    }

    // Patient family add button
    const btnFamilyAdd = document.getElementById("btn-family-add");
    if (btnFamilyAdd) {
        btnFamilyAdd.addEventListener("click", submitFamilyMember);
    }
}

// 2. Bookings manager (Admin view)
async function loadBookingsList(filter = "all") {
    const listContainer = document.getElementById("bookings-list-container");
    if (!listContainer) return;
    listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch("/api/bookings/list");
        let bookings = await res.json();
        
        if (filter !== "all") {
            bookings = bookings.filter(b => b.status === filter);
        }
        
        renderBookingsList(bookings);
    } catch (e) {
        console.error(e);
        listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--red);"><i class="fa-solid fa-triangle-exclamation"></i> Yuklashda xatolik yuz berdi.</div>`;
    }
}

function renderBookingsList(bookings) {
    const listContainer = document.getElementById("bookings-list-container");
    if (bookings.length === 0) {
        listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--text-muted);"><i class="fa-solid fa-circle-info"></i> Qabullar topilmadi.</div>`;
        return;
    }
    
    listContainer.innerHTML = "";
    bookings.forEach(b => {
        const card = document.createElement("div");
        card.className = "patient-row-card";
        
        let statusBadgeClass = "norozi";
        if (b.status === "Keldi") statusBadgeClass = "active";
        else if (b.status === "Kutilmoqda") statusBadgeClass = "active"; // Kutilyapti color
        
        let actionsHtml = "";
        if (b.status === "Kutilmoqda") {
            actionsHtml = `
                <div class="patient-row-actions" style="margin-top: 10px;">
                    <button class="btn-edit" style="background:rgba(16,185,129,0.1); border-color:rgba(16,185,129,0.25); color:var(--green);" onclick="updateBookingStatus(${b.id}, 'Keldi')"><i class="fa-solid fa-check"></i> Keldi</button>
                    <button class="btn-archive" onclick="updateBookingStatus(${b.id}, 'Kelmadi')"><i class="fa-solid fa-xmark"></i> Kelmadi</button>
                    <button class="btn-secondary-mini" onclick="updateBookingStatus(${b.id}, 'Bekor qilindi')">Bekor qilish</button>
                </div>
            `;
        }
        
        card.innerHTML = `
            <div class="patient-row-header">
                <div class="patient-row-title">
                    <h4>${b.patient_name}</h4>
                    <p><i class="fa-solid fa-user-doctor" style="font-size:10px;"></i> Shifokor: <strong>${b.doctor_name}</strong></p>
                </div>
                <div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;">
                    <span class="status-badge ${statusBadgeClass}">${b.status}</span>
                    <span style="font-size:11px; color:var(--text-secondary); font-weight:600;">${b.price.toLocaleString()} UZS</span>
                </div>
            </div>
            <div class="patient-row-details" style="grid-template-columns: 1fr;">
                <div class="detail-item">
                    <span class="lbl">Qabul vaqti</span>
                    <span class="val" style="font-size:14px; font-weight:600; color:var(--accent);"><i class="fa-solid fa-clock"></i> ${b.booking_date} kuni soat ${b.booking_time}</span>
                </div>
            </div>
            ${actionsHtml}
        `;
        listContainer.appendChild(card);
    });
}

async function updateBookingStatus(bookingId, status) {
    try {
        const res = await fetch("/api/bookings/update-status", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ booking_id: bookingId, status: status })
        });
        if (res.ok) {
            showToast(`Status '${status}' deb belgilandi!`, "success");
            // Reload active tab filter
            const activePill = document.querySelector(".booking-filter-pill.active");
            const bfilter = activePill ? activePill.getAttribute("data-bfilter") : "all";
            loadBookingsList(bfilter);
        } else {
            showToast("Xatolik yuz berdi!", "error");
        }
    } catch (e) {
        showToast("Aloqa xatosi!", "error");
    }
}

// 3. Admin Medkarta Modal functions
function openPatientMedkarta(patientId, patientName) {
    currentAdminEMRPatientId = patientId;
    document.getElementById("medkarta-patient-name").innerText = patientName;
    
    // Set date to today
    document.getElementById("emr-visit-date").value = new Date().toISOString().split('T')[0];
    
    // Switch to EMR tab by default
    switchAdminEMRTab('emr');
    
    document.getElementById("medkarta-modal").classList.remove("hidden");
}

function closeMedkartaModal() {
    document.getElementById("medkarta-modal").classList.add("hidden");
}

function switchAdminEMRTab(tabName) {
    currentAdminEMRTab = tabName;
    const emrBtn = document.getElementById("admin-emr-tab-btn");
    const labsBtn = document.getElementById("admin-labs-tab-btn");
    const emrContent = document.getElementById("admin-emr-tab-content");
    const labsContent = document.getElementById("admin-labs-tab-content");

    if (tabName === 'emr') {
        emrBtn.classList.add("active");
        labsBtn.classList.remove("active");
        emrContent.classList.remove("hidden");
        labsContent.classList.add("hidden");
        loadAdminEMRHistory();
    } else {
        emrBtn.classList.remove("active");
        labsBtn.classList.add("active");
        emrContent.classList.add("hidden");
        labsContent.classList.remove("hidden");
        loadAdminLabsList();
    }
}

async function loadAdminEMRHistory() {
    const historyContainer = document.getElementById("admin-emr-history");
    historyContainer.innerHTML = `<div class="text-center py-2" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch(`/api/patients/${currentAdminEMRPatientId}/records`);
        const records = await res.json();
        
        if (records.length === 0) {
            historyContainer.innerHTML = `<p class="text-center py-3" style="color:rgba(255,255,255,0.3); font-size:0.9rem;">Tarixiy yozuvlar mavjud emas.</p>`;
            return;
        }
        
        historyContainer.innerHTML = "";
        records.forEach(r => {
            const card = document.createElement("div");
            card.className = "emr-record-card";
            card.innerHTML = `
                <div class="emr-record-header">
                    <span>👨‍⚕️ Shifokor: <strong>${r.doctor_name}</strong></span>
                    <span>📅 ${r.visit_date}</span>
                </div>
                <div class="emr-record-diagnosis">📋 Diagnoz: ${r.diagnosis}</div>
                ${r.prescription ? `<div class="emr-record-prescription">💊 Retsept: ${r.prescription}</div>` : ''}
                ${r.notes ? `<div class="emr-record-notes">📝 Eslatma: ${r.notes}</div>` : ''}
            `;
            historyContainer.appendChild(card);
        });
    } catch (e) {
        historyContainer.innerHTML = `<p class="text-center py-3" style="color:var(--red);">Yuklashda xatolik yuz berdi.</p>`;
    }
}

async function loadAdminLabsList() {
    const labsContainer = document.getElementById("admin-labs-list");
    labsContainer.innerHTML = `<div class="text-center py-2" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch(`/api/patients/${currentAdminEMRPatientId}/labs`);
        const labs = await res.json();
        
        if (labs.length === 0) {
            labsContainer.innerHTML = `<p class="text-center py-3" style="color:rgba(255,255,255,0.3); font-size:0.9rem;">Tahlillar yuklanmagan.</p>`;
            return;
        }
        
        labsContainer.innerHTML = "";
        labs.forEach(l => {
            const div = document.createElement("div");
            div.className = "lab-item";
            div.innerHTML = `
                <div class="lab-info">
                    <h5>${l.test_name}</h5>
                    <p>Yuklangan sana: ${l.uploaded_at.split('T')[0]}</p>
                </div>
                <a href="${l.pdf_file_path}" target="_blank" class="btn-download-pdf"><i class="fa-solid fa-file-pdf"></i> PDF ko'rish</a>
            `;
            labsContainer.appendChild(div);
        });
    } catch (e) {
        labsContainer.innerHTML = `<p class="text-center py-3" style="color:var(--red);">Yuklashda xatolik yuz berdi.</p>`;
    }
}

// 4. Patient Portal functionalities
async function initPatientPortalData() {
    try {
        // Load doctors list
        const res = await fetch("/api/doctors/all");
        patientDoctorsList = await res.json();
        
        const docSelect = document.getElementById("pbook-doctor-select");
        if (docSelect) {
            docSelect.innerHTML = `<option value="">Shifokorni tanlang...</option>`;
            patientDoctorsList.forEach(d => {
                const opt = document.createElement("option");
                opt.value = d.name;
                const price = d.price !== undefined && d.price !== null ? d.price : 100000;
                opt.innerText = `${d.name} (${d.specialty}) - ${price.toLocaleString()} UZS`;
                docSelect.appendChild(opt);
            });
        }
        
        // Load patient history
        loadPatientEMRHistory();
        loadPatientLabsList();
        loadPatientVisitsHistory();
        loadPatientNextAppointments();
    } catch (e) {
        console.error(e);
    }
}

async function loadPatientBookingSlots() {
    const doctorName = document.getElementById("pbook-doctor-select").value;
    const date = document.getElementById("pbook-date-input").value;
    const grid = document.getElementById("pbook-slots-grid");
    const summary = document.getElementById("pbook-summary");
    const submitBtn = document.getElementById("btn-pbook-submit");
    
    selectedBookingSlot = null;
    submitBtn.classList.add("disabled");
    submitBtn.disabled = true;
    summary.classList.add("hidden");

    if (!doctorName || !date) {
        grid.innerHTML = `<p class="text-center" style="grid-column:1/-1; color:rgba(255,255,255,0.4); font-size:0.9rem;">Shifokor va sanani tanlang...</p>`;
        return;
    }

    grid.innerHTML = `<div class="text-center" style="grid-column:1/-1; color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;

    try {
        const res = await fetch(`/api/bookings/available-slots?doctor_name=${encodeURIComponent(doctorName)}&date=${date}`);
        const slots = await res.json();
        
        grid.innerHTML = "";
        slots.forEach(slot => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = `slot-btn ${slot.available ? '' : 'disabled'}`;
            btn.innerText = slot.time;
            btn.disabled = !slot.available;
            
            if (slot.available) {
                btn.addEventListener("click", () => {
                    document.querySelectorAll(".slot-btn").forEach(b => b.classList.remove("selected"));
                    btn.classList.add("selected");
                    selectedBookingSlot = slot.time;
                    
                    // Show summary
                    const docObj = patientDoctorsList.find(d => d.name === doctorName);
                    const priceVal = docObj && docObj.price !== undefined && docObj.price !== null ? docObj.price : 100000;
                    document.getElementById("pbook-sum-doctor").innerText = doctorName;
                    document.getElementById("pbook-sum-datetime").innerText = `${date} kuni soat ${slot.time}`;
                    document.getElementById("pbook-sum-price").innerText = `${priceVal.toLocaleString()} UZS`;
                    
                    summary.classList.remove("hidden");
                    submitBtn.classList.remove("disabled");
                    submitBtn.disabled = false;
                });
            }
            grid.appendChild(btn);
        });
    } catch (e) {
        grid.innerHTML = `<p class="text-center" style="grid-column:1/-1; color:var(--red);">Bo'sh vaqtlarni olishda xatolik yuz berdi.</p>`;
    }
}

async function submitPatientBooking() {
    const doctorName = document.getElementById("pbook-doctor-select").value;
    const date = document.getElementById("pbook-date-input").value;
    const docObj = patientDoctorsList.find(d => d.name === doctorName);
    
    if (!patientId || !doctorName || !date || !selectedBookingSlot) return;

    try {
        showToast("Band qilinmoqda...", "info");
        const res = await fetch("/api/bookings/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                patient_id: patientId,
                doctor_name: doctorName,
                booking_date: date,
                booking_time: selectedBookingSlot,
                price: (docObj && docObj.price !== undefined && docObj.price !== null) ? docObj.price : 100000.0
            })
        });
        
        if (res.ok) {
            showToast("Siz qabulga muvaffaqiyatli yozildingiz! Telegram orqali xabar yuborildi.", "success");
            // Clear inputs
            document.getElementById("pbook-doctor-select").value = "";
            document.getElementById("pbook-date-input").value = "";
            document.getElementById("pbook-slots-grid").innerHTML = `<p class="text-center" style="grid-column:1/-1; color:rgba(255,255,255,0.4); font-size:0.9rem;">Shifokor va sanani tanlang...</p>`;
            document.getElementById("pbook-summary").classList.add("hidden");
            document.getElementById("btn-pbook-submit").classList.add("disabled");
            document.getElementById("btn-pbook-submit").disabled = true;
        } else {
            const data = await res.json();
            showToast(data.detail || "Band qilishda xatolik!", "error");
        }
    } catch (e) {
        showToast("Aloqa xatosi!", "error");
    }
}

function switchPatientEMRTab(tabName) {
    currentPatientEMRTab = tabName;
    const tabs = ['records', 'labs', 'visits', 'next'];
    
    tabs.forEach(t => {
        const btn = document.getElementById(`p-emr-${t}-tab`);
        const cont = document.getElementById(`p-emr-${t}-container`);
        if (t === tabName) {
            btn.classList.add("active");
            cont.classList.remove("hidden");
        } else {
            btn.classList.remove("active");
            cont.classList.add("hidden");
        }
    });
}

async function loadPatientEMRHistory() {
    const container = document.getElementById("p-emr-records-container");
    if (!container) return;
    container.innerHTML = `<div class="text-center py-2" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch(`/api/patients/${patientId}/records`);
        const records = await res.json();
        
        if (records.length === 0) {
            container.innerHTML = `<p class="text-center py-3" style="color:rgba(255,255,255,0.3); font-size:0.9rem;">Tibbiy tarixingiz topilmadi.</p>`;
            return;
        }
        
        container.innerHTML = "";
        records.forEach(r => {
            const card = document.createElement("div");
            card.className = "emr-record-card";
            
            let pharmacyLinkHtml = "";
            if (r.prescription) {
                const query = encodeURIComponent(r.prescription);
                pharmacyLinkHtml = `
                    <div class="emr-record-prescription">💊 Tavsiya etilgan dori-darmonlar:<br>${r.prescription}</div>
                    <a href="https://arzonapteka.uz/uz/search?query=${query}" target="_blank" class="pharmacy-partner-btn">
                        <i class="fa-solid fa-pills"></i> Dorilarni hamkor dorixonadan sotib olish (10% chegirma)
                    </a>
                `;
            }
            
            card.innerHTML = `
                <div class="emr-record-header">
                    <span>👨‍⚕️ Shifokor: <strong>${r.doctor_name}</strong></span>
                    <span>📅 ${r.visit_date}</span>
                </div>
                <div class="emr-record-diagnosis">📋 Diagnoz (Tashxis): ${r.diagnosis}</div>
                ${pharmacyLinkHtml}
                ${r.notes ? `<div class="emr-record-notes">📝 Izoh: ${r.notes}</div>` : ''}
            `;
            container.appendChild(card);
        });
    } catch (e) {
        container.innerHTML = `<p class="text-center py-3" style="color:var(--red);">Yuklashda xatolik yuz berdi.</p>`;
    }
}

async function loadPatientLabsList() {
    const container = document.getElementById("p-emr-labs-container");
    if (!container) return;
    container.innerHTML = `<div class="text-center py-2" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch(`/api/patients/${patientId}/labs`);
        const labs = await res.json();
        
        if (labs.length === 0) {
            container.innerHTML = `<p class="text-center py-3" style="color:rgba(255,255,255,0.3); font-size:0.9rem;">Tahlil natijalari mavjud emas.</p>`;
            return;
        }
        
        container.innerHTML = "";
        labs.forEach(l => {
            const div = document.createElement("div");
            div.className = "lab-item";
            div.innerHTML = `
                <div class="lab-info">
                    <h5>🧪 ${l.test_name}</h5>
                    <p>Sana: ${l.uploaded_at.split('T')[0]}</p>
                </div>
                <a href="${l.file_path}" target="_blank" class="btn-download-pdf"><i class="fa-solid fa-file-pdf"></i> PDF ko'rish</a>
            `;
            container.appendChild(div);
        });
    } catch (e) {
        container.innerHTML = `<p class="text-center py-3" style="color:var(--red);">Yuklashda xatolik yuz berdi.</p>`;
    }
}

async function loadPatientVisitsHistory() {
    const container = document.getElementById("p-emr-visits-container");
    if (!container) return;
    container.innerHTML = `<div class="text-center py-2" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch(`/api/patients/${patientId}/bookings`);
        const bookings = await res.json();
        
        if (bookings.length === 0) {
            container.innerHTML = `<p class="text-center py-3" style="color:rgba(255,255,255,0.3); font-size:0.9rem;">Tashriflar tarixi topilmadi.</p>`;
            return;
        }
        
        container.innerHTML = "";
        bookings.forEach(b => {
            const card = document.createElement("div");
            card.className = "emr-record-card";
            
            let statusBadge = "";
            if (b.status === "Keldi") {
                statusBadge = `<span class="status-badge active">O'tgan</span>`;
            } else if (b.status === "Kutilmoqda") {
                statusBadge = `<span class="status-badge active" style="background:rgba(59,130,246,0.1); color:#3b82f6; border-color:rgba(59,130,246,0.25);">Kutilmoqda</span>`;
            } else {
                statusBadge = `<span class="status-badge norozi">${b.status}</span>`;
            }
            
            card.innerHTML = `
                <div class="emr-record-header">
                    <span>👨‍⚕️ Shifokor: <strong>${b.doctor_name}</strong></span>
                    <span>📅 ${b.booking_date}</span>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
                    <span style="font-size:0.9rem; color:var(--text-secondary);"><i class="fa-solid fa-clock"></i> Soat: ${b.booking_time}</span>
                    ${statusBadge}
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        container.innerHTML = `<p class="text-center py-3" style="color:var(--red);">Yuklashda xatolik yuz berdi.</p>`;
    }
}

async function loadPatientNextAppointments() {
    const container = document.getElementById("p-emr-next-container");
    if (!container) return;
    container.innerHTML = `<div class="text-center py-2" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch(`/api/patients/${patientId}/bookings`);
        const bookings = await res.json();
        
        const todayStr = new Date().toISOString().split('T')[0];
        const nextAppointments = bookings.filter(b => b.status === "Kutilmoqda" && b.booking_date >= todayStr);
        
        if (nextAppointments.length === 0) {
            container.innerHTML = `
                <div class="text-center py-4" style="color:rgba(255,255,255,0.4);">
                    <i class="fa-solid fa-calendar-xmark" style="font-size:2rem; margin-bottom:10px; color:rgba(255,255,255,0.2);"></i>
                    <p style="font-size:0.95rem;">Kelgusi faol qabullar mavjud emas.</p>
                    <p style="font-size:0.85rem; margin-top:5px; color:var(--text-muted);">Qabulga yozilish bo'limi orqali shifokor ko'rigiga yozilishingiz mumkin.</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = "";
        nextAppointments.forEach(b => {
            const card = document.createElement("div");
            card.className = "emr-record-card";
            card.style.borderColor = "var(--accent)";
            card.style.background = "rgba(107,33,168,0.15)";
            
            card.innerHTML = `
                <div class="emr-record-header">
                    <span style="color:var(--accent);"><i class="fa-solid fa-bell animate-bounce"></i> <strong>Kelgusi uchrashuv</strong></span>
                    <span style="font-weight:600; color:var(--accent);">${b.booking_date}</span>
                </div>
                <div style="margin-top:10px;">
                    <p style="margin:4px 0;">👨‍⚕️ <strong>Shifokor:</strong> ${b.doctor_name}</p>
                    <p style="margin:4px 0;">⏰ <strong>Vaqt:</strong> soat ${b.booking_time} da</p>
                    <p style="margin:4px 0; font-size:0.85rem; color:var(--text-secondary);"><i class="fa-solid fa-clock"></i> Iltimos, belgilangan vaqtdan 10 daqiqa oldin keling.</p>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        container.innerHTML = `<p class="text-center py-3" style="color:var(--red);">Yuklashda xatolik yuz berdi.</p>`;
    }
}

// ================= PATIENT: Q&A CHAT LOGIC =================
async function loadPatientQA() {
    const listContainer = document.getElementById("qa-messages-list");
    if (!listContainer) return;
    listContainer.innerHTML = `<div class="text-center py-2" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch(`/api/qa/patient/${patientId}`);
        const questions = await res.json();
        
        if (questions.length === 0) {
            listContainer.innerHTML = `<p class="text-center py-3" style="color:rgba(255,255,255,0.3); font-size:0.9rem;">Hozircha savollar yo'q.</p>`;
            return;
        }
        
        listContainer.innerHTML = "";
        questions.forEach(q => {
            const item = document.createElement("div");
            item.className = "qa-message-item";
            
            let answerHtml = "";
            if (q.answer_text) {
                answerHtml = `
                    <div class="qa-answer-bubble">
                        <div class="qa-answer-header"><i class="fa-solid fa-user-doctor"></i> Shifokor javobi:</div>
                        <div class="qa-answer-text">${q.answer_text}</div>
                    </div>
                `;
            } else {
                answerHtml = `<span class="qa-pending-badge">Javob kutilmoqda...</span>`;
            }
            
            item.innerHTML = `
                <div class="qa-question-bubble">
                    <div class="qa-question-text"><strong>Savol:</strong> ${q.question_text}</div>
                </div>
                ${answerHtml}
                <span class="qa-time">${q.asked_at.replace('T', ' ').substring(0, 16)}</span>
            `;
            listContainer.appendChild(item);
        });
    } catch (e) {
        listContainer.innerHTML = `<p class="text-center py-3" style="color:var(--red);">Yuklashda xatolik yuz berdi.</p>`;
    }
}

async function submitPatientQuestion() {
    const input = document.getElementById("qa-text-input");
    const text = input.value.trim();
    if (!text) {
        showToast("Iltimos, savolni kiriting!", "error");
        return;
    }
    
    try {
        const res = await fetch("/api/qa/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                patient_id: patientId,
                question_text: text
            })
        });
        if (res.ok) {
            showToast("Savolingiz shifokorga yuborildi!", "success");
            input.value = "";
            loadPatientQA();
        } else {
            showToast("Savol yuborishda xatolik yuz berdi!", "error");
        }
    } catch (e) {
        showToast("Aloqa xatosi!", "error");
    }
}

// ================= PATIENT: FAMILY ACCOUNT SWITCHER LOGIC =================
async function loadPatientFamily() {
    const container = document.getElementById("family-members-list");
    if (!container) return;
    container.innerHTML = `<div class="text-center py-2" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch(`/api/patients/family/${currentUser.chat_id}`);
        const members = await res.json();
        
        container.innerHTML = "";
        members.forEach(m => {
            const card = document.createElement("div");
            const isActive = m.id === patientId;
            card.className = `family-member-card ${isActive ? 'active' : ''}`;
            card.setAttribute("onclick", `switchFamilyMember(${m.id})`);
            
            card.innerHTML = `
                <div class="member-info">
                    <h4>${m.bemor_ismi}</h4>
                    <p><i class="fa-solid fa-phone"></i> ${m.bemor_telefoni}</p>
                </div>
                ${isActive ? '<div class="active-check"><i class="fa-solid fa-circle-check animate-scale"></i></div>' : ''}
            `;
            container.appendChild(card);
        });
    } catch (e) {
        container.innerHTML = `<p class="text-center py-3" style="color:var(--red);">Yuklashda xatolik yuz berdi.</p>`;
    }
}

async function submitFamilyMember() {
    const nameInput = document.getElementById("family-name-input");
    const phoneInput = document.getElementById("family-phone-input");
    const name = nameInput.value.trim();
    const phone = phoneInput.value.trim();
    
    if (!name || !phone) {
        showToast("Iltimos, barcha maydonlarni to'ldiring!", "error");
        return;
    }
    
    try {
        const res = await fetch("/api/patients/family/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                chat_id: currentUser.chat_id,
                bemor_ismi: name,
                bemor_telefoni: phone
            })
        });
        if (res.ok) {
            showToast("Oila a'zosi muvaffaqiyatli qo'shildi!", "success");
            nameInput.value = "";
            phoneInput.value = "";
            loadPatientFamily();
        } else {
            showToast("Oila a'zosi qo'shishda xatolik yuz berdi!", "error");
        }
    } catch (e) {
        showToast("Aloqa xatosi!", "error");
    }
}

async function switchFamilyMember(newPatientId) {
    if (newPatientId === patientId) return;
    
    patientId = newPatientId;
    showToast("Profil almashtirildi!", "info");
    
    try {
        const res = await fetch(`/api/patients/get/${patientId}`);
        const patientData = await res.json();
        
        document.getElementById("patient-welcome").innerText = `Salom, ${patientData.bemor_ismi}!`;
        document.getElementById("patient-doctor").innerText = patientData.shifokor_ismi || "Noma'lum";
        document.getElementById("patient-visit-date").innerText = patientData.oxirgi_tashrif_sanasi || "Noma'lum";
        
        // Render Profile details
        document.getElementById("prof-name").innerText = patientData.bemor_ismi;
        document.getElementById("prof-phone").innerText = patientData.bemor_telefoni;
        
        const statusClass = patientData.status === "Faol" ? "active" : "norozi";
        document.getElementById("prof-status").innerHTML = `<span class="status-badge ${statusClass}">${patientData.status}</span>`;
        
        document.getElementById("prof-visits").innerText = patientData.tashriflar_soni || 1;
        document.getElementById("prof-last-visit").innerText = patientData.oxirgi_tashrif_sanasi || "Yo'q";
        document.getElementById("prof-doctor").innerText = patientData.shifokor_ismi || "Yo'q";
        document.getElementById("prof-last-rating").innerText = patientData.oxirgi_baho ? `${patientData.oxirgi_baho} / 5` : "Baholanmagan";

        // Reset and check rating view
        if (patientData.oxirgi_baho) {
            showPatientThankYou(patientData.oxirgi_baho);
        } else {
            document.getElementById("patient-thankyou-box").classList.add("hidden");
            document.getElementById("patient-rating-box").classList.remove("hidden");
            selectedRating = 0;
            highlightStars(0);
            const submitBtn = document.getElementById("btn-submit-rating");
            submitBtn.classList.add("disabled");
            submitBtn.disabled = true;
            document.getElementById("rating-desc").innerText = "Bahoni tanlang";
        }
        
        // Reload all data for the new active patient
        initPatientPortalData();
        loadPatientFamily();
        
        // Switch back to rating/default tab
        const ratingBtn = document.querySelector('[data-ptab="rating"]');
        if (ratingBtn) ratingBtn.click();
    } catch (e) {
        showToast("Profil yuklashda xatolik yuz berdi!", "error");
    }
}

// ================= ADMIN: Q&A MANAGEMENT =================
async function loadAdminQA() {
    const listContainer = document.getElementById("admin-qa-list-container");
    if (!listContainer) return;
    listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Yuklanmoqda...</div>`;
    
    try {
        const res = await fetch("/api/qa/pending");
        const pending = await res.json();
        
        if (pending.length === 0) {
            listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--text-muted);"><i class="fa-solid fa-circle-info"></i> Yangi savollar yo'q.</div>`;
            return;
        }
        
        listContainer.innerHTML = "";
        pending.forEach(q => {
            const card = document.createElement("div");
            card.className = "patient-row-card";
            card.innerHTML = `
                <div class="patient-row-header">
                    <div class="patient-row-title">
                        <h4>Bemor: ${q.patient_name}</h4>
                        <p><i class="fa-solid fa-phone" style="font-size:10px;"></i> ${q.bemor_telefoni || 'Noma\'lum'}</p>
                    </div>
                    <span class="status-badge kutilmoqda" style="background:rgba(245, 158, 11, 0.15); color:var(--gold); border-color:rgba(245,158,11,0.25);">Javobsiz</span>
                </div>
                <div style="margin-top: 10px; background: rgba(0,0,0,0.1); padding: 8px 10px; border-radius: 6px; font-size: 13px;">
                    <strong>Savol:</strong> ${q.question_text}
                </div>
                <div class="form-group" style="margin-top: 12px;">
                    <label style="font-size:11px; font-weight:600; color:var(--text-muted);">Javob yozish</label>
                    <div style="display:flex; gap:8px; margin-top:4px;">
                        <input type="text" id="doctor-answer-input-${q.id}" class="form-input" style="flex:1; padding:6px 12px; font-size:13px;" placeholder="Javobni kiriting...">
                        <button onclick="submitDoctorAnswer(${q.id}, 'doctor-answer-input-${q.id}')" class="btn-primary" style="padding:6px 15px; font-size:12px;"><i class="fa-solid fa-paper-plane"></i> Javob berish</button>
                    </div>
                </div>
            `;
            listContainer.appendChild(card);
        });
    } catch (e) {
        listContainer.innerHTML = `<div class="text-center py-4" style="color:var(--red);"><i class="fa-solid fa-circle-xmark"></i> Xatolik yuz berdi.</div>`;
    }
}

async function submitDoctorAnswer(questionId, inputId) {
    const input = document.getElementById(inputId);
    const text = input.value.trim();
    if (!text) {
        showToast("Iltimos, javobni kiriting!", "error");
        return;
    }
    
    try {
        const res = await fetch("/api/qa/answer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                question_id: questionId,
                answer_text: text
            })
        });
        if (res.ok) {
            showToast("Javob bemorga yuborildi!", "success");
            loadAdminQA();
        } else {
            showToast("Javob berishda xatolik yuz berdi!", "error");
        }
    } catch (e) {
        showToast("Aloqa xatosi!", "error");
    }
}

// ====== DOCTOR PORTAL DATA INITIALIZATION ======
let doctorBookings = [];
let doctorArchivePatients = [];

function initDoctorPortalData() {
    // 1. Tab switching
    document.querySelectorAll("#doctor-view .bottom-nav .nav-item").forEach(item => {
        // Remove existing listener if any
        const newItem = item.cloneNode(true);
        item.parentNode.replaceChild(newItem, item);
        
        newItem.addEventListener("click", () => {
            const tabId = newItem.getAttribute("data-tab");
            switchDoctorTab(tabId);
        });
    });

    // 2. Search input filtering for archive
    const searchInput = document.getElementById("doc-archive-search-input");
    if (searchInput) {
        // Clone to remove previous listeners
        const newSearchInput = searchInput.cloneNode(true);
        searchInput.parentNode.replaceChild(newSearchInput, searchInput);
        
        newSearchInput.addEventListener("input", (e) => {
            const query = e.target.value.toLowerCase().trim();
            filterDoctorArchive(query);
        });
    }

    // 3. Form submit event
    const acceptForm = document.getElementById("doc-accept-form");
    if (acceptForm) {
        // Clone to remove previous listeners
        const newAcceptForm = acceptForm.cloneNode(true);
        acceptForm.parentNode.replaceChild(newAcceptForm, acceptForm);
        
        newAcceptForm.addEventListener("submit", handleDocAcceptSubmit);
    }

    // 4. Initial loads
    loadDoctorBookings();
    loadDoctorArchive();
    loadDoctorKPIs();
}

function switchDoctorTab(tabId) {
    document.querySelectorAll("#doctor-view .bottom-nav .nav-item").forEach(btn => {
        if (btn.getAttribute("data-tab") === tabId) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });

    document.querySelectorAll("#doctor-view .tab-content").forEach(content => {
        if (content.id === `tab-${tabId}`) {
            content.classList.remove("hidden");
        } else {
            content.classList.add("hidden");
        }
    });
}

async function loadDoctorBookings() {
    const listContainer = document.getElementById("doc-bookings-list");
    if (!listContainer) return;

    try {
        listContainer.innerHTML = '<div class="text-center py-8"><i class="fa-solid fa-spinner fa-spin" style="font-size:1.5rem; opacity:0.3;"></i></div>';
        const res = await fetch(`/api/doctor/bookings?chat_id=${currentUser.chat_id}`);
        if (!res.ok) throw new Error();
        doctorBookings = await res.json();
        
        // Filter out bookings that are already completed ('Keldi' / 'Bekor qilindi')
        const activeBookings = doctorBookings.filter(b => b.status === "Kutilmoqda");

        if (activeBookings.length === 0) {
            listContainer.innerHTML = `
                <div class="text-center py-8">
                    <i class="fa-solid fa-calendar-check" style="font-size: 2.5rem; opacity: 0.2; margin-bottom: 10px;"></i>
                    <p style="color: var(--text-secondary);">Bugun uchun kutilayotgan bemorlar ro'yxati bo'sh.</p>
                </div>`;
            return;
        }

        listContainer.innerHTML = "";
        activeBookings.forEach(b => {
            const card = document.createElement("div");
            card.className = "patient-card-row glass-panel";
            card.style.margin = "10px 0";
            card.innerHTML = `
                <div class="patient-info-col">
                    <h4 style="margin: 0 0 4px 0; color: white;">${b.bemor_ismi}</h4>
                    <p class="phone-num" style="margin: 0; font-size: 0.82rem; color: var(--text-secondary);"><i class="fa-solid fa-phone"></i> ${b.bemor_telefoni}</p>
                    <p class="appointment-time" style="margin: 4px 0 0 0; font-size: 0.85rem; color: white;"><i class="fa-solid fa-clock" style="color:var(--accent); margin-right: 4px;"></i> Soat: <strong>${b.booking_time}</strong></p>
                </div>
                <div class="actions-col" style="display:flex; flex-direction:column; gap:6px; min-width: 100px;">
                    <button class="btn-primary btn-sm" onclick="openDocAcceptModal(${b.id}, '${b.bemor_ismi.replace(/'/g, "\\'")}')" style="padding: 6px 12px; font-size: 0.8rem;">
                        <i class="fa-solid fa-circle-check"></i> Qabul qilish
                    </button>
                    <button class="btn-secondary btn-sm" onclick="openDocPatientHistoryModal(${b.patient_id}, '${b.bemor_ismi.replace(/'/g, "\\'")}', '${b.bemor_telefoni}')" style="padding: 6px 12px; font-size: 0.8rem; background: rgba(255,255,255,0.05); color: white;">
                        <i class="fa-solid fa-notes-medical"></i> Tarixi
                    </button>
                </div>
            `;
            listContainer.appendChild(card);
        });
    } catch (e) {
        listContainer.innerHTML = '<div class="text-center py-8" style="color:var(--red);"><i class="fa-solid fa-circle-xmark"></i> Yuklashda xatolik yuz berdi.</div>';
    }
}

async function loadDoctorArchive() {
    const listContainer = document.getElementById("doc-archive-list");
    if (!listContainer) return;

    try {
        const res = await fetch("/api/patients");
        if (res.ok) {
            doctorArchivePatients = await res.json();
            renderDoctorArchive(doctorArchivePatients);
        }
    } catch (e) {
        listContainer.innerHTML = '<div class="text-center py-4" style="color:var(--red);">Yuklashda xatolik.</div>';
    }
}

function renderDoctorArchive(patientsList) {
    const listContainer = document.getElementById("doc-archive-list");
    if (!listContainer) return;

    if (patientsList.length === 0) {
        listContainer.innerHTML = '<div class="text-center py-4" style="color:var(--text-secondary);">Bemorlar topilmadi.</div>';
        return;
    }

    listContainer.innerHTML = "";
    patientsList.forEach(p => {
        const card = document.createElement("div");
        card.className = "patient-card-row glass-panel";
        card.style.margin = "10px 0";
        card.style.cursor = "pointer";
        card.onclick = () => openDocPatientHistoryModal(p.id, p.bemor_ismi, p.bemor_telefoni);
        card.innerHTML = `
            <div class="patient-info-col" style="flex: 1;">
                <h4 style="margin: 0 0 4px 0; color: white;">${p.bemor_ismi}</h4>
                <p class="phone-num" style="margin: 0; font-size: 0.82rem; color: var(--text-secondary);"><i class="fa-solid fa-phone"></i> ${p.bemor_telefoni}</p>
                <p style="font-size:0.8rem; color:var(--text-secondary); margin:4px 0 0 0;">
                    Oxirgi tashrif: ${p.oxirgi_tashrif_sanasi || "Noma'lum"}
                </p>
            </div>
            <div class="actions-col" style="display: flex; align-items: center; justify-content: center;">
                <i class="fa-solid fa-chevron-right" style="opacity:0.3; color: white;"></i>
            </div>
        `;
        listContainer.appendChild(card);
    });
}

function filterDoctorArchive(query) {
    if (!query) {
        renderDoctorArchive(doctorArchivePatients);
        return;
    }
    const filtered = doctorArchivePatients.filter(p => 
        p.bemor_ismi.toLowerCase().includes(query) || 
        p.bemor_telefoni.includes(query)
    );
    renderDoctorArchive(filtered);
}

async function loadDoctorKPIs() {
    try {
        const res = await fetch(`/api/doctor/kpis?chat_id=${currentUser.chat_id}`);
        if (!res.ok) return;
        const kpis = await res.json();

        document.getElementById("doc-stat-total-patients").innerText = kpis.total_patients;
        document.getElementById("doc-stat-avg-rating").innerText = kpis.avg_rating.toFixed(1);
        document.getElementById("doc-stat-repeat-patients").innerText = kpis.repeat_patients;
        document.getElementById("doc-stat-repeat-rate").innerText = kpis.repeat_rate + "%";
    } catch (e) {
        console.error("Failed to load doctor KPIs:", e);
    }
}

// ------ DOCTOR ACCEPTS PATIENT DIALOG ------
function openDocAcceptModal(bookingId, patientName) {
    document.getElementById("doc-accept-booking-id").value = bookingId;
    document.getElementById("doc-accept-patient-name").innerText = patientName;
    document.getElementById("doc-accept-diagnosis").value = "";
    document.getElementById("doc-accept-prescription").value = "";
    document.getElementById("doc-accept-file").value = "";
    document.getElementById("doc-accept-notes").value = "";

    document.getElementById("doc-accept-modal").classList.remove("hidden");
}

function closeDocAcceptModal() {
    document.getElementById("doc-accept-modal").classList.add("hidden");
}

async function handleDocAcceptSubmit(e) {
    e.preventDefault();
    const btn = e.target.querySelector("button[type='submit']");
    btn.disabled = true;
    const oldText = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saqlanmoqda...';

    const bookingId = document.getElementById("doc-accept-booking-id").value;
    const diagnosis = document.getElementById("doc-accept-diagnosis").value.trim();
    const prescription = document.getElementById("doc-accept-prescription").value.trim();
    const notes = document.getElementById("doc-accept-notes").value.trim();
    const fileInput = document.getElementById("doc-accept-file");

    const formData = new FormData();
    formData.append("booking_id", bookingId);
    formData.append("diagnosis", diagnosis);
    formData.append("prescription", prescription);
    formData.append("notes", notes);
    if (fileInput.files[0]) {
        formData.append("file", fileInput.files[0]);
    }

    try {
        const res = await fetch("/api/doctor/accept-patient", {
            method: "POST",
            body: formData
        });

        if (res.ok) {
            showToast("Bemor qabul qilindi va tibbiy xulosa yuborildi!", "success");
            closeDocAcceptModal();
            loadDoctorBookings();
            loadDoctorKPIs();
        } else {
            showToast("Xatolik yuz berdi!", "error");
        }
    } catch (e) {
        showToast("Aloqa xatosi!", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = oldText;
    }
}

// ------ DOCTOR: VIEW PATIENT HISTORY ------
let docHistoryRecords = [];
let docHistoryLabs = [];

async function openDocPatientHistoryModal(patientId, patientName, patientPhone) {
    document.getElementById("doc-history-patient-name").innerText = patientName;
    document.getElementById("doc-history-patient-phone").innerHTML = `<i class="fa-solid fa-phone"></i> ${patientPhone}`;
    
    // Reset tab and container views
    switchDocHistoryTab('records');

    const recordsContainer = document.getElementById("doc-history-records-container");
    const labsContainer = document.getElementById("doc-history-labs-container");
    recordsContainer.innerHTML = '<div class="text-center py-4"><i class="fa-solid fa-spinner fa-spin" style="color:var(--accent);"></i></div>';
    labsContainer.innerHTML = '<div class="text-center py-4"><i class="fa-solid fa-spinner fa-spin" style="color:var(--accent);"></i></div>';

    document.getElementById("doc-history-modal").classList.remove("hidden");

    try {
        // Fetch records
        const recRes = await fetch(`/api/patients/${patientId}/records`);
        docHistoryRecords = recRes.ok ? await recRes.json() : [];
        
        // Fetch labs
        const labRes = await fetch(`/api/patients/${patientId}/labs`);
        docHistoryLabs = labRes.ok ? await labRes.json() : [];

        renderDocHistoryRecords();
        renderDocHistoryLabs();
    } catch (e) {
        recordsContainer.innerHTML = '<div class="text-center py-4">Tarixni yuklashda xatolik.</div>';
    }
}

function closeDocHistoryModal() {
    document.getElementById("doc-history-modal").classList.add("hidden");
}

function switchDocHistoryTab(tabType) {
    if (tabType === 'records') {
        document.getElementById("btn-doc-emr-records").classList.add("active");
        document.getElementById("btn-doc-emr-labs").classList.remove("active");
        document.getElementById("doc-history-records-container").classList.remove("hidden");
        document.getElementById("doc-history-labs-container").classList.add("hidden");
    } else {
        document.getElementById("btn-doc-emr-records").classList.remove("active");
        document.getElementById("btn-doc-emr-labs").classList.add("active");
        document.getElementById("doc-history-records-container").classList.add("hidden");
        document.getElementById("doc-history-labs-container").classList.remove("hidden");
    }
}

function renderDocHistoryRecords() {
    const container = document.getElementById("doc-history-records-container");
    if (!container) return;

    if (docHistoryRecords.length === 0) {
        container.innerHTML = '<div class="text-center py-4" style="color:var(--text-secondary);">Tashriflar tarixi mavjud emas.</div>';
        return;
    }

    container.innerHTML = "";
    docHistoryRecords.forEach(r => {
        const item = document.createElement("div");
        item.className = "emr-record-item";
        item.style.padding = "10px; background: rgba(255,255,255,0.03); border-radius: 8px; margin: 8px 0; border: 1px solid rgba(255,255,255,0.05);";
        item.innerHTML = `
            <div class="emr-meta" style="display:flex; justify-content:space-between; margin-bottom: 6px; font-size: 0.8rem; color: var(--text-secondary);">
                <span class="emr-date"><i class="fa-solid fa-calendar-day"></i> ${r.visit_date}</span>
                <span class="emr-doc"><i class="fa-solid fa-user-doctor"></i> ${r.doctor_name}</span>
            </div>
            <div class="emr-content" style="font-size: 0.9rem; color: white;">
                <p style="margin: 0 0 4px 0;"><strong>Tashxis (Diagnoz):</strong> ${r.diagnosis}</p>
                ${r.prescription ? `<p style="margin: 0;"><strong>Tavsiyalar:</strong> ${r.prescription}</p>` : ""}
            </div>
        `;
        container.appendChild(item);
    });
}

function renderDocHistoryLabs() {
    const container = document.getElementById("doc-history-labs-container");
    if (!container) return;

    if (docHistoryLabs.length === 0) {
        container.innerHTML = '<div class="text-center py-4" style="color:var(--text-secondary);">Tahlil natijalari yuklanmagan.</div>';
        return;
    }

    container.innerHTML = "";
    docHistoryLabs.forEach(l => {
        const item = document.createElement("div");
        item.className = "emr-record-item";
        item.style.padding = "10px; background: rgba(255,255,255,0.03); border-radius: 8px; margin: 8px 0; border: 1px solid rgba(255,255,255,0.05);";
        item.innerHTML = `
            <div class="emr-meta" style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 6px;">
                <span class="emr-date"><i class="fa-solid fa-clock"></i> ${l.uploaded_at}</span>
            </div>
            <div class="emr-content" style="font-size: 0.9rem; color: white;">
                <p style="margin: 0 0 6px 0;"><strong>Tahlil nomi:</strong> ${l.test_name}</p>
                <a href="${l.file_path}" target="_blank" class="pharmacy-partner-btn" style="margin-top: 4px; width: auto; display: inline-flex; text-decoration: none;">
                    <i class="fa-solid fa-file-pdf"></i> Tahlilni ko'rish (Hujjat)
                </a>
            </div>
        `;
        container.appendChild(item);
    });
}

// ------ ADMIN: DOCTORS TELEGRAM ID LINKING ------
async function loadDoctorsLinkList() {
    const container = document.getElementById("admin-doctors-link-list");
    if (!container) return;

    try {
        container.innerHTML = '<div class="text-center py-2"><i class="fa-solid fa-spinner fa-spin" style="color:var(--accent);"></i> Yuklanmoqda...</div>';
        const res = await fetch("/api/doctors/all");
        if (!res.ok) throw new Error();
        const doctors = await res.json();

        if (doctors.length === 0) {
            container.innerHTML = '<p style="color:var(--text-secondary); font-size:12px;">Shifokorlar ro\'yxati bo\'sh.</p>';
            return;
        }

        container.innerHTML = "";
        doctors.forEach(doc => {
            const row = document.createElement("div");
            row.style = "display:flex; align-items:center; gap:10px; background:rgba(255,255,255,0.03); padding:8px 12px; border-radius:10px; border:1px solid rgba(255,255,255,0.05);";
            row.innerHTML = `
                <div style="flex:1;">
                    <div style="font-weight:600; font-size:0.9rem; color:white;">${doc.name}</div>
                    <div style="font-size:0.75rem; color:var(--text-secondary);">${doc.specialty || 'Shifokor'}</div>
                </div>
                <div style="display:flex; align-items:center; gap:6px;">
                    <input type="number" id="doc-link-chat-id-${doc.id}" value="${doc.chat_id || ''}" placeholder="Telegram ID" style="width:110px; padding:6px 10px; border-radius:8px; border:1px solid rgba(255,255,255,0.2); background:rgba(0,0,0,0.2); color:white; font-size:0.85rem;">
                    <button class="btn-primary" onclick="saveDoctorChatId(${doc.id}, '${doc.name.replace(/'/g, "\\'")}')" style="padding:6px 12px; font-size:0.8rem; width:auto; border-radius:8px; white-space:nowrap;">Saqlash</button>
                </div>
            `;
            container.appendChild(row);
        });
    } catch (e) {
        container.innerHTML = '<p style="color:var(--red); font-size:12px;">Yuklashda xatolik yuz berdi.</p>';
    }
}

async function saveDoctorChatId(doctorId, name) {
    const input = document.getElementById(`doc-link-chat-id-${doctorId}`);
    const chatIdVal = input.value.trim();
    const chatId = chatIdVal ? parseInt(chatIdVal) : null;

    try {
        const res = await fetch("/api/doctors/update-chat-id", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doctor_id: doctorId, chat_id: chatId })
        });
        if (res.ok) {
            showToast(`${name} uchun Telegram ID saqlandi!`, "success");
            loadDoctorsLinkList();
        } else {
            showToast("Saqlashda xatolik yuz berdi!", "error");
        }
    } catch (e) {
        showToast("Aloqa xatosi!", "error");
    }
}


