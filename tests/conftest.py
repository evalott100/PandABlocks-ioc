import asyncio
import logging
import multiprocessing
import os
import sys
import threading
import time
import typing
from collections import OrderedDict, deque
from contextlib import contextmanager
from logging import handlers
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Deque, Dict, Generator, Iterable, List

import pytest
import pytest_asyncio
from aioca import purge_channel_caches
from epicsdbbuilder import ResetRecords
from mock import MagicMock, patch
from numpy import array, int32, ndarray, uint8, uint16, uint32
from pandablocks.connections import Buffer
from pandablocks.responses import TableFieldDetails, TableFieldInfo
from softioc.device_core import RecordLookup

from pandablocks_ioc._types import EpicsName
from pandablocks_ioc.ioc import _TimeRecordUpdater, create_softioc

# Record prefix used in many tests
TEST_PREFIX = "TEST-PREFIX"

BOBFILE_DIR = Path(__file__).parent / "test-bobfiles"

# Timeout value (in seconds)
TIMEOUT = 10


@pytest.fixture
def enable_codecov_multiprocess():
    """Code to enable pytest-cov to work properly with multiprocessing"""
    try:
        from pytest_cov.embed import cleanup_on_sigterm
    except ImportError:
        pass
    else:
        cleanup_on_sigterm()

    return


@pytest.fixture
def caplog_workaround():
    """Create a logger handler to capture all log messages done in child process,
    then print them to the main thread's stdout/stderr so pytest's caplog fixture
    can see them
    See https://stackoverflow.com/questions/63052171/empty-messages-in-caplog-when-logs-emmited-in-a-different-process/63054881#63054881
    """  # noqa: E501

    @contextmanager
    def ctx() -> Generator[None, None, None]:
        ctx = get_multiprocessing_context()
        logger_queue = ctx.Queue()
        logger = logging.getLogger()
        logger.addHandler(handlers.QueueHandler(logger_queue))
        yield
        while not logger_queue.empty():
            log_record: logging.LogRecord = logger_queue.get()
            # Make mypy happy
            assert (
                log_record.args
            ), f"args were none, how did that happen?\nRecord: {log_record}\n"
            f"Args: {log_record.args}"
            logger._log(
                level=log_record.levelno,
                msg=log_record.message,
                args=log_record.args,
                exc_info=log_record.exc_info,
            )

    return ctx


