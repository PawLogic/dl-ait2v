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


def convert_ui_to_api(ui_workflow, comfyui_url="http://127.0.0.1:8188"):
    """Convert UI-format workflow to API format for /prompt submission."""
    object_info = _get_object_info(comfyui_url)
    nodes = ui_workflow.get("nodes", [])
    links = ui_workflow.get("links", [])

    # link_id -> (source_node_id, source_output_slot)
    link_map = {}
    for link in links:
        link_map[link[0]] = (link[1], link[2])

    api = {}
    for node in nodes:
        if node.get("mode", 0) in (2, 4):
            continue

        class_type = node.get("type", "")
        if class_type in ("Reroute", "Note", "PrimitiveNode"):
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
                inputs[name] = [str(src_id), src_slot]
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
    """
    result = {}
    wi = 0  # widget_values index

    input_defs = node_info.get("input", {})
    for category in ("required", "optional"):
        cat = input_defs.get(category, {})
        if not isinstance(cat, dict):
            continue

        for name, spec in cat.items():
            if wi >= len(widget_values):
                break
            if name in connected_names:
                continue
            if not isinstance(spec, (list, tuple)) or len(spec) == 0:
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
