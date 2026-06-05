# Unified Web Interface (Sub-project A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the heat-algorithm camera feeds and the car drive control into a single browser interface (two camera feeds on top, keyboard + on-screen drive control on the bottom), served by one laptop process.

**Architecture:** Extend the existing Flask `HeatWebServer` with drive/stop/status routes and a redesigned page. The browser computes a drive vector from keyboard/joystick and POSTs it to the laptop, which forwards it via the existing `MotorHttpClient` (own daemon thread, TTL deadman). No new processes or threads beyond the one `MotorHttpClient` instance.

**Tech Stack:** Python 3.10+, Flask 3.1, pytest, vanilla JS (no frontend framework).

**Spec:** `docs/superpowers/specs/2026-06-05-unified-interface-design.md`

**Run tests with:** `cd laptop && ../.venv/bin/python -m pytest -q`

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `laptop/src/machine_vision_client/config.py` | Settings | Add `MOTOR_HOST`, `MOTOR_BASE_URL` |
| `laptop/src/machine_vision_client/ui/web_server.py` | HTTP server + routes | Accept `motor`; add `/control/drive`, `/control/stop`, `/status`; render template |
| `laptop/src/machine_vision_client/ui/templates/index.html` | The page (feeds + control panel + JS) | Create (extracted from inline `_PAGE`) |
| `laptop/src/machine_vision_client/main.py` | Orchestration | Build/start/stop `MotorHttpClient`, pass to server |
| `laptop/src/machine_vision_client/control/controller.py` | Control re-exports | Drop `DrivePanel`/`CAR_WIN` |
| `laptop/src/machine_vision_client/control/drive_panel.py` | OpenCV drive window | **Delete** |
| `laptop/tests/test_web_server.py` | Server tests | Extend with motor + status tests |
| `laptop/tests/test_config.py` | Config test | Create |
| `laptop/tests/test_controller.py` | Control export test | Create |

---

## Task 1: Config — motor host / base URL

**Files:**
- Modify: `laptop/src/machine_vision_client/config.py`
- Test: `laptop/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `laptop/tests/test_config.py`:

```python
from machine_vision_client import config


def test_motor_base_url_derives_from_motor_host():
    assert config.MOTOR_BASE_URL == f"http://{config.MOTOR_HOST}"
    assert config.MOTOR_BASE_URL.startswith("http://")


def test_motor_host_defaults_to_esp32_host():
    # With no MOTOR_HOST override, motors share the camera board's host
    # (the one-board end state).
    assert config.MOTOR_HOST == config.ESP32_HOST
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: module 'machine_vision_client.config' has no attribute 'MOTOR_BASE_URL'`

- [ ] **Step 3: Add the constants**

In `config.py`, immediately after the `THERMAL_HTTP_URL` block (before the `# Heat web interface` section), add:

```python
# Motor control host. Defaults to the camera/thermal board (ESP32_HOST) so
# the laptop assumes the one-board end state; override with MOTOR_HOST while
# motors live on a separate board.
MOTOR_HOST = os.environ.get("MOTOR_HOST", ESP32_HOST)
MOTOR_BASE_URL = f"http://{MOTOR_HOST}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add laptop/src/machine_vision_client/config.py laptop/tests/test_config.py
git commit -m "feat: add MOTOR_HOST/MOTOR_BASE_URL config (defaults to ESP32_HOST)"
```

---

## Task 2: `/control/drive` route

**Files:**
- Modify: `laptop/src/machine_vision_client/ui/web_server.py`
- Test: `laptop/tests/test_web_server.py`

- [ ] **Step 1: Write the failing test**

In `test_web_server.py`, replace the top of the file (imports + `_StubPipeline` + `_client`) with this expanded version, and add the new test. The key changes: `import threading`, a `_StubRisk`, `risk`/`risk_lock` on the stub pipeline, a `_FakeMotor`, and `_client()` now returns a 4-tuple including the motor.

