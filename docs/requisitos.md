# AutoEdit — Análisis y especificación de requisitos

Documento de trabajo. Recoge **lo que el sistema hace hoy**, verificado contra el
código, y **lo que debe hacer** según lo acordado pero aún no implementado.

Sirve para dos cosas: decidir qué construir a continuación, y no perder de vista
qué supuestos de diseño hay que levantar antes de poder construirlo.

| | |
|---|---|
| Versión | 1.0 |
| Estado del código | rama `claude/auto-editor-local-export-gsijiq` |
| Tamaño | ~10 600 líneas (Python, JS, CSS, HTML) |
| Pruebas automáticas | 155 |
| Última verificación | contando del código, no de memoria |

---

## 1. Propósito y alcance

AutoEdit es un **editor de vídeo automático de escritorio**, ejecutado en local,
que monta un vídeo a partir del material del usuario guiado por una descripción
en lenguaje natural o por un estilo predefinido, permite corregir el resultado a
mano y lo exporta como vídeo final o como proyecto editable para otros editores.

**Dentro del alcance:** montaje automático, edición manual, render y exportación.

**Fuera del alcance:** grabación, corrección de color avanzada, animación por
fotogramas clave, colaboración entre varias personas, cualquier proceso en la nube.

### Restricción rectora

> **RG-01 — Todo ocurre en la máquina del usuario.** Ni el material, ni el
> prompt, ni los proyectos salen del equipo. La única excepción es el motor de
> prompts con Claude, que está **desactivado por defecto** y requiere que el
> usuario lo active explícitamente.

---

## 2. Actores

| Actor | Descripción |
|---|---|
| **Usuario editor** | Persona que aporta el material y quiere un vídeo montado. Único actor humano. |
| **FFmpeg** | Sistema externo. Decodifica, analiza y renderiza. Obligatorio. |
| **CapCut / Resolve / Premiere** | Sistemas externos receptores de las exportaciones. |
| **Modelo de lenguaje** | Opcional (Claude u Ollama). El sistema funciona sin él. |

---

## 3. Requisitos funcionales implementados

### 3.1 Gestión de proyectos

| ID | El sistema… |
|---|---|
| RF-01 | Crea proyectos con nombre, y genera uno automáticamente si no hay ninguno. |
| RF-02 | Lista los proyectos con su nº de archivos, nº de clips, estilo y fecha. |
| RF-03 | Abre, renombra y duplica un proyecto. |
| RF-04 | Borra un proyecto con su caché y sus exportaciones, previa confirmación. |
| RF-05 | Guarda cada proyecto como **un único JSON** en disco, de forma atómica. |
| RF-06 | Recuerda el último proyecto abierto entre sesiones. |

### 3.2 Importación de material

| ID | El sistema… |
|---|---|
| RF-07 | Importa por arrastrar y soltar, por subida, o por ruta del disco. |
| RF-08 | Importa una carpeta entera, recursivamente. |
| RF-09 | Ofrece un explorador de archivos propio dentro de la interfaz. |
| RF-10 | Acepta 9 formatos de imagen, 9 de audio y 11 de vídeo. |
| RF-11 | **Clasifica cada archivo por su contenido real, no por su extensión.** |
| RF-12 | Referencia los archivos por ruta; no duplica gigabytes. |
| RF-13 | Detecta y avisa si un archivo ya no está donde estaba. |
| RF-14 | Permite excluir un archivo del auto-montaje sin quitarlo del proyecto. |
| RF-15 | Quita un archivo **sin pedir confirmación**, ofreciendo deshacer. |

### 3.3 Análisis automático

