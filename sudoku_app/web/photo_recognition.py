"""Riconoscimento locale di Sudoku fotografati.

La pipeline non dipende da servizi esterni:

1. individua il quadrilatero della griglia;
2. corregge la prospettiva;
3. separa le 81 celle e isola i glifi;
4. classifica le cifre con HOG e un insieme di esempi sintetici;
5. ripara soltanto i conflitti Sudoku evidenti, marcandoli per la revisione.

Il risultato rimane intenzionalmente revisionabile: nessun OCR fotografico è
abbastanza affidabile da salvare direttamente un puzzle senza conferma umana.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps,
    UnidentifiedImageError,
)


RECOGNITION_VERSION = "opencv-hog-synthetic-v3"
DARK_GRID_MEAN_THRESHOLD = 115.0
NEGATIVE_CONFIDENCE_MARGIN = 0.03
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_SIDE = 12000
PROCESSING_MAX_SIDE = 4000
RECTIFIED_SIZE = 900
LOW_CONFIDENCE_THRESHOLD = 0.72


class PhotoRecognitionError(ValueError):
    """Errore leggibile prodotto dalla pipeline fotografica."""


def _normalise_glyph(glyph):
    """Centra un glifo binario in un'immagine 28x28."""
    points = cv2.findNonZero(glyph)

    if points is None:
        return np.zeros((28, 28), dtype=np.uint8)

    x, y, width, height = cv2.boundingRect(points)
    cropped = glyph[y:y + height, x:x + width]
    target = 20
    scale = min(target / max(width, 1), target / max(height, 1))
    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    resized = cv2.resize(
        cropped,
        (resized_width, resized_height),
        interpolation=(
            cv2.INTER_AREA
            if scale < 1
            else cv2.INTER_CUBIC
        ),
    )
    normalised = np.zeros((28, 28), dtype=np.uint8)
    left = (28 - resized_width) // 2
    top = (28 - resized_height) // 2
    normalised[
        top:top + resized_height,
        left:left + resized_width,
    ] = resized

    moments = cv2.moments(normalised)

    if moments["m00"]:
        center_x = moments["m10"] / moments["m00"]
        center_y = moments["m01"] / moments["m00"]
        translation = np.float32([
            [1, 0, 13.5 - center_x],
            [0, 1, 13.5 - center_y],
        ])
        normalised = cv2.warpAffine(
            normalised,
            translation,
            (28, 28),
            flags=cv2.INTER_LINEAR,
            borderValue=0,
        )

    return normalised


@lru_cache(maxsize=1)
def _hog_descriptor():
    return cv2.HOGDescriptor(
        (28, 28),
        (14, 14),
        (7, 7),
        (7, 7),
        9,
    )


def _glyph_feature(glyph):
    feature = _hog_descriptor().compute(glyph).reshape(-1)
    norm = np.linalg.norm(feature)

    if norm:
        feature = feature / norm

    return feature.astype(np.float32)


