"""Call planner: logical call + logical arguments + model -> a validated plan.

Pure function of the library data: no I/O. The plan is what the step executor
(``ola.instrument.Instrument.run``) runs; ``Plan.interpret`` turns the raw results of the
executor back into the logical value defined by the schema.

Steps follow ``ola.steps.Step``: ``{"op": "write"|"query"|"delay", "text", "ms",
"timeout_ms", "returns"}``. See ``Instruments_LIB/schema/README.md`` for the library side
(single ``syntax`` or ``steps``, ``map``, ``response_map``, ``bool``, ``split``).
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .call_errors import (
    CallNotSupportedError,
    InvalidArgumentError,
    ResponseNotRecognisedError,
    ValueNotHandledError,
)
from .library import Library, resolve_model_commands
from .steps import Step

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_RETURNS = {"string", "float", "int", "binary"}
_TRUE = {"1", "ON", "TRUE", "YES"}
_FALSE = {"0", "OFF", "FALSE", "NO"}


@dataclass
class Plan:
    """A validated call, ready for the executor."""

    call: str
    model_id: str
    access: str = "scpi"
    steps: List[Dict[str, Any]] = field(default_factory=list)
    driver: Optional[Dict[str, Any]] = None
    result: Dict[str, Any] = field(default_factory=lambda: {"from_step": None})
    # translation of the answer (from the library) and its logical type (from the schema)
    response: Dict[str, Any] = field(default_factory=dict)
    logical_result: Optional[Dict[str, Any]] = None
    logical_values: Optional[List[str]] = None

    def interpret(self, raw_results: List[Any]) -> Any:
        """Turn the executor's raw results into the logical value of the call."""
        idx = self.result.get("from_step")
        if idx is None:
            return None
        try:
            value = raw_results[idx]
        except (IndexError, TypeError):
            raise ResponseNotRecognisedError(
                f"call '{self.call}' has no result at step {idx}", call=self.call, step_index=idx
            )
        resp = self.response
        if "split" in resp:
            parts = str(value).strip().split(resp["split"])
            i = resp.get("index", 0)
            if i >= len(parts):
                raise ResponseNotRecognisedError(
                    f"call '{self.call}': answer {value!r} has no element {i}",
                    call=self.call,
                    step_index=idx,
                )
            value = parts[i].strip()
            value = _convert(value, resp.get("return_type", "string"), self.call, idx)
        if "bool" in resp:
            text = str(value).strip().upper()
            if text in {str(t).upper() for t in resp["bool"].get("true", [])}:
                return True
            if text in {str(t).upper() for t in resp["bool"].get("false", [])}:
                return False
            raise ResponseNotRecognisedError(
                f"call '{self.call}': answer {value!r} is not a recognised boolean",
                call=self.call,
                step_index=idx,
            )
        if "response_map" in resp:
            table = resp["response_map"]
            text = str(value).strip()
            if text in table:
                return table[text]
            folded = {k.upper(): v for k, v in table.items()}
            if text.upper() in folded:
                return folded[text.upper()]
            raise ResponseNotRecognisedError(
                f"call '{self.call}': answer {value!r} is not in the response map "
                f"of {self.model_id}",
                call=self.call,
                step_index=idx,
            )
        if self.logical_values is not None and str(value).strip() not in self.logical_values:
            raise ResponseNotRecognisedError(
                f"call '{self.call}': answer {value!r} is not one of {self.logical_values} "
                f"(no response_map for {self.model_id})",
                call=self.call,
                step_index=idx,
            )
        return value


def _convert(value: Any, return_type: str, call: str, idx: int) -> Any:
    try:
        if return_type == "int":
            return int(float(str(value).strip()))
        if return_type == "float":
            return float(str(value).strip())
    except ValueError as exc:
        raise ResponseNotRecognisedError(
            f"call '{call}': cannot read {value!r} as {return_type}",
            call=call,
            step_index=idx,
            cause=exc,
        )
    return value