| ID | El sistema… |
|---|---|
| RF-16 | Analiza cada vídeo muestreando fotogramas en gris a 4 fps. |
| RF-17 | Calcula movimiento, nitidez, exposición y contraste por fotograma. |
| RF-18 | Detecta cortes de escena. |
| RF-19 | Identifica los **mejores tramos** de cada vídeo y los puntúa. |
| RF-20 | Extrae de la música el **tempo** y la **rejilla de pulsos**, ajustada a los picos reales. |
| RF-21 | Detecta los inicios de compás y el «drop». |
| RF-22 | Genera la forma de onda y las miniaturas. |
| RF-23 | Analiza en segundo plano, con progreso y sin bloquear la interfaz. |

> Todo el análisis se hace con NumPy sobre datos que entrega FFmpeg. Sin modelos
> ni librerías de audio pesadas.

### 3.4 Auto-edición

| ID | El sistema… |
|---|---|
| RF-24 | Ofrece **12 estilos** predefinidos. |
| RF-25 | Interpreta un prompt en español e inglés con **21 reglas** y 99 pistas de estilo, sin conexión. |
| RF-26 | Entiende negaciones: «sin transiciones» no activa las transiciones. |
| RF-27 | **Informa de qué ha entendido** y de qué palabras no supo aplicar. |
| RF-28 | Deduce formato, ritmo, duración, color, orden, audio y textos del prompt. |
| RF-29 | Clava la duración pedida, iterando hasta lograrlo. |
| RF-30 | Sincroniza los cortes con los pulsos de la música. |
| RF-31 | Elige el mejor tramo de cada vídeo, sin repetir el mismo dos veces. |
| RF-32 | Reparte el material entre todos los archivos disponibles. |
| RF-33 | Aplica transiciones (19), efectos de movimiento (9) y color (10) según el estilo. |
| RF-34 | Genera otra combinación distinta con «Rebarajar». |
| RF-35 | Admite un modelo de lenguaje opcional, con vuelta automática a las reglas si falla. |

### 3.5 Edición manual

| ID | El sistema… |
|---|---|
| RF-36 | Reordena clips arrastrándolos. |
| RF-37 | Parte un clip por el cursor. |
| RF-38 | Ajusta duración, punto de entrada, velocidad, volumen y espejado. |
| RF-39 | Cambia encaje, efecto, intensidad, color y transición por clip. |
| RF-40 | Duplica, elimina y bloquea clips. |
| RF-41 | Aplica un ajuste a todos los clips de una vez. |
| RF-42 | Añade, edita y borra textos con tipografía, color, contorno, caja, posición y animación. |
| RF-43 | Asigna la música y ajusta su punto de entrada y volumen. |
| RF-44 | **Admite varias pistas de audio**, con volumen y silencio propios. |
| RF-45 | Coloca un audio en el segundo exacto arrastrándolo. |
| RF-46 | Baja la música automáticamente cuando suena otro audio. |
| RF-47 | Mantiene **la invariante de la cadena**: los clips de vídeo siempre quedan pegados, y una transición nunca se come más de un tercio de sus clips. |
| RF-48 | Valida antes de renderizar y explica los problemas en lenguaje llano. |

### 3.6 Render

| ID | El sistema… |
|---|---|
| RF-49 | Renderiza en tres fases: normalizar cada clip, unir, y componer textos y audio. |
| RF-50 | **Cachea cada clip por hash**: cambiar uno solo reprocesa ese. |
| RF-51 | Une los cortes secos sin recodificar. |
| RF-52 | Mezcla el audio desde los archivos originales, colocado al milisegundo. |
| RF-53 | Rasteriza los textos con Pillow, sin depender de `drawtext`. |
| RF-54 | Genera vista previa en baja resolución. |
| RF-55 | Informa del progreso y permite cancelar. |

### 3.7 Exportación

| ID | El sistema… |
|---|---|
| RF-56 | Exporta **MP4** final. |
| RF-57 | Exporta **borrador de CapCut** y lo instala en su carpeta si la encuentra. |
| RF-58 | Exporta **FCPXML**, **EDL**, **proyecto nativo** y **escaleta**. |
| RF-59 | Aplana las transiciones a corte seco sin perder ni un milisegundo de sincronía. |
| RF-60 | Documenta en `AUTOEDIT.md` lo que no viaja, para reponerlo a mano. |

