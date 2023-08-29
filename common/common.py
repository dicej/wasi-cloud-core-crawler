import os

MAX_DEPTH: int = 2
CHANNEL_NAME: str = "crawler"

def redis_address() -> str:
    address = os.environ["REDIS_ADDRESS"]
    if address is None:
        raise Exception("REDIS_ADDRESS environment variable must be set")
    else:
        return address
