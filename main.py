import io, logging

from datetime import datetime
from os import path

import telegram.ext as ext

from module.consts import *
import module.schedule as schedule
import module.helper as h

# ==============================
#  Setup the logging
# ==============================

logging.basicConfig(
	level=logging.INFO,
	format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
	handlers=(
		logging.StreamHandler(),
		logging.FileHandler(path.join(LOGS_DIR, "latest.log"), "w"),
		logging.FileHandler(path.join(LOGS_DIR, f"{datetime.now():%Y.%m.%d %H:%M}.log"), "w")
	)
)

LOG = logging.getLogger("bot")
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.WARN)
logging.getLogger("apscheduler").setLevel(logging.WARN)

# ==============================
#  MAIN
# ==============================

if __name__ == '__main__':
	TOKEN: str = None # pyright: ignore[reportAssignmentType]
	with io.open(TOKEN_FILE, "r") as file:
		TOKEN = file.readline() # pyright: ignore[reportConstantRedefinition]
	if type(TOKEN) is not str:
		raise Exception("No Telegram bot token provided")

	app = ext.ApplicationBuilder().token(TOKEN).build()
	app.add_handlers((
		ext.CommandHandler("start", h.on_start, block=False),
		h.make_handler(h.today_cmd_h, h.TODAY_CMD, block=False),
		h.make_handler(h.tomorrow_cmd_h, h.TOMORROW_CMD, block=False),
		h.make_handler(h.now_cmd_h, h.NOW_CMD, block=False),
		h.make_handler(h.schedule_cmd_h, h.SCHEDULE_CMD, block=False),
		h.make_handler(h.help_cmd_h, h.HELP_CMD, block=False),
	))

	async def _app_post_init(_):
		schedule.reload_schedule(
			h.MAIN_SCHEDULE, path.join(CONFIG_DIR, SCHEDULE_FILE), LOG
		)
		
		success = await h.registry_commands(app.bot)
		LOG.info(f"Bot commands setup success: {success}")
		if not success:
			LOG.error("Bot command initialization failed")
			return await app.shutdown()

	async def _app_post_stop(_):
		await h.remove_commands(app.bot)
		LOG.info("Bot stopped")

	app.post_init = _app_post_init
	app.post_stop = _app_post_stop
	app.run_polling()
