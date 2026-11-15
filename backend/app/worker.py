"""Run from root: backend/.venv/bin/python -m app.worker (with PYTHONPATH=backend)."""
import logging
import time
import threading
from . import digest
from .extraction import backfill_titles, cleanup_media, configured, run_batch, run_one
from .main import DEFAULT_DB


def main():
    logging.basicConfig(level=logging.INFO)
    logging.info('Revero worker started. Configure .env to enable Gemini processing.')
    stop = threading.Event()
    def schedule():
        while not stop.is_set():
            try:
                if DEFAULT_DB.exists():
                    digest.tick(DEFAULT_DB)
            except Exception:
                logging.warning('Digest check failed; it will be checked again in 10 seconds.')
            stop.wait(10)
    scheduler = threading.Thread(target=schedule, name='digest-scheduler', daemon=True)
    scheduler.start()
    if DEFAULT_DB.exists():
        try:
            queued = backfill_titles(DEFAULT_DB)
            if queued:
                logging.info('Queued %d inbound share title(s) for caption extraction.', queued)
        except Exception:
            logging.warning('Inbound title backfill failed; it will not block the queue.')
    try:
        while True:
            try:
                if DEFAULT_DB.exists():
                    cleanup_media(DEFAULT_DB)
                # Caption-only jobs are batched first; video and other jobs use the single path.
                processed = run_batch(DEFAULT_DB) if DEFAULT_DB.exists() and configured() else 0
                if not DEFAULT_DB.exists() or not configured() or not (processed or run_one(DEFAULT_DB)):
                    time.sleep(2)
            except Exception:
                # Never log provider responses or credentials.
                logging.warning('Worker could not access the queue; retrying in five seconds.')
                time.sleep(5)
    except KeyboardInterrupt:
        logging.info('Worker stopped; queued work remains in SQLite.')
    finally:
        stop.set()
        scheduler.join(timeout=25)


if __name__ == '__main__':
    main()
