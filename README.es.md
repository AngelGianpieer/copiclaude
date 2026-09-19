# CopiClaude

Usa [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) o
[GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)
en el mismo proyecto y **cambia de uno a otro sin volver a explicar nada**.
Cuando a uno se le acaba la cuota, pulsas una tecla: el otro arranca en la misma
carpeta con una nota de traspaso (lo que pediste, la última respuesta, qué cambió
en git) y cada asistente conserva su propia sesión para poder volver.

- Funciona en **Linux, macOS y Windows**.
- Los agentes corren igual que siempre, en tu terminal. CopiClaude solo reenvía
  teclas y salida, salvo una tecla que significa "cambiar".
- Sin red, sin telemetría, sin cuentas. Nunca ve tus credenciales.
- **No** modifica tu `CLAUDE.md`, `AGENTS.md` ni `.gitignore`.

> Herramienta comunitaria no oficial. Sin relación con Anthropic ni GitHub.

## Instalación

Necesitas Python 3.9+ y al menos uno de los dos CLIs instalado y con sesión iniciada.

```bash
pipx install git+https://github.com/AngelGianpieer/copiclaude
# o:  pip install --user git+https://github.com/AngelGianpieer/copiclaude
```

En Windows el backend ConPTY (`pywinpty`) se instala solo. Usa Windows Terminal o
una consola con soporte de terminal virtual. Comprueba todo con `copiclaude doctor`.

## Uso

```bash
cd mi-proyecto
copiclaude                # arranca el último agente usado (Claude Code la primera vez)
copiclaude --agent copilot
```

Trabaja normal. Para cambiar pulsa **Ctrl+K**, o ejecuta `copiclaude switch` desde
otra terminal. CopiClaude detiene el agente, escribe `.copiclaude/HANDOFF.md` y
arranca el otro pidiéndole que lo lea. Cada agente retoma su conversación anterior
cuando vuelves a él.

### Cuando se alcanza un límite de uso

Lo detecta mirando el registro de sesión del propio agente (errores estructurados,
fiable) y el texto en pantalla (solo una pista). Luego **pregunta** en vez de actuar,
porque "rate limit" también aparece cuando un agente solo habla de límites:

```
 Claude Code parece sin cuota. ctrl+k: cambiar a GitHub Copilot CLI - otra tecla: ignorar
```

Pulsa la tecla de cambio para aceptar; cualquier otra lo descarta (y le llega al
agente). `auto_switch` = `always` cambia sin preguntar y `off` desactiva la
detección. Si el otro agente llegó a su límite hace poco, no se propone volver a él.

### Comandos

| Comando | Qué hace |
| --- | --- |
| `copiclaude` | Ejecuta el agente en el proyecto actual |
| `copiclaude switch` | Pide al copiclaude en ejecución que cambie de agente |
| `copiclaude status [--json]` | Muestra configuración, estado y CLIs detectados |
| `copiclaude config [--user]` | Asistente interactivo (`--show` imprime la config efectiva) |
| `copiclaude doctor` | Revisa Python, terminal, ambos CLIs, git y configuración |
| `copiclaude clean` | Quita el bloque que la 0.1 escribía en `CLAUDE.md`/`AGENTS.md` |

## Configuración

Por capas, gana la última: valores por defecto, archivo de usuario
(`~/.config/copiclaude/config.json`, `%APPDATA%\copiclaude\config.json` en Windows)
y archivo del proyecto `.copiclaude/config.json`. Las claves son las mismas que en
el [README en inglés](README.md#configuration). `COPICLAUDE_LANG=es` fuerza los
mensajes en español (por defecto se usa el idioma del sistema).

Todo el estado vive en `.copiclaude/` en la raíz del proyecto (la carpeta más
cercana con `.git` o `.copiclaude`) y se ignora a sí mismo en git. El traspaso cita
tus últimos prompts leídos del archivo de sesión local del agente; no compartas
`.copiclaude/` si son sensibles. Los agentes siempre arrancan en la raíz del proyecto.

## Límites conocidos

- Los formatos de sesión y los mensajes de cuota son de cada CLI y pueden cambiar;
  por eso la detección falla de forma segura (en el peor caso cambias tú con la tecla).
- Corre un agente a la vez: es un conmutador, no un orquestador en paralelo.
- En Windows hay pruebas automáticas con agentes de prueba; con agentes reales
  depende de `pywinpty`/ConPTY. Abre un issue con la salida de `copiclaude doctor`.

## Desarrollo

```bash
pip install -e ".[test]"
pytest
```

Licencia MIT.
