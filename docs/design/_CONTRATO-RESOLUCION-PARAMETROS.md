# Contrato transversal — resolución de parámetros de riesgo

| Campo | Valor |
|---|---|
| **Documento** | Contrato transversal de resolución de parámetros (se provee · se modela · sale del histórico) |
| **Tipo** | Decisiones troncales (cruzan `provisioning/{cmf,ifrs9,internal}`, `forward`, `stress`, `survival`, `calibration`) |
| **Versión** | 0.1 — **BORRADOR, pendiente de aprobación de Cami** |
| **Fecha** | 2026-07-25 |
| **Autor** | DanIA |
| **Base** | Censo del código en `main` = `c02a4f7`; requisito 3 de la visión de producto (`AGENTS.md` §Visión) |
| **Estado** | Propuesto. **No se programa nada hasta que esté aprobado** |

---

## 1. Por qué existe este documento

El requisito 3 de la visión dice: **para PD, LGD, EAD, PIT/TTC, calibración y escenarios macro, y en los
tres motores, el dato se provee, se modela, o sale del histórico — todas las alternativas, no una**.

La tentación es implementarlo motor por motor. El censo dice por qué eso sería un error: **hoy cada
parámetro ya tiene su propia política de resolución, y esas políticas se contradicen entre motores
para el mismo parámetro**. Añadir dos vías nuevas a cada uno multiplicaría las contradicciones en vez
de resolverlas.

Este documento fija **cómo se resuelve un parámetro**, no qué estimador usa cada motor. Es la misma
regla rectora de los contratos transversales v1: *diseña de extremo a extremo lo caro de cambiar
(las interfaces), difiere lo barato (la lógica intra-capa)*.

## 2. El problema, medido

Censo sobre el código real de `provisioning/{cmf,ifrs9,internal}`, `forward`, `stress`, `survival` y
`calibration` (~7.000 líneas leídas, cada afirmación con `archivo:línea`). Cuatro patologías, y
ninguna es una opinión de estilo:

### P1 · La misma carencia falla de formas opuestas

| Carencia | Un motor | Otro motor |
|---|---|---|
| LGD ausente en la cadena forward→stress | `forward` degrada a `None` con un warning **sin prefijo**, invisible para la card (`forward/satellite.py:398-418`) | `stress` levanta `DATO-INSTITUCIONAL-STR-8` y **aborta** (`stress/engine.py:2465-2486`) |
| Columna declarada en config que no está en el frame | `days_past_due` → `IfrsStagingError` (`ifrs9/staging.py:309-312`) | `is_default` → **el gatillo Stage 3 se apaga en silencio** (`ifrs9/staging.py:200-205`) |
| Insumo de LGD workout ausente | `recovery_time_years` → `IfrsLgdError` | `recovery_cost` → **ceros silenciosos** (`ifrs9/lgd.py:140-145`) |
| Historia macro insuficiente | `macro.py` nunca la relaja → `ForwardFitError` | `satellite.py` sí la relaja según el modo (`forward/satellite.py:273-297`) |

### P2 · Lo institucional se decide solo, o no se decide

`rho` no tiene default y detiene la corrida (`ifrs9/config.py:96-106`). Los umbrales SICR (2.0, 3.0),
los backstops de mora (30/90) y el horizonte de 12 períodos son **igual de institucionales** y se
aplican como constantes, sin aviso (`ifrs9/config.py:125-133`, `329-365`). No hay criterio: el mismo
tipo de dato a veces exige decisión explícita y a veces se inventa.

El caso más grave: **el gatillo SICR cuantitativo —el corazón de IFRS 9— viene apagado por defecto**
(`origination_pd_life_col=None`) y el motor no lo declara en ninguna parte
(`ifrs9/config.py:378-383`, `staging.py:159-162`).

### P3 · La procedencia del valor no se registra

`satellite._scenario_weights` cascadea tres fuentes —atributo del objeto, columna del frame,
config— **sin dejar constancia de cuál ganó** (`forward/satellite.py:729-747`). En IFRS 9, informar
`recovery_col` anula `lgd_col` por completo y sin aviso (`ifrs9/lgd.py:128-132`). En todo el repo hay
**un solo** lugar que marca procedencia: el `source="default_a_confirmar"` de los pesos de escenario
(`forward/scenarios.py:91-106`). Para un motor que se vende por su auditabilidad, esto es la brecha
más seria del censo.

