from typing import Dict, List, OrderedDict

import pytest
from numpy import array, dtype, int32, ndarray, uint8, uint16, uint32
from pandablocks.responses import FieldCapture, TableFieldDetails, TableFieldInfo

from pandablocks_ioc._types import EpicsName


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
def table_data_1() -> List[str]:
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
def table_data_2() -> List[str]:
    """Table data associated with table_fields and table_field_info fixtures.
    See table_unpacked_data for the unpacked equivalent"""

    return [
        "2457862149",
        "4294967291",
        "100",
        "0",
        "0",
        "0",
        "0",
        "0",
        "4293968720",
        "0",
        "9",
        "9999",
        "2035875928",
        "444444",
        "5",
        "1",
        "3464285461",
        "4294967197",
        "99999",
        "2222",
    ]


@pytest.fixture
def table_unpacked_data(
    table_fields: Dict[str, TableFieldDetails]
) -> OrderedDict[EpicsName, ndarray]:
    """The unpacked equivalent of table_data"""
    array_values: List[ndarray] = [
        array([5, 0, 50000], dtype=uint16),
        array(["Immediate", "BITC=1", "Immediate"]),
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


@pytest.fixture
def raw_dump_table_fields():
    return [
        FieldCapture(
            name="PCAP.BITS2",
            type=dtype("uint32"),
            capture="Value",
            scale=1,
            offset=0,
            units="",
        ),
        FieldCapture(
            name="COUNTER1.OUT",
            type=dtype("float64"),
            capture="Min",
            scale=1,
            offset=0,
            units="",
        ),
        FieldCapture(
            name="COUNTER1.OUT",
            type=dtype("float64"),
            capture="Max",
            scale=1,
            offset=0,
            units="",
        ),
        FieldCapture(
            name="COUNTER3.OUT",
            type=dtype("float64"),
            capture="Value",
            scale=1,
            offset=0,
            units="",
        ),
        FieldCapture(
            name="PCAP.TS_START",
            type=dtype("float64"),
            capture="Value",
            scale=8e-09,
            offset=0,
            units="s",
        ),
        FieldCapture(
            name="COUNTER1.OUT",
            type=dtype("float64"),
            capture="Mean",
            scale=1,
            offset=0,
            units="",
        ),
        FieldCapture(
            name="COUNTER2.OUT",
            type=dtype("float64"),
            capture="Mean",
            scale=1,
            offset=0,
            units="",
        ),
    ]