@lru_cache(maxsize=1)
def _synthetic_training_set():
    """Costruisce esempi leggeri usando tutte le famiglie Hershey di OpenCV."""
    fonts = (
        cv2.FONT_HERSHEY_SIMPLEX,
        cv2.FONT_HERSHEY_PLAIN,
        cv2.FONT_HERSHEY_DUPLEX,
        cv2.FONT_HERSHEY_COMPLEX,
        cv2.FONT_HERSHEY_TRIPLEX,
        cv2.FONT_HERSHEY_COMPLEX_SMALL,
    )
    features = []
    labels = []

    for digit in range(1, 10):
        text = str(digit)

        for font in fonts:
            for thickness in (1, 2, 3):
                for angle in (-7, -3, 0, 3, 7):
                    canvas = np.zeros((64, 64), dtype=np.uint8)
                    scale = 1.75 if font != cv2.FONT_HERSHEY_PLAIN else 2.4
                    (width, height), baseline = cv2.getTextSize(
                        text,
                        font,
                        scale,
                        thickness,
                    )
                    origin = (
                        (64 - width) // 2,
                        (64 + height - baseline) // 2,
                    )
                    cv2.putText(
                        canvas,
                        text,
                        origin,
                        font,
                        scale,
                        255,
                        thickness,
                        cv2.LINE_AA,
                    )
                    rotation = cv2.getRotationMatrix2D((31.5, 31.5), angle, 1)
                    rotated = cv2.warpAffine(
                        canvas,
                        rotation,
                        (64, 64),
                        flags=cv2.INTER_LINEAR,
                        borderValue=0,
                    )

                    for shear in (-0.06, 0.0, 0.06):
                        transform = np.float32([
                            [1, shear, -shear * 32],
                            [0, 1, 0],
                        ])
                        variant = cv2.warpAffine(
                            rotated,
                            transform,
                            (64, 64),
                            flags=cv2.INTER_LINEAR,
                            borderValue=0,
                        )
                        glyph = _normalise_glyph(variant)
                        features.append(_glyph_feature(glyph))
                        labels.append(digit)

    font_paths = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("C:/Windows/Fonts/times.ttf"),
        Path("C:/Windows/Fonts/verdana.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("C:/Windows/Fonts/georgia.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf"),
    )

    for font_path in font_paths:
        if not font_path.exists():
            continue

        try:
            font = ImageFont.truetype(str(font_path), size=48)
        except OSError:
            continue

        for digit in range(1, 10):
            text = str(digit)

            for stroke_width in (0, 1):
                canvas = Image.new("L", (64, 64), 0)
                draw = ImageDraw.Draw(canvas)
                box = draw.textbbox(
                    (0, 0),
                    text,
                    font=font,
                    stroke_width=stroke_width,
                )
                width = box[2] - box[0]
                height = box[3] - box[1]
                position = (
                    (64 - width) / 2 - box[0],
                    (64 - height) / 2 - box[1],
                )
                draw.text(
                    position,
                    text,
                    fill=255,
                    font=font,
                    stroke_width=stroke_width,
                    stroke_fill=255,
                )
                base = np.asarray(canvas)

                for angle in (-6, -3, 0, 3, 6):
                    rotation = cv2.getRotationMatrix2D(
                        (31.5, 31.5),
                        angle,
                        1,
                    )
                    variant = cv2.warpAffine(
                        base,
                        rotation,
                        (64, 64),
                        flags=cv2.INTER_LINEAR,
                        borderValue=0,
                    )
                    glyph = _normalise_glyph(variant)
                    features.append(_glyph_feature(glyph))
                    labels.append(digit)

    return (
        np.asarray(features, dtype=np.float32),
        np.asarray(labels, dtype=np.int8),
    )


def _classify_glyph(glyph):
    feature = _glyph_feature(glyph)
    training, labels = _synthetic_training_set()
    squared_distances = np.mean(
        np.square(training - feature),
        axis=1,
    )
    digit_distances = []

    for digit in range(1, 10):
        distances = np.sort(squared_distances[labels == digit])
        digit_distances.append(float(np.mean(distances[:4])))

    digit_distances = np.asarray(digit_distances, dtype=float)
    order = np.argsort(digit_distances)
    best = float(digit_distances[order[0]])
    second = float(digit_distances[order[1]])
    temperature = max((second - best) * 1.8, second * 0.08, 1e-6)
    likelihood = np.exp(
        -np.clip((digit_distances - best) / temperature, 0, 40)
    )
    probabilities = likelihood / likelihood.sum()

    candidates = [
        {
            "digit": int(index + 1),
            "confidence": round(float(probabilities[index]), 4),
        }
        for index in order[:3]
    ]
    relative_margin = max(0.0, (second - best) / max(second, 1e-9))
    confidence = 0.45 + 0.54 * (1 - math.exp(-4.2 * relative_margin))
    confidence = min(0.99, max(float(probabilities[order[0]]), confidence))

    return int(order[0] + 1), round(confidence, 4), candidates


