# Inversión automática de sueldo (DCA con split fijo)

Diseño final, confirmado. Cubre qué hace el bot solo, qué te pide a vos, y
dónde vive cada pieza en el código.

## Decisión de diseño clave

El bot **nunca ejecuta una compra sin tu confirmación explícita** ("SÍ").
Esto aplica siempre — incluido el chequeo automático diario. No es una
limitación técnica: es una decisión tuya, y así quedó también en el prompt
(`PROMPT_MODULES["inversion_sueldo_dca"]` en `agente.py`).

La **transferencia de fondos** (cuenta corriente → cuenta de Inversión)
tampoco la puede hacer el bot solo: ni el MCP de Wallbit ni su API pública
exponen un endpoint de transferencia interna (solo `read` y `trade`). Ese
paso siempre lo hacés vos, manualmente, desde el celular.

## Ejemplo de conversación (guion esperado)

El bot no tiene un formulario fijo — Claude arma cada pregunta en base a las
instrucciones de `PROMPT_MODULES["inversion_sueldo_dca"]`, así que la
redacción exacta puede variar un poco. Esto es el flujo esperado según esas
instrucciones (no es una corrida real: este entorno de trabajo no tiene
salida de red ni a Wallbit ni a la API de Anthropic, así que no pude
ejecutarlo en vivo acá — probalo vos en tu Mac y si algo se desvía de esto lo
ajustamos):

> **Vos:** quiero armar el DCA de mi sueldo
>
> **Bot:** Dale. Para armarlo necesito algunos datos:
> 1) ¿Cuál es el monto aproximado de tu sueldo?
>
> **Vos:** unos 1500 dólares
>
> **Bot:** Bien, $1500 aprox. ¿Más o menos qué día del mes solés recibirlo? (podés no saberlo con precisión, es solo una señal extra)
>
> **Vos:** el día 1
>
> **Bot:** Última: cuando revisás tus transacciones en Wallbit, ¿aparece algún dato que identifique quién te lo transfiere (nombre de tu empleador, alguna referencia), o siempre ves algo genérico como el nombre de la plataforma?
>
> **Vos:** siempre dice "Wallbit LLC", nada más
>
> **Bot:** Entendido, no hay dato de emisor útil — voy a usar solo el monto y el día. ¿Qué tickers querés incluir en el DCA?
>
> **Vos:** NVDA, MSFT y PLTR
>
> **Bot:** ¿Reparto equitativo entre los tres (33/33/34%) o preferís definir un % distinto para cada uno?
>
> **Vos:** equitativo
>
> **Bot:** Listo, quedó configurado: sueldo ≈$1500 (día 1), NVDA/MSFT/PLTR en partes iguales. Todos los días reviso tus movimientos y te aviso si detecto el ingreso.

Después, el día que detecta un depósito que matchea (a pedido o en el chequeo
automático de las 9am):

> **Bot:** [💰 SUELDO DETECTADO] Vi que ingresaron $1490. Pasalo vos a la cuenta de Inversión desde el celu y avisame cuando esté.
>
> **Vos:** ya lo pasé
>
> **Bot:**
> ```
> Ticket de inversión de sueldo — $1490.00 total:
> - NVDA: $496.62 (33.33%) — MARKET
> - MSFT: $496.62 (33.33%) — MARKET
> - PLTR: $496.76 (33.34%) — MARKET
> ¿Confirmás las 3 compras? (SÍ/NO)
> ```
>
> **Vos:** SÍ
>
> **Bot:** Ejecutadas las 3 compras. Quedó registrado en la bitácora.

## Paso a paso

1. **Alta — wizard de configuración, una sola vez** (o cuando pidas rehacerla).
   Cuando le decís al bot algo como *"quiero armar el DCA de mi sueldo"*, te
   pregunta en orden (nada queda asumido — el bot lo puede usar cualquier
   persona, no solo vos, así que todo se pregunta cada vez):
   - **¿Cuál es el monto aproximado de tu sueldo?** — dato principal y
     obligatorio para identificarlo.
   - **¿Más o menos qué día del mes solés recibirlo?** — opcional, señal
     extra para no confundirlo con otro depósito grande cualquier día.
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

   Todo esto queda guardado con `save_config`: `DCA_SUELDO_MONTO_APROX`,
   `DCA_SUELDO_DIA_APROX` (si lo diste), `DCA_SUELDO_EMISOR` (solo si
   confirmaste que ves un dato útil) y `DCA_SUELDO_SPLIT`.

2. **Detección diaria.** Todos los días a las 9am (Argentina) el bot revisa
   tus transacciones (`list_transactions`). La condición base y obligatoria
   es que el monto caiga dentro de un ±15% del `DCA_SUELDO_MONTO_APROX`
   guardado (tolerancia para que un aumento u horas extra no lo dejen
   afuera). A partir de ahí suma confianza con las señales que haya
   disponibles: si el depósito cae cerca del `DCA_SUELDO_DIA_APROX`
   guardado, o si aparece el `DCA_SUELDO_EMISOR` guardado en la
   descripción — en tu caso, esa segunda señal no aplica porque no
   guardaste ninguna (Origen siempre es "Wallbit LLC"). Si no configuraste
   ningún monto, cae al criterio más flojo de respaldo: un depósito
   notablemente más grande que tus ingresos recientes normales. Si no está
   seguro, te pregunta antes de asumir nada. Si no encuentra nada nuevo, no
   te manda ningún mensaje ese día.

