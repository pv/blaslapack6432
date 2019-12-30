PYTHON=python3
FC=gfortran -fPIC
FOPT=-Os -g0
CC=gcc -fPIC
OPT=-Os -g0 -Wall -Werror -std=c89

SRC_PREFIX=
SRC_SUFFIX=64_

DST_PREFIX=
DST_SUFFIX=

CFLAGS = \
	-DBLAS_SYMBOL_PREFIX=$(SRC_PREFIX) \
	-DBLAS_SYMBOL_SUFFIX=$(SRC_SUFFIX) \
	-DBLASLAPACK6432_PREFIX=$(DST_PREFIX) \
	-DBLASLAPACK6432_SUFFIX=$(DST_SUFFIX)

LAPACK_SHA256SUM=106087f1bb5f46afdfba7f569d0cbe23dacb9a07cd24733765a0e89dbe1ad573

all: lapack.tar.gz libblaslapack6432.a

lapack.tar.gz:
	wget -O lapack.tar.gz.tmp https://codeload.github.com/Reference-LAPACK/lapack/tar.gz/v3.9.0
	echo "$(LAPACK_SHA256SUM)  lapack.tar.gz.tmp" | sha256sum -c
	mv -f lapack.tar.gz.tmp lapack.tar.gz

LAPACK: lapack.tar.gz
	rm -rf LAPACK lapack-3.9.0
	tar xzf lapack.tar.gz
	mv -f lapack-3.9.0 LAPACK
	touch LAPACK

signatures.json: LAPACK include.json signatures-override.json generate_signatures.py
	$(PYTHON) generate_signatures.py LAPACK

blaslapack6432.c: signatures.json include.json generate.py
	$(PYTHON) generate.py

libblaslapack6432.a: blaslapack6432.o LAPACK
	$(MAKE) -C . build_lapack_part

%.o: %.c
	$(CC) $(CFLAGS) $(OPT) -c -o $@ $^

%.o: %.f
	$(FC) $(FOPT) -c -o $@ $^

-include blaslapack6432.d

build_lapack_part: blaslapack6432.o $(SOURCES:%.f=%.o)
	echo $(SOURCES)
	ar cru libblaslapack6432.a $^
	ranlib libblaslapack6432.a

distclean:
	rm -rf LAPACK
	rm -f signatures.json lapack.tar.gz

clean:
	rm -f libblaslapack6432.a blaslapack6432.c blaslapack6432.d
	rm -f *.o LAPACK/SRC/*.o

.PHONY: build_lapack_part clean distclean