def _load_image(image_bytes):
    if not image_bytes:
        raise PhotoRecognitionError("Il file caricato è vuoto.")

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise PhotoRecognitionError(
            "La foto supera il limite di 12 MB."
        )

    try:
        with Image.open(BytesIO(image_bytes)) as source:
            if max(source.size) > MAX_IMAGE_SIDE:
                raise PhotoRecognitionError(
                    "La foto è troppo grande: il lato massimo ammesso è "
                    "12000 px."
                )
            source_size = {
                "width": int(source.size[0]),
                "height": int(source.size[1]),
            }
            source.draft(
                "RGB",
                (PROCESSING_MAX_SIDE, PROCESSING_MAX_SIDE),
            )
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail(
                (PROCESSING_MAX_SIDE, PROCESSING_MAX_SIDE),
                Image.Resampling.LANCZOS,
            )
    except PhotoRecognitionError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ) as error:
        raise PhotoRecognitionError(
            "Il file non è un'immagine JPEG, PNG o WebP valida."
        ) from error

    rgb = np.asarray(image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), source_size


def _order_corners(points):
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def _periodic_grid_score(binary, corners):
    """Misura la presenza di linee regolari 9x9 dentro un quadrilatero."""
    sample_size = 450
    destination = np.float32([
        [0, 0],
        [sample_size - 1, 0],
        [sample_size - 1, sample_size - 1],
        [0, sample_size - 1],
    ])
    transform = cv2.getPerspectiveTransform(
        corners.astype(np.float32),
        destination,
    )
    warped = cv2.warpPerspective(
        binary,
        transform,
        (sample_size, sample_size),
        flags=cv2.INTER_LINEAR,
    )
    vertical = warped.mean(axis=0)
    horizontal = warped.mean(axis=1)
    expected = [
        int(round(index * (sample_size - 1) / 9))
        for index in range(10)
    ]

    def line_strength(projection):
        peaks = []

        for position in expected:
            start = max(0, position - 4)
            stop = min(sample_size, position + 5)
            peaks.append(float(np.max(projection[start:stop])))

        baseline = float(np.median(projection))
        return max(0.0, (float(np.mean(peaks)) - baseline) / 255)

    return (
        line_strength(vertical) + line_strength(horizontal)
    ) / 2


def _periodic_projection_bounds(projection):
    """Trova dieci picchi quasi equidistanti in una proiezione 1D."""
    projection = np.asarray(projection, dtype=np.float32)
    length = len(projection)
    radius = max(3, int(round(length * 0.006)))
    kernel = np.ones((radius * 2 + 1, 1), dtype=np.uint8)
    local_maximum = cv2.dilate(
        projection.reshape(-1, 1),
        kernel,
    ).reshape(-1)
    minimum_step = length * 0.075
    maximum_step = length * 0.125
    edge_window = int(round(length * 0.22))
    coarse_step = max(2, length // 300)
    best = None

    def candidate_score(start, end, include_regularity=False):
        step = (end - start) / 9

        if not minimum_step <= step <= maximum_step:
            return None

        expected = np.rint(
            np.linspace(start, end, 10),
        ).astype(int)
        values = local_maximum[expected]
        score = (
            float(np.mean(values))
            + 0.45 * float(np.percentile(values, 25))
        )
        actual = []

        for position in expected:
            lower = max(0, position - radius)
            upper = min(length, position + radius + 1)
            actual.append(
                lower + int(np.argmax(projection[lower:upper]))
            )

        if include_regularity:
            irregularity = (
                float(np.std(np.diff(actual))) / max(step, 1)
            )
            score -= irregularity * 45

        return score, actual, values

    for start in range(0, edge_window + 1, coarse_step):
        for end in range(
            length - edge_window - 1,
            length,
            coarse_step,
        ):
            result = candidate_score(start, end)

            if result is None:
                continue

            score, _, _ = result

            if best is None or score > best[0]:
                best = (score, start, end)

    if best is None:
        return None

    _, coarse_start, coarse_end = best
    refined = None

    for start in range(
        max(0, coarse_start - coarse_step),
        min(length - 1, coarse_start + coarse_step) + 1,
    ):
        for end in range(
            max(start + 1, coarse_end - coarse_step),
            min(length - 1, coarse_end + coarse_step) + 1,
        ):
            result = candidate_score(
                start,
                end,
                include_regularity=True,
            )

            if result is None:
                continue

            score, actual, values = result

            if refined is None or score > refined[0]:
                refined = (score, actual, values)

    if refined is None:
        return None

    score, actual, values = refined
    baseline = float(np.median(projection))
    contrast = (
        float(np.percentile(values, 25)) - baseline
    ) / 255

    if contrast < 0.035:
        return None

    return {
        "start": int(actual[0]),
        "end": int(actual[-1]),
        "positions": [int(position) for position in actual],
        "contrast": round(float(contrast), 4),
        "score": round(float(score), 4),
    }


def _refine_rectified_grid(rectified):
    """Rimuove margini residui trovando le dieci linee in entrambe le assi."""
    gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (3, 3), 0),
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )
    vertical = _periodic_projection_bounds(binary.mean(axis=0))
    horizontal = _periodic_projection_bounds(binary.mean(axis=1))

    if vertical is None or horizontal is None:
        return rectified, None

    left = vertical["start"]
    right = vertical["end"]
    top = horizontal["start"]
    bottom = horizontal["end"]

    if right - left < 500 or bottom - top < 500:
        return rectified, None

    cropped = rectified[top:bottom + 1, left:right + 1]
    refined = cv2.resize(
        cropped,
        (RECTIFIED_SIZE, RECTIFIED_SIZE),
        interpolation=cv2.INTER_CUBIC,
    )
    return refined, {
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "vertical": vertical,
        "horizontal": horizontal,
    }


