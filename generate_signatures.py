# -*- mode:python; coding: utf-8; eval: (blacken-mode) -*-
"""generate_signatures.py blas_dir lapack_dir

Generate signature file `signatures.json` from reference BLAS and
LAPACK sources.

Download and unpack reference Fortran BLAS (http://netlib.org/blas)
and LAPACK (http://netlib.org/blas) sources, and point this script to
the unpacked directories.

"""

import re
import sys
import glob
import json
import pathlib
import argparse
import multiprocessing

from numpy.f2py.crackfortran import crackfortran
from numpy.f2py import auxfuncs, cfuncs, f2py2e


class UserError(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(usage=__doc__.strip())
    parser.add_argument("blas_dir", type=pathlib.Path, help="BLAS source directory")
    parser.add_argument("lapack_dir", type=pathlib.Path, help="LAPACK source directory")
    args = parser.parse_args()

    blas_dir = args.blas_dir
    lapack_dir = args.lapack_dir

    if not (blas_dir / "daxpy.f").exists():
        raise UserError("{} is not a reference BLAS source directory".format(blas_dir))

    if not (lapack_dir / "SRC" / "dgetrf.f").exists():
        raise UserError(
            "{} is not a reference LAPACK source directory".format(lapack_dir)
        )

    signatures = {}

    blas_f_filenames = glob.glob(str(blas_dir / "*.f"))
    lapack_f_filenames = glob.glob(str(lapack_dir / "SRC" / "*.f"))

    names = load_include("include.json")

    multiprocessing.set_start_method("spawn")
    with multiprocessing.Pool(multiprocessing.cpu_count()) as pool:
        filenames = sorted(blas_f_filenames + lapack_f_filenames)
        for infos in pool.imap_unordered(process_fortran, filenames):
            # for infos in map(process_fortran, filenames):
            for info in infos:
                if info["name"] in names:
                    signatures[info["name"]] = info

    with open("signatures.json", "w") as f:
        json.dump(signatures, f, indent=2, allow_nan=False, sort_keys=True)


def process_fortran(filename):
    infos = []

    # read comments to obtain dimension information
    dimension_info = {}
    with open(filename, "r") as f:
        text = f.read()
        for line in text.splitlines():
            m = re.match(
                r"^\*>\s+([A-Z]+) is INTEGER array, dimension \((.+)\)\.?\s*$",
                line,
                flags=re.I,
            )
            if m:
                dimension_info[m.group(1).lower()] = m.group(2).lower()

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
                if varname == "iwork" and "liwork" in info["vars"]:
                    varinfo["dimension"] = ["liwork"]
                    continue

                if varname in dimension_info:
                    varinfo["dimension"] = [dimension_info[varname]]

                if "ld" + varname in info["vars"]:
                    varinfo["dimension"] = ["ld" + varname]
                    continue

        infos.append(info)

    return infos


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


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except UserError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
