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

"""Readout Confusion Inversion."""

from typing import Callable, Iterable, List, Optional, Sequence, Tuple, Union

from functools import partial, wraps
import numpy as np

from mitiq import (
    Executor,
    Observable,
    QPROGRAM,
    MeasurementResult,
)

from cirq.experiments.single_qubit_readout_calibration_test import (
    NoisySingleQubitReadoutSampler,
)
from cirq.experiments.readout_confusion_matrix import measure_confusion_matrix
from cirq.sim import sample_state_vector
from cirq.qis.states import to_valid_state_vector

MatrixLike = Union[
    np.ndarray,
    Iterable[np.ndarray],
    List[np.ndarray],
    Sequence[np.ndarray],
    Tuple[np.ndarray],
]


def execute_with_rci(
    circuit: QPROGRAM,
    executor: Union[Executor, Callable[[QPROGRAM], MeasurementResult]],
    observable: Optional[Observable] = None,
    inverse_confusion_matrix: Optional[MatrixLike] = None,
    p0: float = 0.01,
    p1: float = 0.01,
) -> float:
    """Returns the readout error mitigated expectation value utilizing an
    inverse confusion matrix that is computed by running the quantum program
    `circuit` with the executor function.

    Args:
        executor: A Mitiq executor that executes a circuit and returns the
            unmitigated ``MeasurementResult``.
        observable: Observable to compute the expectation value of.
        inverse_confusion_matrix: The inverse confusion matrix to apply to the
            probability vector that represents the noisy measurement results.
            If None, then an inverse confusion matrix will be generated
            utilizing the same `executor`.
        p0: Probability of flipping a 0 to a 1.
        p1: Probability of flipping a 1 to a 0.
    """
    if not isinstance(executor, Executor):
        executor = Executor(executor)

    qubits = list(circuit.all_qubits())

    if inverse_confusion_matrix is None:
        print("No inverse confusion matrix provided. Generating...")

        # Build a tensored confusion matrix using smaller single qubit confusion matrices.
        # Implies that errors are uncorrelated among qubits
        tensored_matrix = measure_confusion_matrix(
            NoisySingleQubitReadoutSampler(p0, p1), [[q] for q in qubits]
        )
        inverse_confusion_matrix = tensored_matrix.correction_matrix()

    result = executor._run([circuit])
    noisy_result = result[0]
    assert isinstance(noisy_result, MeasurementResult)

    measurement_to_state_vector = partial(
        to_valid_state_vector, num_qubits=len(qubits)
    )

    noisy_state_vectors = np.apply_along_axis(
        measurement_to_state_vector, 1, noisy_result.asarray
    )

    adjusted_state_vectors = (
        inverse_confusion_matrix @ noisy_state_vectors.T
    ).T

    state_vector_to_measurement = partial(
        sample_state_vector, indices=noisy_result.qubit_indices
    )

    adjusted_result = np.apply_along_axis(
        state_vector_to_measurement, 1, adjusted_state_vectors
    ).squeeze()

    result = MeasurementResult(adjusted_result, noisy_result.qubit_indices)
    return observable._expectation_from_measurements([result])


def mitigate_executor(
    executor: Callable[[QPROGRAM], MeasurementResult],
    observable: Optional[Observable] = None,
    *,
    inverse_confusion_matrix: Optional[MatrixLike] = None,
    p0: float = 0.01,
    p1: float = 0.01,
) -> Callable[[QPROGRAM], float]:
    """Returns a modified version of the input 'executor' which is
    error-mitigated with readout confusion inversion (RCI).

    Args:
        executor: A Mitiq executor that executes a circuit and returns the
            unmitigated ``MeasurementResult``.
        observable: Observable to compute the expectation value of.
        inverse_confusion_matrix: The inverse confusion matrix to apply to the
            probability vector that represents the noisy measurement results.
            If None, then an inverse confusion matrix will be generated
            utilizing the same `executor`.
        p0: Probability of flipping a 0 to a 1.
        p1: Probability of flipping a 1 to a 0.

    Returns:
        The error-mitigated version of the input executor.
    """

    @wraps(executor)
    def new_executor(qp: QPROGRAM) -> float:
        return execute_with_rci(
            qp,
            executor,
            observable,
            inverse_confusion_matrix=inverse_confusion_matrix,
            p0=p0,
            p1=p1,
        )

    return new_executor


def rci_decorator(
    observable: Optional[Observable] = None,
    *,
    inverse_confusion_matrix: Optional[MatrixLike] = None,
    p0: float = 0.01,
    p1: float = 0.01,
) -> Callable[
    [Callable[[QPROGRAM], MeasurementResult]], Callable[[QPROGRAM], float]
]:
    """Decorator which adds an error-mitigation layer based on readout
    confusion inversion (RCI) to an executor function, i.e., a function
    which executes a quantum circuit with an arbitrary backend and returns
    a ``MeasurementResult``.

    Args:
        observable: Observable to compute the expectation value of.
        inverse_confusion_matrix: The inverse confusion matrix to apply to the
            probability vector that represents the noisy measurement results.
            If None, then an inverse confusion matrix will be generated
            utilizing the same `executor`.
        p0: Probability of flipping a 0 to a 1.
        p1: Probability of flipping a 1 to a 0.

    Returns:
        The error-mitigating decorator to be applied to an executor function.
    """
    # Raise an error if the decorator is used without parenthesis
    if callable(observable):
        raise TypeError(
            "Decorator must be used with parentheses (i.e., @rci_decorator()) "
            "even if no explicit arguments are passed."
        )

    def decorator(
        executor: Callable[[QPROGRAM], MeasurementResult]
    ) -> Callable[[QPROGRAM], float]:
        return mitigate_executor(
            executor,
            observable,
            inverse_confusion_matrix=inverse_confusion_matrix,
            p0=p0,
            p1=p1,
        )

    return decorator
