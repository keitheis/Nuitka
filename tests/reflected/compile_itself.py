#!/usr/bin/env python
#     Copyright 2014, Kay Hayen, mailto:kay.hayen@gmail.com
#
#     Python tests originally created or extracted from other peoples work. The
#     parts were too small to be protected.
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
#

import os, sys, shutil, tempfile, time, difflib, subprocess

# Find common code relative in file system. Not using packages for test stuff.
sys.path.insert(
    0,
    os.path.normpath(
        os.path.join(
            os.path.dirname( os.path.abspath( __file__ ) ),
            ".."
        )
    )
)
from test_common import (
    my_print,
    setup,
    getTempDir
)

python_version = setup()

# TODO: This ought to no longer be necessary, removing it could highlight bugs.
# No random hashing, it makes comparing outputs futile.
if "PYTHONHASHSEED" not in os.environ:
    os.environ[ "PYTHONHASHSEED" ] = "0"

nuitka_main_path = os.path.join( "..", "..", "bin", "nuitka" )

tmp_dir = getTempDir()

# TODO: Could detect this more automatic.
PACKAGE_LIST = (
    'nuitka',
    'nuitka/nodes',
    'nuitka/tree',
    'nuitka/build',
    'nuitka/freezer',
    'nuitka/gui',
    'nuitka/codegen',
    'nuitka/codegen/templates',
    'nuitka/optimizations',
    'nuitka/finalizations',
)

def diffRecursive( dir1, dir2 ):
    done = set()

    for filename in os.listdir( dir1 ):
        path1 = os.path.join( dir1, filename )
        path2 = os.path.join( dir2, filename )

        done.add( path1 )

        # Skip these binary files of course.
        if filename.endswith( ".o" ) or \
           filename.endswith( ".os" ) or \
           filename.endswith( ".obj" ):
            continue

        # Skip scons build database
        if filename == ".sconsign.dblite":
            continue

        if not os.path.exists( path2 ):
            sys.exit( "Only in %s: %s" % ( dir1, filename ))

        if os.path.isdir( path1 ):
            diffRecursive( path1, path2 )
        elif os.path.isfile( path1 ):
            fromdate = time.ctime( os.stat( path1 ).st_mtime )
            todate = time.ctime( os.stat( path2 ).st_mtime )

            diff = difflib.unified_diff(
                a            = open( path1, "rb" ).readlines(),
                b            = open( path2, "rb" ).readlines(),
                fromfile     = path1,
                tofile       = path2,
                fromfiledate = fromdate,
                tofiledate   = todate,
                n            = 3
            )

            result = list( diff )

            if result:
                for line in result:
                    my_print( line )

                sys.exit( 1 )
        else:
            assert False, path1

    for filename in os.listdir( dir2 ):
        path1 = os.path.join( dir1, filename )
        path2 = os.path.join( dir2, filename )

        if path1 in done:
            continue

        if not os.path.exists( path1 ):
            sys.exit( "Only in %s: %s" % ( dir2, filename ))

def executePASS1():
    my_print( "PASS 1: Compiling from compiler running from .py files." )

    base_dir = os.path.join( "..", ".." )

    for package in PACKAGE_LIST:
        package = package.replace( "/", os.path.sep )

        source_dir = os.path.join( base_dir, package )
        target_dir = package

        if os.path.exists( target_dir ):
            shutil.rmtree( target_dir )

        os.mkdir( target_dir )

        for filename in os.listdir( target_dir ):
            if filename.endswith( ".so" ):
                path = os.path.join( target_dir, filename )

                os.unlink( path )

        for filename in sorted( os.listdir( source_dir ) ):
            if not filename.endswith(".py"):
                continue

            if filename.startswith(".#"):
                continue

            path = os.path.join( source_dir, filename )

            if filename != "__init__.py":
                my_print( "Compiling", path )

                command = [
                    os.environ[ "PYTHON" ],
                    nuitka_main_path,
                    "--module",
                    "--recurse-none",
                    "--output-dir=%s" % target_dir,
                    path
                ]
                command += os.environ.get( "NUITKA_EXTRA_OPTIONS", "" ).split()

                result = subprocess.call(
                    command
                )

                if result != 0:
                    sys.exit( result )
            else:
                shutil.copyfile( path, os.path.join( target_dir, filename ) )


    my_print( "Compiling", nuitka_main_path )

    shutil.copyfile( nuitka_main_path, "nuitka.py" )

    command = [
        os.environ[ "PYTHON" ],
        nuitka_main_path,
        "--recurse-none",
        "--output-dir=.",
        "nuitka.py"
    ]
    command += os.environ.get( "NUITKA_EXTRA_OPTIONS", "" ).split()

    result = subprocess.call(
        command
    )

    if result != 0:
        sys.exit( result )

    scons_inline_copy_path = os.path.join( base_dir, "nuitka", "build", "inline_copy" )

    if os.path.exists( scons_inline_copy_path ):
        shutil.copytree(
            scons_inline_copy_path,
            os.path.join( "nuitka", "build", "inline_copy" )
        )

    shutil.copy(
        os.path.join( base_dir, "nuitka", "build", "SingleExe.scons" ),
        os.path.join( "nuitka", "build", "SingleExe.scons" )
    )
    shutil.copytree(
        os.path.join( base_dir, "nuitka", "build", "static_src" ),
        os.path.join( "nuitka", "build", "static_src" )
    )
    shutil.copytree(
        os.path.join( base_dir, "nuitka", "build", "include" ),
        os.path.join( "nuitka", "build", "include" )
    )