def _fmt_number(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return format(float(value), ".12g")


def _logical_value(
    name: str, arg_spec: Dict[str, Any], value: Any, types: Dict[str, Any], call: str
) -> Any:
    """Check and normalise one logical argument against its schema definition."""
    t = arg_spec["type"]
    kind = types.get(t, {}).get("kind")
    try:
        if t == "int":
            if isinstance(value, bool) or (isinstance(value, float) and value != int(value)):
                raise ValueError
            value = int(value)
        elif t == "float":
            if isinstance(value, bool):
                raise ValueError
            value = float(value)
        elif t == "string":
            value = str(value)
        elif kind == "bool":
            if isinstance(value, str):
                up = value.strip().upper()
                if up in _TRUE:
                    value = True
                elif up in _FALSE:
                    value = False
                else:
                    raise ValueError
            elif not isinstance(value, (bool, int)):
                raise ValueError
            else:
                value = bool(value)
        elif kind == "enum":
            value = str(value).strip().upper()
            value = types[t].get("aliases", {}).get(value, value)
            if value not in types[t]["values"]:
                raise InvalidArgumentError(
                    f"argument '{name}' of '{call}': {value!r} is not one of {types[t]['values']}",
                    call=call,
                )
    except (ValueError, TypeError) as exc:
        raise InvalidArgumentError(
            f"argument '{name}' of '{call}': {value!r} is not a valid {t}", call=call, cause=exc
        )
    if t in ("int", "float"):
        if "min" in arg_spec and value < arg_spec["min"]:
            raise InvalidArgumentError(
                f"argument '{name}' of '{call}': {value} < minimum {arg_spec['min']}", call=call
            )
        if "max" in arg_spec and value > arg_spec["max"]:
            raise InvalidArgumentError(
                f"argument '{name}' of '{call}': {value} > maximum {arg_spec['max']}", call=call
            )
    return value


def _to_text(
    name: str,
    value: Any,
    arg_spec: Optional[Dict[str, Any]],
    pdef: Dict[str, Any],
    types: Dict[str, Any],
    model_id: str,
    call: str,
) -> str:
    """Translate one logical value into the text the instrument expects."""
    t = (arg_spec or {}).get("type")
    kind = types.get(t, {}).get("kind")
    table = pdef.get("map")
    if table is not None:
        found, text = _lookup(table, value)
        if found:
            return text
        if pdef.get("map_default") != "pass":
            raise ValueNotHandledError(
                f"value {value!r} of argument '{name}' is not handled by model "
                f"{model_id} (call '{call}')",
                call=call,
            )
    if kind == "bool" or isinstance(value, bool):
        text = "ON" if value else "OFF"
        allowed = pdef.get("values")
        if allowed and text not in allowed:
            raise ValueNotHandledError(
                f"value {value!r} of argument '{name}' is not handled by model "
                f"{model_id} (call '{call}')",
                call=call,
            )
        return text
    if isinstance(value, (int, float)):
        return _fmt_number(value)
    text = str(value)
    allowed = pdef.get("values")
    # a list of accepted texts is enforced for enum/string arguments (numbers may use keywords)
    if allowed and (kind == "enum" or t in (None, "string")):
        if text not in [str(v) for v in allowed]:
            raise ValueNotHandledError(
                f"value {value!r} of argument '{name}' is not handled by model "
                f"{model_id} (call '{call}'); "
                f"the library has no map and the model accepts {allowed}",
                call=call,
            )
    return text


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


def _evaluate(expression: str, values: Dict[str, Any], call: str) -> float:
    """Evaluate a derived-parameter formula: numbers, names of logical arguments, + - * / **
    and parentheses only (no function calls, no attributes)."""

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return -ev(node.operand) if isinstance(node.op, ast.USub) else ev(node.operand)
        raise ValueError(f"unsupported element in formula {expression!r}")

    try:
        return ev(ast.parse(expression, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, KeyError) as exc:
        raise InvalidArgumentError(
            f"call '{call}': cannot compute {expression!r} with {values}: {exc}",
            call=call,
            cause=exc,
        )


def _lookup(table: Dict[str, Any], value: Any):
    """Find ``value`` in a library ``map``. Keys are strings; numbers match numerically
    (``"20000000"`` matches 2e7), booleans use the keys ``"true"``/``"false"``."""
    if isinstance(value, bool):
        key = "true" if value else "false"
        return (key in table), (str(table[key]) if key in table else None)
    if isinstance(value, (int, float)):
        for k, v in table.items():
            try:
                if float(k) == float(value):
                    return True, str(v)
            except ValueError:
                continue
        return False, None
    key = str(value)
    if key in table:
        return True, str(table[key])
    return False, None


def _substitute(template: str, texts: Dict[str, str], call: str) -> str:
    def repl(m):
        name = m.group(1)
        if name not in texts:
            raise InvalidArgumentError(f"call '{call}' needs argument '{name}'", call=call)
        return texts[name]

    return _PLACEHOLDER.sub(repl, template)


def plan_call(
    library: Library,
    model_id: str,
    call: str,
    args: Optional[Dict[str, Any]] = None,
    *,
    readback: bool = False,
) -> Plan:
    """Plan one logical call for one model.

    ``readback=True`` plans the query half of a ``set`` call (read the setting back).
    Raises CALL-001 (call/model not supported), CALL-002 (value not handled by this model),
    CALL-003 (invalid argument).
    """
    args = dict(args or {})
    ref = library.find_model(model_id)
    if ref is None:
        raise CallNotSupportedError(f"model {model_id!r} is not in the library", call=call)
    definition = resolve_model_commands(ref.series, ref.model).get(call)
    if definition is None:
        raise CallNotSupportedError(f"call '{call}' is not supported by {model_id}", call=call)

    schema = library.schema(ref.category) or {"calls": {}, "types": {}}
    types = schema.get("types", {})
    spec = schema["calls"].get(call)
    access = ref.model.get("access", "scpi")

    # ---- arguments: validate against the schema (or, without a schema, the library parameters)
    if spec is not None:
        schema_args = spec.get("args", {})
    else:
        schema_args = {
            n: {"type": p.get("type", "string")}
            for n, p in (definition.get("parameters") or {}).items()
        }
    kind = spec["kind"] if spec else None
    if kind == "query" or readback or (spec is None and not definition.get("set")):
        half_name = "query"
    else:
        half_name = "set"
    unknown = set(args) - set(schema_args)
    if unknown:
        raise InvalidArgumentError(
            f"call '{call}': unknown argument(s) {sorted(unknown)}", call=call
        )
    logical: Dict[str, Any] = {}
    for name, aspec in schema_args.items():
        if (name not in args or args[name] is None) and "default" in aspec:
            args[name] = aspec["default"]
        if name in args and args[name] is not None:
            logical[name] = _logical_value(name, aspec, args[name], types, call)
        elif aspec.get("required", True) and _uses_arg(definition, name, half_name):
            raise InvalidArgumentError(f"call '{call}' needs argument '{name}'", call=call)

    # ---- driver calls are delegated, with the logical (validated) arguments
    if "driver" in definition:
        return Plan(
            call=call,
            model_id=model_id,
            access="driver",
            driver={"function": definition["driver"]["function"], "args": logical},
            result={"from_step": 0},
        )
    if access == "driver":
        raise CallNotSupportedError(
            f"call '{call}' has no driver implementation in {model_id}", call=call
        )

    # ---- the chosen half
    half = definition.get(half_name)
    if not half:
        raise CallNotSupportedError(
            f"call '{call}' has no {half_name} half in {model_id}", call=call
        )

    # ---- translate arguments into text
    pdefs = definition.get("parameters") or {}
    texts = {
        n: _to_text(n, v, schema_args.get(n), pdefs.get(n, {}), types, model_id, call)
        for n, v in logical.items()
    }
    # derived parameters: one logical argument drives several placeholders of the library
    for dname, ddef in pdefs.items():
        src = ddef.get("from")
        if "expr" in ddef:
            names = src if isinstance(src, list) else [src]
            if all(n in logical for n in names):
                texts[dname] = _fmt_number(_evaluate(ddef["expr"], logical, call))
            continue
        if src is not None and src in logical:
            found, text = _lookup(ddef.get("map", {}), logical[src])
            if not found:
                raise ValueNotHandledError(
                    f"value {logical[src]!r} of argument '{src}' is not handled by model "
                    f"{model_id} "
                    f"(call '{call}', placeholder '{dname}')",
                    call=call,
                )
            texts[dname] = text

    # ---- build the steps
    steps: List[Dict[str, Any]] = []
    if "steps" in half:
        for raw in half["steps"]:
            s = dict(raw)
            if "text" in s:
                s["text"] = _substitute(s["text"], texts, call)
            steps.append(_validated(s, call))
    else:
        text = _substitute(half["syntax"], texts, call)
        if half_name == "query":
            rt = half.get("return_type", "string")
            returns = rt if rt in _RETURNS else "string"
            if "split" in half:
                returns = "string"
            steps.append(_validated({"op": "query", "text": text, "returns": returns}, call))
        else:
            steps.append(_validated({"op": "write", "text": text}, call))

    # ---- which step carries the answer, and how to interpret it
    query_idx = [i for i, s in enumerate(steps) if s["op"] == "query"]
    from_step = half.get("result_step", query_idx[-1] if query_idx else None)
    response = {k: half[k] for k in ("response_map", "bool", "split", "index") if k in half}
    if "split" in response:
        response["return_type"] = half.get("return_type", "string")
    logical_values = None
    result_spec = spec.get("result") if (spec and half_name == "query") else None
    if result_spec and types.get(result_spec.get("type"), {}).get("kind") == "enum":
        logical_values = types[result_spec["type"]]["values"]
    return Plan(
        call=call,
        model_id=model_id,
        access="scpi",
        steps=steps,
        result={"from_step": from_step},
        response=response,
        logical_result=result_spec,
        logical_values=logical_values,
    )


def _uses_arg(definition: Dict[str, Any], name: str, half_name: str) -> bool:
    """True if the chosen half of the library definition uses placeholder ``name``."""
    h = definition.get(half_name)
    if not h:
        return False
    texts = [h.get("syntax", "")] + [s.get("text", "") for s in h.get("steps", [])]
    return any(name in _PLACEHOLDER.findall(t or "") for t in texts)


def _validated(step: Dict[str, Any], call: str) -> Dict[str, Any]:
    try:
        s = Step.from_dict(step)
    except (ValueError, TypeError) as exc:
        raise InvalidArgumentError(
            f"call '{call}': invalid step in the library: {exc}", call=call, cause=exc
        )
    return {k: v for k, v in step.items() if v is not None} if s else step
