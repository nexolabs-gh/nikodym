# Enmienda SDD — una columna identificador se avisa antes de correr, no después

> **Estado: APROBADA (Cami, 2026-08-01) e IMPLEMENTADA.** El alcance se decidió tras medir que la forma primero
> propuesta —«que el preflight mire la cardinalidad»— **no es posible sin romper D-PRE-1**.
>
> **Base:** `main` = `c7fe68a`. **Autor / Fecha:** DanIA / 2026-08-01.

| Campo | Valor |
|---|---|
| **Problema** | Una columna identificador entra al binning como predictor y mata la corrida con jerga de una librería de terceros, en inglés, sin decir qué columna ni cómo salir |
| **Enmienda a** | `_ENMIENDA-PREFLIGHT-DATASET.md` (D-PRE-1, firma de `check_dataset`) y `_ENMIENDA-INVARIANTES-PREVIAS.md` (D-INV-1, protocolo por sección) |
| **No toca** | El `config_hash`, el motor de binning, el veredicto de `check_pipeline`, ni el comportamiento de quien no aporte el perfil |
| **Release** | Aditivo y observable; exige CHANGELOG. No autoriza bump, tag ni publicación |

## 1. Evidencia medida

Salió de verificar el gate de aceptación de P1 con un dataset propio, no de un censo. Un CSV normal
de cartera con su columna de id (`id_operacion`, 6.000 valores distintos en 6.000 filas) mata la
corrida en el paso `binning`:

```
El paso 'binning' falló: No se pudo ajustar OptBinning: All categories moved to others' bin.
At least one category is needed to perform binning.
```

Tres cosas mal a la vez: el mensaje es **de OptBinning y en inglés**, **no nombra la columna**, y
**no dice la salida** —declararla como llave de unicidad, que el paquete C ya hizo posible—. Y el
preflight dio verde: para él el config y el dataset calzan, porque los nombres existen.

**Lo que se midió antes de diseñar, y que cambió la forma del arreglo:**

1. **`check_dataset` no puede mirar la cardinalidad hoy.** Su contrato es «sin ejecutar nada y sin
   leer los datos» (D-PRE-1) y sólo recibe `columns: Sequence[str]`.
2. **El parquet tampoco la trae.** Medido sobre el upload real: las estadísticas por *row group*
   existen, pero `distinct_count` viene `None` en las ocho columnas — pandas/pyarrow no lo escriben.
   Así que no hay forma de deducirla del esquema.
3. **Quien sí la tiene, y gratis, es la ingesta.** `ingest_upload` ya carga el `DataFrame` entero
   para escribir el parquet: ahí un `nunique()` no cuesta una lectura extra.
4. **El criterio no es «cardinalidad alta», es «cardinalidad alta y no numérica».** Una columna
   numérica continua tiene tantos valores distintos como filas y OptBinning la discretiza sin
   problema —`carga_financiera` corrió bien—. Lo que revienta es una columna **de texto** con casi
   un valor por fila, porque todas sus categorías caen al bin «otros» y no queda ninguna.

## 2. Decisiones

**D-PERF-1 — El perfil de columnas es un DATO que se aporta, no algo que el preflight vaya a
buscar.** `check_dataset` gana un parámetro opcional `column_profile`, exactamente como ganó
`index_columns` en su día y por la misma razón: la información no está en los nombres, y salir a
buscarla rompería el contrato «no lee los datos». D-PRE-1 se conserva íntegro.

**D-PERF-2 — `None` significa «no se sabe», nunca «no hay».** Sin perfil no se emite ni un aviso, y
el comportamiento es idéntico al de hoy. Es el precedente literal de `index_columns`: afirmar sin el
dato reintroduce el falso positivo, que aquí sería acusar de identificador a una columna que nadie
midió.

**D-PERF-3 — La invariante la declara el dominio que la impone**, o sea `binning`, siguiendo D-INV-1.
No hay registro central ni lista transversal de «columnas sospechosas».

**D-PERF-4 — Va por un método PROPIO, no ampliando el de D-INV-1.** El protocolo vigente es
`requisitos_incumplidos(columnas)` y lo implementan cuatro secciones; añadirle un parámetro obligaría
a tocar las cuatro para que sólo una lo use. Se añade
`requisitos_incumplidos_por_perfil(perfil)`, que el recorrido invoca con `getattr` igual que el
primero, y que implementa **sólo** quien lo necesita. Aditivo por construcción: una sección que no lo
declare sigue funcionando.

**D-PERF-5 — El criterio es «texto con casi un valor por fila», y el umbral se declara.** Se avisa
cuando una columna candidata a binning **no es numérica** y su cardinalidad supera el **95 %** de las
filas. El 95 % y no el 100 % porque un identificador real puede traer nulos o algún duplicado y
seguiría siendo un identificador; y sólo no numéricas porque una continua se discretiza bien —es lo
que se midió—.

**D-PERF-6 — Avisa, no bloquea** (D-PRE-5, D-INV-3). El usuario puede correr igual: puede tener una
razón que el motor no conoce.

**D-PERF-7 — El copy dice la columna y la salida, sin jerga.** «La columna X parece un identificador
de fila… decláralas en la llave de unicidad para que el binning la deje fuera». Nunca «OptBinning»,
nunca «cardinalidad», nunca el nombre de una clase.

**D-PERF-8 — El mensaje del motor se arregla igual, porque el aviso previo no lo sustituye.** Quien
usa la librería **por código** no pasa por el preflight, y quien ignora el aviso llega al mismo
error. El fallo del binning pasa a nombrar la columna y a decir la salida, en español.

## 3. Alternativas rechazadas

1. **Que `check_dataset` lea el dataset.** Rompe D-PRE-1, que existe para que comprobar sea barato y
   no materialice nada.
2. **Deducirlo del esquema del parquet.** Medido: `distinct_count` viene `None`; el dato no está.
3. **Ampliar `requisitos_incumplidos` con un parámetro.** Obliga a tocar las cuatro implementaciones
   para que una lo use, y acopla el protocolo simple al que necesita estadísticas.
4. **Excluir automáticamente del wildcard las columnas de alta cardinalidad.** Cambia el
   comportamiento del motor y mueve `config_hash`; además decide por el usuario. El paquete C ya dio
   la vía explícita (`unique_keys`), y esto sólo tiene que señalarla.
5. **Arreglar sólo el mensaje del motor.** Deja el fallo donde está: después de pagar la corrida.

## 4. Gates de aceptación

- Con perfil, un dataset con columna identificador emite el aviso **antes** de correr, nombrando la
  columna y la salida; sin perfil no emite nada y el resultado es idéntico al de hoy (los dos
  sentidos).
- Una columna **numérica** de cardinalidad máxima **no** dispara el aviso; una de texto con pocos
  valores tampoco. Control negativo de los dos falsos positivos plausibles.
- Declarar la columna en la llave de unicidad **apaga** el aviso.
- El error del binning, si se llega a él, nombra la columna y la salida en español.
- `check_dataset` sin `column_profile` conserva su comportamiento byte a byte.
- El aviso no bloquea el botón Ejecutar.
- Verificado **en vivo**, con el mismo CSV que destapó el defecto.
