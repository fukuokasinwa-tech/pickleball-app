import streamlit as st
import gspread
import pandas as pd

# ページ基本設定
st.set_page_config(
    page_title="ピックルボール練習会 案内・集計",
    page_icon="🏓",
    layout="centered"
)

# カスタムCSS（デザインの調整）
st.markdown("""
    <style>
    .main-header {
        font-size: 2rem;
        color: #1E3A8A;
        text-align: center;
        font-weight: bold;
        margin-bottom: 1rem;
    }
    .event-card {
        background-color: #F3F4F6;
        padding: 1.2rem;
        border-radius: 10px;
        border-left: 5px solid #2563EB;
        margin-bottom: 1rem;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🏓 ピックルボール練習会 案内・集計</div>', unsafe_allow_html=True)

# --- 1. Google 認証 & 接続処理 (柔軟なフォールバック機能付き) ---
@st.cache_resource(show_spinner=False)
def get_gspread_client():
    # Secretsからサービスアカウント情報を柔軟に取得
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
    else:
        # トラブル回避のため直接キーが置かれている場合にも対応
        creds_dict = dict(st.secrets)
    
    # private_key 内の \n 文字列を実際の改行コードに変換
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
    return gspread.service_account_from_dict(creds_dict)

@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    client = get_gspread_client()
    # URLの取得箇所も柔軟に対応
    url = None
    if "gsheets" in st.secrets and "spreadsheet" in st.secrets["gsheets"]:
        url = st.secrets["gsheets"]["spreadsheet"]
    elif "spreadsheet" in st.secrets:
        url = st.secrets["spreadsheet"]
    elif "spreadsheet_url" in st.secrets:
        url = st.secrets["spreadsheet_url"]
        
    if not url:
        st.error("スプレッドシートのURLがSecrets設定に見つかりません。")
        st.stop()
        
    return client.open_by_url(url)

# --- 2. データ読み込み ---
try:
    sh = get_spreadsheet()
    
    # 各シートの取得（存在しない場合は初期表示用のダミーデータを作成）
    try:
        ws_events = sh.worksheet("events")
        events_data = ws_events.get_all_records()
    except Exception:
        events_data = []

    try:
        ws_parts = sh.worksheet("participants")
        parts_data = ws_parts.get_all_records()
    except Exception:
        parts_data = []

except Exception as e:
    st.error(f"スプレッドシートとの連携でエラーが発生しました: {e}")
    st.stop()

# --- 3. メイン画面レイアウト ---
tab1, tab2 = st.tabs(["📅 練習日程・参加申込", "📊 参加集計一覧"])

# タブ1: 練習日程告知と申し込み
with tab1:
    st.subheader("📢 開催予定の練習会")
    
    if not events_data:
        st.info("現在告知されている練習会日程はありません。スプレッドシートの `events` シートに日程を追加してください。")
    else:
        df_events = pd.DataFrame(events_data)
        
        for idx, row in df_events.iterrows():
            with st.container():
                st.markdown(f"""
                <div class="event-card">
                    <h3>{row.get('title', 'ピックルボール練習会')}</h3>
                    <p><b>日時:</b> {row.get('date', '未定')} {row.get('time', '')}</p>
                    <p><b>場所:</b> {row.get('location', '未定')}</p>
                    <p><b>定員:</b> {row.get('capacity', 'なし')} 名</p>
                    <p><b>備考:</b> {row.get('note', '-')}</p>
                </div>
                """, unsafe_allow_html=True)
                
                # 申込フォーム
                with st.expander(f"👉 この練習会（{row.get('date', '')}）に申し込む"):
                    with st.form(key=f"form_{idx}"):
                        name = st.text_input("お名前 *")
                        comment = st.text_input("コメント・連絡事項")
                        submit = st.form_submit_button("参加を申し込む")
                        
                        if submit:
                            if not name:
                                st.warning("お名前を入力してください。")
                            else:
                                try:
                                    ws_parts = sh.worksheet("participants")
                                    ws_parts.append_row([row.get('id', idx), row.get('date', ''), name, comment])
                                    st.success(f"{name} 様の申し込みを受け付けました！")
                                    st.rerun()
                                except Exception as err:
                                    st.error(f"送信に失敗しました: {err}")

# タブ2: 参加集計一覧
with tab2:
    st.subheader("👥 参加集計状況")
    
    if not parts_data:
        st.info("まだ参加申込はありません。")
    else:
        df_parts = pd.DataFrame(parts_data)
        
        # 日程ごとに集計して見やすく表示
        st.metric("現在の延べ参加申込数", f"{len(df_parts)} 名")
        
        st.dataframe(
            df_parts,
            use_container_width=True,
            hide_index=True
        )
