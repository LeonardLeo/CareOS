"""Check that module calls and module interfaces agree.

`terraform validate` does this and more, but it needs provider schemas from
registry.terraform.io. That is reachable from CI and not from every development environment,
and infrastructure that can only be checked in one place tends to be checked in neither.

So this covers the failure that actually happens when someone edits Terraform: a variable
renamed in a module and not at its call sites, an argument passed that no longer exists, a
required variable quietly dropped, or an output referenced after it was deleted. Every one of
those is a `terraform plan` that fails after a reviewer has already approved the diff.

Deliberately not a Terraform parser. It reads `variable`, `output`, and `module` blocks with
regular expressions, which is enough for the question being asked and would be the wrong tool
for any harder one. If this ever needs to understand expressions, delete it and depend on
`terraform validate` instead.

    python3 scripts/check_terraform_wiring.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

INFRA = Path(__file__).resolve().parent.parent / "infra"

#: `variable "name" {` at the start of a line.
VARIABLE_RE = re.compile(r'^variable\s+"([^"]+)"\s*\{', re.MULTILINE)
OUTPUT_RE = re.compile(r'^output\s+"([^"]+)"\s*\{', re.MULTILINE)
MODULE_RE = re.compile(r'^module\s+"([^"]+)"\s*\{', re.MULTILINE)

#: A `default = ...` anywhere inside a variable block makes it optional. Matched within the
#: block's own text rather than file-wide, so a default on one variable cannot make another
#: look optional.
DEFAULT_RE = re.compile(r"^\s*default\s*=", re.MULTILINE)

#: `module.<name>.<output>` used anywhere.
MODULE_OUTPUT_REF_RE = re.compile(r"\bmodule\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\b")


def _block_body(text: str, start: int) -> str:
    """Return the brace-balanced body beginning at the `{` on or after `start`."""
    opened = text.index("{", start)
    depth = 0
    for index in range(opened, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opened + 1 : index]
    raise ValueError("unbalanced braces")


def module_interface(directory: Path) -> tuple[dict[str, bool], set[str]]:
    """Variables (name -> has a default) and output names declared in `directory`."""
    variables: dict[str, bool] = {}
    outputs: set[str] = set()

    for path in sorted(directory.glob("*.tf")):
        text = path.read_text()
        for match in VARIABLE_RE.finditer(text):
            body = _block_body(text, match.end() - 1)
            variables[match.group(1)] = bool(DEFAULT_RE.search(body))
        outputs.update(m.group(1) for m in OUTPUT_RE.finditer(text))

    return variables, outputs


def module_calls(path: Path) -> list[tuple[str, str, set[str]]]:
    """(module label, resolved source directory, argument names) for each `module` block."""
    text = path.read_text()
    calls: list[tuple[str, str, set[str]]] = []

    for match in MODULE_RE.finditer(text):
        body = _block_body(text, match.end() - 1)
        source = re.search(r'^\s*source\s*=\s*"([^"]+)"', body, re.MULTILINE)
        if source is None:
            continue
        # Only top-level assignments. A nested one belongs to an inner block, not to the
        # module's own arguments.
        arguments = {
            m.group(1)
            for m in re.finditer(r"^  ([A-Za-z0-9_]+)\s*=", body, re.MULTILINE)
            if m.group(1) != "source"
        }
        calls.append((match.group(1), source.group(1), arguments))

    return calls


def main() -> int:
    problems: list[str] = []
    env_dirs = sorted(p for p in (INFRA / "envs").iterdir() if p.is_dir())
    if not env_dirs:
        print(f"no environments found under {INFRA / 'envs'}", file=sys.stderr)
        return 1

    checked = 0
    for env in env_dirs:
        for tf_file in sorted(env.glob("*.tf")):
            text = tf_file.read_text()
            declared_here = set()

            for label, source, arguments in module_calls(tf_file):
                declared_here.add(label)
                module_dir = (tf_file.parent / source).resolve()
                if not module_dir.is_dir():
                    problems.append(f"{tf_file}: module {label!r} source {source!r} not found")
                    continue

                variables, _ = module_interface(module_dir)
                checked += 1

                for argument in sorted(arguments - set(variables)):
                    problems.append(
                        f"{tf_file}: module {label!r} passes {argument!r}, "
                        f"which {source} does not declare"
                    )
                required = {name for name, has_default in variables.items() if not has_default}
                for missing in sorted(required - arguments):
                    problems.append(
                        f"{tf_file}: module {label!r} omits required variable {missing!r}"
                    )

            # Outputs referenced against what the target module actually declares. Catches an
            # output renamed in a module and still consumed by an environment.
            sources = {label: source for label, source, _ in module_calls(tf_file)}
            for reference in MODULE_OUTPUT_REF_RE.finditer(text):
                label, output = reference.group(1), reference.group(2)
                source = sources.get(label)
                if source is None:
                    continue
                module_dir = (tf_file.parent / source).resolve()
                if not module_dir.is_dir():
                    continue
                _, outputs = module_interface(module_dir)
                if output not in outputs:
                    problems.append(
                        f"{tf_file}: reads module.{label}.{output}, "
                        f"which {source} does not output"
                    )

    for problem in sorted(set(problems)):
        print(problem, file=sys.stderr)

    if problems:
        print(f"\n{len(set(problems))} problem(s)", file=sys.stderr)
        return 1

    print(f"{checked} module call(s) across {len(env_dirs)} environment(s): inputs and outputs agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
