"""Tests for the four JSON files in .actor/ and their agreement with the code.

Plain Python, own runner, no pytest and no network. The point is that the
store page can never promise something the run does not deliver:

* the four files are valid JSON with the keys Apify expects;
* the charge events are exactly page-checked at 0.05 and change-detected at
  0.02, in the file and in src/main.py;
* every field listed in a dataset view is a field src/main.py really writes,
  read from the source with `ast`, not from a comment.

Run it from the Actor folder:

    ../../.venv/bin/python tests/test_schemas.py
"""

from __future__ import annotations

import ast
import json
import os
import sys
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ACTOR_DIR = os.path.join(ROOT, ".actor")
MAIN_PY = os.path.join(ROOT, "src", "main.py")

EXPECTED_EVENTS = {
    "page-checked": 0.05,
    "change-detected": 0.02,
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def load_json(name: str) -> dict:
    path = os.path.join(ACTOR_DIR, name)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main_module_ast() -> ast.Module:
    with open(MAIN_PY, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=MAIN_PY)


def constant_tuple(tree: ast.Module, name: str) -> list[str]:
    """Read a module-level tuple or list of strings from the source."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets and isinstance(node.value, (ast.Tuple, ast.List)):
                return [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                ]
    raise AssertionError("src/main.py has no module-level %s tuple" % name)


def constant_string(tree: ast.Module, name: str) -> str:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets and isinstance(node.value, ast.Constant):
                return str(node.value.value)
    raise AssertionError("src/main.py has no module-level %s constant" % name)


def pushed_fields(tree: ast.Module) -> list[str]:
    """The literal keys of the dict that `build_item` returns."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_item":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
                    keys = []
                    for key in inner.value.keys:
                        if not (
                            isinstance(key, ast.Constant)
                            and isinstance(key.value, str)
                        ):
                            raise AssertionError(
                                "build_item returns a dict with a non-literal key; "
                                "the views cannot be checked against it"
                            )
                        keys.append(key.value)
                    return keys
            raise AssertionError("build_item does not return a dict literal")
    raise AssertionError("src/main.py has no build_item function")


# --------------------------------------------------------------------------
# Tiny runner
# --------------------------------------------------------------------------

FAILURES: list[str] = []
PASSED = 0


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(name: str, func) -> None:
    global PASSED
    try:
        func()
    except Exception:  # noqa: BLE001 - the runner reports, it does not crash
        FAILURES.append(name)
        print("FAIL  %s" % name)
        print(traceback.format_exc())
    else:
        PASSED += 1
        print("ok    %s" % name)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_files_exist_and_are_valid_json() -> None:
    for name in (
        "actor.json",
        "input_schema.json",
        "dataset_schema.json",
        "output_schema.json",
    ):
        path = os.path.join(ACTOR_DIR, name)
        check(os.path.isfile(path), "missing .actor/%s" % name)
        loaded = load_json(name)
        check(isinstance(loaded, dict), ".actor/%s must be a JSON object" % name)


def test_actor_json_wiring() -> None:
    actor = load_json("actor.json")
    check(actor.get("actorSpecification") == 1, "actorSpecification must be 1")
    check(actor.get("name") == "page-change-monitor", "name must be page-change-monitor")
    check(
        actor.get("title") == "Website Change Monitor: Track Page Updates",
        "title must be Website Change Monitor: Track Page Updates",
    )
    check(str(actor.get("version")) == "0.1", "version must be 0.1")
    check(actor.get("input") == "./input_schema.json", "input must point at the schema")
    check(
        (actor.get("storages") or {}).get("dataset") == "./dataset_schema.json",
        "storages.dataset must point at dataset_schema.json",
    )
    check(
        actor.get("output") == "./output_schema.json",
        "output must point at output_schema.json",
    )
    check(actor.get("dockerfile") == "../Dockerfile", "dockerfile must be ../Dockerfile")
    check(
        os.path.isfile(os.path.join(ROOT, "Dockerfile")),
        "the Dockerfile referenced by actor.json must exist",
    )
    check(
        os.path.isfile(os.path.join(ROOT, "requirements.txt")),
        "requirements.txt must exist",
    )


def test_charge_events_and_prices() -> None:
    actor = load_json("actor.json")
    events = (actor.get("pay_per_event") or {}).get("actorChargeEvents") or {}
    check(
        set(events) == set(EXPECTED_EVENTS),
        "the charge events must be exactly %s, found %s"
        % (sorted(EXPECTED_EVENTS), sorted(events)),
    )
    for name, price in EXPECTED_EVENTS.items():
        found = events[name].get("eventPriceUsd")
        check(
            isinstance(found, (int, float)) and abs(float(found) - price) < 1e-9,
            "%s must cost US$ %.2f, found %r" % (name, price, found),
        )
        check(
            (events[name].get("eventTitle") or "").strip(),
            "%s needs an eventTitle" % name,
        )
        check(
            (events[name].get("eventDescription") or "").strip(),
            "%s needs an eventDescription" % name,
        )


def test_code_charges_the_same_event_names() -> None:
    tree = main_module_ast()
    in_code = {
        constant_string(tree, "EVENT_PAGE_CHECKED"),
        constant_string(tree, "EVENT_CHANGE_DETECTED"),
    }
    check(
        in_code == set(EXPECTED_EVENTS),
        "src/main.py charges %s, the schema declares %s"
        % (sorted(in_code), sorted(EXPECTED_EVENTS)),
    )
    source = open(MAIN_PY, "r", encoding="utf-8").read()
    check(
        "asyncio.wait_for(" in source and "CHARGE_TIMEOUT_SECONDS" in source,
        "every charge must be wrapped in asyncio.wait_for with a timeout",
    )
    check(
        "asyncio.TimeoutError" in source,
        "a charge that times out must be caught, not left to kill the run",
    )


def test_input_schema_fields() -> None:
    schema = load_json("input_schema.json")
    check(schema.get("schemaVersion") == 1, "schemaVersion must be 1")
    check(schema.get("type") == "object", "the input schema must be an object")
    props = schema.get("properties") or {}
    expected = {"urls", "requestDelaySeconds", "requestTimeoutSeconds", "excerptChars"}
    check(
        set(props) == expected,
        "the input must be exactly %s, found %s" % (sorted(expected), sorted(props)),
    )
    check(schema.get("required") == ["urls"], "urls must be the only required field")
    for name, field in props.items():
        check((field.get("title") or "").strip(), "%s needs a title" % name)
        check(
            len((field.get("description") or "").strip()) > 20,
            "%s needs a real description" % name,
        )
        check((field.get("editor") or "").strip(), "%s needs an editor" % name)
    # A required field carries a prefill, an optional one carries a default.
    check("prefill" in props["urls"], "urls needs a prefill example")
    for name in ("requestDelaySeconds", "requestTimeoutSeconds", "excerptChars"):
        check("default" in props[name], "%s needs a default" % name)

    tree = main_module_ast()
    defaults_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets
            ):
                defaults_node = node.value
    check(isinstance(defaults_node, ast.Dict), "src/main.py needs a DEFAULTS dict")
    code_defaults = {
        key.value: ast.literal_eval(value)
        for key, value in zip(defaults_node.keys, defaults_node.values)
        if isinstance(key, ast.Constant)
    }
    check(
        set(code_defaults) == expected,
        "DEFAULTS in src/main.py must cover exactly the input fields: %s vs %s"
        % (sorted(code_defaults), sorted(expected)),
    )
    for name in ("requestDelaySeconds", "requestTimeoutSeconds", "excerptChars"):
        check(
            code_defaults[name] == props[name]["default"],
            "default of %s differs: schema %r, code %r"
            % (name, props[name]["default"], code_defaults[name]),
        )


