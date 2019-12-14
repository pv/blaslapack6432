all: libblaslapack6432.a

libblaslapack6432.a: blaslapack6432.o
	ar cru $@ $^
	ranlib $@

blaslapack6432.f90: generate.py signatures.json signatures-override.json include.json Makefile
	python3 generate.py --src-symbol-suffix=_64

%.o: %.f90
	gfortran -shared -Os -std=f2003 -Wall -Werror -c -o $@ $^
