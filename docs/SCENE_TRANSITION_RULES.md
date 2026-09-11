# Deterministic scene transition rules

`continue` keeps scene id, location, clothing, body state, and props, then
changes only explicit fields. `partial` also preserves unspecified fields;
replace clothing clears all old base and outerwear, while layer clothing keeps
the inner base. `new_scene` uses default-clear/allowlist-inherit.

New scenes inherit character identity, relationship, memory, stable hair/makeup,
persistent injury, explicitly carried objects, and explicitly persistent
emotion. They clear old location/environment/props, outfit, pose, action,
held objects, expression, lighting/camera, sweat, dirt, wetness, temporary
fatigue, and previous image scene continuity.

Shower sets cleanliness clean, sweat none, and dirt none. A terminal “just
finished shower” action ends damp unless `final_wetness` says otherwise. If a
composite transaction later changes clothes, moves, or starts the destination
activity, its final wetness is dry. Exercise without a shower never becomes
clean automatically. Injury is not cleared by scene change.

Example:

```json
{
  "transition_type": "new_scene",
  "actions": [
    {"type": "shower"},
    {"type": "replace_outfit", "preset": "clean_casual"},
    {"type": "move", "location": "图书馆"},
    {"type": "start_activity", "activity": "在图书馆休闲玩耍"}
  ]
}
```

Agent call:

```bash
avatarctl transition --action shower --replace-outfit clean_casual \
  --location 图书馆 --activity 在图书馆休闲玩耍
```

Add `--render --no-send` for a transactional test generation. Production use
must omit `--no-send` only when real delivery is intended and authorized.