### 3.8 Interfaz

| ID | El sistema… |
|---|---|
| RF-61 | Se sirve en local, sin paso de compilación. |
| RF-62 | Muestra una línea de tiempo con zoom, regla y marcas de pulso. |
| RF-63 | Encaja la vista previa sea cual sea el formato, y ofrece pantalla completa. |
| RF-64 | Ofrece atajos: espacio, `S`, `F`, `Supr`, flechas. |
| RF-65 | Informa de los trabajos en curso con progreso y cancelación. |

---

## 4. Requisitos no funcionales

| ID | Requisito |
|---|---|
| RNF-01 | **Local**: sin servicios externos ni cuentas. |
| RNF-02 | **Instalación mínima**: un `pip install`; FFmpeg viene incluido. |
| RNF-03 | **Multiplataforma**: Windows, macOS y Linux. |
| RNF-04 | **Sin compilación** en la interfaz: HTML, CSS y JS directos. |
| RNF-05 | **Reeditar es barato**: la caché evita reprocesar lo que no cambió. |
| RNF-06 | **Degradación elegante**: sin ffprobe, sin fuentes o sin modelo, sigue funcionando. |
| RNF-07 | **Errores en lenguaje llano**, no volcados de FFmpeg. |
| RNF-08 | **Cobertura de pruebas**: 155 tests; los de render se saltan solos sin FFmpeg. |
| RNF-09 | **Formato de proyecto legible**: un JSON copiable y versionable. |
| RNF-10 | **Seguridad de rutas**: solo se sirven archivos de la carpeta de trabajo. |

---

## 5. Supuestos de diseño

Esta es la sección que decide qué se puede construir encima y qué no.

| ID | Supuesto | Consecuencia |
|---|---|---|
| **SUP-01** | El montaje es **una sola tira de clips encadenados**. | Bloquea capas, superposiciones y pantalla dividida. Está metido en el modelo, en la recolocación, en el planificador y en el render. |
| **SUP-02** | La vista previa es **un MP4 ya renderizado**. | Impide manipular objetos en directo. Toda edición exige regenerar. |
| **SUP-03** | Hay **una música** que se recorta sola al vídeo. | Las pistas añadidas a mano son libres, pero el planificador solo coloca una. |
| **SUP-04** | El prompt **no conoce el material**. | No se puede pedir «usa este audio primero». |
| **SUP-05** | El formato de CapCut es **reconstruido**. | Puede romperse al actualizar CapCut. |
| **SUP-06** | Un clip **ocupa el lienzo entero**. | No hay posición ni tamaño por clip. |

> **SUP-01 y SUP-06 son la misma raíz.** Levantarlos es el trabajo que desbloquea
> casi todo el punto 7.

---

## 6. Limitaciones conocidas

| ID | Limitación |
|---|---|
| LC-01 | Transiciones, filtros y efectos no viajan a CapCut: son recursos internos no documentados. |
| LC-02 | El borrador de CapCut apunta a rutas absolutas; mover el material lo rompe. |
| LC-03 | En FCPXML los textos van como marcadores. |
| LC-04 | El EDL solo transporta cortes y tiempos. |
| LC-05 | Máximo 60 textos compuestos por render. |
| LC-06 | Sin ffprobe, el sondeo es menos preciso en formatos raros. |

---

## 7. Requisitos pendientes

Numerados para poder referirlos. **Ninguno está implementado.**

### 7.1 Audio dirigido por el prompt

| ID | El sistema debe… | Depende de |
|---|---|---|
| RP-01 | Reconocer en el prompt los **nombres de los archivos** del proyecto, tolerando erratas. | SUP-04 |
| RP-02 | Entender el **papel** de cada audio: narración o fondo. | RP-01 |
| RP-03 | Colocar las narraciones **en el orden pedido**, una tras otra. | RP-02 |
| RP-04 | Poner el fondo en otra pista, a volumen bajo. | RP-02 |
| RP-05 | Hacer que **la duración del vídeo la marque la narración**, no la música. | RP-03 |

