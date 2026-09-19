"""User-facing strings (English and Spanish). Choose with COPICLAUDE_LANG=en|es;
otherwise the locale decides, defaulting to English."""

from __future__ import annotations

import locale
import os
from typing import Dict

MESSAGES: Dict[str, Dict[str, str]] = {
    "en": {
        "starting": "starting {agent} ({key} switches agent)",
        "not_installed": "'{command}' was not found. Install {agent} or set '{name}.command' in the config.",
        "backend_error": "{error}",
        "switching": "switching {source} -> {target} ({reason})",
        "reason_manual": "manual",
        "reason_quota": "usage limit",
        "reason_request": "requested",
        "handoff_written": "handoff written to {path}; starting {target}",
        "banner_limit": "{agent} looks out of quota. {key}: switch to {target} - any other key: ignore",
        "banner_other_exhausted": "{agent} looks out of quota, but {other} hit a limit {minutes} min ago - not switching",
        "banner_cannot_switch": "cannot switch: {target} is not installed",
        "retrying": "{agent} exited right away; retrying as a {mode} session",
        "mode_new": "new",
        "mode_resume": "resumed",
        "exited_error": "{agent} exited with code {code}",
        "terminal_closed": "terminal closed, stopping {agent}",
        "signal_stop": "received a stop signal, stopping {agent}",
        "nested": "already running inside copiclaude; refusing to nest.",
        "need_tty": "copiclaude needs an interactive terminal (stdin and stdout must be a TTY).",
        "already_running": "another copiclaude is already running in this project (pid {pid}).",
        "already_running_unknown": "another copiclaude is already running in this project.",
        "risky_root": "{root} is your home or filesystem root, not a project. State would be stored in {root}/.copiclaude. Continue?",
        "risky_root_refused": "Refusing to use {root} as a project. Run copiclaude inside a project, or pass --yes.",
        "legacy_found": "found a 0.1 handoff block in {files}; run 'copiclaude clean' to remove it.",
        "legacy_cleaned": "removed the old handoff block from {path} (backup: {path}.copiclaude.bak)",
        "legacy_none": "nothing to clean.",
        "config_error": "configuration problem: {error}",
        "warning": "warning: {text}",
        "switch_requested": "switch requested; the running copiclaude will switch within a second.",
        "switch_no_instance": "no copiclaude is running in this project.",
        "wizard_title": "copiclaude setup for {where}",
        "wizard_default_agent": "Default agent (claude/copilot)",
        "wizard_model": "  {agent} model (empty = agent default)",
        "wizard_effort": "  {agent} effort ({choices}; empty = default)",
        "wizard_auto": "When a usage limit is detected (ask/always/off)",
        "wizard_key": "Key that switches agent",
        "wizard_invalid": "  invalid value, try again",
        "wizard_saved": "saved {path}",
        "wizard_no_tty": "The setup wizard needs an interactive terminal. Edit {path} by hand instead.",
        "status_title": "copiclaude {version}",
        "doctor_ok": "ok",
        "doctor_missing": "missing",
    },
    "es": {
        "starting": "iniciando {agent} ({key} cambia de agente)",
        "not_installed": "No se encontro '{command}'. Instala {agent} o define '{name}.command' en la configuracion.",
        "backend_error": "{error}",
        "switching": "cambiando {source} -> {target} ({reason})",
        "reason_manual": "manual",
        "reason_quota": "limite de uso",
        "reason_request": "solicitado",
        "handoff_written": "handoff escrito en {path}; iniciando {target}",
        "banner_limit": "{agent} parece sin cuota. {key}: cambiar a {target} - otra tecla: ignorar",
        "banner_other_exhausted": "{agent} parece sin cuota, pero {other} llego a su limite hace {minutes} min - no se cambia",
        "banner_cannot_switch": "no se puede cambiar: {target} no esta instalado",
        "retrying": "{agent} salio de inmediato; reintentando como sesion {mode}",
        "mode_new": "nueva",
        "mode_resume": "reanudada",
        "exited_error": "{agent} termino con codigo {code}",
        "terminal_closed": "terminal cerrada, deteniendo {agent}",
        "signal_stop": "senal de parada recibida, deteniendo {agent}",
        "nested": "ya se esta ejecutando dentro de copiclaude; no se anida.",
        "need_tty": "copiclaude necesita una terminal interactiva (stdin y stdout deben ser un TTY).",
        "already_running": "ya hay otro copiclaude corriendo en este proyecto (pid {pid}).",
        "already_running_unknown": "ya hay otro copiclaude corriendo en este proyecto.",
        "risky_root": "{root} es tu carpeta personal o la raiz del sistema, no un proyecto. El estado se guardaria en {root}/.copiclaude. Continuar?",
        "risky_root_refused": "No uso {root} como proyecto. Ejecuta copiclaude dentro de un proyecto, o pasa --yes.",
        "legacy_found": "hay un bloque de handoff de la 0.1 en {files}; ejecuta 'copiclaude clean' para quitarlo.",
        "legacy_cleaned": "se quito el bloque de handoff viejo de {path} (copia: {path}.copiclaude.bak)",
        "legacy_none": "nada que limpiar.",
        "config_error": "problema de configuracion: {error}",
        "warning": "aviso: {text}",
        "switch_requested": "cambio solicitado; el copiclaude en ejecucion cambiara en menos de un segundo.",
        "switch_no_instance": "no hay ningun copiclaude corriendo en este proyecto.",
        "wizard_title": "configuracion de copiclaude para {where}",
        "wizard_default_agent": "Agente por defecto (claude/copilot)",
        "wizard_model": "  modelo de {agent} (vacio = el del agente)",
        "wizard_effort": "  esfuerzo de {agent} ({choices}; vacio = por defecto)",
        "wizard_auto": "Al detectar un limite de uso (ask/always/off)",
        "wizard_key": "Tecla para cambiar de agente",
        "wizard_invalid": "  valor invalido, intenta de nuevo",
        "wizard_saved": "guardado {path}",
        "wizard_no_tty": "El asistente necesita una terminal interactiva. Edita {path} a mano.",
        "status_title": "copiclaude {version}",
        "doctor_ok": "ok",
        "doctor_missing": "falta",
    },
}


def language() -> str:
    forced = os.environ.get("COPICLAUDE_LANG", "").strip().lower()
    if forced in MESSAGES:
        return forced
    try:
        code = (os.environ.get("LC_ALL") or os.environ.get("LANG") or locale.getlocale()[0] or "").lower()
    except (ValueError, TypeError):
        code = ""
    return "es" if code.startswith("es") else "en"


def t(message_id: str, /, **values: object) -> str:
    template = MESSAGES[language()].get(message_id) or MESSAGES["en"][message_id]
    return template.format(**values)
