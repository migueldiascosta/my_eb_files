##
# Copyright 2009-2018 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for building and installing Siesta, implemented as an easyblock

@author: Miguel Dias Costa (National University of Singapore)
@author: Ake Sandgren (Umea University)
"""
import os
import stat

import easybuild.tools.toolchain as toolchain
from distutils.version import LooseVersion
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, apply_regex_substitutions, change_dir, copy_dir, copy_file, mkdir
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd


class EB_SSDFT(ConfigureMake):
    """
    Support for building/installing Siesta.
    - avoid parallel build for older versions
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra options for Siesta"""
        extra = {
            'with_transiesta': [True, "Build transiesta", CUSTOM],
            'with_utils': [True, "Build all utils", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars=extra)

    def configure_step(self):
        """
        Custom configure and build procedure for Siesta.
        - There are two main builds to do, siesta and transiesta
        - In addition there are multiple support tools to build
        """

        start_dir = self.cfg['start_dir']
        obj_dir = os.path.join(start_dir, '../Obj')
        arch_make = os.path.join(obj_dir, 'arch.make')
        bindir = os.path.join(start_dir, '../bin')

        par = '-j %s' % self.cfg['parallel']

        # enable OpenMP support if desired
        env_var_suff = ''
        if self.toolchain.options.get('openmp', None):
            env_var_suff = '_MT'

        scalapack = os.environ['LIBSCALAPACK' + env_var_suff]
        blacs = os.environ['LIBSCALAPACK' + env_var_suff]
        lapack = os.environ['LIBLAPACK' + env_var_suff]
        blas = os.environ['LIBBLAS' + env_var_suff]
        if get_software_root('imkl') or get_software_root('FFTW'):
            fftw = os.environ['LIBFFT' + env_var_suff]
        else:
            fftw = None

        regex_newlines = []
        regex_subs = [
            ('dc_lapack.a', ''),
            (r'^NETCDF_INTERFACE\s*=.*$', ''),
            ('libsiestaBLAS.a', ''),
            ('libsiestaLAPACK.a', ''),
            # Needed here to allow 4.1-b1 to be built with openmp
            (r"^(LDFLAGS\s*=).*$", r"\1 %s %s" % (os.environ['FCFLAGS'], os.environ['LDFLAGS'])),
        ]

        netcdff_loc = get_software_root('netCDF-Fortran')
        if netcdff_loc:
            # Needed for gfortran at least
            regex_newlines.append((r"^(ARFLAGS_EXTRA\s*=.*)$", r"\1\nNETCDF_INCFLAGS = -I%s/include" % netcdff_loc))

        if fftw:
            fft_inc, fft_lib = os.environ['FFT_INC_DIR'], os.environ['FFT_LIB_DIR']
            fppflags = r"\1\nFFTW_INCFLAGS = -I%s\nFFTW_LIBS = -L%s %s" % (fft_inc, fft_lib, fftw)
            regex_newlines.append((r'(FPPFLAGS\s*=.*)$', fppflags))

        # Make a temp installdir during the build of the various parts
        mkdir(bindir)

        # change to actual build dir
        mkdir(obj_dir)
        change_dir(obj_dir)

        # Populate start_dir with makefiles
        adjust_permissions(os.path.join(start_dir, 'obj_setup.sh'), stat.S_IXUSR, recursive=False, relative=True)
        run_cmd(os.path.join(start_dir, 'obj_setup.sh'), log_all=True, simple=True, log_output=True)

        # MPI?
        if self.toolchain.options.get('usempi', None):
            self.cfg.update('configopts', '--enable-mpi')

        # BLAS and LAPACK
        self.cfg.update('configopts', '--with-blas="%s"' % blas)
        self.cfg.update('configopts', '--with-lapack="%s"' % lapack)

        # ScaLAPACK (and BLACS)
        self.cfg.update('configopts', '--with-scalapack="%s"' % scalapack)
        self.cfg.update('configopts', '--with-blacs="%s"' % blacs)

        # NetCDF-Fortran
        if netcdff_loc:
            self.cfg.update('configopts', '--with-netcdf=-lnetcdff')

        # Configure is run in obj_dir, configure script is in ../
        adjust_permissions(os.path.join(start_dir, 'configure'), stat.S_IXUSR, recursive=False, relative=True)
        adjust_permissions(os.path.join(start_dir, 'FoX/configure'), stat.S_IXUSR, recursive=False, relative=True)

        # SSDFT version
        copy_file(os.path.join(start_dir, 'version.F90'), os.path.join(start_dir, 'version.F90.orig'))
        copy_file(os.path.join(start_dir, 'version_dmf.F90'), os.path.join(start_dir, 'version.F90'))

        super(EB_SSDFT, self).configure_step(cmd_prefix=start_dir)

        apply_regex_substitutions(arch_make, regex_subs)

        regex_subs_Makefile = [
            (r'CFLAGS\)-c', r'CFLAGS) -c'),
            (r'^VPATH=\.$', r'VPATH=%s' % start_dir),
            ]
        apply_regex_substitutions(os.path.join(start_dir, 'Makefile_dmf'), regex_subs_Makefile)

        run_cmd('make clean', log_all=True, simple=True, log_output=True)
        run_cmd('make %s -f %s/Makefile_dmf ssdft' % (par, start_dir), log_all=True, simple=True, log_output=True)

        copy_file(os.path.join(obj_dir, 'ssdft'), bindir)

    def build_step(self):
        """No build step for Siesta."""
        pass

    def install_step(self):
        """Custom install procedure for Siesta: copy binaries."""
        bindir = os.path.join(self.installdir, 'bin')
        copy_dir(os.path.join(self.cfg['start_dir'], '../bin'), bindir)

    def sanity_check_step(self):
        """Custom sanity check for Siesta."""

        bins = ['bin/ssdft']

        custom_paths = {
            'files': bins,
            'dirs': [],
        }
        custom_commands = []
        if self.toolchain.options.get('usempi', None):
            # make sure Siesta was indeed built with support for running in parallel
            custom_commands.append("echo 'SystemName test' | mpirun -np 2 ssdft 2>/dev/null | grep PARALLEL")

        super(EB_SSDFT, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
