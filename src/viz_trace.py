# viz_anim.py
import json
from pathlib import Path


def build_viz_trace(processes: dict):
    """
    Build a trace list for web animation from manager.get_processes().

    Example trace element:
      { "id": "JOB-1", "stage": "Proc_Build",
        "resource": "3DPrinter_1", "t0": 10.0, "t1": 40.0 }
    """
    trace = []

    for proc_name, proc in processes.items():
        # Iterate completed jobs in each process
        for job in getattr(proc, "completed_jobs", []):
            for step in getattr(job, "processing_history", []):
                s = step.get("start_time")
                e = step.get("end_time")
                if s is None or e is None:
                    continue

                trace.append(
                    {
                        "id": f"JOB-{job.id_job}",
                        "stage": step.get("process", proc_name),
                        "resource": step.get("resource_name"),
                        "t0": float(s),
                        "t1": float(e),
                    }
                )

    # Sort by id and start time
    trace.sort(key=lambda x: (x["id"], x["t0"]))
    return trace


def export_animation_html(trace, filename="factory_animation.html"):
    """
    Create an HTML + JS file from the trace list for local viewing.
    """
    # Convert trace to JSON string
    trace_json = json.dumps(trace, ensure_ascii=False)

    # Per-process coordinates (adjust positions later if needed)
    html_template = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <title>3D Print Farm Animation</title>
  <style>
    body {{
      font-family: sans-serif;
      background: #111;
      color: #eee;
    }}
    #wrapper {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      margin-top: 10px;
    }}
    #controls {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    button {{
      padding: 4px 10px;
      border-radius: 4px;
      border: none;
      cursor: pointer;
    }}
    canvas {{
      background: #222;
      border: 1px solid #444;
    }}
  </style>
</head>
<body>
  <div id="wrapper">
    <h2>3D 프린팅 팜 공정 애니메이션</h2>
    <div id="controls">
      <button id="playPauseBtn">⏸ Pause</button>
      <label>속도:
        <input id="speedInput" type="range" min="0.1" max="5" step="0.1" value="1" />
        <span id="speedLabel">1.0x</span>
      </label>
      <span id="timeLabel"></span>
    </div>
    <canvas id="factoryCanvas" width="1000" height="400"></canvas>
  </div>

  <script>
    // ====== Trace data from Python ======
    const TRACE = {trace_json};

    // ====== Process -> screen position mapping ======
    const STATION_LAYOUT = {{
      "Proc_Build":         {{ x: 100,  y: 80,  label: "Build" }},
      "Proc_Wash1":         {{ x: 260,  y: 80,  label: "Wash1" }},
      "Proc_Dry1":          {{ x: 420,  y: 80,  label: "Dry1" }},
      "Proc_SupportRemoval":{{ x: 580,  y: 80,  label: "Support" }},
      "Proc_Inspect":       {{ x: 740,  y: 80,  label: "Inspect" }},
      "Proc_Wash2":         {{ x: 260,  y: 220, label: "Wash2" }},
      "Proc_Dry2":          {{ x: 420,  y: 220, label: "Dry2" }},
      "Proc_UV":            {{ x: 580,  y: 220, label: "UV" }}
    }};

    const canvas = document.getElementById("factoryCanvas");
    const ctx = canvas.getContext("2d");
    const playPauseBtn = document.getElementById("playPauseBtn");
    const speedInput = document.getElementById("speedInput");
    const speedLabel = document.getElementById("speedLabel");
    const timeLabel = document.getElementById("timeLabel");

    // Simulation time range
    let simMin = Infinity;
    let simMax = -Infinity;
    for (const e of TRACE) {{
      if (e.t0 < simMin) simMin = e.t0;
      if (e.t1 > simMax) simMax = e.t1;
    }}
    if (!isFinite(simMin)) {{
      simMin = 0;
      simMax = 1;
    }}

    let simNow = simMin;
    let speed = parseFloat(speedInput.value); // minutes/second
    let playing = true;

    function uniqueJobIds() {{
      const s = new Set();
      for (const e of TRACE) s.add(e.id);
      return Array.from(s);
    }}
    const JOB_IDS = uniqueJobIds();

    function getStageAt(jobId, t) {{
      // Stage where the job resides at time t
      for (const e of TRACE) {{
        if (e.id === jobId && e.t0 <= t && t <= e.t1) {{
          return e.stage;
        }}
      }}
      return null;
    }}

    function drawStations() {{
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      for (const [name, pos] of Object.entries(STATION_LAYOUT)) {{
        ctx.strokeStyle = "#888";
        ctx.lineWidth = 1;
        ctx.strokeRect(pos.x - 40, pos.y - 20, 80, 40);

        ctx.fillStyle = "#fff";
        ctx.fillText(pos.label || name, pos.x, pos.y - 28);
      }}
    }}

    function drawJobs() {{
      // Offset rows slightly to reduce overlap
      const rowHeight = 16;

      JOB_IDS.forEach((jobId, idx) => {{
        const stage = getStageAt(jobId, simNow);
        if (!stage) return;
        const pos = STATION_LAYOUT[stage];
        if (!pos) return;

        const yOffset = ((idx % 3) - 1) * rowHeight; // -1,0,1
        const y = pos.y + yOffset;

        // Dot
        ctx.beginPath();
        ctx.arc(pos.x, y, 6, 0, Math.PI * 2);
        ctx.fillStyle = "#4caf50";
        ctx.fill();

        // Label (small)
        ctx.fillStyle = "#fff";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(jobId, pos.x + 10, y);
      }});
    }}

    function render() {{
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Background grid (optional)
      drawStations();
      drawJobs();

      timeLabel.textContent = "Sim Time: " + simNow.toFixed(1) + " min";
    }}

    let lastTs = null;
    function loop(timestamp) {{
      if (!lastTs) lastTs = timestamp;
      const dt = (timestamp - lastTs) / 1000; // seconds
      lastTs = timestamp;

      if (playing) {{
        simNow += dt * speed;
        if (simNow > simMax) simNow = simMin;
      }}

      render();
      requestAnimationFrame(loop);
    }}

    // Controls
    playPauseBtn.addEventListener("click", () => {{
      playing = !playing;
      playPauseBtn.textContent = playing ? "⏸ Pause" : "▶ Play";
    }});

    speedInput.addEventListener("input", () => {{
      speed = parseFloat(speedInput.value);
      speedLabel.textContent = speed.toFixed(1) + "x";
    }});

    // Start
    render();
    requestAnimationFrame(loop);
  </script>
</body>
</html>
"""
    Path(filename).write_text(html_template, encoding="utf-8")
    print(f"[viz_anim] Animation HTML saved to: {filename}")
