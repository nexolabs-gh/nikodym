# Enmienda — el paso CMF declara lo que de verdad necesita (M-3)

> 🔴 **Estado: NO SE IMPLEMENTA. Decisión de producto de Cami, 2026-08-05.** No es un rechazo del
> diagnóstico —que está medido y es correcto— sino del **destino de la inversión**: la normativa
> local de cada país sale del alcance de la librería.
>
> > *«Descartamos normativa local de países hace tiempo atrás: CMF, norma peruana, boliviana, etc.
> > No podemos estar detrás de cada actualización de cada país para que RiskLib esté al corriente.
> > Sólo podemos seguir estándares comunes como Basilea o IFRS 9 […] Lo que sí hay que dejar es
> > todo bien para, por ejemplo, un modelo PD y LGD, y luego el modelador —o la misma Nikodym
> > Advisory— hace los ajustes para llevarlo a la normativa local del país.»*
>
> El documento se conserva **escrito y sin implementación**, con el precedente de D-MAX-3 y
> D-SEG-11: el diagnóstico costó medirlo y sigue siendo cierto el día que CMF vuelva al alcance.
>
> ⚠️ **Lo que sí sobrevive de aquí es §2.2 y §4**, porque no son de CMF: la mentira de
> `inert_artifacts` y el hallazgo de la cobertura regulatoria asimétrica valen igual, y la primera
> se cierra por la vía de [`_ENMIENDA-REQUISITOS-DECLARADOS.md`](_ENMIENDA-REQUISITOS-DECLARADOS.md),
> que es donde M-2 y M-3 resultaron ser el mismo defecto.
>
> Enmienda a [`15-provisioning-cmf.md`](15-provisioning-cmf.md) §4, §7 y §9.
> Decisiones: **D-CMF-1 … D-CMF-6**, ninguna vigente.

---

## 1. El problema, y por qué NO es un olvido

`CmfProvisioningStep.requires` es un atributo de clase fijo —`(("data", "frame"),)`
(`provisioning/cmf/step.py:62`)— mientras el paso, bajo `pd_mapping.method='pd_breaks'`, exige
**tres** artefactos más (`cmf/step.py:291-294`):

1. `(pd_mapping.pd_source_domain, pd_mapping.pd_source_key)` — por defecto `("model", "raw_pd_frame")`
2. `("data", "labels")`
3. `("data", "splits")`

Sus **tres hermanas de provisiones** lo construyen dinámico, con el mismo patrón: atributo de clase
como default y asignación en `__init__` que lo tapa (`ifrs9/step.py:83`, `internal/step.py:78`,
`provisioning/step.py:75`).

🔴 **Pero CMF no se quedó atrás por descuido: es lo que su SDD manda, por escrito y cuatro veces.**
`15-provisioning-cmf.md` lo declara en `:56`, `:61`, `:275` («**Dependencias condicionales (no CT-1
duras)**») y `:349`, y lo repite en la secuencia canónica de `execute` (`:425`, paso 3: «Exigir solo
`data.frame` como `requires` duro»). El código está **conforme a su contrato**.

**El defecto real es la divergencia entre contratos**: `16-provisioning-ifrs9.md:59` manda lo
contrario para IFRS 9, y `internal` y el orquestador siguieron a IFRS 9. Cerrar M-3 no es corregir
una implementación: es **decidir cuál de los dos criterios vale**, y enmendar el que pierda.

⚠️ **Y la frase del censo «el DAG sigue sin ordenar los pasos» es imprecisa**: no hay DAG que ordene
nada. `Study._resolve_steps` (`core/study.py:460-476`) devuelve la lista literal y el orden sale de
`_DEFAULT_DOMAIN_ORDER` (`core/study.py:109-136`), una tupla escrita a mano; el scheduler topológico
está diferido a F5 (`core/steps.py:5-8`). Un `requires` dinámico **no ordena**: hace que la
validación lineal **detecte** el desorden. Es una diferencia que importa para no prometer de más.

## 2. Lo que cuesta hoy, medido ejecutando

### 2.1 Verde, y después revienta

Con `provisioning_cmf` en `pd_breaks` y sólo `("data","frame")` disponible:

```
check_pipeline -> True   ('provisioning_cmf',)
Study.run_step -> ArtifactNotFoundError: pd_mapping.method='pd_breaks' exige el artefacto
                  ('model', 'raw_pd_frame') antes de calcular provisioning_cmf.
```

Y con los pasos declarados **en orden inválido** (`["provisioning_cmf", "calibration"]`),
`check_pipeline` sigue diciendo `executable=True`. La hermana con `requires` dinámico, en el mismo
escenario, responde `False` y nombra la causa:

```
El paso 'provisioning_internal' necesita 'calibrated_pd_frame', que produce 'calibration',
y ningún paso anterior lo genera
```

**Eso es lo único que separa a CMF de sus hermanas**: no el orden, sino la capacidad de detectarlo.

### 2.2 Un tercer efecto que el censo no traía: `inert_artifacts` **miente**

`_validate_injected_artifacts` (`core/study.py:610-612`) construye lo requerido desde
`paso.requires`. Medido, inyectando la PD por la puerta pública en una corrida `pd_breaks`:

| paso | `inert_artifacts` |
|---|---|
| `provisioning_cmf` | `(('model','raw_pd_frame'),)` ← **falso** |
| `provisioning_internal` (contraste) | `()` |

Quien trae su PD desde fuera lee hoy, en una superficie pública (`PipelineCheck.inert_artifacts`),
que **su clave no se usa** — y el paso la va a leer. Es un falso aviso, no una omisión.

### 2.3 Lo que ya está cubierto, y por dónde