Y la vía «institucional con evidencia» no existe: `source='official'` en `stress` **sólo sirve para
bloquear** —lo verifica dos veces, en config y en runtime— y no hay ninguna ruta que acepte la
metadata externa y deje pasar el valor (`stress/config.py:938-952`, `stress/engine.py:1811-1837`).

### P4 · El momento de validación es arbitrario

Tres carencias declarativas equivalentes, tres momentos y tres excepciones: fuente de CCF ausente →
`IfrsEadError` en runtime; pesos `source='config'` → `IfrsConfigError` al construir; pesos
`source='forward'` que no suman 1 → `IfrsEclError` **después de staging** (`ifrs9/ead.py:155-164`,
`config.py:484-517`, `ecl.py:360-380`). El principio declarado del proyecto es que una opción mala se
rechaza **al validar**.

### P5 · El corolario: `fail_on_falta_dato` es tres cosas

Confirmado por el censo en las tres familias: en `ifrs9` sólo gatilla el chequeo PIT y con `False` el
fallo ocurre igual, más tarde (`ifrs9/config.py:637-646`); en `survival` es un **campo reservado que
no altera nada** (`survival/config.py:301-310`); en `forward` se compone con un segundo flag por AND
(`forward/config.py:650`); en `stress` e `internal` sí hace lo que dice. Un nombre, cinco
comportamientos.

### Cuánto de esto ya se cobra la corrida

El config por defecto de IFRS 9 **no es ejecutable**: sus tres defaults (`term_structure_source`,
`scenarios.source`, `ead.method`) se contradicen entre sí y el preset de la UI tiene que
sobrescribirlos (`ui/presets.py:751-800`). Es el síntoma exacto de un contrato de resolución
inexistente.

## 3. Las decisiones

### CRP-1 — Un parámetro de riesgo se declara, no se cablea

Todo parámetro resoluble (PD, LGD, EAD, CCF, `rho`, factor sistémico, tasa de descuento, pesos de
escenario, shocks, tasa central de calibración, umbrales SICR) se declara con las **vías que admite**,
en vez de escribirse como campo suelto con una política implícita:

```python
class ParameterSource(StrEnum):
    PROVIDED   = "provided"     # viene en una columna del dataset
    DECLARED   = "declared"     # lo fija la institución en el config
    ESTIMATED  = "estimated"    # el motor lo modela desde el histórico
    REGULATORY = "regulatory"   # sale de una tabla normativa versionada (matrices CMF)
```

**Las cuatro vías son el contrato; qué vías admite cada parámetro lo declara su motor.** Un parámetro
que hoy sólo admite una vía no se vuelve mágicamente flexible: se vuelve **explícito** sobre lo que
no admite, que es el paso previo obligatorio.

### CRP-2 — Resolución explícita; el modo automático es opt-in y deja rastro

Se acaba la cascada implícita. El usuario declara la vía. Existe un modo `auto` con un orden de
precedencia **documentado y estable**, pero es opt-in y **registra cuál vía ganó**. Una cascada que
no dice cuál fuente usó no es una comodidad: es un número sin trazabilidad, y este motor se vende por
la trazabilidad.

### CRP-3 — El valor viaja con su procedencia (`Resolved[T]`)

Un parámetro resuelto no es un `float`: es el valor **más** de dónde salió.

```python
@dataclass(frozen=True)
class Resolved[T]:
    value: T
    source: ParameterSource
    origin: str          # columna, campo de config, estimador, o id de tabla normativa
    evidence: str | None # hash del archivo, cita normativa, n de la muestra de ajuste
    is_default: bool     # ¿lo eligió el motor porque el usuario no dijo nada?
```

La procedencia entra al **audit-trail y a la model card**, y es lo que convierte `official` de veto en
vía real: un shock con `source=DECLARED`, `origin="circular_2345.pdf"`, `evidence=<sha256>` es
auditable; hoy simplemente se rechaza.

### CRP-4 — Prohibido apagarse en silencio

Si por falta de un dato un gatillo, un ajuste o un paso **queda inerte**, se emite marca declarada.
Sin excepciones. Esto mata de una vez los casos del censo: `is_default` ausente, `pd_pit_origination`
ausente, `origination_pd_life_col=None`, `recovery_cost`→ceros, contingente→0, `lgd_base` ausente en
forward. Un motor que no calcula algo y no lo dice es peor que uno que falla.

