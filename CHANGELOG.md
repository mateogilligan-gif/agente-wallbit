# Changelog

Registro de las actualizaciones del bot, en orden cronológico (la más reciente arriba).

## 2026-10-02 — Lectura real del efectivo de la cuenta de Inversión

### Corregido

- **`wallbit_client.obtener_cash_inversion` nunca encontraba el efectivo**:
  buscaba un campo `cash` que Wallbit no manda. La respuesta real de
  `get_stocks_balance` es `{"data": [{"symbol", "shares"}, ...]}` y el
  efectivo de Inversión es la fila `{"symbol": "USD", "shares": <monto>}`
  (verificado con una consulta de solo lectura). Por eso el job de planes
  DCA nunca armaba tickets: siempre entendía "no se pudo leer" y
  reintentaba en silencio. Ahora lee la fila USD. Si la lista es válida y
  no trae fila USD, el efectivo es 0 (se avisa la falta de plata). `None`
  queda solo para errores o formatos inesperados.
- Los tests usaban mocks con la forma `{"cash": ...}`, que nunca existió en
  Wallbit. Ahora usan la forma real (anonimizada).

### Nota

- El MCP de Wallbit expone 14 tools, entre ellas `internal_operation`, que
  **sí** transfiere fondos entre checking (DEFAULT) e inversión
  (INVESTMENT). El bot no la usa ni la expone: la documentación que dice
  que "Wallbit no tiene API para mover plata entre cuentas" quedó
  desactualizada.
- El plan 1 de octubre de 2026 se marcó `descartado` en la base porque
  Mateo hizo esa compra a mano. El plan sigue activo; la próxima compra es
  el 2026-11-02.

## 2026-10-02 — El log ya no guarda el token de Telegram ni la apikey de FMP

### Corregido (seguridad)

- **`bot.log` guardaba el token del bot de Telegram en texto plano**:
  `httpx` (lo usan python-telegram-bot y el SDK de Anthropic) loguea en
  INFO cada request con la URL completa, y la URL de Telegram lleva el
  token adentro (unas 400.000 líneas). Ahora el logger `httpx` queda en
  WARNING. Se revisaron los demás loggers que escribían en `bot.log`
  (apscheduler, telegram.ext, anthropic, yfinance): ninguno escribe claves.
  Wallbit y Brave mandan su key en headers, y requests/urllib3 solo loguean
  URLs en DEBUG.
- **FMP**: el mensaje de un error de red de `requests` incluye la URL con
  `?apikey=...`, y ese texto llegaba al LLM y a la bitácora de la DB. Ahora
  se tapa (`apikey=***`) antes de devolverlo. No hubo filtración real:
  `FMP_API_KEY` todavía no está configurada.
- Se vació `bot.log` para sacar las líneas viejas con el token.

## 2026-10-02 — list_transactions alineado con el schema real de Wallbit

### Corregido

- **`wallbit_client.list_transactions`**: Wallbit solo acepta `limit` 10, 20
  o 50. Si el modelo pedía otro número (ej. 30), la consulta se rechazaba.
  Ahora `limit` se redondea **hacia arriba** al valor permitido más cercano,
  con tope 50 (5 → 10, 30 → 50). Nunca devuelve menos de lo pedido; para
  más de 50 está `page`. El default sigue siendo 50.

### Agregado

- La tool `list_transactions` expone `page` y `from_date`/`to_date`
  (AAAA-MM-DD), validados localmente antes de llamar: fechas reales,
  `from_date` no posterior a `to_date` y `page` entero mayor o igual a 1.
  Un input inválido devuelve `ok: false` con un mensaje claro, sin tocar
  Wallbit. Los filtros de moneda, estado, tipo y monto no se exponen por ahora.
- Verificado con una consulta real de solo lectura (`limit`, `page` y fechas).

## 2026-10-02 — create_trade con el schema real de Wallbit y GUARDAR para guardar planes

