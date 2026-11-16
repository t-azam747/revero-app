"""Run from root: backend/.venv/bin/python -m app.worker (with PYTHONPATH=backend)."""
import logging
import time
import threading
import os
from contextlib import ExitStack
from .storage import initialize
from .operations import worker_guard, paused
from . import digest
from .extraction import backfill_titles, cleanup_media, configured, run_batch, run_one
from .main import DEFAULT_DB


def run():
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
    if os.environ.get('REVERO_RUN_SCHEDULER', 'true') == 'true':
        scheduler.start()
    if os.environ.get('REVERO_RUN_PROCESSING','true') == 'true' and DEFAULT_DB.exists() and not paused(DEFAULT_DB,'processing'):
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
                if os.environ.get('REVERO_RUN_PROCESSING','true') != 'true' or paused(DEFAULT_DB,'processing'):
                    time.sleep(2); continue
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
        if scheduler.is_alive(): scheduler.join(timeout=25)


def main():
    initialize(DEFAULT_DB)
    with ExitStack() as stack:
        if os.environ.get('REVERO_RUN_SCHEDULER','true') == 'true': stack.enter_context(worker_guard(DEFAULT_DB,'scheduler'))
        if os.environ.get('REVERO_RUN_PROCESSING','true') == 'true': stack.enter_context(worker_guard(DEFAULT_DB,'processing'))
        run()


if __name__ == '__main__':
    main()
