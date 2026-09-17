# Inversión automática de sueldo (DCA con split fijo)

Diseño final, confirmado (rediseñado el 2026-09-16 a partir de un problema real
que encontró Mateo: el traspaso a la cuenta de Inversión siempre iba a ser
manual, así que el bot tiene que trabajar alrededor de eso, no fingir que no
existe). Cubre qué hace el bot solo, qué te pide a vos, y dónde vive cada
pieza en el código.

## Decisión de diseño clave

El bot **nunca ejecuta una compra sin tu confirmación explícita** ("SÍ").
Esto aplica siempre — incluido cualquier chequeo automático. No es una
limitación técnica: es una decisión tuya, y así quedó también en el prompt
(`PROMPT_MODULES["inversion_sueldo_dca"]` en `agente.py`).

La **transferencia de fondos** (cuenta corriente → cuenta de Inversión)
tampoco la puede hacer el bot: el MCP de Wallbit solo tiene 5 herramientas
(`get_checking_balance`, `get_stocks_balance`, `list_transactions`,
`get_asset`, `create_trade`) — ninguna mueve plata entre cuentas. Ese paso
siempre lo hacés vos, manualmente, desde el celular (según la documentación
oficial de Wallbit, ese traspaso manual sí es posible e inmediato dentro de
la app).

Lo que sí puede hacer el bot es **notar solo cuándo ya hiciste ese
traspaso**, sin que se lo tengas que avisar por chat: compara el efectivo
disponible en tu cuenta de Inversión contra una foto de ese mismo valor
tomada justo antes de avisarte cuánto transferir. Ver
`wallbit_client.obtener_cash_inversion` y `salary_dca.traspaso_detectado`.

## Por qué cambió el diseño

La primera versión le preguntaba a la persona, en el alta, "¿qué % de tu
sueldo querés invertir?" y, apenas detectaba el sueldo, esperaba que
confirmara por chat "ya transferí" antes de seguir. Mateo señaló el problema:
si el traspaso es manual sí o sí, pedirle a la persona que además escriba
"ya transferí" es un paso de más — el bot puede simplemente fijarse solo.
Y separado de eso, el % a invertir puede cambiar mes a mes, así que tiene más
sentido preguntarlo (o reconfirmarlo) cada vez que se detecta un sueldo, no
una sola vez en el alta.

También surgió un problema de costo: si el bot revisa `list_transactions`
los 365 días del año buscando el sueldo, es trabajo de más la mayoría de los
días. La solución: pedirle a la persona un **rango de días** del mes en que
suele cobrar (no un solo día fijo, porque no siempre cae exacto) y solo
llamar a Wallbit dentro de esa ventana.

## Ejemplo de conversación (guion esperado)

El bot no tiene un formulario fijo — Claude arma cada pregunta en base a las
instrucciones de `PROMPT_MODULES["inversion_sueldo_dca"]`, así que la
redacción exacta puede variar un poco. Esto es el flujo esperado según esas
instrucciones (no es una corrida real: este entorno de trabajo no tiene
salida de red ni a Wallbit ni a la API de Anthropic, así que no pude
ejecutarlo en vivo acá — probalo vos en tu Mac y si algo se desvía de esto lo
ajustamos):

**Alta (una sola vez):**

> **Vos:** quiero armar el DCA de mi sueldo
>
> **Bot:** Dale. Para armarlo necesito algunos datos:
> 1) ¿Cuál es el monto aproximado de tu sueldo?
>
> **Vos:** unos 1500 dólares
>
> **Bot:** Bien, $1500 aprox. ¿Entre qué días del mes solés recibirlo? Dame un rango, no hace falta que sea un día exacto (ej. "del 28 al 3").
>
> **Vos:** del 28 al 3
>
> **Bot:** Última: cuando revisás tus transacciones en Wallbit, ¿aparece algún dato que identifique quién te lo transfiere (nombre de tu empleador, alguna referencia), o siempre ves algo genérico como el nombre de la plataforma?
>
> **Vos:** siempre dice "Wallbit LLC", nada más
>
> **Bot:** Entendido, no hay dato de emisor útil — voy a usar solo el monto y el rango de días. ¿Qué tickers querés incluir en el DCA?
>
> **Vos:** NVDA, MSFT y PLTR
>
> **Bot:** ¿Reparto equitativo entre los tres (33/33/34%) o preferís definir un % distinto para cada uno?
>
> **Vos:** equitativo
>
> **Bot:** Listo, quedó configurado: sueldo ≈$1500 (entre el 28 y el 3), en NVDA/MSFT/PLTR partes iguales. Cuando lo detecte te voy a preguntar cuánto de ese sueldo querés invertir.

Nota: acá NO se preguntó todavía el % a invertir — eso pasa recién cuando se
detecta el sueldo (ver abajo).

