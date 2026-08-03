"""Gate de las CIFRAS DE TESTS que publican la landing y el README.

Las dos superficies afirman cuántos tests tiene la librería. Es copy público —lo lee un banco que
está decidiendo si confía en el motor— y hasta hoy **no lo ataba nada**: `landing-evidence.test.ts`
re-deriva del fixture todo lo demás que la página publica, pero estas dos constantes no salen de un
fixture, salen de correr la suite, así que quedaban fuera por construcción.

🔴 El modo de fallo que este gate existe para cerrar es sutil, y es propio de la política de
«publicar debajo» que la landing eligió a propósito: **una cota inferior nunca deja de ser
verdadera**. `TESTS_SUITE` se quedó en "4.400" con una procedencia anotada de 4.482 mientras la
suite real llegaba a 4.971 — seguía siendo cierta y subestimaba el producto en casi 600 tests. Nada
la delataba, porque no había nada que delatar: no estaba mal, estaba vieja. Y en paralelo el README
publicaba "más de 4.500" sobre el mismo número, así que las dos superficies públicas se
contradecían.

⚠️ **Límite declarado, no escondido: la cota de la suite completa NO se compara contra una
recolección en vivo.** Los 9 jobs de la matriz `Tests (os, python)` instalan `--extra scoring` y
nada más (`.github/workflows/ci.yml:69`), así que ahí `--collect-only` recolecta menos tests que en
un árbol completo y un gate que comparase contra él daría rojo por el entorno, no por el dato. En su
lugar se ata la cota a la **procedencia que el propio archivo documenta**, que obliga a que quien
remida actualice las dos cosas a la vez. La cifra que sí se remide de verdad es la de los tres
dominios sin interfaz, que es un subconjunto que no depende de extras opcionales.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_EVIDENCIA = _RAIZ / "web" / "src" / "components" / "landing-evidence.ts"
_README = _RAIZ / "README.md"

# Los tres dominios que no tienen interfaz. Escritos a mano desde la decisión de producto que los
# agrupa (survival SALIÓ de este grupo en la 1.7.0 al ganar pantalla), nunca derivados de un glob:
# un oráculo que descubriera el grupo solo no notaría que un dominio cambió de lado.
_DOMINIOS_SIN_INTERFAZ = ("markov", "stress", "forward")


def _cota(nombre: str) -> int:
    """La cifra que la landing publica, como entero. `"4.900"` → `4900`."""
    texto = _EVIDENCIA.read_text(encoding="utf-8")
    match = re.search(rf'export const {nombre} = "([\d.]+)"', texto)
    assert match, f"no se encontró la constante {nombre} en landing-evidence.ts"
    return int(match.group(1).replace(".", ""))


def _procedencia(etiqueta: str) -> int:
    """La medición que el comentario de cabecera declara haber hecho."""
    texto = _EVIDENCIA.read_text(encoding="utf-8")
    match = re.search(rf"{etiqueta} \.+ ([\d.]+)", texto)
    assert match, f"no se encontró la procedencia documentada de «{etiqueta}»"
    return int(match.group(1).replace(".", ""))


def _recolectados(rutas: list[str]) -> int:
    """Cuenta real de tests, con pytest en un subproceso.

    En subproceso y no con `request.session`: este gate tiene que poder medir un SUBCONJUNTO, y la
    sesión en curso sólo conoce lo que se le pidió recolectar a ella.
    """
    salida = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *rutas],
        capture_output=True,
        text=True,
        cwd=_RAIZ,
        check=False,
    )
    match = re.search(r"(\d+) tests? collected", salida.stdout)
    assert match, f"no se pudo leer la cuenta de pytest. stdout:\n{salida.stdout[-2000:]}"
    return int(match.group(1))


def test_las_dos_superficies_publican_la_misma_cota() -> None:
    """El README y la landing hablan del mismo número, y hasta hoy no lo hacían (4.500 vs 4.400)."""
    cota = _cota("TESTS_SUITE")
    readme = _README.read_text(encoding="utf-8")
    match = re.search(r"más de ([\d.]+) en la suite completa", readme)
    assert match, "el README dejó de publicar la cota de la suite: revisa si se movió la frase"
    assert int(match.group(1).replace(".", "")) == cota, (
        f"README publica {match.group(1)} y la landing {cota}. Son el mismo dato en dos "
        "superficies públicas: se barren en el mismo commit."
    )


def test_la_cota_publicada_es_cierta_segun_su_propia_procedencia() -> None:
    """«Más de N» exige que N no supere lo medido, o la página miente hacia arriba."""
    assert _cota("TESTS_SUITE") <= _procedencia("suite completa")
    assert _cota("TESTS_DOMINIOS") <= _procedencia("los TRES dominios sin interfaz")


def test_la_cota_publicada_no_se_queda_vieja() -> None:
    """El defecto real: una cota inferior envejece sin dejar de ser verdadera.

    El margen es holgado a propósito —la cifra se redondea hacia abajo y no se persigue commit a
    commit—, pero acotado: 479 tests de desfase es lo que había cuando esto se escribió.
    """
    for nombre, etiqueta in (
        ("TESTS_SUITE", "suite completa"),
        ("TESTS_DOMINIOS", "los TRES dominios sin interfaz"),
    ):
        desfase = _procedencia(etiqueta) - _cota(nombre)
        assert desfase < 200, (
            f"{nombre} publica {_cota(nombre)} y su propia procedencia dice "
            f"{_procedencia(etiqueta)}: {desfase} de desfase. Sube la cota — subestimar el "
            "producto en la página que argumenta que todo está verificado es publicar mal."
        )


def test_la_procedencia_de_los_tres_dominios_es_la_medicion_real() -> None:
    """El único oráculo INDEPENDIENTE del gate: se remide, no se cree lo que el archivo dice.

    Es el subconjunto que se puede medir en cualquier job —no depende de ningún extra opcional más
    allá de `scoring`—, y es justamente la cifra que ya se equivocó una vez: decía "más de 600"
    mientras survival contaba en el grupo, y dejó de ser cierta al salir.
    """
    # Los globs se expanden aquí y no se le pasan a pytest: `subprocess.run` con lista no pasa por
    # el shell, y pytest los recibiría como rutas literales inexistentes. Lo destapó este mismo
    # gate al escribirlo — recolectó cero y su ancla anti-vacuidad lo cazó.
    rutas = sorted(
        str(ruta.relative_to(_RAIZ))
        for dominio in _DOMINIOS_SIN_INTERFAZ
        for ruta in (_RAIZ / "tests" / "unit").glob(f"test_{dominio}_*.py")
    )
    assert len(rutas) >= 10, f"sólo se encontraron {len(rutas)} archivos: el glob está roto"
    real = _recolectados(rutas)
    assert real >= 400, f"sólo se recolectaron {real}: el glob no está encontrando los archivos"
    assert real == _procedencia("los TRES dominios sin interfaz"), (
        f"los tres dominios sin interfaz recolectan {real} tests y la cabecera de "
        f"landing-evidence.ts declara {_procedencia('los TRES dominios sin interfaz')}. "
        "Remide y actualiza las dos cosas: la procedencia y, si hace falta, la cota."
    )
