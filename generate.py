# -*- mode:python; coding: utf-8; eval: (blacken-mode) -*-
"""generate.py

Generate wrapper source files.

"""

import os
import sys
import json
import textwrap
import argparse
import traceback

import jinja2


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
    args = parser.parse_args()

    signatures = load_signatures("signatures.json", "signatures-override.json")

    generate_signatures(signatures)


def generate_signatures(signatures):
    names = load_include("include.json")
    errors = []

    codes = []

    for name in names:
        try:
            item = signatures[name]
            item["name"]
        except KeyError:
            errors.append((name, "", "missing signature"))
            continue

        try:
            code = generate_code(item, prototype=True)
            code += "\n\n"
            code += generate_code(item)
        except UserError as exc:
            # Postpone error reporting
            errors.append((name, item, exc))
            continue

        codes.append(code)

    preamble = """
        /*
         * BLAS and partial LAPACK wrappers using 32-bit integers,
         * calling ILP64 routines, with possible symbol prefix/suffix.
         *
         * This file is autogenerated; do not edit manually.
         * See https://github.com/pv/blaslapack6432
         */
        #include <stdlib.h>
        #include <assert.h>

        #ifdef _MSC_VER
        typedef __int64 int64_t;
        #else
        #include <stdint.h>
        #endif

        #ifndef BLASLAPACK6432_PREFIX
        #define BLASLAPACK6432_PREFIX
        #endif

        #ifndef BLASLAPACK6432_SUFFIX
        #define BLASLAPACK6432_SUFFIX
        #endif

        #ifndef BLAS_SYMBOL_PREFIX
        #define BLAS_SYMBOL_PREFIX
        #endif

        #ifndef BLAS_SYMBOL_SUFFIX
        #define BLAS_SYMBOL_SUFFIX 64_
        #endif

        #define INT int
        #define SRC_INT int64_t
        #define NAME_EXPAND(prefix,name,suffix) prefix ## name ## _ ## suffix
        #define NAME_HELPER(prefix,name,suffix) NAME_EXPAND(prefix,name,suffix)

        #define FUNC(name) NAME_HELPER(BLASLAPACK6432_PREFIX,name,BLASLAPACK6432_SUFFIX)
        #define SRC_FUNC(name) NAME_HELPER(BLAS_SYMBOL_PREFIX,name,BLAS_SYMBOL_SUFFIX)

        #define MIN(a, b) ((a) < (b) ? (a) : (b))

        typedef struct { float re; float im; } c_t;
        typedef struct { double re; double im; } z_t;
        """
    preamble = textwrap.dedent(preamble).strip() + "\n\n"

    with open("blaslapack6432.c", "w") as f:
        f.write(preamble)

        for code in codes:
            f.write("\n\n")
            f.write(code)

    with open("blaslapack6432.d", "w") as f:
        seen = set()
        f.write("SOURCES = ")
        for fn in signatures["skipped_files"]:
            if os.path.basename(fn) in seen:
                continue
            if seen:
                f.write(" \\\n    ")
            seen.add(os.path.basename(fn))
            f.write(fn)

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