### Corregido

- **`wallbit_client.create_trade`** mandaba `ticker`, `side` ("buy"/"sell")
  y `order_type` en minúsculas, pero el MCP de Wallbit espera `symbol`,
  `direction` ("BUY"/"SELL") y `order_type` en mayúsculas ("MARKET"/"LIMIT").
  Cualquier orden real iba a ser rechazada por validación. Ahora usa el
  schema real (revisado leyendo la definición de la tool, sin ejecutar
  ninguna orden): monto en `amount` (USD), `currency: "USD"` y, para LIMIT,
  `limit_price` + `time_in_force` (DAY por default, o GTC; Wallbit lo exige
  en LIMIT). STOP y STOP_LIMIT, que Wallbit acepta, se siguen rechazando
  localmente porque el bot no los usa. La validación local se mantiene,
  adaptada a los valores nuevos. La tool expuesta al LLM usa los nombres nuevos.

### Agregado

- **GUARDAR para guardar o editar un plan DCA**: `gestionar_plan_dca`
  (crear/editar) solo guarda si el mensaje real del usuario es exactamente
  "guardar". "SÍ" queda reservado para comprar.
- Mientras hay un plan en creación o edición sin guardar (borrador vigente
  30 minutos), un "SÍ" a secas no ejecuta ningún ticket pendiente: se pide
  "SÍ plan N" o GUARDAR. Cierra por código el cruce de un "sí" dicho para
  guardar un plan que terminaba comprando otro.

## 2026-10-02 — Planes DCA programados reemplazan la inversión automática de sueldo

La inversión automática de sueldo dependía de detectar el depósito del
sueldo en las transacciones y de esperar a que Mateo pasara la plata a mano
a la cuenta de Inversión (Wallbit no tiene API para mover plata entre
cuentas). Era compleja y nunca se llegó a configurar. Los planes DCA parten
de que la plata ya está en la cuenta de Inversión: el día X de cada mes, el
bot arma el ticket del monto fijo configurado y espera el SÍ. Son más
simples, más predecibles y es lo que se quería en realidad. DCA es
disciplina, no análisis: sin research ni noticias.

### Agregado

- **`planes_dca.py`**: hasta 5 planes (día del mes, monto fijo en USD,
  hasta 10 tickers con reparto equitativo o por %). Toda la lógica son
  funciones puras: fecha programada (último día del mes si el día no
  existe, lunes si cae fin de semana), mes abierto (ponerse al día dentro
  del mismo mes, nunca recuperar meses anteriores), reparto de la plata en
  orden de número de plan descontando tickets pendientes, y mínimo de USD 1
  por orden validado al configurar.
- Tools **`gestionar_plan_dca`** (previsualizar/crear/listar/editar/pausar/
  reactivar/borrar/descartar_ticket, con verificación de tickers vía
  `get_asset`) y **`ejecutar_plan_dca`**, la única forma de comprar un plan.
- **Confirmación por código**: el texto real que llega por Telegram viaja
  hasta la tool (`ContextVar`). Matching estricto: solo "SÍ"/"CONFIRMO" o
  "SÍ plan N" con varios tickets pendientes. Un cambio de estado atómico
  impide comprar dos veces el mismo plan en el mismo mes.
- Una ejecución cortada a la mitad nunca se reintenta: se avisa una vez
  para revisar en la app qué órdenes salieron.
- Tablas `planes_dca` y `ejecuciones_dca`; job diario
  `chequear_planes_dca_diario` (9am Argentina) que no llama al LLM y no
  llama a Wallbit si ningún plan toca hoy. Módulo de prompt `planes_dca`
  (sin research, confirmación sin excepciones). Docs: `docs/planes_dca.md`.

### Eliminado