`check_dataset` **sí** avisa, vía `requisitos_incumplidos_por_contexto` (`cmf/config.py:196-215`),
pero sólo del caso «la sección productora no está activa». No ve el orden, ni una `pd_source_key`
que nadie produce, ni el falso `inert_artifacts`.

## 3. Las decisiones

### D-CMF-1 — el criterio que vale es el de IFRS 9, y SDD-15 se enmienda

`requires` declara **lo que el paso va a leer con la config que se le dio**, no lo que leería en el
peor caso ni en el mejor. Tres de los cuatro pasos de provisiones ya lo hacen así; el cuarto queda
alineado y `15-provisioning-cmf.md` §4/§7/§9 se corrige en sus cinco puntos, en el mismo commit.

**Por qué éste y no el otro:** un `requires` que declara de menos convierte la comprobación previa
en una promesa que el motor no sostiene, y ésa es exactamente la clase de defecto que este repo
lleva tres releases cerrando —«decía compatible sobre un config que muere en su primer paso»—. El
criterio contrario (declarar sólo lo incondicional) sólo protege contra falsos positivos, y §3.2
mide que aquí **no los hay**.

### D-CMF-2 — la clave se toma del config tal cual, sin tabla intermedia

`requires` bajo `pd_breaks` pasa a incluir `(pd_source_domain, pd_source_key)` **leídos del config**,
más `("data","labels")` y `("data","splits")`.

⚠️ **El riesgo que SDD-15 temía es real de nombrar y falso de medir.** `pd_source_key` es `str`
libre —no un `Literal` validado, que es justo el argumento con que `ifrs9/step.py:256-259` justifica
el suyo—, así que `requires` pasa a depender de una cadena que escribe el usuario. Medido, con la
clave por defecto apuntando a un dominio que no la produce:

```
check_pipeline -> False | El paso 'provisioning_cmf' necesita 'raw_pd_frame', que produce
                          'calibration', y ningún paso anterior lo genera
```

**No es falso positivo**: `CalibrationStep.provides` no contiene `raw_pd_frame` (medido), de modo
que ese config ya moría en runtime. Sólo muere antes y con el nombre del artefacto a la vista.

Se descarta la alternativa de derivar la clave de una tabla `dominio → artefacto` como hace
`internal` (`internal/step.py:64-67`): dejaría `pd_source_key` como campo público **inerte**, y ése
es un defecto que este repo ya tiene censado por separado. Aquí se respeta lo que el usuario declaró.

### D-CMF-3 — la validación de `execute` se conserva, y NO queda inalcanzable

Con D-CMF-1 puesto, `_check_prerequisites` corta antes por la ruta normal. Pero `execute` es
**alcanzable directamente** —`study.run_step` no es el único camino, y un test del repo ya lo llama
así (`test_cmf_step.py:228-249`)—, así que su `raise` sigue vivo y con su diagnóstico rico. No hay
código muerto que decidir, a diferencia del precedente de la guarda del transformer.

### D-CMF-4 — se acepta que el mensaje del camino normal pierda la cita a `pd_breaks`

Hoy quien corre por el camino normal lee el mensaje del paso, que **cita `pd_mapping.method`**
(`cmf/step.py:319-322`). Con `requires` dinámico leerá antes el genérico del núcleo, que nombra el
artefacto y quién lo produce pero no por qué se exige.

Se acepta **declarándolo**, no se calla: el mensaje genérico es accionable, enriquecerlo obligaría a
tocar el núcleo para los treinta y tantos pasos, y el motivo sigue publicándose donde el usuario lo
lee primero —el preflight, vía `requisitos_incumplidos_por_contexto`—.

### D-CMF-5 — el cambio de veredicto de `check_pipeline` es el punto, no un efecto lateral

Un config `pd_breaks` con la sección productora ausente o mal ordenada pasa de `executable=True` a
`executable=False`. Es **comportamiento público observable**, y la interfaz lo consume en cada
tecleo: por eso esta enmienda existe en vez de ser un arreglo. No rompe ninguna corrida que hoy
funcione —sólo las que hoy mueren— y ninguna configuración de fábrica lo alcanza: el default de
`pd_mapping.method` es `provided_cmf_category`, que no exige nada extra (medido).

### D-CMF-6 — el gate mide las dos direcciones, y el `provided_cmf_category` es la mitad que importa

Un `requires` dinámico mal escrito exige de más, y eso es el defecto simétrico: rojo sobre un config
que corre. El gate cubre **los dos** métodos:

- `provided_cmf_category` (el default) → `requires == (("data","frame"),)`, exactamente como hoy;
- `pd_breaks` → los cuatro, con la clave que el config declara, y `check_pipeline` en rojo con el
  orden invertido;
- e `inert_artifacts` vacío al inyectar la PD, que es la §2.2.

## 4. Coste medido

| superficie | efecto |
|---|---|
| `config_hash` | **ninguno**, medido: `requires` es atributo del `Step`, no campo de config |
| firmas públicas | ninguna; `requires` ya es parte del `Step` Protocol (`core/steps.py:43`) |
| tests que rompen | **uno**, y sólo si el builder cambiara el caso default: `test_cmf_step.py:177` |
| goldens de DAG u orden | **no existe ninguno** |
| `check_pipeline` | cambia de veredicto (D-CMF-5) |
| `inert_artifacts` | deja de mentir (§2.2) |
| SDD-15 | se enmiendan cinco puntos, en el mismo commit |

⚠️ **Y un hallazgo que sale de medir el coste, ajeno a M-3**: la lista de cobertura regulatoria al
100 % incluye `provisioning/internal/step.py` pero **no** `provisioning/cmf/step.py` (sólo su
`__init__.py`). Las dos son motores de provisión; una está al 100 % obligatorio y la otra no. Se
declara aquí, no se cierra aquí.