### 7.2 Capas de vídeo

| ID | El sistema debe… | Depende de |
|---|---|---|
| RP-06 | Admitir **varias pistas de vídeo** superpuestas. | SUP-01 |
| RP-07 | Dar a cada clip **posición, tamaño y giro** en el lienzo. | SUP-06 |
| RP-08 | Colocación **libre** en las capas: sin recolocación en cadena. | RP-06 |
| RP-09 | **Componer** las capas al renderizar. | RP-06, RP-07 |
| RP-10 | Ofrecer **plantillas de pantalla dividida**. | RP-07 |
| RP-11 | Llevar las capas a CapCut y FCPXML. | RP-06 |

### 7.3 Manipulación directa

| ID | El sistema debe… | Depende de |
|---|---|---|
| RP-12 | Mostrar un **recuadro con tiradores** sobre la vista previa al seleccionar un clip. | RP-07 |
| RP-13 | Permitir mover, escalar y girar arrastrando. | RP-12 |

### 7.4 Vista previa

| ID | El sistema debe… | Depende de |
|---|---|---|
| RP-14 | Regenerar la vista previa **sola** tras cada cambio. | — |
| RP-15 | Renderizar solo **el tramo del cursor**, no todo. | — |
| RP-16 | Reproducir en **tiempo real** componiendo en el navegador. | SUP-02, RP-06 |
| RP-17 | Generar **copias ligeras** de cada archivo para el navegador. | RP-16 |

> **RP-16 no dará una imagen idéntica al render.** Serían dos motores distintos.
> El MP4 de FFmpeg sigue siendo la verdad; el directo, una guía fiel.

### 7.5 Comodidades

| ID | El sistema debe… |
|---|---|
| RP-18 | Ofrecer un lanzador de doble clic (`arrancar.bat`). |
| RP-19 | Permitir forzar la orientación del visor. |

---

## 8. Trazabilidad

| Módulo | Requisitos | ¿Le afecta levantar SUP-01? |
|---|---|---|
| `models.py` | RF-05, RF-47 | **Sí** — es donde vive |
| `editing.py` | RF-36…RF-48 | **Sí** — la recolocación |
| `ai/planner.py` | RF-24, RF-29…RF-34 | **Sí** — solo sabe montar una tira |
| `render/renderer.py` | RF-49…RF-55 | **Sí** — pega en vez de componer |
| `web/js/timeline.js` | RF-62 | **Sí** — una fila de vídeo |
| `analysis/` | RF-16…RF-23 | No |
| `ai/prompt.py` | RF-25…RF-28 | No |
| `export/` | RF-56…RF-60 | Parcial |
| `storage.py` | RF-01…RF-15 | No |
| `jobs.py` | RF-23, RF-55 | No |

**Cinco módulos afectados de once.** Los otros seis —análisis, prompt,
almacenamiento, trabajos y buena parte de la exportación— siguen valiendo igual.
Ese es el argumento de por qué conviene cambiar la capa y no reescribir.

---

## 9. Orden propuesto

| Fase | Qué | Por qué |
|---|---|---|
| **1** | RP-01…RP-05 | Es lo que falla hoy, y no toca SUP-01. |
| **2** | RP-14, RP-15 | Quita la espera con poco esfuerzo. |
| **3** | RP-06…RP-09 | Levanta SUP-01. El cambio de fondo. |
| **4** | RP-10…RP-13 | Ya es fácil con la fase 3 hecha. |
| **5** | RP-16, RP-17 | Lo más caro. Solo si sigue haciendo falta. |

Las fases 1 y 2 no dependen de nada. La 3 es la que hay que planificar con
cuidado, y los 155 tests son la red que la hace segura.
