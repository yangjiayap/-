import streamlit as st
import requests
import base64
import time
import uuid
import hmac
import json
from hashlib import sha1
from PIL import Image
from io import BytesIO
from datetime import datetime
from pathlib import Path

# 这里之后再写 st.set_page_config 或其他逻辑
# =========================
# 1. 登录与 API 动态配置
# =========================
# 初始化状态
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = None
if "api_config" not in st.session_state:
    st.session_state.api_config = {}

# 登录拦截：在进入主界面前要求输入 Key
if not st.session_state.authenticated:
    st.markdown("<h2 style='text-align: center; margin-top: 50px;'>🔐 AI 实验站登录</h2>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.5, 1])
    with col:
        with st.container(border=True):
            name = st.text_input("请输入使用者姓名")
            ak = st.text_input("Liblib AccessKey (AK)", type="password")
            sk = st.text_input("Liblib SecretKey (SK)", type="password")
            tpl = st.text_input("Template UUID", value="5d7e67009b344550bc1aa6ccbfa1d7f4")

            if st.button("进入系统", use_container_width=True, type="primary"):
                if name and ak and sk:
                    st.session_state.username = name
                    st.session_state.api_config = {"ak": ak, "sk": sk, "tpl": tpl}
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("请完整填写信息！")
    st.stop()  # 拦截，未登录不执行后续代码

# 动态获取当前登录用户输入的密钥
ACCESS_KEY = st.session_state.api_config["ak"]
SECRET_KEY = st.session_state.api_config["sk"]
TEMPLATE_UUID = st.session_state.api_config["tpl"]
LIBLIB_DOMAIN = "https://openapi.liblibai.cloud"

import time
import uuid
import hmac
from hashlib import sha1


def liblib_request(uri, payload):
    timestamp = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())

    # 1. 严格对齐官方签名原串
    content = '&'.join((uri, timestamp, nonce))

    # 2. 严格对齐官方 HmacSHA1 算法
    digest = hmac.new(SECRET_KEY.encode(), content.encode(), sha1).digest()

    # 3. 关键：urlsafe 编码并移除尾部等号
    sign = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()

    params = {
        "AccessKey": ACCESS_KEY,
        "Signature": sign,
        "Timestamp": timestamp,
        "SignatureNonce": nonce
    }

    url = f"{LIBLIB_DOMAIN}{uri}"

    try:
        r = requests.post(url, params=params, json=payload, timeout=60)
        # 调试：如果还是报错，可以在这里 print(r.text)
        return r.json()
    except Exception as e:
        print(f"请求异常: {e}")
        return None


def generate_image(prompt_or_payload, steps=30, width=1024, height=1024):
    # 处理输入参数
    if isinstance(prompt_or_payload, dict):
        prompt = prompt_or_payload.get("prompt", "")
        steps = int(prompt_or_payload.get("steps", steps))
        width = prompt_or_payload.get("width", width)
        height = prompt_or_payload.get("height", height)
    else:
        prompt = prompt_or_payload

    start_time = time.time()

    # 按照官方文档要求构造 Payload
    payload = {
        "templateUuid": TEMPLATE_UUID,
        "generateParams": {
            "prompt": prompt,
            "imgCount": 1,
            "steps": steps,
            # 必须是字典对象，不能是字符串 "1024x1024"
            "imageSize": {
                "width": width,
                "height": height
            }
        }
    }

    # ① 提交任务
    submit_uri = "/api/generate/webui/text2img/ultra"
    submit = liblib_request(submit_uri, payload)

    # 防御性编程：检查返回结果
    if not submit or submit.get("code") != 0:
        st.error(f"❌ Liblib 提交失败：{submit}")
        return None, 0  # 确保返回两个值，防止解包错误

    task_id = submit.get("data", {}).get("generateUuid")
    if not task_id:
        st.error("❌ 未能获取到任务 UUID")
        return None, 0

    # ② 轮询结果
    status_uri = "/api/generate/webui/status"
    for _ in range(60):
        status = liblib_request(status_uri, {"generateUuid": task_id})

        if not status or status.get("code") != 0:
            time.sleep(2)
            continue

        data = status.get("data", {})
        # 2 表示成功，5 表示部分成功
        if data.get("generateStatus") in [2, 5]:
            images = data.get("images", [])
            if images:
                img_url = images[0].get("imageUrl")
                img_data = requests.get(img_url).content
                img = Image.open(BytesIO(img_data))
                return img, time.time() - start_time

        # 如果任务失败 (例如状态码为 3 或 4)
        if data.get("generateStatus") in [3, 4]:
            st.error(f"❌ 生图任务失败，状态码：{data.get('generateStatus')}")
            break

        time.sleep(2)

    return None, 0

    # 轮询部分保持不变...
    # (注意轮询时的 uri 通常是 "/api/generate/webui/status")

    # ② 轮询结果 (逻辑保持不变)
    # ... 剩下的轮询逻辑 ...

