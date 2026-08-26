"""Exportación a un proyecto editable de CapCut.

CapCut guarda cada proyecto ("borrador") como una carpeta con varios JSON. El
formato **no es público**: está reconstruido a partir de borradores reales, y
CapCut lo cambia entre versiones. Por eso este exportador:

* escribe solo campos que se han visto de forma estable en varias versiones;
* **no inventa identificadores de recursos** que no conoce (transiciones y
  efectos son recursos internos de CapCut). En vez de generar un borrador que
  CapCut rechazaría, aplana las transiciones a corte seco y deja anotado en
  `AUTOEDIT.md` qué transición llevaba cada corte, para reponerlas en dos clics;
* deja la línea de tiempo **exacta**: orden, recortes, velocidades, volúmenes,
  música y textos caen en el fotograma que les toca.

Lo que sí se conserva siempre: los cortes, los tramos usados de cada archivo,
la música sincronizada y los textos.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..models import Project, TextClip, Timeline
from .common import FlatClip, FlatTimeline, flatten, to_microseconds

CAPCUT_VERSION = 360000
CAPCUT_NEW_VERSION = "110.0.0"


def _uid() -> str:
    return str(uuid.uuid4()).upper()


# --------------------------------------------------------------------------
# Localización de la carpeta de borradores
# --------------------------------------------------------------------------


def candidate_draft_dirs() -> list[Path]:
    """Rutas donde CapCut/CapCut Pro suele guardar sus borradores."""
    home = Path.home()
    import os

    candidates = [
        home / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
        home / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates += [
            Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            Path(local) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
        ]
    candidates.append(home / "Documents" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft")
    return candidates


def find_capcut_drafts_dir() -> Optional[Path]:
    for path in candidate_draft_dirs():
        if path.is_dir():
            return path
    return None


# --------------------------------------------------------------------------
# Materiales
# --------------------------------------------------------------------------


@dataclass
class MaterialRefs:
    """Identificadores auxiliares que CapCut exige por cada segmento."""

    speed: str
    canvas: str
    sound_mapping: str
    vocal_separation: str

    def as_list(self) -> list[str]:
        return [self.speed, self.canvas, self.sound_mapping, self.vocal_separation]


def _video_material(clip: FlatClip) -> dict:
    asset = clip.asset
    is_photo = asset.kind == "image"
    duration = to_microseconds(asset.duration if asset.duration > 0 else 10.0)
    return {
        "audio_fade": None,
        "category_id": "",
        "category_name": "local",
        "check_flag": 62978047,
        "crop": {
            "lower_left_x": 0.0,
            "lower_left_y": 1.0,
            "lower_right_x": 1.0,
            "lower_right_y": 1.0,
            "upper_left_x": 0.0,
            "upper_left_y": 0.0,
            "upper_right_x": 1.0,
            "upper_right_y": 0.0,
        },
        "crop_ratio": "free",
        "crop_scale": 1.0,
        "duration": duration,
        "extra_type_option": 0,
        "formula_id": "",
        "freeze": None,
        "has_audio": bool(asset.has_audio),
        "height": asset.height or 1080,
        "id": _uid(),
        "intensifies_audio_path": "",
        "intensifies_path": "",
        "is_ai_generate_content": False,
        "is_copyright": False,
        "is_text_edit_overdub": False,
        "is_unified_beauty_mode": False,
        "local_id": "",
        "local_material_id": "",
        "material_id": "",
        "material_name": asset.name,
        "material_url": "",
        "matting": {"flag": 0, "has_use_quick_brush": False, "has_use_quick_eraser": False,
                    "interactiveTime": [], "path": "", "strokes": []},
        "media_path": "",
        "object_locked": None,
        "origin_material_id": "",
        "path": str(Path(asset.path).resolve()),
        "picture_from": "none",
        "picture_set_category_id": "",
        "picture_set_category_name": "",
        "request_id": "",
        "reverse_intensifies_path": "",
        "reverse_path": "",
        "smart_motion": None,
        "source": 0,
        "source_platform": 0,
        "stable": None,
        "team_id": "",
        "type": "photo" if is_photo else "video",
        "video_algorithm": {
            "algorithms": [],
            "complement_frame_config": None,
            "deflicker": None,
            "gameplay_configs": [],
            "motion_blur_config": None,
            "noise_reduction": None,
            "path": "",
            "quality_enhance": None,
            "time_range": None,
        },
        "width": asset.width or 1920,
    }


def _audio_material(clip: FlatClip) -> dict:
    asset = clip.asset
    return {
        "app_id": 0,
        "category_id": "",
        "category_name": "local",
        "check_flag": 1,
        "duration": to_microseconds(asset.duration),
        "effect_id": "",
        "formula_id": "",
        "id": _uid(),
        "intensifies_path": "",
        "is_ai_clone_tone": False,
        "is_text_edit_overdub": False,
        "is_ugc": False,
        "local_material_id": "",
        "music_id": "",
        "name": asset.name,
        "path": str(Path(asset.path).resolve()),
        "query": "",
        "request_id": "",
        "resource_id": "",
        "search_id": "",
        "source_platform": 0,
        "team_id": "",
        "text_id": "",
        "tone_category_id": "",
        "tone_category_name": "",
        "tone_effect_id": "",
        "tone_effect_name": "",
        "tone_platform": "",
        "tone_second_category_id": "",
        "tone_second_category_name": "",
        "tone_speaker": "",
        "tone_type": "",
        "type": "extract_music",
        "wave_points": [],
    }


def _speed_material(speed: float) -> dict:
    return {"curve_speed": None, "id": _uid(), "mode": 0, "speed": round(speed, 6), "type": "speed"}


def _canvas_material() -> dict:
    return {"album_image": "", "blur": 0.0, "color": "", "id": _uid(), "image": "",
            "image_id": "", "image_name": "", "source_platform": 0, "team_id": "",
            "type": "canvas_color"}


def _sound_mapping_material() -> dict:
    return {"audio_channel_mapping": 0, "id": _uid(), "is_config_open": False, "type": "none"}


def _vocal_separation_material() -> dict:
    return {"choice": 0, "id": _uid(), "production_path": "", "removed_sounds": [],
            "time_range": None, "type": "vocal_separation"}


def _hex_to_rgb(color: str) -> list[float]:
    c = (color or "#FFFFFF").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) < 6:
        c = "FFFFFF"
    return [round(int(c[i: i + 2], 16) / 255.0, 4) for i in (0, 2, 4)]


_ALIGN = {"left": 0, "center": 1, "right": 2}


def _text_material(text: TextClip, canvas_height: int) -> dict:
    content = text.text.upper() if text.style.uppercase else text.text
    rgb = _hex_to_rgb(text.style.color)
    # CapCut mide la fuente en su propia escala; 15 equivale al tamaño estándar
    # sobre un lienzo de 1080 px de alto.
    font_size = round(max(4.0, text.style.size * 15.0 / 64.0), 2)
    rich = {
        "text": content,
        "styles": [
            {
                "fill": {"content": {"render_type": "solid",
                                     "solid": {"alpha": 1.0, "color": rgb}}},
                "font": {"id": "", "path": ""},
                "range": [0, len(content)],
                "size": font_size,
                "useLetterColor": True,
            }
        ],
    }
    stroke_rgb = _hex_to_rgb(text.style.stroke_color)
    return {
        "add_type": 0,
        "alignment": _ALIGN.get(text.style.align, 1),
        "background_alpha": 1.0 if text.style.box else 0.0,
        "background_color": "#000000" if text.style.box else "",
        "background_height": 0.14,
        "background_horizontal_offset": 0.0,
        "background_round_radius": 0.2 if text.style.box else 0.0,
        "background_style": 1 if text.style.box else 0,
        "background_vertical_offset": 0.0,
        "background_width": 0.14,
        "bold_width": 0.0,
        "border_alpha": 1.0,
        "border_color": "#%02X%02X%02X" % tuple(int(v * 255) for v in stroke_rgb),
        "border_width": round(text.style.stroke * 0.06, 3),
        "check_flag": 7,
        "content": json.dumps(rich, ensure_ascii=False),
        "font_category_id": "",
        "font_category_name": "",
        "font_id": "",
        "font_name": "",
        "font_path": text.style.font or "",
        "font_resource_id": "",
        "font_size": font_size,
        "font_source_platform": 0,
        "font_team_id": "",
        "font_title": "none",
        "font_url": "",
        "fixed_height": -1.0,
        "fixed_width": -1.0,
        "force_apply_line_max_width": False,
        "global_alpha": 1.0,
        "has_shadow": bool(text.style.shadow),
        "id": _uid(),
        "initial_scale": 1.0,
        "is_rich_text": False,
        "italic_degree": 0,
        "ktv_color": "",
        "language": "",
        "layer_weight": 1,
        "letter_spacing": 0.0,
        "line_feed": 1,
        "line_max_width": 0.82,
        "line_spacing": 0.02,
        "multi_language_current": "none",
        "name": "",
        "original_size": [],
        "preset_category": "",
        "preset_category_id": "",
        "preset_has_set_alignment": False,
        "preset_id": "",
        "preset_index": 0,
        "preset_name": "",
        "recognize_task_id": "",
        "recognize_type": 0,
        "relevance_segment": [],
        "shadow_alpha": 0.8 if text.style.shadow else 0.0,
        "shadow_angle": -45.0,
        "shadow_color": "#000000",
        "shadow_distance": 5.0,
        "shadow_point": {"x": 0.6, "y": -0.6},
        "shadow_smoothing": 1.0,
        "shape_clip_x": False,
        "shape_clip_y": False,
        "style_name": "",
        "sub_type": 0,
        "text_alpha": 1.0,
        "text_color": "#%02X%02X%02X" % tuple(int(v * 255) for v in rgb),
        "text_curve": None,
        "text_preset_resource_id": "",
        "text_size": 30,
        "text_to_audio_ids": [],
        "tts_auto_update": False,
        "type": "text",
        "typesetting": 0,
        "underline": False,
        "underline_offset": 0.22,
        "underline_width": 0.05,
        "use_effect_default_color": True,
        "words": {"end_time": [], "start_time": [], "text": []},
    }


# --------------------------------------------------------------------------
# Segmentos
# --------------------------------------------------------------------------


def _base_segment(material_id: str, refs: list[str], start: float, duration: float,
                  source_start: float, source_duration: float) -> dict:
    return {
        "caption_info": None,
        "cartoon": False,
        "clip": {
            "alpha": 1.0,
            "flip": {"horizontal": False, "vertical": False},
            "rotation": 0.0,
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": 0.0},
        },
        "common_keyframes": [],
        "enable_adjust": True,
        "enable_color_correct_adjust": False,
        "enable_color_curves": True,
        "enable_color_match_adjust": False,
        "enable_color_wheels": True,
        "enable_lut": True,
        "enable_smart_color_adjust": False,
        "extra_material_refs": refs,
        "group_id": "",
        "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
        "id": _uid(),
        "intensifies_audio": False,
        "is_placeholder": False,
        "is_tone_modify": False,
        "keyframe_refs": [],
        "last_nonzero_volume": 1.0,
        "material_id": material_id,
        "render_index": 0,
        "responsive_layout": {
            "enable": False,
            "horizontal_pos_layout": 0,
            "size_layout": 0,
            "target_follow": "",
            "vertical_pos_layout": 0,
        },
        "reverse": False,
        "source_timerange": {
            "duration": to_microseconds(source_duration),
            "start": to_microseconds(source_start),
        },
        "speed": 1.0,
        "target_timerange": {
            "duration": to_microseconds(duration),
            "start": to_microseconds(start),
        },
        "template_id": "",
        "template_scene": "default",
        "track_attribute": 0,
        "track_render_index": 0,
        "uniform_scale": {"on": True, "value": 1.0},
        "visible": True,
        "volume": 1.0,
    }


def _video_segment(clip: FlatClip, material_id: str, refs: list[str], index: int) -> dict:
    segment = _base_segment(
        material_id, refs, clip.timeline_start, clip.timeline_duration,
        clip.source_start, clip.source_duration,
    )
    segment["speed"] = round(clip.speed, 6)
    segment["volume"] = round(max(0.0, min(1.0, clip.volume)), 4)
    segment["last_nonzero_volume"] = segment["volume"] or 1.0
    segment["render_index"] = index
    segment["clip"]["flip"]["horizontal"] = bool(clip.mirror)
    segment["clip"]["rotation"] = float(clip.rotation)
    return segment


def _audio_segment(clip: FlatClip, material_id: str, refs: list[str]) -> dict:
    segment = _base_segment(
        material_id, refs, clip.timeline_start, clip.timeline_duration,
        clip.source_start, clip.source_duration,
    )
    segment["speed"] = round(clip.speed, 6)
    segment["volume"] = round(max(0.0, min(1.0, clip.volume)), 4)
    segment["last_nonzero_volume"] = segment["volume"] or 1.0
    return segment


def _text_segment(text: TextClip, material_id: str, refs: list[str], index: int) -> dict:
    segment = _base_segment(material_id, refs, text.start, text.duration, 0.0, text.duration)
    # CapCut sitúa por el centro del lienzo: x,y en [-1, 1] e y positivo hacia arriba.
    segment["clip"]["transform"] = {
        "x": round((text.style.x - 0.5) * 2, 4),
        "y": round((0.5 - text.style.y) * 2, 4),
    }
    segment["render_index"] = 14000 + index
    segment["track_render_index"] = 1
    return segment


# --------------------------------------------------------------------------
# Documento completo
# --------------------------------------------------------------------------


def build_draft_content(flat: FlatTimeline, name: str) -> dict:
    materials: dict[str, list] = {
        "ai_translates": [], "audio_balances": [], "audio_effects": [], "audio_fades": [],
        "audio_track_indexes": [], "audios": [], "beats": [], "canvases": [], "chromas": [],
        "color_curves": [], "digital_humans": [], "drafts": [], "effects": [], "filters": [],
        "flowers": [], "green_screens": [], "handwrites": [], "hsl": [], "images": [],
        "log_color_wheels": [], "loudnesses": [], "manual_deformations": [],
        "material_animations": [], "material_colors": [], "multi_language_refs": [],
        "placeholders": [], "plugin_effects": [], "primary_color_wheels": [],
        "realtime_denoises": [], "shapes": [], "smart_crops": [], "smart_relights": [],
        "sound_channel_mappings": [], "speeds": [], "stickers": [], "tail_leaders": [],
        "text_templates": [], "texts": [], "time_marks": [], "transitions": [],
        "video_effects": [], "video_trackings": [], "videos": [], "vocal_beautifys": [],
        "vocal_separations": [],
    }

    video_segments: list[dict] = []
    for index, clip in enumerate(flat.video):
        material = _video_material(clip)
        materials["videos"].append(material)
        refs = _new_refs(materials, clip.speed)
        video_segments.append(_video_segment(clip, material["id"], refs, index))

    audio_segments: list[dict] = []
    for clip in flat.audio:
        material = _audio_material(clip)
        materials["audios"].append(material)
        refs = _new_refs(materials, clip.speed, canvas=False)
        audio_segments.append(_audio_segment(clip, material["id"], refs))

    text_segments: list[dict] = []
    for index, text in enumerate(flat.texts):
        material = _text_material(text, flat.height)
        materials["texts"].append(material)
        refs = _new_refs(materials, 1.0, canvas=False)
        text_segments.append(_text_segment(text, material["id"], refs, index))

    tracks: list[dict] = [
        {"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": True,
         "name": "", "segments": video_segments, "type": "video"}
    ]
    if audio_segments:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": True,
                       "name": "", "segments": audio_segments, "type": "audio"})
    if text_segments:
        tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": True,
                       "name": "", "segments": text_segments, "type": "text"})

    now = int(time.time() * 1_000_000)
    return {
        "canvas_config": {"height": flat.height, "ratio": "original", "width": flat.width},
        "color_space": 0,
        "config": {
            "adjust_max_index": 1,
            "attachment_info": [],
            "combination_max_index": 1,
            "export_range": None,
            "extract_audio_last_index": 1,
            "lyrics_recognition_id": "",
            "lyrics_sync": True,
            "lyrics_taskinfo": [],
            "maintrack_adsorb": True,
            "material_save_mode": 0,
            "multi_language_current": "none",
            "multi_language_list": [],
            "multi_language_main": "none",
            "multi_language_mode": "none",
            "original_sound_last_index": 1,
            "record_audio_last_index": 1,
            "sticker_max_index": 1,
            "subtitle_keywords_config": None,
            "subtitle_recognition_id": "",
            "subtitle_sync": True,
            "subtitle_taskinfo": [],
            "system_font_list": [],
            "video_mute": False,
            "zoom_info_params": None,
        },
        "cover": None,
        "create_time": 0,
        "duration": to_microseconds(flat.duration),
        "extra_info": None,
        "fps": float(flat.fps),
        "free_render_index_mode_on": False,
        "group_container": None,
        "id": _uid(),
        "keyframe_graph_list": [],
        "keyframes": {"adjusts": [], "audios": [], "effects": [], "filters": [],
                      "handwrites": [], "stickers": [], "texts": [], "videos": []},
        "last_modified_platform": _platform_info(),
        "materials": materials,
        "mutable_config": None,
        "name": name,
        "new_version": CAPCUT_NEW_VERSION,
        "platform": _platform_info(),
        "relationships": [],
        "render_index_track_mode_on": True,
        "retouch_cover": None,
        "source": "default",
        "static_cover_image_path": "",
        "time_marks": None,
        "tracks": tracks,
        "update_time": now,
        "version": CAPCUT_VERSION,
    }


def _new_refs(materials: dict[str, list], speed: float, canvas: bool = True) -> list[str]:
    speed_material = _speed_material(speed)
    materials["speeds"].append(speed_material)
    mapping = _sound_mapping_material()
    materials["sound_channel_mappings"].append(mapping)
    vocal = _vocal_separation_material()
    materials["vocal_separations"].append(vocal)
    refs = [speed_material["id"]]
    if canvas:
        canvas_material = _canvas_material()
        materials["canvases"].append(canvas_material)
        refs.append(canvas_material["id"])
    refs += [mapping["id"], vocal["id"]]
    return refs


def _platform_info() -> dict:
    import platform as _p

    system = {"Darwin": "mac", "Windows": "windows"}.get(_p.system(), "linux")
    return {
        "app_id": 3704,
        "app_source": "lv",
        "app_version": CAPCUT_NEW_VERSION,
        "device_id": "",
        "hard_disk_id": "",
        "mac_address": "",
        "os": system,
        "os_version": _p.release(),
    }


def build_draft_meta(flat: FlatTimeline, name: str, folder: Path, draft_id: str) -> dict:
    now_s = int(time.time())
    now_us = now_s * 1_000_000
    material_metas = []
    for asset in flat.assets:
        metetype = {"video": "video", "image": "photo", "audio": "music"}.get(asset.kind, "video")
        material_metas.append({
            "create_time": now_s,
            "duration": to_microseconds(asset.duration),
            "extra_info": asset.name,
            "file_Path": str(Path(asset.path).resolve()),
            "height": asset.height or 0,
            "id": _uid(),
            "import_time": now_s,
            "import_time_ms": now_us,
            "item_source": 1,
            "md5": "",
            "metetype": metetype,
            "roughcut_time_range": {"duration": to_microseconds(asset.duration), "start": 0},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0,
            "width": asset.width or 0,
        })

    return {
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_materials": [],
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "draft_cover.jpg",
        "draft_deeplink_url": "",
        "draft_enterprise_info": {
            "draft_enterprise_extra": "",
            "draft_enterprise_id": "",
            "draft_enterprise_name": "",
            "enterprise_material": [],
        },
        "draft_fold_path": str(folder.resolve()),
        "draft_id": draft_id,
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_materials": [
            {"type": 0, "value": material_metas},
            {"type": 1, "value": []},
            {"type": 2, "value": []},
            {"type": 3, "value": []},
            {"type": 6, "value": []},
            {"type": 7, "value": []},
            {"type": 8, "value": []},
        ],
        "draft_materials_copied_info": [],
        "draft_name": name,
        "draft_new_version": "",
        "draft_removable_storage_device": "",
        "draft_root_path": str(folder.parent.resolve()),
        "draft_segment_backup_info": [],
        "draft_timeline_materials_size_": 0,
        "draft_type": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": to_microseconds(flat.duration),
    }


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------


README_TEMPLATE = """# {name} — borrador de CapCut generado por AutoEdit