**Cuando detecta el sueldo** (a pedido, o en el chequeo automático diario —
que solo corre dentro del rango de días configurado):

> **Bot:** [💰 SUELDO DETECTADO] Vi que ingresaron $1500. ¿Qué % de tu sueldo (o monto fijo en USD) querés invertir en este DCA?
>
> **Vos:** el 10%
>
> **Bot:** Bien, vas a invertir $150 de este sueldo. Transferí esos $150 a la cuenta de Inversión cuando quieras — yo me doy cuenta solo cuando llegue.

El bot guarda ese 10% (`DCA_SUELDO_MODO_MONTO`/`DCA_SUELDO_MONTO_VALOR`) y lo
va a reusar el próximo mes — pero te lo va a volver a preguntar, dándote la
opción de mantenerlo o cambiarlo:

> **Bot** (el mes siguiente): [💰 SUELDO DETECTADO] Vi que ingresaron $1620. Tenés configurado invertir el 10% ($162 de este sueldo). ¿Mantenemos o lo cambiamos este mes?
>
> **Vos:** mantené

**Cuando el chequeo automático nota que la plata ya está en la cuenta de
Inversión** (sin que vos hayas tenido que avisar por chat):

> **Bot:**
> ```
> Ticket de inversión de sueldo — $150.00 total:
> - NVDA: $49.66 (33.33%) — MARKET
> - MSFT: $49.66 (33.33%) — MARKET
> - PLTR: $49.68 (33.34%) — MARKET
> ¿Confirmás las 3 compras? (SÍ/NO)
> ```
>
> **Vos:** SÍ
>
> **Bot:** Ejecutadas las 3 compras. Quedó registrado en la bitácora.

Si en cualquier momento le avisás vos mismo "ya transferí $150" antes de que
el chequeo automático lo note, el bot arma el ticket ahí mismo, sin esperar.

## Paso a paso

1. **Alta — wizard de configuración, una sola vez** (o cuando pidas rehacerla).
   Cuando le decís al bot algo como *"quiero armar el DCA de mi sueldo"*, te
   pregunta en orden (nada queda asumido — el bot lo puede usar cualquier
   persona, no solo vos, así que todo se pregunta cada vez):
   - **¿Cuál es el monto aproximado de tu sueldo?** — dato principal y
     obligatorio para identificarlo.
   - **¿Entre qué días del mes solés recibirlo?** — prácticamente
     obligatorio: pedí un *rango* (ej. "del 28 al 3"), no un día exacto. Esto
     es lo que le permite al chequeo automático NO revisar tus transacciones
     los 365 días del año — solo dentro de esa ventana. Si de verdad no
     tenés idea, se puede dejar "todo el mes" (equivale a revisar siempre,
     como antes de tener esta optimización).
   - **¿Ves algún dato que identifique quién te lo transfiere, o siempre es
     algo genérico?** — en tu caso puntual, el comprobante de Wallbit
     siempre muestra "Origen: Wallbit LLC" (el rail, no tu empleador), así
     que esa señal no te sirve a vos. Pero eso no es necesariamente cierto
     para cualquier cuenta, así que el bot se lo pregunta a cada usuario en
     vez de asumirlo — si alguien sí ve un dato útil, lo guarda como señal
     de refuerzo extra.
   - **¿Qué tickers?** (máximo 10 — más que eso, el ticket de confirmación
     deja de ser algo legible antes de decir SÍ, y el monto por ticker queda
     muy chico. Tope aplicado en código, no solo sugerido.)
   - **¿Reparto equitativo o personalizado?** Si es personalizado, pedís el
     % de cada ticker (tienen que sumar 100); si es equitativo, el bot
     reparte en partes iguales entre los tickers que diste (con
     `split_equitativo`, código puro — nunca a mano).

   Notá que acá **no** se pregunta todavía qué % del sueldo invertir — eso
   se pregunta (o reconfirma) cada vez que se detecta un sueldo nuevo, ver
   el paso 3.

   Todo esto queda guardado con `save_config`, salvo el rango de días que
   usa su propia tool (`guardar_rango_dias_sueldo`, valida que sean días de
   mes reales antes de guardar): `DCA_SUELDO_MONTO_APROX`,
   `DCA_SUELDO_DIA_DESDE`/`DCA_SUELDO_DIA_HASTA`, `DCA_SUELDO_EMISOR` (solo
   si confirmaste que ves un dato útil), y `DCA_SUELDO_SPLIT`.