class DummyServer:
    # Flag for useful debug output when writing tests
    # for diagnosing mismatching sent data.
    debug = False
    _debug_file = "out.txt"

    # Mechanism to tell the server to send a specific response back to the client
    # when it sees an expected string. When the expected message is seen the
    # response will be left-appended to the send buffer so it is sent next.
    # Items are removed from the Dict when they are sent.
    expected_message_responses: Dict[str, str] = {}

    def __init__(self) -> None:
        # This will be added to whenever control port gets a message
        self.received: List[str] = []
        # Add to this to give the control port something to send back
        self.send: Deque[str] = deque()
        # Add to this to give the data port something to send
        self.data: Iterable[bytes] = []

        if self.debug and os.path.isfile(self._debug_file):
            os.remove(self._debug_file)

    async def handle_ctrl(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        buf = Buffer()
        is_multiline = False

        while True:
            received = await reader.read(4096)
            if not received:
                break
            buf += received
            for line in buf:
                decoded_line = line.decode()
                self.received.append(decoded_line)
                if decoded_line in self.expected_message_responses:
                    self.send.appendleft(self.expected_message_responses[decoded_line])
                    del self.expected_message_responses[decoded_line]
                if line.endswith(b"<") or line.endswith(b"<B"):
                    is_multiline = True
                if not is_multiline or not line:
                    is_multiline = False

                    try:
                        data = self.send.popleft()
                    except IndexError:
                        # Keep this server running, just send a blank message
                        # This is most likely being consumed by GetChanges
                        data = "."
                    to_send = data + "\n"
                    if self.debug:
                        with open(self._debug_file, "a") as f:
                            print(line, to_send, flush=True, file=f)
                    writer.write(to_send.encode())
                    await writer.drain()

    async def handle_data(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        # oneshot data writer
        try:
            await reader.read(4096)
            for data in self.data:
                await asyncio.sleep(0.1)
                writer.write(data)
                await writer.drain()
        except IOError:
            # During shutdown we see exceptions due to the client side disconnecting
            pass

    async def open(self):
        self._ctrl_server = await asyncio.start_server(
            self.handle_ctrl, "127.0.0.1", 8888
        )
        self._data_server = await asyncio.start_server(
            self.handle_data, "127.0.0.1", 8889
        )

    async def close(self):
        self._ctrl_server.close()
        self._data_server.close()
        await self._ctrl_server.wait_closed()
        await self._data_server.wait_closed()

    def drain_expected_messages(self, timeout=TIMEOUT):
        """Waits for the expected_message_responses to be empty"""
        sleep_period = 0.2

        start_time = time.time()
        while self.expected_message_responses:
            time.sleep(sleep_period)
            if time.time() - start_time > timeout:
                raise Exception("Timeout waiting for server expected messages to clear")


def _clear_records():
    # Remove any records created at epicsdbbuilder layer
    ResetRecords()
    # And at pythonSoftIoc level
    # TODO: Remove this hack and use use whatever comes out of
    # https://github.com/dls-controls/pythonSoftIOC/issues/56
    RecordLookup._RecordDirectory.clear()


@pytest_asyncio.fixture
def clear_records():
    """Fixture to delete all records before and after a test."""
    _clear_records()
    yield
    _clear_records()


def custom_logger():
    """Add a custom logger that prints everything to subprocess's stderr,
    otherwise pytest doesn't see logging messages from spawned Processes"""
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    logging.getLogger("").addHandler(sh)


@pytest.fixture(autouse=True)
def aioca_cleanup():
    """Purge the aioca channel cache as the test terminates.
    This suppresses spurious "IOC disconnected" error messages"""
    yield
    purge_channel_caches()


@pytest.fixture
def table_fields() -> Dict[str, TableFieldDetails]:
    """Table field definitions, taken from a SEQ.TABLE instance.
    Associated with table_data and table_field_info fixtures"""
    return {
        "REPEATS": TableFieldDetails(
            subtype="uint",
            bit_low=0,
            bit_high=15,
            description="Number of times the line will repeat",
            labels=None,
        ),
        "TRIGGER": TableFieldDetails(
            subtype="enum",
            bit_low=16,
            bit_high=19,
            description="The trigger condition to start the phases",
            labels=[
                "Immediate",
                "BITA=0",
                "BITA=1",
                "BITB=0",
                "BITB=1",
                "BITC=0",
                "BITC=1",
                "POSA>=POSITION",
                "POSA<=POSITION",
                "POSB>=POSITION",
                "POSB<=POSITION",
                "POSC>=POSITION",
                "POSC<=POSITION",
            ],
        ),
        "POSITION": TableFieldDetails(
            subtype="int",
            bit_low=32,
            bit_high=63,
            description="The position that can be used in trigger condition",
            labels=None,
        ),
        "TIME1": TableFieldDetails(
            subtype="uint",
            bit_low=64,
            bit_high=95,
            description="The time the optional phase 1 should take",
            labels=None,
        ),
        "OUTA1": TableFieldDetails(
            subtype="uint",
            bit_low=20,
            bit_high=20,
            description="Output A value during phase 1",
            labels=None,
        ),
        "OUTB1": TableFieldDetails(
            subtype="uint",
            bit_low=21,
            bit_high=21,
            description="Output B value during phase 1",
            labels=None,
        ),
        "OUTC1": TableFieldDetails(
            subtype="uint",
            bit_low=22,
            bit_high=22,
            description="Output C value during phase 1",
            labels=None,
        ),
        "OUTD1": TableFieldDetails(
            subtype="uint",
            bit_low=23,
            bit_high=23,
            description="Output D value during phase 1",
            labels=None,
        ),
        "OUTE1": TableFieldDetails(
            subtype="uint",
            bit_low=24,
            bit_high=24,
            description="Output E value during phase 1",
            labels=None,
        ),
        "OUTF1": TableFieldDetails(
            subtype="uint",
            bit_low=25,
            bit_high=25,
            description="Output F value during phase 1",
            labels=None,
        ),
        "TIME2": TableFieldDetails(
            subtype="uint",
            bit_low=96,
            bit_high=127,
            description="The time the mandatory phase 2 should take",
            labels=None,
        ),
        "OUTA2": TableFieldDetails(
            subtype="uint",
            bit_low=26,
            bit_high=26,
            description="Output A value during phase 2",
            labels=None,
        ),
        "OUTB2": TableFieldDetails(
            subtype="uint",
            bit_low=27,
            bit_high=27,
            description="Output B value during phase 2",
            labels=None,
        ),
        "OUTC2": TableFieldDetails(
            subtype="uint",
            bit_low=28,
            bit_high=28,
            description="Output C value during phase 2",
            labels=None,
        ),
        "OUTD2": TableFieldDetails(
            subtype="uint",
            bit_low=29,
            bit_high=29,
            description="Output D value during phase 2",
            labels=None,
        ),
        "OUTE2": TableFieldDetails(
            subtype="uint",
            bit_low=30,
            bit_high=30,
            description="Output E value during phase 2",
            labels=None,
        ),
        "OUTF2": TableFieldDetails(
            subtype="uint",
            bit_low=31,
            bit_high=31,
            description="Output F value during phase 2",
            labels=None,
        ),
    }


@pytest.fixture
def table_field_info(table_fields) -> TableFieldInfo:
    """Table data associated with table_fields and table_data fixtures"""
    return TableFieldInfo(
        "table", None, "Sequencer table of lines", 16384, table_fields, 4
    )


@pytest.fixture
def table_data() -> List[str]:
    """Table data associated with table_fields and table_field_info fixtures.
    See table_unpacked_data for the unpacked equivalent"""
    return [
        "2457862149",
        "4294967291",
        "100",
        "0",
        "269877248",
        "678",
        "0",
        "55",
        "4293968720",
        "0",
        "9",
        "9999",
    ]


@pytest.fixture
def table_unpacked_data(
    table_fields: Dict[str, TableFieldDetails]
) -> typing.OrderedDict[EpicsName, ndarray]:
    """The unpacked equivalent of table_data"""
    array_values: List[ndarray] = [
        array([5, 0, 50000], dtype=uint16),
        # Below labels correspond to numeric values [0, 6, 0]
        array(["Immediate", "BITC=1", "Immediate"], dtype="<U9"),
        array([-5, 678, 0], dtype=int32),
        array([100, 0, 9], dtype=uint32),
        array([0, 1, 1], dtype=uint8),
        array([0, 0, 1], dtype=uint8),
        array([0, 0, 1], dtype=uint8),
        array([1, 0, 1], dtype=uint8),
        array([0, 0, 1], dtype=uint8),
        array([1, 0, 1], dtype=uint8),
        array([0, 55, 9999], dtype=uint32),
        array([0, 0, 1], dtype=uint8),
        array([0, 0, 1], dtype=uint8),
        array([1, 1, 1], dtype=uint8),
        array([0, 0, 1], dtype=uint8),
        array([0, 0, 1], dtype=uint8),
        array([1, 0, 1], dtype=uint8),
    ]
    data: OrderedDict[EpicsName, ndarray] = OrderedDict()
    for field_name, data_array in zip(table_fields.keys(), array_values):
        data[EpicsName(field_name)] = data_array
    return data


@pytest_asyncio.fixture
def dummy_server_introspect_panda(
    dummy_server_in_thread: DummyServer, table_data: List[str]
):
    """A dummy server that responds to all the requests introspect_panda makes
    during its operation.
    Note that the order of responses was determined by trial and error."""
    get_changes_scalar_data = (
        # Note the deliberate concatenation across lines - this must be a single
        # entry in the list
        "!PCAP.TRIG_EDGE=Falling\n!PCAP.GATE=CLOCK1.OUT\n!PCAP.GATE.DELAY=1\n"
        "!*METADATA.LABEL_PCAP1=PcapMetadataLabel\n"
        "!SEQ1.TABLE<\n"
        "."
    )

    # Transform the plain list of values into one that PandA would send
    tmp = ["!" + s + "\n" for s in table_data]
    tmp.append(".")  # Add the multiline terminator
    get_changes_multiline_data = "".join(tmp)

    table_fields_data = (
        # Note the deliberate concatenation across lines - this must be a single
        # entry in the list
        "!15:0 REPEATS uint\n!19:16 TRIGGER enum\n!63:32 POSITION int\n"
        "!95:64 TIME1 uint\n!20:20 OUTA1 uint\n!21:21 OUTB1 uint\n!22:22 OUTC1 uint\n"
        "!23:23 OUTD1 uint\n!24:24 OUTE1 uint\n!25:25 OUTF1 uint\n!127:96 TIME2 uint\n"
        "!26:26 OUTA2 uint\n!27:27 OUTB2 uint\n!28:28 OUTC2 uint\n!29:29 OUTD2 uint\n"
        "!30:30 OUTE2 uint\n!31:31 OUTF2 uint\n."
    )

    trigger_field_labels = (
        # Note the deliberate concatenation across lines - this must be a single
        # entry in the list
        "!Immediate\n!BITA=0\n!BITA=1\n!BITB=0\n!BITB=1\n!BITC=0\n!BITC=1\n"
        "!POSA>=POSITION\n!POSA<=POSITION\n!POSB>=POSITION\n!POSB<=POSITION\n"
        "!POSC>=POSITION\n!POSC<=POSITION\n."
    )

    dummy_server_in_thread.send += [
        "!PCAP 1\n!SEQ 1\n.",  # BLOCK definitions
        "OK =PCAP Desc",
        "OK =SEQ Desc",
        "!TRIG_EDGE 3 param enum\n!GATE 1 bit_mux\n.",  # PCAP fields
        "!TABLE 7 table\n.",  # SEQ field
        get_changes_scalar_data,
        "OK =Trig Edge Desc",
        "!Rising\n!Falling\n!Either\n.",  # TRIG_EDGE enum labels
        "OK =Gate Desc",
        "OK =100",  # GATE MAX_DELAY
        "!TTLIN1.VAL\n!INENC1.A\n!CLOCK1.OUT\n.",  # GATE labels
        "OK =Sequencer table of lines",  # TABLE Desc
        "OK =16384",  # TABLE MAX_LENGTH
        table_fields_data,
        get_changes_multiline_data,
        trigger_field_labels,
        "OK =Number of times the line will repeat",  # Repeats field desc
        "OK =The trigger condition to start the phases",  # TRIGGER field desc
        "OK =The position that can be used in trigger condition",  # POSITION field desc
        "OK =The time the optional phase 1 should take",  # TIME1 desc
        "OK =Output A value during phase 1",  # OUTA1 desc
        "OK =Output B value during phase 1",  # OUTB1 desc
        "OK =Output C value during phase 1",  # OUTC1 desc
        "OK =Output D value during phase 1",  # OUTD1 desc
        "OK =Output E value during phase 1",  # OUTE1 desc
        "OK =Output F value during phase 1",  # OUTF1 desc
        "OK =The time the mandatory phase 2 should take",  # TIME2 desc
        "OK =Output A value during phase 2",  # OUTA2 desc
        "OK =Output B value during phase 2",  # OUTB2 desc
        "OK =Output C value during phase 2",  # OUTC2 desc
        "OK =Output D value during phase 2",  # OUTD2 desc
        "OK =Output E value during phase 2",  # OUTE2 desc
        "OK =Output F value during phase 2",  # OUTF2 desc
    ]
    # If you need to change the above responses,
    # it'll probably help to enable debugging on the server
    # import os

    # os.remove(dummy_server_in_thread._debug_file)
    # dummy_server_in_thread.debug = True
    yield dummy_server_in_thread


@pytest_asyncio.fixture
def dummy_server_system(dummy_server_introspect_panda: DummyServer):
    """A server for a full system test"""

    # Add data for GetChanges to consume. Number of items should be bigger than
    # the sleep time given during IOC startup
    dummy_server_introspect_panda.send += ["."] * 50

    yield dummy_server_introspect_panda


@pytest_asyncio.fixture
def dummy_server_time(dummy_server_in_thread: DummyServer):
    """Dummy server just for the Time field"""
    dummy_server_in_thread.expected_message_responses.update(
        [
            ("*BLOCKS?", "!PULSE 1\n."),
            ("*DESC.PULSE?", "OK =One-shot pulse delay and stretch"),
            ("PULSE.*?", "!DELAY 1 time\n."),  # PULSE fields
            ("*DESC.PULSE.DELAY?", "OK =Output pulse delay (0 for no delay)"),
            ("*ENUMS.PULSE.DELAY.UNITS?", "!min\n!s\n!ms\n!us\n."),
            ("PULSE1.DELAY.MIN?", "OK =8e-06"),
            (
                "*CHANGES?",
                "!PULSE.DELAY=100\n!PULSE1.DELAY.UNITS=ms\n!PULSE1.DELAY.MIN=8e-06\n.",
            ),
        ]
    )

    # Add data for GetChanges to consume. Number of items should be bigger than
    # the sleep time given during IOC startup
    dummy_server_in_thread.send += ["."] * 50

    # If you need to change the above responses,
    # it'll probably help to enable debugging on the server
    # import os

    # if os.path.isfile(dummy_server_in_thread._debug_file):
    #     os.remove(dummy_server_in_thread._debug_file)
    # dummy_server_in_thread.debug = True

    yield dummy_server_in_thread


@patch("pandablocks_ioc.ioc.AsyncioClient.close")
@patch("pandablocks_ioc.ioc.softioc.interactive_ioc")
def ioc_wrapper(
    bobfile_dir: str,
    child_conn: Connection,
    mocked_interactive_ioc: MagicMock,
    mocked_client_close: MagicMock,
):
    """Wrapper function to start the IOC and do some mocking"""

    async def inner_wrapper():
        create_softioc("localhost", TEST_PREFIX, bobfile_dir)
        # If you see an error on the below line, it probably means an unexpected
        # exception occurred during IOC startup
        mocked_interactive_ioc.assert_called_once()
        mocked_client_close.assert_called_once()

        child_conn.send("R")  # "Ready"

        # Leave this process running until its torn down by pytest
        await asyncio.Event().wait()

    custom_logger()
    asyncio.run(inner_wrapper())


def select_and_recv(conn: Connection):
    """Wait for the given Connection to have data to receive, and return it.
    If a character is provided check its correct before returning it."""
    rrdy = False
    if conn.poll(TIMEOUT):
        rrdy = True

    if rrdy:
        val = conn.recv()
    else:
        pytest.fail("Did not receive anything before timeout")

    return val


@pytest_asyncio.fixture
def subprocess_ioc(
    tmp_path: Path, enable_codecov_multiprocess, caplog, caplog_workaround
) -> Generator[Path, None, None]:
    """Run the IOC in its own subprocess. When finished check logging logged no
    messages of WARNING or higher level."""
    with caplog.at_level(logging.WARNING):
        with caplog_workaround():
            ctx = get_multiprocessing_context()
            parent_conn, child_conn = ctx.Pipe()
            p = ctx.Process(target=ioc_wrapper, args=(tmp_path, child_conn))
            try:
                p.start()
                select_and_recv(parent_conn)  # Wait for IOC to start up
                yield tmp_path
            finally:
                p.terminate()
                p.join(10)
                # Should never take anywhere near 10 seconds to terminate, it's just
                # there to ensure the test doesn't hang indefinitely during cleanup

    # We expect all tests to pass without warnings (or worse) logged.
    assert (
        len(caplog.messages) == 0
    ), f"At least one warning/error/exception logged during test: {caplog.records}"


@pytest_asyncio.fixture
def mocked_time_record_updater():
    """An instance of _TimeRecordUpdater with MagicMocks and some default values"""
    base_record = MagicMock()
    base_record.name = TEST_PREFIX + ":BASE:RECORD"

    # We don't have AsyncMock in Python3.7, so do it ourselves
    client = MagicMock()
    f = asyncio.Future()
    f.set_result("8e-09")
    client.send.return_value = f

    mocked_record_info = MagicMock()
    mocked_record_info.record = MagicMock()
    mocked_record_info.record.name = EpicsName(TEST_PREFIX + ":TEST:STR")

    return _TimeRecordUpdater(
        mocked_record_info,
        client,
        {},
        ["TEST1", "TEST2", "TEST3"],
        base_record,
        TEST_PREFIX,
        True,
    )


def get_multiprocessing_context():
    """Tests must use "forkserver" method. If we use "fork" we inherit some
    state from Channel Access from test-to-test, which causes test hangs.
    We cannot use multiprocessing.set_start_method() as it doesn't work inside
    of Pytest."""
    if sys.platform == "win32":
        start_method = "spawn"
    else:
        start_method = "forkserver"
    return multiprocessing.get_context(start_method)


@pytest_asyncio.fixture
async def dummy_server_async():
    server = DummyServer()
    await server.open()
    yield server
    await server.close()


@pytest_asyncio.fixture
def dummy_server_in_thread():
    loop = asyncio.new_event_loop()
    server = DummyServer()
    t = threading.Thread(target=loop.run_forever)
    t.start()
    f = asyncio.run_coroutine_threadsafe(server.open(), loop)
    f.result(timeout=TIMEOUT)
    yield server
    asyncio.run_coroutine_threadsafe(server.close(), loop).result(timeout=TIMEOUT)
    loop.call_soon_threadsafe(loop.stop())
    t.join()


class Rows:
    def __init__(self, *rows):
        self.rows = rows

    def __eq__(self, o):
        same = o.tolist() == [pytest.approx(row) for row in self.rows]
        return same
