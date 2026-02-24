import logging
import threading
from flask import Flask
from src.config.settings import settings
from src.scrapers.homeserve_scraper import HomeServeScrapers
from src.bot.telegram_client import TelegramClient
from src.bot.homeserve_bot import HomeServeBot

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Servidor web requerido por Render
app = Flask(__name__)

@app.route("/")
def home():
    return "HomeServe Bot funcionando"


def iniciar_bot():

    try:

        settings.validate()

        scraper = HomeServeScrapers(
            usuario=settings.USUARIO,
            password=settings.PASSWORD,
            login_url=settings.LOGIN_URL,
            asignacion_url=settings.ASIGNACION_URL
        )

        telegram = TelegramClient(
            bot_token=settings.BOT_TOKEN,
            chat_id=settings.CHAT_ID,
            api_url=settings.TELEGRAM_API_URL
        )

        bot = HomeServeBot(
            scraper=scraper,
            telegram=telegram,
            intervalo=settings.INTERVALO_SEGUNDOS
        )

        bot.iniciar()

    except Exception as e:

        logger.error(f"Error iniciando bot: {e}")


# Ejecutar bot en segundo plano
threading.Thread(target=iniciar_bot, daemon=True).start()


if __name__ == "__main__":

    import os

    port = int(os.environ.get("PORT", 10000))

    app.run(host="0.0.0.0", port=port)
