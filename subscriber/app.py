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
from typing import List, Tuple, cast, Optional
from html.parser import HTMLParser
from urllib import parse
from datetime import datetime
from dataclasses import dataclass

class MessagingGuest(exports.MessagingGuest):
    def configure(self) -> GuestConfiguration:
        return GuestConfiguration(redis_address(), [CHANNEL_NAME], None)

    def handler(self, messages: List[Message]):
        loop = PollLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(handle_async(messages))

async def handle_async(messages: List[Message]):
    print(f"{datetime.now()}: got {len(messages)} messages")

    for result in asyncio.as_completed(map(maybe_get, messages)):
        value = await result
        
        if value is not None:
            value.crawl()

@dataclass
class Download:
    depth: int
    url: str
    mime: str
    body: bytes
    
    def crawl(self):
        print(f"{datetime.now()}: got {self.url}: mime: {self.mime} body length: {len(self.body)}")
                
        if self.mime.startswith("image/"):
            print(f"{datetime.now()}: found an image from url {self.url}")
            
            bucket = kv.open_bucket("images")
            outgoing_value = kv.new_outgoing_value()
            kv.outgoing_value_write_body_sync(outgoing_value, self.body)
            readwrite.set(bucket, self.url, outgoing_value)
                    
        elif self.depth + 1 < MAX_DEPTH and self.mime.startswith("text/html"):
            url_parsed = parse.urlparse(self.url)
            urls = get_urls(str(self.body, "utf-8"), f"{url_parsed.scheme}://{url_parsed.netloc}/")
                    
            print(f"{datetime.now()}: {self.url}: found {len(urls)} urls")
                
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
    
                    client = messaging.connect(redis_address())
                            
                    producer.send(
                        client,
                        CHANNEL_NAME,
                        [Message(
                            bytes(json.dumps({"url": url, "depth": self.depth + 1}), "utf-8"),
                            FormatSpec.RAW,
                            None
                        )]
                    )

async def maybe_get(message: Message) -> Optional[Download]:
    body = json.loads(message.data)
    url: str = body["url"]
    depth: int = body["depth"]
            
    if depth < MAX_DEPTH:
        return await get(depth, url)
    else:
        return None
            
async def get(depth: int, url: str) -> Download:
    print(f"{datetime.now()}: getting {url}")
                
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
    if status < 200 or status > 299:
        return Download(depth, url, "text/plain", bytes(f"unexpected status for {url}: {status}", "utf-8"))

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

    return Download(depth, url, content_types[0], bytes(body))

class Parser(HTMLParser):
    def __init__(self, base_url: str):
        HTMLParser.__init__(self)
        self.urls: List[str] = []
        self.base_url = base_url
                        
    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str | None]]):
        url: Optional[str] = None
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value is not None:
                    url = value
                    break
        elif tag == "img":
            for name, value in attrs:
                if name == "src" and value is not None:
                    url = value
                    break

        if url is None:
            return
        
        absurl = parse.urldefrag(parse.urljoin(self.base_url, url))[0]
        parsed_url = parse.urlparse(absurl)

        if absurl.startswith(self.base_url):
            self.urls.append(absurl)
                        
def get_urls(html: str, base_url: str) -> List[str]:
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
