"""Color-vision accessible scientific figures, exported at configured 600+ DPI."""
from io import BytesIO

from cycler import cycler
from matplotlib import rc_context
from matplotlib.figure import Figure

from src.utils.config import FigureSettings


def figure_style(settings: FigureSettings) -> dict:
    """Return an explicit style without changing global plotting state."""
    return {"font.family": settings.font_family, "font.size": settings.font_size,
            "axes.prop_cycle": cycler(color=settings.palette), "axes.spines.top": False,
            "axes.spines.right": False, "savefig.dpi": settings.dpi}


def export_png(figure: Figure, settings: FigureSettings) -> bytes:
    """Export an already labeled scientific figure as a standalone PNG."""
    output = BytesIO()
    with rc_context(figure_style(settings)):
        figure.savefig(output, format="png", dpi=settings.dpi, bbox_inches="tight")
    return output.getvalue()