```python
import threading

from machine_vision_client.ui.web_server import FrameBus, HeatWebServer


class _StubRisk:
    score = 7
    last_event = "test event"


class _StubPipeline:
    def __init__(self):
        self.density = 4
        self.min_conf = 20.0
        self.risk = _StubRisk()
        self.risk_lock = threading.Lock()

    def adjust_density(self, delta):
        self.density += delta
        return self.density

    def adjust_min_conf(self, delta):
        self.min_conf += delta
        return self.min_conf


class _FakeMotor:
    def __init__(self):
        self.calls = []
        self.last_error = None
        self.last_status = {"state": "ok"}

    def set_vector(self, x, y, r):
        self.calls.append((x, y, r))


def _client():
    bus = FrameBus()
    pipeline = _StubPipeline()
    motor = _FakeMotor()
    server = HeatWebServer(bus, pipeline, "127.0.0.1", 8000, motor=motor)
    return server.app.test_client(), bus, pipeline, motor
```

Then update the three existing tests that unpack `_client()` to take 4 values (`client, _bus, _pipe, _motor = _client()` for the index/density/min_conf tests — `test_frame_bus_publish_then_stream_yields_latest` does not call `_client()` and is unchanged), and add:

```python
def test_control_drive_sets_motor_vector():
    client, _bus, _pipe, motor = _client()
    resp = client.post("/control/drive", json={"x": 0.5, "y": -1.0, "r": 0.25})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert motor.calls == [(0.5, -1.0, 0.25)]


def test_control_drive_defaults_missing_axes_to_zero():
    client, _bus, _pipe, motor = _client()
    resp = client.post("/control/drive", json={"y": 1.0})
    assert resp.status_code == 200
    assert motor.calls == [(0.0, 1.0, 0.0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_web_server.py -v`
Expected: FAIL — `HeatWebServer.__init__()` got an unexpected keyword argument `motor` (and the new drive tests 404).

- [ ] **Step 3: Implement the route**

In `web_server.py`, change `__init__` to accept and store `motor`:

```python
    def __init__(self, bus: FrameBus, pipeline, host: str, port: int, motor=None):
        self._bus = bus
        self._pipeline = pipeline
        self._host = host
        self._port = port
        self._motor = motor
        self._app = Flask(__name__)
        self._register_routes()
```

Add this route inside `_register_routes` (after the `min_conf` route):

```python
        @app.route("/control/drive", methods=["POST"])
        def drive():
            data = request.get_json(silent=True) or {}
            x = float(data.get("x", 0.0))
            y = float(data.get("y", 0.0))
            r = float(data.get("r", 0.0))
            if self._motor is not None:
                self._motor.set_vector(x, y, r)
            return jsonify(ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_web_server.py -v`
Expected: PASS (all web_server tests green)

- [ ] **Step 5: Commit**

```bash
git add laptop/src/machine_vision_client/ui/web_server.py laptop/tests/test_web_server.py
git commit -m "feat: add POST /control/drive route forwarding to MotorHttpClient"
```

---

## Task 3: `/control/stop` route

**Files:**
- Modify: `laptop/src/machine_vision_client/ui/web_server.py`
- Test: `laptop/tests/test_web_server.py`

- [ ] **Step 1: Write the failing test**

Add to `test_web_server.py`:

```python
def test_control_stop_zeroes_motor_vector():
    client, _bus, _pipe, motor = _client()
    resp = client.post("/control/stop")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert motor.calls == [(0.0, 0.0, 0.0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_web_server.py::test_control_stop_zeroes_motor_vector -v`
Expected: FAIL with 404 (route not registered)

- [ ] **Step 3: Implement the route**

Add inside `_register_routes` (after the `drive` route):

```python
        @app.route("/control/stop", methods=["POST"])
        def stop():
            if self._motor is not None:
                self._motor.set_vector(0.0, 0.0, 0.0)
            return jsonify(ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_web_server.py::test_control_stop_zeroes_motor_vector -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add laptop/src/machine_vision_client/ui/web_server.py laptop/tests/test_web_server.py
git commit -m "feat: add POST /control/stop route"
```

