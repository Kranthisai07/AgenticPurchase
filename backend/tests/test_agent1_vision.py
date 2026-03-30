import pytest

from ..apps.agent1_vision import main as vision
from ..libs.schemas.models import BBox


@pytest.fixture(autouse=True)
def reset_client():
    vision._set_client_for_tests(None)
    yield
    vision._set_client_for_tests(None)


@pytest.fixture
def sample_image(tmp_path):
    from PIL import Image

    path = tmp_path / "sample_bottle.jpg"
    img = Image.new("RGB", (10, 10), color=(120, 200, 150))
    img.save(path)
    return path


class _StubColor:
    def __init__(self, r, g, b, score):
        self.color = type("Color", (), {"red": r, "green": g, "blue": b})()
        self.score = score


class _StubDominant:
    def __init__(self, colors):
        self.colors = colors


class _StubImageProps:
    def __init__(self, colours):
        self.dominant_colors = _StubDominant(colours)


class _StubVertex:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _StubObject:
    def __init__(self, name, score):
        self.name = name
        self.score = score
        self.bounding_poly = type(
            "Poly",
            (),
            {"normalized_vertices": [_StubVertex(0.1, 0.2), _StubVertex(0.9, 0.8)]},
        )()


class _StubLabel:
    def __init__(self, description, score):
        self.description = description
        self.score = score


class _StubText:
    def __init__(self, description):
        self.description = description


class _StubResponse:
    def __init__(self, *, objects=None, labels=None, text=None, colors=None):
        self.localized_object_annotations = objects or []
        self.label_annotations = labels or []
        self.text_annotations = text or []
        self.image_properties_annotation = _StubImageProps(colors or [])

        class _PB:
            def __init__(self, outer):
                self.outer = outer

            def __getattr__(self, item):
                return getattr(self.outer, item)

        self._pb = _PB(self)


class _StubClient:
    def __init__(self, response):
        self._response = response

    def annotate_image(self, *_args, **_kwargs):
        return self._response


@pytest.mark.asyncio
async def test_intake_with_object_detection(sample_image):
    response = _StubResponse(
        objects=[_StubObject("bottle", 0.93)],
        text=[_StubText("Nike sports bottle")],
        colors=[_StubColor(10, 200, 20, 0.9)],
    )
    vision._set_client_for_tests(_StubClient(response))

    hypo = await vision.intake_image(str(sample_image))

    assert hypo.label == "bottle"
    assert hypo.brand == "Nike"
    assert isinstance(hypo.bbox, BBox)
    assert hypo.color is not None


@pytest.mark.asyncio
async def test_intake_with_label_detection(sample_image):
    response = _StubResponse(
        labels=[_StubLabel("pen", 0.81)],
        text=[_StubText("Pilot pen packaging")],
    )
    vision._set_client_for_tests(_StubClient(response))

    hypo = await vision.intake_image(str(sample_image.with_suffix(".png")))

    assert hypo.label == "pen"
    assert hypo.brand == "Pilot"
    assert hypo.bbox is None


@pytest.mark.asyncio
async def test_intake_fallback(sample_image):
    response = _StubResponse()
    vision._set_client_for_tests(_StubClient(response))

    hypo = await vision.intake_image(str(sample_image.with_name("random_item.jpg")))

    assert hypo.label in {"bottle", "object"}
    assert hypo.brand in {None, "Nike"}
