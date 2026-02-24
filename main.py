import logging
from src.config.settings import settings
from src.scrapers.homeserve_scraper import HomeServeScrapers
from src.bot.telegram_client import TelegramClient
from src.bot.homeserve_bot import HomeServeBot


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def main():

    settings.validate()

    scraper = HomeServeScrapers(
        usuario=settings.USUARIO,
        password=settings.PASSWORD,
        login_url=settings.LOGIN_URL,
        asignacion_url=settings.ASIGNACION_URL
    )

    telegram = TelegramClient(
        bot_token=settings.BOT_TOKEN,
        chat_id=settings.CHAT_ID
    )

    bot = HomeServeBot(
        scraper,
        telegram,
        intervalo=settings.INTERVALO_SEGUNDOS
    )

    bot.iniciar()


if __name__ == "__main__":
    main()
