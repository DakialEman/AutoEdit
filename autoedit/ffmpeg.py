"""Capa fina sobre FFmpeg/FFprobe.

Aquí vive todo lo que toca el subproceso: ejecución con progreso, sondeo de
archivos y construcción de filtros reutilizables. El resto del código nunca
llama a FFmpeg directamente.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .config import find_ffmpeg, find_ffprobe

ProgressCb = Callable[[float, str], None]


class FFmpegError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, log: str):
        self.cmd = cmd
        self.returncode = returncode
        self.log = log
        tail = "\n".join(log.strip().splitlines()[-25:])
        super().__init__(f"FFmpeg falló (código {returncode}):\n{tail}")


# --------------------------------------------------------------------------
# Ejecución
# --------------------------------------------------------------------------


def run(
    args: list[str],
    *,
    total_duration: float = 0.0,
    on_progress: Optional[ProgressCb] = None,
    label: str = "",
    timeout: Optional[float] = None,
) -> str:
    """Ejecuta ffmpeg y devuelve su log. Informa del progreso si se pide."""
    cmd = [find_ffmpeg(), "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        errors="replace",
        bufsize=1,
    )
    lines: list[str] = []
    assert proc.stdout is not None

    def _pump() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            lines.append(line)
            if len(lines) > 4000:
                del lines[:2000]
            if on_progress and total_duration > 0:
                t = _parse_time(line)
                if t is not None:
                    on_progress(min(0.999, t / total_duration), label)

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        thread.join(timeout=2)
        raise FFmpegError(cmd, -9, "".join(lines) + "\nTiempo de espera agotado.")
    thread.join(timeout=5)
    log = "".join(lines)
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.returncode, log)
    if on_progress:
        on_progress(1.0, label)
    return log


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")


def _parse_time(line: str) -> Optional[float]:
    m = _TIME_RE.search(line)
    if not m:
        return None
    h, mm, ss = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(ss)


def run_capture(args: list[str], timeout: float = 120) -> str:
    """Ejecuta ffmpeg ignorando el código de salida (para sondeos)."""
    cmd = [find_ffmpeg(), "-hide_banner", "-nostdin", *args]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, errors="replace", timeout=timeout
    )
    return (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------------------
# Sondeo de archivos
# --------------------------------------------------------------------------


@dataclass
class MediaInfo:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    codec: str = ""
    rotation: int = 0

    @property
    def display_width(self) -> int:
        """Ancho tras aplicar la rotación de metadatos."""
        return self.height if self.rotation in (90, 270) else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotation in (90, 270) else self.height


def probe(path: str | Path) -> MediaInfo:
    """Sondea un archivo. Usa ffprobe si está; si no, parsea `ffmpeg -i`."""
    path = str(path)
    ffprobe = find_ffprobe()
    if ffprobe:
        try:
            return _probe_ffprobe(ffprobe, path)
        except Exception:
            pass
    return _probe_ffmpeg(path)


def _probe_ffprobe(ffprobe: str, path: str) -> MediaInfo:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    data = json.loads(out.stdout or "{}")
    info = MediaInfo()
    fmt = data.get("format") or {}
    try:
        info.duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        info.duration = 0.0
    for stream in data.get("streams") or []:
        st = stream.get("codec_type")
        if st == "video" and not info.has_video:
            # Las portadas incrustadas (mjpeg/png adjunto) no son vídeo real.
            if stream.get("disposition", {}).get("attached_pic"):
                continue
            info.has_video = True
            info.width = int(stream.get("width") or 0)
            info.height = int(stream.get("height") or 0)
            info.codec = stream.get("codec_name") or ""
            info.fps = _parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
            info.rotation = _rotation_from_stream(stream)
            if not info.duration:
                try:
                    info.duration = float(stream.get("duration") or 0.0)
                except (TypeError, ValueError):
                    pass
        elif st == "audio" and not info.has_audio:
            info.has_audio = True
            if not info.codec:
                info.codec = stream.get("codec_name") or ""
            if not info.duration:
                try:
                    info.duration = float(stream.get("duration") or 0.0)
                except (TypeError, ValueError):
                    pass
    return info


def _rotation_from_stream(stream: dict) -> int:
    tags = stream.get("tags") or {}
    rot = tags.get("rotate")
    if rot:
        try:
            return int(float(rot)) % 360
        except ValueError:
            pass
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(-float(sd["rotation"])) % 360
            except (TypeError, ValueError):
                pass
    return 0


def _parse_rate(rate: str | None) -> float:
    if not rate:
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")
_VID_RE = re.compile(r"Stream #\d+:\d+.*?: Video: ([a-zA-Z0-9_]+).*?, (\d+)x(\d+)")
_FPS_RE = re.compile(r"(\d+\.?\d*) fps")
_AUD_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: ")
_ROT_RE = re.compile(r"rotate\s*:\s*(-?\d+)")
_DISP_ROT_RE = re.compile(r"displaymatrix: rotation of (-?\d+\.?\d*) degrees")


def _probe_ffmpeg(path: str) -> MediaInfo:
    """Fallback: `ffmpeg -i` escribe la información del archivo en stderr."""
    text = run_capture(["-i", path])
    info = MediaInfo()
    m = _DUR_RE.search(text)
    if m:
        h, mm, ss = m.groups()
        info.duration = int(h) * 3600 + int(mm) * 60 + float(ss)
    v = _VID_RE.search(text)
    if v:
        info.has_video = True
        info.codec, w, h = v.group(1), v.group(2), v.group(3)
        info.width, info.height = int(w), int(h)
        seg = text[v.start(): v.start() + 400]
        f = _FPS_RE.search(seg)
        if f:
            info.fps = float(f.group(1))
    info.has_audio = bool(_AUD_RE.search(text))
    r = _ROT_RE.search(text)
    if r:
        info.rotation = int(r.group(1)) % 360
    else:
        d = _DISP_ROT_RE.search(text)
        if d:
            info.rotation = int(-float(d.group(1))) % 360
    return info


# --------------------------------------------------------------------------
# Utilidades de filtros
# --------------------------------------------------------------------------


def escape_filter_value(value: str) -> str:
    """Escapa un texto para incrustarlo en un filtro (drawtext, etc.)."""
    out = value.replace("\\", "\\\\")
    for ch in ("'", ":", "%", ",", "[", "]", ";"):
        out = out.replace(ch, "\\" + ch)
    return out.replace("\n", "\\n")


def escape_path(path: str | Path) -> str:
    """Escapa una ruta usada como valor dentro de un filtro."""
    s = str(path).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def hex_to_ffmpeg_color(color: str) -> str:
    """`#RRGGBB` o `#RRGGBBAA` -> `0xRRGGBB@alpha` que entiende FFmpeg."""
    c = (color or "#FFFFFF").strip().lstrip("#")
    if len(c) == 8:
        rgb, alpha = c[:6], int(c[6:], 16) / 255.0
        return f"0x{rgb.upper()}@{alpha:.3f}"
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        c = "FFFFFF"
    return f"0x{c.upper()}"


def concat_list_file(paths: Iterable[Path], dest: Path) -> Path:
    """Escribe un fichero para el demuxer `concat`."""
    lines = []
    for p in paths:
        safe = str(p.resolve()).replace("'", r"'\''")
        lines.append(f"file '{safe}'")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def has_filter(name: str) -> bool:
    """Comprueba si el FFmpeg disponible soporta un filtro concreto."""
    key = "_filters_cache"
    cache = globals().get(key)
    if cache is None:
        try:
            cache = run_capture(["-filters"], timeout=30)
        except Exception:
            cache = ""
        globals()[key] = cache
    return bool(re.search(rf"^\s*\S+\s+{re.escape(name)}\s", cache, re.M))
