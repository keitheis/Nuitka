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
""" Code to generate and interact with compiled module objects.

"""

from .ConstantCodes import (
    getConstantCode,
)

from .VariableCodes import (
    getLocalVariableInitCode,
)

from .Indentation import indented

from . import CodeTemplates

from nuitka import Options, Utils

import re

def getModuleAccessCode(context):
    return "module_%s" % context.getModuleCodeName()

def getModuleIdentifier(module_name):
    # TODO: This is duplication with ModuleNode.getCodeName, remove it.
    def r(match):
        c = match.group()
        if c == '.':
            return "$"
        else:
            return "$$%d$" % ord(c)

    return "".join(re.sub("[^a-zA-Z0-9_]", r ,c) for c in module_name)

def getModuleDeclarationCode(module_name, extra_declarations):
    module_header_code = CodeTemplates.module_header_template % {
        "module_identifier"  : getModuleIdentifier( module_name ),
        "extra_declarations" : extra_declarations
    }

    return CodeTemplates.template_header_guard % {
        "header_guard_name" : "__%s_H__" % getModuleIdentifier(module_name),
        "header_body"       : module_header_code
    }

def getModuleMetapathLoaderEntryCode(module_name, is_shlib):
    if is_shlib:
        return CodeTemplates.template_metapath_loader_shlib_module_entry % {
            "module_name" : module_name
        }
    else:
        return CodeTemplates.template_metapath_loader_compiled_module_entry % {
            "module_name"       : module_name,
            "module_identifier" : getModuleIdentifier( module_name ),
        }


def getModuleCode( context, module_name, codes, metapath_loader_inittab,
                   function_decl_codes, function_body_codes, temp_variables ):
    # For the module code, lots of attributes come together.
    # pylint: disable=R0914
    module_identifier = getModuleIdentifier(module_name)

    header = CodeTemplates.global_copyright % {
        "name"    : module_name,
        "version" : Options.getVersion()
    }

    # Temp local variable initializations
    local_var_inits = [
        getLocalVariableInitCode(
            context  = context,
            variable = variable
        )
        for variable in
        temp_variables
    ]

    if context.needsExceptionVariables():
        local_var_inits += [
            "PyObject *exception_type, *exception_value;",
            "PyTracebackObject *exception_tb;"
        ]

    for keeper_variable in range(1, context.getKeeperVariableCount()+1):
        # For finally handlers of Python3, which have conditions on assign and
        # use.
        if Options.isDebug() and Utils.python_version >= 300:
            keeper_init = " = NULL";
        else:
            keeper_init = ""

        local_var_inits += [
            "PyObject *exception_keeper_type_%d%s;" % (
                keeper_variable,
                keeper_init
            ),
            "PyObject *exception_keeper_value_%d%s;" % (
                keeper_variable,
                keeper_init
            ),
            "PyTracebackObject *exception_keeper_tb_%d%s;" % (
                keeper_variable,
                keeper_init
            )
        ]

    local_var_inits += [
        "%s%s%s;" % (
            tmp_type,
            " " if not tmp_type.endswith("*") else "",
            tmp_name
        )
        for tmp_name, tmp_type in
        context.getTempNameInfos()
    ]

    if context.needsExceptionVariables():
        module_exit = CodeTemplates.template_module_exception_exit
    else:
        module_exit = CodeTemplates.template_module_noexception_exit

    module_code = CodeTemplates.module_body_template % {
        "module_name"           : module_name,
        "module_name_obj"       : getConstantCode(
            context  = context,
            constant = module_name
        ),
        "module_identifier"       : module_identifier,
        "module_functions_decl"   : function_decl_codes,
        "module_functions_code"   : function_body_codes,
        "temps_decl"              : indented(local_var_inits),
        "module_code"             : indented(codes),
        "module_exit"             : module_exit,
        "metapath_loader_inittab" : indented(
            sorted(metapath_loader_inittab)
        ),
        "use_unfreezer"           : 1 if metapath_loader_inittab else 0

    }

    return header + module_code
