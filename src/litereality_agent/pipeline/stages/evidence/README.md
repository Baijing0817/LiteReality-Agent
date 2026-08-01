# Evidence stage

The evidence stage turns capture frames and RoomPlan surfaces into stable visual references used by
authoring: rectified wall images, floor/ceiling evidence, known/unknown masks, and selected views.

```bash
uv run litereality stage evidence run/<scene>
uv run litereality stage evidence run/<scene> --force
```

The stage requires a completed seed and writes under
`run/<scene>/realism_authoring/surface_ref/`. Rendering and image-selection implementations live in
`services/rendering`; this package owns only evidence-stage orchestration and artifact policy.
