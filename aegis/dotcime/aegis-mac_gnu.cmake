# Aegis user macros for machine aegis-mac + compiler gnu (conda-forge osx-arm64).
# Loaded after cime_config/machines/cmake_macros/gnu.cmake, so it can override it.

# gfortran/clang on arm64-apple-darwin do not implement -mcmodel=large
# (gnu.cmake adds it when CMAKE_SYSTEM_PROCESSOR is "arm64").
foreach (_flagvar CMAKE_C_FLAGS CMAKE_CXX_FLAGS CMAKE_Fortran_FLAGS)
  string(REPLACE "-mcmodel=large" "" ${_flagvar} "${${_flagvar}}")
endforeach()

# The C compiler is clang, but gnu.cmake adds gfortran-only checks to the C
# debug flags. clang ignores them (with an "argument unused" warning on every
# C file), so they give no checking; strip them from C (Fortran keeps them).
foreach (_gfortran_only "-fcheck=bounds" "-ffpe-trap=invalid,zero,overflow")
  string(REPLACE "${_gfortran_only}" "" CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG}")
endforeach()

# Compilers: MPICH wrappers and serial compilers from the conda env (on PATH).
# The C/C++ compilers are conda-forge clang; Fortran is conda-forge gfortran.
set(MPICC "mpicc")
set(MPICXX "mpicxx")
set(MPIFC "mpif90")
set(SCC "clang")
set(SCXX "clang++")
set(SFC "gfortran")

set(NetCDF_C_PATH "$ENV{AEGIS_E3SM_ENV}" CACHE FILEPATH "" FORCE)
set(NetCDF_Fortran_PATH "$ENV{AEGIS_E3SM_ENV}" CACHE FILEPATH "" FORCE)

# BLAS/LAPACK: E3SM's find_dep_packages.cmake calls find_package(BLAS/LAPACK);
# use Apple Accelerate from the macOS SDK explicitly. (The conda-forge
# OpenBLAS-backed libblas/liblapack in the env are only runtime deps of
# moab/tempest-remap.)
set(BLA_VENDOR "Apple")

# Find the conda-env shared libraries at run time.
string(APPEND CMAKE_EXE_LINKER_FLAGS " -Wl,-rpath,$ENV{AEGIS_E3SM_ENV}/lib")

# e3sm.exe is linked by mpicxx (clang++), whose -lm (libSystem) comes before
# gfortran's -lgcc, so gfortran's x**n helper __powidf2 would bind to Apple's
# compiler-rt copy. That copy evaluates 1/r even for n > 0, so 0.0**3 raises
# divide-by-zero, which -ffpe-trap (debug builds) turns into SIGILL on Apple
# silicon (seen in DATM, datm_comp_mod.F90). Listing gfortran's libgcc.a first
# makes these helpers come from libgcc, as in a gfortran-driven link.
execute_process(COMMAND gfortran -print-libgcc-file-name
                OUTPUT_VARIABLE _aegis_libgcc OUTPUT_STRIP_TRAILING_WHITESPACE)
if (NOT EXISTS "${_aegis_libgcc}")
  message(FATAL_ERROR "aegis-mac: cannot locate gfortran libgcc.a (got '${_aegis_libgcc}')")
endif()
string(APPEND CMAKE_EXE_LINKER_FLAGS " ${_aegis_libgcc}")

string(APPEND CMAKE_C_FLAGS_RELEASE " -O2")
string(APPEND CMAKE_CXX_FLAGS_RELEASE " -O2")
string(APPEND CMAKE_Fortran_FLAGS_RELEASE " -O2")

# E3SM's components/cmake/modules/FindHDF5.cmake restricts find_library to
# .so/.a suffixes, so on macOS it cannot find the conda-forge .dylib files.
# Resolving the cache variables here first makes its find_library a no-op.
find_library(HDF5_LIBRARIES NAMES libhdf5.dylib hdf5
             PATHS "$ENV{AEGIS_E3SM_ENV}/lib" NO_DEFAULT_PATH REQUIRED)
find_library(HDF5_HL_LIBRARIES NAMES libhdf5_hl.dylib hdf5_hl
             PATHS "$ENV{AEGIS_E3SM_ENV}/lib" NO_DEFAULT_PATH REQUIRED)
