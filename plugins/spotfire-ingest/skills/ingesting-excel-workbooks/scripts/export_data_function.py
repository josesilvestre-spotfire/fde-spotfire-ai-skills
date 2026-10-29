"""Stage 6: turn the reconciled calculation model into a data function script.

A Spotfire data function cannot import files that sit next to it, so this script
writes one self-contained file: the excel_compat functions the model uses, the
model code itself (unchanged, so the DXP runs the code that passed the
reconciliation), and the lines that map the data function's parameters to the
model's inputs and outputs.

The model declares its interface (see the scaffold):
    PARAMETERS        {"FlowRate": "Inputs!B3"}       value inputs (document properties)
    TABLE_PARAMETERS  {"SEGMENTS": "Segments!A2:D21"} table inputs
    SPOTFIRE_OUTPUTS  ["SEGMENT_RESULTS", "OutletPressure"]
    spotfire_outputs(result) -> {output name: DataFrame or value}

Usage:
    python export_data_function.py --model <ingest>/calc_model.py
        --out <app>/datafunctions/<file>.py [--name "Calculate Pressure Profile"]

Prints the inputs and outputs for the dataFunctions entry of spec.json.
Standard library only.
"""

import argparse
import ast
import json
import sys
from pathlib import Path


def _literal(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name
                                                for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def _names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | \
        {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def compat_subset(compat_source, needed):
    """The top-level definitions of excel_compat the model needs, with their own
    dependencies, in file order."""
    tree = ast.parse(compat_source)
    defs = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defs[target.id] = node
    keep, pending = set(), [n for n in needed if n in defs]
    while pending:
        name = pending.pop()
        if name in keep:
            continue
        keep.add(name)
        pending.extend(n for n in _names(defs[name]) if n in defs and n not in keep)
    lines = compat_source.splitlines()
    imports, out = [], []
    kept_nodes = [defs[k] for k in keep]
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append("\n".join(lines[node.lineno - 1:node.end_lineno]))
        elif node in kept_nodes:
            start = node.lineno - 1
            if getattr(node, "decorator_list", None):
                start = node.decorator_list[0].lineno - 1
            out.append("\n".join(lines[start:node.end_lineno]))
    return "\n".join(imports) + "\n\n\n" + "\n\n\n".join(out), sorted(keep)


def strip_model(source):
    """Remove the module docstring, the excel_compat import and the command-line
    block. Returns (code, docstring)."""
    tree = ast.parse(source)
    lines = source.splitlines()
    drop = set()
    doc = ast.get_docstring(tree) or ""
    if doc:
        first = tree.body[0]
        drop.update(range(first.lineno - 1, first.end_lineno))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "excel_compat":
            drop.update(range(node.lineno - 1, node.end_lineno))
        elif isinstance(node, ast.Import) and any(a.name == "excel_compat" for a in node.names):
            drop.update(range(node.lineno - 1, node.end_lineno))
        elif isinstance(node, ast.If) and "__name__" in ast.unparse(node.test):
            drop.update(range(node.lineno - 1, len(lines)))
    code = "\n".join(line for i, line in enumerate(lines) if i not in drop).strip()
    return code + "\n", doc


def export(model_path, out_path, name=None):
    model_path = Path(model_path)
    source = model_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    params = _literal(tree, "PARAMETERS") or {}
    tables = _literal(tree, "TABLE_PARAMETERS") or {}
    outputs = _literal(tree, "SPOTFIRE_OUTPUTS") or []
    if not outputs:
        raise ValueError("SPOTFIRE_OUTPUTS is empty: declare the data function outputs and "
                         "spotfire_outputs() in the model first")
    for pname in list(params) + list(tables) + list(outputs):
        if not pname.isidentifier():
            raise ValueError(f"'{pname}' is not a valid parameter name")
    compat_path = model_path.with_name("excel_compat.py")
    if not compat_path.exists():
        compat_path = Path(__file__).with_name("excel_compat.py")
    compat, kept = compat_subset(compat_path.read_text(encoding="utf-8"), _names(tree))
    body, doc = strip_model(source)
    title = name or "Calculation model"
    parts = [f'"""{title}.', ""]
    if doc:
        parts += [doc.replace('"' * 3, "'" * 3), ""]
    parts += [
        "The model code below is the code that was reconciled against the workbook's",
        "values; the Excel behaviour functions it uses come first.",
        '"""',
        "",
        "# Excel behaviour functions used by the model",
        compat,
        "",
        "",
        "# Calculation model",
        body,
        "",
        "# Data function inputs and outputs",
        "_inputs = {",
    ]
    for pname, key in params.items():
        parts.append(f"    {key!r}: {pname},")
    parts.append("}")
    parts.append("_tables = {")
    for pname, key in tables.items():
        parts.append(f"    {key!r}: {pname},")
    parts.append("}")
    parts.append("_outputs = spotfire_outputs(run(_inputs, _tables))")
    for oname in outputs:
        parts.append(f"{oname} = _outputs[{oname!r}]")
    text = "\n".join(parts) + "\n"
    ast.parse(text)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    entry = {"inputs": [{"name": p, "type": "value", "bind": {"property": p}} for p in params] +
             [{"name": t, "type": "table", "bind": {"table": t, "columns": "*"}}
              for t in tables],
             "outputs": outputs, "excelCompatFunctions": kept}
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--name", help="data function name, Title Case verb + object")
    args = parser.parse_args()
    entry = export(args.model, args.out, args.name)
    print(f"data function script -> {args.out}")
    print(json.dumps(entry, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
