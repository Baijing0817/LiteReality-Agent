"""The public pipeline stage catalog, in execution order."""

from litereality_agent.pipeline.stage import Stage
from litereality_agent.pipeline.stages import (
    author,
    evidence,
    ingest,
    publish,
    quality,
    reconstruct,
    refine,
    seed,
)

STAGES = (
    Stage("ingest", ingest.run, is_complete=ingest.complete),
    Stage("reconstruct", reconstruct.run, ("ingest",), is_complete=reconstruct.complete),
    Stage("seed", seed.run, ("reconstruct",), is_complete=seed.complete),
    Stage("evidence", evidence.run, ("seed",), is_complete=evidence.complete),
    Stage("author", author.run, ("seed", "evidence"), is_complete=author.complete),
    Stage("refine", refine.run, ("author",), required=False, is_complete=refine.complete),
    Stage("quality", quality.run, ("author",), required=False, is_complete=quality.complete),
    Stage("publish", publish.run, ("author",), required=False, is_complete=publish.complete),
)

__all__ = ["STAGES"]