def generate_code(item, prototype=False):
    args = [dict(item["vars"][arg], name=arg) for arg in item["args"]]
    integer_args = [arg for arg in args if arg["typespec"] == "integer"]
    has_integer_array_args = any(arg.get("dimension") for arg in integer_args)

    fmt = {
        "double precision": "double",
        "real": "float",
        "complex": "c_t",
        "complex*16": "z_t",
    }

    def format_src_type(typespec):
        return dict(fmt, integer="SRC_INT", logical="SRC_INT",).get(typespec, "void")

    def format_dst_type(typespec):
        return dict(fmt, integer="INT", logical="INT").get(typespec, "void")

    if prototype:
        BLAS_FUNC = "SRC_FUNC"
        format_dst_type = format_src_type
    else:
        BLAS_FUNC = "FUNC"

    BLAS_SRC_FUNC = "SRC_FUNC"

    def format_array_size(dim_info):
        (dim_info,) = dim_info

        if isinstance(dim_info, dict):
            (value_type,) = dim_info.keys()
            (value,) = dim_info.values()
        else:
            try:
                return str(int(dim_info))
            except ValueError:
                return "*" + dim_info

        if value_type == "min":
            return "MIN(*{0}, *{1})".format(*value)
        elif value_type == "mulmin":
            return "{0} * (int64_t)MIN(*{1}, *{2})".format(*value)
        else:
            raise ValueError("Unknown dimension value: {!r}".format(dim_info))

    for arg in args:
        arg["dst_ctype"] = format_dst_type(arg["typespec"])
        arg["src_ctype"] = format_src_type(arg["typespec"])

        if arg["typespec"] == "integer":
            if "dimension" in arg:
                arg["array_size"] = format_array_size(arg["dimension"])
                arg["constant_dimension"] = "*" not in arg["array_size"]
            else:
                arg["constant_dimension"] = False

    for j, arg in enumerate(list(args)):
        if "intent" not in arg and arg["typespec"] == "integer":
            raise ValueError("Integer argument with unknown 'intent': {!r}".format(arg))

        if arg["typespec"] == "character":
            if arg.get("dimension"):
                raise UserError("Cannot deal with character arrays")
            args.append(dict(typespec="character_size", name="size{}".format(j)))

    template_src = """
       {%- if item.block == "function" -%}
           {{format_dst_type(item.prefix)}}
       {%- else -%}
           void
       {%- endif %}
       {{BLAS_FUNC}}({{item.name}})(
       {%- for arg in args -%}
           {%- if not loop.first %}, {% endif -%}
           {%- if arg.typespec == "character_size" -%}
           size_t {{arg.name}}
           {%- else -%}
           {{arg.dst_ctype}} *{{arg.name}}
           {%- endif -%}
       {%- endfor -%}
       )
       {%- if prototype -%}
          ;
       {%- else %}
       {
         {%- for arg in integer_args %}
           {% if arg.dimension and arg.constant_dimension -%}
             {{arg.src_ctype}} {{arg.name}}_tmp[{{arg.array_size}}];
           {% elif arg.dimension -%}
             {{arg.src_ctype}} *{{arg.name}}_tmp;
           {%- else -%}
             {{arg.src_ctype}} {{arg.name}}_tmp[1];
           {%- endif -%}
         {% endfor %}
         {%- if has_integer_array_args %}
           int64_t idx;
         {%- endif -%}
         {%- if item.block == "function" %}
           {{format_dst_type(item.prefix)}} return_value;
         {%- endif -%}
         {% for arg in integer_args -%}
           {%- if arg.dimension and not arg.constant_dimension %}
           {{arg.name}}_tmp = ({{arg.src_ctype}} *)calloc({{arg.array_size}}, sizeof({{arg.src_ctype}}));
           assert({{arg.name}}_tmp != NULL);
           {%- endif -%}
           {%- if "in" in arg.intent -%}
           {%- if arg.dimension %}
           for (idx = 0; idx < {{arg.array_size}}; ++idx) {{arg.name}}_tmp[idx] = ({{arg.src_ctype}}){{arg.name}}[idx];
           {%- else %}
           {{arg.name}}_tmp[0] = ({{arg.src_ctype}}){{arg.name}}[0];
           {%- endif -%}
           {%- endif %}
         {%- endfor -%}
         {%- if item.block == "function" %}
           {% if item.prefix == "integer" -%}
           return_value = ({{format_src_type(item.prefix)}}){{BLAS_SRC_FUNC}}({{item.name}})(
           {%- else -%}
           return_value = {{BLAS_SRC_FUNC}}({{item.name}})(
           {%- endif -%}
         {%- else %}
           {{BLAS_SRC_FUNC}}({{item.name}})(
         {%- endif %}
           {%- for arg in args -%}
             {%- if not loop.first %}, {% endif -%}
             {%- if arg.typespec == "character_size" -%}
               1
             {%- elif arg.typespec == "integer" -%}
               {{arg.name}}_tmp
             {%- else -%}
               {{arg.name}}
             {%- endif -%}
           {%- endfor -%}
         );
         {%- for arg in integer_args -%}
           {%- if "out" in arg.intent -%}
           {%- if arg.dimension %}
           for (idx = 0; idx < {{arg.array_size}}; ++idx) {{arg.name}}[idx] = ({{arg.dst_ctype}}){{arg.name}}_tmp[idx];
           {%- else %}
           {{arg.name}}[0] = ({{arg.dst_ctype}}){{arg.name}}_tmp[0];
           {%- endif %}
           {%- endif %}
           {%- if arg.dimension and not arg.constant_dimension %}
           free({{arg.name}}_tmp);
           {%- endif %}
         {%- endfor %}
         {%- if item.block == "function" %}
           return return_value;
         {%- endif %}
       }
       {% endif %}
    """

    template = jinja2.Template(textwrap.dedent(template_src))

    try:
        return template.render(locals())
    except Exception:
        raise UserError(traceback.format_exc())


def load_include(fn):
    with open(fn, "r") as f:
        include = json.load(f)

    def filter_comments(items):
        return [x for x in items if not x.startswith("#")]

    names = filter_comments(include["other"])

    for part in filter_comments(include["sd"]):
        names.append("s" + part)
        names.append("d" + part)

    for part in filter_comments(include["cz"]):
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
