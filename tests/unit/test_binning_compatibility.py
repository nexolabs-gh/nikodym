"""Regresión de compatibilidad para la matriz OptBinning del extra ``scoring``."""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_optbinning_fit_real_compatible_con_sklearn_bloqueado() -> None:
    """Ejercita un fit real que falla si vuelve el ``TypeError`` de sklearn 1.8+."""
    script = textwrap.dedent(
        """
        import warnings

        import numpy as np
        import optbinning
        import ortools
        import sklearn
        from optbinning import OptimalBinning

        x = np.array(
            [
                -2.9905473309103234,
                -2.7103479483898267,
                -2.3890742298011736,
                -2.1747049480793614,
                -1.646856736127113,
                -1.363844337977086,
                -1.1215342997381281,
                -0.7507833548741435,
                -0.4596236770364335,
                -0.18558587866330795,
                0.2067731093984071,
                0.45815638319335783,
                0.773032489007628,
                1.0656558201267914,
                1.4438005351409897,
                1.7318822026772882,
                2.0798960146456023,
                2.338061767638047,
                2.6905519186713827,
                2.9553862978285106,
            ],
            dtype=float,
        )
        y = np.array([0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1])
        binner = OptimalBinning(
            name="x",
            dtype="numerical",
            prebinning_method="uniform",
            solver="mip",
            max_n_prebins=5,
            min_prebin_size=0.05,
        )

        # Deuda conocida: OptBinning 0.20.0 llama el keyword deprecado en sklearn 1.6/1.7.
        # El warning se captura solo aquí para no relajar `filterwarnings=error` en la suite.
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", FutureWarning)
            binner.fit(x, y)

        warning_messages = [str(warning.message) for warning in captured]
        assert any("force_all_finite" in message for message in warning_messages)
        assert binner.status == "OPTIMAL"
        assert len(binner.splits) > 0
        print(
            f"optbinning={optbinning.__version__} "
            f"ortools={ortools.__version__} "
            f"scikit-learn={sklearn.__version__} "
            f"status={binner.status} n_splits={len(binner.splits)}"
        )
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "status=OPTIMAL" in completed.stdout
    assert "n_splits=" in completed.stdout
