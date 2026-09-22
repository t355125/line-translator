import os
import json
import hmac
import hashlib
import base64
import requests
from flask import Flask, request, abort

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

# ===== 問答紀錄設定 =====
MY_USER_ID = "U8730208994c8ae0d56900870d60d3280"  # 只存這個人問的
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")   # 在 Render 環境變數設定
GITHUB_REPO = os.environ.get("GITHUB_REPO", "t355125/line-translator")
QA_PATH = "docs/qa_log.json"


def save_qa(question, answer, source):
    """把一則問答 append 進 GitHub 的 docs/qa_log.json。失敗不影響主流程。"""
    if not GITHUB_TOKEN:
        return
    import datetime
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{QA_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    try:
        # 讀現有內容
        r = requests.get(api, headers=headers, timeout=15)
        if r.status_code == 200:
            info = r.json()
            sha = info["sha"]
            current = json.loads(base64.b64decode(info["content"]).decode("utf-8"))
            if not isinstance(current, list):
                current = []
        elif r.status_code == 404:
            sha = None
            current = []
        else:
            return
        # 新增一筆(最新在前),上限保留 500 筆
        tw = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        current.insert(0, {
            "id": tw.strftime("%Y%m%d%H%M%S") + str(len(current)),
            "q": question[:2000],
            "a": answer[:5000],
            "source": source,
            "time": tw.strftime("%Y-%m-%d %H:%M"),
        })
        current = current[:500]
        new_content = base64.b64encode(
            json.dumps(current, ensure_ascii=False, indent=1).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": "add qa log", "content": new_content}
        if sha:
            payload["sha"] = sha
        requests.put(api, headers=headers, json=payload, timeout=15)
    except Exception:
        pass  # 存紀錄失敗不影響回覆

SYSTEM_PROMPT = """你是一個聰明的翻譯兼語言學習助理,服務對象是一位在台灣做防水與建材、正拓展東南亞市場、同時正在學西班牙文的商務人士。你要先判斷使用者這則訊息屬於哪一種,再決定怎麼回。

【重要:輸出格式限制】
你的回覆會發到 LINE,LINE 不支援 Markdown。
絕對不要用 * 星號、# 井號、` 反引號 做粗體或標題,那些符號會原樣顯示變成亂碼。
只能用文字、emoji、和「─」線條、全形空格「　」縮排來排版。

【判斷訊息類型】
A. 翻譯需求:想把某段話翻成另一種語言(有明講目標語言,或就是丟一段話進來)。支援中英日泰緬越西等各語言互翻。
B. 文法/單字問題:在問某個字、某個變化、某個文法點,例如「dan 是什麼」「damos 怎麼來的」「del 跟 de 差在哪」「這個動詞怎麼變位」。特別是西班牙文的學習提問。
C. 一般對話:問你問題、想討論、要建議。

【A. 翻譯需求時】
1. 目標語言:有指定就翻指定語言;沒指定時,中文→西班牙文,西班牙文→繁體中文,其他語言→繁體中文。使用者現在主力學西班牙文,所以中文預設一律翻成西班牙文,不要翻成英文,除非使用者明講要英文。
2. 場合判斷:商務/客戶/正式文件就翻得正式專業;日常口語就翻得自然。
3. 格式:第一行給翻譯結果,接著空一行用「💡」開頭給一則簡短提醒(更道地講法、語氣或文化提醒),沒必要就不加。

【B. 文法/單字問題時——用「拆解卡片」格式回,這是重點】
針對西班牙文(或其他語言)的字詞,用下面這種純文字卡片回覆(不要用星號):

📖 damos(動詞變化形)
───────────
　意思:我們給
　原形:dar(給)
　變化:dar 現在式・第一人稱複數(nosotros)
　搭配:dar + 東西 + a + 對象
　例句:Damos las gracias a todos.
　　　　我們向大家道謝。

如果使用者一次問好幾個字(例如「dan mos del」),就每個字各給一張卡片,中間用「───────────」隔開,簡潔即可。

【C. 一般對話時】
像懂多國語言和商務溝通的顧問,自然回答、給建議、討論,不套格式。

【共通原則】
- 用繁體中文跟使用者溝通(翻譯出的目標語言內容除外)。
- 西語例句盡量用 A1~A2 程度、生活化的句子。
- 專業親切,不囉嗦。拿不準就以翻譯為主,並在提醒裡順帶問一句。"""


def call_claude(user_text, system=SYSTEM_PROMPT, max_tokens=1500):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_text}],
    }
    r = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=40)
    r.raise_for_status()
    data = r.json()
    parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip() or "(處理失敗,請再試一次)"


def call_claude_chat(messages, system, max_tokens=1000):
    """支援多輪對話:messages 是 [{role, content}, ...]"""
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    r = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=40)
    r.raise_for_status()
    data = r.json()
    parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip() or "(處理失敗,請再試一次)"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:4900]}],
    }
    requests.post(LINE_REPLY_URL, headers=headers, json=payload, timeout=15)


