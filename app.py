import streamlit as st
import os
import dashscope
from datetime import datetime
from fpdf import FPDF
import platform

# ================= 嘗試導入 PDF 庫 =================
try:
    import fitz  # PyMuPDF
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    st.error("❌ 未安裝 pymupdf 庫，請運行: pip install pymupdf")
# ==================================================

# ================= 配置區 =================
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
if not dashscope.api_key:
    st.error("🚫 未檢測到 DASHSCOPE_API_KEY，請在環境變量或 .env 中設定")
# =========================================

st.set_page_config(page_title="保單智能解讀助手", page_icon="🛡️", layout="wide")

# --- 使用計數器（文件數量版） ---
# 修改日期：2026-03-12
# 修改者：Grok
# 原因：改為統計「已分析過的保單文件總數」，而不是人數，更符合實際使用（一人可能分析多份）
# 實現方式：本地文件 counter.txt，每次成功生成報告 +1（計一份保單）
# 未來可擴展：加獨立用戶 ID 判斷、或用外部 DB 統計真實用戶數
COUNTER_FILE = "usage_counter.txt"

def get_usage_count():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except:
                return 0
    return 0

def increment_usage_count():
    count = get_usage_count() + 1
    with open(COUNTER_FILE, "w") as f:
        f.write(str(count))
    return count