def _find_grid_once(image):
    height, width = image.shape[:2]
    detection_scale = min(1.0, 1800 / max(height, width))
    detection = cv2.resize(
        image,
        None,
        fx=detection_scale,
        fy=detection_scale,
        interpolation=cv2.INTER_AREA,
    )
    gray = cv2.cvtColor(detection, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    binary = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        np.ones((5, 5), dtype=np.uint8),
        iterations=2,
    )
    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_LIST,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    image_area = float(gray.shape[0] * gray.shape[1])
    candidates = []

    for contour in sorted(
        contours,
        key=cv2.contourArea,
        reverse=True,
    )[:30]:
        area = float(cv2.contourArea(contour))

        if area < image_area * 0.06:
            continue

        perimeter = cv2.arcLength(contour, True)

        for epsilon in (0.018, 0.025, 0.035, 0.05):
            polygon = cv2.approxPolyDP(
                contour,
                epsilon * perimeter,
                True,
            )

            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue

            corners = _order_corners(polygon)
            sides = [
                np.linalg.norm(corners[(index + 1) % 4] - corners[index])
                for index in range(4)
            ]
            longest = max(sides)
            shortest = min(sides)

            if shortest < 120 or longest / max(shortest, 1) > 2.8:
                continue

            square_quality = shortest / longest
            grid_structure = _periodic_grid_score(binary, corners)
            score = (
                (area / image_area)
                * (0.55 + 0.45 * square_quality)
                * (0.3 + 1.7 * grid_structure)
            )
            candidates.append((
                score,
                corners,
                area / image_area,
                grid_structure,
                "contour_quad",
            ))
            break

        # Le pagine fotografate spesso incurvano leggermente le dieci linee:
        # il contorno resta chiaramente quadrato, ma non viene semplificato a
        # quattro vertici. Il rettangolo orientato è un buon fallback soltanto
        # quando all'interno conserva la periodicità 9x9.
        rectangle = cv2.minAreaRect(contour)
        rectangle_width, rectangle_height = rectangle[1]
        rectangle_shortest = min(rectangle_width, rectangle_height)
        rectangle_longest = max(rectangle_width, rectangle_height)

        if (
            rectangle_shortest >= 120
            and rectangle_longest / max(rectangle_shortest, 1) <= 1.65
        ):
            rectangle_corners = _order_corners(
                cv2.boxPoints(rectangle),
            )
            grid_structure = _periodic_grid_score(
                binary,
                rectangle_corners,
            )

            if grid_structure >= 0.07:
                rectangle_area_ratio = (
                    rectangle_width * rectangle_height / image_area
                )
                square_quality = (
                    rectangle_shortest / rectangle_longest
                )
                score = (
                    rectangle_area_ratio
                    * (0.55 + 0.45 * square_quality)
                    * (0.3 + 1.7 * grid_structure)
                    * 0.92
                )
                candidates.append((
                    score,
                    rectangle_corners,
                    rectangle_area_ratio,
                    grid_structure,
                    "periodic_rectangle",
                ))

    if not candidates:
        raise PhotoRecognitionError(
            "Non riesco a individuare la griglia. Inquadra tutto il bordo "
            "del Sudoku, evita riflessi e scatta la foto più frontalmente."
        )

    _, corners, area_ratio, grid_structure, detection_method = max(
        candidates,
        key=lambda item: item[0],
    )
    corners = corners / detection_scale

    if detection_method == "periodic_rectangle":
        # Il rettangolo minimo può tagliare il lato convesso di una pagina
        # incurvata. Un piccolo margine permette al raffinamento successivo
        # di ritrovare le vere linee esterne invece di agganciarsi alle
        # penultime.
        center = corners.mean(axis=0)
        corners = center + (corners - center) * 1.055
        corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
        corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)

    destination = np.float32([
        [0, 0],
        [RECTIFIED_SIZE - 1, 0],
        [RECTIFIED_SIZE - 1, RECTIFIED_SIZE - 1],
        [0, RECTIFIED_SIZE - 1],
    ])
    perspective = cv2.getPerspectiveTransform(corners, destination)
    rectified = cv2.warpPerspective(
        image,
        perspective,
        (RECTIFIED_SIZE, RECTIFIED_SIZE),
        flags=cv2.INTER_CUBIC,
    )
    refinement = None

    if detection_method == "periodic_rectangle":
        rectified, refinement = _refine_rectified_grid(rectified)

    if refinement is not None:
        refined_rectangle = np.float32([[
            [refinement["left"], refinement["top"]],
            [refinement["right"], refinement["top"]],
            [refinement["right"], refinement["bottom"]],
            [refinement["left"], refinement["bottom"]],
        ]])
        inverse_perspective = np.linalg.inv(perspective)
        corners = cv2.perspectiveTransform(
            refined_rectangle,
            inverse_perspective,
        )[0]
        detection_method += "+projection_refine"

    detection_confidence = min(
        1.0,
        0.35 * min(1.0, area_ratio / 0.45)
        + 0.65 * min(1.0, grid_structure / 0.28),
    )
    return (
        rectified,
        corners,
        round(detection_confidence, 4),
        detection_method,
    )


