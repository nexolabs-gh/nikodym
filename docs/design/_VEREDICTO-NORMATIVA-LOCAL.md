# Veredicto — qué queda del roadmap tras sacar la normativa local del alcance

> **Estado: APROBADO por Cami (2026-08-05).** No introduce ni retira ninguna capacidad: decide el
> estado de los nodos de roadmap que la decisión del 2026-08-05 dejó sin sustento, para que nadie
> vuelva a planificar sobre uno muerto.
>
> Precedente de forma: [`_ENMIENDA-REQUISITOS-CMF.md`](_ENMIENDA-REQUISITOS-CMF.md), D-MAX-3 y
> D-SEG-11 — **una decisión sin objeto se conserva escrita, nunca se borra**, porque su diagnóstico
> costó medirlo y sigue siendo cierto el día que la condición vuelva.

---

## 1. La decisión que lo origina

Cami, 2026-08-05: *«Descartamos normativa local de países hace tiempo atrás: CMF, norma peruana,
boliviana, etc. No podemos estar detrás de cada actualización de cada país […] Sólo podemos seguir
estándares comunes como Basilea o IFRS 9 […] Lo que sí hay que dejar es todo bien para, por ejemplo,
un modelo PD y LGD, y luego el modelador —o la misma Nikodym Advisory— hace los ajustes para
llevarlo a la normativa local.»*

Su mitad de **posicionamiento** ya se implementó el 2026-08-04: portada sin país en seis
superficies, CMF como caso de referencia en [`norma-local.md`](../../docs_site/norma-local.md), cero
código borrado. Lo que faltaba era su mitad de **plan**, que es este documento.

---

## 2. 🔴 P3 y la decisión no decían lo mismo, y hubo que elegir

`privado/ROADMAP-CONSOLIDADO-2026-07-31.md` §P3 no proponía renunciar a la normativa local:
proponía **hacerla como dato** — *«un banco peruano usa sus tablas SBS sin que Nikodym publique una
versión»*. La decisión del 2026-08-05 es más dura: sale del alcance, y el aterrizaje lo hace el
modelador o Nikodym Advisory.

**Gana la decisión del 2026-08-05** (Cami, en esta sesión). Pero antes de cerrar P3 se midió su
premisa, porque si la capacidad ya existiera, cerrarlo estaría tirando valor.

### D-JUR-1 — La capacidad neutra existe, y la promesa de P3 es PARCIAL. Medido.

**Lo que confirma la hipótesis:** el cálculo de `provisioning/internal` **no conoce ninguna tabla de
supervisor**. Cero matrices, cero tramos de mora, cero categorías de rating, cero porcentajes
normativos; agrupa por nombres arbitrarios y multiplica lo que le dan
(`provisioning/internal/engine.py:82-101` son todas sus constantes). Un banco de cualquier país
puede correr `PE = PI · PDI · Exposición` hoy, y el catálogo ya expone dos trabajos sin CMF
(`ui/jobs.py:219`, `:263`, ambos con `jurisdiction_code: None`).

**Lo que la refuta**, y no es el cálculo sino todo lo que lo rodea:

| Regla de una norma local | Estado | Evidencia |
|---|---|---|
| Staging / clasificación de deudores | Imposible dentro del motor; sólo precalculable fuera | no hay campo de clasificación; `grouping="provided"` lee un grupo ya formado |
| Tramos de mora | Imposible | cero ocurrencias de `dpd`/mora en `internal/*.py` |
| Garantías, haircuts, aforos | Imposible | lee **una** columna de exposición; `CmfGuaranteeConfig` no tiene equivalente neutro |
| Mínimos regulatorios | Parcial, sólo LGD | hay `lgd_floor`/`lgd_cap`; no hay piso de PD ni de provisión |
| Regla del máximo | 🔴 Cerrada a Chile | `ProvisioningSource` es un `Literal` de tres valores y prohíbe `source_a == source_b`: «máximo(estándar local, interno propio)» **no se puede declarar** fuera de Chile |
| Provisiones adicionales / contracíclicas | Imposible | no hay término aditivo |
| Castigos | Imposible | cero ocurrencias |

⚠️ **Y lo precalculado desaparece del `config_hash` y del audit trail**, que es precisamente lo que
un validador viene a leer. Más dos fugas de presentación: el informe imprime la cifra en **formato
de peso chileno** (`report/prose.py:2204`), y **no existe ninguna demostración sin CMF** — ni
preset, ni dataset, ni test de integración.

**Conclusión.** Hoy el usuario no declara *tablas* (no hay dónde), declara *columnas ya calculadas*;
y no obtiene una *provisión regulatoria*, obtiene **la última multiplicación** de una. La frase
publicable —y sólo ésta— es:

> El motor de provisión interna no conoce ninguna tabla de supervisor: tú declaras tus grupos, tu PD
> y tu severidad, y él calcula `PE = PI · PDI · Exposición` con aritmética exacta y trazabilidad
> completa. Lo que no hace es interpretar tu norma por ti: la clasificación, la mora, las garantías
> y los mínimos los aterriza el modelador encima.

