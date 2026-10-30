-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

Format: 3.0 (native)
Source: gcc-mingw-w64
Binary: gcc-mingw-w64-bootstrap, gcc-mingw-w64, gcc-mingw-w64-i686, gcc-mingw-w64-i686-posix, gcc-mingw-w64-i686-win32, gcc-mingw-w64-x86-64, gcc-mingw-w64-x86-64-posix, gcc-mingw-w64-x86-64-win32, gcc-mingw-w64-ucrt64, g++-mingw-w64, g++-mingw-w64-i686, g++-mingw-w64-i686-posix, g++-mingw-w64-i686-win32, g++-mingw-w64-x86-64, g++-mingw-w64-x86-64-posix, g++-mingw-w64-x86-64-win32, g++-mingw-w64-ucrt64, gfortran-mingw-w64, gfortran-mingw-w64-i686, gfortran-mingw-w64-i686-posix, gfortran-mingw-w64-i686-win32, gfortran-mingw-w64-x86-64, gfortran-mingw-w64-x86-64-posix, gfortran-mingw-w64-x86-64-win32, gfortran-mingw-w64-ucrt64, gobjc-mingw-w64, gobjc-mingw-w64-i686, gobjc-mingw-w64-i686-posix, gobjc-mingw-w64-i686-win32, gobjc-mingw-w64-x86-64, gobjc-mingw-w64-x86-64-posix, gobjc-mingw-w64-x86-64-win32, gobjc-mingw-w64-ucrt64, gobjc++-mingw-w64, gobjc++-mingw-w64-i686, gobjc++-mingw-w64-i686-posix, gobjc++-mingw-w64-i686-win32, gobjc++-mingw-w64-x86-64,
 gobjc++-mingw-w64-x86-64-posix, gobjc++-mingw-w64-x86-64-win32, gobjc++-mingw-w64-ucrt64, gnat-mingw-w64, gnat-mingw-w64-i686, gnat-mingw-w64-i686-posix, gnat-mingw-w64-i686-win32, gnat-mingw-w64-x86-64, gnat-mingw-w64-x86-64-posix, gnat-mingw-w64-x86-64-win32, gnat-mingw-w64-ucrt64, gcc-mingw-w64-i686-posix-runtime, gcc-mingw-w64-i686-win32-runtime, gcc-mingw-w64-x86-64-posix-runtime, gcc-mingw-w64-x86-64-win32-runtime, gcc-mingw-w64-ucrt64-runtime,
 gcc-mingw-w64-base
