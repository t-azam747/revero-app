"""Separate reply worker; never starts Gemini or digest scheduling."""
import time
from .instagram import initialize, run_one, settings
from .main import DEFAULT_DB


def main():
    initialize(DEFAULT_DB)
    try:
        while True:
            if not run_one(DEFAULT_DB, settings()):
                time.sleep(2)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
