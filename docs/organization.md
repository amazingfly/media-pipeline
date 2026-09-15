# Repository organization

## Ownership

| Repository | Owns | Consumes |
| --- | --- | --- |
| [sa3](https://github.com/amazingfly/sa3) | Audio generation, training, library | Prompts and audio inputs |
| [images](https://github.com/amazingfly/images) | Image generation, LoRA training, reusable accessory validators | Prompts, references, model weights |
| [ltx-video](https://github.com/amazingfly/ltx-video) | Music-video generation, assembly, short selection | Still images and audio |
| [storybook-pipeline](https://github.com/amazingfly/storybook-pipeline) | Story compilation, scene selection/review, narration, story assembly | Image backends/assets and story JSON |
| [media-pipeline](https://github.com/amazingfly/media-pipeline) | Cross-repository scheduling, provenance, publishing adapters | Component commands and manifests |

Storybook and music-video generation are distinct consumers of image assets.
Story-specific sequencing belongs in storybook-pipeline; the general coordinator
schedules it as one component. `configs/storybook.example.json` shows that boundary.

## Implemented organization controls

- One workspace configuration supplies component roots, interpreters, data stores,
  and model/tool paths. See [workspace configuration](workspace.md).
- Every repository has a machine-checked `workflows.json` and readable support
  index. Historical code remains at its existing paths with explicit status.
- Shared Colab/session helpers have one canonical source package and verified
  standalone copies in each component. CI detects modified copies.
- Versioned artifact contracts and checkpoint v2 record file hashes, component
  source state, and Python environments. Resume detects stale inputs and outputs.
  See [contracts and provenance](contracts.md).

Durable storage is configurable; existing media and model stores remain in place.
Remote GPU environments and model outputs still require their normal integration
validation. Further repo splitting is unnecessary for these controls: shorts stay
with LTX, and publishing adapters stay with the coordinator.