Architecture: any all
Version: 27
Maintainer: Stephen Kitt <skitt@debian.org>
Homepage: https://www.gnu.org/software/gcc/
Standards-Version: 4.7.2
Vcs-Browser: https://salsa.debian.org/mingw-w64-team/gcc-mingw-w64
Vcs-Git: https://salsa.debian.org/mingw-w64-team/gcc-mingw-w64.git
Build-Depends: binutils-mingw-w64-i686 (>= 2.30~), binutils-mingw-w64-ucrt64, binutils-mingw-w64-x86-64 (>= 2.30~), bison, debhelper-compat (= 10), flex, g++-14 <!stage1>, gcc-14-source, gnat-14 [alpha amd64 arm64 armel armhf hppa i386 mips64el mipsel ppc64 ppc64el riscv64 s390x sh4 sparc64 x32] <!stage1>, libelf-dev, libgmp-dev, libisl-dev, libmpc-dev, libmpfr-dev, mingw-w64-i686-dev <!stage1>, mingw-w64-ucrt64-dev <!stage1>, mingw-w64-x86-64-dev <!stage1>, xz-utils, zlib1g-dev
Package-List:
 g++-mingw-w64 deb devel optional arch=all profile=!stage1
 g++-mingw-w64-i686 deb devel optional arch=all profile=!stage1
 g++-mingw-w64-i686-posix deb devel optional arch=any profile=!stage1
 g++-mingw-w64-i686-win32 deb devel optional arch=any profile=!stage1
 g++-mingw-w64-ucrt64 deb devel optional arch=any profile=!stage1
 g++-mingw-w64-x86-64 deb devel optional arch=all profile=!stage1
 g++-mingw-w64-x86-64-posix deb devel optional arch=any profile=!stage1
 g++-mingw-w64-x86-64-win32 deb devel optional arch=any profile=!stage1
 gcc-mingw-w64 deb devel optional arch=all profile=!stage1
 gcc-mingw-w64-base deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-bootstrap deb devel optional arch=any
 gcc-mingw-w64-i686 deb devel optional arch=all profile=!stage1
 gcc-mingw-w64-i686-posix deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-i686-posix-runtime deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-i686-win32 deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-i686-win32-runtime deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-ucrt64 deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-ucrt64-runtime deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-x86-64 deb devel optional arch=all profile=!stage1
 gcc-mingw-w64-x86-64-posix deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-x86-64-posix-runtime deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-x86-64-win32 deb devel optional arch=any profile=!stage1
 gcc-mingw-w64-x86-64-win32-runtime deb devel optional arch=any profile=!stage1
 gfortran-mingw-w64 deb devel optional arch=all profile=!stage1
 gfortran-mingw-w64-i686 deb devel optional arch=all profile=!stage1
 gfortran-mingw-w64-i686-posix deb devel optional arch=any profile=!stage1
 gfortran-mingw-w64-i686-win32 deb devel optional arch=any profile=!stage1
 gfortran-mingw-w64-ucrt64 deb devel optional arch=any profile=!stage1
 gfortran-mingw-w64-x86-64 deb devel optional arch=all profile=!stage1
 gfortran-mingw-w64-x86-64-posix deb devel optional arch=any profile=!stage1
 gfortran-mingw-w64-x86-64-win32 deb devel optional arch=any profile=!stage1
 gnat-mingw-w64 deb devel optional arch=all profile=!stage1
 gnat-mingw-w64-i686 deb devel optional arch=all profile=!stage1
 gnat-mingw-w64-i686-posix deb devel optional arch=alpha,amd64,arm64,armel,armhf,hppa,i386,mips64el,mipsel,ppc64,ppc64el,riscv64,s390x,sh4,sparc64,x32 profile=!stage1
 gnat-mingw-w64-i686-win32 deb devel optional arch=alpha,amd64,arm64,armel,armhf,hppa,i386,mips64el,mipsel,ppc64,ppc64el,riscv64,s390x,sh4,sparc64,x32 profile=!stage1
 gnat-mingw-w64-ucrt64 deb devel optional arch=alpha,amd64,arm64,armel,armhf,hppa,i386,mips64el,mipsel,ppc64,ppc64el,riscv64,s390x,sh4,sparc64,x32 profile=!stage1
 gnat-mingw-w64-x86-64 deb devel optional arch=all profile=!stage1
 gnat-mingw-w64-x86-64-posix deb devel optional arch=alpha,amd64,arm64,armel,armhf,hppa,i386,mips64el,mipsel,ppc64,ppc64el,riscv64,s390x,sh4,sparc64,x32 profile=!stage1
 gnat-mingw-w64-x86-64-win32 deb devel optional arch=alpha,amd64,arm64,armel,armhf,hppa,i386,mips64el,mipsel,ppc64,ppc64el,riscv64,s390x,sh4,sparc64,x32 profile=!stage1
 gobjc++-mingw-w64 deb devel optional arch=all profile=!stage1
 gobjc++-mingw-w64-i686 deb devel optional arch=all profile=!stage1
 gobjc++-mingw-w64-i686-posix deb devel optional arch=any profile=!stage1
 gobjc++-mingw-w64-i686-win32 deb devel optional arch=any profile=!stage1
 gobjc++-mingw-w64-ucrt64 deb devel optional arch=any profile=!stage1
 gobjc++-mingw-w64-x86-64 deb devel optional arch=all profile=!stage1
 gobjc++-mingw-w64-x86-64-posix deb devel optional arch=any profile=!stage1
 gobjc++-mingw-w64-x86-64-win32 deb devel optional arch=any profile=!stage1
 gobjc-mingw-w64 deb devel optional arch=all profile=!stage1
 gobjc-mingw-w64-i686 deb devel optional arch=all profile=!stage1
 gobjc-mingw-w64-i686-posix deb devel optional arch=any profile=!stage1
 gobjc-mingw-w64-i686-win32 deb devel optional arch=any profile=!stage1
 gobjc-mingw-w64-ucrt64 deb devel optional arch=any profile=!stage1
 gobjc-mingw-w64-x86-64 deb devel optional arch=all profile=!stage1
 gobjc-mingw-w64-x86-64-posix deb devel optional arch=any profile=!stage1
 gobjc-mingw-w64-x86-64-win32 deb devel optional arch=any profile=!stage1
Checksums-Sha1:
 2171842749126ae72b6b073986454e35ed3181f8 36248 gcc-mingw-w64_27.tar.xz
Checksums-Sha256:
 c1bf57cbe5f952ee5a7fa8b3e91dd031474e5ce61f468628f48b00e5bcbe8e30 36248 gcc-mingw-w64_27.tar.xz
Files:
 5b4867bd944fdb63d259a5abbe551149 36248 gcc-mingw-w64_27.tar.xz

-----BEGIN PGP SIGNATURE-----

iQIzBAEBCgAdFiEEnPVX/hPLkMoq7x0ggNMC9Yhtg5wFAmfErWMACgkQgNMC9Yht
g5weDA//Y6P3x5LdlROFdEWCrEd3VKQVFDhHflZ++RsZGpNzhsB36XeTN5d+/1y4
FMYpAwTZHR7spsJPc7wzNTTBwNzxDtu3CfECDRjJgAtHavcmqFWTLTsaZdN4c7Dx
Fv8x+sqNvv074E0E+Iv/vonAikzwRDHS3UTDBaIotgvKrn4+iAZoMASBwEJ3lohA
obnjpasdxBT3URHhoCOZF18unQeODFHQpvQM4oGWjue9ktBpv/itfdq7YyquZMJT
K1RER30gHeT/KYn13pbwcmAhfm2ESZeXCM/qVC7OQmUQMo7NCPf1ZipbhtOPykPy
hpLleMdzJM3uuXieZVqJwewidpftgBEMgXaB8GcFIZUvkaL1tCnOcoU6GEc9UrFY
+hHZzpmfV7iR2ou4l1c0Us5/GOckJ/QsTMNhgs/AcpU+/iu7nHvaPcwjQJt606Uo
+1HICOZK21IwTvoLkq2w6c8I4soMRkT+4xvqm59AS7JJAkOrmKs8S0jgfR9/40Wn
pwqQsTnZS4UzYj1ENf/W3xWgCtGzpynDI4kl1Lg+tSTV9p89yjzltUnPrMmOcICr
LAL8FtWDHhl/3RqGQbAkuK5ovodxQymujCJM3mEiKi3v0NL8m3dSNNhxXQ5GqPv7
Rn8MhS8cajyEKb82tG65rnwrjwOUFn+g0nJfTLTZvTyoyCQvNEI=
=0n8y
-----END PGP SIGNATURE-----
