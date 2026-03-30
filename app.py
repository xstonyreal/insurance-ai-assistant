import streamlit as st
import os
import dashscope
from datetime import datetime, date
from fpdf import FPDF
from fpdf.enums import XPos, YPos  # 修复警告：用于替代过时的 ln=True
import platform
import hashlib
import sqlite3

# =================================================================
# 模块一：用户认证系统 (User Authentication System)
# 功能：处理用户注册、登录、每日使用额度限制
# =================================================================
DB_FILE = "users.db"

def init_db():
    """初始化 SQLite 数据库，存储用户信息和使用频率数据"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 字段说明：role (权限角色), daily_limit (每日配额), uses_today (今日已用次数)
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',           -- 'guest' 或 'user'
                    daily_limit INTEGER DEFAULT 5,     -- 默认每天5次，可改
                    uses_today INTEGER DEFAULT 0,
                    last_use_date TEXT DEFAULT ''
                 )''')
    conn.commit()
    conn.close()


def hash_password(password):
    """使用 SHA-256 算法对密码进行哈希脱敏，确保存储安全"""
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    """新用户注册逻辑"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                  (username, hash_password(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # 用户名已存在触发
    finally:
        conn.close()

def login_user(username, password):
    """用户登录验证，并检查/重置每日计数器"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password_hash, daily_limit, uses_today, last_use_date FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    stored_hash, limit, uses_today, last_date = row
    if stored_hash == hash_password(password):
        # 检查是否新的一天，重置计数
        today = date.today().isoformat()
        # 核心逻辑：如果跨天了，自动将今日使用次数重置为 0
        if last_date != today:
            uses_today = 0
        return {"username": username, "daily_limit": limit, "uses_today": uses_today, "today": today}
    return None

def update_user_usage(username, today):
    """当 AI 生成报告成功后，增加该用户的今日使用计数"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""UPDATE users 
                 SET uses_today = uses_today + 1, last_use_date = ? 
                 WHERE username = ?""", (today, username))
    conn.commit()
    conn.close()

def get_remaining_uses(username):
    """查询用户当天还剩多少次分析机会"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT daily_limit, uses_today, last_use_date FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 0
    limit, used, last_date = row
    # 若日期不是今天，说明还没用过，返回完整配额
    if last_date != date.today().isoformat():
        return limit
    return max(0, limit - used)

# =================================================================
# 模块二：文档解析与 PDF 报表生成
# 功能：提取 PDF/TXT 内容，并将 AI 分析结果转化为美观的 PDF
# =================================================================
# 尝试导入 PyMuPDF (fitz)，用于处理 PDF 文本提取
try:
    import fitz  # PyMuPDF
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    st.error("❌ 未安裝 pymupdf 庫，請運行: pip install pymupdf")
# ==================================================

