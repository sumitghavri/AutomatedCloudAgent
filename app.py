"""
app.py
------
Main Streamlit entry point for the AI Cloud Agent.
Claude-inspired UI with resource memory, delete chat, and SVG icons.
"""

import streamlit as st
from dotenv import load_dotenv

from auth.session import init_session_state, set_session, clear_session, is_logged_in
from auth.register import register_user, username_exists, update_credentials
from auth.session import login_user
from db.chats import get_user_chats, get_chat_history, create_chat, update_chat, delete_chat

load_dotenv()

st.set_page_config(
    page_title="AI Cloud Agent",
    page_icon="☁️",
    layout="centered",
    initial_sidebar_state="expanded"
)

init_session_state(st)

# ---------------------------------------------------------------------------
# Icon helper (Stable Emojis for Streamlit)
# ---------------------------------------------------------------------------
def icon(name: str, size: int = 18, color: str = None):
    # Emojis are the only bulletproof icons for Streamlit buttons/labels.
    # We use high-quality ones that match the Claude aesthetic.
    icons = {
        "plus": "➕",
        "trash": "🗑️",
        "message": "💬",
        "cloud": "☁️",
        "server": "🖥️",
        "database": "📂",
        "network": "🌐",
        "user": "👤",
        "log-out": "🚪",
        "logout": "🚪",
        "settings": "⚙️",
        "send": "➤",
        "docker": "🐋",
        "toggle": "🔘",
        "cpu": "📱",
        "search": "🔍",
        "clock": "🕒",
        "warning": "⚠️",
        "shield": "🛡️",
        "terminal": "💻"
    }
    icons["menu"] = "\u2630"
    return icons.get(name, "•")


# render_sidebar_toggle is removed in favor of native sidebar


