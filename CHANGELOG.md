# Changelog

Registro de las actualizaciones del bot, en orden cronológico (la más reciente arriba).

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
