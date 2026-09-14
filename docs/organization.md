# Repository organization and next fixes

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

## Recommended next work, in priority order

1. **Centralize workstation configuration.** Checkout paths, interpreters, model
   locations and data stores still appear in many presets and launchers. Expand
   the existing ignored workspace config and environment variables into one
   documented configuration convention. Compatibility links should be a migration
   aid, not a requirement for fresh installations.
2. **Version component contracts and tested revisions.** Document and validate the
   exchanged audio, image, video and story manifest schemas. Record input hashes,
   component Git revisions and environment versions with every run. The current
   runner fingerprints commands/configuration, not source or input contents.
3. **Label supported workflows and archive experiments.** Versioned SDXL/FLUX and
   accessory recipes remain valuable, but directory suffixes do not establish
   which variants are supported or deployed. Maintain a small supported-workflow
   index; move superseded source only after confirming installed service and data
   references. Keep historical recipes reproducible.
4. **Consolidate shared Colab/session infrastructure.** Authentication, token
   refresh, polling, keepalive and artifact download helpers overlap across
   components. Extract a small shared package with explicit interfaces after
   comparing behavioral differences. Do not merge them merely because filenames
   match. It does not yet justify another repository by itself.
5. **Separate durable data from checkouts consistently.** Existing large stores
   already live outside Git, but some workflows still generate logs/results beside
   source. Adopt a configurable data root with separate models, datasets, runs and
   credentials. Preserve manifests and provenance when relocating data.

These are proposed follow-up changes, not claims that runtime migration or
cross-model integration testing has been completed. Further repo splitting is not
the priority: keep shorts with LTX and publishing adapters with the coordinator
until they have independent consumers or release needs.
