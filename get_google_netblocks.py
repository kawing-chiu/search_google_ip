#!/usr/bin/env python3
"""Get google netblocks
"""
import subprocess
import re
from ipaddress import IPv4Network



DNS_SERVER = '127.0.0.1'
#HOSTS = ['_netblocks.google.com', '_cloud-netblocks.googleusercontent.com']


def _parse_args():
    from argparse import ArgumentParser
    parser = ArgumentParser(description="")
    parser.add_argument('host', nargs='?', default='_netblocks.google.com')
    parser.add_argument('--no-save', action='store_true')
    args = parser.parse_args()
    return args

def main():
    args = _parse_args()
    blocks = []

    def _get_netblocks(addr, depth=0):
        if depth > 3:
            return

        if addr.startswith('ip4:'):
            addr = re.sub('^ip4:', '', addr)
            blocks.append(addr)
        elif addr.startswith('ip6:'):
            pass
        elif addr.startswith('include:'):
            addr = re.sub('^include:', '', addr)
            _get_netblocks(addr, depth=depth + 1)
        else:
            query = subprocess.check_output(
                    ['dig', '@' + DNS_SERVER, addr, 'txt', '+short'],
                    timeout=10)
            query = query.decode().rstrip()
            query = re.sub(r'^"v=spf1 ', '', query)
            query = re.sub(r' [?~]all"$', '', query)
    
            addrs = query.split(' ')
            for addr in addrs:
                _get_netblocks(addr, depth=depth + 1)

    _get_netblocks(args.host)

    for block in blocks:
        IPv4Network(block)

    if args.no_save:
        print(blocks)
    else:
        with open('google_netblocks.py', 'w') as f:
            print('GOOGLE_NETBLOCKS = {}'.format(repr(blocks)), file=f)

if __name__ == "__main__":
    main()
