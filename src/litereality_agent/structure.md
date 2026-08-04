# Package structure

The intended shape of the package — what each folder owns and why. This is the target we are
building toward, not a description of where every file sits today.

## agent

Everything the agents need to run:

- the tools we define for agents to use
- the tracing that records what they did
- the prompts that kick off each agent
- how tools get registered so agents can reach them

### Tools

1. **render_and_compare** — select a view, render it, and compare. Three levels of annotation:
   wall focus, object focus, or everything focus.
2. **grid** — draw a grid over an image for measurement, so the agent can locate something
   relatively precisely instead of estimating.
3. **compile** — make sure the Blender file we write actually compiles, with no bugs.
4. **select_view** — given the current focus, pick which views to look at and return their view
   indices, which rendering and comparison then use. Includes `wall_focus_view`.
5. **fetch_materials** — fetch materials from Poly Haven, with the option to change the
   material's main colour.
6. **critic** — make an overall judgement from the images: what makes this look bad, and what
   would make it better.

The source for all of these lives here, so the agent can use them directly. We can also reuse them
outside the agentic loop by calling into `agent/tools` ourselves.

### Tracing

Everything lands in one HTML page: every interaction, every tool call, every render.

## models

Off-the-shelf models that work on their own, without the pipeline. The ones this pipeline uses:
TRELLIS, procedural generation, and GroundingDINO.

Simple calls do not belong here — image generation, or an LLM making a quick judgement like
classification. Those stay embedded in the pipeline.

Runtimes are set up here too, so we can do things like call TRELLIS from Modal.

## pipeline

`scene_init` does the deterministic build-up and produces the `Room.py` folder. This is critical —
it is the seed stage.

After that, `agent authoring` is where the real loop happens. We define several stages for the
workflow, each of which is an agentic loop that uses the tools in `agent/tools` to get what we
want, and they run sequentially.

Last comes deterministic QC over the resulting `Room.py`. QC is part of the pipeline: if it fails,
an agent fixes `Room.py`, and we repeat until every check passes. So all the QC lives in this
folder too.

The whole pipeline exists to produce one thing — a good `Room.py` that has passed all quality
control.

## room_format

What we can do with a `Room.py` folder, whether or not agents have re-optimized it:

1. export to Blender files
2. export to GLB
3. render final videos — slightly duplicated with the rendering in `agent/tools`, but still worth
   keeping separate
4. export to a self-contained Three.js HTML page for viewing

### Where does the scene-editing demo go?

Under `room_format`, since it is more about what we do once we already have a room. It does not
change the original `Room.py` folder itself: it uses the tools defined under `agent/tools` to do
what we ask, then saves the result to a **new** folder rather than overwriting the old one.
Everything that happens in the pipeline folder overwrites the original `Room.py`.
