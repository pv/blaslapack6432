blaslapack6432
==============

Wrapper library providing LP64 Fortran ABI for BLAS and partially for LAPACK by
forwarding calls to ILP64 libraries.

Full LAPACK wrapper coverage does not appear reasonable to provide, because not
all IWORK array sizes are easily known at the interface level, and can depend
on LAPACK internals.

The wrappers generally also write to all integer input variables, which may
limit some use cases.


Usage
-----

To build:

    $ make

It will download reference LAPACK sources and regenerate `blaslapack6432.c`,
which is a stand-alone source code file for the wrappers, and build a static
library with unwrapper routines from reference LAPACK.

