# Changelog

Registro de las actualizaciones del bot, en orden cronológico (la más reciente arriba).

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
