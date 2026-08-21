# Agente Financiero Wallbit

Un agente de IA conectado a tu cuenta de [Wallbit](https://wallbit.io) que vive en Telegram. Lo armé para investigar empresas, rastrear mi portfolio y pensar mejor antes de mover plata — no para operar más seguido.

Usa la API pública de Wallbit + Claude (Anthropic) como cerebro + fuentes de datos gratuitas. Open source.

---

## Qué puede hacer

**Portfolio y cuenta**
- Saldo en cuenta corriente y posiciones de inversión en tiempo real
- Resumen del portfolio con cantidad de acciones, precio promedio, valor actual y P&L por posición
- Historial de transacciones

**Análisis de acciones**
- Fundamentals completos: P/E, market cap, márgenes, crecimiento, consenso de analistas (Yahoo Finance)
- Estado de resultados anual: ingresos, utilidad neta, EBITDA
- Insiders: quién está comprando o vendiendo dentro de la empresa
- Historial de dividendos
- Filings oficiales de la SEC: 10-K, 10-Q, 8-K

**Earnings**
- Earnings Calendar: próximas fechas de reporte de tu portfolio con EPS estimado del consenso
- Aviso automático cada mañana si alguna empresa tuya reporta esa semana
- Earnings Preview: escenarios bull/base/bear antes de que reporte
- Earnings Analysis: análisis post-resultados con comparación vs consenso

**Mercado y macro**
- Datos de la Fed en tiempo real: inflación, tasas, desempleo, PIB, curva de tasas, dólar
- Noticias financieras en tiempo real vía Brave Search (Bloomberg, Reuters, CNBC)
- Sector Overview: análisis de un sector con landscape competitivo y valuación histórica

**Herramientas de inversión**
- Watchlist con alertas de precio automáticas (chequeo cada 30 minutos)
- Thesis Tracker: armá y revisá tesis de inversión estructuradas
- Idea Generation: screener por valor, crecimiento o calidad
- Screener de tesis: describís una tesis en lenguaje natural ("empresas de defensa con contratos nuevos") y el agente busca candidatos con Brave Search + los valida con datos reales de yfinance (revenue growth, márgenes, deuda, P/E)
- Lectura de páginas completas: cuando un snippet de noticia no alcanza, el agente entra a la URL real (web oficial de la empresa, prensa o foros especializados del país/rubro donde opera esa empresa — no importa si es Argentina, EEUU, Australia o Europa) y extrae el texto completo del artículo
- Búsqueda global de noticias: motor propio (Google News RSS + GDELT) que busca en prensa de cualquier país del mundo filtrando por código ISO de país e idioma, no limitado a medios en inglés como el buscador general
- Sentimiento social: consulta StockTwits (comunidad 100% financiera) para ver el % de mensajes Bullish/Bearish sobre un ticker. Evaluamos usar X/Twitter y lo descartamos — desde 2026 cobra por post leído y tiene mucho más ruido (bots, pump groups) sin ninguna etiqueta de sentimiento
- Diario de trading: registrá decisiones y detectá sesgos cognitivos
- Metas financieras con seguimiento de progreso
- Presupuesto mensual por categorías
- Morning Briefing: resumen diario de portfolio + mercado + macro

**Análisis estructurado**
- Decision Log: registra automáticamente cada análisis (veredicto + precio + razonamiento) para comparar si la tesis fue correcta en el próximo análisis del mismo ticker
- Bull vs Bear: debate estructurado con dos argumentos opuestos sobre un mismo ticker — el veredicto es tuyo
- Profundidad configurable: "análisis rápido de X" (1 búsqueda) o "análisis profundo de X" (3 búsquedas + financials + SEC)

**Ejecución de órdenes**
- Comprá y vendé acciones directamente desde Telegram
- Siempre pide confirmación explícita antes de ejecutar
- Sugiere tipo de orden (MARKET o LIMIT) según condiciones del mercado

---

## Requisitos

- Python 3.10+ (Mac, Linux o Windows)
- Cuenta en [Wallbit](https://wallbit.io)
- Cuenta en [Telegram](https://telegram.org)
- API keys (ver instalación)

---

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/mateogilligan-gif/agente-wallbit.git
cd agente-wallbit
```

### 2. Obtener las API keys

| Key | Dónde obtenerla | Costo |
|-----|----------------|-------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys | Pago por uso |
| `WALLBIT_API_KEY` | Panel de Wallbit → API | Gratis con cuenta |
| `TELEGRAM_BOT_TOKEN` | Telegram → [@BotFather](https://t.me/BotFather) → /newbot | Gratis |
| `BRAVE_API_KEY` | [api.search.brave.com](https://api.search.brave.com) | Gratis hasta 2000 búsquedas/mes |
| `TELEGRAM_USER_ID` | Telegram → [@userinfobot](https://t.me/userinfobot) → /start | Gratis |

### 3. Configurar

```bash
cp config.env.example config.env
```

Editá `config.env` con tus datos:

```
ANTHROPIC_API_KEY=sk-ant-...
WALLBIT_API_KEY=wlb_live_...
TELEGRAM_BOT_TOKEN=123456789:ABC-...
BRAVE_API_KEY=BSA...
TELEGRAM_USER_ID=123456789
```

### 4. Instalar y lanzar

```bash
bash instalar.sh
cd ~/agente-wallbit && python3 telegram_bot.py
```

### 5. Arranque automático (opcional)

**Mac:**
```bash
cp ~/agente-wallbit/com.agente.wallbit.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.agente.wallbit.plist
```

**Linux:**
```bash
# Crear el servicio
sudo nano /etc/systemd/system/agente-wallbit.service
```
Contenido del archivo:
```
[Unit]
Description=Agente Wallbit
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/TU_USUARIO/agente-wallbit/telegram_bot.py
WorkingDirectory=/home/TU_USUARIO/agente-wallbit
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable agente-wallbit
sudo systemctl start agente-wallbit
```

**Windows:**
Buscá "Programador de tareas" en el menú inicio, creá una tarea nueva que ejecute `python telegram_bot.py` al iniciar sesión.

El bot arranca solo en cada inicio. No necesitás tener la terminal abierta.

---

## Despliegue en la nube (sin depender de tu computadora)

Si no querés tener el bot corriendo en tu máquina, podés desplegarlo en [Railway](https://railway.app) — es la opción más simple y tiene un plan gratis para empezar.

### Railway (recomendado)

1. Creá una cuenta en [railway.app](https://railway.app)
2. Nuevo proyecto → Deploy from GitHub repo → seleccioná `agente-wallbit`
3. En Variables, cargá las mismas keys de tu `config.env`
4. En Settings → Deploy → Start Command:
```
python telegram_bot.py
```
5. Deploy. El bot corre 24/7 sin necesitar tu computadora prendida.

> **Costo estimado:** Railway cobra ~$5/mes en el plan Hobby. DigitalOcean y Render son alternativas similares.

---

## Uso

Escribile a tu bot en Telegram en lenguaje natural:

```
"¿Cuál es mi saldo?"
"Analizá NVDA — fundamentals, insiders y noticias recientes"
"Hacé un earnings preview de AAPL"
"Dame 5 ideas de acciones de crecimiento en IA"
"¿Cuál es la inflación actual en EEUU?"
"Agregá MSFT a mi watchlist"
"Avisame si SPY baja de $500"
"Morning Briefing"
"Armame una tesis de inversión para AMZN"
"Analizá el sector de semiconductores"
"¿Mis empresas reportan earnings esta semana?"
"Comprá $100 de VOO" (pide confirmación antes de ejecutar)
```

## Comandos de Telegram

| Comando | Función |
|---------|---------|
| `/start` | Iniciar el agente |
| `/balance` | Ver saldo y posiciones |
| `/briefing` | Morning Briefing completo |
| `/earnings` | Earnings próximos de tu portfolio (14 días) |
| `/debate TICKER` | Debate Bull vs Bear de una acción |
| `/alertas` | Ver alertas de precio activas |
| `/watchlist` | Ver watchlist con precios actuales |
| `/ayuda` | Lista de comandos |

---

## Arquitectura

```
agente-wallbit/
├── agente.py          # Motor principal — Anthropic Tool Use (23 herramientas)
├── wallbit_client.py  # Cliente Wallbit MCP + parser de portfolio
├── market_data.py     # Yahoo Finance, FRED, SEC EDGAR, Earnings Calendar
├── database.py        # SQLite — watchlist, alertas, metas, historial, diario
├── brave_client.py    # Brave Search con caché 30min
├── web_reader.py      # Lector de páginas web completas (empresas, diarios locales)
├── global_search.py   # Motor de búsqueda global de noticias (Google News RSS + GDELT)
├── social_sentiment.py # Sentimiento social vía StockTwits (Bullish/Bearish)
├── telegram_bot.py    # Bot de Telegram + jobs automáticos
├── instalar.sh        # Script de instalación
└── config.env.example # Template de configuración
```

El bot usa el patrón **Anthropic Tool Use**: Claude decide qué herramientas llamar, Python las ejecuta con datos reales, y Claude interpreta los resultados. Cada respuesta está basada en datos reales de tu cuenta y del mercado, no en estimaciones.

El módulo **Bull vs Bear** hace dos llamadas separadas a Claude con instrucciones opuestas (alcista y bajista) para forzar análisis sin sesgo de confirmación. El **Decision Log** registra cada veredicto con precio y razonamiento, y los cruza con el próximo análisis del mismo ticker para saber si la tesis fue correcta.

---

## Fuentes de datos

| Fuente | Qué provee | Costo |
|--------|-----------|-------|
| Wallbit API | Saldo, posiciones, historial, ejecución de órdenes | Incluido con cuenta Wallbit |
| Yahoo Finance | Fundamentals, historial, insiders, dividendos, earnings calendar | Gratis |
| FRED (Federal Reserve) | Inflación, tasas, desempleo, PIB, macro | Gratis |
| SEC EDGAR | Filings 10-K, 10-Q, 8-K | Gratis |
| Brave Search | Noticias financieras en tiempo real | Gratis hasta 2000 búsquedas/mes |
| Google News RSS | Prensa local por país/idioma (cualquier mercado del mundo) | Gratis, sin API key |
| GDELT Project | Índice global de noticias de prácticamente todos los países | Gratis, sin API key |

---

## Jobs automáticos

El bot corre dos tareas en segundo plano sin que tengas que pedirlas:

- **Cada 30 minutos**: verifica alertas de precio de tu watchlist y notifica si alguna se disparó
- **Todos los días a las 8am (Argentina)**: revisa si alguna empresa de tu portfolio reporta earnings esa semana y te avisa

---

## Nota

Proyecto de uso personal y educativo. No constituye asesoramiento financiero. Todas las decisiones de inversión son responsabilidad del usuario.