2. **Detección de sueldo — solo dentro de la ventana de días.** El chequeo
   automático diario primero mira si HOY cae dentro del rango configurado
   (`salary_dca.hoy_esta_en_ventana_sueldo`); si no, no llama a Wallbit para
   nada ese día. Dentro de la ventana, revisa `list_transactions`: un
   depósito se considera "sueldo" si el monto cae dentro de un ±15% del
   `DCA_SUELDO_MONTO_APROX` guardado (tolerancia para que un aumento u horas
   extra no lo dejen afuera), sumando confianza si además aparece el
   `DCA_SUELDO_EMISOR` guardado en la descripción. Si no hay monto
   configurado, cae al criterio más flojo de respaldo: un depósito
   notablemente más grande que los ingresos recientes normales. Si no está
   seguro, pregunta antes de asumir nada. Si no encuentra nada nuevo, no
   manda ningún mensaje ese día.

3. **Pregunta cuánto invertir — cada vez, no una sola vez.** Si ya hay un %
   o monto fijo configurado de una vez anterior, el bot lo muestra y
   pregunta si se mantiene o se cambia ese mes. Si es la primera vez,
   pregunta directamente. En cualquier caso, llama a
   `calcular_monto_a_invertir_sueldo(monto_sueldo=X, modo=..., valor=...)`
   antes de avisar nada — nunca calcula esto a mano.

4. **Avisa el monto exacto a transferir y arranca la espera.** *"[💰 SUELDO
   DETECTADO] Vi que ingresaron $X. Según lo configurado, vas a invertir $Y
   de eso. Transferí esos $Y a la cuenta de Inversión cuando quieras — yo me
   doy cuenta solo cuando llegue."* Inmediatamente después, el bot llama a
   `iniciar_espera_traspaso_sueldo(monto_esperado=Y)`, que guarda ese monto
   y una foto del efectivo actual de tu cuenta de Inversión — la base para
   poder notar el traspaso después, sin que se lo tengas que confirmar por
   chat.

5. **Chequeo automático del traspaso — acotado a 10 días.** Cada corrida
   diaria (independiente de la ventana de días del sueldo) se fija si hay un
   traspaso pendiente: compara el efectivo actual de tu cuenta de Inversión
   contra la foto guardada. Si el aumento se parece al monto esperado
   (con un margen del 10%, porque el traspaso es manual y puede no ser
   exacto), arma el ticket usando el **monto real** que llegó, no el
   teórico. Si pasan más de 10 días sin novedad, deja de chequearlo solo
   (`salary_dca.espera_vencida`) — vos podés avisar manualmente en cualquier
   momento igual, sin esperar a que se cumplan los 10 días ni después de
   que se cumplan.

6. **Calcula el split — con código, no a mano.** Llama a
   `calcular_split_sueldo(monto_total=...)` con el monto real detectado
   (o el que le dijiste manualmente). Esa tool (en `salary_dca.py`) hace el
   reparto exacto en dólares para cada ticker según tu split guardado, con
   el redondeo ya resuelto (para que la suma dé siempre exactamente el
   monto transferido, nunca unos centavos de más o de menos).

7. **Te muestra el ticket** y **ejecuta solo si decís SÍ.** Ahí, y solo ahí,
   llama a `create_trade` una vez por cada ticker del split. Si decís NO, no
   se ejecuta nada.

8. **Queda registrado.** Fecha, monto total y el split ejecutado se guardan
   en la bitácora del bot (`registrar_bitacora`).

## Dónde vive cada pieza

| Pieza | Archivo |
|---|---|
| Cálculo de cuánto invertir del sueldo (% o monto fijo, nunca el depósito completo) | `salary_dca.py` → `calcular_monto_a_invertir` |
| Cálculo de montos (split → dólares por ticker, redondeo exacto) | `salary_dca.py` → `calcular_montos` |
| Reparto equitativo (% iguales entre N tickers, redondeo exacto) | `salary_dca.py` → `split_equitativo` |
| Rango de días del mes (ventana de detección, cruza fin de mes) | `salary_dca.py` → `dia_en_rango`, `hoy_esta_en_ventana_sueldo`, `validar_rango_dias` |
| Detección del traspaso a la cuenta de Inversión (sin API de transferencias) | `wallbit_client.py` → `obtener_cash_inversion`; `salary_dca.py` → `traspaso_detectado`, `espera_vencida` |
| Tool `calcular_monto_a_invertir_sueldo` (% o monto fijo del sueldo detectado) | `salary_dca.py` |
| Tool `calcular_split_sueldo` (acepta `split` personalizado o `tickers` para equitativo) | `salary_dca.py` |
| Tool `guardar_rango_dias_sueldo` (valida y guarda el rango de días) | `salary_dca.py` |
| Tool `iniciar_espera_traspaso_sueldo` (guarda monto esperado + foto de cash) | `salary_dca.py` |
| Protocolo completo — wizard de alta, detección, pregunta de %, ticket, ejecución | `agente.py` → `PROMPT_MODULES["inversion_sueldo_dca"]` |
| Job diario (ventana de días + chequeo de traspaso pendiente) | `telegram_bot.py` → `chequear_sueldo_diario`, `_chequear_traspaso_pendiente` |
| Config guardada | tabla `configuracion` vía `save_config`/`obtener_config` — claves `DCA_SUELDO_MONTO_APROX`, `DCA_SUELDO_DIA_DESDE`/`DCA_SUELDO_DIA_HASTA`, `DCA_SUELDO_EMISOR` (opcional), `DCA_SUELDO_MODO_MONTO`/`DCA_SUELDO_MONTO_VALOR` (se reconfirman en cada detección), `DCA_SUELDO_SPLIT`, `DCA_SUELDO_ULTIMA_FECHA`, `DCA_SUELDO_MONTO_ESPERADO`/`DCA_SUELDO_CASH_BASELINE`/`DCA_SUELDO_ESPERA_DESDE` (estado del traspaso pendiente) |