- `salary_dca.py`, sus 4 tools (`calcular_split_sueldo`,
  `calcular_monto_a_invertir_sueldo`, `guardar_rango_dias_sueldo`,
  `iniciar_espera_traspaso_sueldo`), el job `chequear_sueldo_diario`, el
  módulo de prompt `inversion_sueldo_dca`, sus tests y
  `docs/inversion_sueldo_dca.md`. No hubo datos que migrar. Total de tools:
  de 41 a 39.

### Corregido

- `wallbit_client.get_asset` mandaba el parámetro `ticker`, pero el MCP de
  Wallbit espera `symbol`: fallaba siempre con un error de validación.
  Verificado contra la API real (solo lectura).

## 2026-10-01 — Fuente de datos de empresa opcional y paga: Financial Modeling Prep (FMP)

Las noticias por ticker vía `brave_search` son búsqueda web genérica, con
ruido, y el bot no tenía forma de encontrar empresas por sector + market cap
(`screener_filtrar`/`thesis_screener` solo validan una lista de tickers que
Mateo ya trae). FMP (plan Starter, ~USD 19-22/mes) resuelve las dos cosas
con datos estructurados, pero es pago — así que convive como un **modo**
alternativo al gratis (Brave), elegido por Mateo desde el chat, nunca
activado solo. Mateo todavía no tiene la API key — todo quedó probado con
mocks, la prueba real queda pendiente para cuando se suscriba.

### Agregado

- **`fmp_client.py`**: cliente de FMP (HTTP + parsers + cache de 30 min,
  mismo patrón que `brave_client.py`) y 3 tools nuevas:
  - `noticias_empresa(ticker, limite)`: noticias por ticker — usa FMP en
    modo `fmp_pago`, Brave (`brave_client.search_ticker_news`, sin
    reescribir) en modo `gratis`. Misma forma normalizada en los dos casos:
    `{titulo, url, fuente, fecha}` + `fuente_datos` ("fmp"/"brave").
  - `screener_empresas(sector, industria, market_cap_min, market_cap_max, pais, limite)`:
    screener real por sector/industria/market cap, solo en modo `fmp_pago`
    (en modo gratis sugiere `brave_search` + `thesis_screener` o pasarse a
    pago). Pide al menos un filtro — no se puede pedir "todo el mercado".
  - `configurar_modo_datos_empresa(modo)`: guarda `MODO_DATOS_EMPRESA`
    ("gratis" o "fmp_pago") en config, validando antes de guardar.
- **Modo no configurado**: si nadie eligió modo todavía, `noticias_empresa`
  usa gratis por default y agrega `"modo_no_configurado": true` + un campo
  `"aviso"` con la instrucción explícita de preguntar — así el bot sabe que
  tiene que preguntar aunque el mensaje del usuario no mencione el tema
  (ej. "analizá NVDA" no dispara ningún módulo de prompt por keyword). La
  misma regla también quedó en `PROMPT_CORE` (no depende solo del módulo).
- **Fallbacks sin excepciones**: sin `FMP_API_KEY`, con una key sin acceso
  al plan (error de plan/auth de FMP), o con timeout/error de red — en
  noticias cae a Brave avisando el motivo; en el screener devuelve
  `ok: false` con un mensaje claro. Nunca una excepción sin manejar.
- **`PROMPT_MODULES["datos_empresa_fmp"]`**: explica la diferencia de costo
  entre modos (noticias confirmadas en Starter, el screener podría necesitar
  un plan superior — no confirmado), cómo cambiar de modo por chat, y que
  no hay que volver a preguntar una vez configurado.
- Paso 2 de "ANÁLISIS DE EMPRESA" en `PROMPT_CORE` ahora usa
  `noticias_empresa` para las noticias del ticker (antes `brave_search`
  directo); `brave_search` sigue para búsquedas abiertas que no son de un
  ticker puntual. El módulo `screener_tesis` ahora prueba `screener_empresas`
  primero cuando el modo es `fmp_pago` y la tesis define sector/market cap.
