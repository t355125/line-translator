import os
import requests

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

VOCAB_PROMPT = """請幫一位正在學西班牙文的台灣人,出今天的 10 個西班牙文單字(A1~A2 程度)。

重要:這是要發到 LINE 的純文字訊息,LINE 不支援 Markdown。
絕對不要使用任何 * 星號、# 井號、` 反引號等符號來做粗體或標題。
只能用文字、emoji、和「─」線條來排版。

要求:
- 動詞、名詞、常用字都可以混搭,盡量每天不同、生活化實用。
- 每個單字用下面這個格式(照抄這個排版,不要加星號):

1️⃣ desayunar(動詞)
　意思:吃早餐
　變化:desayuno(我)/ desayunas(你)
　搭配:desayunar + 食物
　例句:Desayuno pan con café.
　　　　我吃麵包配咖啡。
───────────

(第 2 個用 2️⃣、第 3 個用 3️⃣,以此類推到 🔟)

格式細節:
- 動詞:標「(動詞)」,附現在式常用變化(我/你),有固定介詞就寫在「搭配」。
- 名詞:標「(名詞・陽性)」或「(名詞・陰性)」,附單複數(el/la、-s)。
- 每個字都要一個 A1~A2 生活化例句,西語一行、中文一行。
- 每個單字之間用「───────────」分隔。
- 行首用全形空格「　」縮排,讓層次清楚。

最後附一句今日鼓勵小語。整體用繁體中文說明,直接輸出,不要開場白。"""


def get_vocab():
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": VOCAB_PROMPT}],
    }
    r = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()


def broadcast(text):
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"messages": [{"type": "text", "text": text[:4900]}]}
    r = requests.post(LINE_BROADCAST_URL, headers=headers, json=payload, timeout=15)
    r.raise_for_status()


if __name__ == "__main__":
    body = get_vocab()
    message = "📚 今日西語單字 (A1~A2)\n━━━━━━━━━━\n\n" + body
    broadcast(message)
    print("推播完成")