def make_thumbnail(img, size=256):
    thumb = img.copy()
    thumb.thumbnail((size, size))
    return thumb


def chat_image_block(img, thumb, key):
    expand_key = f"{key}_expand"
    if expand_key not in st.session_state:
        st.session_state[expand_key] = False

    if not st.session_state[expand_key]:
        st.image(thumb, width=250) # 缩略图保持小尺寸
        if st.button("🔍 查看大图", key=f"{key}_btn"):
            st.session_state[expand_key] = True
            st.rerun()
    else:
        # 放大模式：显式限制图片尺寸（Streamlit 官方推荐做法）
        with st.container():
            st.image(
                img,
                width=600  # ✅ 关键：直接限制像素宽度
            )

        if st.button("⬅ 收起图片", key=f"{key}_close"):
            st.session_state[expand_key] = False
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


def save_record(username, mode, prompt, img, duration):
    # 1. 构造文件名
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}.png"

    # 2. 尝试保存（多路径兼容）
    try:
        # 路径 A：本地电脑桌面（适合你在自己电脑跑）
        path_local = Path.home() / "Desktop" / "AI_Generation_Records" / username / mode
        path_local.mkdir(parents=True, exist_ok=True)
        img.save(path_local / filename)
    except Exception:
        try:
            # 路径 B：当前程序所在目录（适合 GitHub/云端 部署跑）
            path_cloud = Path("records") / username / mode
            path_cloud.mkdir(parents=True, exist_ok=True)
            img.save(path_cloud / filename)
        except Exception as e:
            # 如果都失败了，仅在后台打印，不干扰用户生图
            print(f"保存记录失败: {e}")
# =========================
# 后续 UI / 三种模式代码
# =========================
# ⬇️ 以下全部保持你原样（未动）

# =========================
# 2. 界面增强 (CSS 与布局控制)
# =========================
def inject_custom_css():
    st.markdown("""
    <style>
    /* ================== 聊天行布局 ================== */
    .chat-row {
        display: flex;
        align-items: flex-start;
        margin-bottom: 20px;
        width: 100%;
    }
/* 放大图片的最大可视范围 */
.chat-image-large {
    max-width: 600px;        /* 控制“放大后”最大宽度 */
    margin: 12px 0;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #e5e7eb;
}

/* 防止图片纵向过高 */
.chat-image-large img {
    max-height: 520px;
    object-fit: contain;
}

    /* 用户：内容在右，头像在最右 */
    .chat-row.user {
        flex-direction: row-reverse; /* 关键：让头像和气泡顺序反转 */
    }

    /* AI：内容在左，头像在最左 */
    .chat-row.ai {
        flex-direction: row;
    }

    .chat-avatar {
        width: 38px;
        height: 38px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        margin: 0 12px;
        flex-shrink: 0;
        background: #f0f2f5;
    }

    /* 气泡通用样式 */
    .user-bubble, .ai-bubble {
        padding: 12px 16px;
        border-radius: 18px;
        max-width: 70%;
        line-height: 1.5;
        word-wrap: break-word;
    }

    .user-bubble {
        background-color: #007AFF;
        color: white;
        border-bottom-right-radius: 2px; /* 微信/ChatGPT 风格小尖角 */
    }

    .ai-bubble {
        background-color: #F2F2F7;
        color: black;
        border-bottom-left-radius: 2px;
    }

    /* ================== 图片放大控制 ================== */
    .chat-image-container {
        display: flex;
        flex-direction: column;
        align-items: flex-start; /* 默认居左 */
    }

    .chat-row.user .chat-image-container {
        align-items: flex-end; /* 用户生成的图居右 */
    }

    .chat-image-large {
        max-width: 800px; /* 限制最大宽度，不至于撑破界面 */
        width: 100%;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin: 10px 0;
    }

    .chat-image-large img {
        width: 100% !important;
        height: auto !important;
        display: block;
    }

    .block-container {
        max-width: 1200px;
        padding-top: 2.8rem;
    }
    </style>
    """, unsafe_allow_html=True)