- `config.env.example`: `FMP_API_KEY` opcional, con nota del costo.
- `README.md`: sección nueva "Datos de empresa: modo gratis vs FMP pago"
  (incluye paso a paso para probar el modo pago cuando llegue la key real).

### Nota sobre el endpoint de noticias

Endpoint de noticias por ticker: `/stable/news/stock` con el parámetro
`symbols`, confirmado en la página oficial de la doc "Search Stock News
API" (su ejemplo es `https://financialmodelingprep.com/stable/news/stock?symbols=AAPL`).
"search-stock-news" es el nombre de la página de la doc, no la ruta de la
API. Sin una key válida no se puede verificar en vivo (FMP devuelve 401
"Invalid API KEY" para CUALQUIER ruta, exista o no), así que la prueba real
queda pendiente de la suscripción. Las constantes `FMP_NEWS_PATH` y
`FMP_NEWS_TICKER_PARAM` están arriba de todo en `fmp_client.py`.

### Archivos

| Archivo | Cambio |
|---|---|
| `fmp_client.py` | Nuevo — cliente FMP, 3 tools, lógica pura testeable sin red |
| `agente.py` | Import de `fmp_client`, regla nueva en `PROMPT_CORE`, módulo `datos_empresa_fmp`, ajustes en "ANÁLISIS DE EMPRESA" y `screener_tesis` |
| `config.env.example` | `FMP_API_KEY` opcional |
| `README.md` | Sección "Datos de empresa", tabla de fuentes, conteo de tools (39 → 41), árbol de arquitectura |
| `tests/test_fmp_client.py` | Nuevo — 55 tests: lógica pura, las dos tools en ambos modos, los 9 casos borde del spec |
| `tests/test_agente.py` | Tests de regresión del módulo `datos_empresa_fmp` |

**204 tests en total, todos pasando** (`python3 -m pytest tests/ -q`).

## 2026-09-25 — Análisis de empresa con más rigor: framing de "jefe de equipo de analistas"

Se le sumó a la sección de análisis de empresa (`PROMPT_CORE` en `agente.py`) la misma disciplina que ya usábamos en la skill de research de Mateo (`analista-financiero-broker`): pensar el análisis como si el bot fuera el jefe de un equipo de analistas de un bróker, cada sección del informe encargada a un analista distinto.

### Agregado

- **Verificación de ticker obligatoria** antes de investigar: confirmar con `get_asset`/`yf_info` que el ticker corresponde a la empresa correcta (evita confundir tickers parecidos de empresas distintas), chequear que siga cotizando, y aclarar si es pública o privada.
- **Regla explícita de "nunca desde memoria"**: los datos de precio, market cap, noticias y estado de la empresa siempre se buscan en el momento, nunca se contestan de memoria.
- **Sección de riesgos clave** (ejecución, deuda, caja/runway, dilución, riesgo regulatorio) — antes solo había un resumen numérico liviano.
- **Competencia marcada por tipo** (pública, privada, o subsidiaria de otra empresa) en vez de solo nombrar competidores.
- **Cierre con fuentes**, marcando explícitamente cuando un dato viene de una fuente no oficial (foro, transcripción de un inversor particular) antes de tratarlo como confirmado.

### Archivos

| Archivo | Cambio |
|---|---|
| `agente.py` | Sección "ANÁLISIS DE EMPRESA" de `PROMPT_CORE` reescrita con el framing nuevo |
| `README.md` | Nota en "Análisis de acciones" sobre el nuevo rigor |
| `tests/test_agente.py` | Tests nuevos: verificación de ticker, regla de "nunca desde memoria", riesgos y fuentes presentes en el prompt |

**143 tests en total, todos pasando** (`python3 -m pytest tests/ -q`).

## 2026-09-16 — Rediseño de la inversión de sueldo: detección automática del traspaso + rango de días

