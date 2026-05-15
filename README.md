# 🤖 Agente Financiero Wallbit

Tu analista de Wall Street personal, disponible 24/7 por Telegram. Conectado en tiempo real a tu cuenta de [Wallbit](https://wallbit.io) — consultá tu portafolio, **ejecutá compras y ventas**, recibí alertas automáticas de precio, análisis de earnings nivel sell-side (JPMorgan/GS format), screener de acciones, datos macro de la Fed, filings oficiales de la SEC e insiders. Todo desde un mensaje de Telegram, gratis y open source.

## ¿Qué puede hacer?

- **Balance y portafolio** — saldo en cuenta corriente y todas tus posiciones en tiempo real
- **Análisis de acciones** — fundamentals, P/E, market cap, márgenes, crecimiento (vía Yahoo Finance)
- **Datos macro** — inflación, tasa Fed, desempleo, curva de tasas (vía FRED)
- **Filings SEC** — 10-K, 10-Q, 8-K directo de la fuente oficial
- **Insiders** — quién está comprando/vendiendo dentro de cada empresa
- **Earnings Analysis** — análisis post-resultados nivel sell-side (JPMorgan/GS format)
- **Earnings Preview** — escenarios bull/base/bear antes de que reporte una empresa
- **Idea Generation** — screener de acciones por valor, crecimiento o calidad
- **Sector Overview** — análisis sectorial completo con landscape competitivo
- **Thesis Tracker** — armá y revisá tesis de inversión estructuradas
- **Watchlist con alertas** — chequeo automático de precios cada 30 minutos
- **Metas financieras** — creá objetivos y seguí el progreso
- **Presupuesto mensual** — categorizá gastos y controlá límites
- **Diario de trading** — registrá decisiones y detectá sesgos cognitivos
- **Morning Briefing** — resumen diario de tu portafolio + mercado + macro

## Requisitos

- Mac con Python 3.10+
- Cuenta en [Wallbit](https://wallbit.io)
- Cuenta en [Telegram](https://telegram.org)
- API keys (ver sección de instalación)

## Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/agente-wallbit.git
cd agente-wallbit
```

### 2. Obtener las API keys necesarias

| Key | Dónde obtenerla | Costo |
|-----|----------------|-------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys | Pago por uso |
| `WALLBIT_API_KEY` | Panel de Wallbit → API | Gratis con cuenta |
| `TELEGRAM_BOT_TOKEN` | Telegram → [@BotFather](https://t.me/BotFather) → /newbot | Gratis |
| `BRAVE_API_KEY` | [api.search.brave.com](https://api.search.brave.com) | Gratis hasta 2000 búsquedas/mes |
| `TELEGRAM_USER_ID` | Telegram → [@userinfobot](https://t.me/userinfobot) → /start | Gratis |

### 3. Configurar las API keys

```bash
cp config.env.example config.env
```

Editá `config.env` con tus datos reales:

```
ANTHROPIC_API_KEY=sk-ant-...
WALLBIT_API_KEY=wlb_live_...
TELEGRAM_BOT_TOKEN=123456789:ABC-...
BRAVE_API_KEY=BSA...
TELEGRAM_USER_ID=123456789
```

### 4. Instalar dependencias y lanzar

```bash
bash instalar.sh
cd ~/agente-wallbit && python3 telegram_bot.py
```

### 5. (Opcional) Arranque automático al encender la Mac

```bash
cp ~/agente-wallbit/com.agente.wallbit.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.agente.wallbit.plist
```

Con esto el bot arranca solo cada vez que iniciás sesión. No necesitás la terminal.

## Uso

Abrí Telegram y escribile a tu bot. Ejemplos:

```
"¿Cuál es mi saldo?"
"Analizá los fundamentals de NVDA"
"Hacé un earnings preview de AAPL para esta semana"
"Dame 5 ideas de acciones de crecimiento en IA"
"Cuál es la inflación actual en EEUU"
"Agregá MSFT a mi watchlist"
"Avisame si SPY baja de $500"
"Morning Briefing"
"Armame una tesis de inversión para AMZN"
"Analizá el sector de semiconductores"
```

## Comandos de Telegram

| Comando | Función |
|---------|---------|
| `/start` | Iniciar el agente |
| `/balance` | Ver saldo y posiciones |
| `/briefing` | Morning Briefing completo |
| `/alertas` | Ver alertas activas |
| `/watchlist` | Ver watchlist con precios |
| `/ayuda` | Lista de comandos |

## Arquitectura

```
agente-wallbit/
├── agente.py          # Motor principal con Anthropic Tool Use (14 herramientas)
├── database.py        # Base de datos SQLite (watchlist, alertas, metas, historial)
├── wallbit_client.py  # Cliente HTTP para Wallbit MCP
├── brave_client.py    # Cliente Brave Search con caché 30min
├── market_data.py     # Yahoo Finance, FRED, SEC EDGAR
├── telegram_bot.py    # Bot de Telegram con job queue
├── instalar.sh        # Script de instalación
└── config.env.example # Template de configuración
```

El bot usa el patrón **Anthropic Tool Use** — Claude decide qué herramientas llamar, Python las ejecuta con datos reales, y Claude interpreta los resultados. Esto garantiza que cada respuesta esté basada en datos reales de tu cuenta y del mercado.

## Fuentes de datos

| Fuente | Qué provee | Costo |
|--------|-----------|-------|
| Wallbit MCP | Saldo, posiciones, trades | Incluido con Wallbit |
| Yahoo Finance | Fundamentals, historial, insiders, dividendos | Gratis |
| FRED (Fed Reserve) | Inflación, tasas, macro | Gratis |
| SEC EDGAR | Filings 10-K, 10-Q, 8-K | Gratis |
| Brave Search | Noticias financieras en tiempo real | Gratis hasta 2000/mes |

## Nota

Este proyecto es de uso personal y educativo. No constituye asesoramiento financiero. Todas las decisiones de inversión son responsabilidad del usuario.
