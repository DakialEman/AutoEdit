# AutoEdit 🎬

Editor de vídeo automático que corre **entero en tu máquina**. Le das tus clips,
tus fotos y tu música; le dices en una frase cómo lo quieres (o eliges un estilo);
y te devuelve un montaje ya cortado, sincronizado con la música y corregido de
color. Después puedes retocarlo a mano y exportarlo como **MP4** o como
**proyecto editable de CapCut**, DaVinci Resolve o Premiere.

Nada sube a internet. Ni tus vídeos, ni tu prompt, ni nada.

Hay [ejecutable](#el-ejecutable) para Windows, macOS y Linux: un archivo, doble clic, sin instalar Python.

---

## El ejecutable

Un solo archivo, sin instalar Python ni nada. Lleva dentro el propio Python, la
interfaz y FFmpeg; pesa unos 70 MB.

Descárgalo de la página de
[releases](https://github.com/DakialEman/AutoEdit/releases) — hay uno por
sistema — y ábrelo con doble clic. Se abre una ventana de terminal con la
dirección de la interfaz y el navegador solo, en <http://127.0.0.1:8765>. Para
cerrarlo, cierra esa ventana. Tus proyectos siguen guardándose en `~/AutoEdit`,
así que puedes borrar y reemplazar el ejecutable sin perder nada.

| Sistema | Archivo |
| --- | --- |
| Windows 10/11 | `AutoEdit-windows-x64.exe` |
| macOS con Apple Silicon (M1 y posteriores) | `AutoEdit-macos-arm64` |
| macOS con Intel | `AutoEdit-macos-x64` |
| Linux | `AutoEdit-linux-x64` |

La primera vez tarda unos segundos más en abrir, porque descomprime su contenido
en una carpeta temporal.

> **Windows** enseña un aviso azul de SmartScreen («Windows protegió tu PC»)
> porque el archivo no está firmado — firmar cuesta unos cientos de euros al año.
> Pulsa **Más información → Ejecutar de todas formas**.
>
> **macOS** dice que «no se puede comprobar que no contenga software malicioso»,
> por lo mismo. Abre la carpeta en el Finder, clic derecho sobre el archivo →
> **Abrir** → **Abrir**. O desde la terminal:
>
> ```bash
> chmod +x AutoEdit-macos-arm64
> xattr -dr com.apple.quarantine AutoEdit-macos-arm64
> ./AutoEdit-macos-arm64
> ```
>
> **Linux**: `chmod +x AutoEdit-linux-x64` y a correr.

El ejecutable acepta los mismos subcomandos que `python -m autoedit`, si lo
llamas desde una terminal:

```bash
./AutoEdit-linux-x64 doctor                     # comprobar el entorno
./AutoEdit-linux-x64 edit ./material -p "algo dinámico" -o video.mp4
./AutoEdit-linux-x64 serve --port 9000          # la interfaz en otro puerto
```

### Construirlo tú

Con el repositorio clonado y las dependencias instaladas:

```bash
pip install pyinstaller
python packaging/build.py
```

Sale en `dist/`. Un ejecutable solo se puede construir **desde su propio
sistema**: el `.exe` hay que hacerlo en Windows, el de macOS en un Mac. Para
tenerlos los tres sin tener las tres máquinas está
`.github/workflows/build.yml`, que los construye en GitHub Actions — se lanza a
mano desde la pestaña *Actions*, o solo con publicar una etiqueta:

```bash
git tag v1.0.0 && git push --tags
```

Y para comprobar que el binario recién hecho arranca de verdad:

```bash
python packaging/smoke_test.py
```

---

## Instalación desde el código

Hace falta **Python 3.10 o superior**. Compruébalo con `python --version`.

<details open>
<summary><b>Linux y macOS</b></summary>

```bash
git clone https://github.com/DakialEman/AutoEdit
cd AutoEdit

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m autoedit
```
</details>

<details open>
<summary><b>Windows</b></summary>

Instala Python desde [python.org](https://www.python.org/downloads/) — **no**
desde la Microsoft Store, que da problemas de permisos con las carpetas. En el
instalador marca **«Add python.exe to PATH»** (viene desmarcada, abajo del todo)
y reinicia la terminal al terminar.

En **PowerShell** o **CMD**:

```powershell
git clone https://github.com/DakialEman/AutoEdit
cd AutoEdit

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python -m autoedit
```

En **Git Bash** la ruta de activación cambia — es `Scripts`, no `bin`:

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt

python -m autoedit
```
</details>

Se abre solo en <http://127.0.0.1:8765>. Sabrás que el entorno está activo
porque el prompt lleva `(.venv)` delante.

> **Si Windows responde «no se encontró Python» y te ofrece la Microsoft Store**,
> es un atajo falso que trae el sistema: Python no está instalado, o se instaló
> sin marcar «Add python.exe to PATH». Instálalo de python.org y abre una
> terminal nueva. Si `python` sigue fallando pero `py --version` funciona, usa
> `py` en lugar de `python` en todos los comandos.

**FFmpeg** es lo único que hace falta de fuera, y viene incluido con
`imageio-ffmpeg`, así que normalmente no tienes que instalar nada. Si ya tienes
FFmpeg en el sistema, AutoEdit lo prefiere (suele traer más códecs).

Para comprobar que todo está en su sitio:

```bash
python -m autoedit doctor
```

---

## Cómo se usa

1. **Trae tu material.** Arrastra vídeos, fotos y música al panel de la
   izquierda, o pulsa «Del disco» para escoger una carpeta entera. AutoEdit
   analiza cada archivo por su cuenta: detecta los mejores momentos de cada
   vídeo y saca el tempo y los pulsos de la música.

2. **Di cómo lo quieres.** Escribe algo como:

   > *vertical para TikTok, rápido, al ritmo de la música, color cálido,
   > 30 segundos, con título "Verano 2026"*

   O pulsa uno de los estilos: Dinámico, Cinematográfico, Vlog, Viaje,
   Recuerdos, Tráiler, Estético, Acción, Boda, A cámara, Promo, Beat Sync.

   Debajo del prompt aparece **lo que ha entendido** y, si algo no lo ha
   sabido aplicar, también te lo dice. Sin fingir.

3. **Retócalo.** Todo lo que propone es editable: arrastra los clips para
   reordenarlos, ajusta duraciones y puntos de entrada, cambia efectos,
   transiciones y color, añade textos, cambia la música. `Espacio` reproduce,
   `S` corta por el cursor, `Supr` borra.

4. **Expórtalo.** Vídeo final, o proyecto editable para seguir en otro sitio.

También funciona desde la terminal, sin abrir nada:

```bash
python -m autoedit edit ~/Vídeos/Japón \
    --prompt "montaje de viaje vertical de 45 segundos, ritmo medio" \
    --output ~/japon.mp4 \
    --capcut
```

---

## Qué entiende del prompt

El intérprete funciona **sin conexión y sin modelo**: son reglas que entienden
español e inglés.

| Le dices | Hace |
|---|---|
| *vertical, horizontal, cuadrado, 4:5* | Cambia el lienzo |
| *rápido, frenético / lento, tranquilo* | Acorta o alarga los cortes |
| *30 segundos, 2 minutos, 1:30, medio minuto* | Clava esa duración |
| *blanco y negro, vintage, cálido, frío, vivo, nocturno* | Aplica ese color |
| *al ritmo, beat sync* | Corta sobre los pulsos de la música |
| *sin transiciones / con fundidos* | Cortes secos o encadenados |
| *sin música / que se escuche mi voz* | Mezcla el audio como toca |
| *mejores momentos / cronológico / aleatorio* | Ordena el material |
| *que suba, in crescendo* | Acelera hacia el final |
| *con título "Lo que sea"* | Pone ese texto en pantalla |

Entiende negaciones: *«sin transiciones»* no activa las transiciones.

### Con un modelo (opcional)

Si prefieres que interprete el prompt un modelo de lenguaje, hay dos opciones,
las dos desactivadas por defecto:

```bash
# Local, sin salir de tu máquina (recomendado si quieres LLM)
export AUTOEDIT_OLLAMA_MODEL=llama3.1        # con Ollama corriendo

# O la API de Claude
pip install anthropic
export ANTHROPIC_API_KEY=...
export AUTOEDIT_PROMPT_ENGINE=anthropic
```

Si el modelo falla, tarda o rechaza la petición, AutoEdit vuelve solo a sus
reglas locales. Nunca te quedas sin montaje.

---

## Exportación

| Formato | Para qué sirve |
|---|---|
| **MP4** | El vídeo final, con efectos, color y audio mezclado |
| **Proyecto de CapCut** | Borrador editable que se abre en CapCut |
| **FCPXML** | DaVinci Resolve, Premiere Pro, Final Cut Pro |
| **EDL (CMX 3600)** | Lista de cortes universal |
| **Proyecto AutoEdit** | Copia completa, para archivar o mover de equipo |
| **Escaleta** | Resumen del montaje en Markdown |

### Sobre CapCut, con franqueza

El formato de borrador de CapCut **no es público**: está reconstruido a partir de
borradores reales y CapCut lo cambia entre versiones. AutoEdit hace lo que se
puede hacer con garantías y no finge el resto:

- **Se conserva**: el orden de los clips, el tramo exacto que se usa de cada uno,
  las duraciones, la velocidad, el volumen, la música con su punto de entrada y
  los textos con su posición.
- **No se genera**: transiciones, filtros y efectos, porque en CapCut son
  recursos internos identificados por códigos que no son públicos. Inventarlos
  produciría un borrador que CapCut rechaza. En vez de eso, cada corte que
  llevaba transición queda anotado en el archivo `AUTOEDIT.md` de la carpeta,
  para reponerlas en dos clics.

El borrador **apunta a tus archivos originales** por su ruta: si los mueves
después, CapCut los dará por perdidos.

Si tu destino es un editor de escritorio, **FCPXML es el camino fiable**: ese sí
es un formato documentado.

---

## Cómo está hecho

```
autoedit/
  models.py         Un único documento JSON describe todo el proyecto
  storage.py        Proyectos en disco, biblioteca de material
  ffmpeg.py         Capa fina sobre FFmpeg (con plan B si no hay ffprobe)
  analysis/
    media.py        Momentos destacados, cortes de escena, nitidez, exposición
    audio.py        Tempo, pulsos, energía y "drop", solo con NumPy
  ai/
    styles.py       Los doce estilos recomendados
    prompt.py       Prompt → estilo, con reglas locales ES/EN
    llm.py          Motor opcional (Claude u Ollama)
    planner.py      El auto-editor: decide cortes, tramos, efectos
  editing.py        Operaciones manuales, con sus invariantes
  render/           Timeline → MP4, en tres fases y con caché
  export/           CapCut, FCPXML, EDL, proyecto nativo
  app.py            API HTTP y servidor de la interfaz
web/                Interfaz sin build: HTML, CSS y JavaScript a pelo
packaging/          El ejecutable: receta de PyInstaller, build y prueba
```

Tres decisiones que explican casi todo lo demás:

**Una sola representación.** Auto-montar, editar a mano y exportar hablan del
mismo `Timeline`. Por eso lo que ves en la línea de tiempo es exactamente lo que
sale renderizado y lo que llega a CapCut.

**Las transiciones solapan.** Un clip con transición de 0,4 s empieza 0,4 s antes
de que acabe el anterior. Así la duración del modelo coincide al milisegundo con
la del vídeo renderizado, y los textos nunca se desincronizan.

**El render va por fases y con caché.** Cada clip se normaliza por separado a un
MP4 con parámetros idénticos, y el resultado se guarda con un hash de sus
ajustes. Cambiar un clip solo vuelve a procesar ese clip; los cortes secos se
pegan sin recodificar. Reeditar sale barato.

---

## Ajustes

Por variables de entorno:

| Variable | Por defecto | Qué hace |
|---|---|---|
| `AUTOEDIT_HOME` | `~/AutoEdit` | Dónde viven proyectos, caché y exportaciones |
| `AUTOEDIT_PORT` | `8765` | Puerto de la interfaz |
| `AUTOEDIT_CRF` | `20` | Calidad del vídeo (menos = mejor y más pesado) |
| `AUTOEDIT_PRESET` | `veryfast` | Preset de x264 (`slow` = más pequeño, más lento) |
| `AUTOEDIT_PREVIEW_HEIGHT` | `640` | Altura de la vista previa |
| `AUTOEDIT_FFMPEG` | — | Ruta a un FFmpeg concreto |
| `AUTOEDIT_PROMPT_ENGINE` | `auto` | `heuristic`, `ollama` o `anthropic` |

¿Quieres tus propias tipografías para los textos? Déjalas en
`~/AutoEdit/fonts/` y aparecerán en el desplegable.

---

## Tests

```bash
pip install pytest httpx
pytest
```

Son 157 y tardan unos segundos. La suite de render genera su propio material con
FFmpeg y se salta sola si no lo encuentra.

---

## Licencia

MIT.