## Cómo abrirlo

1. Cierra CapCut si lo tienes abierto.
2. Copia **esta carpeta entera** dentro de la carpeta de borradores de CapCut:
   - macOS: `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/`
   - Windows: `%LOCALAPPDATA%\\CapCut\\User Data\\Projects\\com.lveditor.draft\\`
3. Abre CapCut. El proyecto aparecerá en la lista de borradores.

> Si AutoEdit encontró tu carpeta de CapCut, ya lo ha copiado por ti y este
> paso te lo puedes saltar.

## Importante sobre los archivos

El borrador **apunta a los archivos originales** por su ruta absoluta; no los
copia. Si mueves o renombras tus vídeos, fotos o música, CapCut los dará por
perdidos. Rutas usadas:

{paths}

## Qué se ha conservado

- Orden de los clips, tramo usado de cada uno y duración exacta.
- Velocidad y volumen por clip.
- Música, con su punto de entrada y su volumen.
- Textos, con posición, tamaño y color aproximados.

## Qué tendrás que reponer a mano

El formato de borrador de CapCut no es público y sus transiciones, filtros y
efectos son recursos internos identificados por códigos que cambian entre
versiones. AutoEdit no los inventa: prefiere darte un proyecto que abre bien a
uno que CapCut rechace.

- **Corrección de color:** el montaje usaba «{grade}».
- **Efectos de movimiento** por clip (zoom, paneo…).
{transitions}

