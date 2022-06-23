import os
from functools import partial

from tornado import gen
from tornado.ioloop import IOLoop

from distributed.comm import connect, listen


def to_serialized(obj):
    from distributed.protocol import Serialized, serialize

    return Serialized(*serialize(obj))


def run_sync(loop, func):
    """Starts the `IOLoop`, runs the given function, and stops the loop.
    The function must return a yieldable object

    This is a limited, faster version of IOLoop.run_sync().
    (this function's overhead is 36 µs here, while
     IOLoop.run_sync's overhead is 68 µs)
    """
    future_cell = [None]

    def run():
        fut = gen.convert_yielded(func())
        fut.add_done_callback(lambda _: loop.stop())
        future_cell[0] = fut

    loop.add_callback(run)
    loop.start()
    return future_cell[0].result()


class LoopOverhead:
    """
    These are not distributed benchmarks per se, but help assessing
    Tornado's loop management overhead for other benchmarks.
    """

    def setup(self):
        self.loop = IOLoop()
        self.loop.make_current()

    def time_loop_start_stop(self):
        self.loop.add_callback(self.loop.stop)
        self.loop.start()

    @gen.coroutine
    def _empty_coro(self):
        pass

    def time_loop_run_sync(self):
        run_sync(self.loop, self._empty_coro)


class Connect:
    """
    Test overhead of connect() and Comm.close().
    """

    N_CONNECTS = 100

    def setup(self):
        self.loop = IOLoop()
        self.loop.make_current()

    @gen.coroutine
    def _handle_comm(self, comm):
        yield comm.close()

    @gen.coroutine
    def _connect_close(self, addr):
        comm = yield connect(addr)
        yield comm.close()

    @gen.coroutine
    def _main(self, address):
        listener = listen(address, self._handle_comm)
        yield listener.start()
        yield [
            self._connect_close(listener.contact_address)
            for i in range(self.N_CONNECTS)
        ]
        listener.stop()

    def _time_connect(self, address):
        run_sync(self.loop, partial(self._main, address))

    def time_tcp_connect(self):
        self._time_connect("tcp://127.0.0.1")

    def time_inproc_connect(self):
        self._time_connect("inproc://")


class Transfer:
    """
    Test speed of transfering objects on established comms.
    """

    N_SMALL_TRANSFERS = 100
    N_LARGE_TRANSFERS = 100

    _LARGE = 10 * 1024 * 1024
    _LARGE_UNCOMPRESSIBLE = os.urandom(_LARGE // 10) * 10

    MSG_SMALL = {
        "op": "update",
        "x": [123, 456],
        "data": b"foo",
    }
    # Since this is compressible, it might stress compression instead of
    # actual transmission cost
    MSG_LARGE = {
        "op": "update",
        "x": [123, 456],
        "data": b"z" * _LARGE,
    }
    MSG_LARGE_UNCOMPRESSIBLE = {
        "op": "update",
        "x": [123, 456],
        "data": _LARGE_UNCOMPRESSIBLE,
    }
    MSG_LARGE_SERIALIZED = {
        "op": "update",
        "x": [123, 456],
        "data": to_serialized(_LARGE_UNCOMPRESSIBLE),
    }

    def setup(self):
        self.loop = IOLoop()
        self.loop.make_current()

    @gen.coroutine
    def _handle_comm(self, n_transfers, comm):
        for i in range(n_transfers):
            obj = yield comm.read()
            yield comm.write(obj)
        yield comm.close()

    @gen.coroutine
    def _main(self, address, obj, n_transfers, **kwargs):
        listener = listen(address, partial(self._handle_comm, n_transfers), **kwargs)
        yield listener.start()
        comm = yield connect(listener.contact_address, **kwargs)
        for i in range(n_transfers):
            yield comm.write(obj)
        # Read back to ensure that the round-trip is complete
        for i in range(n_transfers):
            yield comm.read()
        yield comm.close()
        listener.stop()

    def _time_small(self, address):
        run_sync(
            self.loop,
            partial(self._main, address, self.MSG_SMALL, self.N_SMALL_TRANSFERS),
        )

    def _time_large(self, address):
        run_sync(
            self.loop,
            partial(self._main, address, self.MSG_LARGE, self.N_LARGE_TRANSFERS),
        )

    def _time_large_uncompressible(self, address):
        run_sync(
            self.loop,
            partial(
                self._main,
                address,
                self.MSG_LARGE_UNCOMPRESSIBLE,
                self.N_LARGE_TRANSFERS,
            ),
        )

    def _time_large_no_deserialize(self, address):
        run_sync(
            self.loop,
            partial(
                self._main,
                address,
                self.MSG_LARGE_SERIALIZED,
                self.N_LARGE_TRANSFERS,
                deserialize=False,
            ),
        )

    def time_tcp_small_transfers(self):
        self._time_small("tcp://127.0.0.1")

    def time_tcp_large_transfers(self):
        self._time_large("tcp://127.0.0.1")

    def time_tcp_large_transfers_uncompressible(self):
        self._time_large_uncompressible("tcp://127.0.0.1")

    def time_tcp_large_transfers_no_serialize(self):
        self._time_large_no_deserialize("tcp://127.0.0.1")

    def time_inproc_small_transfers(self):
        self._time_small("inproc://")

    def time_inproc_large_transfers(self):
        self._time_large("inproc://")
