# Planes DCA programados

Un plan DCA es una compra fija que se repite todos los meses: **día del mes
+ monto en USD + lista de tickers con su reparto**. Ejemplos:

- Plan 1: el día 5, USD 100 en MELI, NU y AAPL en partes iguales.
- Plan 2: el día 20, USD 50 en NU, CRML y AXTI.

DCA es disciplina, no análisis: el bot compra lo configurado, sin research,
sin noticias y sin sugerir cambios. Parte de que la plata ya está en la
cuenta de Inversión (Wallbit no tiene API para mover plata entre cuentas).

Reemplaza a la vieja "inversión automática de sueldo", que dependía de
detectar el depósito del sueldo y esperar un traspaso manual. Era compleja
y nunca se llegó a configurar.

## Principio: el código decide, el LLM conversa

Toda la lógica de fechas, montos, mínimo por orden, reparto de la plata
entre planes y "ya se ejecutó este mes" vive en `planes_dca.py` como
funciones puras que reciben `hoy` como parámetro. El LLM solo pregunta los
datos, muestra lo que devuelven las tools y transmite la respuesta.

| Pieza | Dónde |
|---|---|
| Fechas, reparto de cash, confirmación, ticket | `planes_dca.py` (funciones puras) |
| Tools `gestionar_plan_dca` y `ejecutar_plan_dca` | `planes_dca.py` |
| Tablas `planes_dca` y `ejecuciones_dca` | `database.py` |
| Job diario (9am Argentina, 12:00 UTC) | `telegram_bot.chequear_planes_dca_diario` → `planes_dca.correr_chequeo_diario` |
| Módulo de prompt | `agente.PROMPT_MODULES["planes_dca"]` |

## Datos

```
planes_dca(id, numero UNIQUE, nombre, dia, monto_usd, split_json, activo,
           desde_periodo 'YYYY-MM', creado, actualizado)

ejecuciones_dca(id, plan_id, plan_numero, periodo 'YYYY-MM', estado,
                monto_usd, split_json, texto_ticket, fecha_ticket,
                fecha_ejecucion, resultado_json, avisado,
                UNIQUE(plan_id, periodo))
```

- `numero` es el que ve el usuario (1 a 5). Al borrar un plan, su número
  se reusa. `id` es interno y nunca se reusa, así el historial de un plan
  borrado no se mezcla con el nuevo.
- `desde_periodo`: primer mes que toma el plan. Si se crea o reactiva el
  mismo día de su fecha programada o antes, es este mes; si ya pasó, el
  mes siguiente.
- `UNIQUE(plan_id, periodo)`: una sola fila por plan y por mes.
- Estados de una ejecución:
  - `sin_fondos`: ya se avisó la falta de plata ese mes; se sigue reintentando en silencio.
  - `pendiente`: el ticket se mandó y espera SÍ/NO. Reserva esa plata para que no la use otro plan.
  - `ejecutando`: se están mandando las órdenes. Si el bot se cae acá, queda así.
  - `ejecutado` o `descartado`: mes cerrado.
- El ticket guarda una foto del split y el monto. Se compra exactamente lo
  que el usuario vio, no el plan tal como esté al confirmar.

## Fechas

- **Fecha programada** de un mes: el día del plan. Si no existe en ese mes
  (31 en abril, 30 en febrero), se usa el último día del mes. Si cae sábado
  o domingo, el lunes siguiente, aunque sea del mes siguiente (sigue
  contando como la compra del mes original). Los feriados de EE.UU. quedan
  fuera de alcance: si Wallbit rechaza la orden, se informa el error.
- **Mes abierto**: desde la fecha programada hasta lo primero entre el fin
  de ese mes calendario y el día anterior a la fecha programada del mes
  siguiente. Así:
  - si el bot estuvo apagado el día del plan, se pone al día dentro del
    mismo mes y el ticket dice que es una ejecución atrasada;
  - nunca se recupera un mes anterior;
  - nunca hay dos meses abiertos a la vez para un mismo plan.
- Un ticket pendiente vence cuando su mes se cierra: ya no se puede
  ejecutar ni reserva plata.

Ejemplo: plan del día 31, octubre de 2026. El 31/10 es sábado, así que la
compra es el lunes 2/11 y cuenta como la de octubre. Si el bot estuvo
apagado ese día, puede ponerse al día hasta el 29/11. El 30/11 ya es la
compra de noviembre.

## Job diario

`correr_chequeo_diario(hoy)` nunca llama al LLM:

1. Por cada ejecución que quedó en `ejecutando` (el bot se cayó en medio de
   la compra) manda **un solo** aviso: hay que revisar en la app qué
   órdenes salieron. Nunca la reintenta, para no comprar dos veces.
2. Si no hay planes activos, o ninguno toca hoy, termina sin llamar a Wallbit.
3. Lee el efectivo de la cuenta de Inversión (`obtener_cash_inversion`).
   Si no se pudo leer, no hace nada más: reintenta en la próxima corrida
   sin mandar aviso de falta de plata.
4. Al efectivo le resta lo reservado por tickets pendientes y reparte el
   resto en orden de número de plan. A los planes que alcanzan les arma el
   ticket (estado `pendiente`) y se lo manda. A los que no, les manda el
   aviso de cuánto falta, como máximo una vez por mes y por plan. Nunca
   compra parcial.

Cada mensaje se manda por Telegram y además se guarda en el historial como
mensaje del bot. Mientras haya tickets pendientes, `mensaje_libre` le suma
al chat la línea `PLANES_DCA_PENDIENTES: ...`, así el modelo sabe a qué
responde un "SÍ" y se activa el módulo de prompt.

## Confirmación y ejecución

