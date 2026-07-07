import asyncio
import logging
import config
from handlers.followup import send_due_followups

log = logging.getLogger("PEAK-SCHEDULER")

async def run_followup_scheduler(bot):
    interval = config.FOLLOWUP_CHECK_INTERVAL_MIN * 60
    log.info("Scheduler بدأ")
    while True:
        try:
            await send_due_followups(bot)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("خطأ في Scheduler: %s", e)
        await asyncio.sleep(interval)
