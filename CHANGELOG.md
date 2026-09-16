# Changelog

Registro de las actualizaciones del bot, en orden cronológico (la más reciente arriba).

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
