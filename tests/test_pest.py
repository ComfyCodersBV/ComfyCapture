from __future__ import annotations

import shutil
import subprocess

import pytest

from comfycapture.core import pest
from comfycapture.core.models import Action, Device, DeviceKind, Selector, SelectorKind, Step, Target, Test


def checkout() -> Test:
    return Test(
        id="t",
        name="Guest checkout",
        tags=("CINF-19",),
        device=Device(DeviceKind.MOBILE, name="iPhone 15"),
        steps=(
            Step("s1", Action.NAVIGATE, url="/products/42"),
            Step(
                "s2",
                Action.TAP,
                target=Target(Selector(SelectorKind.TEST_ID, "add", attribute="wire:model.live")),
            ),
            Step("s3", Action.FILL, target=Target(Selector(SelectorKind.LABEL, "E-mail")), value="{{email}}"),
            Step(
                "s4",
                Action.FILL,
                target=Target(Selector(SelectorKind.ROLE, "Password", role="textbox")),
                value="{{secret:pw}}",
            ),
            Step(
                "s5", Action.ASSERT_TEXT, target=Target(Selector(SelectorKind.CSS, "h1")), value="It's done"
            ),
        ),
    )


def test_steps_become_a_pest_chain() -> None:
    output = pest.render(checkout())

    assert "$page = visit('/products/42')->on()->iPhone15();" in output
    assert "->fill('internal:label=\"E-mail\"s', env('EMAIL'))" in output
    assert "env('COMFYCAPTURE_SECRET_PW')" in output
    assert "->assertSeeIn('h1', 'It\\'s done');" in output
    assert output.rstrip().endswith("})->group('CINF-19');")


def test_steps_pest_cannot_express_block_the_export() -> None:
    broken = Test(id="t", name="Broken", steps=(Step("s9", Action.UNKNOWN, raw="drag"),))

    with pytest.raises(pest.PestExportError, match="s9"):
        pest.render(broken)


@pytest.mark.skipif(shutil.which("php") is None, reason="php is not installed")
def test_rendered_test_is_valid_php(tmp_path) -> None:
    path = tmp_path / pest.filename(checkout())
    path.write_text(pest.render(checkout()))

    result = subprocess.run(["php", "-l", str(path)], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
