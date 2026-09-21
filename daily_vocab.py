import os
import requests

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

VOCAB_PROMPT = """請幫一位正在學西班牙文的台灣人,出今天的 10 個西班牙文單字(A1~A2 程度)。
要求:
- 動詞、名詞、常用字都可以混搭,盡量每天不同、生活化實用。
- 每個單字用下面這個格式,簡潔清楚:

[序號]. [西語單字] ([詞性縮寫])
   ▪ 意思:[中文]
   ▪ 若是動詞:標原形,附一個現在式變化例(如 hablar → hablo 我說)
   ▪ 若是名詞:標陰陽性(el/la),單複數變化
   ▪ 常搭介詞/用法:[如 pensar en、ir a,若無則略]
   ▪ 例句:[A1~A2 西語短句] → [中文]

最後附一句今日鼓勵小語。
整體用繁體中文說明,直接輸出內容,不要多餘開場白。"""


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