def _find_grid(image):
    """
    Cerca la griglia prima nell'immagine originale e, quando necessario,
    anche nel negativo.

    Il negativo viene provato quando la ricerca normale fallisce oppure
    quando la griglia raddrizzata risulta prevalentemente scura.
    """
    normal_result = None
    normal_error = None

    try:
        normal_result = _find_grid_once(image)
    except PhotoRecognitionError as error:
        normal_error = error

    try_negative = normal_result is None

    if normal_result is not None:
        normal_rectified = normal_result[0]
        normal_gray = cv2.cvtColor(
            normal_rectified,
            cv2.COLOR_BGR2GRAY,
        )
        normal_mean = float(np.mean(normal_gray))

        if normal_mean < DARK_GRID_MEAN_THRESHOLD:
            try_negative = True

    if not try_negative:
        rectified, corners, confidence, method = normal_result
        return rectified, corners, confidence, method, False

    negative_image = cv2.bitwise_not(image)
    negative_result = None
    negative_error = None

    try:
        negative_result = _find_grid_once(negative_image)
    except PhotoRecognitionError as error:
        negative_error = error

    if normal_result is None and negative_result is None:
        message = (
            str(normal_error)
            if normal_error is not None
            else "Non riesco a individuare la griglia."
        )
        raise PhotoRecognitionError(
            f"{message} Ho provato anche il negativo dell'immagine "
            "senza trovare una griglia affidabile."
        ) from negative_error

    if normal_result is None:
        rectified, corners, confidence, method = negative_result
        return (
            rectified,
            corners,
            confidence,
            f"{method}+negative",
            True,
        )

    if negative_result is None:
        rectified, corners, confidence, method = normal_result
        return rectified, corners, confidence, method, False

    (
        normal_rectified,
        normal_corners,
        normal_confidence,
        normal_method,
    ) = normal_result
    (
        negative_rectified,
        negative_corners,
        negative_confidence,
        negative_method,
    ) = negative_result

    normal_mean = float(np.mean(cv2.cvtColor(
        normal_rectified,
        cv2.COLOR_BGR2GRAY,
    )))
    dark_background = normal_mean < DARK_GRID_MEAN_THRESHOLD

    use_negative = (
        negative_confidence
        >= normal_confidence + NEGATIVE_CONFIDENCE_MARGIN
    )

    if (
        dark_background
        and negative_confidence
        >= normal_confidence - NEGATIVE_CONFIDENCE_MARGIN
    ):
        use_negative = True

    if use_negative:
        return (
            negative_rectified,
            negative_corners,
            negative_confidence,
            f"{negative_method}+negative",
            True,
        )

    return (
        normal_rectified,
        normal_corners,
        normal_confidence,
        normal_method,
        False,
    )


