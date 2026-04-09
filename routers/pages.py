"""Page routes — render HTML templates."""

from fastapi import APIRouter, Request

router = APIRouter()

PAGES = [
    {"slug": "segments", "title": "Segment Frequency", "icon": "train", "desc": "Train frequencies per track segment"},
    {"slug": "reach", "title": "Station Reach", "icon": "map-pin", "desc": "Reachable stations within a time budget"},
    {"slug": "connectivity", "title": "Station Connectivity", "icon": "bar-chart-3", "desc": "Multi-dimensional station comparison"},
    {"slug": "duration", "title": "Travel Duration", "icon": "timer", "desc": "Travel time to any destination"},
    {"slug": "multimodal", "title": "Multimodal Duration", "icon": "bus", "desc": "Door-to-door with all operators"},
    {"slug": "punctuality", "title": "Train Punctuality", "icon": "alarm-clock", "desc": "Real-time delay analysis"},
    {"slug": "accessibility", "title": "Stop Accessibility", "icon": "footprints", "desc": "Distance to nearest transit stop"},
    {"slug": "propagation", "title": "Delay Propagation", "icon": "search", "desc": "Where delays originate"},
    {"slug": "problematic", "title": "Problematic Trains", "icon": "alert-triangle", "desc": "Consistently late trains"},
    {"slug": "missed", "title": "Missed Connections", "icon": "link-2", "desc": "Broken transfers due to delays"},
]


def _ctx(request: Request, **kwargs):
    from main import templates
    template_name = kwargs.pop("template")
    context = {"pages": PAGES, **kwargs}
    return templates.TemplateResponse(request, template_name, context)


@router.get("/")
async def home(request: Request):
    return _ctx(request, template="home.html")


@router.get("/segments")
async def segments(request: Request):
    return _ctx(request, template="segments.html", page_title="Segment Frequency")


@router.get("/reach")
async def reach(request: Request):
    return _ctx(request, template="reach.html", page_title="Station Reach")


@router.get("/connectivity")
async def connectivity(request: Request):
    return _ctx(request, template="connectivity.html", page_title="Station Connectivity")


@router.get("/duration")
async def duration(request: Request):
    return _ctx(request, template="duration.html", page_title="Travel Duration")


@router.get("/multimodal")
async def multimodal(request: Request):
    return _ctx(request, template="multimodal.html", page_title="Multimodal Duration")


@router.get("/punctuality")
async def punctuality(request: Request):
    return _ctx(request, template="punctuality.html", page_title="Train Punctuality")


@router.get("/accessibility")
async def accessibility(request: Request):
    return _ctx(request, template="accessibility.html", page_title="Stop Accessibility")


@router.get("/propagation")
async def propagation(request: Request):
    return _ctx(request, template="propagation.html", page_title="Delay Propagation")


@router.get("/problematic")
async def problematic(request: Request):
    return _ctx(request, template="problematic.html", page_title="Problematic Trains")


@router.get("/missed")
async def missed(request: Request):
    return _ctx(request, template="missed.html", page_title="Missed Connections")
