import os
import urllib.parse
from datetime import datetime
import pandas as pd
import streamlit as st
fr

st.set_page_config(
    page_title="Indore East Congregation - Field Service Portal",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 🛑 UI STYLING & WATERMARK REMOVAL
clean_ui_css = """
    <style>
    footer { display: none !important; visibility: hidden !important; }
    div[class*="viewerBadge"],
    div[class*="ProfileButton"],
    div[class*="StreamlitBranding"],
    div[class*="stAppDeployButton"],
    div[data-testid="stStatusWidget"],
    div[data-testid="stDecoration"],
    [data-testid="stAppViewerBadge"],
    .viewerBadge_container__1QSob,
    .viewerBadge_link__1S137,
    #root > div:first-child > div:nth-child(2) {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }
    div[data-testid="stCheckbox"] label {
        font-size: 1.25rem !important;
        font-weight: 700 !important;
        color: #1E3A8A !important;
        cursor: pointer !important;
    }
    div[data-testid="stCheckbox"] input[type="checkbox"] {
        transform: scale(1.3) !important;
        margin-right: 10px !important;
        cursor: pointer !important;
    }
    .receipt-box {
        border: 2px dashed #1E3A8A;
        border-radius: 10px;
        padding: 18px;
        background-color: #F0FDF4;
        margin-top: 15px;
    }
    </style>
"""
st.markdown(clean_ui_css, unsafe_allow_html=True)

# 🔒 CONFIDENTIAL PINS
OVERSEER_PIN = "1 Peter 5:2"
ADMIN_PIN = "2027"

# 📁 LOCAL BACKUP FILE
LOCAL_BACKUP = "service_reports_db.xlsx"

REGULAR_PIONEERS = [
    "Paul, Austin",
    "Paul, Pragati",
    "Khandare, Janki",
    "Khandare, Ishita",
    "Tirkey, Libnus",
    "Lalita, Merlin",
    "XaXa, Fabiola",
    "Susai Paul, Benita",
    "Kindo, Hilariyas",
]

# 📋 ROSTER WITH SISTER NATASHA MOHAN ADDED
ROSTER_DATA = {
    "Kingdom Hall (किंगडम हॉल)": [
        "Paul, Austin",
        "Paul, Pragati",
        "Borasi, Kiran",
        "Buddha, Lata",
        "Chuhan, Sushmita",
        "Khandare, Ishita",
        "Khandare, Janki",
        "Khakha, Anoop",
        "Mohan, Natasha",
        "Patel, Rosemary",
        "Peter, Vinod",
        "Peter, Sunita",
        "Raidas, Puran",
        "Raidas, Dasoda",
        "Soloman, Sawan",
        "Swami, Ajit",
        "Swami, Jennifer",
        "Swami, Steven",
        "Tirkey, Libnus",
        "Tirkey, Nirmala",
        "Tirkey, Mitchell",
        "Tirkey, Moses",
        "Topo, Ashrita",
    ],
    "Pushp Nagar (पुष्प नगर)": [
        "Oru, Deepak",
        "Oru, Seema",
        "Bharonda, Yash",
        "Gomes, Anju",
        "Hsieh, Josephine",
        "Khakha, Silvanus",
        "XaXa, Fabiola",
        "Lalita, Merlin",
        "Lartius, Issac",
        "Maida, Anugrah",
        "Maida, Vikrant",
        "Oru, Augustin",
        "Oru, Magdalene",
        "Oru, Neha",
        "Paul, Regina",
        "Susai Paul, Alwin",
        "Susai Paul, Benita",
        "Swami, Alpana",
        "Swami, Joel",
        "Topno, Diana",
        "Topno, Sara",
        "Vincent, Neil",
        "Vincent, Sapan",
        "Vinod, Vandita",
    ],
    "Scheme 78 (स्कीम 78)": [
        "Oru, Dheeraj",
        "Oru, Angelina",
        "Barnabas, Rajni",
        "Barnabas, Harshil",
        "Joel, John",
        "Kindo, Hilariyas",
        "Kindo, Sunita",
        "Kindo, Abhishek",
        "Lartius, Kenneth",
        "Lartius, Edrina",
        "Lartius, Neil",
        "Nunes, Emmanuel",
        "Ojha, Kusum",
        "Peter, Jerald",
        "Peter, Kiran",
        "Peter, Andrea",
        "Swami, Joshi",
        "Swami, Neeta",
        "Swami, Sharin",
        "Tiwari, Eva",
        "Yadav, Tanu",
    ],
}

MONTHS_BILINGUAL = [
    "August (अगस्त)",
    "September (सितंबर)",
    "October (अक्टूबर)",
    "November (नवंबर)",
    "December (दिसंबर)",
    "January (जनवरी)",
    "February (फ़रवरी)",
    "March (मार्च)",
    "April (अप्रैल)",
    "May (मई)",
    "June (जून)",
    "July (जुलाई)",
]

REQUIRED_COLS = [
    "Group",
    "Publisher",
    "Month",
    "Role",
    "Participated",
    "Hours",
    "Bible Studies",
    "Comments",
    "Submitted At",
]

current_m_idx = 0
cur_month_str = datetime.now().strftime("%B")
for idx, m_name in enumerate(MONTHS_BILINGUAL):
  if cur_month_str in m_name:
    current_m_idx = idx
    break


# ☁️ GOOGLE SHEETS DUAL-SYNC ENGINE
def get_connection():
  try:
    return st.connection("gsheets", type=GSheetsConnection)
  except Exception:
    return None


def load_data():
  conn = get_connection()
  if conn:
    try:
      df = conn.read(worksheet="Master_Database", ttl=5)
      if df is not None and not df.empty:
        for col in REQUIRED_COLS:
          if col not in df.columns:
            df[col] = ""
        return df[REQUIRED_COLS]
    except Exception:
      pass

  # Fallback to local
  if os.path.exists(LOCAL_BACKUP):
    try:
      df = pd.read_excel(LOCAL_BACKUP)
      for col in REQUIRED_COLS:
        if col not in df.columns:
          df[col] = ""
      return df[REQUIRED_COLS]
    except Exception:
      pass

  return pd.DataFrame(columns=REQUIRED_COLS)


def save_data(df):
  for col in REQUIRED_COLS:
    if col not in df.columns:
      df[col] = ""
  df = df[REQUIRED_COLS]

  # 1. Local backup save
  try:
    df.to_excel(LOCAL_BACKUP, index=False)
  except Exception:
    pass

  # 2. Cloud Google Sheet live save
  conn = get_connection()
  if conn:
    try:
      conn.update(worksheet="Master_Database", data=df)
    except Exception:
      pass


st.title("📖 इंदौर ईस्ट मंडली - क्षेत्र सेवा पोर्टल")
st.caption("Indore East Congregation - Field Service Report Portal")
st.markdown("---")

menu = st.sidebar.selectbox("मेन्यू / Menu Navigation", [
    "📝 रिपोर्ट जमा करें (Submit Report)",
    "📊 ग्रुप रिपोर्ट देखें (Overseers Only 🔒)",
    "🌟 रेगुलर पायनियर (Pioneers Special 🔒)",
    "⚙️ एडमिन एवं एक्सेल डाउनलोड (Admin & Export 🔒)",
])

# 1. PUBLISHERS & PIONEERS FORM
if menu == "📝 रिपोर्ट जमा करें (Submit Report)":
  st.header("📝 मासिक क्षेत्र सेवा रिपोर्ट / Monthly Report")

  col1, col2 = st.columns(2)
  with col1:
    selected_group = st.selectbox(
        "अपना ग्रुप चुनें / Select Group", list(ROSTER_DATA.keys())
    )
  with col2:
    selected_publisher = st.selectbox(
        "अपना नाम चुनें / Select Name", ROSTER_DATA[selected_group]
    )

  selected_month = st.selectbox(
      "महीना चुनें / Select Month", MONTHS_BILINGUAL, index=current_m_idx
  )

  is_regular_pioneer = selected_publisher in REGULAR_PIONEERS

  is_auxiliary = False
  if not is_regular_pioneer:
    is_auxiliary = st.checkbox(
        "🎗️ क्या आपने इस महीने सहायक पायनियर सेवा की? (Auxiliary Pioneer)",
        value=False,
    )
  else:
    st.info("🌟 आप रेगुलर पायनियर के रूप में दर्ज हैं (Regular Pioneer).")

  with st.form("report_form"):
    submitted_check = st.checkbox(
        "✔ क्या आपने इस महीने प्रचार सेवा में भाग लिया? (Participated in"
        " Ministry)",
        value=False,
    )
    st.markdown("---")

    hours = 0
    if is_regular_pioneer or is_auxiliary:
      hours = st.number_input(
          "प्रचार के कुल घंटे (Hours):",
          min_value=0,
          max_value=200,
          value=0,
          help="केवल पायनियरों के लिए",
      )

    bible_studies = st.number_input(
        "बाइबल अध्ययनों की संख्या (Bible Studies / B.S.):",
        min_value=0,
        max_value=30,
        value=0,
    )
    comments = st.text_area(
        "टिप्पणी / Remarks (बीमारी, विशेष परिस्थिति, या कोई अन्य जानकारी):"
    )

    submit_btn = st.form_submit_button("रिपोर्ट सबमिट करें (Submit Report)")

    if submit_btn:
      if not submitted_check and hours == 0 and bible_studies == 0:
        st.warning(
            "⚠️ कृपया पुष्टि करें कि आपने प्रचार में भाग लिया है या अपनी सही"
            " जानकारी भरें।"
        )
      else:
        role_label = (
            "Regular Pioneer"
            if is_regular_pioneer
            else ("Auxiliary Pioneer" if is_auxiliary else "Publisher")
        )
        raw_month = selected_month.split(" (")[0]
        submission_time = datetime.now().strftime("%d-%b-%Y %I:%M %p")

        df = load_data()

        already_exists = not df[
            (df["Publisher"] == selected_publisher)
            & (df["Month"] == raw_month)
        ].empty

        new_entry = {
            "Group": selected_group.split(" (")[0],
            "Publisher": selected_publisher,
            "Month": raw_month,
            "Role": role_label,
            "Participated": "Yes" if submitted_check else "No",
            "Hours": hours if (is_regular_pioneer or is_auxiliary) else "-",
            "Bible Studies": bible_studies,
            "Comments": comments,
            "Submitted At": submission_time,
        }

        # Safe update
        df = df[
            ~(
                (df["Publisher"] == selected_publisher)
                & (df["Month"] == raw_month)
            )
        ]
        df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
        save_data(df)

        if already_exists:
          st.info(
              "🔄 आपकी पहले से मौजूद रिपोर्ट को नए विवरण के साथ अपडेट कर दिया"
              " गया है।"
          )
        else:
          st.success("🎉 आपकी रिपोर्ट सफलतापूर्वक दर्ज हो गई है! धन्यवाद।")

        st.markdown(
            f"""
                <div class="receipt-box">
                    <h4 style="margin:0; color:#1E3A8A;">🧾 रिपोर्ट रसीद / Confirmation Slip</h4>
                    <hr style="margin:8px 0;">
                    <b>प्रचारक का नाम (Name):</b> {selected_publisher}<br>
                    <b>ग्रुप (Group):</b> {selected_group.split(" (")[0]}<br>
                    <b>महीना (Month):</b> {selected_month}<br>
                    <b>पद (Role):</b> {role_label}<br>
                    <b>प्रचार में भाग लिया:</b> {'हाँ (Yes)' if submitted_check else 'नहीं (No)'}<br>
                    <b>घंटे (Hours):</b> {hours if (is_regular_pioneer or is_auxiliary) else "N/A"}<br>
                    <b>बाइबल अध्ययन (B.S.):</b> {bible_studies}<br>
                    <b>दिनांक व समय:</b> {submission_time}
                </div>
                """,
            unsafe_allow_html=True,
        )

# 2. OVERSEERS SECTION
elif menu == "📊 ग्रुप रिपोर्ट देखें (Overseers Only 🔒)":
  st.header("📊 ग्रुप रिपोर्ट स्थिति / Group Reports Status")
  pin = st.text_input(
      "ग्रुप ओवरसियर पिन दर्ज करें (Enter PIN):", type="password"
  )

  if pin == OVERSEER_PIN or pin == ADMIN_PIN:
    st.success("पहुँच स्वीकृत ✔ (Access Granted)")

    col_btn, _ = st.columns([1, 4])
    with col_btn:
      if st.button("🔄 डेटा रीफ्रेश करें (Refresh Live Data)"):
        st.rerun()

    view_group = st.selectbox(
        "ग्रुप चुनें / Select Group", list(ROSTER_DATA.keys())
    )
    view_month = st.selectbox(
        "महीना चुनें / Select Month", MONTHS_BILINGUAL, index=current_m_idx
    )

    raw_group = view_group.split(" (")[0]
    raw_month = view_month.split(" (")[0]

    df = load_data()
    group_month_df = df[
        (df["Group"] == raw_group) & (df["Month"] == raw_month)
    ]

    all_group_publishers = ROSTER_DATA.get(view_group, [])
    submitted_publishers = (
        group_month_df["Publisher"].tolist()
        if not group_month_df.empty
        else []
    )
    missing_publishers = [
        pub for pub in all_group_publishers if pub not in submitted_publishers
    ]

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("कुल प्रचारक (Total)", len(all_group_publishers))
    col_m2.metric("रिपोर्ट प्राप्त हुई (Received)", len(submitted_publishers))
    col_m3.metric("रिपोर्ट बाकी है (Pending)", len(missing_publishers))

    st.markdown("---")
    tab1, tab2 = st.tabs([
        "✅ प्राप्त रिपोर्ट (Received Reports)",
        "⏳ बाकी रिपोर्ट (Pending Reports)",
    ])

    with tab1:
      if not group_month_df.empty:
        total_bs = pd.to_numeric(
            group_month_df["Bible Studies"], errors="coerce"
        ).sum()
        num_pioneers = group_month_df[
            group_month_df["Role"].isin(
                ["Regular Pioneer", "Auxiliary Pioneer"]
            )
        ].shape[0]

        st.caption(
            f"📈 **ग्रुप सारांश:** कुल बाइबल अध्ययन: **{int(total_bs)}** |"
            f" पायनियर रिपोर्ट: **{num_pioneers}**"
        )
        st.dataframe(group_month_df, use_container_width=True)
      else:
        st.info(f"{view_month} के लिए इस ग्रुप से अभी कोई रिपोर्ट नहीं आई है।")

    with tab2:
      if missing_publishers:
        st.warning(
            f"⚠️ **{view_group}** के इन भाई-बहनों की **{view_month}** की रिपोर्ट"
            " बाकी है:"
        )
        missing_df = pd.DataFrame(
            {"प्रचारक का नाम (Pending Publisher)": missing_publishers}
        )
        st.dataframe(missing_df, use_container_width=True)

        names_bullet = "\n".join([f"• {name}" for name in missing_publishers])
        reminder_msg = (
            "प्यारे भाईयों और बहनों, प्यार भरा नमस्कार। कृपया ध्यान दें कि"
            f" *{view_month}* की क्षेत्र सेवा रिपोर्ट इन भाई-बहनों की आना बाकी"
            f" है:\n\n{names_bullet}\n\nकृपया पोर्टल लिंक पर जाकर अपनी रिपोर्ट"
            " जल्द सबमिट कर दें। धन्यवाद!"
        )

        encoded_msg = urllib.parse.quote(reminder_msg)
        whatsapp_url = f"https://api.whatsapp.com/send?text={encoded_msg}"

        st.markdown("---")
        st.link_button(
            "📲 व्हाट्सएप पर याद दिलाएं (Send Reminder on WhatsApp)",
            whatsapp_url,
        )
        with st.expander(
            "📝 मैसेज टेक्स्ट देखें या कॉपी करें (View / Copy Message)"
        ):
          st.text_area("Message Copy:", reminder_msg, height=180)
      else:
        st.success(
            f"🎉 बधाई! {view_group} के सभी भाई-बहनों की रिपोर्ट"
            f" **{view_month}** के लिए जमा हो चुकी है!"
        )

  elif pin:
    st.error("अमान्य पिन! (Invalid PIN)")

# 3. PIONEERS SECTION
elif menu == "🌟 रेगुलर पायनियर (Pioneers Special 🔒)":
  st.header("🌟 रेगुलर पायनियर सेवा रिकॉर्ड (Pioneers Special)")
  pin = st.text_input("पायनियर ओवरसियर पिन दर्ज करें:", type="password")

  if pin == OVERSEER_PIN or pin == ADMIN_PIN:
    st.success("Access Granted ✔")
    df = load_data()
    pioneer_df = df[df["Publisher"].isin(REGULAR_PIONEERS)]
    if not pioneer_df.empty:
      st.dataframe(pioneer_df, use_container_width=True)
    else:
      st.info("पायनियरों का कोई रिकॉर्ड अभी उपलब्ध नहीं है।")
  elif pin:
    st.error("गलत पिन! (Invalid PIN)")

# 4. ADMIN PANEL
elif menu == "⚙️ एडमिन एवं एक्सेल डाउनलोड (Admin & Export 🔒)":
  st.header("⚙️ मंडली सचिव मास्टर कंट्रोल (Secretary Master Control)")
  pin = st.text_input("मास्टर एडमिन पिन दर्ज करें:", type="password")

  if pin == ADMIN_PIN:
    st.success("Admin Access Granted ✔")
    df = load_data()
    if not df.empty:
      st.dataframe(df, use_container_width=True)
      if os.path.exists(LOCAL_BACKUP):
        with open(LOCAL_BACKUP, "rb") as f:
          st.download_button(
              label="📥 मास्टर रिपोर्ट एक्सेल शीट डाउनलोड करें (Download Excel)",
              data=f,
              file_name="Indore_East_Master_Field_Service_Report.xlsx",
              mime=(
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              ),
          )
    else:
      st.info("डेटाबेस अभी खाली है।")
  elif pin:
    st.error("गलत एडमिन पिन! (Invalid Admin PIN)")