# =========================
# 3. 页面配置与头部对齐
# =========================
st.set_page_config(page_title="AI Studio Pro", layout="wide")
inject_custom_css()

if "username" not in st.session_state: st.session_state.username = None

# 登录逻辑
if not st.session_state.username:
    st.markdown("<h2 style='text-align: center; margin-top: 100px;'>🎨 AI 智能实验站</h2>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1, 1])
    with col:
        with st.container(border=True):
            name = st.text_input("请输入姓名")
            if st.button("开始创作", use_container_width=True, type="primary"):
                if name.strip():
                    st.session_state.username = name.strip()
                    st.rerun()
    st.stop()

# --- 顶部导航栏 ---
head_l, head_m, head_r = st.columns([3, 5, 2])
with head_l:
    st.markdown('<p class="logo-text">✨ AI Hub Pro</p>', unsafe_allow_html=True)
with head_r:
    with st.popover(f"👤 {st.session_state.username}", use_container_width=True):
        if st.button("退出登录", use_container_width=True):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

# --- 侧边栏 ---
st.sidebar.title("控制面板")
ui_mode = st.sidebar.radio("模式切换", ["对话界面", "基础图形界面", "复杂图形界面"])

st.title(f"{ui_mode}")

# --- 模式 1：对话界面 (保持原逻辑) ---
if ui_mode == "对话界面":
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {"role": "assistant", "type": "text", "content": "您好！请输入提示词。"}
        ]

    # ===== 对话显示区（带头像）=====
    chat_box = st.container(border=False)
    with chat_box:
        for i, msg in enumerate(st.session_state.chat_history):

            # ========= 用户消息 =========
            if msg["role"] == "user":
                st.markdown(
                    f"""
                        <div class="chat-row user">
                            <div class="chat-avatar">🙂</div>
                            <div class="user-bubble">{msg["content"]}</div>
                        </div>
                        """,
                    unsafe_allow_html=True
                )

            # ========= AI 消息 =========
            else:
                # ---- 文本 ----
                if msg["type"] == "text":
                    st.markdown(
                        f"""
                        <div class="chat-row ai">
                            <div class="chat-avatar">🤖</div>
                            <div class="ai-bubble">{msg["content"]}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                # ---- 图片（无气泡、无头像）----
                else:
                    st.markdown(
                        """
                        <div class="chat-row ai" style="margin-left:44px;">
                        """,
                        unsafe_allow_html=True
                    )

                    chat_image_block(
                        img=msg["content"],
                        thumb=msg["thumb"],
                        key=f"chat_{i}"
                    )

                    buf = BytesIO()
                    msg["content"].save(buf, format="PNG")

                    st.download_button(
                        label="📥 下载图片",
                        data=buf.getvalue(),
                        file_name=f"chat_gen_{i}.png",
                        mime="image/png",
                        key=f"chat_dl_{i}"
                    )

                    st.markdown("</div>", unsafe_allow_html=True)

    # ===== 输入框 =====
    if prompt := st.chat_input("描述你想画的..."):
        # ① 先立刻显示用户消息
        st.session_state.chat_history.append(
            {"role": "user", "type": "text", "content": prompt}
        )
        st.rerun()

    # ===== AI 响应（检测最后一条）=====
    if st.session_state.chat_history[-1]["role"] == "user":
        last_prompt = st.session_state.chat_history[-1]["content"]

        with st.spinner("正在绘图..."):
            img, dur = generate_image(last_prompt)
            if img:
                save_record(st.session_state.username, ui_mode, last_prompt, img, dur)
                thumb = make_thumbnail(img)
                # ✅ 生成完成后的固定话术（灰色气泡）
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "type": "text",
                    "content": "我已经为你生成好了这张图，你可以查看或下载 👇"
                })

                # ✅ 紧接着加入图片
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "type": "image",
                    "content": img,
                    "thumb": thumb
                })

                st.rerun()



# --- 模式 2：基础图形界面 ---
elif ui_mode == "基础图形界面":
    col_l, col_r = st.columns([1, 1], gap="large")
    with col_l:
        st.subheader("指令")
        with st.container(border=True):
            p = st.text_area("提示词", height=150)
            btn = st.button("开始生成", use_container_width=True, type="primary")

    with col_r:
        st.subheader("生成区")

        with st.container(border=True):
            if btn and p:
                with st.spinner("正在生成中..."):
                    img, dur = generate_image(p)
                    if img:
                        st.session_state.b_img = img
                        st.session_state.b_thumb = make_thumbnail(img)

            if "b_img" in st.session_state and st.session_state.b_img:
                chat_image_block(
                    img=st.session_state.b_img,
                    thumb=st.session_state.b_thumb,
                    key="basic_img"
                )

                buf = BytesIO()
                st.session_state.b_img.save(buf, format="PNG")
                st.download_button(
                    "💾 下载图片",
                    buf.getvalue(),
                    "basic.png",
                    use_container_width=True
                )
            else:
                st.markdown(
                    "<div style='height:300px;display:flex;align-items:center;justify-content:center;color:#aaa;'>图片预览将在此显示</div>",
                    unsafe_allow_html=True
                )

# --- 模式 3：复杂图形界面 ---
# --- 模式 3：复杂图形界面 ---
# --- 模式 3：复杂图形界面（与基础界面同逻辑） ---
else:
    if "adv_img" not in st.session_state:
        st.session_state.adv_img = None
        st.session_state.adv_thumb = None

    col_l, col_r = st.columns([1, 1.2], gap="large")

    # ================= 左侧：专家参数 =================
    with col_l:
        st.subheader("指令")

        with st.container(border=True):
            adv_p = st.text_area("Prompt", height=120)

            t1, t2 = st.tabs(["尺寸 / 步数", "高级采样"])

            with t1:
                steps = st.slider("步数", 10, 50, 20)
                w = st.selectbox("宽度", [512, 768, 1024])
                h = st.selectbox("高度", [512, 768, 1024])

            with t2:
                cfg = st.slider("CFG Scale", 1, 20, 7)
                sampler = st.selectbox(
                    "采样器",
                    ["Euler a", "DPM++ 2M Karras"]
                )

            render_btn = st.button(
                "开始渲染",
                use_container_width=True,
                type="primary"
            )

    # ================= 右侧：生成区（完全照基础界面） =================
    with col_r:
        st.subheader("生成区")

        with st.container(border=True):

            # ✅ 生成逻辑：和基础界面一模一样
            if render_btn and adv_p.strip():
                with st.spinner("正在生成中..."):
                    img, dur = generate_image({
                        "prompt": adv_p,
                        "steps": steps,
                        "cfg_scale": cfg,
                        "width": w,
                        "height": h,
                        "sampler_name": sampler
                    })

                    if img:
                        save_record(
                            st.session_state.username,
                            ui_mode,
                            adv_p,
                            img,
                            dur
                        )
                        st.session_state.adv_img = img
                        st.session_state.adv_thumb = make_thumbnail(img)

            # ✅ 展示逻辑
            if st.session_state.adv_img:
                chat_image_block(
                    img=st.session_state.adv_img,
                    thumb=st.session_state.adv_thumb,
                    key="adv_img"
                )

                buf = BytesIO()
                st.session_state.adv_img.save(buf, format="PNG")
                st.download_button(
                    "💾 下载高清原图",
                    buf.getvalue(),
                    "advanced.png",
                    use_container_width=True
                )
            else:
                st.markdown(
                    "<div style='height:300px;display:flex;align-items:center;justify-content:center;color:#aaa;'>图片预览将在此显示</div>",
                    unsafe_allow_html=True
                )



