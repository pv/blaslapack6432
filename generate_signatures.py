# -*- mode:python; coding: utf-8; eval: (blacken-mode) -*-
"""generate_signatures.py blas_dir lapack_dir

Generate signature file `signatures.json` from reference BLAS and
LAPACK sources.

Download and unpack reference Fortran BLAS (http://netlib.org/blas)
and LAPACK (http://netlib.org/blas) sources, and point this script to
the unpacked directories.

"""

import os
import io
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

    multiprocessing.set_start_method("spawn")
    with multiprocessing.Pool(multiprocessing.cpu_count()) as pool:
        filenames = sorted(blas_f_filenames + lapack_f_filenames)
        for infos in pool.imap_unordered(process_fortran, filenames):
            # for infos in map(process_fortran, filenames):
            for info in infos:
                signatures[info["name"]] = info

    with open("signatures.json", "w") as f:
        json.dump(signatures, f, indent=2, allow_nan=False, sort_keys=True)


def process_fortran(filename):
    infos = []
    for info in crackfortran(filename):
        # Drop unnecessary info
        for kw in ["body", "entry", "externals", "from", "interfaced"]:
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

        infos.append(info)

    return infos


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except UserError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