Mateo encontró un problema real de diseño en la feature de DCA de sueldo:
como Wallbit no tiene API para mover plata entre la cuenta corriente y la de
Inversión, ese traspaso siempre iba a ser manual — pedirle además que
confirme por chat "ya transferí" era un paso de más que el bot puede evitar
detectando la llegada de esa plata solo. De esa conversación salió un
rediseño de la feature (no un ajuste chico):

### Agregado

- **Detección automática del traspaso** (`wallbit_client.obtener_cash_inversion`,
  `salary_dca.traspaso_detectado`/`espera_vencida`): el bot guarda una foto
  del efectivo de la cuenta de Inversión al avisar cuánto transferir
  (`salary_dca.iniciar_espera_traspaso_sueldo`), y el chequeo diario compara
  contra esa foto para notar solo cuándo llegó la plata — con 10% de margen
  de tolerancia (el traspaso es manual, puede no ser exacto al centavo) y un
  tope de 10 días de espera antes de dejar de chequearlo solo. El split
  siempre se calcula con el monto REAL que llegó, no con el teórico.
- **Rango de días en vez de un día fijo** (`salary_dca.dia_en_rango`,
  `hoy_esta_en_ventana_sueldo`, `validar_rango_dias`, tool
  `guardar_rango_dias_sueldo`): el wizard ahora pide un rango (ej. "del 28
  al 3", soporta cruzar fin de mes) en vez de un solo día aproximado. El
  chequeo diario de sueldo nuevo solo llama a `list_transactions` si HOY
  cae dentro de esa ventana — el resto del mes no toca la API de Wallbit
  para nada. Sin rango configurado, sigue chequeando todos los días (mismo
  comportamiento que antes).
- **El % o monto fijo a invertir se pregunta en cada detección, no en el
  alta**: si ya hay uno guardado de una vez anterior, el bot lo muestra y
  pregunta si se mantiene o se cambia ese mes; si es la primera vez, lo
  pregunta directamente. Esto permite ajustarlo mes a mes sin tener que
  "reconfigurar" nada.

### Corregido

- El flujo anterior le pedía a la persona confirmar el traspaso por chat
  ("ya transferí") antes de calcular el split — quedó reemplazado por la
  detección automática de arriba (se puede seguir avisando manualmente en
  cualquier momento, como atajo).

### Archivos

| Archivo | Cambio |
|---|---|
| `salary_dca.py` | Nuevo: `dia_en_rango`, `validar_rango_dias`, `hoy_esta_en_ventana_sueldo`, `traspaso_detectado`, `espera_vencida`; tools `guardar_rango_dias_sueldo` e `iniciar_espera_traspaso_sueldo` |
| `wallbit_client.py` | Nuevo: `obtener_cash_inversion` (extrae el efectivo de la cuenta de Inversión de la respuesta de `get_stocks_balance`) |
| `telegram_bot.py` | `chequear_sueldo_diario` reescrito: chequeo de traspaso pendiente (`_chequear_traspaso_pendiente`) + ventana de días para el chequeo de sueldo nuevo |
| `agente.py` | Módulo de prompt `inversion_sueldo_dca` reescrito: wizard sin la pregunta de %, pregunta de % en cada detección, protocolo de aviso + espera automática, nuevo contexto `CHEQUEO_TRASPASO_SUELDO` |
| `docs/inversion_sueldo_dca.md`, `README.md` | Diseño y ejemplo de conversación actualizados al flujo nuevo |
| `tests/test_salary_dca.py`, `tests/test_wallbit_client.py`, `tests/test_telegram_bot.py`, `tests/test_agente.py` | Tests nuevos para cada pieza; se agregó un fixture en `test_telegram_bot.py` para evitar que el estado de esta feature se filtre entre archivos de test (comparten una misma DB de test) |

**140 tests en total, todos pasando** (`python3 -m pytest tests/ -q`).

## 2026-09-16 — Auditoría de código y arreglos menores

Revisión completa del repo (con un segundo agente para una mirada independiente) antes de que Mateo empiece a mostrar/recomendar el bot a otras personas. Se encontraron y corrigieron los siguientes puntos — ninguno crítico de plata, pero sí de robustez y prolijidad:

### Corregido

- **Manejador de errores global en Telegram** (`telegram_bot.py`, `manejador_errores`): si algo falla procesando un mensaje o un job automático, antes el usuario se quedaba sin ninguna respuesta ("⏳ Procesando..." y nada más). Ahora se loguea el error completo en `bot.log` y, si vino de un mensaje de chat, se le avisa al usuario en vez de dejarlo esperando en silencio.
- **HTML sin escapar en los reportes de research** (`research_campaigns.py`, `renderizar_html`): los títulos/URLs/fuentes de noticias externas (Brave, Google News, Reddit, StockTwits) se insertaban tal cual en el HTML local que genera el bot. Ahora se escapan con `html.escape()` antes de insertarlos — evita que un título con caracteres de HTML/JS quede interpretado en la página que Mateo abre en su navegador. De paso, se renombró una variable local `html` que tapaba el nombre del módulo recién importado.
- **`create_trade` sin validación local** (`wallbit_client.py`): antes de tocar el servidor real de Wallbit, ahora se valida localmente que el ticker no esté vacío, que `side` sea `buy`/`sell`, que el monto sea un número positivo, que `order_type` sea `market`/`limit`, y que las órdenes LIMIT traigan un precio válido — así un dato mal formado se corta acá con un mensaje claro, en vez de depender de que Wallbit lo rechace del otro lado.
- **Descripción desactualizada de `save_config`** (`database.py`): mencionaba claves de un esquema de config anterior (`MONTO_SUELDO`, `PORCENTAJE_DCA`) que ya no existen desde el refactor de la feature de sueldo.
- **Tipos inconsistentes en `yf_get_earnings_calendar`** (`market_data.py`): la rama que procesa el calendario de earnings como `dict` (una de dos formas posibles según la versión de yfinance) no casteaba los valores a `float` como sí hacía la rama `DataFrame` — podían quedar como `numpy.float64`. Ahora ambas ramas castean igual.

### Hallazgo señalado, no resuelto todavía

- El único control real que impide que el bot ejecute una compra sin confirmación explícita es una instrucción de texto en el prompt (`PROMPT_CORE`/`PROMPT_MODULES`), no un chequeo de código. `create_trade` está disponible para el modelo en todos los mensajes (la lista `TOOLS` en `agente.py` es global, no se filtra por tema), junto con herramientas que traen texto de internet sin filtrar. Queda pendiente decidir e implementar un control de confirmación real a nivel de código antes de considerar esto completamente cerrado.

### Archivos

| Archivo | Cambio |
|---|---|
| `telegram_bot.py` | Nuevo `manejador_errores`, registrado con `add_error_handler` |
| `research_campaigns.py` | Escapado de HTML en `renderizar_html`, variable renombrada |
| `wallbit_client.py` | Validación local en `create_trade` |
| `database.py` | Descripción de `save_config` actualizada |
| `market_data.py` | Casteo a `float` consistente en `yf_get_earnings_calendar` |
| `tests/test_wallbit_client.py`, `tests/test_research_campaigns.py`, `tests/test_market_data.py` | Tests nuevos para cada arreglo |

**105 tests en total, todos pasando** (`python3 -m pytest tests/ -q`).

## 2026-09-15 — Inversión automática de sueldo (DCA con split fijo)

### Agregado

- **Wizard de configuración por chat.** Al pedirle al bot algo como *"quiero armar el DCA de mi sueldo"*, pregunta en orden: monto aproximado del sueldo (dato principal), día del mes en que suele llegar (opcional, señal extra), si hay algún dato que identifique a quien lo transfiere o es siempre algo genérico (se pregunta siempre, no se asume — varía según la cuenta de cada usuario), **qué % de ese sueldo invertir en el DCA o un monto fijo en dólares** (por default NO se invierte el depósito completo, solo la porción elegida — salvo que se elija explícitamente 100%), qué tickers incluir (máximo 10), y si el reparto es equitativo o personalizado por porcentaje.
- **Chequeo diario automático** (`chequear_sueldo_diario`, 9am Argentina): revisa las transacciones buscando un depósito que matchee el monto configurado. Si no encuentra nada, no manda ningún mensaje ese día.
- **Cálculo de cuánto invertir por código** — nueva tool `calcular_monto_a_invertir_sueldo` (en `salary_dca.py`) que aplica el % o monto fijo configurado sobre el sueldo detectado, antes de pedir el traspaso manual. El monto a transferir/invertir nunca es el sueldo completo salvo elección explícita.
- **Cálculo de montos por código, no por el modelo de IA** — tool `calcular_split_sueldo` (en `salary_dca.py`) que reparte el monto a invertir exacto en dólares por ticker, con el redondeo resuelto para que la suma siempre dé el monto exacto. Soporta reparto personalizado (`split`) o equitativo (`tickers`, se calcula solo).
- **Tope de 10 tickers por split**, aplicado como validación dura en el código (no solo una sugerencia al modelo) — para que el ticket de confirmación siga siendo legible y los montos por ticker no queden irrisorios.
- **Confirmación explícita obligatoria antes de cualquier compra**, sin excepciones — incluido el chequeo automático diario, que solo arma el ticket y espera el "SÍ".
- **Traspaso de fondos siempre manual**: Wallbit no tiene una API para mover plata entre cuentas propias, así que el bot solo avisa y pide que el traspaso a la cuenta de Inversión se haga a mano desde el celular.
- Documentación completa del diseño en `docs/inversion_sueldo_dca.md`, con un ejemplo de cómo es la conversación con el bot.

### Corregido

- `requirements.txt`: faltaba el extra `[job-queue]` en `python-telegram-bot`, necesario para que corran los 4 jobs automáticos del bot (alertas cada 30 min, earnings diario, research diario, y el nuevo chequeo de sueldo). Sin esto, el bot fallaba al arrancar con `AttributeError: 'NoneType' object has no attribute 'run_repeating'`.
- Diseño inicial asumía que se invertía el depósito completo del sueldo — corregido para siempre preguntar y respetar la porción (% o monto fijo) que el usuario quiere destinar al DCA.

### Archivos

| Archivo | Cambio |
|---|---|
| `salary_dca.py` | Nuevo — matemática del split y de cuánto invertir (pura, sin red), tools `calcular_monto_a_invertir_sueldo` y `calcular_split_sueldo` |
| `agente.py` | Nuevo módulo de prompt `inversion_sueldo_dca` con el protocolo completo |
| `telegram_bot.py` | Nuevo job diario `chequear_sueldo_diario` |
| `requirements.txt` | Fix del extra `[job-queue]` |
| `docs/inversion_sueldo_dca.md` | Nuevo — diseño completo + ejemplo de conversación |
| `README.md` | Sección nueva describiendo la feature |
| `tests/test_salary_dca.py` | Nuevo — tests de la matemática del split, de cuánto invertir, y de las tools |
| `tests/test_telegram_bot.py` | Nuevo — tests del job diario (mockeado) |
| `tests/test_agente.py` | Tests nuevos del módulo de prompt |

**96 tests en total, todos pasando** (`python3 -m pytest tests/ -q`) — corridos tanto en el entorno de desarrollo como en la máquina real de Mateo antes de darlo por confirmado. El MCP de Wallbit (`list_transactions`/`create_trade`), que había estado roto del lado del servidor durante buena parte del desarrollo, ya fue arreglado por Wallbit y confirmado funcionando.
