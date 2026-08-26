# AutoEdit 🎬

Editor de vídeo automático que corre **entero en tu máquina**. Le das tus clips,
tus fotos y tu música; le dices en una frase cómo lo quieres (o eliges un estilo);
y te devuelve un montaje ya cortado, sincronizado con la música y corregido de
color. Después puedes retocarlo a mano y exportarlo como **MP4** o como
**proyecto editable de CapCut**, DaVinci Resolve o Premiere.

Nada sube a internet. Ni tus vídeos, ni tu prompt, ni nada.

---

## Instalación

```bash
git clone https://github.com/DakialEman/AutoEdit
cd AutoEdit

python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m autoedit
```

Se abre solo en <http://127.0.0.1:8765>.

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

Son 142 y tardan unos segundos. La suite de render genera su propio material con
FFmpeg y se salta sola si no lo encuentra.

---

## Licencia

MIT.