Corolario de taxonomía: **todo warning que declare una carencia lleva prefijo de marca**. Los cuatro
warnings sin prefijo de `forward` (`hazard_derivado_desde_pd_marginal`, `lgd_base_ausente`,
`pd_basis_asumida_desde_config`, `pd_basis_no_resuelta`) son invisibles para `card.falta_dato` porque
el filtro es por prefijo — degradaciones reales que no llegan al informe.

### CRP-5 — Dos momentos de validación, no cinco

**(1) Al validar el config**: todo lo decidible sin mirar el dato —vías incompatibles, pesos que no
suman 1, un `Literal` fuera de rango—. **(2) En un gate único de entrada al motor**: todo lo que
depende del dato —columna ausente, cobertura incompleta, rango inválido—. **Nada se valida a mitad
del cálculo.** Un peso de escenario que no suma 1 no puede descubrirse después de staging.

### CRP-6 — `fail_on_falta_dato` tiene una sola semántica en todo el paquete

Se redefine como: *«¿una marca declarada emitida durante la corrida la detiene?»*, con ese
comportamiento en **todas** las capas. Lo que hoy significa otra cosa (el chequeo PIT anticipado de
IFRS 9) se renombra a lo que hace. El campo reservado de `survival` se implementa o se elimina; un
campo que el usuario escribe y no hace nada es peor que ausente.

## 4. Qué se fija ahora y qué se difiere

**Se fija ahora** (barato, estructural, y caro de cambiar después): las cuatro vías, el `Resolved[T]`
con procedencia, la prohibición de apagado silencioso, los dos momentos de validación y la semántica
única del flag.

**Se difiere** (a cada SDD de dominio, cuando toque): *qué* estimador concreto usa cada parámetro por
la vía `ESTIMATED`; el orden de precedencia del modo `auto` por parámetro; y la migración de los ~20
nombres de columna literales del motor CMF (`engine.py:509-514`, `872`, `926`, `993`…) a parámetros
declarados.

**Fuera de alcance, y hay que decirlo:** EAD **no tiene dueño** en `forward` ni en `stress` — vive
entero en el motor ECL inyectado y sólo se lo reconoce por nombre de columna a excluir
(`stress/engine.py:332-349`). O entra al contrato con dueño explícito, o se declara fuera; hoy está
en tierra de nadie.

## 5. Relación con B3.a (dejar de asumir Chile)

El censo encontró **15 puntos** donde la jurisdicción chilena está en el código, y el más profundo no
es la tabla de matrices sino la **taxonomía de carteras**: `cartera: Literal["comercial", "consumo",
"hipotecario", "grupal"]` en `governance/config.py:27`, las 6 carteras literales del motor CMF
(`cmf/engine.py:96-103`), los tramos de mora B-1, el `is_default = dpd >= 90` cableado
(`cmf/engine.py:540`) y el default `cmf_portfolio` que ata a `internal/` (`internal/config.py:119`).

Esto **confirma la decisión ya tomada**: B3.a va antes de construir la matriz de flexibilidad encima.
Un `ParameterSpec` cuya llave de segmentación sea un `Literal` chileno hay que rehacerlo entero para
Perú. Los dos trabajos tocan los mismos archivos, así que el orden importa y el orden es: **primero
desacoplar la jurisdicción, después la resolución de parámetros.**

## 6. Criterios de aceptación

1. Ninguna cascada de resolución sin registro de la vía ganadora.
2. Ningún gatillo o ajuste que quede inerte sin marca declarada; test que lo verifique por capa.
3. `fail_on_falta_dato` con el mismo comportamiento observable en las siete capas, verificado con un
   test parametrizado por capa —no uno por capa escrito a mano—.
4. La model card de una corrida permite responder, para cada parámetro: *¿de dónde salió este
   número?* Sin leer el config y sin abrir el código.
5. El config por defecto de cada motor es **ejecutable**: sus defaults no se contradicen entre sí.

## 7. Riesgos

- **Alcance.** Toca siete capas y ~7.000 líneas. Mitigación: se adopta por capa, empezando por la que
  más duele (IFRS 9), y cada capa entra con sus tests antes de seguir.
- **Ruptura de configs existentes.** Redefinir `fail_on_falta_dato` cambia comportamiento observable.
  Va en `1.6.0` con nota explícita en el CHANGELOG; las capas afectadas están declaradas
  experimentales, salvo el flag, que hay que revisar caso a caso.
- **Sobrediseño.** El riesgo simétrico: un contrato tan general que nadie pueda implementarlo. Por eso
  §4 difiere los estimadores concretos y fija sólo las interfaces.
