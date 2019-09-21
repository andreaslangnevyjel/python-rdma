# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-

import contextlib
import pickle
import socket
import time
from collections import namedtuple
from mmap import mmap

import rdma.ibverbs as ibv

import rdma.path
import rdma.vtools
from .libibopts import LibIBOpts

infotype = namedtuple("infotype", "path addr rkey size iters")


class Endpoint(object):
    ctx = None
    pd = None
    cq = None
    mr = None
    peerinfo = None

    def __init__(self, opt, dev):
        self.opt = opt
        self.ctx = rdma.get_verbs(dev)
        self.cc = self.ctx.comp_channel()
        self.cq = self.ctx.cq(2 * opt.tx_depth, self.cc)
        self.poller = rdma.vtools.CQPoller(self.cq)
        self.pd = self.ctx.pd()
        self.srq = self.pd.srq(opt.tx_depth)
        self.qp = self.pd.qp(
            ibv.IBV_QPT_RC,
            opt.tx_depth,
            self.cq,
            opt.tx_depth,
            self.cq,
            # max_send_sge=opt.num_sge,
            # max_recv_sge=1,
            srq=self.srq,
        )
        self.pool = rdma.vtools.BufferPool(self.pd, 2 * opt.tx_depth, 256 + 40)
        self.pool.post_recvs(self.srq, opt.tx_depth)
        self.mem = mmap(-1, opt.size)
        self.mr = self.pd.mr(
            self.mem,
            ibv.IBV_ACCESS_LOCAL_WRITE | ibv.IBV_ACCESS_REMOTE_WRITE,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self):
        if self.ctx is not None:
            self.ctx.close()

    def connect(self, peerinfo, is_server_mode: bool):
        self.peerinfo = peerinfo
        print(
            "establish {} {!r}".format(
                "server" if is_server_mode else "client",
                self.path,
            ),
        )
        self.qp.establish(self.path.forward_path, ibv.IBV_ACCESS_REMOTE_WRITE)

    def rdma_recv(self):
        print("recvpath {!r}".format(self.path))
        # sg_list = self.mr.sge()
        send_pi = self.pool.pop()
        self.pool.copy_to(b"xxxxx", send_pi)
        self.qp.post_send(self.pool.make_send_wr(send_pi, 256, self.path))
        # read_buffer.post_send(self.qp, depth)
        # self.qp.post_send(read_buffer.make_send_wr(read_buffer.pop(), 256, self.path))
        tpost = time.monotonic()

        print("start", tpost)
        # print(self.poller.sleep(wakeat=tpost + 1))
        # print("s2")
        for wc in self.poller.iterwc(count=2, timeout=4):
            print(wc.status, wc.opcode, wc)
            if wc.opcode == ibv.IBV_WC_RECV:
                print(self.pool.copy_from(wc.wr_id, length=4))
            self.pool.finish_wcs(self.srq, wc)
        epost = time.monotonic()
        print("done", epost)

    def rdma(self):

        if self.opt.num_sge > 1:
            block = self.opt.size / self.opt.num_sge + 1
            sg_list = []
            offset = 0
            while offset < self.opt.size:
                if offset + block > self.opt.size:
                    block = self.opt.size - offset
                sg_list.append(self.mr.sge(block, offset))
                offset += block
        else:
            sg_list = self.mr.sge()

        swr = ibv.send_wr(
            wr_id=0,
            remote_addr=self.peerinfo.addr,
            rkey=self.peerinfo.rkey,
            sg_list=sg_list,
            opcode=ibv.IBV_WR_RDMA_WRITE,
            send_flags=ibv.IBV_SEND_SIGNALED,
        )
        n = self.opt.iters
        depth = min(self.opt.tx_depth, n, self.qp.max_send_wr)

        tpost = time.monotonic()
        for i in range(depth):
            self.qp.post_send(swr)

        completions = 0
        posts = depth
        for wc in self.poller.iterwc(timeout=1):
            if wc.status != ibv.IBV_WC_SUCCESS:
                print("Error")
                raise ibv.WCError(wc, self.cq, obj=self.qp)
            # print(wc.opcode, ibv.IBV_WC_RECV, wc)
            if wc.opcode == ibv.IBV_WC_RECV:
                print(self.pool.copy_from(wc.wr_id, length=4))
            else:
                completions += 1
                if posts < n:
                    self.qp.post_send(swr)
                    posts += 1
                    self.poller.wakeat = time.monotonic() + 1
            if completions == n:
                send_pi = self.pool.pop()
                self.pool.copy_to(b"xxyxx", send_pi)
                self.qp.post_send(self.pool.make_send_wr(send_pi, 256, self.path))
            elif completions == n + 1:
                break
            self.pool.finish_wcs(self.srq, wc)
        else:
            raise rdma.RDMAError("CQ timed out")

        tcomp = time.monotonic()

        rate = self.opt.size * self.opt.iters / 1e6 / (tcomp - tpost)
        print("{:.1f} MB/sec".format(rate))


