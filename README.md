# wasi-cloud-core-crawler

A simple web crawler demo written in Python, targeting
[wasi-http](https://github.com/WebAssembly/wasi-http),
[wasi-messaging](https://github.com/WebAssembly/wasi-messaging), and
[wasi-keyvalue](https://github.com/WebAssembly/wasi-keyvalue).

# Prerequistes

- [Python](https://www.python.org/) 3.10 or later
- [Redis](https://redis.io/) 7.0 or later
- [componentize-py](https://pypi.org/project/componentize-py/) 0.4.1
- a [fork of Spin](https://github.com/dicej/spin/tree/wasi-keyvalue) with experimental `wasi-cloud-core` support
- [curl](https://curl.se/) for testing

# Building and running

This application is composed of two cooperating pieces:

- `publisher`: accepts an HTTP POST request to `/crawl` containing a JSON array of URLs to crawl and publishes them to a Redis channel
- `subscriber`: reads from the Redis channel, downloading each URL, and recursively publishes any hyperlinks to the Redis channel, up to a predefined depth

First, start `redis-server` if it's not already running.  Then, in two separate terminals, run:

```shell
(cd publisher && spin build --up -e REDIS_ADDRESS=redis://127.0.0.1:6379)
```
and

```shell
(cd subscriber && spin build --up -e REDIS_ADDRESS=redis://127.0.0.1:6379)
```

Finally, in a third terminal, you can send a request to the publisher:

```shell
curl -i -H 'content-type: application/octet-stream' \
    -d '["https://fermyon.com"]' \
    http://127.0.0.1:3000/crawl
```
