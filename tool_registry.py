"""
tool_registry.py — Registro compartido de herramientas para Anthropic Tool Use.

Antes (cambio 1 de esta serie) el registro y el decorador @tool vivían en
agente.py, junto con las 32 funciones que resuelven cada tool. Eso obligaba
a que TODAS las tools estuvieran en un solo archivo, aunque su lógica de
negocio ya vivía repartida en wallbit_client.py, market_data.py, etc.

Este módulo no depende de ningún otro archivo del proyecto (ni agente.py, ni
market_data.py, ni nada) — es la pieza mínima y neutral que permite que cada
módulo de dominio registre sus propias tools con @tool(...) sin generar
imports circulares con agente.py (que sí importa a todos los demás).
"""

TOOL_REGISTRY = {}


def tool(name: str, description: str, input_schema: dict):
    """Decorador: registra el schema de una tool junto con la función que la ejecuta.

    Cualquier módulo puede usarlo así, junto a la lógica de negocio que ya
    tenga: schema y handler quedan definidos en el mismo lugar.

        from tool_registry import tool

        @tool("mi_tool", "Descripción para Claude.", {"type": "object", "properties": {}, "required": []})
        def _tool_mi_tool(inputs: dict):
            return {"ok": True, "data": "..."}
    """
    def decorador(func):
        TOOL_REGISTRY[name] = {
            "schema": {"name": name, "description": description, "input_schema": input_schema},
            "handler": func,
        }
        return func
    return decorador
