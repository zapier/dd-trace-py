# 3p
import wrapt
from nose.tools import assert_raises
import pymemcache
from pymemcache.exceptions import (
    MemcacheClientError,
    MemcacheServerError,
    MemcacheUnknownCommandError,
    MemcacheUnknownError,
    MemcacheIllegalInputError,
)

# project
from ddtrace import Pin
from ddtrace.contrib.pymemcache.patch import unpatch
from .utils import MockSocket, _str
from .test_client_mixin import PymemcacheClientTestCaseMixin

from tests.test_tracer import get_dummy_tracer


_Client = pymemcache.client.base.Client


class PymemcacheClientTestCase(PymemcacheClientTestCaseMixin):
    """ Tests for a patched pymemcache.client.base.Client. """

    def test_patch(self):
        assert issubclass(pymemcache.client.base.Client, wrapt.ObjectProxy)
        client = self.make_client([])
        self.assertIsInstance(client, wrapt.ObjectProxy)

    def test_unpatch(self):
        unpatch()
        from pymemcache.client.base import Client

        self.assertEqual(Client, _Client)

    def test_set_get(self):
        client = self.make_client([b"STORED\r\n", b"VALUE key 0 5\r\nvalue\r\nEND\r\n"])
        client.set(b"key", b"value", noreply=False)
        result = client.get(b"key")
        assert _str(result) == "value"

        self.check_spans(2, ["set", "get"])

    def test_append_stored(self):
        client = self.make_client([b"STORED\r\n"])
        result = client.append(b"key", b"value", noreply=False)
        assert result is True

        self.check_spans(1, ["append"])

    def test_prepend_stored(self):
        client = self.make_client([b"STORED\r\n"])
        result = client.prepend(b"key", b"value", noreply=False)
        assert result is True

        self.check_spans(1, ["prepend"])

    def test_cas_stored(self):
        client = self.make_client([b"STORED\r\n"])
        result = client.cas(b"key", b"value", b"cas", noreply=False)
        assert result is True

        self.check_spans(1, ["cas"])

    def test_cas_exists(self):
        client = self.make_client([b"EXISTS\r\n"])
        result = client.cas(b"key", b"value", b"cas", noreply=False)
        assert result is False

        self.check_spans(1, ["cas"])

    def test_cas_not_found(self):
        client = self.make_client([b"NOT_FOUND\r\n"])
        result = client.cas(b"key", b"value", b"cas", noreply=False)
        assert result is None

        self.check_spans(1, ["cas"])

    def test_delete_exception(self):
        client = self.make_client([Exception("fail")])

        def _delete():
            client.delete(b"key", noreply=False)

        assert_raises(Exception, _delete)

        spans = self.check_spans(1, ["delete"])
        self.assertEqual(spans[0].error, 1)

    def test_flush_all(self):
        client = self.make_client([b"OK\r\n"])
        result = client.flush_all(noreply=False)
        assert result is True

        self.check_spans(1, ["flush_all"])

    def test_incr_exception(self):
        client = self.make_client([Exception("fail")])

        def _incr():
            client.incr(b"key", 1)

        assert_raises(Exception, _incr)

        spans = self.check_spans(1, ["incr"])
        self.assertEqual(spans[0].error, 1)

    def test_get_error(self):
        client = self.make_client([b"ERROR\r\n"])

        def _get():
            client.get(b"key")

        assert_raises(MemcacheUnknownCommandError, _get)

        spans = self.check_spans(1, ["get"])
        self.assertEqual(spans[0].error, 1)

    def test_get_unknown_error(self):
        client = self.make_client([b"foobarbaz\r\n"])

        def _get():
            client.get(b"key")

        assert_raises(MemcacheUnknownError, _get)

        self.check_spans(1, ["get"])

    def test_gets_found(self):
        client = self.make_client([b"VALUE key 0 5 10\r\nvalue\r\nEND\r\n"])
        result = client.gets(b"key")
        assert result == (b"value", b"10")

        self.check_spans(1, ["gets"])

    def test_touch_not_found(self):
        client = self.make_client([b"NOT_FOUND\r\n"])
        result = client.touch(b"key", noreply=False)
        assert result is False

        self.check_spans(1, ["touch"])

    def test_set_client_error(self):
        client = self.make_client([b"CLIENT_ERROR some message\r\n"])

        def _set():
            client.set("key", "value", noreply=False)

        assert_raises(MemcacheClientError, _set)

        spans = self.check_spans(1, ["set"])
        self.assertEqual(spans[0].error, 1)

    def test_set_server_error(self):
        client = self.make_client([b"SERVER_ERROR some message\r\n"])

        def _set():
            client.set(b"key", b"value", noreply=False)

        assert_raises(MemcacheServerError, _set)

        spans = self.check_spans(1, ["set"])
        self.assertEqual(spans[0].error, 1)

    def test_set_key_with_space(self):
        client = self.make_client([b""])

        def _set():
            client.set(b"key has space", b"value", noreply=False)

        assert_raises(MemcacheIllegalInputError, _set)

        spans = self.check_spans(1, ["set"])
        self.assertEqual(spans[0].error, 1)

    def test_quit(self):
        client = self.make_client([])
        result = client.quit()
        assert result is None

        self.check_spans(1, ["quit"])

    def test_replace_not_stored(self):
        client = self.make_client([b"NOT_STORED\r\n"])
        result = client.replace(b"key", b"value", noreply=False)
        assert result is False

        self.check_spans(1, ["replace"])

    def test_version_success(self):
        client = self.make_client([b"VERSION 1.2.3\r\n"], default_noreply=False)
        result = client.version()
        assert result == b"1.2.3"

        self.check_spans(1, ["version"])

    def test_stats(self):
        client = self.make_client([b"STAT fake_stats 1\r\n", b"END\r\n"])
        result = client.stats()
        assert client.sock.send_bufs == [b"stats \r\n"]
        assert result == {b"fake_stats": 1}

        self.check_spans(1, ["stats"])