def compileAndCompareWith( nuitka ):
    base_dir = os.path.join( "..", ".." )

    for package in PACKAGE_LIST:
        package = package.replace( "/", os.path.sep )

        source_dir = os.path.join( base_dir, package )

        for filename in sorted( os.listdir( source_dir ) ):
            if not filename.endswith(".py"):
                continue

            if filename.startswith(".#"):
                continue

            path = os.path.join( source_dir, filename )

            if filename != "__init__.py":
                my_print( "Compiling", path )

                target = filename.replace( ".py", ".build" )

                target_dir = os.path.join( tmp_dir, target )

                if os.path.exists( target_dir ):
                    shutil.rmtree( target_dir )

                command = [
                    nuitka,
                    "--module",
                    "--recurse-none",
                    "--output-dir=%s"% tmp_dir,
                    path
                ]
                command += os.environ.get( "NUITKA_EXTRA_OPTIONS", "" ).split()

                result = subprocess.call(
                    command
                )

                if result != 0:
                    sys.exit( result )

                diffRecursive( os.path.join( package, target ), target_dir )

                shutil.rmtree(target_dir)

                if os.name == "nt":
                    target_filename = filename.replace(".py", ".pyd")
                else:
                    target_filename = filename.replace(".py", ".so")

                os.unlink(os.path.join(tmp_dir, target_filename))


def executePASS2():
    my_print( "PASS 2: Compiling from compiler running from .exe and many .so files." )

    # Windows will load the compiled modules (pyd) only from PYTHONPATH, so we
    # have to add it.
    if os.name == "nt":
        os.environ[ "PYTHONPATH" ] = ":".join( PACKAGE_LIST )

    compileAndCompareWith( os.path.join( ".", "nuitka.exe" ) )

    # Undo the damage from above.
    if os.name == "nt":
        del os.environ[ "PYTHONPATH" ]

    my_print( "OK." )

def executePASS3():
    my_print( "PASS 3: Compiling from compiler running from .py files to single .exe." )

    exe_path = os.path.join( tmp_dir, "nuitka.exe" )

    if os.path.exists( exe_path ):
        os.unlink( exe_path )

    build_path = os.path.join( tmp_dir, "nuitka.build" )

    if os.path.exists( build_path ):
        shutil.rmtree( build_path )

    path = os.path.join( "..", "..", "bin", "nuitka" )

    my_print( "Compiling", path )

    command = [
        os.environ[ "PYTHON" ],
        nuitka_main_path,
        path,
        "--output-dir=%s" % tmp_dir,
        "--exe",
        "--recurse-all"
    ]
    result = subprocess.call(
        command
    )

    if result != 0:
        sys.exit( result )

    shutil.rmtree( build_path )

    my_print( "OK." )

def executePASS4():
    my_print( "PASS 4: Compiling the compiler running from single exe" )

    exe_path = os.path.join( tmp_dir, "nuitka.exe" )

    compileAndCompareWith( exe_path )

    my_print( "OK." )

def executePASS5():
    my_print( "PASS 5: Compiling the compiler 'nuitka' package to a single '.so' file." )

    path = os.path.join( "..", "..", "nuitka" )

    command = [
        os.environ[ "PYTHON" ],
        nuitka_main_path,
        path,
        "--output-dir=%s" % tmp_dir,
        "--recurse-all",
        "--recurse-dir=%s" % path,
        "--module",
        path

    ]
    result = subprocess.call(
        command
    )

    if result != 0:
        sys.exit( result )

    os.unlink( os.path.join( tmp_dir, "nuitka.so" ) )
    shutil.rmtree( os.path.join( tmp_dir, "nuitka.build" ) )

cross_compilation = "--windows-target" in os.environ.get( "NUITKA_EXTRA_OPTIONS", "" )

executePASS1()

if cross_compilation:
    my_print( "PASS 2: Skipped for cross-compilation case." )
else:
    executePASS2()
executePASS3()

if cross_compilation:
    my_print( "PASS 4: Skipped for cross-compilation case." )
else:
    executePASS4()

shutil.rmtree( "nuitka" )

executePASS5()

os.unlink(os.path.join(tmp_dir, "nuitka.exe" ))
os.rmdir(tmp_dir)
