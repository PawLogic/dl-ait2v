#!/usr/bin/env python3
"""
Convert ComfyUI UI-format workflow to API format.

UI format: saved from ComfyUI web interface (nodes array + links array)
API format: what ComfyUI /prompt endpoint accepts (node_id -> {class_type, inputs})

Requires ComfyUI to be running — uses /object_info to resolve widget input names.
Handles COMFY_DYNAMICCOMBO_V3 dynamic inputs (e.g., LTXVAddGuideMulti).
"""
import requests

_object_info_cache = None


def is_ui_format(workflow):
    """Detect if workflow is in UI format (vs API format)."""
    return (
        isinstance(workflow, dict)
        and "nodes" in workflow
        and isinstance(workflow.get("nodes"), list)
    )


def _resolve_set_get_nodes(nodes, link_map):
    """
    Build resolution maps for KJNodes SetNode/GetNode (frontend-only patterns).

    SetNode: stores a named value AND passes it through (transparent pass-through).
    GetNode: retrieves a named value by name.

    Returns:
      set_map:      {name: (src_node_id_str, src_slot)}   — active SetNodes by name
      set_node_map: {set_node_id_str: (src_id_str, slot)} — active SetNodes by node ID
      get_map:      {get_node_id_str: name}               — all GetNodes
    """
    set_map = {}
    set_node_map = {}
    get_map = {}
    for node in nodes:
        ct = node.get("type", "")
        widgets = node.get("widgets_values", [])
        if ct == "SetNode":
            if node.get("mode", 0) in (2, 4):
                continue  # muted SetNode → unavailable
            name = widgets[0] if widgets else None
            for inp in node.get("inputs", []):
                lid = inp.get("link")
                if lid is not None and lid in link_map:
                    src_id, src_slot = link_map[lid]
                    entry = (str(src_id), src_slot)
                    if name:
                        set_map[name] = entry
                    set_node_map[str(node["id"])] = entry
                    break
        elif ct == "GetNode":
            if widgets:
                get_map[str(node["id"])] = widgets[0]
    return set_map, set_node_map, get_map


def convert_ui_to_api(ui_workflow, comfyui_url="http://127.0.0.1:8188"):
    """Convert UI-format workflow to API format for /prompt submission."""
    object_info = _get_object_info(comfyui_url)
    nodes = ui_workflow.get("nodes", [])
    links = ui_workflow.get("links", [])

    # link_id -> (source_node_id, source_output_slot)
    link_map = {}
    for link in links:
        link_map[link[0]] = (link[1], link[2])

    # Resolve SetNode/GetNode: transparent pass-through and named variable patterns
    set_map, set_node_map, get_map = _resolve_set_get_nodes(nodes, link_map)
    if set_map:
        print(f"  SetNode/GetNode resolved: {list(set_map.keys())}")

    # Resolve PrimitiveNode: built-in constant nodes whose value should be inlined
    primitive_map = {}  # node_id_str → value
    for node in nodes:
        if node.get("type") == "PrimitiveNode" and node.get("mode", 0) not in (2, 4):
            widgets = node.get("widgets_values", [])
            if widgets:
                primitive_map[str(node["id"])] = widgets[0]

    api = {}
    for node in nodes:
        if node.get("mode", 0) in (2, 4):
            continue

        class_type = node.get("type", "")
        # SetNode/GetNode are frontend-only; skip them (their values are inlined below)
        if class_type in ("Reroute", "Note", "PrimitiveNode", "SetNode", "GetNode"):
            continue

        node_id = str(node["id"])
        inputs = {}
        connected_names = set()

        # ── 1. Connected inputs ──
        for inp_slot in node.get("inputs", []):
            name = inp_slot["name"]
            link_id = inp_slot.get("link")
            if link_id is not None and link_id in link_map:
                src_id, src_slot = link_map[link_id]
                src_id_str = str(src_id)
                # Resolve PrimitiveNode → inline constant value
                if src_id_str in primitive_map:
                    inputs[name] = primitive_map[src_id_str]
                    connected_names.add(name)
                    continue
                # Resolve GetNode → SetNode source (named variable pattern)
                elif src_id_str in get_map:
                    get_name = get_map[src_id_str]
                    if get_name in set_map:
                        src_id_str, src_slot = set_map[get_name]
                    # else: SetNode muted/missing → dangling ref, fix_dangling_refs handles it
                # Resolve direct SetNode reference → SetNode's source (pass-through)
                elif src_id_str in set_node_map:
                    src_id_str, src_slot = set_node_map[src_id_str]
                # After chain resolution, check again if resolved source is PrimitiveNode
                if src_id_str in primitive_map:
                    inputs[name] = primitive_map[src_id_str]
                else:
                    inputs[name] = [src_id_str, src_slot]
                connected_names.add(name)

        # ── 2. Widget values → named inputs ──
        widgets = node.get("widgets_values", [])
        if widgets and class_type in object_info:
            mapped = _map_widgets(
                object_info[class_type], widgets, connected_names
            )
            inputs.update(mapped)
        elif widgets and class_type not in object_info:
            print(
                f"  Warning: no object_info for '{class_type}', "
                f"widget values ({len(widgets)}) dropped"
            )

        api[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
            "_meta": {"title": node.get("title", class_type)},
        }

    print(f"  Converted {len(api)} nodes (skipped {len(nodes) - len(api)})")
    return api