class PymemcacheHashClientTestCase(PymemcacheClientTestCaseMixin):
    """ Tests for a patched pymemcache.client.hash.HashClient. """

    def get_spans(self):
        spans = []
        for _, client in self.client.clients.items():
            pin = Pin.get_from(client)
            tracer = pin.tracer
            spans.extend(tracer.writer.pop())
        return spans

    def make_client_pool(self, hostname, mock_socket_values, serializer=None, **kwargs):
        mock_client = pymemcache.client.base.Client(
            hostname, serializer=serializer, **kwargs
        )
        tracer = get_dummy_tracer()
        Pin.override(mock_client, tracer=tracer)

        mock_client.sock = MockSocket(mock_socket_values)
        client = pymemcache.client.base.PooledClient(hostname, serializer=serializer)
        client.client_pool = pymemcache.pool.ObjectPool(lambda: mock_client)
        return mock_client

    def make_client(self, *mock_socket_values, **kwargs):
        current_port = 11012
        from pymemcache.client.hash import HashClient

        self.client = HashClient([], **kwargs)
        ip = "127.0.0.1"

        for vals in mock_socket_values:
            s = "{}:{}".format(ip, current_port)
            c = self.make_client_pool((ip, current_port), vals, **kwargs)
            self.client.clients[s] = c
            self.client.hasher.add_node(s)
            current_port += 1
        return self.client

    def test_delete_many_found(self):
        """
        delete_many internally calls client.delete so we should expect to get
        delete for our span resource.

        for base.Clients self.delete() is called which by-passes our tracing
        on delete()
        """
        client = self.make_client([b"STORED\r", b"\n", b"DELETED\r\n"])
        result = client.add(b"key", b"value", noreply=False)
        result = client.delete_many([b"key"], noreply=False)
        assert result is True

        self.check_spans(2, ["add", "delete"])