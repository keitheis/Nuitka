#     Copyright 2014, Kay Hayen, mailto:kay.hayen@gmail.com
#
#     Part of "Nuitka", an optimizing Python compiler that is compatible and
#     integrates with CPython, but also works on its own.
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

from .ErrorCodes import (
    getErrorExitBoolCode,
    getErrorExitCode,
    getReleaseCodes,
    getReleaseCode
)

def getSliceLookupCode(to_name, source_name, lower_name, upper_name, emit,
                       context):
    emit(
        "%s = LOOKUP_SLICE( %s, %s, %s );" % (
            to_name,
            source_name,
            lower_name if lower_name is not None else "Py_None",
            upper_name if upper_name is not None else "Py_None"
        )
    )

    getReleaseCodes(
        release_names = (source_name, lower_name, upper_name),
        emit          = emit,
        context       = context
    )

    getErrorExitCode(
        check_name = to_name,
        emit       = emit,
        context    = context
    )

    context.addCleanupTempName(to_name)


def getSliceLookupIndexesCode(to_name, lower_name, upper_name, source_name,
                              emit, context):
    emit(
        "%s = LOOKUP_INDEX_SLICE( %s, %s, %s );" % (
            to_name,
            source_name,
            lower_name,
            upper_name,
        )
    )

    getReleaseCode(
        release_name = source_name,
        emit         = emit,
        context      = context
    )

    getErrorExitCode(
        check_name = to_name,
        emit       = emit,
        context    = context
    )

    context.addCleanupTempName(to_name)


def getSliceObjectCode(to_name, lower_name, upper_name, step_name, emit,
                       context):
    emit(
        "%s = MAKE_SLICEOBJ( %s, %s, %s );" % (
            to_name,
            lower_name if lower_name is not None else "Py_None",
            upper_name if upper_name is not None else "Py_None",
            step_name if step_name is not None else "Py_None",
        )
    )

    getReleaseCodes(
        release_names = (lower_name, upper_name, step_name),
        emit          = emit,
        context       = context
    )

    # Note: Cannot fail

    context.addCleanupTempName(to_name)


def getSliceAssignmentIndexesCode(target_name, lower_name, upper_name,
                                  value_name, emit, context):
    res_name = context.getIntResName()

    emit(
        """%s = PySequence_SetSlice( %s, %s, %s, %s );""" % (
            res_name,
            target_name,
            lower_name,
            upper_name,
            value_name
        )
    )

    getReleaseCodes(
        release_names = (value_name, target_name),
        emit          = emit,
        context       = context
    )

    getErrorExitBoolCode(
        condition       = "%s == -1" % res_name,
        quick_exception = None,
        emit            = emit,
        context         = context
    )


def getSliceAssignmentCode(target_name, lower_name, upper_name, value_name,
                           emit, context):
    res_name = context.getBoolResName()

    emit(
        "%s = SET_SLICE( %s, %s, %s, %s );" % (
            res_name,
            target_name,
            lower_name if lower_name is not None else "Py_None",
            upper_name if upper_name is not None else "Py_None",
            value_name
        )
    )

    getReleaseCodes(
        release_names = (target_name, lower_name, upper_name, value_name),
        emit          = emit,
        context       = context
    )

    getErrorExitBoolCode(
        condition = "%s == false" % res_name,
        emit      = emit,
        context   = context
    )


def getSliceDelCode(target_name, lower_name, upper_name, emit, context):
    res_name = context.getBoolResName()

    emit(
        "%s = DEL_SLICE( %s, %s, %s );" % (
            res_name,
            target_name,
            lower_name,
            upper_name
        )
    )

    getReleaseCode(
        release_name = target_name,
        emit         = emit,
        context      = context
    )

    getErrorExitBoolCode(
        condition = "%s == false" % res_name,
        emit      = emit,
        context   = context
    )
