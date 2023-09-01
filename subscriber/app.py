import asyncio
import json
import poll_loop

from common import MAX_DEPTH, CHANNEL_NAME, redis_address
from crawler import exports
from crawler.types import Ok, Err
from crawler.imports import types2 as http, messaging_types as messaging, producer, outgoing_handler2 as outgoing_handler
from crawler.imports.types2 import MethodGet, Scheme, SchemeHttp, SchemeHttps, SchemeOther
from crawler.imports.messaging_types import GuestConfiguration, Message, FormatSpec
from crawler.imports import types as kv, readwrite
from poll_loop import Stream, Sink, PollLoop
from typing import List, Tuple, cast
from html.parser import HTMLParser
from urllib import parse

class MessagingGuest(exports.MessagingGuest):
    def configure(self) -> GuestConfiguration:
        return GuestConfiguration(redis_address(), [CHANNEL_NAME], None)

    def handler(self, messages: List[Message]):
        loop = PollLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(handle_async(messages))

async def handle_async(messages: List[Message]):
    client = None
    for message in messages:
        body = json.loads(message.data)
        url: str = body["url"]
        depth: int = body["depth"]
            
        if depth < MAX_DEPTH:
            mime, body = await get(url)

            print(f"got {url}: mime: {mime} body length: {len(body)}")
            
            if mime.startswith("image/jpeg"):
                print(f"found a jpeg from url {url}")
                bucket = kv.open_bucket("images")
                outgoing_value = kv.new_outgoing_value()
                kv.outgoing_value_write_body_sync(outgoing_value, body)
                readwrite.set(bucket, url, outgoing_value)

            if depth + 1 < MAX_DEPTH and mime.startswith("text/html"):
                urls = get_urls(str(body, "utf-8"), 'https://www.fermyon.com')
                
                print(f"{url}: found {len(urls)} urls")
            
                for url in urls:
                    bucket = kv.open_bucket("urls")
                    try:
                        incoming_value = readwrite.get(bucket, url)
                        value = kv.incoming_value_consume_sync(incoming_value)
                        # parse value of bytes to int
                        value = int(value)
                        outgoing_value = kv.new_outgoing_value()
                        kv.outgoing_value_write_body_sync(outgoing_value, bytes(str(value + 1), "utf-8"))
                        readwrite.set(bucket, url, outgoing_value)
                    except Err as e:
                        msg = kv.trace(e.value)
                        print(f"error: {msg}")
                    except ValueError as e:
                        # if value is not an int, set it to 1
                        outgoing_value = kv.new_outgoing_value()
                        kv.outgoing_value_write_body_sync(outgoing_value, bytes("1", "utf-8"))
                        readwrite.set(bucket, url, outgoing_value)

                        if client is None:
                            client = messaging.connect(redis_address())
                        
                        producer.send(
                            client,
                            CHANNEL_NAME,
                            [Message(
                                bytes(json.dumps({"url": url, "depth": 0}), "utf-8"),
                                FormatSpec.RAW,
                                None
                            )]
                        )

async def get(url: str) -> Tuple[str, bytes]:
    url_parsed = parse.urlparse(url)

    match url_parsed.scheme:
        case "http":
            scheme: Scheme = SchemeHttp()
        case "https":
            scheme = SchemeHttps()
        case _:
            scheme = SchemeOther(url_parsed.scheme)

    request = http.new_outgoing_request(
        MethodGet(),
        url_parsed.path,
        scheme,
        url_parsed.netloc,
        http.new_fields([])
    )

    response = await outgoing_request_send(request)

    status = http.incoming_response_status(response)
    if status == 404:
        return "text/plain", b"not found"
    if status < 200 or status > 299:
        raise Exception(f"unexpected status for {url}: {status}")

    headers = http.fields_entries(http.incoming_response_headers(response))
    content_types = list(map(
        lambda pair: str(pair[1], "utf-8"),
        filter(lambda pair: pair[0] == "content-type", headers)
    ))

    stream = Stream(http.incoming_response_consume(response))

    body = bytearray()

    while True:
        chunk = await stream.next()
        if chunk is None:
            break
        else:
            body.extend(chunk)

    return content_types[0], bytes(body)

class Parser(HTMLParser):
    def __init__(self, base_url: str = None):
        HTMLParser.__init__(self)
        self.urls: List[str] = []
        self.base_url = base_url
                        
    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str | None]]):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value is not None:
                    absurl = parse.urljoin(self.base_url, value)
                    if absurl.startswith(self.base_url):
                        self.urls.append(absurl)
                        
def get_urls(html: str, base_url: str = None) -> List[str]:
    parser = Parser(base_url)
    parser.feed(html)
    return list(set(parser.urls))

async def outgoing_request_send(request: int) -> int:
    future = outgoing_handler.handle(request, None)
    pollable = http.listen_to_future_incoming_response(future)

    while True:
        response = http.future_incoming_response_get(future)
        if response is None:
            await poll_loop.register(cast(PollLoop, asyncio.get_event_loop()), pollable)
        else:
            if isinstance(response, Ok):
                return response.value
            else:
                raise response

# Dummy implementation to satisfy `crawler` world:
class IncomingHandler2(exports.IncomingHandler2):
    def handle(self, request: int, response_out: int):
        raise NotImplementedError
