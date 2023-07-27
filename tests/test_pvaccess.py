import collections
from typing import cast, OrderedDict

import numpy
import pytest
from fixtures.mocked_panda import TEST_PREFIX
from numpy import ndarray
from p4p import Value
from p4p.client.thread import Context

from pandablocks_ioc._types import EpicsName


@pytest.mark.asyncio
async def test_table_column_info(
    mocked_panda_standard_responses,
    table_unpacked_data: OrderedDict[EpicsName, ndarray],
):
    """Test that the table columns have the expected PVAccess information in the
    right order"""

    ctxt = Context("pva", nt=False)

    table_value: Value = ctxt.get(TEST_PREFIX + ":SEQ1:TABLE")

    for (actual_name, actual_value), (expected_name, expected_value) in zip(
        table_value.todict(wrapper=collections.OrderedDict)["value"].items(),
        table_unpacked_data.items(),
    ):
        cast(str, actual_name)
        assert actual_name.upper() == expected_name, (
            f"Order of columns incorrect expected: {expected_name} "
            f"Actual: {actual_name.upper()}"
        )
        numpy.testing.assert_array_equal(actual_value, expected_value)
