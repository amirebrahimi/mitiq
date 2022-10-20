# Copyright (C) 2021 Unitary Fund
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Unit tests for readout confusion inversion."""
from functools import partial
import cirq
from cirq.experiments.single_qubit_readout_calibration_test import (
    NoisySingleQubitReadoutSampler,
)
import numpy as np
import pytest

from mitiq.interface.mitiq_cirq.cirq_utils import (
    generate_inverse_confusion_matrix,
)
from mitiq.observable.observable import Observable
from mitiq.observable.pauli import PauliString
from mitiq._typing import MeasurementResult
from mitiq.rem.rem import execute_with_rem, mitigate_executor, rem_decorator
from mitiq.raw import execute as raw_execute
from mitiq.interface.mitiq_cirq import sample_bitstrings

# Default qubit register and circuit for unit tests
qreg = [cirq.LineQubit(i) for i in range(2)]
circ = cirq.Circuit(cirq.ops.X.on_each(*qreg), cirq.measure_each(*qreg))
observable = Observable(PauliString("ZI"), PauliString("IZ"))


def noisy_readout_executor(
    circuit, p0: float = 0.01, p1: float = 0.01, shots: int = 8192
) -> MeasurementResult:
    simulator = NoisySingleQubitReadoutSampler(p0, p1)
    result = simulator.run(circuit, repetitions=shots)

    return MeasurementResult(
        result=np.column_stack(list(result.measurements.values())),
        qubit_indices=tuple(
            # q[2:-1] is necessary to convert "q(number)" into "number"
            int(q[2:-1])
            for k in result.measurements.keys()
            for q in k.split(",")
        ),
    )


def test_rem_identity():
    executor = partial(sample_bitstrings, noise_level=(0,))
    identity = np.identity(4)
    result = execute_with_rem(
        circ, executor, observable, inverse_confusion_matrix=identity
    )
    assert np.isclose(result, -2.0)


def test_rem_with_matrix():
    # test with an executor that completely flips results
    p0 = 1
    p1 = 1
    noisy_executor = partial(noisy_readout_executor, p0=p0, p1=p1)
    unmitigated = raw_execute(circ, noisy_executor, observable)
    assert np.isclose(unmitigated, 2.0)

    inverse_confusion_matrix = np.array(
        [
            [0, 0, 0, 1],
            [0, 0, 1, 0],
            [0, 1, 0, 0],
            [1, 0, 0, 0],
        ]
    )

    mitigated = execute_with_rem(
        circ,
        noisy_executor,
        observable,
        inverse_confusion_matrix=inverse_confusion_matrix,
    )
    assert np.isclose(mitigated, -2.0)


def test_rem_with_invalid_matrix():
    executor = partial(sample_bitstrings, noise_level=(0,))
    identity = np.identity(2)
    with pytest.raises(AssertionError):
        execute_with_rem(
            circ, executor, observable, inverse_confusion_matrix=identity
        )


def test_doc_is_preserved():
    """Tests that the doc of the original executor is preserved."""

    def first_executor(circuit):
        """Doc of the original executor."""
        return 0

    identity = np.identity(4)

    mit_executor = mitigate_executor(
        first_executor, inverse_confusion_matrix=identity
    )
    assert mit_executor.__doc__ == first_executor.__doc__

    @rem_decorator(inverse_confusion_matrix=identity)
    def second_executor(circuit):
        """Doc of the original executor."""
        return 0

    assert second_executor.__doc__ == first_executor.__doc__


def test_mitigate_executor():
    true_rem_value = -2.0

    # test with an executor that completely flips results
    p0 = 1
    p1 = 1
    noisy_executor = partial(noisy_readout_executor, p0=p0, p1=p1)

    inverse_confusion_matrix = np.array(
        [
            [0, 0, 0, 1],
            [0, 0, 1, 0],
            [0, 1, 0, 0],
            [1, 0, 0, 0],
        ]
    )

    base = raw_execute(circ, noisy_executor, observable)

    mitigated_executor = mitigate_executor(
        noisy_executor,
        observable,
        inverse_confusion_matrix=inverse_confusion_matrix,
    )
    rem_value = mitigated_executor(circ)
    assert abs(true_rem_value - rem_value) < abs(true_rem_value - base)


def test_rem_decorator():
    true_rem_value = -2.0

    qubits = list(circ.all_qubits())

    # test with an executor that completely flips results
    p0 = 1
    p1 = 1
    inverse_confusion_matrix = generate_inverse_confusion_matrix(
        qubits, p0=p0, p1=p1
    )

    @rem_decorator(
        observable, inverse_confusion_matrix=inverse_confusion_matrix
    )
    def noisy_readout_decorated_executor(qp) -> MeasurementResult:
        # test with an executor that completely flips results
        return noisy_readout_executor(qp, p0=1, p1=1)

    noisy_executor = partial(noisy_readout_executor, p0=p0, p1=p1)

    base = raw_execute(circ, noisy_executor, observable)

    rem_value = noisy_readout_decorated_executor(circ)
    assert abs(true_rem_value - rem_value) < abs(true_rem_value - base)