def client_mode(hostname, opt, dev):
    with Endpoint(opt, dev) as end:
        ret = socket.getaddrinfo(hostname, str(opt.ip_port), opt.af,
                                 socket.SOCK_STREAM)
        ret = ret[0]
        with contextlib.closing(socket.socket(ret[0], ret[1])) as sock:
            if opt.debug >= 1:
                print(
                    "Connecting to {!r} {!r}".format(
                        ret[4][0],
                        ret[4][1],
                    ),
                )
            sock.connect(ret[4])

            path = rdma.path.IBPath(dev, SGID=end.ctx.end_port.default_gid)
            rdma.path.fill_path(end.qp, path, max_rd_atomic=0)
            path.reverse(for_reply=False)

            sock.send(
                pickle.dumps(
                    infotype(
                        path=path,
                        addr=end.mr.addr,
                        rkey=end.mr.rkey,
                        size=opt.size,
                        iters=opt.iters,
                    ),
                ),
            )
            buf = sock.recv(1024)
            peerinfo = pickle.loads(buf)

            end.path = peerinfo.path
            end.path.reverse(for_reply=False)
            end.path.set_end_port(end.ctx.node)
            print(end.path)

            print(
                "path to peer {!r}\nMR peer raddr={:x} peer rkey={:x}".format(
                    end.path.forward_path,
                    peerinfo.addr,
                    peerinfo.rkey,
                ),
            )
            print(
                "{:d} iterations of {:d} is {:d} bytes".format(
                    opt.iters,
                    opt.size,
                    opt.iters * opt.size,
                ),
            )

            end.connect(peerinfo, False)
            # Synchronize the transition to RTS
            sock.send(b"Ready")
            print("ready")
            sock.recv(1024)
            time.sleep(0.5)
            print("go")
            end.rdma()

            sock.shutdown(socket.SHUT_WR)
            sock.recv(1024)


def server_mode(opt, dev):
    ret = socket.getaddrinfo(
        None,
        str(opt.ip_port),
        opt.af,
        socket.SOCK_STREAM,
        0,
        socket.AI_PASSIVE,
    )
    ret = ret[0]
    with contextlib.closing(socket.socket(ret[0], ret[1])) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(ret[4])
        if opt.debug >= 1:
            print(
                "Listening on {!r} {!r}".format(
                    ret[4][0],
                    ret[4][1],
                ),
            )
        sock.listen(1)

        s, addr = sock.accept()
        with contextlib.closing(s):
            buf = s.recv(1024)
            peerinfo = pickle.loads(buf)

            opt.size = peerinfo.size
            opt.iters = peerinfo.iters

            with Endpoint(opt, dev) as end:
                with rdma.get_gmp_mad(end.ctx.end_port, verbs=end.ctx) as umad:
                    end.path = peerinfo.path
                    end.path.end_port = end.ctx.end_port
                    rdma.path.fill_path(end.qp, end.path, max_rd_atomic=0)
                    rdma.path.resolve_path(umad, end.path, reversible=True)
                    print("p=", end.path)
                s.send(
                    pickle.dumps(
                        infotype(
                            path=end.path,
                            addr=end.mr.addr,
                            rkey=end.mr.rkey,
                            size=None,
                            iters=None,
                        ),
                    ),
                )

                print(
                    "path to peer {!r}\nMR peer raddr={:x} peer rkey={:x}".format(
                        end.path.forward_path,
                        peerinfo.addr,
                        peerinfo.rkey,
                    ),
                )
                print(
                    "{:d} iterations of {:d} is {:d} bytes".format(
                        opt.iters,
                        opt.size,
                        opt.iters * opt.size,
                    ),
                )

                end.connect(peerinfo, True)
                # Synchronize the transition to RTS
                s.send(b"ready")
                end.rdma_recv()
                s.recv(1024)
                if opt.bidirectional:
                    end.rdma()

                s.shutdown(socket.SHUT_WR)
                s.recv(1024)


def cmd_rdma_bw(argv, o):
    """Perform a RDMA bandwidth test over a RC QP.
       Usage: %prog [SERVER]

       If SERVER is not specified then a server instance is started. A
       connection is made using TCP/IP sockets between the client and server
       process. This connection is used to exchange the connection
       information."""

    o.add_option(
        "-C",
        "--Ca",
        dest="CA",
        help="RDMA device to use. Specify a device name or node GUID",
    )
    o.add_option(
        "-P",
        "--Port",
        dest="port",
        help="RDMA end port to use. Specify a GID, port GUID, DEVICE/PORT or port number.",
    )
    o.add_option(
        "-p",
        "--port",
        default=4444,
        type="int",
        dest="ip_port",
        help="listen on/connect to port PORT",
    )
    o.add_option(
        "-6",
        "--ipv6",
        action="store_const",
        const=socket.AF_INET6,
        dest="af",
        default=0,
        help="use IPv6",
    )
    o.add_option(
        "-b",
        "--bidirectional",
        default=False,
        action="store_true",
        help="measure bidirectional bandwidth",
    )
    o.add_option(
        "-d",
        "--ib-dev",
        metavar="DEV",
        dest="CA",
        help="use IB device DEV",
    )
    o.add_option(
        "-i",
        "--ib-port",
        type="int",
        metavar="PORT",
        dest="port",
        help="use port PORT of IB device",
    )
    o.add_option(
        "-s",
        "--size",
        default=1024 * 1024,
        type="int",
        metavar="BYTES",
        help="exchange messages of size BYTES,(client only)",
    )
    o.add_option(
        "-e",
        "--num-sge",
        default=1,
        type="int",
        metavar="NUM",
        help="Number of sges to use.",
    )
    o.add_option(
        "-t",
        "--tx-depth",
        default=100,
        type="int",
        help="number of exchanges",
    )
    o.add_option(
        "-n",
        "--iters",
        default=1000,
        type="int",
        help="number of exchanges (client only)",
    )
    o.add_option(
        "--debug",
        dest="debug",
        action="count",
        default=0,
        help="Increase the debug level, each -d increases by 1.",
    )

    args, values = o.parse_args(argv)
    lib = LibIBOpts(o, args, 1, (str,))

    if len(values) == 1:
        client_mode(values[0], args, lib.get_end_port())
    else:
        server_mode(args, lib.get_end_port())
    return True
