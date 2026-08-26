# Exportar a CapCut

Notas sobre cómo AutoEdit genera un borrador de CapCut, qué se conserva y qué no,
y por qué.

## El formato

CapCut guarda cada proyecto ("borrador", *draft*) como una **carpeta** con varios
archivos JSON:

| Archivo | Contiene |
|---|---|
| `draft_content.json` | El montaje: lienzo, materiales, pistas y segmentos |
| `draft_meta_info.json` | Metadatos del borrador y la lista de material importado |
| `draft_virtual_store.json` | Estado auxiliar de la interfaz |
| `AUTOEDIT.md` | Lo añade AutoEdit: instrucciones y qué reponer a mano |

**El formato no está documentado por ByteDance.** Lo que hay es conocimiento
reconstruido a partir de borradores reales, y cambia entre versiones de CapCut.
AutoEdit escribe solo campos que se han visto de forma estable, y prefiere
omitir algo antes que inventarlo.

## Dónde va la carpeta

| Sistema | Ruta |
|---|---|
| macOS | `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/` |
| Windows | `%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft\` |

Si AutoEdit encuentra esa carpeta en tu equipo, marca la casilla «Copiarlo
directamente a la carpeta de CapCut» y lo deja puesto por ti. Si no, te da la
carpeta (o un `.zip`) para que la copies a mano.

Cierra CapCut antes de copiar: si está abierto, no relee la lista de borradores.

## Qué se conserva

- El **orden** de los clips y su posición exacta en la línea de tiempo.
- El **tramo** que se usa de cada archivo (`source_timerange`), al microsegundo.
- La **duración** de cada segmento (`target_timerange`).
- La **velocidad** y el **volumen** por clip.
- El **espejado horizontal** y la rotación.
- La **música**, con su punto de entrada y su volumen.
- Los **textos**: contenido, posición, tamaño, color, contorno y alineación.
- El **lienzo**: resolución y fotogramas por segundo.

## Qué no viaja, y por qué

**Transiciones, filtros y efectos de movimiento.** En CapCut son recursos
internos identificados por un `effect_id` y un `resource_id` que forman parte de
su catálogo privado y cambian entre versiones. Un borrador con identificadores
inventados o vacíos, en el mejor de los casos, ignora el efecto; en el peor,
CapCut se niega a abrir el proyecto.

Así que AutoEdit hace dos cosas:

1. **Aplana las transiciones a corte seco** manteniendo los tiempos exactos.
   Concretamente, recorta la cabecera del clip que llevaba transición justo por
   la duración del solape. El resultado dura exactamente lo mismo y sigue
   sincronizado con la música.

2. **Deja constancia** en `AUTOEDIT.md`: qué transición llevaba cada corte, en
   qué segundo, y de cuánto era. Reponerlas en CapCut son dos clics por corte,
   y ya están todos donde tienen que estar.

Lo mismo con la corrección de color: el `AUTOEDIT.md` dice qué look llevaba el
montaje para que apliques el filtro equivalente.

## Los archivos no se copian

El borrador **referencia tus vídeos, fotos y música por su ruta absoluta**. No
duplica gigabytes. La contrapartida: si mueves o renombras el material después de
exportar, CapCut te dirá que faltan archivos. Las rutas usadas quedan listadas en
`AUTOEDIT.md`.

Si te llevas el proyecto a otro ordenador, lleva también el material y ponlo en
la misma ruta, o vuelve a exportar desde AutoEdit en la máquina destino.

## Si no te abre

Por orden de probabilidad:

1. **CapCut estaba abierto** al copiar la carpeta. Ciérralo y vuelve a abrirlo.
2. **La carpeta está en el sitio equivocado.** Tiene que quedar como
   `.../com.lveditor.draft/NombreDelProyecto/draft_content.json`, no un nivel
   más adentro ni más afuera.
3. **Tu versión de CapCut espera otro esquema.** Es el riesgo de un formato no
   público. En ese caso usa **FCPXML**, que sí está documentado, o exporta el
   MP4 y edítalo encima.

## La alternativa fiable

Si tu destino es un editor de escritorio (DaVinci Resolve, Premiere Pro, Final
Cut Pro), usa **FCPXML**: es un formato público y estable, y AutoEdit exporta ahí
la secuencia completa con sus cortes, recortes, velocidades y la pista de música.
Los textos van como marcadores, para no depender de efectos propietarios de cada
programa.