## Cómo se probó (sin tocar dinero real)

Todo esto se validó con `pytest`, sin conectarse a Wallbit ni a tu cuenta
real, ni ejecutar ninguna orden real:

- **Cuánto invertir del sueldo** (`tests/test_salary_dca.py`): modo
  porcentaje y modo fijo calculan bien, un 10% nunca da el sueldo completo,
  100% sí invierte todo, se rechaza un % fuera de rango o un monto fijo
  mayor al sueldo detectado.
- **Matemática del split** (`tests/test_salary_dca.py`): porcentajes que no
  suman 100 se rechazan, redondeos como 100/3 siguen sumando exactamente
  el monto total, montos inválidos (cero o negativos) se rechazan. Lo mismo
  para el reparto equitativo (`split_equitativo`) con cantidades de tickers
  que no dividen 100 parejo (ej. 7 tickers).
- **Rango de días** (`tests/test_salary_dca.py`): rangos simples y rangos
  que cruzan fin de mes (ej. "28 al 3") se evalúan bien sin importar si el
  mes tiene 28, 30 o 31 días; sin rango configurado, siempre chequea (mismo
  comportamiento que antes de esta optimización).
- **Detección del traspaso** (`tests/test_salary_dca.py`,
  `tests/test_wallbit_client.py`): el efectivo de la cuenta de Inversión se
  extrae bien de distintos formatos de respuesta; el match tolera que se
  transfiera un poco menos de lo pedido (10% de margen) pero no un monto muy
  por debajo; la espera se corta sola después de 10 días.
- **Las tools en sí** (`tests/test_salary_dca.py`): con valores explícitos,
  con la preferencia guardada en una base de datos temporal, y el error claro
  cuando no hay ninguno de los dos.
- **El módulo de prompt** (`tests/test_agente.py`): se activa con las
  palabras clave correctas y con los dos contextos automáticos (sueldo
  detectado, traspaso detectado); tests de regresión confirman que el texto
  siempre reafirma la regla de confirmación explícita, que el % se pregunta
  en cada detección (no una sola vez en el alta), y que el split siempre usa
  el monto real transferido.
- **El job diario** (`tests/test_telegram_bot.py`): la ventana de días
  filtra bien cuándo se llama al agente; el chequeo de traspaso no toca
  Wallbit si no hay nada pendiente, detecta la llegada de fondos con el
  monto real, y se rinde solo pasado el plazo de espera.

`python3 -m pytest tests/ -v` — ver el conteo actualizado en `CHANGELOG.md`
(la entrada más reciente).

## Estado

El código y el bot ya están andando, y el MCP de Wallbit
(`list_transactions`/`create_trade`) está confirmado funcionando. Falta
correr el wizard de alta por chat con el diseño nuevo (monto aproximado,
rango de días, tickers, reparto) — sin eso configurado, el chequeo
automático no tiene nada que ofrecer todavía. Una vez armado, lo ideal es
probar con un mensaje directo tipo *"revisá si me llegó el sueldo"* contra
una transacción real, en vez de esperar al chequeo automático, para
confirmar que la detección, la pregunta de %, el aviso del monto a
transferir y la detección del traspaso se comportan como se espera antes de
depender de que corra todo solo.

Nota sobre `list_transactions` y `get_stocks_balance`: en este sandbox no
tengo salida de red hacia `mcp.wallbit.io` (el proxy la bloquea), así que no
pude probarlo en vivo para confirmar el nombre exacto del campo de efectivo
de la cuenta de Inversión en la respuesta real de Wallbit.
`obtener_cash_inversion` prueba varios nombres posibles (`cash`,
`available_cash`, `cash_balance`, `available`) tanto en el nivel raíz como
anidado bajo `data`, pero si en la práctica no detecta nada, puede ser que
Wallbit use un nombre de campo distinto — avisame qué devuelve
`get_stocks_balance` en tu cuenta real y lo ajustamos.
