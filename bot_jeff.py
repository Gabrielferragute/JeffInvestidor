import os
import sys
import asyncio
import threading
import requests
import yfinance as yf
from io import StringIO
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update
from telegram.error import BadRequest
from telegram.request import HTTPXRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types

# Carregar variáveis de ambiente
load_dotenv()

TELEGRAM_TOKEN = os.getenv("JEFF_TELEGRAM_TOKEN")
ALLOWED_USER_ID = os.getenv("JEFF_ALLOWED_USER_ID")
GEMINI_API_KEY = os.getenv("JEFF_LLM_API_KEY")

def load_user_profile() -> str:
    """Carrega o perfil financeiro do usuário sem versioná-lo no Git.

    Prioridade: variável JEFF_USER_PROFILE (deploy) > arquivo perfil.md (local).
    """
    env_profile = os.getenv("JEFF_USER_PROFILE")
    if env_profile:
        return env_profile.replace("\\n", "\n").strip()
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfil.md")
    if os.path.exists(profile_path):
        with open(profile_path, encoding="utf-8") as f:
            return f.read().strip()
    print("[AVISO] Nenhum perfil encontrado (JEFF_USER_PROFILE ou perfil.md). Usando perfil genérico.", flush=True)
    return "User Profile: not provided. Ask the user about income, monthly contribution and goals before giving personalized advice."

USER_PROFILE = load_user_profile()

SYSTEM_PROMPT = f"""
You are "Jeff", a Senior Financial Analyst and Capital Allocator acting as a personal investment co-pilot. Your primary goal is to help the user build wealth safely, protect capital, and achieve long-term financial independence.

You combine the mental models of legendary investors (Ray Dalio, Warren Buffett, Charlie Munger, Nassim Taleb) with sharp, practical execution in the Brazilian and global financial markets.

{USER_PROFILE}

Whenever the user asks for investment advice, market evaluation, or asset analysis, you MUST ALWAYS respond strictly using the following 5-part structure (formatted in Markdown):

📊 **Resumo rápido da situação**
[Concise summary]

📈 **Oportunidade**
[Technical advantages]

⚠️ **Riscos**
[Specific risks]

🧠 **Estratégia recomendada**
[Actionable step-by-step]

⏳ **Horizonte de tempo**
[Clear timeline]

Use tools for any market data (Selic, BTC, B3) or math projections (compound interest, tax). Do not guess. Do NOT make up any market data.
"""

# ==============================================================================
# FERRAMENTAS FINANCEIRAS (TOOLS)
# ==============================================================================

def get_taxa_selic() -> str:
    """Busca a taxa Selic/CDI anual mais recente diretamente da API oficial do Banco Central do Brasil."""
    print("[DEBUG Tool] Executando get_taxa_selic()", flush=True)
    try:
        req = requests.get('https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json', timeout=5)
        data = req.json()
        return f"Selic Meta: {data[0]['valor']}% (Data: {data[0]['data']})"
    except Exception as e:
        print(f"[DEBUG Tool Error] get_taxa_selic: {str(e)}", flush=True)
        return f"Error fetching Selic: {str(e)}"

def get_bitcoin_price() -> str:
    """Busca a cotação em tempo real do Bitcoin em Reais (BRL) via CoinGecko."""
    print("[DEBUG Tool] Executando get_bitcoin_price()", flush=True)
    try:
        req = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=brl', timeout=5)
        data = req.json()
        return f"Bitcoin Price (BRL): R$ {data['bitcoin']['brl']}"
    except Exception as e:
        print(f"[DEBUG Tool Error] get_bitcoin_price: {str(e)}", flush=True)
        return f"Error fetching BTC price: {str(e)}"

def get_asset_price(ticker: str) -> str:
    """Busca a cotação mais recente de ações, FIIs e ETFs da B3 (ex: 'PETR4', 'MXRF11')."""
    print(f"[DEBUG Tool] Executando get_asset_price('{ticker}')", flush=True)
    try:
        clean_ticker = ticker.strip().upper()
        if not clean_ticker.endswith('.SA') and '.' not in clean_ticker:
            clean_ticker = f"{clean_ticker}.SA"
        asset = yf.Ticker(clean_ticker)
        price = asset.history(period="1d")['Close'].iloc[-1]
        return f"Price of {clean_ticker}: R$ {price:.2f}"
    except Exception as e:
        print(f"[DEBUG Tool Error] get_asset_price: {str(e)}", flush=True)
        return f"Error fetching asset price for {ticker}: {str(e)}"

