import os

MAX_DEPTH: int = 2
CHANNEL_NAME: str = "crawler"

def redis_address() -> str:
    try:
        return os.environ["REDIS_ADDRESS"]
    except KeyError:
        raise Exception("REDIS_ADDRESS environment variable must be set")