def test_dataset_views_match_what_the_code_writes() -> None:
    dataset = load_json("dataset_schema.json")
    check(dataset.get("actorSpecification") == 1, "actorSpecification must be 1")
    declared = set(((dataset.get("fields") or {}).get("properties") or {}))
    views = dataset.get("views") or {}
    check(views, "dataset_schema.json must declare at least one view")

    tree = main_module_ast()
    written = pushed_fields(tree)
    listed = constant_tuple(tree, "ITEM_FIELDS")
    check(
        set(written) == set(listed),
        "ITEM_FIELDS %s does not match the keys build_item writes %s"
        % (sorted(listed), sorted(written)),
    )
    check(
        declared == set(written),
        "dataset_schema fields %s do not match the written fields %s"
        % (sorted(declared), sorted(written)),
    )

    for view_name, view in views.items():
        fields = ((view.get("transformation") or {}).get("fields")) or []
        check(fields, "view %s lists no field" % view_name)
        unknown = [f for f in fields if f not in written]
        check(
            not unknown,
            "view %s promises field(s) the run never writes: %s"
            % (view_name, unknown),
        )
        display = ((view.get("display") or {}).get("properties")) or {}
        extra = [f for f in display if f not in fields]
        check(
            not extra,
            "view %s formats field(s) it does not select: %s" % (view_name, extra),
        )
        check((view.get("title") or "").strip(), "view %s needs a title" % view_name)

    overview = ((views.get("overview") or {}).get("transformation") or {}).get("fields")
    check(
        overview is not None and set(overview) == set(written),
        "the overview view must list exactly the written fields: %s vs %s"
        % (sorted(overview or []), sorted(written)),
    )


def test_output_schema() -> None:
    output = load_json("output_schema.json")
    check(
        output.get("actorOutputSchemaVersion") == 1,
        "actorOutputSchemaVersion must be 1",
    )
    props = output.get("properties") or {}
    check(props, "the output schema must declare properties")
    for name, field in props.items():
        template = field.get("template") or ""
        check(template.startswith("{{links."), "%s needs a links template" % name)
        check((field.get("title") or "").strip(), "%s needs a title" % name)
        check((field.get("description") or "").strip(), "%s needs a description" % name)
    check(
        "summary" in props,
        "the run summary written to the key-value store must be in the output",
    )
    source = open(MAIN_PY, "r", encoding="utf-8").read()
    check(
        'set_value("SUMMARY"' in source or "set_value(\n                \"SUMMARY\"" in source,
        "src/main.py must write the SUMMARY record the output schema points at",
    )


TESTS = [
    ("the four files exist and are valid JSON", test_files_exist_and_are_valid_json),
    ("actor.json wiring", test_actor_json_wiring),
    ("charge events and prices", test_charge_events_and_prices),
    ("the code charges the same event names", test_code_charges_the_same_event_names),
    ("input schema fields", test_input_schema_fields),
    ("dataset views match what the code writes", test_dataset_views_match_what_the_code_writes),
    ("output schema", test_output_schema),
]


def main() -> int:
    print("schema tests (no network)")
    for name, func in TESTS:
        run(name, func)
    total = len(TESTS)
    if FAILURES:
        print("RESULT: %d/%d passed, FAILED: %s" % (PASSED, total, ", ".join(FAILURES)))
        return 1
    print("RESULT: %d/%d passed, 0 failed" % (PASSED, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