def code_interpreter(python_code: str) -> str:
    """Executa script Python para matemática financeira (juros compostos, projeções, impostos). Retorna o output impresso."""
    print(f"[DEBUG Tool] Executando code_interpreter:\n{python_code}", flush=True)
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    try:
        exec(python_code, {})
        sys.stdout = old_stdout
        out = redirected_output.getvalue()
        print(f"[DEBUG Tool Output] code_interpreter: {out}", flush=True)
        return out
    except Exception as e:
        sys.stdout = old_stdout
        print(f"[DEBUG Tool Error] code_interpreter: {str(e)}", flush=True)
        return f"Error executing Python code: {str(e)}"

# Configuração do Gemini Model com Function Calling
config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[get_taxa_selic, get_bitcoin_price, get_asset_price, code_interpreter]
)

# Cliente Gemini inicializado sob demanda ou na carga
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def get_gemini_client():
    global client
    if client is None:
        key = os.getenv("JEFF_LLM_API_KEY")
        if not key:
            raise ValueError("JEFF_LLM_API_KEY não configurada no ambiente.")
        client = genai.Client(api_key=key)
    return client

def process_llm_response(user_id: str, user_text: str) -> str:
    print(f"[DEBUG] process_llm_response iniciado para user_id {user_id}", flush=True)
    
    # Modelos disponíveis com prioridade configurável
    custom_model = os.getenv("GEMINI_MODEL")
    models_to_try = []
    if custom_model:
        models_to_try.append(custom_model)
    models_to_try.extend([
        'gemini-2.5-flash',
        'gemini-2.0-flash',
        'gemini-3-flash-preview',
        'gemini-3.5-flash',
        'gemini-3.6-flash',
        'gemini-flash-latest'
    ])
    
    last_error = None
    ai_client = get_gemini_client()
    for model_name in models_to_try:
        try:
            print(f"[DEBUG] Chamando modelo {model_name}...", flush=True)
            chat = ai_client.chats.create(
                model=model_name,
                config=config
            )
            response = chat.send_message(user_text)
            print(f"[DEBUG] Resposta gerada com sucesso pelo {model_name}", flush=True)
            return response.text
        except Exception as e:
            print(f"[DEBUG Warning] Falha no modelo {model_name}: {str(e)}", flush=True)
            last_error = e
            continue
            
    return f"Erro ao processar resposta da IA: {str(last_error)}"

