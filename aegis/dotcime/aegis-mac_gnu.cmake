# Aegis user macros for machine aegis-mac + compiler gnu (conda-forge osx-arm64).
# Loaded after cime_config/machines/cmake_macros/gnu.cmake, so it can override it.

# gfortran/clang on arm64-apple-darwin do not implement -mcmodel=large
# (gnu.cmake adds it when CMAKE_SYSTEM_PROCESSOR is "arm64").
foreach (_flagvar CMAKE_C_FLAGS CMAKE_CXX_FLAGS CMAKE_Fortran_FLAGS)
  string(REPLACE "-mcmodel=large" "" ${_flagvar} "${${_flagvar}}")
endforeach()

# Compilers: MPICH wrappers and serial compilers from the conda env (on PATH).
# The C/C++ compilers are conda-forge clang; Fortran is conda-forge gfortran.
set(MPICC "mpicc")
set(MPICXX "mpicxx")
set(MPIFC "mpif90")
set(SCC "clang")
set(SCXX "clang++")
set(SFC "gfortran")

set(NetCDF_C_PATH "$ENV{NETCDF_PATH}" CACHE FILEPATH "" FORCE)
set(NetCDF_Fortran_PATH "$ENV{NETCDF_PATH}" CACHE FILEPATH "" FORCE)

# BLAS/LAPACK from conda-forge (openblas-backed libblas/liblapack).
string(APPEND SLIBS " -L$ENV{AEGIS_E3SM_ENV}/lib -llapack -lblas")
string(APPEND CMAKE_EXE_LINKER_FLAGS " -Wl,-rpath,$ENV{AEGIS_E3SM_ENV}/lib")

string(APPEND CMAKE_C_FLAGS_RELEASE " -O2")
string(APPEND CMAKE_CXX_FLAGS_RELEASE " -O2")
string(APPEND CMAKE_Fortran_FLAGS_RELEASE " -O2")

# E3SM's components/cmake/modules/FindHDF5.cmake restricts find_library to
# .so/.a suffixes, so on macOS it cannot find the conda-forge .dylib files.
# Pre-seeding the cache variables makes find_library a no-op.
set(HDF5_LIBRARIES "$ENV{HDF5_ROOT}/lib/libhdf5.dylib" CACHE FILEPATH "" FORCE)
set(HDF5_HL_LIBRARIES "$ENV{HDF5_ROOT}/lib/libhdf5_hl.dylib" CACHE FILEPATH "" FORCE)