def _extract_glyph(cell_gray, reject_grid_fragments=False):
    size = cell_gray.shape[0]
    margin = max(7, int(round(size * 0.14)))
    interior = cell_gray[margin:size - margin, margin:size - margin]
    blurred = cv2.GaussianBlur(interior, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        7,
    )
    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        np.ones((2, 2), dtype=np.uint8),
    )
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    interior_area = float(interior.size)
    candidates = []

    for label in range(1, count):
        x, y, width, height, area = stats[label]
        center_x, center_y = centroids[label]
        touches_left = x <= 1
        touches_top = y <= 1
        touches_right = x + width >= interior.shape[1] - 1
        touches_bottom = y + height >= interior.shape[0] - 1
        touched_edges = sum((
            touches_left,
            touches_top,
            touches_right,
            touches_bottom,
        ))

        if area < interior_area * 0.006:
            continue

        if area > interior_area * 0.55:
            continue

        if height < interior.shape[0] * 0.24:
            continue

        if width < 2:
            continue

        # Dopo una rettifica di pagina leggermente curva, una linea della
        # griglia può attraversare il margine interno della cella. Le linee
        # lunghe e sottili, o le reti che toccano più bordi, non sono cifre.
        if reject_grid_fragments:
            if (
                height >= interior.shape[0] * 0.86
                and width <= interior.shape[1] * 0.16
            ):
                continue

            if (
                width >= interior.shape[1] * 0.86
                and height <= interior.shape[0] * 0.16
            ):
                continue

            if touched_edges >= 2:
                continue

        distance = math.hypot(
            center_x - interior.shape[1] / 2,
            center_y - interior.shape[0] / 2,
        )
        center_weight = max(
            0.3,
            1 - distance / (interior.shape[0] * 0.75),
        )
        candidates.append((area * center_weight, label))

    if not candidates:
        return None, None

    _, selected = max(candidates)
    mask = np.zeros_like(binary)
    mask[labels == selected] = 255
    points = cv2.findNonZero(mask)
    x, y, width, height = cv2.boundingRect(points)

    if width / max(height, 1) > 1.25:
        return None, None

    glyph = _normalise_glyph(mask)
    box = {
        "x": int(x + margin),
        "y": int(y + margin),
        "width": int(width),
        "height": int(height),
    }
    return glyph, box


def _conflicting_indices(values):
    conflicts = set()
    units = []

    for row in range(9):
        units.append([row * 9 + column for column in range(9)])

    for column in range(9):
        units.append([row * 9 + column for row in range(9)])

    for box_row in range(3):
        for box_column in range(3):
            units.append([
                (box_row * 3 + row) * 9 + box_column * 3 + column
                for row in range(3)
                for column in range(3)
            ])

    for unit in units:
        by_digit = {}

        for index in unit:
            value = values[index]

            if value:
                by_digit.setdefault(value, []).append(index)

        for indices in by_digit.values():
            if len(indices) > 1:
                conflicts.update(indices)

    return conflicts


