# -*- mode:python; coding: utf-8; eval: (blacken-mode) -*-
"""generate.py

Generate wrapper source files.

"""

import sys
import json
import textwrap
import argparse


class UserError(Exception):
    pass


class JsonMergeError(Exception):
    def __init__(self, main, override, keys):
        self.main = main
        self.override = override
        self.keys = keys
        super().__init__()

    def __str__(self):
        return "Json merge error in key {}:\nmain: {}\noverride: {}".format(
            "/".join(self.keys), self.main, self.override
        )


def main():
    parser = argparse.ArgumentParser(usage=__doc__.strip())
    parser.add_argument(
        "--src-symbol-suffix",
        dest="src_suffix",
        default="",
        help="Symbol suffix in the 'source' libraries.",
    )
    parser.add_argument(
        "--dst-symbol-suffix",
        dest="dst_suffix",
        default="",
        help="Symbol suffix in the 'destination' library to generate.",
    )
    parser.add_argument(
        "--src-symbol-prefix",
        dest="src_prefix",
        default="",
        help="Symbol prefix in the 'source' libraries.",
    )
    parser.add_argument(
        "--dst-symbol-prefix",
        dest="dst_prefix",
        default="",
        help="Symbol prefix in the 'destination' library to generate.",
    )
    args = parser.parse_args()

    signatures = load_signatures("signatures.json", "signatures-override.json")

    generate_signatures(
        signatures,
        src_suffix=args.src_suffix,
        src_prefix=args.src_prefix,
        dst_suffix=args.dst_suffix,
        dst_prefix=args.dst_prefix,
        integer_type="integer(kind=c_int64_t)",
    )


def generate_signatures(signatures, **kw):
    names = load_include("include.json")
    errors = []

    with open("blaslapack6432.f90", "w") as f:
        for name in names:
            try:
                info = signatures[name]
            except KeyError:
                errors.append((name, "", "missing signature"))
                continue

            try:
                code = generate_code(name, info, **kw)
            except UserError as exc:
                # Postpone error reporting
                errors.append((name, info, exc))
                continue

            f.write("\n\n")
            f.write(code)

    if errors:
        msgs = []

        for name, info, exc in errors:
            exc_fmt = textwrap.indent(str(exc), " " * 4)
            msg = (
                f"error: {name}: failed to generate wrapper code\n"
                f"    from info: {info!r}\n"
                f"{exc_fmt}"
            )
            msgs.append(msg)

        raise UserError("\n\n".join(msgs))


def generate_code(
    name, info, src_prefix, src_suffix, dst_prefix, dst_suffix, integer_type
):
    # Cannot have integer arguments with unknown dimension
    errors = []
    fix_suggestion = []

    src_name = src_prefix + info["name"] + src_suffix
    dst_name = dst_prefix + info["name"] + dst_suffix

    def map_src_type(fortran_type):
        if fortran_type == "complex*16":
            return "complex(16)"
        else:
            return fortran_type

    def map_type(fortran_type):
        if fortran_type == "integer":
            return integer_type, True
        else:
            return map_src_type(fortran_type), False

    for varname, varinfo in info["vars"].items():
        if varinfo["typespec"] == "integer" and "dimension" in varinfo:
            if len(varinfo["dimension"]) != 1:
                errors.append(f"{name}:{varname}: argument has more than one dimension")
            if "*" in varinfo["dimension"]:
                errors.append(
                    f"{name}:{varname}: integer argument with unknown dimension"
                )
                fix_suggestion.append(f'"{varname}": {{"dimension": ["???"]}}')

    if errors:
        msg = "\n".join(errors)
        if fix_suggestion:
            suggestion = f'"{name}": {{"vars": {{' + ",\n".join(fix_suggestion) + "}},"
            msg += "\nsuggestion: " + suggestion.replace("\n", "\nsuggestion: ")
        raise UserError(msg)

    code = ""

    if info["block"] == "subroutine":
        code += "subroutine {}({})\n".format(dst_name, ", &\n    ".join(info["args"]))
    elif info["block"] == "function":
        prefix, _ = map_type(info["prefix"])
        code += "{} function {}({})\n".format(
            prefix, dst_name, ", &\n    ".join(info["args"])
        )
    else:
        raise UserError("bad 'block' value")

    code += "  use iso_c_binding\n"

    tmp_vars = []
    tmp_assign = []
    tmp_rev_assign = []
    call_args = []

    for arg in info["args"]:
        typespec, is_int = map_type(info["vars"][arg]["typespec"])

        dimension = info["vars"][arg].get("dimension")
        if dimension is not None:
            code += "  {}, dimension(*) :: {}\n".format(typespec, arg)
        else:
            code += "  {} :: {}\n".format(typespec, arg)

        if is_int:
            if dimension is not None:
                assert len(dimension) == 1
                tmp_vars.append(
                    "  {}, dimension({}) :: {}_tmpbuf\n".format(
                        "integer", dimension[0], arg
                    )
                )
                sl = "(1:{})".format(dimension[0])
            else:
                tmp_vars.append("  {} :: {}_tmpbuf\n".format("integer", arg))
                sl = ""
            tmp_rev_assign.append("{}{} = {}_tmpbuf{}\n".format(arg, sl, arg, sl))

            if dimension is not None:
                tmp_assign.append("{}_tmpbuf{} = int({}{})\n".format(arg, sl, arg, sl))
            else:
                tmp_assign.append("{}_tmpbuf = int({})\n".format(arg, arg))
            call_args.append(arg + "_tmpbuf")
        else:
            call_args.append(arg)

    if info["block"] == "function":
        code += "  {} {}\n".format(map_src_type(info["prefix"]), src_name)
        code += "  external {}\n".format(src_name)

    code += "\n"
    for statement in tmp_vars:
        code += "  " + statement

    code += "\n"
    for statement in tmp_assign:
        code += "  " + statement

    if info["block"] == "subroutine":
        code += "  call {}({})\n".format(src_name, ", &\n    ".join(call_args))
    elif info["block"] == "function":
        code += "  {} = {}({})\n".format(
            dst_name, src_name, ", &\n    ".join(call_args)
        )

    code += "\n"
    for statement in tmp_rev_assign:
        code += "  " + statement

    if info["block"] == "subroutine":
        code += "end subroutine {}\n".format(dst_name)
    elif info["block"] == "function":
        code += "end function {}\n".format(dst_name)

    return code


def load_include(fn):
    with open(fn, "r") as f:
        include = json.load(f)

    names = include["other"]

    for part in include["sd"]:
        names.append("s" + part)
        names.append("d" + part)

    for part in include["cz"]:
        names.append("c" + part)
        names.append("z" + part)

    return names


def load_signatures(main_fn, override_fn):
    with open(main_fn, "r") as f:
        signatures = json.load(f)

    with open(override_fn, "r") as f:
        override = json.load(f)

    try:
        json_merge(signatures, override)
    except JsonMergeError as exc:
        raise UserError(str(exc))

    return signatures


def json_merge(main, override):
    if not isinstance(main, dict):
        return override

    if not isinstance(override, dict):
        raise JsonMergeError(main, override, ())

    for name, key in override.items():
        try:
            main[name] = json_merge(main.get(name), override[name])
        except JsonMergeError as exc:
            raise JsonMergeError(exc.main, exc.override, (name,) + exc.keys)

    return main


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except UserError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