---

## Task 4: `/status` route (risk + motor health)

**Files:**
- Modify: `laptop/src/machine_vision_client/ui/web_server.py`
- Test: `laptop/tests/test_web_server.py`

- [ ] **Step 1: Write the failing test**

Add to `test_web_server.py`:

```python
def test_status_reports_risk_and_motor_health():
    client, _bus, _pipe, _motor = _client()
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["risk"] == 7
    assert body["event"] == "test event"
    assert body["motor_ok"] is True
    assert body["motor_error"] is None
    assert body["motor_status"] == {"state": "ok"}


def test_status_reports_motor_offline_on_error():
    client, _bus, _pipe, motor = _client()
    motor.last_error = "connection refused"
    body = client.get("/status").get_json()
    assert body["motor_ok"] is False
    assert body["motor_error"] == "connection refused"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_web_server.py -k status -v`
Expected: FAIL with 404 (route not registered)

- [ ] **Step 3: Implement the route**

Add inside `_register_routes` (after the `stop` route):

```python
        @app.route("/status")
        def status():
            with self._pipeline.risk_lock:
                score = self._pipeline.risk.score
                event = self._pipeline.risk.last_event
            motor = self._motor
            return jsonify(
                risk=score,
                event=event,
                motor_ok=(motor is not None and motor.last_error is None),
                motor_error=(motor.last_error if motor is not None else "no motor"),
                motor_status=(motor.last_status if motor is not None else None),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_web_server.py -k status -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add laptop/src/machine_vision_client/ui/web_server.py laptop/tests/test_web_server.py
git commit -m "feat: add GET /status (risk score + motor health)"
```

---

## Task 5: Page template — extract + add control panel

**Files:**
- Create: `laptop/src/machine_vision_client/ui/templates/index.html`
- Modify: `laptop/src/machine_vision_client/ui/web_server.py`
- Test: `laptop/tests/test_web_server.py`

- [ ] **Step 1: Write the failing test**

Replace the existing `test_index_serves_page_with_feeds` in `test_web_server.py` with:

```python
def test_index_serves_page_with_feeds_and_controls():
    client, _bus, _pipe, _motor = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"rgb.mjpg" in resp.data
    assert b"thermal.mjpg" in resp.data
    assert b"/control/drive" in resp.data   # drive JS present
    assert b'id="joy"' in resp.data          # on-screen joystick present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_web_server.py::test_index_serves_page_with_feeds_and_controls -v`
Expected: FAIL — `/control/drive` / `id="joy"` not found in the current inline page.

- [ ] **Step 3: Create the template**