def _map_widgets(node_info, widget_values, connected_names):
    """
    Map widget_values array to {name: value} dict.

    Handles:
    - Regular widget types (INT, FLOAT, STRING, BOOLEAN, combo list)
    - COMFY_DYNAMICCOMBO_V3 with dynamic sub-input expansion
    - control_after_generate companion widgets (skip)
    - dict-style widgets_values (some VHS nodes store {name: value} directly)
    """
    result = {}

    # VHS and some custom nodes use dict-style widgets_values: {input_name: value}
    if isinstance(widget_values, dict):
        for name, value in widget_values.items():
            if name not in connected_names and isinstance(value, (str, int, float, bool)):
                result[name] = value
        return result

    wi = 0  # widget_values index

    input_defs = node_info.get("input", {})
    for category in ("required", "optional"):
        cat = input_defs.get(category, {})
        if not isinstance(cat, dict):
            continue

        for name, spec in cat.items():
            if wi >= len(widget_values):
                break
            if not isinstance(spec, (list, tuple)) or len(spec) == 0:
                continue
            if name in connected_names:
                # Advance wi if this input also has a widget value slot
                if _is_widget_type(spec):
                    wi += 1
                    wi = _skip_control_widget(widget_values, wi)
                continue

            type_info = spec[0]

            # ── Dynamic combo: expand sub-inputs from selected option ──
            if type_info == "COMFY_DYNAMICCOMBO_V3":
                combo_val = widget_values[wi]
                result[name] = combo_val
                wi += 1

                # Find selected option's sub-inputs
                opts = spec[1].get("options", []) if len(spec) > 1 else []
                selected = None
                for opt in opts:
                    if str(opt.get("key")) == str(combo_val):
                        selected = opt
                        break

                if selected:
                    sub_defs = selected.get("inputs", {}).get("required", {})
                    for sub_name, sub_spec in sub_defs.items():
                        full_name = f"{name}.{sub_name}"
                        if full_name in connected_names:
                            continue
                        if _is_widget_type(sub_spec):
                            if wi >= len(widget_values):
                                break
                            result[full_name] = widget_values[wi]
                            wi += 1

                wi = _skip_control_widget(widget_values, wi)

            # ── Regular widget type ──
            elif _is_widget_type(spec):
                result[name] = widget_values[wi]
                wi += 1
                wi = _skip_control_widget(widget_values, wi)

    return result


def _skip_control_widget(widget_values, wi):
    """Skip 'control_after_generate' companion widget if present."""
    if (
        wi < len(widget_values)
        and isinstance(widget_values[wi], str)
        and widget_values[wi] in ("fixed", "increment", "decrement", "randomize")
    ):
        return wi + 1
    return wi


def _is_widget_type(spec):
    """Check if an input spec is a widget type (not a node connection)."""
    if not spec or not isinstance(spec, (list, tuple)) or len(spec) == 0:
        return False
    type_info = spec[0]
    if isinstance(type_info, list):
        return True
    if isinstance(type_info, str):
        return type_info in (
            "INT", "FLOAT", "STRING", "BOOLEAN", "COMBO",
            "COMFY_DYNAMICCOMBO_V3",
        )
    return False


def _get_object_info(comfyui_url):
    """Fetch and cache node type definitions from ComfyUI."""
    global _object_info_cache
    if _object_info_cache is None:
        r = requests.get(f"{comfyui_url}/object_info", timeout=30)
        r.raise_for_status()
        _object_info_cache = r.json()
        print(f"  Loaded object_info: {len(_object_info_cache)} node types")
    return _object_info_cache
