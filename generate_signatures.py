# -*- mode:python; coding: utf-8; eval: (blacken-mode) -*-
"""generate_signatures.py lapack_dir

Generate signature file `signatures.json` from reference BLAS and
LAPACK sources.

Download and unpack reference LAPACK (http://netlib.org/blas) sources,
and point this script to the unpacked directory.

"""

import re
import sys
import glob
import json
import pathlib
import argparse
import multiprocessing

from numpy.f2py.crackfortran import crackfortran

from generate import load_include


class UserError(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(usage=__doc__.strip())
    parser.add_argument("lapack_dir", type=pathlib.Path, help="LAPACK source directory")
    parser.add_argument("--no-parallel", action="store_true")
    args = parser.parse_args()

    lapack_dir = args.lapack_dir
    blas_dir = args.lapack_dir / "BLAS" / "SRC"

    if not (blas_dir / "daxpy.f").exists():
        raise UserError("{} is not a reference BLAS source directory".format(blas_dir))

    if not (lapack_dir / "SRC" / "dgetrf.f").exists():
        raise UserError(
            "{} is not a reference LAPACK source directory".format(lapack_dir)
        )

    names = load_include("include.json")

    signatures = {}

    blas_f_filenames = glob.glob(str(blas_dir / "*.f"))
    lapack_f_filenames = glob.glob(str(lapack_dir / "SRC" / "*.f"))

    filenames = sorted(blas_f_filenames + lapack_f_filenames)

    if args.no_parallel:
        pool = None
        pool_map = map
    else:
        pool = multiprocessing.Pool(multiprocessing.cpu_count())
        pool_map = pool.imap_unordered

    skipped_files = set(filenames)

    try:
        for filename, infos in pool_map(process_fortran, filenames):
            for info in infos:
                if info["name"] in names:
                    if filename in skipped_files:
                        skipped_files.remove(filename)
                    signatures[info["name"]] = info
    finally:
        if pool is not None:
            pool.terminate()

    signatures["skipped_files"] = sorted(skipped_files)

    with open("signatures.json", "w") as f:
        json.dump(signatures, f, indent=2, allow_nan=False, sort_keys=True)


def process_fortran(filename):
    infos = []

    # read comments to obtain dimension information
    dimension_info = {}
    intent_info = {}
    with open(filename, "r") as f:
        text = f.read()
        for line in text.splitlines():
            m = re.match(
                r"^\*>\s+([A-Z]+) is INTEGER array, dimension \(([A-Z]+)\)\.?\s*$",
                line,
                flags=re.I,
            )
            if m:
                dimension_info[m.group(1).lower()] = ("var", m.group(2).lower())

            m = re.match(
                r"^\*>\s+([A-Z]+) is INTEGER array, dimension \(min\(([A-Z]+),([A-Z]+)\)\)\.?\s*$",
                line,
                flags=re.I,
            )
            if m:
                dimension_info[m.group(1).lower()] = (
                    "min",
                    m.group(2).lower(),
                    m.group(3).lower(),
                )

            m = re.match(
                r"^\*>\s+([A-Z]+) is INTEGER array, dimension \(([0-9]+)\*min\(([A-Z]+),([A-Z]+)\)\)\.?\s*$",
                line,
                flags=re.I,
            )
            if m:
                dimension_info[m.group(1).lower()] = (
                    "mulmin",
                    int(m.group(2).lower()),
                    m.group(3).lower(),
                    m.group(4).lower(),
                )

            m = re.match(
                r"^\*>\s+([A-Z]+) is INTEGER array, dimension \(max\(1,([A-Z]+)\)\)\.?\s*$",
                line,
                flags=re.I,
            )
            if m:
                dimension_info[m.group(1).lower()] = ("var", m.group(2).lower())

            m = re.match(
                r"^\*>\s+\\param\[(in|out|in,out)\]\s+([A-Z]+)\s*$", line, flags=re.I,
            )
            if m:
                intent_info[m.group(2).lower()] = m.group(1).split(",")

    # parse with f2py
    for info in crackfortran(filename):
        # Drop unnecessary info
        for kw in ["body", "entry", "externals", "from", "interfaced", "sortvars"]:
            info.pop(kw, None)
        for varname, varinfo in info["vars"].items():
            for kw in ["check", "depend", "=", "attrspec"]:
                varinfo.pop(kw, None)

        # Determine integer array dimensions, if possible
        for varname, varinfo in info["vars"].items():
            if varinfo["typespec"] != "integer":
                continue

            dims = varinfo.get("dimension", [])

            if dims == ["*"]:
                dt, *di = dimension_info.get(varname, (None, None))

                if dt == "var" and di[0] in info["vars"]:
                    varinfo["dimension"] = di

                if dt == "min" and di[0] in info["vars"] and di[1] in info["vars"]:
                    varinfo["dimension"] = [{"min": di}]

                if dt == "mulmin" and di[1] in info["vars"] and di[2] in info["vars"]:
                    varinfo["dimension"] = [{"mulmin": di}]

            if varname in intent_info:
                varinfo["intent"] = intent_info[varname]

        infos.append(info)

    return filename, infos


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except UserError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