def reply_to_line(reply_token, text):
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:4900]}],
    }
    requests.post(LINE_REPLY_URL, headers=headers, json=payload, timeout=15)


def verify_signature(body_bytes, signature):
    mac = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"), body_bytes, hashlib.sha256
    ).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")


@app.route("/", methods=["GET"])
def health():
    return "OK", 200


EXPLAIN_PROMPT = """你是西班牙文老師。使用者會給你一個西班牙文單字,請針對它輸出「純文字」的完整拆解(不要 markdown 星號),內容:

如果是動詞,格式如下(每個人稱都要:變位 + 簡易英文拼音發音 + 一句 A1~A2 例句與中文):
單字(動詞) — 中文意思

▪ yo [變位] (發音)
　[西語例句] / [中文]
▪ tú [變位] (發音)
　[西語例句] / [中文]
▪ él/ella [變位] (發音)
　[西語例句] / [中文]
▪ nosotros [變位] (發音)
　[西語例句] / [中文]
▪ vosotros [變位] (發音)
　[西語例句] / [中文]
▪ ellos/ellas [變位] (發音)
　[西語例句] / [中文]

發音用簡易英文拼音,重音節大寫,例如 voy→(BOY)、hablamos→(ah-BLAH-mos),讓人一看就會念。

如果是名詞:
單字(名詞・陰性/陽性) — 中文意思
　單數:el/la ... (發音)
　複數:los/las ... (發音)
例句:一句 A1~A2 西語 / 中文

如果是其他詞性:給意思、發音、用法、一個例句即可。
直接輸出,不要開場白。"""


@app.route("/explain", methods=["GET"])
def explain():
    word = (request.args.get("word") or "").strip()
    if not word:
        resp = app.make_response(json.dumps({"error": "no word"}, ensure_ascii=False))
    else:
        try:
            text = call_claude(word, system=EXPLAIN_PROMPT, max_tokens=1500)
        except Exception as e:
            text = f"(載入失敗:{e})"
        resp = app.make_response(json.dumps({"word": word, "detail": text}, ensure_ascii=False))
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Access-Control-Allow-Origin"] = "*"  # 允許 GitHub Pages 網頁呼叫
    return resp


@app.route("/ask", methods=["POST", "OPTIONS"])
def ask():
    # 瀏覽器跨網域預檢請求
    if request.method == "OPTIONS":
        resp = app.make_response("")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        data = request.get_json(force=True) or {}
        messages = data.get("messages", [])
        system = data.get("system", "你是西班牙文老師,用繁體中文回答。")
        if not isinstance(messages, list) or not messages:
            raise ValueError("no messages")
        # 安全上限:最多保留最近 20 則、system 長度設限
        messages = messages[-20:]
        system = str(system)[:4000]
        text = call_claude_chat(messages, system=system, max_tokens=1000)
        # 存網站問答紀錄
        try:
            last_q = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_q = str(m.get("content", ""))
                    break
            if last_q:
                save_qa(last_q, text, "網站")
        except Exception:
            pass
    except Exception as e:
        text = f"(伺服器錯誤:{e})"

    resp = app.make_response(json.dumps({"reply": text}, ensure_ascii=False))
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/qa", methods=["GET"])
def qa():
    """讓網站讀取問答紀錄"""
    hdr = {"Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*"}
    content = "[]"
    if GITHUB_TOKEN:
        api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{QA_PATH}"
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        try:
            r = requests.get(api, headers=headers, timeout=15)
            if r.status_code == 200:
                content = base64.b64decode(r.json()["content"]).decode("utf-8")
        except Exception:
            pass
    resp = app.make_response(content)
    for k, v in hdr.items():
        resp.headers[k] = v
    return resp


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    if not verify_signature(body, signature):
        abort(400)

    events = json.loads(body).get("events", [])
    for event in events:
        if event.get("type") == "message" and event["message"].get("type") == "text":
            user_text = event["message"]["text"].strip()
            reply_token = event["replyToken"]
            user_id = event.get("source", {}).get("userId", "")

            # 方便你取得自己的 user ID(雖然推播用 broadcast 不需要,留著備用)
            if user_text in ("我的id", "我的ID", "myid"):
                reply_to_line(reply_token, f"你的 user ID:\n{user_id or '(取不到)'}")
                continue

            # 快捷:打 esp 回網站連結
            if user_text.lower() in ("esp", "網站", "單字庫", "西語"):
                reply_to_line(
                    reply_token,
                    "📖 你的西語學習網站:\nhttps://t355125.github.io/line-translator/",
                )
                continue

            try:
                result = call_claude(user_text)
            except Exception as e:
                result = f"(發生錯誤:{e})"
            reply_to_line(reply_token, result)
            # 只存你本人問的問答紀錄
            if user_id == MY_USER_ID:
                save_qa(user_text, result, "LINE")

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
