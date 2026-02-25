import streamlit as st
import os
import dashscope
from datetime import datetime
from fpdf import FPDF
import platform

# ================= 尝试导入 PDF 库 =================
try:
    import fitz  # PyMuPDF

    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
# ==================================================

# ================= 配置区 =================
# ⚠️ 请在这里填入你的真实 API KEY
dashscope.api_key = ""
# =========================================

st.set_page_config(page_title="保险保单解读助手", page_icon="🛡️", layout="wide")


# --- 核心功能函数 ---

def extract_text_from_pdf(file):
    """从上传的 PDF 文件中提取文字（加速版）"""
    text = ""
    file_bytes = file.read()
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for page in doc:
        # 使用最快的纯文本模式
        text += page.get_text("text", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    doc.close()
    return text


def extract_text_from_txt(file):
    """从上传的 TXT 文件中提取文字"""
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

        # --- 1. 字体配置 ---
        system_name = platform.system()
        if system_name == "Windows":
            font_path = "C:/Windows/Fonts/simhei.ttf"
        elif system_name == "Darwin":
            font_path = "/System/Library/Fonts/STHeiti Light.ttc"
        else:
            st.error("❌ 当前系统未配置中文字体。")
            return None

        if not os.path.exists(font_path):
            st.error("❌ 找不到字体文件。")
            return None

        pdf.add_font("SimHei", "", font_path, uni=True)
        pdf.set_font("SimHei", size=12)

        # --- 2. 定义主题色 (保险蓝) ---
        PRIMARY_COLOR = (0, 82, 155)  # 专业深蓝色
        ACCENT_COLOR = (230, 80, 80)  # 警示红色
        BG_COLOR = (245, 249, 252)  # 浅蓝背景

        # --- 3. 封面设计 ---
        # 标题
        pdf.set_text_color(*PRIMARY_COLOR)
        pdf.set_font("SimHei", size=20)
        pdf.cell(0, 18, "🛡️ 保险保单深度解读报告", ln=True, align='C')
        pdf.ln(3)

        pdf.set_text_color(100, 100, 100)
        pdf.set_font("SimHei", size=10)
        pdf.cell(0, 8, "—— AI 驱动的智能风险分析 ——", ln=True, align='C')
        pdf.ln(10)

        # 信息卡片
        pdf.set_fill_color(*BG_COLOR)
        pdf.rect(20, pdf.get_y(), 170, 30, 'F')

        pdf.set_text_color(60, 60, 60)
        pdf.set_font("SimHei", size=10)
        pdf.cell(0, 8, f"📄 分析文件：{filename}", ln=True)
        pdf.cell(0, 8, f"🎭 专家视角：{persona}", ln=True)
        pdf.cell(0, 8, f"🕒 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True)
        pdf.ln(15)

        # --- 4. 内容排版 ---
        lines = content_text.split('\n')
        in_list = False

        for line in lines:
            line = line.strip()
            if not line:
                pdf.ln(4)
                continue

            # 处理三级标题 ### -> 带图标的警示标题
            if line.startswith("###"):
                text = line.replace("###", "").strip()
                # 提取图标
                icon = "⚠️" if "陷阱" in text or "不赔" in text else "💡"
                pdf.set_text_color(*ACCENT_COLOR if "陷阱" in text else PRIMARY_COLOR)
                pdf.set_font("SimHei", size=14)
                pdf.cell(0, 10, f"{icon} {text}", ln=True)
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("SimHei", size=12)
                pdf.ln(4)
                in_list = False

            # 处理二级标题 ## -> 主要章节
            elif line.startswith("##"):
                text = line.replace("##", "").strip()
                pdf.set_text_color(*PRIMARY_COLOR)
                pdf.set_font("SimHei", size=15)
                pdf.cell(0, 12, f"📌 {text}", ln=True)
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("SimHei", size=12)
                pdf.ln(5)
                in_list = False

            # 处理列表项 -
            elif line.startswith("-") or line.startswith("•"):
                text = line[1:].strip()
                clean_text = text.replace("**", "")

                # 开始一个新列表时，加一点上边距
                if not in_list:
                    pdf.ln(2)
                    in_list = True

                # 列表项样式
                x_start = pdf.get_x()
                y_start = pdf.get_y()
                pdf.set_text_color(80, 80, 80)
                pdf.circle(x_start + 2, y_start + 4, 1.5, style='F')
                pdf.set_x(x_start + 8)
                pdf.multi_cell(0, 7, clean_text)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(2)

            # 普通文本
            else:
                clean_text = line.replace("**", "")
                pdf.set_text_color(50, 50, 50)
                pdf.multi_cell(0, 7, clean_text)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(3)
                in_list = False

        # --- 5. 页脚 ---
        pdf.set_y(-20)
        pdf.set_fill_color(*BG_COLOR)
        pdf.rect(0, pdf.get_y(), 210, 20, 'F')

        pdf.set_text_color(100, 100, 100)
        pdf.set_font("SimHei", size=9)
        pdf.cell(0, 5, "本报告由 AI 生成，基于您提供的保单条款进行分析。", ln=True, align='C')
        pdf.cell(0, 5, "结果仅供参考，具体理赔以保险公司最终审核为准。", ln=True, align='C')

        return bytes(pdf.output(dest='S'))

    except Exception as e:
        st.error(f"生成 PDF 失败：{e}")
        import traceback
        traceback.print_exc()
        return None

# --- 界面布局 ---

st.title("🛡️ 保险保单智能解读助手")
st.markdown("上传保单，选择**专家视角**，一键获取深度解读报告！")

# 初始化 Session State (内存缓存)
if 'current_content' not in st.session_state:
    st.session_state.current_content = None
if 'current_filename' not in st.session_state:
    st.session_state.current_filename = None

# --- 侧边栏 ---
with st.sidebar:
    st.header("📄 1. 上传保单")
    uploaded_file = st.file_uploader("支持 .pdf / .txt", type=["txt", "pdf"])

    content = None

    if uploaded_file is not None:
        file_name = uploaded_file.name
        st.success(f"✅ 已加载：{file_name}")

        # 如果文件变了，或者第一次加载，才重新解析
        if st.session_state.current_filename != file_name:
            with st.spinner("📖 正在解析文件..."):
                try:
                    if file_name.endswith(".pdf"):
                        if PDF_SUPPORT:
                            content = extract_text_from_pdf(uploaded_file)
                        else:
                            st.error("❌ 未安装 pymupdf 库")
                            st.stop()
                    else:
                        content = extract_text_from_txt(uploaded_file)

                    if len(content) > 50:
                        st.session_state.current_content = content
                        st.session_state.current_filename = file_name
                        st.success("✅ 解析成功！")
                    else:
                        st.warning("⚠️ 文件内容似乎为空。")
                        st.session_state.current_content = None
                except Exception as e:
                    st.error(f"❌ 解析失败：{e}")
                    st.session_state.current_content = None
        else:
            # 文件没变，直接用缓存
            content = st.session_state.current_content
            st.info("ℹ️ 使用已解析的缓存数据")
    else:
        st.info("👈 请先上传文件")

    st.divider()

    st.header("🎭 2. 选择专家视角")
    persona = st.selectbox(
        "谁来帮您分析？",
        (
            "🕵️‍♂️ 理赔调查员 (找茬排雷)",
            "⚖️ 资深律师 (审核陷阱)",
            "🧮 精算师 (性价比分析)",
            "👵 养老规划师 (适合谁买)",
            "🗣️ 大白话翻译 (通俗易懂)"
        )
    )

# --- 主逻辑：根据人设生成 Prompt ---

system_instruction = ""
if "理赔调查员" in persona:
    system_instruction = "你是一位拥有 20 年经验的保险理赔调查员，专门帮用户“找茬”和“排雷”。重点找出最容易导致拒赔的陷阱、隐蔽的免责条款和严苛的理赔条件。语气要犀利、直接、带有警示性。输出格式：### ⚠️ 核心拒赔陷阱 ... ### 💡 关键数据 ..."
elif "律师" in persona:
    system_instruction = "你是一位精通保险法的资深律师。从法律合规和维权角度审查这份保单。重点指出模糊的定义、可能产生歧义的条款以及对消费者不利的格式条款。语气要严谨、专业、客观。输出格式：### ⚖️ 法律风险点 ... ### 📝 修改/注意建议 ..."
elif "精算师" in persona:
    system_instruction = "你是一位冷酷理性的精算师。忽略情感因素，重点分析保费与保额的杠杆率、等待期长短、免赔额高低以及报销比例。告诉用户这款产品性价比如何。语气要数据驱动、冷静。输出格式：### 📊 性价比分析 ... ### 💰 适合人群画像 ..."
elif "养老" in persona:
    system_instruction = "你是一位温暖的养老规划师。重点分析这份保单在长期护理、疾病保障和资金领取方面的表现。告诉用户老了以后靠这份保险能不能过上好日子。语气要温暖、关怀、展望未来。输出格式：### 🏡 养老适配度 ... ### 👴 给长辈的建议 ..."
else:
    system_instruction = "你是一位擅长科普的社区大妈/大叔。请把这份复杂的保单翻译成连小学生都能听懂的大白话。不要用什么术语，多用比喻。语气要亲切、接地气、像聊天一样。输出格式：### 🗣️ 咱老百姓听得懂的话 ..."

# --- 主界面展示 ---

if st.session_state.current_content:
    st.subheader(f"📄 当前分析：{st.session_state.current_filename}")
    st.caption(f"专家视角：{persona}")

    # 构造 Prompt (限制长度防止超时，但足够覆盖核心条款)
    # 这里取前 15000 字，和之前成功时一样
    content_preview = st.session_state.current_content[:15000]
    prompt = f"{system_instruction}\n\n【保单内容】:\n{content_preview}"

    if st.button("🚀 生成分析报告", type="primary", use_container_width=True):
        with st.spinner(f"🤖 {persona} 正在深度思考中..."):
            try:
                response = dashscope.Generation.call(
                    model='qwen-turbo',
                    messages=[{'role': 'user', 'content': prompt}]
                )

                if response.status_code == 200:
                    result_text = response.output.text
                    st.markdown(result_text)
                    st.balloons()

                    # 🔴 新增：生成 PDF 并提供下载
                    pdf_bytes = create_pdf_report(
                        st.session_state.current_filename,
                        persona,
                        result_text
                    )

                    if pdf_bytes:
                        st.download_button(
                            label="📥 下载报告为 PDF",
                            data=pdf_bytes,
                            file_name=f"{st.session_state.current_filename}_解读报告.pdf",
                            mime="application/pdf",
                            type="primary"
                        )
                else:
                    st.error(f"AI 调用失败：{response.message}")
            except Exception as e:
                st.error(f"发生错误：{e}")

    # 可选：查看原始文字 (这里不限制 1000 字，直接折叠显示全部，或者只显示前 2000 字预览)
    with st.expander("👀 查看提取的原始文字"):
        st.text(st.session_state.current_content[:2000] + "...")

else:

    st.info("👆 请在左侧上传文件以开始分析。")
