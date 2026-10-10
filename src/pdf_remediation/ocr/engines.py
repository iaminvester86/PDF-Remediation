"""OCR engines. Both return text lines with pixel boxes and a confidence.

* **RapidOCR** (default): pure Python wheels (Apache-2.0) running PaddleOCR
  models on ONNX Runtime. The models ship inside the wheel, so it works offline
  with no system packages. Install with ``pip install -e ".[ocr]"``.
* **Tesseract** (optional): needs the ``tesseract`` program plus language packs
  and ``pip install pytesseract``. Useful for languages RapidOCR's default
  models do not cover.
"""
from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass

from PIL import Image


@dataclass
class PixelLine:
    text: str
    box: tuple[float, float, float, float]  # left, top, right, bottom in image pixels
    confidence: float


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        from rapidocr import RapidOCR

        self._engine = RapidOCR(params={"Global.log_level": "warning"})  # default logs every model load

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("rapidocr") is not None and importlib.util.find_spec("onnxruntime") is not None

    def recognize(self, image: Image.Image, lang: str = "en") -> list[PixelLine]:
        import numpy as np

        out = self._engine(np.asarray(image.convert("RGB")))
        if out is None or out.boxes is None:
            return []
        lines = []
        for quad, text, score in zip(out.boxes, out.txts, out.scores):
            xs = [float(p[0]) for p in quad]
            ys = [float(p[1]) for p in quad]
            lines.append(PixelLine(str(text), (min(xs), min(ys), max(xs), max(ys)), float(score)))
        return lines


# BCP 47 primary language -> Tesseract traineddata name
_TESSERACT_LANGS = {"en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita", "pt": "por", "nl": "nld",
                    "zh": "chi_sim", "ja": "jpn", "ko": "kor", "ar": "ara", "ru": "rus", "vi": "vie", "hi": "hin"}


class TesseractEngine:
    name = "tesseract"

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("pytesseract") is not None and shutil.which("tesseract") is not None

    def recognize(self, image: Image.Image, lang: str = "en") -> list[PixelLine]:
        import pytesseract

        code = _TESSERACT_LANGS.get(lang.split("-")[0].lower(), "eng")
        data = pytesseract.image_to_data(image, lang=code, output_type=pytesseract.Output.DICT)
        groups: dict[tuple, list[int]] = {}
        for i, word in enumerate(data["text"]):
            if word.strip() and float(data["conf"][i]) >= 0:
                groups.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
        lines = []
        for idxs in groups.values():
            left = min(data["left"][i] for i in idxs)
            top = min(data["top"][i] for i in idxs)
            right = max(data["left"][i] + data["width"][i] for i in idxs)
            bottom = max(data["top"][i] + data["height"][i] for i in idxs)
            conf = sum(float(data["conf"][i]) for i in idxs) / len(idxs) / 100.0
            lines.append(PixelLine(" ".join(data["text"][i] for i in idxs), (left, top, right, bottom), conf))
        return lines


ENGINES = {"rapidocr": RapidOcrEngine, "tesseract": TesseractEngine}
_cache: dict[str, object] = {}


def available_engines() -> list[str]:
    return [name for name, cls in ENGINES.items() if cls.available()]


def get_engine(preference: str = "auto"):
    """The requested engine, or the first available one for "auto". None if none is installed."""
    names = [preference] if preference in ENGINES else list(ENGINES)
    for name in names:
        cls = ENGINES[name]
        if cls.available():
            if name not in _cache:  # model loading is slow: keep one engine per process
                _cache[name] = cls()
            return _cache[name]
    return None