- La única forma de comprar un plan es la tool `ejecutar_plan_dca(numero)`.
  El prompt prohíbe usar `create_trade` directo para un plan.
- El texto real que llegó por Telegram viaja hasta la tool con un
  `ContextVar`: `mensaje_libre` lo setea alrededor de `agente.chat`. Si la
  tool se llama fuera de un mensaje real (un job, `/balance`), rechaza. No
  se lee "el último mensaje de usuario" de la DB porque los jobs guardan
  mensajes sintéticos con rol user.
- **Matching estricto**: se normaliza el texto (minúsculas, sin tildes, sin
  puntuación al principio y al final) y solo valen `si`, `confirmo`,
  `si plan N` o `confirmo plan N`. "si querés cambiá el plan 2", "no sé si"
  o "dale" no compran.
- Con más de un ticket pendiente, un "SÍ" sin número se rechaza y el bot
  pide "SÍ plan N". Cada ticket ya dice qué responder.
- Antes de mandar órdenes, la fila pasa de `pendiente` a `ejecutando` con
  un `UPDATE ... WHERE estado = 'pendiente'`. Si ese cambio no ocurre (un
  SÍ repetido, una segunda llamada), no se compra nada.
- Se manda un `create_trade` MARKET/buy por ticker. Si una orden falla, se
  sigue con las demás y se informa cuál falló, sin reintentarla. Queda
  registrado en la bitácora: fecha, plan, monto y resultado de cada orden.
- "NO" llama a `gestionar_plan_dca(accion='descartar_ticket')`. Ese mes se
  saltea y el plan sigue activo para el siguiente.

## GUARDAR para guardar, SÍ solo para comprar

- `gestionar_plan_dca` con `crear` o `editar` solo guarda si el mensaje
  real del usuario de ese turno es exactamente `guardar`. Usa el mismo
  matching estricto y el mismo mecanismo de mensaje real que la compra. Si
  no, devuelve el resumen sin guardar y le pide al bot que muestre
  "Respondé GUARDAR".
- "SÍ" queda reservado para comprar. Para que un "sí" dicho durante la
  creación no confirme por error un ticket pendiente, `previsualizar` (o un
  crear/editar sin GUARDAR) deja registrado un **borrador en curso**
  (config `DCA_PLAN_EN_EDICION_DESDE`). Mientras el borrador está vigente,
  `ejecutar_plan_dca` rechaza un SÍ sin número, aunque haya un solo ticket,
  y pide "SÍ plan N" o GUARDAR.
- El borrador se limpia al guardar. Si la creación se abandona, vence solo
  a los 30 minutos (`MINUTOS_BORRADOR_VIGENTE`).
- "GUARDAR" nunca compra: no es una confirmación válida para `ejecutar_plan_dca`.

## Editar, pausar y borrar

- **Editar** pide GUARDAR igual que crear y vuelve a validar todo: tickers con `get_asset`, mínimo de
  USD 1 por orden. Si había un ticket pendiente con los datos viejos, se
  descarta y el job arma uno nuevo. Si el plan ya se ejecutó este mes, el
  cambio aplica desde el mes siguiente.
- **Pausar** descarta el ticket pendiente de este mes. **Reactivar** sigue
  la misma regla que crear: si la fecha de este mes ya pasó, arranca el mes
  siguiente, sin ticket atrasado.
- **Borrar** elimina el plan y sus tickets abiertos. Las ejecuciones ya
  hechas quedan como historial.

## Ejemplo de conversación

**Crear un plan**

> **Mateo:** armame un plan de DCA el día 5 con USD 100 en MELI, NU y AAPL en partes iguales
>
> **Bot:** *(llama `gestionar_plan_dca(previsualizar)`)* Plan 1: día 5, USD 100.00, MELI 33.33% / NU 33.33% / AAPL 33.34%. Primera compra: 05/10/2026 (USD 33.33 / 33.33 / 33.34). Respondé GUARDAR para guardar el plan.
>
> **Mateo:** sí
>
> **Bot:** Para guardar el plan respondé GUARDAR ("sí" queda reservado para confirmar compras).
>
> **Mateo:** GUARDAR
>
> **Bot:** *(llama `gestionar_plan_dca(crear)`)* Listo, guardé el plan 1. Guardarlo no compra nada: el 5 te llega el ticket.

**El día del plan, con la plata en la cuenta de Inversión**

> **Bot (job, 9am):**
> Plan 1 — compra programada de 2026-10 — USD 100.00 total:
> - MELI: USD 33.33 (33.33%) — MARKET
> - NU: USD 33.33 (33.33%) — MARKET
> - AAPL: USD 33.34 (33.34%) — MARKET
>
> ¿Confirmás las 3 compras? Respondé SÍ para comprar o NO para saltear este mes.
>
> **Mateo:** SÍ
>
> **Bot:** *(llama `ejecutar_plan_dca(1)`)* Listo: se mandaron las 3 órdenes del plan 1 (MELI, NU y AAPL).

**Plata insuficiente**

> **Bot (job, 9am del 20):** Plan 2: hoy toca la compra de USD 50.00, pero en la cuenta de Inversión hay USD 18.00 libres (descontando lo reservado para otros planes). Para el plan 2 te faltan USD 32.00 en la cuenta de Inversión. Transferí la diferencia desde la app de Wallbit: reviso de nuevo en los próximos días y te armo el ticket cuando alcance. Este aviso no se repite este mes.
>
> *(los días siguientes, si sigue sin alcanzar, el bot no dice nada; cuando la plata llega, manda el ticket del plan 2)*

**Dos tickets pendientes**

> **Mateo:** SÍ
>
> **Bot:** Tenés dos tickets pendientes (plan 1 y plan 2). Respondé "SÍ plan 1" o "SÍ plan 2" para elegir cuál comprar.