Todo eso son dos clics en CapCut, y los cortes ya están donde tienen que estar.

---
Generado por AutoEdit el {date}.
"""


def _readme(flat: FlatTimeline, name: str, project: Project) -> str:
    paths = "\n".join(f"- `{Path(a.path).resolve()}`" for a in flat.assets) or "- (ninguno)"
    transitions = [
        f"  - Corte {i + 1} (en {c.timeline_start:.2f}s): «{c.original_transition}» "
        f"de {c.original_transition_duration:.2f}s"
        for i, c in enumerate(flat.video)
        if c.original_transition != "cut" and c.original_transition_duration > 0
    ]
    if transitions:
        block = "- **Transiciones** que llevaba el montaje:\n" + "\n".join(transitions)
    else:
        block = "- No había transiciones: todos los cortes eran secos."
    return README_TEMPLATE.format(
        name=name,
        paths=paths,
        grade=project.style.grade,
        transitions=block,
        date=time.strftime("%d/%m/%Y %H:%M"),
    )


def export_capcut(
    project: Project,
    dest_dir: Path,
    timeline: Optional[Timeline] = None,
    install: bool = False,
) -> dict:
    """Escribe el borrador de CapCut. Devuelve un informe para la interfaz."""
    flat = flatten(project, timeline)
    if not flat.video:
        raise ValueError("No hay nada que exportar: la línea de tiempo está vacía.")

    safe_name = "".join(c for c in project.name if c.isalnum() or c in " -_()").strip()
    safe_name = safe_name or "AutoEdit"
    folder = dest_dir / safe_name
    n = 1
    while folder.exists():
        folder = dest_dir / f"{safe_name}_{n}"
        n += 1
    folder.mkdir(parents=True)

    draft_id = _uid()
    content = build_draft_content(flat, safe_name)
    meta = build_draft_meta(flat, safe_name, folder, draft_id)

    (folder / "draft_content.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2), "utf-8"
    )
    (folder / "draft_meta_info.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), "utf-8"
    )
    (folder / "draft_virtual_store.json").write_text(
        json.dumps(
            {"draft_materials": [], "draft_virtual_store": [
                {"type": 0, "value": []}, {"type": 1, "value": []}, {"type": 2, "value": []}
            ]},
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )
    (folder / "AUTOEDIT.md").write_text(_readme(flat, safe_name, project), "utf-8")

    report = {
        "folder": str(folder),
        "clips": len(flat.video),
        "audio_clips": len(flat.audio),
        "texts": len(flat.texts),
        "duration": flat.duration,
        "notes": list(flat.notes),
        "installed_to": None,
        "missing": [a.path for a in flat.assets if not Path(a.path).exists()],
    }

    if install:
        drafts = find_capcut_drafts_dir()
        if drafts:
            target = drafts / folder.name
            m = 1
            while target.exists():
                target = drafts / f"{folder.name}_{m}"
                m += 1
            shutil.copytree(folder, target)
            # `draft_fold_path` debe apuntar a donde vive de verdad el borrador.
            meta["draft_fold_path"] = str(target.resolve())
            meta["draft_root_path"] = str(target.parent.resolve())
            (target / "draft_meta_info.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), "utf-8"
            )
            report["installed_to"] = str(target)
        else:
            report["notes"].append(
                "No se ha encontrado la carpeta de borradores de CapCut en este equipo; "
                "copia la carpeta a mano siguiendo las instrucciones de AUTOEDIT.md."
            )
    return report


def export_capcut_zip(project: Project, dest: Path, timeline: Optional[Timeline] = None) -> dict:
    """Igual que `export_capcut`, pero empaquetado en un .zip."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        report = export_capcut(project, Path(tmp), timeline, install=False)
        folder = Path(report["folder"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in folder.rglob("*"):
                if path.is_file():
                    zf.write(path, Path(folder.name) / path.relative_to(folder))
    report["folder"] = str(dest)
    report["zip"] = str(dest)
    return report