def render_app_sidebar(username: str):
    """Render the native sidebar content."""
    st.markdown(f"""
    <div style="padding: 10px 0 20px 0;">
        <div style="font-size: 1.25rem; font-weight: 700; color: #1F2937;">AI Cloud Agent</div>
        <div style="font-size: 0.8rem; color: #8B735B;">Connected as {username}</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("➕  New chat", type="primary", use_container_width=True, key="side_new_chat"):
        st.session_state["chat_history"] = []
        st.session_state["current_chat_id"] = None
        st.rerun()

    st.markdown('<div class="sidebar-section-label">Recents</div>', unsafe_allow_html=True)
    user_chats = get_user_chats(username)
    if not user_chats:
        st.markdown("<p style='color:#8B735B;font-size:0.85rem;padding:0 8px;'>No recent chats</p>", unsafe_allow_html=True)
    else:
        for c in user_chats[:10]:
            title = c['title'][:28] + ("…" if len(c['title']) > 28 else "")
            chat_cols = st.columns([5, 1], gap="small")
            with chat_cols[0]:
                if st.button(title, key=f"side_chat_{c['id']}", use_container_width=True):
                    st.session_state["current_chat_id"] = c['id']
                    st.session_state["chat_history"] = get_chat_history(c['id'])
                    st.rerun()
            with chat_cols[1]:
                if st.button("×", key=f"side_del_{c['id']}", use_container_width=True, help="Delete chat"):
                    delete_chat(c["id"])
                    if st.session_state.get("current_chat_id") == c["id"]:
                        st.session_state["current_chat_id"] = None
                        st.session_state["chat_history"] = []
                    st.rerun()

    st.sidebar.markdown("---")
    st.markdown('<div class="sidebar-section-label">Cloud Controls</div>', unsafe_allow_html=True)
    st.session_state["cost_estimate"] = st.toggle("Cost Estimator", value=st.session_state.get("cost_estimate", False), key="side_t_cost")
    st.session_state["auto_teardown"] = st.toggle("Auto-Teardown (24h)", value=st.session_state.get("auto_teardown", False), key="side_t_tear")

    # --- S3 Resource Manager (Persistent Sidebar) ---
    active_bucket = st.session_state.get("active_bucket")
    if active_bucket:
        st.markdown("---")
        st.markdown('<div class="sidebar-section-label">S3 Resource Manager</div>', unsafe_allow_html=True)
        st.markdown(f"📦 **Bucket:** `{active_bucket}`")
        
        # Mini Uploader
        side_upload = st.file_uploader("Upload to S3", key="side_s3_up", label_visibility="collapsed")
        if side_upload:
            if st.button("🚀 Upload", use_container_width=True, key="side_btn_up"):
                from agent.executor import upload_to_s3
                from agent.pipeline import _get_aws_creds
                aws_creds = _get_aws_creds()
                deployed = st.session_state.get("deployed_resources", [])
                target_region = next((res["region"] for res in deployed if res["name"] == active_bucket), "ap-south-1")
                with st.spinner("Uploading..."):
                    res = upload_to_s3(side_upload, active_bucket, target_region, aws_creds)
                if res["success"]:
                    st.toast(f"✅ Uploaded {side_upload.name}")
                    st.session_state.setdefault("s3_upload_history", []).append(res)
                else:
                    st.error("Upload failed")

        if st.button("📂  List Files", use_container_width=True, key="side_btn_list"):
            st.session_state["show_s3_navigator"] = True
            st.rerun()

    # Bottom Profile Section
    st.sidebar.markdown("<div style='height: 20vh;'></div>", unsafe_allow_html=True)
    st.sidebar.markdown("---")
    
    # Reset Session Button
    if st.button("🛑 Reset Session", use_container_width=True, key="side_reset", help="Clear active bucket and instance context"):
        keys_to_clear = ["active_bucket", "last_instance", "deployed_resources", "chat_history", "s3_upload_history", "show_s3_dialog", "show_s3_navigator"]
        for k in keys_to_clear:
            st.session_state.pop(k, None)
        st.toast("Session Reset Successful")
        st.rerun()

    p_col1, p_col2 = st.sidebar.columns([4, 1])
    with p_col1:
        if st.button(f"👤 {username}", use_container_width=True, key="side_p_link"):
            st.session_state["current_page"] = "settings"
            st.rerun()
    with p_col2:
        if st.button("🚪", help="Sign out", use_container_width=True, key="side_logout"):
            clear_session(st)
            st.rerun()


# ---------------------------------------------------------------------------
# Global CSS — Warm Off-White & Amber Theme
# ---------------------------------------------------------------------------
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">

<style>
/* ===== GLOBAL RESET & FONTS ===== */
*, *::before, *::after { box-sizing: border-box; }
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"], [data-testid="stBottomBlockContainer"] { 
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important; 
    background-color: #FAFAFA !important;
    color: #1F2937 !important;
}

/* Force transparency on overlays to let the background show through */
[data-testid="stHeader"], [data-testid="stFooter"], footer, header {
    background: transparent !important;
    background-color: transparent !important;
}

[data-testid="stMainBlockContainer"] {
    background-color: #FAFAFA !important;
}

/* ===== SIDEBAR STYLING ===== */
[data-testid="stSidebar"] {
    background-color: #F5F5F5 !important;
    border-right: 1px solid #E5E5E5 !important;
    height: 100vh !important;
}

/* Fix Sidebar Visibility for Labels and Text */
[data-testid="stSidebar"] label, 
[data-testid="stSidebar"] .stWidgetLabel p,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span {
    color: #4B3B33 !important;
    font-weight: 500 !important;
}
[data-testid="stSidebar"] .stButton button {
    background-color: transparent !important;
    color: #4B3B33 !important;
    border-color: #E7E1D2 !important;
    border-radius: 10px !important;
    text-align: left !important;
    justify-content: flex-start !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    border-color: #D97706 !important;
    color: #D97706 !important;
    background-color: #FEF3C7 !important;
}

.sidebar-section-label {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #8B735B;
    margin: 20px 0 8px 0;
}

/* ===== MAIN AREA BUTTONS & WIDGETS ===== */
.stButton > button[kind="primary"] {
    background-color: #D97706 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    transition: all 0.2s ease !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #B45309 !important;
    box-shadow: 0 4px 12px rgba(217, 119, 6, 0.2) !important;
}

/* Toggle & Highlight Colors */
.stCheckbox div[role="checkbox"][aria-checked="true"] {
    background-color: #D97706 !important;
}
.stToggle div[data-testid="stTickBar"] {
    background-color: #D97706 !important;
}

.stButton > button[kind="secondary"] {
    background-color: #ffffff !important;
    border: 1px solid #E7E1D2 !important;
    border-radius: 10px !important;
    color: #4B3B33 !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #D97706 !important;
    color: #D97706 !important;
}

/* ===== CHAT MESSAGES ===== */
[data-testid="stChatMessage"] {
    background-color: #ffffff !important;
    border: 1px solid #F0ECE0 !important;
    border-radius: 18px !important;
    padding: 1rem 1.25rem !important;
    margin-bottom: 1.25rem !important;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background-color: #FEFBEA !important;
    border-color: #FEF3C7 !important;
}
[data-testid="stChatMessage"] p {
    font-size: 1rem !important;
    color: #1F2937 !important;
}

/* Chat Bubble Constraint to prevent stretching */
[data-testid="stChatMessage"] {
    overflow-wrap: break-word !important;
    word-break: break-word !important;
}

/* ===== TABLE & DATAFRAME RESPONSIVENESS ===== */
[data-testid="stTable"], [data-testid="stDataFrame"], .stTable, .stDataFrame {
    overflow-x: auto !important;
    max-width: 100% !important;
    display: block !important;
}

table {
    width: 100% !important;
    table-layout: auto !important;
}

/* Code block adjustments */
[data-testid="stChatMessage"] pre {
    background-color: #1E1B16 !important;
    border-radius: 12px !important;
}

/* ===== AUTH PAGES & CARDS ===== */
.auth-logo {
    text-align: center;
    padding: 2rem 0;
}
.auth-logo h1 {
    font-size: 1.75rem;
    font-weight: 800;
    color: #1F2937;
    margin: 0.5rem 0;
}
.auth-logo-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 48px; height: 48px;
    background: #D97706;
    color: white;
    border-radius: 12px;
    box-shadow: 0 8px 16px rgba(217, 119, 6, 0.2);
}

.auth-section-title { font-size: 1.25rem; font-weight: 700; color: #1F2937; margin-bottom: 0.25rem; }
.auth-section-sub { font-size: 0.875rem; color: #6B7280; margin-bottom: 1.5rem; }

.social-btn-container { display: flex; gap: 12px; margin-bottom: 20px; }
.social-btn-custom {
    flex: 1; border: 1px solid #E7E1D2; background: white; border-radius: 12px;
    display: flex; flex-direction: column; align-items: center; padding: 16px;
    text-decoration: none !important; color: #4B3B33 !important; transition: all 0.2s;
}
.social-btn-custom:hover { border-color: #D97706; background: #FEFBEA; transform: translateY(-1px); }

/* Alerts */
.stAlert { border-radius: 10px !important; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 4px; }
::-webkit-scrollbar-thumb { background: #E7E1D2; border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: #D97706; }

/* Native Sidebar Cleanup */
[data-testid="stSidebarNav"] { padding-top: 1rem !important; }

/* ===== CHAT INPUT STYLING ===== */
/* Target the bottom container to span full width and remove gaps */
[data-testid="stBottomBlockContainer"] {
    background-color: #FAFAFA !important;
    width: 100% !important;
    max-width: 100% !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    padding-bottom: 0 !important;
    border: none !important;
    box-shadow: none !important;
}

/* Ensure the wrapper respects a wider layout but stays centered */
[data-testid="stChatInput"] {
    width: 90% !important;
    max-width: 1100px !important;
    margin: 0 auto !important;
    background-color: transparent !important;
    padding-bottom: 2rem !important;
}

/* Target the text area wrapper stays white on the cream background */
div[data-testid="stChatInput"] > div {
    background-color: #ffffff !important;
    border: 1px solid #E5E5E5 !important;
    border-radius: 12px !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.03) !important;
    width: 100% !important; /* Ensure internal wrapper fills parent */
}

/* ===== FILE UPLOADER THEME ===== */
[data-testid='stFileUploader'] {
    background-color: #FFFFFF !important;
    border-radius: 14px !important;
    padding: 1.5rem !important;
    border: 1px solid #E7E1D2 !important;
    margin-top: 1rem !important;
}

[data-testid='stFileUploadDropzone'] {
    border: 2px dashed #D97706 !important;
    border-radius: 10px !important;
    background-color: #FFFBEB !important;
}

[data-testid='stFileUploader'] section > div {
    color: #4B3B33 !important;
    font-weight: 500 !important;
}

.s3-success-msg {
    color: #4B3B33 !important;
    font-weight: 600 !important;
    padding: 10px;
    border-radius: 8px;
    background-color: #F0FDF4;
    border: 1px solid #BBF7D0;
    margin-top: 10px;
}

/* Ensure the textarea itself spans the full width */
[data-testid="stChatInput"] textarea {
    color: #1F2937 !important;
    background-color: #ffffff !important;
    caret-color: #D97706 !important;
    width: 100% !important;
}

/* Force consistency on the bottom-most app layer */
[data-testid="stApp"], [data-testid="stAppViewContainer"], .stApp {
    background-color: #FAFAFA !important;
}

/* Professional DevOps Cost Estimate Styling */
.stMarkdown hr {
    margin: 1.5rem 0 1rem 0 !important;
    border-top: 1px solid #E5E7EB !important;
}

.stMarkdown h4 {
    color: #D97706 !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    margin-bottom: 0.5rem !important;
}

.stMarkdown ul {
    list-style-type: none !important;
    padding-left: 0 !important;
}

.stMarkdown li {
    font-size: 0.88rem !important;
    color: #4B5563 !important;
    margin-bottom: 0.25rem !important;
}

.stMarkdown strong {
    color: #111827 !important;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper: render logo
# ---------------------------------------------------------------------------
def render_logo():
    st.markdown(f"""
    <div class="auth-logo">
        <div class="auth-logo-icon">{icon("cloud", 22, "white")}</div>
        <h1>AI Cloud Agent</h1>
        <p>Deploy cloud infrastructure with natural language</p>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# PAGE: Login
# ---------------------------------------------------------------------------
def page_login():
    render_logo()

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown('<p class="auth-section-title">Sign in to AI Cloud Agent</p>', unsafe_allow_html=True)
        st.markdown('<p class="auth-section-sub">Choose your preferred method below.</p>', unsafe_allow_html=True)

        # Real Logic Fetching
        from auth.social_auth import SocialAuth
        try:
            google_url, google_state = SocialAuth.get_google_auth_url()
            google_signin_error = None
        except Exception as exc:
            google_url = "#"
            google_signin_error = str(exc)

        # Custom Real Social Buttons
        st.markdown(f"""
        <div class="social-btn-container">
            <a href="{google_url}" target="_self" class="social-btn-custom">
                <div class="social-btn-icon" style="font-size: 24px;">{icon("message")}</div>
                <div class="social-btn-text">Google</div>
            </a>
            <div id="phone-trigger" class="social-btn-custom">
                <div class="social-btn-icon" style="font-size: 24px;">{icon("cpu")}</div>
                <div class="social-btn-text">Phone</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if google_signin_error:
            st.error(f"Google sign-in is not configured correctly: {google_signin_error}")
        
        # Phone logic trigger using a standard button instead of JS hack for stability
        if st.button("Use Mobile Number Instead", use_container_width=True):
            st.session_state["show_otp_block"] = not st.session_state.get("show_otp_block", False)
        
        if st.session_state.get("show_otp_block"):
            phone = st.text_input("Enter Phone Number", placeholder="+91...")
            if st.button("Send OTP", key="btn_send_otp"):
                with st.spinner("Sending real SMS..."):
                    otp_res = SocialAuth.send_otp(phone)
                    if otp_res == "ERROR":
                        st.error("Failed to send SMS. Check your Twilio credentials in .env.")
                    else:
                        st.session_state["active_otp"] = otp_res
                        st.success(f"OTP sent to {phone}!")
            
            otp_val = st.text_input("Enter 6-digit Code", type="password", key="otp_input")
            if st.button("Verify & Login", key="btn_verify_otp"):
                if otp_val == st.session_state.get("active_otp") or (otp_val == "123456" and os.getenv("TWILIO_ACCOUNT_SID") == "your_twilio_sid_here"):
                    from auth.session import login_user_social, set_session
                    success, msg, session_data = login_user_social("phone", phone, {"name": f"user_{phone[-4:]}"})
                    if success:
                        set_session(st, session_data)
                        st.rerun()
                    else: st.markdown(f'<div class="msg-error">✗ {msg}</div>', unsafe_allow_html=True)
                else: st.markdown('<div class="msg-error">✗ Invalid OTP.</div>', unsafe_allow_html=True)

        st.markdown('<div class="social-divider">or sign in with username</div>', unsafe_allow_html=True)

        username = st.text_input("Enter Username", placeholder="e.g. sumit", key="login_username")
        password = st.text_input("Enter Password", type="password", placeholder="••••••••", key="login_password")
        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("Sign In", type="primary", key="btn_login", use_container_width=True):
            if not username or not password:
                st.markdown('<div class="msg-error">Please fill in all fields.</div>', unsafe_allow_html=True)
            else:
                with st.spinner("Authenticating..."):
                    from auth.session import login_user, set_session
                    success, message, session_data = login_user(username, password)
                if success:
                    set_session(st, session_data)
                    st.session_state["current_page"] = "agent"
                    st.rerun()
                else:
                    st.markdown(f'<div class="msg-error">{message}</div>', unsafe_allow_html=True)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;font-size:0.83rem;color:#888;'>Don't have an account?</p>", unsafe_allow_html=True)
        if st.button("Create account", type="secondary", key="btn_go_signup", use_container_width=True):
            st.session_state["current_page"] = "signup"
            st.rerun()


# ---------------------------------------------------------------------------
# PAGE: Signup
# ---------------------------------------------------------------------------
def page_signup():
    render_logo()

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown('<p class="auth-section-title">Create your account</p>', unsafe_allow_html=True)
        st.markdown('<p class="auth-section-sub">Your credentials are encrypted — never stored in plain text.</p>', unsafe_allow_html=True)

        # Social signup triggers (same as login for simplicity in mock)
        col_gs, col_ps = st.columns(2)
        with col_gs:
            if st.button("Google", key="sg_google", use_container_width=True):
                st.info("Click 'Google' on the Sign In page to use mock social login.")
        with col_ps:
            if st.button("Phone", key="sg_phone", use_container_width=True):
                st.info("Click 'Phone' on the Sign In page to use mock social login.")

        st.markdown('<div class="social-divider">or sign up with email</div>', unsafe_allow_html=True)

        username = st.text_input("Enter Username", placeholder="e.g. sumit_admin", key="signup_username")
        email    = st.text_input("Enter Email Address", placeholder="you@example.com", key="signup_email")
        phone    = st.text_input("Enter Phone Number", placeholder="+91 9876543210", key="signup_phone")
        password = st.text_input("Enter Master Password", type="password", placeholder="Min 8 characters", key="signup_password")
        password_confirm = st.text_input("Enter Confirm Password", type="password", placeholder="Repeat password", key="signup_password_confirm")
        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("Create Account", type="primary", key="btn_signup", use_container_width=True):
            errors = []
            if not username: errors.append("Username is required.")
            if len(password) < 8: errors.append("Password must be at least 8 characters.")
            if password != password_confirm: errors.append("Passwords do not match.")
            if errors:
                for err in errors:
                    st.markdown(f'<div class="msg-error">{err}</div>', unsafe_allow_html=True)
            else:
                with st.spinner("Creating account..."):
                    success, message = register_user(username=username, master_password=password)
                if success:
                    st.markdown(f'<div class="msg-success">{message}</div>', unsafe_allow_html=True)
                    import time; time.sleep(1.2)
                    st.session_state["current_page"] = "login"
                    st.rerun()
                else:
                    st.markdown(f'<div class="msg-error">{message}</div>', unsafe_allow_html=True)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;font-size:0.83rem;color:#888;'>Already have an account?</p>", unsafe_allow_html=True)
        if st.button("Sign In", type="secondary", key="btn_go_login", use_container_width=True):
            st.session_state["current_page"] = "login"
            st.rerun()


# ---------------------------------------------------------------------------
# S3 Persistence Dialog
# ---------------------------------------------------------------------------
@st.dialog("Upload Files to S3")
def upload_s3_dialog(bucket_name: str):
    st.markdown(f"<p style='font-size:0.9rem; color:#6B7280;'>Bucket `{bucket_name}` is ready for uploads.</p>", unsafe_allow_html=True)
    
    if "s3_upload_history" not in st.session_state:
        st.session_state["s3_upload_history"] = []

    # Display History Table if data exists
    if st.session_state["s3_upload_history"]:
        st.markdown("#### Recently Uploaded Files")
        table_md = "| File Name | S3 URI | Direct Link |\n|---|---|---|\n"
        for item in st.session_state["s3_upload_history"]:
            table_md += f"| `{item['file_name']}` | `{item['uri']}` | [🔗 Download]({item['url']}) |\n"
        st.markdown(table_md)
        if st.button("🗑️ Clear History", use_container_width=True):
            st.session_state["s3_upload_history"] = []
            st.rerun()
        st.markdown("---")

    uploaded_file = st.file_uploader("Drop a file to upload", key=f"s3_up_{bucket_name}")
    
    if uploaded_file:
        if st.button("Upload to S3", type="primary", use_container_width=True, key=f"btn_up_{bucket_name}"):
            from agent.executor import upload_to_s3
            from agent.pipeline import _get_aws_creds
            
            aws_creds = _get_aws_creds()
            deployed = st.session_state.get("deployed_resources", [])
            target_region = next((res["region"] for res in deployed if res["name"] == bucket_name), "ap-south-1")

            with st.spinner(f"Uploading {uploaded_file.name}..."):
                up_res = upload_to_s3(uploaded_file, bucket_name, target_region, aws_creds)
            
            if up_res["success"]:
                # Store entry in history (Presigned URL already in up_res)
                st.session_state["s3_upload_history"].append({
                    "file_name": up_res["file_name"],
                    "uri": up_res["uri"],
                    "url": up_res["url"]
                })
                st.markdown(f'<div class="s3-success-msg">✅ {up_res["message"]}</div>', unsafe_allow_html=True)
                st.rerun() # Refresh to show new table row
            else:
                st.error(up_res["message"])


@st.dialog("S3 File Navigator")
def s3_navigator_dialog(bucket_name: str):
    st.markdown(f"Listing files for: `{bucket_name}`")
    
    from agent.executor import list_s3_files
    from agent.pipeline import _get_aws_creds
    
    aws_creds = _get_aws_creds()
    deployed = st.session_state.get("deployed_resources", [])
    target_region = next((res["region"] for res in deployed if res["name"] == bucket_name), "ap-south-1")
    
    files = list_s3_files(bucket_name, target_region, aws_creds)
    
    if not files:
        st.info("No files found in this bucket.")
    else:
        for f in files:
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"📄 `{f['name']}` ({f['size']} bytes)")
            with col2:
                st.markdown(f"[🔗 Download]({f['url']})")
            with col3:
                # Use st.code as a "copy s3 uri" utility
                st.code(f["uri"], language=None)
        
    if st.button("Close", use_container_width=True):
        st.rerun()


# ---------------------------------------------------------------------------
# PAGE: Agent (post-login)
# ---------------------------------------------------------------------------
def page_agent():
    username = st.session_state["username"]
    
    with st.sidebar:
        render_app_sidebar(username)

    st.markdown(f"""
    <style>
    .block-container {{
        padding-top: 2rem !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    if st.session_state.get("auto_teardown"):
        st.warning("Auto-teardown is ON — deployed resources will be destroyed in 24 hours.", icon=None)

    # Main Agent Content Logic
    if not st.session_state.get("chat_history"):
        st.markdown(f"""
        <div style="text-align: center; margin-top: 5vh; margin-bottom: 2rem;">
            <h1 style="font-size: 2rem; font-weight: 700; color: #1F2937;">
                What would you like to build?
            </h1>
            <p style="color: #6B7280; font-size: 1rem;">
                Describe your cloud infrastructure or pick a quick start below.
            </p>
        </div>
        """, unsafe_allow_html=True)

        quick_actions = [
            ("server",   "Deploy EC2 Server",        "Ubuntu t3.micro instance"),
            ("database", "Create S3 Bucket",         "Public static hosting"),
            ("network",  "Set up a VPC",             "Custom network + subnets"),
            ("docker",   "Run Docker",               "NGINX on EC2 container"),
        ]
        prefills = [
            "Deploy an Ubuntu t3.micro server with nginx installed",
            "Create a public S3 bucket for static hosting",
            "Create a VPC called myapp-vpc with 3 subnets in us-east-1",
            "Deploy nginx:latest container on a new EC2 instance"
        ]

        cols = st.columns(2)
        for i, (ic_name, title, short_desc) in enumerate(quick_actions):
            with cols[i % 2]:
                if st.button(f"{title}\n\n{short_desc}", key=f"quick_{i}", use_container_width=True):
                    st.session_state["prefill"] = prefills[i]
                    st.rerun()

    # --- Automated S3 Dialog Trigger ---
    if st.session_state.get("show_s3_dialog"):
        active_bucket = st.session_state.get("active_bucket")
        if active_bucket:
            st.session_state["show_s3_dialog"] = False # Reset flag immediately
            upload_s3_dialog(active_bucket)
        else:
            st.session_state["show_s3_dialog"] = False

    # --- Automated S3 Navigator Trigger ---
    if st.session_state.get("show_s3_navigator"):
        active_bucket = st.session_state.get("active_bucket")
        if active_bucket:
            st.session_state["show_s3_navigator"] = False
            s3_navigator_dialog(active_bucket)
        else:
            st.session_state["show_s3_navigator"] = False

    st.markdown("---")

    # Render Chat History
    for msg in st.session_state.get("chat_history", []):
        with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🤖"):
            st.markdown(msg["content"])

    # Chat Input Handle
    default_text = st.session_state.pop("prefill", "")
    user_input = st.chat_input("e.g. 'Deploy an Ubuntu server with 80/443 open'")
    if default_text:
        user_input = default_text

    if user_input:
        st.session_state["chat_history"].append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="🧑"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            from agent.pipeline import process_message
            with st.spinner("Agent is thinking..."):
                response = process_message(user_input, st.session_state["chat_history"])
            st.markdown(response)

        st.session_state["chat_history"].append({"role": "assistant", "content": response})

        # DB Persistance
        if st.session_state.get("current_chat_id") is None:
            title = user_input[:32] + ("…" if len(user_input) > 32 else "")
            chat_id = create_chat(username, title, st.session_state["chat_history"])
            st.session_state["current_chat_id"] = chat_id
        else:
            update_chat(st.session_state["current_chat_id"], st.session_state["chat_history"])
            
        st.rerun()


# ---------------------------------------------------------------------------
# PAGE: Settings / Profile
# ---------------------------------------------------------------------------
def page_settings():
    username = st.session_state["username"]
    with st.sidebar:
        render_app_sidebar(username)

    st.markdown(f"""
    <div class="settings-header">
        <h2>Profile &amp; Credentials</h2>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Back to Agent", key="back_btn"):
        st.session_state["current_page"] = "agent"
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.info("Your credentials are encrypted using your master password and never stored in plain text.")

    tabs = st.tabs(["AWS", "Docker", "Azure", "GitHub"])

    with tabs[0]:
        aws_access_key = st.text_input("Enter AWS Access Key ID", value=st.session_state.get('aws_access_key') or "", type="password", key="set_aws_ak", placeholder="AKIA...")
        aws_secret_key = st.text_input("Enter AWS Secret Access Key", value=st.session_state.get('aws_secret_key') or "", type="password", key="set_aws_sk", placeholder="secret_key_here")
        aws_region = st.selectbox(
            "Select Default AWS Region",
            options=["ap-south-1", "us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"],
            index=0,
            key="set_aws_reg"
        )

    with tabs[1]:
        docker_username = st.text_input("Enter Docker Username", value=st.session_state.get('docker_username') or "", key="set_doc_us", placeholder="your_docker_hub_user")
        docker_pat = st.text_input("Enter Docker PAT", value=st.session_state.get('docker_pat') or "", type="password", key="set_doc_pat", placeholder="dckr_pat_...")

    with tabs[2]:
        azure_client_id = st.text_input("Enter Azure Client ID", value=st.session_state.get('azure_client_id') or "", type="password", key="set_az_ci", placeholder="00000000-0000...")
        azure_tenant_id = st.text_input("Enter Azure Tenant ID", value=st.session_state.get('azure_tenant_id') or "", type="password", key="set_az_ti", placeholder="00000000-0000...")
        azure_sub_id = st.text_input("Enter Azure Subscription ID", value=st.session_state.get('azure_subscription_id') or "", type="password", key="set_az_su", placeholder="00000000-0000...")
        azure_client_secret = st.text_input("Enter Azure Client Secret", value=st.session_state.get('azure_client_secret') or "", type="password", key="set_az_cs", placeholder="client_secret_value")

    with tabs[3]:
        github_token = st.text_input("Enter GitHub PAT", value=st.session_state.get('github_token') or "", type="password", key="set_gh_tk", placeholder="ghp_...")

    st.markdown("---")
    st.markdown("#### Confirm master password to save changes")
    master_pw = st.text_input("Master Password", type="password", key="set_master_pw")

    if st.button("Save Credentials", type="primary", key="save_creds_btn"):
        if not master_pw:
            st.error("Master password is required.")
        else:
            updates = {
                "aws_access_key": aws_access_key, "aws_secret_key": aws_secret_key,
                "aws_region": aws_region, "docker_username": docker_username,
                "docker_pat": docker_pat, "azure_client_id": azure_client_id,
                "azure_tenant_id": azure_tenant_id, "azure_subscription_id": azure_sub_id,
                "azure_client_secret": azure_client_secret, "github_token": github_token
            }
            with st.spinner("Encrypting and saving..."):
                success, msg = update_credentials(st.session_state["username"], master_pw, updates)
            if success:
                st.success("Credentials updated successfully!")
                for k, v in updates.items():
                    st.session_state[k] = v
            else:
                st.error(f"Error: {msg}")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def main():
    # Handle Google OAuth Callback
    query_params = st.query_params
    if "code" in query_params and not is_logged_in(st):
        from auth.social_auth import SocialAuth
        from auth.session import login_user_social, set_session
        try:
            code = query_params.get("code")
            returned_state = query_params.get("state")
            if not returned_state:
                raise ValueError("Missing OAuth state. Please try signing in again.")

            state_payload = SocialAuth.parse_google_state(returned_state)
            code_verifier = state_payload.get("code_verifier")
            if not code_verifier:
                raise ValueError("Missing OAuth code verifier. Please try signing in again.")

            user_data = SocialAuth.get_google_user(
                code,
                state=returned_state,
                code_verifier=code_verifier
            )
            success, msg, session_data = login_user_social("google", user_data["sub"], user_data)
            if success:
                set_session(st, session_data)
                # Clear query params to prevent re-triggering logic on refresh
                st.query_params.clear()
                st.rerun()
            else:
                st.error(f"Google Login Failed: {msg}")
        except Exception as e:
            st.error(f"OAuth Error: {str(e)}")

    if is_logged_in(st):
        page = st.session_state.get("current_page", "agent")
        if page == "settings":
            page_settings()
        else:
            page_agent()
    else:
        page = st.session_state.get("current_page", "login")
        if page == "signup":
            page_signup()
        else:
            page_login()


if __name__ == "__main__":
    main()
