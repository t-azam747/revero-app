"""Separate reply worker; never starts Gemini or digest scheduling."""
import time
from .instagram import initialize, run_one, settings
from .main import DEFAULT_DB
from .operations import worker_guard
import logging


def main():
    initialize(DEFAULT_DB)
    with worker_guard(DEFAULT_DB,'instagram'):
        try:
            while True:
                try:
                    if not run_one(DEFAULT_DB, settings()): time.sleep(2)
                except Exception:
                    logging.warning('Instagram worker paused after a queue error; retrying.')
                    time.sleep(5)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