def _candidate_is_valid(values, index, digit):
    row, column = divmod(index, 9)

    for other_column in range(9):
        other = row * 9 + other_column

        if other != index and values[other] == digit:
            return False

    for other_row in range(9):
        other = other_row * 9 + column

        if other != index and values[other] == digit:
            return False

    start_row = (row // 3) * 3
    start_column = (column // 3) * 3

    for other_row in range(start_row, start_row + 3):
        for other_column in range(start_column, start_column + 3):
            other = other_row * 9 + other_column

            if other != index and values[other] == digit:
                return False

    return True


def _grid_has_solution(values):
    """Controllo rapido di esistenza usato solo per letture OCR incerte."""
    values = [int(value) for value in values]
    row_masks = [0] * 9
    column_masks = [0] * 9
    box_masks = [0] * 9

    for index, value in enumerate(values):
        if not value:
            continue

        row, column = divmod(index, 9)
        box = (row // 3) * 3 + column // 3
        bit = 1 << value

        if (
            row_masks[row] & bit
            or column_masks[column] & bit
            or box_masks[box] & bit
        ):
            return False

        row_masks[row] |= bit
        column_masks[column] |= bit
        box_masks[box] |= bit

    full_mask = sum(1 << digit for digit in range(1, 10))

    def search():
        best_index = None
        best_candidates = 0
        best_count = 10

        for index, value in enumerate(values):
            if value:
                continue

            row, column = divmod(index, 9)
            box = (row // 3) * 3 + column // 3
            candidates = full_mask & ~(
                row_masks[row]
                | column_masks[column]
                | box_masks[box]
            )
            count = candidates.bit_count()

            if count == 0:
                return False

            if count < best_count:
                best_index = index
                best_candidates = candidates
                best_count = count

                if count == 1:
                    break

        if best_index is None:
            return True

        row, column = divmod(best_index, 9)
        box = (row // 3) * 3 + column // 3
        candidates = best_candidates

        while candidates:
            bit = candidates & -candidates
            candidates -= bit
            digit = bit.bit_length() - 1
            values[best_index] = digit
            row_masks[row] |= bit
            column_masks[column] |= bit
            box_masks[box] |= bit

            if search():
                values[best_index] = 0
                row_masks[row] ^= bit
                column_masks[column] ^= bit
                box_masks[box] ^= bit
                return True

            values[best_index] = 0
            row_masks[row] ^= bit
            column_masks[column] ^= bit
            box_masks[box] ^= bit

        return False

    return search()


def _repair_conflicts(cells):
    values = [cell["value"] for cell in cells]
    corrected = set()

    for _ in range(81):
        conflicts = _conflicting_indices(values)

        if not conflicts:
            break

        index = min(
            conflicts,
            key=lambda item: (
                cells[item]["confidence"],
                -len(cells[item]["candidates"]),
            ),
        )
        replacement = 0

        for candidate in cells[index]["candidates"][1:]:
            digit = candidate["digit"]

            if _candidate_is_valid(values, index, digit):
                replacement = digit
                break

        if replacement == values[index]:
            replacement = 0

        values[index] = replacement
        corrected.add(index)

    for index, value in enumerate(values):
        cells[index]["value"] = int(value)
        cells[index]["corrected_for_consistency"] = index in corrected

    return corrected


def _refine_uncertain_with_sudoku_constraints(cells):
    """Riconsidera le alternative OCR senza imporre una soluzione completa."""
    values = [cell["value"] for cell in cells]
    uncertain = [
        cell["index"]
        for cell in cells
        if (
            cell["detected"]
            and (
                cell["confidence"] < LOW_CONFIDENCE_THRESHOLD
                or cell["corrected_for_consistency"]
            )
        )
    ]

    if not uncertain:
        return set()

    # Con molte letture dubbie l'esistenza di una soluzione è un segnale
    # troppo debole e rischia di spostare errori fra celle. In quel caso è
    # più onesto lasciare alla revisione le confidenze OCR originali.
    if len(uncertain) > 2:
        return set()

    for index in uncertain:
        values[index] = 0

    if not _grid_has_solution(values):
        return set()

    changed = set()

    for index in sorted(
        uncertain,
        key=lambda item: cells[item]["confidence"],
        reverse=True,
    ):
        previous = cells[index]["value"]
        chosen = 0
        options = []

        for candidate in cells[index]["candidates"]:
            digit = int(candidate["digit"])

            if digit not in options:
                options.append(digit)

        for digit in options:
            if not _candidate_is_valid(values, index, digit):
                continue

            values[index] = digit

            if _grid_has_solution(values):
                chosen = digit
                break

            values[index] = 0

        values[index] = chosen
        cells[index]["value"] = chosen

        if chosen != previous:
            cells[index]["corrected_for_consistency"] = True
            changed.add(index)

    return changed


class SudokuPhotoRecognizer:
    """Pipeline riutilizzabile dal servizio web e dai test."""

    def recognise(self, image_bytes):
        image, source_size = _load_image(image_bytes)
        (
            rectified,
            corners,
            grid_confidence,
            detection_method,
            image_inverted,
        ) = _find_grid(image)
        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        cell_size = RECTIFIED_SIZE // 9
        cells = []
        reject_grid_fragments = detection_method.startswith(
            "periodic_rectangle"
        )

        for row in range(9):
            for column in range(9):
                top = row * cell_size
                left = column * cell_size
                cell_gray = gray[
                    top:top + cell_size,
                    left:left + cell_size,
                ]
                glyph, box = _extract_glyph(
                    cell_gray,
                    reject_grid_fragments=reject_grid_fragments,
                )
                index = row * 9 + column

                if glyph is None:
                    cells.append({
                        "index": index,
                        "row": row,
                        "column": column,
                        "value": 0,
                        "confidence": 0.99,
                        "candidates": [],
                        "detected": False,
                        "glyph_box": None,
                        "corrected_for_consistency": False,
                    })
                    continue

                value, confidence, candidates = _classify_glyph(glyph)
                cells.append({
                    "index": index,
                    "row": row,
                    "column": column,
                    "value": value,
                    "confidence": confidence,
                    "candidates": candidates,
                    "detected": True,
                    "glyph_box": box,
                    "corrected_for_consistency": False,
                })

        corrected = _repair_conflicts(cells)
        corrected.update(
            _refine_uncertain_with_sudoku_constraints(cells)
        )
        grid = "".join(str(cell["value"]) for cell in cells)
        detected = [cell for cell in cells if cell["detected"]]
        mean_confidence = (
            sum(cell["confidence"] for cell in detected) / len(detected)
            if detected
            else 0.0
        )
        low_confidence = [
            cell["index"]
            for cell in cells
            if (
                cell["detected"]
                and (
                    cell["confidence"] < LOW_CONFIDENCE_THRESHOLD
                    or cell["corrected_for_consistency"]
                )
            )
        ]
        warnings = []

        if image_inverted:
            warnings.append(
                "È stato rilevato uno sfondo scuro: "
                "il riconoscimento ha usato automaticamente "
                "il negativo dell'immagine."
            )

        if len(detected) < 17:
            warnings.append(
                "Sono state rilevate meno di 17 cifre: controlla che "
                "l'intera griglia sia visibile e a fuoco."
            )

        if mean_confidence < LOW_CONFIDENCE_THRESHOLD:
            warnings.append(
                "La confidenza OCR è bassa: verifica le celle evidenziate."
            )

        if corrected:
            warnings.append(
                "Alcune letture in conflitto sono state sostituite con "
                "un'alternativa o svuotate."
            )

        success, encoded = cv2.imencode(
            ".png",
            rectified,
            [cv2.IMWRITE_PNG_COMPRESSION, 6],
        )

        if not success:
            raise PhotoRecognitionError(
                "Non è stato possibile preparare l'anteprima raddrizzata."
            )

        return {
            "algorithm_version": RECOGNITION_VERSION,
            "grid": grid,
            "image_inverted": image_inverted,
            "detected_digit_count": len(detected),
            "mean_confidence": round(mean_confidence, 4),
            "grid_detection_confidence": grid_confidence,
            "grid_detection_method": detection_method,
            "low_confidence_indices": low_confidence,
            "cells": cells,
            "warnings": warnings,
            "source_size": source_size,
            "grid_corners": [
                [round(float(x), 2), round(float(y), 2)]
                for x, y in corners
            ],
            "rectified_png": encoded.tobytes(),
        }
