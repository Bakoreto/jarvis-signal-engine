from flask import Flask, request, jsonify
import anthropic
import requests
import os
import json
from datetime import datetime, timezone

app = Flask(__name__)

# === CONFIGURACIÓN ===
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MIN_SCORE = float(os.environ.get("MIN_SCORE", "7.5"))
MIN_RR = float(os.environ.get("MIN_RR", "2.0"))

JARVIS_SYSTEM_PROMPT = """Eres JARVIS, una mesa de trading institucional especializada en señales de alta probabilidad.
Analizas mercados usando metodología ICT/Smart Money con los siguientes conceptos:
BOS, CHoCH, Liquidity Sweeps, FVG, Order Blocks, Multi Timeframe Bias, Fibonacci, RR institucional.

KILL ZONES (UTC):
- Asia: 00:00-04:00 (BTC, ETH, JPY pairs)
- London Open: 07:00-09:00 (Forex, GOLD, índices EU)
- London/NY Overlap: 12:00-16:00 (Todos los mercados)
- New York: 12:00-14:00 (US100, SP500, GOLD)
- NY PM: 15:00-17:00 (Cierres institucionales)

FILTROS OBLIGATORIOS - NO emitir señal si:
- RR menor a 1:2
- Score menor a 7.5/10
- Estructura ambigua
- Sin confirmación HTF
- Sin sweep de liquidez
- Fuera de Kill Zone (salvo score >= 9.0)

SCORE PONDERADO (máx 10):
- BOS o CHoCH confirmado: +2.0
- Sweep de liquidez: +2.0
- Confluencia HTF D1/H4: +1.5
- OB o FVG de calidad: +1.0
- Kill Zone activa: +1.0
- Momentum alineado: +0.5
- RR >= 1:3: +0.5
- Volumen confirmatorio: +0.5

Responde ÚNICAMENTE en JSON con esta estructura exacta (sin markdown, sin texto extra):
{
  "symbol": "BTCUSDT",
  "direction": "LONG",
  "score": 8.2,
  "entry": 105000,
  "sl": 104200,
  "tp1": 106200,
  "tp2": 107500,
  "tp3": 109000,
  "rr": 3.1,
  "sesgo_htf": "ALCISTA",
  "estructura": ["BOS M15", "Sweep SSL", "FVG reclaim"],
  "confirmaciones": ["Momentum alcista", "Confluencia H4", "Kill Zone activa"],
  "invalidacion": "Cierre bajo OB M15 en 104500",
  "macro": "Sin eventos próximos",
  "kill_zone": "London/NY Overlap",
  "emitir": true,
  "motivo_no_emision": null
}"""

KILL_ZONES = [
    {"name": "Asia", "start": 0, "end": 4},
    {"name": "London Open", "start": 7, "end": 9},
    {"name": "London/NY Overlap", "start": 12, "end": 16},
    {"name": "New York", "start": 12, "end": 14},
    {"name": "NY PM", "start": 15, "end": 17},
]

def get_active_kill_zone():
    hour = datetime.now(timezone.utc).hour
    for kz in KILL_ZONES:
        if kz["start"] <= hour < kz["end"]:
            return kz["name"]
    return None

def analyze_with_jarvis(data):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    hour = datetime.now(timezone.utc).hour
    kz = get_active_kill_zone()

    user_message = f"""Analiza {data.get('symbol', 'UNKNOWN')} para señal institucional.

Datos del webhook de TradingView:
- Símbolo: {data.get('symbol')}
- Precio actual: {data.get('close', data.get('price', 'N/D'))}
- Open: {data.get('open', 'N/D')}
- High: {data.get('high', 'N/D')}
- Low: {data.get('low', 'N/D')}
- Volumen: {data.get('volume', 'N/D')}
- Timeframe: {data.get('timeframe', 'N/D')}
- RSI: {data.get('rsi', 'N/D')}
- EMA 20: {data.get('ema20', 'N/D')}
- EMA 50: {data.get('ema50', 'N/D')}
- ATR: {data.get('atr', 'N/D')}
- Señal Pine Script: {data.get('signal', 'N/D')}
- Hora UTC actual: {hour}:00
- Kill Zone activa: {kz or 'Ninguna'}

Aplica todos los filtros JARVIS. Score mínimo: {MIN_SCORE}. RR mínimo: {MIN_RR}.
Responde solo JSON."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=JARVIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

def send_telegram(signal):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    bar = "█" * round(signal["score"]) + "░" * (10 - round(signal["score"]))
    direction_emoji = "🟢" if signal["direction"] == "LONG" else "🔴"
    fmt = lambda n: f"{float(n):.4f}" if n and float(n) < 100 else (f"{float(n):.2f}" if n else "—")

    msg = f"""━━━━━━━━━━━━━━━━━━━━━━━
🎯 JARVIS SIGNAL
━━━━━━━━━━━━━━━━━━━━━━━

📊 {signal['symbol']} {direction_emoji} {signal['direction']}
🕐 Sesión: {signal.get('kill_zone', 'N/D')}

📈 SESGO HTF: {signal.get('sesgo_htf', '—')}

🧱 ESTRUCTURA:
{chr(10).join(['✅ ' + e for e in signal.get('estructura', [])])}

💰 ENTRADA: {fmt(signal.get('entry'))}
🛑 STOP LOSS: {fmt(signal.get('sl'))}

🎯 TAKE PROFITS:
TP1 (40%): {fmt(signal.get('tp1'))}
TP2 (35%): {fmt(signal.get('tp2'))}
TP3 (25%): {fmt(signal.get('tp3'))}

📐 RR: 1:{signal.get('rr', '—')}

✅ CONFIRMACIONES:
{chr(10).join(['✅ ' + c for c in signal.get('confirmaciones', [])])}

❌ INVALIDACIÓN: {signal.get('invalidacion', '—')}

⚠️ MACRO: {signal.get('macro', 'Sin eventos')}

🏆 SCORE: {signal.get('score', '—')}/10
[{bar}]

💼 RIESGO: 1% del capital

━━━━━━━━━━━━━━━━━━━━━━━
JARVIS Institutional Desk"""

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    )

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "JARVIS Signal Engine activo", "version": "2.0"})

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data"}), 400

        signal = analyze_with_jarvis(data)

        if signal.get("emitir") and signal.get("score", 0) >= MIN_SCORE:
            send_telegram(signal)
            return jsonify({"status": "signal_sent", "signal": signal}), 200
        else:
            return jsonify({
                "status": "no_signal",
                "score": signal.get("score"),
                "motivo": signal.get("motivo_no_emision")
            }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "kill_zone": get_active_kill_zone(), "time_utc": datetime.now(timezone.utc).strftime("%H:%M")}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
