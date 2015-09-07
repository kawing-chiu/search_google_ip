#!/usr/bin/env python3
"""Search reachable google app engine ips
"""
from ipaddress import IPv4Network
import ssl
from itertools import islice, cycle
import time
import logging
from collections import Counter
import sys
import errno
import warnings

from tornado import gen
from tornado.queues import Queue
from tornado.ioloop import IOLoop
from tornado.simple_httpclient import SimpleAsyncHTTPClient
from tornado.httpclient import HTTPRequest
from tornado.netutil import OverrideResolver
from tornado.locks import Lock
from tornado.queues import Queue

from google_netblocks import GOOGLE_NETBLOCKS



APP_ID = 'your_app_id'
ADDITIONAL_NETBLOCKS = ['208.117.0.0/16', '192.119.0.0/16']
CONCURRENCY = 3000
GOOD_IP_FILE = 'good_ips'


file_lock = Lock()

def _create_ip_iterator():
    GOOGLE_NETBLOCKS.extend(ADDITIONAL_NETBLOCKS)
    blocks = [list(IPv4Network(block).hosts()) for block in GOOGLE_NETBLOCKS]
    blocks = [reversed(block) for block in blocks]

    def ip_iter():
        pending = len(blocks)
        nexts = cycle(iter(block).__next__ for block in blocks)
        while pending:
            try:
                for next in nexts:
                    yield str(next())
            except StopIteration:
                pending -= 1
                nexts = cycle(islice(nexts, pending))
    return ip_iter()

def _get_test_ips():
    with open(GOOD_IP_FILE) as f:
        good_ips = f.readline().rstrip().split('|')
    return iter(good_ips)


@gen.coroutine
def record_good_ip(ip):
    with (yield file_lock.acquire()):
        with open(GOOD_IP_FILE, 'a+') as f:
            f.seek(0)
            records = f.readline()
            if not records:
                records = []
            else:
                records = records.rstrip().split('|')
            if ip not in records:
                if records:
                    f.write('|')
                f.write(ip)


@gen.coroutine
def test_ip(ip):
    hostname = APP_ID + '.appspot.com'
    url = 'https://' + hostname + '/2'
    request = HTTPRequest(url, request_timeout=5)

    try:
        client = SimpleAsyncHTTPClient(force_instance=True,
                hostname_mapping={hostname: ip})

        res = yield client.fetch(request, raise_error=False)
        if isinstance(res.error, OSError):
            if res.error.errno == errno.EMFILE:
                warning_msg = ("Too many open files. You should increase the"
                        " maximum allowed number of network connections in you"
                        " system or decrease the CONCURRENCY setting.")
                warnings.warn(warning_msg)
        if res.code == 200:
            return True
        else:
            return False
    finally:
        client.close()


def _disable_logging():
    logging.getLogger('tornado.general').setLevel(logging.CRITICAL)

    def ssl_error_filter(record):
        if record.exc_info:
            exc = sys.exc_info()[1]
            if isinstance(exc, (ssl.CertificateError, ssl.SSLError, ssl.SSLEOFError)):
                return False
            elif isinstance(exc, OSError):
                if exc.errno in (
                        errno.EHOSTUNREACH, errno.ECONNREFUSED,
                        errno.ECONNRESET, errno.ENOTCONN,
                        errno.ENETUNREACH, errno.EPIPE,
                        errno.ETIMEDOUT,
                    ):
                    return False
        return True

    logging.getLogger('tornado.application').addFilter(ssl_error_filter)


@gen.coroutine
def run(args):
    if not args.test:
        ip_iter = _create_ip_iterator()
    else:
        ip_iter = _get_test_ips()
        good_ips = []

    job_queue = Queue(maxsize=200)

    start = time.time()
    counter = Counter()

    @gen.coroutine
    def job_producer():
        for ip in ip_iter:
            yield job_queue.put(ip)
            #print("Put {}".format(ip))

    @gen.coroutine
    def worker(id):
        while True:
            ip = yield job_queue.get()
            try:
                good = yield test_ip(ip)
                counter['all'] += 1
                if args.progress:
                    if counter['all'] % 10000 == 0:
                        print("Tested {} ips.".format(counter['all']))
                if good:
                    print("Found good ip: {}".format(ip))
                    counter['good'] += 1
                    if not args.test:
                        yield record_good_ip(ip)
                    else:
                        good_ips.append(ip)
            finally:
                job_queue.task_done()

    for i in range(CONCURRENCY):
        worker(i)

    _disable_logging()

    try:
        yield job_producer()
        yield job_queue.join()
    finally:
        print("\n\nTested: {} ips\nFound {} good ips\nQps: {}".format(
            counter['all'],
            counter['good'],
            counter['all'] / (time.time() - start)
        ))

    if args.test and args.remove:
        with open(GOOD_IP_FILE + '_removed', 'w') as f:
            f.write('|'.join(good_ips))


def _parse_args():
    from argparse import ArgumentParser
    parser = ArgumentParser(description="Search google ips")
    parser.add_argument('-t', '--test', action='store_true',
            help="test ips in the good_ips file only")
    parser.add_argument('--remove', action='store_true',
            help="remove invalid ips, use together with -t")
    parser.add_argument('--progress', action='store_true',
            help="show progress when working")
    args = parser.parse_args()
    return args

def main():
    args = _parse_args()

    io_loop = IOLoop.current()
    io_loop.run_sync(lambda: run(args))

if __name__ == "__main__":
    main()