# ==============================================================================
# TELEGRAM BOT HANDLERS
# ==============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return
        
    user_id = str(update.message.from_user.id)
    if user_id != str(ALLOWED_USER_ID):
        print(f"[DEBUG] Acesso negado para User ID: {user_id}", flush=True)
        await update.message.reply_text(f"⛔ Acesso negado. Seu ID ({user_id}) não está autorizado.")
        return

    welcome_text = (
        "💼 *Olá! Eu sou o Jeff, seu copiloto e analista de investimentos.*\n\n"
        "Minha missão é guiar sua jornada rumo à liberdade financeira com alocação inteligente de capital, "
        "gestão de risco e foco no longo prazo.\n\n"
        "📊 *Metodologia:*\n"
        "• Modelos mentais de Ray Dalio, Warren Buffett, Charlie Munger e Nassim Taleb.\n"
        "• Estratégia em fases: Reserva de Emergência (CDB 100% CDI) ➔ Ativos Geradores de Renda.\n"
        "• Regra dos 20% de aporte mensal.\n\n"
        "🛠 *Ferramentas integradas em tempo real:*\n"
        "• 🏦 Taxa Selic oficial (Banco Central do Brasil)\n"
        "• ₿ Cotação do Bitcoin (CoinGecko)\n"
        "• 📈 Cotações de ações e FIIs da B3 (Yahoo Finance)\n"
        "• 🧮 Cálculos avançados via Python (juros compostos, prazos, impostos)\n\n"
        "💬 *Como começar:* Envie sua dúvida em texto livre! Exemplos:\n"
        "_\"Qual é a Selic hoje e quanto rende meu aporte mensal no CDB?\"_\n"
        "_\"Vale a pena aportar em MXRF11 agora?\"_\n"
        "_\"Analise os riscos de investir em PETR4 no momento.\"_"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return
        
    user_id = str(update.message.from_user.id)
    if user_id != str(ALLOWED_USER_ID):
        await update.message.reply_text(f"⛔ Acesso negado. Seu ID ({user_id}) não está autorizado.")
        return

    help_text = (
        "ℹ️ *Guia de Uso do Jeff:*\n\n"
        "*Comandos disponíveis:*\n"
        "• /start - Boas-vindas e introdução ao bot\n"
        "• /help - Exibe este guia de ajuda\n\n"
        "*Estrutura das análises (5 blocos):*\n"
        "1. 📊 Resumo rápido da situação\n"
        "2. 📈 Oportunidade\n"
        "3. ⚠️ Riscos\n"
        "4. 🧠 Estratégia recomendada\n"
        "5. ⏳ Horizonte de tempo\n\n"
        "Basta me enviar mensagens diretamente no chat para obter análises detalhadas."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return
        
    user_id = str(update.message.from_user.id)
    print(f"[DEBUG] Recebida mensagem de User ID: '{user_id}' | Texto: '{update.message.text}'", flush=True)
    
    if user_id != str(ALLOWED_USER_ID):
        print(f"[DEBUG] Acesso negado para User ID: {user_id}", flush=True)
        await update.message.reply_text(f"⛔ Acesso negado. Seu ID ({user_id}) não está autorizado.")
        return

    # Send typing action (protegido contra falhas temporárias de proxy)
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    except Exception as e:
        print(f"[DEBUG Warning] Ignorando falha no send_chat_action: {e}", flush=True)
    
    user_text = update.message.text
    try:
        loop = asyncio.get_running_loop()
        reply_text = await loop.run_in_executor(None, process_llm_response, user_id, user_text)
    except Exception as e:
        reply_text = f"❌ Erro interno no processamento: {str(e)}"

    # Envio da resposta com retentativas para contornar erros temporários
    for send_attempt in range(3):
        try:
            await update.message.reply_text(reply_text, parse_mode='Markdown')
            break
        except BadRequest:
            await update.message.reply_text(reply_text)
            break
        except Exception as e:
            print(f"[DEBUG Warning] Tentativa {send_attempt + 1} de envio falhou ({e}). Tentando novamente...", flush=True)
            await asyncio.sleep(1)

# ==============================================================================
# HTTP HEALTH CHECK SERVER (Render / Railway / Heroku / Fly.io)
# ==============================================================================

def run_health_server():
    class HealthCheckHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"OK - Jeff Bot is running.")

        def log_message(self, format, *args):
            return  # Silenciar logs do HTTP server

    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"Health check HTTP server rodando na porta {port}...", flush=True)
    server.serve_forever()

# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================

def main():
    if not all([TELEGRAM_TOKEN, ALLOWED_USER_ID, GEMINI_API_KEY]):
        print("ERRO: Variáveis de ambiente faltando no .env (JEFF_TELEGRAM_TOKEN, JEFF_ALLOWED_USER_ID, JEFF_LLM_API_KEY)")
        sys.exit(1)

    threading.Thread(target=run_health_server, daemon=True).start()
    
    print("Iniciando Bot do Jeff com Google GenAI SDK...", flush=True)
    
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    if proxy_url:
        print(f"Detectado servidor proxy ({proxy_url}). Configurando HTTPXRequest com timeouts estendidos...", flush=True)
        request = HTTPXRequest(
            proxy=proxy_url,
            connect_timeout=20.0,
            read_timeout=20.0,
            write_timeout=20.0,
            pool_timeout=20.0
        )
        application = Application.builder().token(TELEGRAM_TOKEN).request(request).build()
    else:
        application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot online. Aguardando mensagens...", flush=True)
    application.run_polling(bootstrap_retries=-1, poll_interval=1.0)

if __name__ == '__main__':
    main()
