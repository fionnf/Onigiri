"""The app on a phone, end to end, in a real browser.

Opt in with E2E=1; it needs the built web app (pnpm build in web/) and Chromium.
A stubbed server (stub_server.py) answers in place of Claude; everything else,
including the service worker and the database, is real.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

if os.environ.get("E2E") != "1":
    pytest.skip("browser tests run with E2E=1", allow_module_level=True)

playwright_api = pytest.importorskip("playwright.async_api")

ROOT = Path(__file__).resolve().parents[3]
WEB_DIST = ROOT / "web" / "dist"
if not (WEB_DIST / "index.html").exists():
    pytest.skip("build the web app first: pnpm build in web/", allow_module_level=True)

PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36"
    ),
}

EMAIL = os.environ["OWNER_EMAIL"]
PASSWORD = os.environ["OWNER_PASSWORD"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = free_port()
    env = {**os.environ, "PORT": str(port), "WEB_DIST": str(WEB_DIST)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.e2e.stub_server"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("the app did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
async def phone(server):
    from onigiri.main import ensure_owner

    await ensure_owner()  # the per-test cleanup emptied the users table
    async with playwright_api.async_playwright() as p:
        launch = {}
        if os.environ.get("E2E_CHROMIUM"):
            launch["executable_path"] = os.environ["E2E_CHROMIUM"]
        browser = await p.chromium.launch(**launch)
        context = await browser.new_context(**PHONE)
        page = await context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(server, wait_until="networkidle")
        await page.fill("input[type=email]", EMAIL)
        await page.fill("input[type=password]", PASSWORD)
        await page.click("button[type=submit]")
        await page.get_by_role("navigation", name="Main").wait_for()
        # The service worker must control the page for sharing and offline use.
        await page.evaluate("navigator.serviceWorker.ready")
        await page.reload(wait_until="networkidle")
        assert await page.evaluate("!!navigator.serviceWorker.controller")
        yield page, context, server
        assert errors == [], errors
        await browser.close()


LAYOUT_PROBE = """
() => {
  const visible = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const small = [...document.querySelectorAll('input:not([type=file]), textarea, select')]
    .filter(visible).filter(el => parseFloat(getComputedStyle(el).fontSize) < 16)
    .map(el => el.placeholder || el.getAttribute('aria-label') || el.tagName);
  const tiny = [...document.querySelectorAll('.btn, nav[aria-label=Main] a')]
    .filter(visible).filter(el => el.getBoundingClientRect().height < 40)
    .map(el => (el.innerText || el.getAttribute('aria-label') || '').trim());
  return {
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    smallInputs: small, tinyTargets: tiny,
  };
}
"""


async def assert_phone_friendly(page, where: str) -> None:
    result = await page.evaluate(LAYOUT_PROBE)
    assert result["overflow"] <= 0, f"{where}: page scrolls sideways"
    assert result["smallInputs"] == [], f"{where}: iOS would zoom into {result['smallInputs']}"
    assert result["tinyTargets"] == [], f"{where}: too small to tap: {result['tinyTargets']}"


async def wait_for_recipe(page, title: str) -> None:
    await page.wait_for_url("**/r/**", timeout=30_000)
    await page.get_by_role("heading", name=title).wait_for(timeout=15_000)


async def test_sharing_a_link_saves_a_recipe_without_another_tap(phone) -> None:
    page, _, _ = phone
    # What Android does when you pick Onigiri in Instagram's share menu: a form POST
    # to the share target, which the service worker catches.
    await page.evaluate(
        """() => {
          const form = document.createElement('form');
          form.method = 'POST'; form.action = '/share-target'; form.enctype = 'multipart/form-data';
          const add = (name, value) => { const i = document.createElement('input');
            i.type = 'hidden'; i.name = name; i.value = value; form.appendChild(i); };
          add('title', 'Reel');
          add('text', 'Shared lentil soup\\n200 g red lentils, 1 onion. Fry, simmer 20 min.');
          document.body.appendChild(form); form.submit();
        }"""
    )
    await wait_for_recipe(page, "Shared lentil soup")
    await page.locator("text=200 g red lentils >> visible=true").wait_for()


async def test_a_phone_photo_is_shrunk_uploaded_and_stored(phone, tmp_path) -> None:
    from PIL import Image

    page, _, _ = phone
    photo = tmp_path / "IMG_0042.jpg"
    big = Image.effect_noise((4032, 3024), 60).convert("RGB")
    big.save(photo, quality=95)
    original_size = photo.stat().st_size

    await page.get_by_role("navigation", name="Main").get_by_role("link", name="Add").click()
    await assert_phone_friendly(page, "add")
    # The keyboard must not pop up over the screen on arrival.
    assert await page.evaluate("document.activeElement.tagName") != "TEXTAREA"
    await page.get_by_text("Take photo").wait_for()

    await page.locator("input[type=file][multiple]").set_input_files(str(photo))
    await page.get_by_role("button", name="Save recipe").click()
    await wait_for_recipe(page, "Photographed tomato soup")

    source = await page.request.get(page.url.replace("/r/", "/api/recipes/"))
    stored = (await source.json())["source"]
    uploaded = int(stored["photo_text"].split("photo, ")[1].split(" bytes")[0])
    assert uploaded < original_size / 3, "the photo was not shrunk before upload"
    assert stored["media"][0]["kind"] == "image"


CREATE_RECIPE = """async (title) => {
  await fetch('/api/recipes', {method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({title, servings: 2,
      groups: [{ingredients: [{raw: '250 g flour'}, {raw: '150 ml water'}]}],
      steps: [{text: 'Knead for 5 minutes.'}, {text: 'Cook in a dry pan.'}]})});
}"""


async def test_saved_recipes_open_without_a_connection(phone) -> None:
    page, context, server = phone
    await page.evaluate(CREATE_RECIPE, "Opened flatbread")
    await page.evaluate(CREATE_RECIPE, "Never opened focaccia")

    # One recipe is opened while online; the other is only saved from Settings.
    await page.goto(server, wait_until="networkidle")
    await page.get_by_text("Opened flatbread").click()
    await page.get_by_role("heading", name="Opened flatbread").wait_for()
    await page.locator("text=250 g flour >> visible=true").wait_for()
    opened_url = page.url

    await page.goto(server + "/settings", wait_until="networkidle")
    await page.get_by_role("button", name="Save recipes for offline now").click()
    await page.get_by_text("Saved 2 recipes on this phone.").wait_for(timeout=15_000)
    never_opened_id = await page.evaluate(
        "async () => (await (await fetch('/api/recipes?q=focaccia&semantic=false'))"
        ".json()).items[0].id"
    )

    await context.set_offline(True)
    try:
        await page.goto(opened_url)
        await page.get_by_role("heading", name="Opened flatbread").wait_for(timeout=10_000)
        await page.locator("text=250 g flour >> visible=true").wait_for(timeout=10_000)
        await page.get_by_text("Offline. Recipes you have opened").wait_for()

        await page.goto(f"{server}/r/{never_opened_id}")
        await page.get_by_role("heading", name="Never opened focaccia").wait_for(timeout=10_000)
        await page.locator("text=150 ml water >> visible=true").wait_for(timeout=10_000)

        await page.goto(f"{server}/r/{never_opened_id}/cook")
        await page.get_by_text("Knead for 5 minutes.").wait_for(timeout=10_000)

        await page.goto(server)
        await page.get_by_text("Never opened focaccia").wait_for(timeout=10_000)
    finally:
        await context.set_offline(False)


async def test_signing_out_forgets_what_was_saved(phone) -> None:
    page, _, server = phone
    await page.evaluate(CREATE_RECIPE, "Private soup")
    await page.goto(server + "/settings", wait_until="networkidle")
    await page.get_by_role("button", name="Save recipes for offline now").click()
    await page.get_by_text("Saved 1 recipes on this phone.").wait_for(timeout=15_000)
    assert await page.evaluate("caches.has('onigiri-api')")

    await page.get_by_role("button", name="Sign out").click()
    await page.locator("input[type=email]").wait_for()
    remaining = await page.evaluate(
        "async () => (await caches.has('onigiri-api')) &&"
        " (await (await caches.open('onigiri-api')).keys()).length"
    )
    assert not remaining


async def test_every_screen_fits_a_phone(phone) -> None:
    page, _, server = phone
    await page.evaluate(
        """async () => {
          await fetch('/api/recipes', {method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: 'Layout check stew', servings: 4,
              description: 'A long description that used to wrap one word per line on a phone.',
              groups: [{ingredients: [{raw: '1 kg beef'}]}], steps: [{text: 'Braise 2 hours.'}],
              tags: ['stew', 'beef', 'winter', 'one pot', 'make ahead', 'freezer friendly']})});
        }"""
    )
    for path in ("/", "/add", "/profile", "/settings"):
        await page.goto(server + path, wait_until="networkidle")
        await assert_phone_friendly(page, path)

    await page.goto(server, wait_until="networkidle")
    await page.get_by_text("Layout check stew").click()
    heading = page.get_by_role("heading", name="Layout check stew")
    await heading.wait_for()
    await assert_phone_friendly(page, "recipe")
    # The title gets the full width rather than a narrow column beside the buttons.
    box = await heading.bounding_box()
    assert box and box["width"] > 300

    await page.get_by_role("link", name="Edit").click()
    await page.get_by_role("button", name="Save").first.wait_for()
    await assert_phone_friendly(page, "edit")

    await page.goto(page.url.replace("/edit", "/cook"), wait_until="networkidle")
    await page.get_by_text("Braise 2 hours.").wait_for()
    await assert_phone_friendly(page, "cook")