# ================= 配置區 =================
# 初始化数据库 2026.03.26
init_db()

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
    """将 Markdown 格式的 AI 报告转换为结构化的 PDF 文档"""
    try:
        pdf = FPDF()
        pdf.add_page()

        # 中文字体兼容性处理：优先寻找本地字体文件
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

        # 注意：此处将原有的 uni=True 去掉（新版默认支持 Unicode），并修改 cell 换行逻辑
        pdf.add_font("SimHei", "", font_path)
        pdf.set_font("SimHei", size=12)

        PRIMARY_COLOR = (0, 82, 155)
        ACCENT_COLOR = (230, 80, 80)
        BG_COLOR = (245, 249, 252)

        pdf.set_text_color(*PRIMARY_COLOR)
        pdf.set_font("SimHei", size=20)
        # 修改点：用 new_x 和 new_y 替代 ln=True
        pdf.cell(0, 18, "🛡️ 保單深度解讀報告", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(3)

        pdf.set_text_color(100, 100, 100)
        pdf.set_font("SimHei", size=10)
        pdf.cell(0, 8, "—— AI 驅動的智能風險分析 ——", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.ln(10)

        pdf.set_fill_color(*BG_COLOR)
        pdf.rect(20, pdf.get_y(), 170, 30, 'F')

        pdf.set_text_color(60, 60, 60)
        pdf.set_font("SimHei", size=10)
        pdf.cell(0, 8, f"📄 分析文件：{filename}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, f"🎭 專家視角：{persona}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 8, f"🕒 生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
                pdf.cell(0, 10, f"{icon} {text}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("SimHei", size=12)
                pdf.ln(4)
                in_list = False

            elif line.startswith("##"):
                text = line.replace("##", "").strip()
                pdf.set_text_color(*PRIMARY_COLOR)
                pdf.set_font("SimHei", size=15)
                pdf.cell(0, 12, f"📌 {text}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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

        # 报告的页脚增加免责声明
        pdf.set_y(-25)  # 留出足夠空間
        pdf.set_font("SimHei", size=8)
        pdf.set_text_color(150, 150, 150)
        pdf.multi_cell(0, 4,
                       "【法律聲明】本報告由 AI 自動生成，僅供學習交流。AI 無法替代專業保險經紀人或律師。任何理賠爭議請以保險公司官方解釋為準。下載即代表您已閱讀並同意本免責條款。",
                       align='C')

        pdf.set_text_color(100, 100, 100)
        pdf.set_font("SimHei", size=9)
        pdf.cell(0, 5, "本報告由 AI 生成，基於您提供的保單條款進行分析。", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        pdf.cell(0, 5, "結果僅供參考，具體理賠以保險公司最終審核為準。", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')

        # 修改点：dest='S' 已弃用，显式转换为 bytes 格式，解决 Streamlit 不识别 bytearray 的问题
        return bytes(pdf.output())

    except Exception as e:
        st.error(f"生成 PDF 失敗：{e}")
        import traceback
        traceback.print_exc()
        return None

# =================================================================
# 模块三：Streamlit UI 布局与 AI 流式交互
# 功能：构建 Web 界面，调用 Qwen 模型并实现打字机效果
# =================================================================

# 初始化 DashScope (通义千问 API)
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
init_db()

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
    # ================= 新增：登录 / 注册 =================
    st.header("🔑 2. 授权登录")

    if 'user_info' not in st.session_state:
        st.session_state.user_info = None

    if st.session_state.user_info is None:
        # 未登录状态
        tab_login, tab_register = st.tabs(["登录", "注册"])

        with tab_login:
            username = st.text_input("用户名", key="login_user")
            password = st.text_input("密码", type="password", key="login_pass")
            if st.button("登录", use_container_width=True):
                user_data = login_user(username, password)
                if user_data:
                    st.session_state.user_info = user_data
                    st.success(f"✅ 欢迎回来，{username}！")
                    st.rerun()
                else:
                    st.error("用户名或密码错误")

        with tab_register:
            new_user = st.text_input("用户名（建议用邮箱或手机号）", key="reg_user")
            new_pass = st.text_input("设置密码", type="password", key="reg_pass")
            if st.button("注册并登录", use_container_width=True):
                if register_user(new_user, new_pass):
                    # 注册成功后自动登录
                    st.session_state.user_info = {
                        "username": new_user,
                        "daily_limit": 10,
                        "uses_today": 0,
                        "today": date.today().isoformat()
                    }
                    st.success(f"🎉 注册成功！欢迎 {new_user}")
                    st.rerun()
                else:
                    st.error("用户名已被注册")

        st.info("👤 游客模式：每 Session 最多分析 **3 次**")

    else:
        # 已登录状态
        username = st.session_state.user_info["username"]
        remaining = get_remaining_uses(username)

        st.success(f"👤 已登录：**{username}**")
        st.caption(f"今日剩余次数：**{remaining}** 次")

        if st.button("退出登录"):
            st.session_state.user_info = None
            st.rerun()

    st.divider()

    st.header("🎭 3. 選擇專家視角")
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

        #免责声明
        if st.session_state.report_text:
            st.warning("⚠️ **提醒**：AI 分析僅供參考，請核對保險合同原件。")
            st.markdown(st.session_state.report_text)
        # --- 第一步：计算权限（不重复造轮子） ---
        is_logged_in = st.session_state.user_info is not None
        if is_logged_in:
            username = st.session_state.user_info["username"]
            remaining = get_remaining_uses(username)
            limit_msg = f"✅ 已登錄用戶：{username} | 今日剩餘：{remaining} 次"
        else:
            # 确保游客模式下也有计数器变量
            if 'guest_uses' not in st.session_state: st.session_state.guest_uses = 0
            remaining = 3 - st.session_state.guest_uses
            limit_msg = f"🟡 遊客模式 | 本次會話剩餘：{remaining} 次"

        can_generate = remaining > 0

        # --- 第二步：分支渲染（根据 report_text 是否有值来决定显示什么） ---
        if st.session_state.report_text:
            # 【分支 A：显示报告模式】
            # 因为 session_state 跨标签页共享，这里显示的内容就是 AI 刚写完的内容
            st.markdown(st.session_state.report_text)

            # PDF 下载逻辑
            pdf_data = create_pdf_report(st.session_state.current_filename, persona, st.session_state.report_text)
            if pdf_data:
                st.download_button("📥 下載 PDF 分析報告", data=pdf_data,
                                   file_name=f"分析報告_{st.session_state.current_filename}.pdf",
                                   mime="application/pdf", use_container_width=True)

            # 重置逻辑：清除报告，让页面回到【分支 B】
            if st.button("🔄 重新分析（將消耗次數）", use_container_width=True):
                if can_generate:
                    st.session_state.report_text = None
                    st.session_state.messages = []  # 清空对话历史，避免旧报告干扰新追问
                    st.rerun()

        else:
            # 【分支 B：显示生成按钮模式】 标准写法，确保 Streamlit 正常渲染组件
            if can_generate:
                st.info(limit_msg)
            else:
                st.error(f"❌ {limit_msg} (已達上限)")

            if can_generate:
                if st.button("🚀 開始生成分析報告", type="primary", use_container_width=True):
                    with st.spinner(f"🤖 {persona} 正在深度思考中..."):
                        try:
                            # 1. 准备给 AI 的初始指令
                            content_preview = st.session_state.current_content[:15000]
                            initial_prompt = f"{system_instruction}\n\n【保單內容】:\n{content_preview}"

                            # 2. 调用流式接口
                            report_placeholder = st.empty()
                            full_content = ""
                            responses = dashscope.Generation.call(
                                model='qwen-turbo',
                                messages=[{'role': 'user', 'content': initial_prompt}],
                                stream=True, incremental_output=True
                            )

                            # 1. 流式输出循环
                            for response in responses:
                                if response.status_code == 200:
                                    chunk = response.output.text
                                    full_content += chunk
                                    report_placeholder.markdown(full_content + "▌")  # 实时渲染流式文字

                            # 3. 【核心点】生成结束后存入 Session 记忆
                            if full_content:
                                # 1. 先把光标 ▌ 去掉，把内容固定下来，消除视觉上的“跳动”
                                report_placeholder.markdown(full_content)

                                # 2. 存入 Session 记忆（这不会触发 UI 刷新）
                                st.session_state.report_text = full_content
                                st.session_state.messages = [{"role": "assistant", "content": full_content}]

                                # 3. 扣除次数逻辑
                                increment_usage_count()
                                if not is_logged_in:
                                    st.session_state.guest_uses += 1
                                else:
                                    update_user_usage(username, date.today().isoformat())

                                # 4. 执行跳转刷新
                                st.rerun()
                        except Exception as e:
                            st.error(f"發生錯誤：{e}")
    with tab_chat:
        # --- 1. 渲染历史对话记录 ---
        # 这里的 messages 列表包含了：
        #   - 初始生成的报告 (由 tab_report 在生成成功后存入)
        #   - 用户后续的所有提问
        #   - AI 针对提问的所有回答
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # --- 2. 追问输入框逻辑 ---
        # 使用 if prompt := st.chat_input(...) 语法：只有用户输入并回车时才会进入此分支
        if prompt := st.chat_input("在此繼續追問（例如：這個 exclusion 實際影響大唔大？）"):

            # A. 立即记录并显示用户的提问
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # B. 调用 AI 进行针对性回答
            with st.chat_message("assistant"):
                with st.spinner("思考中..."):
                    try:
                        # 【核心：上下文获取】
                        # 优先使用已生成的“完整报告”作为 AI 思考的基础背景。
                        # 如果报告还没生成（理论上概率极低），则截取保单前 3000 字作为背景。
                        context = st.session_state.report_text or st.session_state.current_content[:3000]

                        # 【核心：Prompt 构造】
                        # 将：1. 专家人设指令 + 2. 之前的报告/保单背景 + 3. 用户的新问题 揉合在一起。
                        # 这样 AI 就能实现“基于理赔调查员身份，针对刚才报告中提到的陷阱进行深度解答”。
                        chat_prompt = f"{system_instruction}\n\n【之前報告或保單內容】:\n{context}\n\n【用戶新問題】:\n{prompt}"

                        # 调用非流式接口（追问通常较短，非流式响应更稳健）
                        response = dashscope.Generation.call(
                            model='qwen-turbo',
                            messages=[{'role': 'user', 'content': chat_prompt}]
                        )

                        if response.status_code == 200:
                            reply = response.output.text
                            st.markdown(reply)

                            # C. 将 AI 的回答存入 session_state 消息历史
                            st.session_state.messages.append({"role": "assistant", "content": reply})

                            # D. 【关键：状态同步】
                            # 执行 rerun() 强制 Streamlit 重新运行脚本。
                            # 这样可以确保：
                            #   1. 追问的文字被固化在页面上。
                            #   2. 主标签页 (tab_report) 保持“报告显示模式”，不会因为追问动作而误跳回“生成按钮模式”。
                            st.rerun()
                        else:
                            st.error(f"追問失敗，AI 響應錯誤：{response.message}")
                    except Exception as e:
                        st.error(f"追問時發生技術錯誤：{e}")

    # --- 3. 原始文字查看器 (折叠框) ---
    # 放在最下面作为兜底参考，不影响主流程操作
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

# 免责声明
st.divider()
st.caption("""
**⚖️ 免責聲明：** 本工具由 AI 技術驅動，生成的報告僅供參考，不構成任何保險購買、理賠建議或法律意見。  
保險條款極其複雜，AI 識別可能存在偏差（幻觉）。**具體保障範圍、理賠條件及給付金額，請務必以保險公司簽章的正式合同及法律法規為準。** 開發者不對因使用本報告導致的任何決策後果承擔法律責任。
""")