3. **Te avisa y te pide el traspaso manual.**
   *"[💰 SUELDO DETECTADO] Vi que ingresaron $X. Pasalo vos a la cuenta de
   Inversión desde el celu y avisame cuando esté."* El bot espera tu
   confirmación de que ya transferiste antes de seguir.

4. **Calcula el split — con código, no a mano.** Una vez que confirmás el
   traspaso, el bot llama a la tool `calcular_split_sueldo(monto_total)`.
   Esa tool (en `salary_dca.py`) hace el reparto exacto en dólares para cada
   ticker según tu split guardado, con el redondeo ya resuelto (para que la
   suma dé siempre exactamente tu monto transferido, nunca unos centavos de
   más o de menos). El modelo nunca hace esta cuenta de memoria.

5. **Te muestra el ticket.**
   ```
   Ticket de inversión de sueldo — $500.00 total:
   - NVDA: $250.00 (50%) — MARKET
   - MSFT: $125.00 (25%) — MARKET
   - PLTR: $125.00 (25%) — MARKET
   ¿Confirmás las 3 compras? (SÍ/NO)
   ```

6. **Ejecuta solo si decís SÍ.** Ahí, y solo ahí, llama a `create_trade` una
   vez por cada ticker del split. Si decís NO, no se ejecuta nada.

7. **Queda registrado.** Fecha, monto total y el split ejecutado se guardan
   en la bitácora del bot (`registrar_bitacora`).

## Dónde vive cada pieza

| Pieza | Archivo |
|---|---|
| Cálculo de montos (split → dólares por ticker, redondeo exacto) | `salary_dca.py` |
| Reparto equitativo (% iguales entre N tickers, redondeo exacto) | `salary_dca.py` → `split_equitativo` |
| Tool `calcular_split_sueldo` (acepta `split` personalizado o `tickers` para equitativo) | `salary_dca.py` |
| Protocolo completo — wizard de alta, detección, ticket, ejecución | `agente.py` → `PROMPT_MODULES["inversion_sueldo_dca"]` |
| Job diario (detección + ventana de fechas) | `telegram_bot.py` → `chequear_sueldo_diario` |
| Config guardada | tabla `configuracion` vía `save_config`/`obtener_config` — claves `DCA_SUELDO_MONTO_APROX`, `DCA_SUELDO_DIA_APROX` (opcional), `DCA_SUELDO_EMISOR` (opcional, solo si el usuario confirma que le sirve), `DCA_SUELDO_SPLIT`, `DCA_SUELDO_ULTIMA_FECHA` |

## Cómo se probó (sin tocar dinero real)

Todo esto se validó con `pytest`, sin conectarse a Wallbit ni a tu cuenta
real, ni ejecutar ninguna orden real:

- **Matemática del split** (`tests/test_salary_dca.py`): porcentajes que no
  suman 100 se rechazan, redondeos como 100/3 siguen sumando exactamente
  el monto total, montos inválidos (cero o negativos) se rechazan. Lo mismo
  para el reparto equitativo (`split_equitativo`) con cantidades de tickers
  que no dividen 100 parejo (ej. 7 tickers).
- **La tool en sí** (`tests/test_salary_dca.py`): con split personalizado
  explícito, con `tickers` para reparto equitativo, con split guardado en una
  base de datos temporal, prioridad correcta entre los tres, y el error claro
  cuando no hay ninguno de los tres.
- **El módulo de prompt** (`tests/test_agente.py`): se activa con las
  palabras clave correctas y también con el contexto del chequeo automático;
  un test de regresión confirma que el texto del módulo siempre reafirma la
  regla de confirmación explícita.
- **El job diario** (`tests/test_telegram_bot.py`): con un "bot" y un
  `agente.chat` simulados — si no hay novedades no se manda mensaje, si las
  hay se manda tal cual, y la ventana de fechas se actualiza en ambos casos.

`python3 -m pytest tests/ -v` — 84 tests, todos verdes (36 nuevos de esta
feature, incluyendo el tope de 10 tickers).

## Lo que falta para que ande en producción

El código y los tests están listos. Para que el bot empiece a chequear de
verdad tu cuenta hace falta el próximo `git pull` + reinicio del bot en tu
Mac (el patrón de siempre: yo escribo y pruebo el código, vos lo corrés en
tu entorno real). Antes de que se dispare por primera vez, corré el wizard de
alta con el bot (monto aproximado del sueldo, qué tickers, qué reparto) — si
no hay nada configurado todavía, el primer chequeo automático no va a tener
nada que ofrecerte.

Nota sobre `list_transactions`: en este sandbox no tengo salida de red hacia
`mcp.wallbit.io` (el proxy la bloquea), así que no pude probarlo en vivo para
ver qué otros campos trae además de lo que se ve en la app. El diseño quedó
basado en lo que confirmaste del comprobante real (Origen = "Wallbit LLC",
genérico) — si en algún momento ves un campo de concepto/descripción más
específico al tocar una transacción, avisame y lo sumo como señal extra.