# --- 核心功能函數 ---
def extract_text_from_pdf(file):
    """從上傳的 PDF 文件中提取文字（加速版）"""
    text = ""
    file_bytes = file.read()
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for page in doc:
        text += page.get_text("text", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    doc.close()
    return text

def extract_text_from_txt(file):
    """從上傳的 TXT 文件中提取文字"""
    try:
        return file.read().decode('utf-8')
    except UnicodeDecodeError:
        file.seek(0)
        return file.read().decode('gbk', errors='ignore')

# generate pdf report
def create_pdf_report(filename, persona, content_text):
    try:
        pdf = FPDF()
        pdf.add_page()

        font_path = None
        if os.path.exists("SimHei.ttf"):
            font_path = "SimHei.ttf"
        elif os.path.exists("NotoSansSC-Regular.otf"):
            font_path = "NotoSansSC-Regular.otf"
        elif os.path.exists("C:/Windows/Fonts/simhei.ttf"):
            font_path = "C:/Windows/Fonts/simhei.ttf"
        elif os.path.exists("/System/Library/Fonts/STHeiti Light.ttc"):
            font_path = "/System/Library/Fonts/STHeiti Light.ttc"

        if not font_path:
            st.error("❌ 未找到中文字體文件。請確保 SimHei.ttf 已上傳到項目根目錄。")
            return None

        pdf.add_font("SimHei", "", font_path, uni=True)
        pdf.set_font("SimHei", size=12)

        PRIMARY_COLOR = (0, 82, 155)
        ACCENT_COLOR = (230, 80, 80)
        BG_COLOR = (245, 249, 252)

        pdf.set_text_color(*PRIMARY_COLOR)
        pdf.set_font("SimHei", size=20)
        pdf.cell(0, 18, "🛡️ 保單深度解讀報告", ln=True, align='C')
        pdf.ln(3)

        pdf.set_text_color(100, 100, 100)
        pdf.set_font("SimHei", size=10)
        pdf.cell(0, 8, "—— AI 驅動的智能風險分析 ——", ln=True, align='C')
        pdf.ln(10)

        pdf.set_fill_color(*BG_COLOR)
        pdf.rect(20, pdf.get_y(), 170, 30, 'F')

        pdf.set_text_color(60, 60, 60)
        pdf.set_font("SimHei", size=10)
        pdf.cell(0, 8, f"📄 分析文件：{filename}", ln=True)
        pdf.cell(0, 8, f"🎭 專家視角：{persona}", ln=True)
        pdf.cell(0, 8, f"🕒 生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True)
        pdf.ln(15)

        lines = content_text.split('\n')
        in_list = False

        for line in lines:
            line = line.strip()
            if not line:
                pdf.ln(4)
                continue

            if line.startswith("###"):
                text = line.replace("###", "").strip()
                icon = "⚠️" if "陷阱" in text or "不賠" in text else "💡"
                pdf.set_text_color(*ACCENT_COLOR if "陷阱" in text else PRIMARY_COLOR)
                pdf.set_font("SimHei", size=14)
                pdf.cell(0, 10, f"{icon} {text}", ln=True)
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("SimHei", size=12)
                pdf.ln(4)
                in_list = False

            elif line.startswith("##"):
                text = line.replace("##", "").strip()
                pdf.set_text_color(*PRIMARY_COLOR)
                pdf.set_font("SimHei", size=15)
                pdf.cell(0, 12, f"📌 {text}", ln=True)
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("SimHei", size=12)
                pdf.ln(5)
                in_list = False

            elif line.startswith("-") or line.startswith("•"):
                text = line[1:].strip()
                clean_text = text.replace("**", "")

                if not in_list:
                    pdf.ln(2)
                    in_list = True

                x_start = pdf.get_x()
                y_start = pdf.get_y()
                pdf.set_text_color(80, 80, 80)
                pdf.circle(x_start + 2, y_start + 4, 1.5, style='F')
                pdf.set_x(x_start + 8)
                pdf.multi_cell(0, 7, clean_text)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(2)

            else:
                clean_text = line.replace("**", "")
                pdf.set_text_color(50, 50, 50)
                pdf.multi_cell(0, 7, clean_text)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(3)
                in_list = False

        pdf.set_y(-20)
        pdf.set_fill_color(*BG_COLOR)
        pdf.rect(0, pdf.get_y(), 210, 20, 'F')

        pdf.set_text_color(100, 100, 100)
        pdf.set_font("SimHei", size=9)
        pdf.cell(0, 5, "本報告由 AI 生成，基於您提供的保單條款進行分析。", ln=True, align='C')
        pdf.cell(0, 5, "結果僅供參考，具體理賠以保險公司最終審核為準。", ln=True, align='C')

        return bytes(pdf.output(dest='S'))

    except Exception as e:
        st.error(f"生成 PDF 失敗：{e}")
        import traceback
        traceback.print_exc()
        return None

# --- 界面布局 ---
st.title("🛡️ 保單智能解讀助手")
st.markdown("上傳保單，選擇**專家視角**，一鍵獲取深度解讀報告！")

# 顯示已分析保單文件總數
# 修改日期：2026-03-12
# 修改者：Grok
# 原因：改為統計保單文件數量，而非人數
usage_count = get_usage_count()
st.caption(f"目前已分析過 **{usage_count}** 份保單文件")

# 初始化 Session State
if 'current_content' not in st.session_state:
    st.session_state.current_content = None
if 'current_filename' not in st.session_state:
    st.session_state.current_filename = None
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'report_text' not in st.session_state:
    st.session_state.report_text = None

# --- 側邊欄 ---
with st.sidebar:
    st.header("📄 1. 上傳保單")
    uploaded_file = st.file_uploader("支持 .pdf / .txt", type=["txt", "pdf"])

    content = None
    if uploaded_file is not None:
        file_name = uploaded_file.name
        st.success(f"✅ 已加載：{file_name}")

        if st.session_state.current_filename != file_name:
            with st.spinner("📖 正在解析文件..."):
                try:
                    if file_name.endswith(".pdf"):
                        if PDF_SUPPORT:
                            content = extract_text_from_pdf(uploaded_file)
                        else:
                            st.error("❌ 未安裝 pymupdf 庫")
                            st.stop()
                    else:
                        content = extract_text_from_txt(uploaded_file)

                    if len(content) > 50:
                        st.session_state.current_content = content
                        st.session_state.current_filename = file_name
                        st.session_state.report_text = None
                        st.session_state.messages = []
                        st.success("✅ 解析成功！")
                    else:
                        st.warning("⚠️ 文件內容似乎為空。")
                        st.session_state.current_content = None
                except Exception as e:
                    st.error(f"❌ 解析失敗：{e}")
                    st.session_state.current_content = None
        else:
            content = st.session_state.current_content
            st.info("ℹ️ 使用已解析的緩存數據")
    else:
        st.info("👈 請先上傳文件")

    st.divider()
    st.header("🎭 2. 選擇專家視角")
    persona = st.selectbox(
        "誰來幫您分析？",
        (
            "🕵️‍♂️ 理賠調查員 (找茬排雷)",
            "⚖️ 資深律師 (審核陷阱)",
            "🧮 精算師 (性價比分析)",
            "👵 養老規劃師 (適合誰買)",
            "🗣️ 大白話翻譯 (通俗易懂)"
        )
    )

# --- 主邏輯：根據人設生成 Prompt ---
system_instruction = ""
if "理賠調查員" in persona:
    system_instruction = "你是一位擁有 20 年經驗的保險理賠調查員，專門幫用戶「找茬」和「排雷」。重點找出最容易導致拒賠的陷阱、隱蔽的免責條款和嚴苛的理賠條件。語氣要犀利、直接、帶有警示性。輸出格式：### ⚠️ 核心拒賠陷阱 ... ### 💡 關鍵數據 ..."
elif "律師" in persona:
    system_instruction = "你是一位精通保險法的資深律師。從法律合規和維權角度審查這份保單。重點指出模糊的定義、可能產生歧義的條款以及對消費者不利的格式條款。語氣要嚴謹、專業、客觀。輸出格式：### ⚖️ 法律風險點 ... ### 📝 修改/注意建議 ..."
elif "精算師" in persona:
    system_instruction = "你是一位冷酷理性的精算師。忽略情感因素，重點分析保費與保額的槓桿率、等待期長短、免賠額高低以及報銷比例。告訴用戶這款產品性價比如何。語氣要數據驅動、冷靜。輸出格式：### 📊 性價比分析 ... ### 💰 適合人群畫像 ..."
elif "養老" in persona:
    system_instruction = "你是一位溫暖的養老規劃師。重點分析這份保單在長期護理、疾病保障和資金領取方面的表現。告訴用戶老了以後靠這份保險能不能過上好日子。語氣要溫暖、關懷、展望未來。輸出格式：### 🏡 養老適配度 ... ### 👴 給長輩的建議 ..."
else:
    system_instruction = "你是一位擅長科普的社區大媽/大叔。請把這份複雜的保單翻譯成連小學生都能聽懂的大白話。不要用什麼術語，多用比喻。語氣要親切、接地氣、像聊天一樣。輸出格式：### 🗣️ 咱老百姓聽得懂的話 ..."

# --- 主界面展示 ---
if st.session_state.current_content:
    st.subheader(f"📄 當前分析：{st.session_state.current_filename}")
    st.caption(f"專家視角：{persona}")

    tab_report, tab_chat = st.tabs(["完整報告", "追問對話"])

    with tab_report:
        with st.container():
            st.markdown("""
            <div style="background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.08);">
            """, unsafe_allow_html=True)

            if st.session_state.report_text:
                st.markdown(st.session_state.report_text)
            else:
                st.info("點擊下方按鈕生成報告")

            st.markdown("</div>", unsafe_allow_html=True)

        content_preview = st.session_state.current_content[:15000]
        initial_prompt = f"{system_instruction}\n\n【保單內容】:\n{content_preview}"

        if st.button("🚀 生成分析報告", type="primary", use_container_width=True):
            with st.spinner(f"🤖 {persona} 正在深度思考中..."):
                try:
                    response = dashscope.Generation.call(
                        model='qwen-turbo',
                        messages=[{'role': 'user', 'content': initial_prompt}]
                    )

                    if response.status_code == 200:
                        result_text = response.output.text
                        st.session_state.report_text = result_text
                        st.session_state.messages.append({"role": "assistant", "content": result_text})

                        # 成功生成報告後，計數 +1（計保單文件數）
                        increment_usage_count()
                        st.rerun()  # 刷新頁面顯示新計數

                        pdf_bytes = create_pdf_report(
                            st.session_state.current_filename,
                            persona,
                            result_text
                        )
                        if pdf_bytes:
                            st.download_button(
                                label="📥 下載報告為 PDF",
                                data=pdf_bytes,
                                file_name=f"{st.session_state.current_filename}_解讀報告.pdf",
                                mime="application/pdf",
                                type="primary"
                            )
                    else:
                        st.error(f"AI 調用失敗：{response.message}")
                except Exception as e:
                    st.error(f"發生錯誤：{e}")

    with tab_chat:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("在此繼續追問（例如：這個 exclusion 實際影響大唔大？）"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("思考中..."):
                    try:
                        context = st.session_state.report_text or st.session_state.current_content[:3000]
                        chat_prompt = f"{system_instruction}\n\n【之前報告或保單內容】:\n{context}\n\n【用戶新問題】:\n{prompt}"

                        response = dashscope.Generation.call(
                            model='qwen-turbo',
                            messages=[{'role': 'user', 'content': chat_prompt}]
                        )

                        if response.status_code == 200:
                            reply = response.output.text
                            st.markdown(reply)
                            st.session_state.messages.append({"role": "assistant", "content": reply})
                        else:
                            st.error("追問失敗，請重試")
                    except Exception as e:
                        st.error(f"追問錯誤：{e}")

    with st.expander("👀 查看提取的原始文字"):
        st.text(st.session_state.current_content[:2000] + "...")

else:
    st.info("👆 請在左側上傳文件以開始分析。")

st.divider()
st.subheader("💬 用戶反饋")
st.markdown("""
您的反饋是我們進步的動力！如果您在使用過程中遇到任何問題，或有更好的建議，請花 1 分鐘填寫下方表單。
""")
st.link_button("📝 點擊此處填寫反饋表", "https://v.wjx.cn/vm/trZqdgp.aspx# ")