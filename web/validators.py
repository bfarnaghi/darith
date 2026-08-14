# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import warnings

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


DASHBOARD_GIF_MAX_BYTES = 2 * 1024 * 1024
DASHBOARD_GIF_MAX_DIMENSION = 1200
DASHBOARD_GIF_MAX_FRAMES = 300
PROFILE_IMAGE_MAX_BYTES = 2 * 1024 * 1024
PROFILE_IMAGE_MAX_DIMENSION = 1200
PROFILE_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_dashboard_gif(upload):
    if upload.size > DASHBOARD_GIF_MAX_BYTES:
        raise ValidationError("Each dashboard GIF must be 2 MB or smaller.")

    original_position = upload.tell()
    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(upload)
            if image.format != "GIF":
                raise ValidationError("Upload a real GIF image.")
            width, height = image.size
            if max(width, height) > DASHBOARD_GIF_MAX_DIMENSION:
                raise ValidationError("GIF dimensions cannot exceed 1200 x 1200 pixels.")
            if getattr(image, "n_frames", 1) > DASHBOARD_GIF_MAX_FRAMES:
                raise ValidationError("GIF animations cannot exceed 300 frames.")
            image.verify()
    except ValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError("The GIF dimensions are too large.") from None
    except (OSError, UnidentifiedImageError, ValueError):
        raise ValidationError("Upload a valid, readable GIF image.") from None
    finally:
        upload.seek(original_position)


def validate_profile_image(upload):
    if upload.size > PROFILE_IMAGE_MAX_BYTES:
        raise ValidationError("Profile pictures must be 2 MB or smaller.")

    original_position = upload.tell()
    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(upload)
            if image.format not in PROFILE_IMAGE_FORMATS:
                raise ValidationError("Upload a JPEG, PNG, or WebP profile picture.")
            if getattr(image, "n_frames", 1) > 1:
                raise ValidationError("Profile pictures must be still images.")
            width, height = image.size
            if max(width, height) > PROFILE_IMAGE_MAX_DIMENSION:
                raise ValidationError(
                    "Profile picture dimensions cannot exceed 1200 x 1200 pixels."
                )
            image.verify()
    except ValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError("The profile picture dimensions are too large.") from None
    except (OSError, UnidentifiedImageError, ValueError):
        raise ValidationError("Upload a valid, readable profile picture.") from None
    finally:
        upload.seek(original_position)
