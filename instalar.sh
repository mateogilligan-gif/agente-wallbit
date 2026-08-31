#!/bin/bash
# Instalador del Agente Wallbit — Mac, Linux o Windows (WSL/Git Bash)
set -e

echo "🤖 Instalando Agente Wallbit..."

# Detectar el comando de Python disponible
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "❌ No se encontró Python instalado. Instalá Python 3.10+ antes de continuar."
    exit 1
fi

echo "✓ Usando $($PYTHON --version)"

# Verificar que exista config.env
if [ ! -f "config.env" ]; then
    if [ -f "config.env.example" ]; then
        echo "⚠️  No existe config.env — copiando desde config.env.example."
        echo "   Editalo con tus API keys antes de arrancar el bot."
        cp config.env.example config.env
    else
        echo "❌ No se encontró config.env ni config.env.example. Revisá el repo."
        exit 1
    fi
fi

# Instalar dependencias
echo "📦 Instalando dependencias de Python..."
$PYTHON -m pip install -r requirements.txt --break-system-packages 2>/dev/null || \
    $PYTHON -m pip install -r requirements.txt

echo ""
echo "✅ Instalación completa."
echo ""
echo "Próximos pasos:"
echo "  1. Editá config.env con tus API keys (si no lo hiciste)"
echo "  2. Corré: $PYTHON telegram_bot.py"
echo ""
