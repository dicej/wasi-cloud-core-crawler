import asyncio
import json

from common import CHANNEL_NAME, redis_address
from crawler import exports
from crawler.types import Ok
from crawler.imports import types2 as http, messaging_types as messaging, producer
from crawler.imports.types2 import MethodPost
from crawler.imports.messaging_types import Message, FormatSpec, GuestConfiguration
from poll_loop import Stream, Sink, PollLoop
from typing import List
from urllib import parse

class IncomingHandler2(exports.IncomingHandler2):
    def handle(self, request: int, response_out: int):
        loop = PollLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(handle_async(request, response_out))

async def handle_async(request: int, response_out: int):
    try:
        method = http.incoming_request_method(request)
        path = http.incoming_request_path_with_query(request)
        headers = http.fields_entries(http.incoming_request_headers(request))
    
        if isinstance(method, MethodPost) and path == "/crawl":
            stream = Stream(http.incoming_request_consume(request))

            body = bytearray()

            while True:
                chunk = await stream.next()
                if chunk is None:
                    break
                else:
                    body.extend(chunk)

            # We expect the body to be a list of URLs, serialized as a JSON array of strings
            urls: List[str] = json.loads(body)

            # Sanity check that they're valid URLs
            for url in urls:
                parse.urlparse(url)

            client = messaging.connect(redis_address())
            
            for url in urls:
                producer.send(
                    client,
                    CHANNEL_NAME,
                    [Message(
                        bytes(json.dumps({"url": url, "depth": 0}), "utf-8"),
                        FormatSpec.RAW,
                        None
                    )]
                )

            status = 200
        else:
            status = 400

        response = http.new_outgoing_response(status, http.new_fields([]))
        http.set_response_outparam(response_out, Ok(response))
        Sink(http.outgoing_response_write(response)).close()
        
    except Exception as e:
        response = http.new_outgoing_response(
            500,
            http.new_fields([("content-type", b"text/plain")])
        )
        http.set_response_outparam(response_out, Ok(response))

        sink = Sink(http.outgoing_response_write(response))
        await sink.send(bytes(f"{type(e).__name__}: {str(e)}", "utf-8"))
        sink.close()

# Dummy implementation to satisfy `crawler` world:
class MessagingGuest(exports.MessagingGuest):
    def configure(self) -> GuestConfiguration:
        raise NotImplementedError

    def handler(self, messages: List[Message]):
        raise NotImplementedError