Create `laptop/src/machine_vision_client/ui/templates/index.html` with this exact content:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Fire Risk - Unified Control</title>
<style>
  body{margin:0;background:#111;color:#ddd;font-family:system-ui,sans-serif}
  h1{font-size:18px;padding:10px 14px;margin:0;background:#000;display:flex;justify-content:space-between;align-items:center}
  .badge{padding:2px 8px;border-radius:4px;margin-left:6px;font-size:13px}
  .ok{background:#1a3} .bad{background:#a22}
  .feeds{display:flex;flex-wrap:wrap;gap:12px;padding:12px}
  .feed{background:#000;border:1px solid #333;border-radius:6px;padding:6px}
  .feed h2{font-size:13px;margin:4px 6px;color:#9af}
  img{display:block;max-width:100%;height:auto;background:#222}
  .control{display:flex;gap:24px;align-items:center;padding:12px 14px;border-top:1px solid #333}
  #joy{width:180px;height:180px;border-radius:50%;background:#1a1a22;border:1px solid #456;position:relative;touch-action:none;flex:none}
  #nub{width:54px;height:54px;border-radius:50%;background:#48c;position:absolute;left:63px;top:63px}
  button{background:#223;color:#cde;border:1px solid #456;border-radius:5px;padding:8px 14px;margin:3px;cursor:pointer;font-size:14px}
  button:hover{background:#345}
  #stop{background:#a22;color:#fff;font-weight:bold}
  .hint{font-size:12px;color:#888;margin-bottom:4px}
  #status{font-size:12px;color:#8a8;margin-top:4px}
</style></head>
<body>
  <h1>Fire Risk - Unified Control
    <span>
      <span id="risk" class="badge">RISK -</span>
      <span id="motor" class="badge">motor ?</span>
    </span>
  </h1>
  <div class="feeds">
    <div class="feed"><h2>RGB + material / risk overlay</h2>
      <img src="/rgb.mjpg" alt="rgb"></div>
    <div class="feed"><h2>Thermal (cropped)</h2>
      <img src="/thermal.mjpg" alt="thermal"></div>
  </div>
  <div class="control">
    <div id="joy"><div id="nub"></div></div>
    <div>
      <div class="hint">Drive: <b>W A S D</b> move, <b>Q E</b> rotate, <b>Space</b> stop. Drag the joystick on touch.</div>
      <div>
        <button onmousedown="rotate(1)" onmouseup="rotate(0)">&#8634; rotate L (Q)</button>
        <button onmousedown="rotate(-1)" onmouseup="rotate(0)">rotate R (E) &#8635;</button>
        <button id="stop" onclick="stopNow()">STOP (space)</button>
      </div>
      <div>
        <button onclick="ctl('density',1)">grid +</button>
        <button onclick="ctl('density',-1)">grid -</button>
        <button onclick="ctl('min_conf',5)">min-conf +</button>
        <button onclick="ctl('min_conf',-5)">min-conf -</button>
      </div>
      <div id="status"></div>
    </div>
  </div>
<script>
  let keyVec={x:0,y:0,r:0};
  let joyVec={x:0,y:0};
  let rotBtn=0;
  const pressed=new Set();
  const KEYMAP={w:['y',1],s:['y',-1],d:['x',1],a:['x',-1],q:['r',1],e:['r',-1]};

  function recompute(){
    let x=0,y=0,r=0;
    for(const k of pressed){const m=KEYMAP[k]; if(!m)continue;
      if(m[0]==='x')x+=m[1]; else if(m[0]==='y')y+=m[1]; else r+=m[1];}
    keyVec={x,y,r};
  }
  function current(){
    return {x: joyVec.x||keyVec.x, y: joyVec.y||keyVec.y, r: rotBtn||keyVec.r};
  }
  async function send(){
    const v=current();
    try{ await fetch('/control/drive',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(v)}); }catch(e){}
  }
  async function stopNow(){
    pressed.clear(); keyVec={x:0,y:0,r:0}; joyVec={x:0,y:0}; rotBtn=0;
    try{ await fetch('/control/stop',{method:'POST'}); }catch(e){}
  }
  function rotate(dir){ rotBtn=dir; send(); }

  setInterval(send, 66);  // ~15 Hz drive loop

  document.addEventListener('keydown',e=>{
    const k=e.key.toLowerCase();
    if(k===' '){e.preventDefault(); stopNow(); return;}
    if(KEYMAP[k]){pressed.add(k); recompute();}
  });
  document.addEventListener('keyup',e=>{
    const k=e.key.toLowerCase();
    if(KEYMAP[k]){pressed.delete(k); recompute();}
  });
  window.addEventListener('blur',stopNow);

  const joy=document.getElementById('joy'), nub=document.getElementById('nub');
  let dragging=false;
  const R=63;
  function setNub(dx,dy){
    const m=Math.hypot(dx,dy); if(m>R){dx=dx*R/m; dy=dy*R/m;}
    nub.style.left=(R+dx)+'px'; nub.style.top=(R+dy)+'px';
    joyVec={x:dx/R, y:-dy/R};
  }
  function joyMove(e){
    if(!dragging)return;
    const rect=joy.getBoundingClientRect();
    const p=e.touches?e.touches[0]:e;
    setNub(p.clientX-rect.left-90, p.clientY-rect.top-90);
  }
  function joyStart(e){dragging=true; joyMove(e);}
  function joyEnd(){dragging=false; joyVec={x:0,y:0}; nub.style.left='63px'; nub.style.top='63px';}
  joy.addEventListener('pointerdown',joyStart);
  window.addEventListener('pointermove',joyMove);
  window.addEventListener('pointerup',joyEnd);

  async function ctl(name,delta){
    try{ const r=await fetch(`/control/${name}?delta=${delta}`,{method:'POST'});
      document.getElementById('status').textContent=JSON.stringify(await r.json()); }catch(e){}
  }
  setInterval(async()=>{  // status poll ~2 Hz
    try{
      const s=await (await fetch('/status')).json();
      const rb=document.getElementById('risk');
      rb.textContent='RISK '+s.risk; rb.className='badge '+(s.risk>3?'bad':'ok');
      const mb=document.getElementById('motor');
      mb.textContent=s.motor_ok?'motor ok':'motor offline';
      mb.className='badge '+(s.motor_ok?'ok':'bad');
    }catch(e){}
  },500);
</script>
</body></html>
```

- [ ] **Step 4: Switch the index route to render the template**

In `web_server.py`, update the Flask import to include `render_template`:

```python
from flask import Flask, Response, jsonify, render_template, request
```

Replace the `index` route body:

```python
        @app.route("/")
        def index():
            return render_template("index.html")
```

Then delete the now-unused `_PAGE = """..."""` module-level string (the whole assignment). Flask auto-discovers templates in `machine_vision_client/ui/templates/` because the app is `Flask(__name__)` in the `ui` package.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_web_server.py -v`
Expected: PASS (all web_server tests green, including the new index test)

- [ ] **Step 6: Commit**

```bash
git add laptop/src/machine_vision_client/ui/web_server.py \
        laptop/src/machine_vision_client/ui/templates/index.html \
        laptop/tests/test_web_server.py
git commit -m "feat: unified page template — feeds on top, drive control on bottom"
```

---

## Task 6: Wire `MotorHttpClient` into `main.py`

**Files:**
- Modify: `laptop/src/machine_vision_client/main.py`

This task is orchestration glue (constructing/starting/stopping a thread and passing it to the server). It has no isolated unit seam; it is verified by importing the module and running the full suite, then a manual local smoke run.

- [ ] **Step 1: Add the import**

In `main.py`, add `MOTOR_BASE_URL` to the `config` import block and import the motor client:

```python
from machine_vision_client.config import (
    LOCAL_DEV,
    MOTOR_BASE_URL,
    RGB_H,
    RGB_SOURCE,
    RGB_W,
    WEB_HOST,
    WEB_PORT,
)
from machine_vision_client.control.motor_http import MotorHttpClient
```

- [ ] **Step 2: Construct + start the motor client and pass it to the server**

Replace the server-construction block:

```python
    server = HeatWebServer(bus, pipeline, WEB_HOST, WEB_PORT)
    server.start()
```

with:

```python
    motor = MotorHttpClient(MOTOR_BASE_URL)
    motor.start()
    server = HeatWebServer(bus, pipeline, WEB_HOST, WEB_PORT, motor=motor)
    server.start()
    print(f"[control] motor commands -> {MOTOR_BASE_URL}")
```

- [ ] **Step 3: Stop the motor client on shutdown**

In the `finally:` block, add `motor.stop()` alongside the existing cleanup:

```python
    finally:
        motor.stop()
        pipeline.stop()
        visible.release()
```

- [ ] **Step 4: Verify the module imports and the suite passes**

Run: `cd laptop && ../.venv/bin/python -c "import machine_vision_client.main"`
Expected: no output, exit 0.

Run: `cd laptop && ../.venv/bin/python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add laptop/src/machine_vision_client/main.py
git commit -m "feat: wire MotorHttpClient into main loop (start/stop, pass to web server)"
```

---

## Task 7: Delete OpenCV `DrivePanel`, fix `controller.py`

**Files:**
- Delete: `laptop/src/machine_vision_client/control/drive_panel.py`
- Modify: `laptop/src/machine_vision_client/control/controller.py`
- Test: `laptop/tests/test_controller.py`

- [ ] **Step 1: Write the failing test**

Create `laptop/tests/test_controller.py`:

```python
from machine_vision_client.control import controller


def test_controller_exports_motor_stack():
    assert hasattr(controller, "MotorHttpClient")
    assert hasattr(controller, "DriveVector")


def test_controller_no_longer_exports_opencv_panel():
    assert not hasattr(controller, "DrivePanel")
    assert not hasattr(controller, "CAR_WIN")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_controller.py -v`
Expected: FAIL — `test_controller_no_longer_exports_opencv_panel` fails because `controller` still re-exports `DrivePanel`/`CAR_WIN`.

- [ ] **Step 3: Rewrite `controller.py` and delete `drive_panel.py`**

Replace the entire contents of `controller.py` with:

```python
"""Car drive controller — re-exports the HTTP motor stack used by the app."""

from machine_vision_client.control.motor_http import DriveVector, MotorHttpClient

__all__ = ["DriveVector", "MotorHttpClient"]
```

Delete the OpenCV panel:

```bash
git rm laptop/src/machine_vision_client/control/drive_panel.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd laptop && ../.venv/bin/python -m pytest tests/test_controller.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Verify nothing else references the deleted symbols**

Run: `cd /Users/ethan/Desktop/SKKU/senior_capstone && grep -rn "DrivePanel\|CAR_WIN\|drive_panel" laptop/src/machine_vision_client laptop/tests`
Expected: no output (exit 1). (Scope to the package dir, not `laptop/src`, to skip the stale `*.egg-info/SOURCES.txt` build artifact.)

- [ ] **Step 6: Commit**

```bash
git add laptop/src/machine_vision_client/control/controller.py laptop/tests/test_controller.py
git commit -m "refactor: remove OpenCV DrivePanel; web UI replaces it"
```

---

## Task 8: Full verification + manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `cd laptop && ../.venv/bin/python -m pytest -q`
Expected: all tests pass (33 prior + the new config/controller/web tests), no warnings.

- [ ] **Step 2: Manual smoke (local dev, no hardware)**

Run: `cd /Users/ethan/Desktop/SKKU/senior_capstone && HEAT_LOCAL=1 .venv/bin/python heat_algorithm`

Open `http://localhost:8000` in a browser and confirm:
- Two camera feeds appear on top (RGB from webcam; thermal mock).
- The drive control panel (joystick + buttons) appears below.
- The "motor offline" badge shows (no motor board in local dev) while feeds keep streaming — confirms control degrades independently of vision.
- Pressing WASD / dragging the joystick triggers `POST /control/drive` (visible in the server console as request logs); these will error against no board, which is expected in local dev.

Stop with Ctrl-C; confirm clean shutdown (`motor.stop()` runs without hanging).

- [ ] **Step 3: Final commit (if any smoke fixes were needed)**

```bash
git add -A
git commit -m "chore: unified web interface verified (sub-project A complete)"
```

---

## Notes for the implementer

- Run every command from the repo root or `laptop/` as shown; the venv lives at `/Users/ethan/Desktop/SKKU/senior_capstone/.venv`. Always invoke `../.venv/bin/python -m pytest`, never bare `pytest` (see CLAUDE.md venv shebang note).
- `MotorHttpClient` already owns its transport thread, TTL deadman, and auto-stop. Do **not** add a second drive loop in the web server — the browser only updates a setpoint via `/control/drive`.
- Sub-project B (unified firmware) is out of scope for this plan; see the spec's follow-on section.
