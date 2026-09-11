# State schema v0.2.4

Schema version 2 keeps `character`, legacy `visual`, legacy `internal`,
`continuity`, and `memory`, and adds:

| Partition | Lifetime | Important fields |
|---|---|---|
| `relationship` | Permanent; relationship events only | role, stage, trust, intimacy, attachment, dynamic, commitments, boundaries, names |
| `scene` | Scene | scene_id, location, environment, activity, time_of_day, props |
| `appearance` | Scene/stable mix | structured outfit (base/legwear/footwear/outerwear), hair, makeup, accessories |
| `physical` | Scene with persistent injury exception | cleanliness, wetness, sweat, dirt, fatigue, injury |
| `emotion` | Baseline plus immediate | baseline, current, intensity, reason, persist flag |
| `presentation` | Scene | pose, action, expression, gaze, held objects, lighting, camera |
| `continuity` | Transaction metadata | mode, scene_id, source revision/job, last image/prompt |
| `memory` | Long-lived | summary, shared experiences, stable preferences, unfinished items, recent events |

Legacy mapping:

| v0.2.3 | v0.2.4 |
|---|---|
| `internal.relationship_stage` | `relationship.stage` plus exact legacy value |
| `internal.trust` | `relationship.trust` |
| `internal.affection` | `relationship.intimacy`, `attachment`, plus exact legacy value |
| `internal.mood` | `emotion.baseline/current` |
| `internal.current_activity` | `scene.activity` |
| `visual.outfit/legwear/footwear` | `appearance.outfit` |
| `visual.hair/makeup` | `appearance.hair/makeup` |
| `visual.expression/pose/action` | `presentation` |
| `visual.scene` | `scene.location/environment` |
| `visual.lighting/camera` | `presentation.lighting/camera` |
| existing `continuity.*` | retained exactly and extended |
| `memory.recent_events` | retained exactly; long-term fields added |

The legacy partitions are compatibility views and are synchronized after fixed
transitions and legacy allowlisted updates.

Author maintenance has three distinct surfaces: `relationship-update` performs
a schema-validated partial update; legacy `update --set internal.relationship_*`
remains compatible; `relationship-overwrite` replaces the complete canonical
object without merge. Normal overwrite uses the schema above. Explicit
`AUTHOR-BREAK-GLASS` overwrite may carry future or repair structures while
retaining JSON-object, backup, atomic-write, and audit requirements.
