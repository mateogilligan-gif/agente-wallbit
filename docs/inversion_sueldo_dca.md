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
> **Bot:** Entendido, no hay dato de emisor útil — voy a usar solo el monto y el día. ¿Qué porcentaje de tu sueldo querés invertir en este DCA, o preferís un monto fijo en dólares cada vez? (por defecto NO se invierte el sueldo completo)
>
> **Vos:** el 10% de mi sueldo
>
> **Bot:** Bien, 10% cada vez. ¿Qué tickers querés incluir en el DCA?
>
> **Vos:** NVDA, MSFT y PLTR
>
> **Bot:** ¿Reparto equitativo entre los tres (33/33/34%) o preferís definir un % distinto para cada uno?
>
> **Vos:** equitativo
>
> **Bot:** Listo, quedó configurado: sueldo ≈$1500 (día 1), invertís el 10% de cada sueldo, en NVDA/MSFT/PLTR partes iguales. Todos los días reviso tus movimientos y te aviso si detecto el ingreso.

Después, el día que detecta un depósito que matchea (a pedido o en el chequeo
automático de las 9am):

> **Bot:** [💰 SUELDO DETECTADO] Vi que ingresaron $1490 (tu sueldo). Según lo configurado, vas a invertir $149 de eso (10%). Pasá esos $149 a la cuenta de Inversión desde el celu y avisame cuando esté.
>
> **Vos:** ya lo pasé
>
> **Bot:**
> ```
> Ticket de inversión de sueldo — $149.00 total:
> - NVDA: $49.66 (33.33%) — MARKET
> - MSFT: $49.66 (33.33%) — MARKET
> - PLTR: $49.68 (33.34%) — MARKET
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
   - **¿Qué % de tu sueldo querés invertir, o preferís un monto fijo en
     dólares?** — clave: por default NO se invierte el sueldo completo,
     solo la porción que elijas acá (ej. "10% de mi sueldo" o "siempre
     $200"), salvo que elijas explícitamente 100%.
   - **¿Qué tickers?** (máximo 10 — más que eso, el ticket de confirmación
     deja de ser algo legible antes de decir SÍ, y el monto por ticker queda
     muy chico. Tope aplicado en código, no solo sugerido.)
   - **¿Reparto equitativo o personalizado?** Si es personalizado, pedís el
     % de cada ticker (tienen que sumar 100); si es equitativo, el bot
     reparte en partes iguales entre los tickers que diste (con
     `split_equitativo`, código puro — nunca a mano).

   Todo esto queda guardado con `save_config`: `DCA_SUELDO_MONTO_APROX`,
   `DCA_SUELDO_DIA_APROX` (si lo diste), `DCA_SUELDO_EMISOR` (solo si
   confirmaste que ves un dato útil), `DCA_SUELDO_MODO_MONTO` ("porcentaje"
   o "fijo"), `DCA_SUELDO_MONTO_VALOR` (el número), y `DCA_SUELDO_SPLIT`.

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

3. **Calcula cuánto de eso invertir — con código, no a mano.** Detectado el
   sueldo por $X, el bot llama a `calcular_monto_a_invertir_sueldo(monto_sueldo=X)`
   antes de pedirte nada. Esa tool aplica tu % o monto fijo configurado y
   devuelve "monto_a_invertir" — la porción real a transferir, no el sueldo
   completo.

4. **Te avisa y te pide el traspaso manual — solo de esa porción.**
   *"[💰 SUELDO DETECTADO] Vi que ingresaron $X (tu sueldo). Según lo
   configurado, vas a invertir $Y de eso. Pasá esos $Y a la cuenta de
   Inversión desde el celu y avisame cuando esté."* El bot espera tu
   confirmación de que ya transferiste antes de seguir.

5. **Calcula el split — con código, no a mano.** Una vez que confirmás el
   traspaso, el bot llama a la tool `calcular_split_sueldo(monto_total)`,
   pasándole el "monto_a_invertir" del paso 3 (no el sueldo completo). Esa
   tool (en `salary_dca.py`) hace el reparto exacto en dólares para cada
   ticker según tu split guardado, con el redondeo ya resuelto (para que la
   suma dé siempre exactamente el monto transferido, nunca unos centavos de
   más o de menos). El modelo nunca hace esta cuenta de memoria.

6. **Te muestra el ticket.**
   ```
   Ticket de inversión de sueldo — $150.00 total:
   - NVDA: $75.00 (50%) — MARKET
   - MSFT: $37.50 (25%) — MARKET
   - PLTR: $37.50 (25%) — MARKET
   ¿Confirmás las 3 compras? (SÍ/NO)
   ```

7. **Ejecuta solo si decís SÍ.** Ahí, y solo ahí, llama a `create_trade` una
   vez por cada ticker del split. Si decís NO, no se ejecuta nada.

8. **Queda registrado.** Fecha, monto total y el split ejecutado se guardan
   en la bitácora del bot (`registrar_bitacora`).

## Dónde vive cada pieza

| Pieza | Archivo |
|---|---|
| Cálculo de cuánto invertir del sueldo (% o monto fijo, nunca el depósito completo) | `salary_dca.py` → `calcular_monto_a_invertir` |
| Cálculo de montos (split → dólares por ticker, redondeo exacto) | `salary_dca.py` |
| Reparto equitativo (% iguales entre N tickers, redondeo exacto) | `salary_dca.py` → `split_equitativo` |
| Tool `calcular_monto_a_invertir_sueldo` (% o monto fijo del sueldo detectado) | `salary_dca.py` |
| Tool `calcular_split_sueldo` (acepta `split` personalizado o `tickers` para equitativo) | `salary_dca.py` |
| Protocolo completo — wizard de alta, detección, ticket, ejecución | `agente.py` → `PROMPT_MODULES["inversion_sueldo_dca"]` |
| Job diario (detección + ventana de fechas) | `telegram_bot.py` → `chequear_sueldo_diario` |
| Config guardada | tabla `configuracion` vía `save_config`/`obtener_config` — claves `DCA_SUELDO_MONTO_APROX`, `DCA_SUELDO_DIA_APROX` (opcional), `DCA_SUELDO_EMISOR` (opcional, solo si el usuario confirma que le sirve), `DCA_SUELDO_MODO_MONTO` ("porcentaje"/"fijo"), `DCA_SUELDO_MONTO_VALOR`, `DCA_SUELDO_SPLIT`, `DCA_SUELDO_ULTIMA_FECHA` |

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
- **Las tools en sí** (`tests/test_salary_dca.py`): con valores explícitos,
  con la preferencia guardada en una base de datos temporal, y el error claro
  cuando no hay ninguno de los dos.
- **El módulo de prompt** (`tests/test_agente.py`): se activa con las
  palabras clave correctas y también con el contexto del chequeo automático;
  tests de regresión confirman que el texto siempre reafirma la regla de
  confirmación explícita y que nunca se invierte el sueldo completo por
  default.
- **El job diario** (`tests/test_telegram_bot.py`): con un "bot" y un
  `agente.chat` simulados — si no hay novedades no se manda mensaje, si las
  hay se manda tal cual, y la ventana de fechas se actualiza en ambos casos.

`python3 -m pytest tests/ -v` — 105 tests, todos verdes (48 de esta feature,
incluyendo el tope de 10 tickers y el cálculo de cuánto invertir; los 9
restantes son de la auditoría de código del 2026-09-16, ver `CHANGELOG.md`).

## Estado

El código, el bot y el MCP de Wallbit (`list_transactions`/`create_trade`,
antes rotos del lado del servidor) ya están andando. Falta solo correr el
wizard de alta por chat (monto aproximado del sueldo, qué % o monto fijo
invertir, qué tickers, qué reparto) — sin eso configurado, el chequeo
automático no tiene nada que ofrecer todavía. Una vez armado, lo ideal es
probarlo con un mensaje directo tipo *"revisá si me llegó el sueldo"* contra
una transacción real, en vez de esperar al chequeo automático de las 9am,
para confirmar que la detección y el cálculo de cuánto invertir se comportan
como se espera antes de depender de que corra solo.

Nota sobre `list_transactions`: en este sandbox no tengo salida de red hacia
`mcp.wallbit.io` (el proxy la bloquea), así que no pude probarlo en vivo para
ver qué otros campos trae además de lo que se ve en la app. El diseño quedó
basado en lo que confirmaste del comprobante real (Origen = "Wallbit LLC",
genérico) — si en algún momento ves un campo de concepto/descripción más
específico al tocar una transacción, avisame y lo sumo como señal extra.
