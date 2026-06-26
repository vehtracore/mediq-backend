from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageStat, UnidentifiedImageError


MIN_IMAGE_SIDE = 320
ANALYSIS_SIDE = 160
MIN_BRIGHTNESS = 35
MAX_BRIGHTNESS = 245
MIN_CONTRAST = 10
MIN_LAPLACIAN_VARIANCE = 18.0


@dataclass(frozen=True)
class LabImageQualityResult:
    passed: bool
    reason: str | None = None
    lighting_score: str = "Acceptable"


def _laplacian_variance(gray_image: Image.Image) -> float:
    width, height = gray_image.size
    if width < 3 or height < 3:
        return 0.0

    pixels = gray_image.load()
    values: list[int] = []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            values.append(
                (4 * pixels[x, y])
                - pixels[x - 1, y]
                - pixels[x + 1, y]
                - pixels[x, y - 1]
                - pixels[x, y + 1]
            )

    if not values:
        return 0.0

    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def assess_lab_image_quality(image_bytes: bytes) -> LabImageQualityResult:
    """
    Fast local screening before Gemini. Thresholds are intentionally conservative:
    only obviously unusable images are blocked here; borderline scans still go
    through the AI prompt where strip-specific quality control can decide.
    """
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
            if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
                return LabImageQualityResult(
                    passed=False,
                    reason=(
                        "Image resolution is too low. Retake the strip photo "
                        "closer to the camera with the full strip visible."
                    ),
                    lighting_score="Poor",
                )

            gray = image.convert("L")
            gray.thumbnail((ANALYSIS_SIDE, ANALYSIS_SIDE))

            stat = ImageStat.Stat(gray)
            brightness = stat.mean[0]
            contrast = stat.stddev[0]
            focus_score = _laplacian_variance(gray)

            if brightness < MIN_BRIGHTNESS:
                return LabImageQualityResult(
                    passed=False,
                    reason=(
                        "The image is too dark for a reliable scan. Retake it "
                        "in brighter, even lighting."
                    ),
                    lighting_score="Poor",
                )

            if brightness > MAX_BRIGHTNESS:
                return LabImageQualityResult(
                    passed=False,
                    reason=(
                        "The image is overexposed for a reliable scan. Retake "
                        "it without glare or direct flash on the strip."
                    ),
                    lighting_score="Poor",
                )

            if contrast < MIN_CONTRAST:
                return LabImageQualityResult(
                    passed=False,
                    reason=(
                        "The image does not have enough contrast for a reliable "
                        "scan. Place the strip on a plain white background."
                    ),
                    lighting_score="Poor",
                )

            if (
                focus_score < MIN_LAPLACIAN_VARIANCE
                and contrast < MIN_CONTRAST * 2.5
            ):
                return LabImageQualityResult(
                    passed=False,
                    reason=(
                        "The image appears blurry. Hold the camera steady and "
                        "retake a sharper photo of the strip."
                    ),
                    lighting_score="Poor",
                )

            lighting_score = (
                "Good"
                if 75 <= brightness <= 215 and contrast >= 25
                else "Acceptable"
            )
            return LabImageQualityResult(
                passed=True,
                lighting_score=lighting_score,
            )

    except UnidentifiedImageError:
        return LabImageQualityResult(
            passed=False,
            reason="Upload a clear JPG, PNG, or WEBP image of the urine strip.",
            lighting_score="Poor",
        )