---

## 3. Veredicto nodo por nodo

### D-JUR-2 — B3.a-2 («el contenido normativo del motor CMF»): **SIN OBJETO**

Su condición de arranque, escrita en el propio nodo, era *«cuando exista un segundo motor que exija
el molde común — es decir, con B3.b»*. Con la normativa local fuera de alcance **B3.b no va a
ocurrir**, así que la condición no se cumple nunca.

🔴 **No es un rechazo del diagnóstico.** Los 15 puntos de chilenidad censados siguen ahí y siguen
siendo correctos; que sean chilenos **sigue siendo correcto también**, porque viven en el motor CMF,
que es un caso de referencia declarado. **Condición de reactivación:** que exista un segundo motor
de jurisdicción. No la busques en `src/`: no es un olvido.

### D-JUR-3 — B3.b («implementar una jurisdicción nueva»): **CERRADO POR ALCANCE**

Antes decía «no se inicia de forma especulativa; requiere compromiso comercial firmado». Ahora es
más simple: **no se inicia**. Un compromiso comercial por una jurisdicción nueva no la mete en la
librería — la atiende Nikodym Advisory como trabajo de integración, que es el modelo de negocio
vigente (la librería es 100 % gratuita; lo pagado es el aterrizaje).

⚠️ **La regla de honestidad que colgaba de B3.b NO se retira: se refuerza.** *«Mientras no exista su
motor, la librería no tiene motor SBS»* pasa de ser una restricción temporal a una permanente, y es
lo que impide que el material comercial insinúe cobertura regional.

### D-JUR-4 — El selector de jurisdicción en preset y UI: **SIN OBJETO**

Su razón de diferimiento era *«un desplegable con una sola opción no es una elección»*. Esa razón
era temporal y ahora es **permanente**.

### D-JUR-5 — B5 («validación humana de las matrices CMF»): **SIGUE DEBIÉNDOSE, y el detonante cambia**

Decisión explícita de Cami en esta sesión. El motor CMF no se borra, sus matrices están **en
producción**, y desde el 2026-08-04 hay además una página pública que las presenta como caso de
referencia trabajado.

🔴 **Publicar un caso de referencia sin validación humana es exactamente la sobrepromesa que se
acaba de quitar del titular.** Lo que cambia es el detonante: ya no es «el primer compromiso
concreto en Chile» —que con la normativa local fuera de alcance podría no llegar nunca— sino **que
la página ya está publicada**. La deuda es exigible ahora.

### D-JUR-6 — B7 («mapa regulatorio LATAM»): **SIN OBJETO como nodo de la librería**

Investigar las circulares de cada supervisor es literalmente el trabajo que la decisión declara
insostenible. Si hace falta para una conversación comercial es **material de Eduardo**, no plan de
producto, y como tal vive en `privado/`, no en el ROADMAP.

### D-JUR-7 — F3 («Provisiones CMF»): **no cambia de estado, cambia de encuadre**

Sigue implementado y experimental. Deja de rotularse «norma local» como si fuera una familia con más
miembros por venir: es **el** caso de referencia, en singular y congelado. Su DoD incumplido es
D-JUR-5.

---

## 4. 🔴 Lo que el veredicto ABRE, que no es un nodo muerto

### D-JUR-8 — La capacidad neutra existe y no se comunica: eso sí acerca una venta

D-JUR-1 midió que hay un motor de provisiones que funciona sin una línea de norma local, y que **no
tiene ni una demostración**: ni preset, ni dataset, ni guía. Hoy la respuesta a *«¿y para Perú?»* en
una reunión depende de que quien conteste conozca `provisioning_internal` de memoria.

Nodo propuesto, con su alcance ya medido y **acotado a lo que la frase publicable sostiene**:

1. Cambiar el default `portfolio_col="cmf_portfolio"` a uno neutro. ⚠️ **Mueve el `config_hash`** de
   todo config que lo omita ⇒ minor con nota SemVer, precedente `1.4.0`/`1.8.0`. Decisión de release.
2. La moneda del informe, hoy CLP *hardcoded*. Ya declarada como contrato transversal de
   presentación en el censo del 2026-07-31.
3. Un dataset + preset + guía que lo demuestren corriendo, sin CMF.

⚠️ **No entra en este nodo** abrir la regla del máximo a dos internos: eso es diseño de contrato y
exige su propio SDD.

---

## 5. Lo que este veredicto NO toca

- **El motor CMF y sus 39 archivos de test.** Cero código borrado, igual que el 2026-08-04.
- **IFRS 9, Basilea y el pipeline F1**: son estándar común, o sea el alcance que se conserva.
- **P4 (LGD modelada)**: no está contaminado por la decisión. Sigue vivo y sigue siendo el siguiente
  valor real. ⚠️ Con una premisa corregida al medirla en esta sesión: `provided`/`group_historical`
  **no es «de dónde viene la LGD»** sino **cómo se agrega**, así que no es «añadir un valor al
  `Literal`» — exige enmienda antes de programar.
